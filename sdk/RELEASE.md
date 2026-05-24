# SDK release runbook

This runbook documents the **human** steps a maintainer with PyPI
publish credentials runs at merge time. It is NOT executed by CI —
PyPI publish is a manual gate by design.

When Phase 1 PR 10 merges to `main`, run BOTH releases below from the
same merge commit. Cut `0.3.1` first (final 0.3-line patch) so pilots
who pin `vera-sdk>=0.3,<1` get the `DeprecationWarning` immediately,
then cut `1.0.0`.

## Prerequisites

* Push access to the GitHub repository (for tagging).
* PyPI credentials configured for `twine` (either `~/.pypirc` or
  `TWINE_USERNAME` / `TWINE_PASSWORD` env vars). Trusted-publisher
  (OIDC) flow is preferred if you've configured it for the project.
* `python -m build` available locally (`pip install build twine`).
* The working tree clean and at the merge commit:
  ```bash
  git checkout main
  git pull --ff-only origin main
  git log --oneline -1  # should be the Phase 1 PR 10 merge commit
  git status            # should be clean
  ```

## Step 1: Tag and publish `0.3.1` (deprecation patch)

`0.3.1` is the final 0.3-line release. It ships the
`DeprecationWarning` on `@vera.audit` (already committed via PR #203)
and nothing else functional — pilots pinned `>=0.3,<1` get the
warning, then migrate at their own pace.

**`main` carries version `1.0.0` in `pyproject.toml` / `setup.py`.**
For the 0.3.1 cut, temporarily flip the version in those two files,
build, upload, then revert. Don't commit the flip — the tag is what
matters.

```bash
# From the repo root, at the merge commit on main:

# 1. Tag the merge commit BEFORE flipping version files. The tag
#    points at the merge commit; the wheel built from the temp-flipped
#    files just happens to be uploaded under the 0.3.1 name.
git tag -a v0.3.1 -m "vera-sdk 0.3.1 — DeprecationWarning on @vera.audit"

# 2. Flip version in pyproject.toml and setup.py to 0.3.1. Use sed or
#    just edit manually — both occurrences of "1.0.0" → "0.3.1".
sed -i.bak 's/version = "1.0.0"/version = "0.3.1"/' sdk/pyproject.toml
sed -i.bak 's/version="1.0.0"/version="0.3.1"/' sdk/setup.py

# 3. Build from the SDK directory.
cd sdk
rm -rf dist/ build/ *.egg-info
python -m build  # produces dist/vera_sdk-0.3.1-py3-none-any.whl + .tar.gz

# 4. Verify the build artifacts have the right version.
ls dist/  # should show vera_sdk-0.3.1-*

# 5. Upload to PyPI (use --repository testpypi first if you want a
#    dry-run on test.pypi.org).
twine upload dist/vera_sdk-0.3.1*

# 6. Revert the version flip — DO NOT COMMIT the temp change.
cd ..
mv sdk/pyproject.toml.bak sdk/pyproject.toml
mv sdk/setup.py.bak sdk/setup.py
rm -rf sdk/dist sdk/build sdk/*.egg-info
git status  # should be clean again

# 7. Push the tag.
git push origin v0.3.1
```

## Step 2: Tag and publish `1.0.0` (stable cut)

`1.0.0` is the version `main` already points at — no version flip
needed.

```bash
# Still at the merge commit on main:

git tag -a v1.0.0 -m "vera-sdk 1.0.0 — first stable release"

cd sdk
rm -rf dist/ build/ *.egg-info
python -m build  # produces dist/vera_sdk-1.0.0-*
ls dist/         # verify 1.0.0 artifacts

twine upload dist/vera_sdk-1.0.0*

cd ..
git push origin v1.0.0
```

## Step 3: Smoke-test the published wheels

Run in a throwaway venv to catch any packaging bug before pilots hit
it.

```bash
# 0.3.1 smoke test
python -m venv /tmp/vera-031-smoke && source /tmp/vera-031-smoke/bin/activate
pip install --upgrade pip
pip install vera-sdk==0.3.1
python -c "import vera; from vera import audit; print('0.3.1 ok')"
deactivate && rm -rf /tmp/vera-031-smoke

# 1.0.0 smoke test
python -m venv /tmp/vera-100-smoke && source /tmp/vera-100-smoke/bin/activate
pip install --upgrade pip
pip install vera-sdk==1.0.0
python -c "from vera import gate, audit, PolicyBlock, PendingReview, init; print('1.0.0 ok')"
vera --version  # should print 'vera, version 1.0.0'

# codemod extra
pip install 'vera-sdk[codemod]==1.0.0'
python -c "from vera.codemod import AuditToGateTransformer; print('codemod extra ok')"
deactivate && rm -rf /tmp/vera-100-smoke
```

## Step 4: Announce

* Update the pilot channel with the release notes (lift from
  `sdk/CHANGELOG.md::[1.0.0]`).
* If you maintain a `RELEASES` section on the dashboard / docs site,
  bump it to point at `1.0.0`.
* Direct-message any pilot still pinned `<0.3` to migrate to `0.3.1`
  on their own timeline (the `DeprecationWarning` will guide them).

## Step 5: Verify the GitHub release page

* https://github.com/Ad0420/Agent_Compliance/releases — both tags
  should appear.
* Optionally upload the `dist/*` artifacts to the GitHub release for
  archival (PyPI is the canonical source).

## Rollback plan

If a published wheel turns out to be broken:

1. **Do NOT delete the PyPI release** — PyPI rejects re-uploads of the
   same version + filename. You'd be permanently locked out of that
   version number.
2. **Cut a new patch** instead. Bump to `0.3.2` / `1.0.1`, fix the
   bug, repeat steps 1–4 above for the new version.
3. If the bug is severe (data corruption, security), yank the broken
   version on PyPI (`pip install -i ...` will refuse to install
   yanked versions by default but they remain resolvable for users
   who already pinned them).

## Notes for future releases

* `0.3.x` is a permanent dead-end after `0.3.1`. Bug-fix backports to
  the 0.3 line would require maintaining a `release-0.3` branch; the
  current convention is "1.x or upgrade." Document any exception
  here when it happens.
* Each minor bump (`1.x → 1.(x+1)`) follows the same flow minus the
  `0.3.x` step. Just tag + build + upload + smoke from `main`.
* Each major bump (`1.x → 2.0.0`) needs a new MIGRATION.md section
  before the release commit lands. `@vera.audit` removal is scheduled
  for 2.0.0 per the `removed_in="2.0.0"` annotation in
  `sdk/vera/decorator.py::_AUDIT_DEPRECATION_MESSAGE`.
