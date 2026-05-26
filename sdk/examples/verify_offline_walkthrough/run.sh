#!/usr/bin/env bash
# Orchestrates the offline-verify walkthrough end-to-end:
#   1. Build a fixture evidence bundle.
#   2. Verify it offline (HMAC mode — secret supplied via env var).
#   3. Tamper with the bundle and re-verify to confirm the verifier
#      catches the change (exit 1).
#
# Exits 0 only if both the happy path AND the tamper-detection step
# behave as expected. Anything else surfaces non-zero so CI / shell
# pipelines flag the regression immediately.

set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WORK="$(mktemp -d -t vera_walkthrough.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

BUNDLE="$WORK/bundle.tar.gz"
# The HMAC secret here MUST match the one baked into produce_bundle.py.
# In production, this comes from your secrets manager — never check it in.
export VERA_HMAC_SECRET="walkthrough-demo-secret-do-not-use-in-production"

echo "[1/3] producing bundle at $BUNDLE..."
python3 "$HERE/produce_bundle.py" --out "$BUNDLE" >/dev/null

echo "[2/3] verifying bundle (happy path)..."
python3 "$HERE/verify_bundle.py" "$BUNDLE"

echo "[3/3] tampering with bundle and confirming verifier rejects..."
TAMPER_DIR="$WORK/tamper"
mkdir -p "$TAMPER_DIR"
tar -xzf "$BUNDLE" -C "$TAMPER_DIR"
# Flip one byte in a record's leaf_hash. Picks the first hex digit and
# rotates it through 0..9a..f → an obviously different value.
FIRST_RECORD="$(ls "$TAMPER_DIR/records/" | head -n1)"
python3 - <<PY
import json
from pathlib import Path
p = Path("$TAMPER_DIR/records/$FIRST_RECORD")
data = json.loads(p.read_text())
orig = data["leaf_hash"]
flip = "f" if orig[0] != "f" else "0"
data["leaf_hash"] = flip + orig[1:]
p.write_text(json.dumps(data, indent=2, sort_keys=True))
PY
TAMPERED_BUNDLE="$WORK/bundle_tampered.tar.gz"
( cd "$TAMPER_DIR" && tar -czf "$TAMPERED_BUNDLE" . )

if python3 "$HERE/verify_bundle.py" "$TAMPERED_BUNDLE"; then
    echo "FAIL: verifier did NOT reject tampered bundle" >&2
    exit 1
fi
echo "OK: verifier correctly rejected the tampered bundle"

echo
echo "walkthrough complete — happy path and tamper detection both behaved as expected."
