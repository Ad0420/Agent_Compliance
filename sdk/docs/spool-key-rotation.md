# Spool key rotation and recovery

The durable spool encrypts every record at rest with AES-256-GCM, keyed off
the `VERA_SPOOL_KEY` env var (passed through PBKDF2-HMAC-SHA256 with 200k
iterations). The encryption key cannot be changed in place — there is no
re-key-on-the-fly path. This document covers the supported rotation
procedure and the recovery procedure when an operator changes the key
without migrating first.

## Detecting a key-rotation incident

After any operation that involves the spool (process startup, dequeue,
rehydrate), look for the following log line:

```
vera.client: SPOOL DECRYPTION FAILURE — N row(s) moved to quarantine ...
```

This fires exactly once per process. The rows that failed to decrypt are
NOT deleted — they are moved (in a single transaction) into the
`spool_quarantine_records` table. The original `spool_records` table loses
the affected ids only after the quarantine insert commits successfully.

You can also poll the spool programmatically:

```python
from vera.spool import Spool
s = Spool("/var/lib/vera/spool.db", passphrase=os.environ["VERA_SPOOL_KEY"])
if s.quarantine_size() > 0:
    for row in s.list_quarantined():
        print(row)
```

`list_quarantined()` returns metadata only — the ciphertext is not exposed
because it cannot be decrypted with the current key.

## Recovery procedure

### Case 1: you still have the previous passphrase

This is the recoverable case. The audit chain is preserved; you just need
to round-trip the rows through the old key.

1. Stop all writers that target this spool path. Do not start any client
   with the new passphrase until you finish step 4.

2. Open the spool with the **previous** passphrase from a one-off Python
   shell. Dequeue the quarantined rows by reading the `payload_ciphertext`
   and `payload_nonce` columns directly:

   ```python
   import sqlite3, json
   from cryptography.hazmat.primitives.ciphers.aead import AESGCM
   from cryptography.hazmat.primitives import hashes
   from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

   # Read the salt the spool was initialised with.
   conn = sqlite3.connect("/var/lib/vera/spool.db")
   salt_hex = conn.execute(
       "SELECT value FROM spool_metadata WHERE key='salt_hex'"
   ).fetchone()[0]
   salt = bytes.fromhex(salt_hex)

   # Derive the OLD key.
   old_key = PBKDF2HMAC(
       algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000
   ).derive(b"<OLD_PASSPHRASE_HERE>")

   aes = AESGCM(old_key)
   rows = conn.execute(
       "SELECT id, payload_ciphertext, payload_nonce FROM spool_quarantine_records"
   ).fetchall()
   recovered = []
   for row_id, ct, nonce in rows:
       plaintext = aes.decrypt(nonce, ct, associated_data=None)
       record = json.loads(plaintext.decode("utf-8"))
       recovered.append((row_id, record))
   conn.close()
   ```

3. Re-enqueue the recovered records into a fresh spool initialised with
   the new passphrase. Use a separate path (e.g. `spool.db.new`) so you
   don't have to coordinate ownership of the file in the same step:

   ```python
   import os
   from vera.spool import Spool
   os.environ["VERA_SPOOL_KEY"] = "<NEW_PASSPHRASE_HERE>"
   s = Spool("/var/lib/vera/spool.db.new", passphrase=os.environ["VERA_SPOOL_KEY"])
   for _, record in recovered:
       s.enqueue(record)
   s.close()
   ```

4. Swap the file paths atomically (`mv spool.db spool.db.old && mv
   spool.db.new spool.db`). Restart the SDK clients.

5. Verify `quarantine_size() == 0` and that the regular `size()` count
   matches expectations. Once you've confirmed the new spool is intact,
   delete `spool.db.old`.

### Case 2: the previous passphrase is lost

This is the unrecoverable case. The ciphertext in
`spool_quarantine_records` cannot be decrypted by anyone. You have two
choices:

* **Accept the loss explicitly.** Document the incident, count the lost
  rows from `quarantine_size()`, then `DELETE FROM spool_quarantine_records`
  to free the disk. The audit chain has a hole; report it to your
  compliance team.

* **Cold-storage the quarantine table.** `pg_dump`/`sqlite3 .dump` the
  quarantine rows into a separate immutable file and keep them on cold
  storage in case the previous passphrase is recovered later (rare but
  possible — e.g. it was held in a now-restored backup).

The SDK will not auto-delete quarantined rows. Disk pressure from a large
quarantine table will eventually trip `max_bytes` on the spool itself
(remember, both tables live in the same SQLite file). Plan a cleanup
window if quarantine growth becomes a problem.

## Supported planned rotation

If you want to rotate the passphrase deliberately (e.g. annual key
rotation policy), follow this sequence:

1. Drain the spool first. Point all writers at a healthy backend and wait
   until `Spool(...).size() == 0` and the in-memory queues are empty
   (call `client.close()` on each writer).

2. Move the spool file aside (rename it). The next process to start with
   the new `VERA_SPOOL_KEY` will create a fresh empty spool with a new
   salt — no decryption needed because there are no existing rows.

3. Confirm new-key writes work, then delete the moved-aside file.

This is the cheap path: it does not require running the recovery
procedure. If your audit-chain SLO does not permit a quiescent window for
draining, use the Case 1 recovery procedure above instead.

## Why there is no in-place rotation

In-place re-encryption would require holding both the old and new keys
during a multi-second cursor over every row. The threat model for the
spool is "compliance team finds a copy of the file on a backup disk." A
re-key pass that briefly holds the old key in memory does not change that
threat model meaningfully, but the rotation path is rare enough (annual
or less) that the operational simplicity of the documented procedure
outweighs the convenience of an in-place CLI. We may add a `vera-spool
rotate-key` command in a future release if customer demand justifies it.
