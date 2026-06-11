---
create_time: 2026-06-11 10:48:14
status: done
prompt: sdd/prompts/202606/publish_sase_github_011_to_pypi.md
---
# Plan: Fix sase-github Trusted Publisher Mismatch and Publish 0.1.1 to PyPI

## Goal

Diagnose why the `sase-org/sase-github` publish workflow cannot upload to PyPI, fix the root cause, publish the
appropriate next version (**0.1.1** — already released via release-please on GitHub but never delivered to PyPI), and
verify the release the same way the `sase==0.1.5` release was verified (watch the workflow run, poll the PyPI JSON API,
then do an independent throwaway-venv install smoke).

## Investigation Findings (verified live)

**Root cause: the PyPI trusted publisher for `sase-github` points at a repository that no longer exists.**

- PyPI serves only `sase-github==0.1.0` (uploaded 2026-02-23). The attestation/provenance certificate for the 0.1.0
  wheel (via `https://pypi.org/integrity/...`) shows it was published from
  `bbugyi200/sase-github/.github/workflows/publish.yml@refs/tags/v0.1.0` with `environment: pypi`.
- The current repo `sase-org/sase-github` was created **2026-03-14** (after 0.1.0 shipped), and `bbugyi200/sase-github`
  now returns 404 (no transfer redirect — the old repo is gone). PyPI trusted publishers match on the configured
  owner/repo (and owner ID), so **no claims from `sase-org/sase-github` can ever match the stale publisher**.
- This explains both 2026-06-09 failures, which were misdiagnosed as a workflow-filename problem at the time:
  - Run `27236430385` (push, workflow at `publish.yml`): `invalid-publisher`, claims showed
    `sase-org/sase-github/.github/workflows/publish.yml@refs/heads/master`, env `pypi`.
  - Run `27236626542` (dispatch, after commit `6a9fea0` renamed the workflow to `release.yml` hoping to match the old
    config): `invalid-publisher` again, claims showed `.../release.yml@refs/heads/master`, env `pypi`.
  - Both filename variants failed identically because the publisher's **repository owner** is wrong, not the filename.
- Version state: master `pyproject.toml` = `0.1.1`, tag `v0.1.1` and GitHub release exist,
  `git diff v0.1.1 master -- src/ pyproject.toml README.md` is empty (the only post-tag commits touch workflows and
  release-please config), so building from master HEAD yields content identical to the v0.1.1 tag. An open
  release-please PR (#2) for 0.1.2 exists and should stay open — 0.1.1 is the version stuck in the pipeline.
- The current workflow (`release.yml` on master) is the hardened publish workflow: release-please → build →
  install-smoke → publish (trusted publishing, `environment: pypi`), with a `workflow_dispatch` input `publish_existing`
  that gates build+publish for recovery — the same pattern used for `sase==0.1.5`.
- Build preflight (local `uv build` to /tmp): wheel 18 KB, sdist 112 KB, 36 files in the sdist — **no** PyPI 100 MB
  file-size risk (the failure mode that bit the `sase` sdist does not apply here).
- The repo already has a `pypi` GitHub environment, and the sibling `sase` repo's working setup uses
  `.github/workflows/publish.yml` + environment `pypi` + publisher repo `sase-org/sase`.

## Steps

1. **Rename the workflow back to `publish.yml`** (one small commit to `sase-org/sase-github` master):
   - `git mv .github/workflows/release.yml .github/workflows/publish.yml` — reverts the misdiagnosed `6a9fea0` rename
     and restores parity with the `sase` repo, so every sase-org package converges on `publish.yml` + env `pypi`.
   - Generalize the hardcoded dispatch-input description ("Publish the existing 0.1.1 release artifacts" → "Publish the
     existing release artifacts for the version on master").
   - Commit via the sase commit flow and push to master. The push-triggered run will be a release-please no-op
     (`release_created=false`, build/publish skip) — sanity-check it goes green.

2. **User action (blocking, cannot be done by the agent): fix the trusted publisher on pypi.org.** In the `sase-github`
   project's Publishing settings (as `bbugyi200`):
   - Remove the stale publisher pointing at `bbugyi200/sase-github` (if still listed).
   - Add a GitHub publisher with exactly: owner `sase-org`, repository `sase-github`, workflow `publish.yml`,
     environment `pypi`. I will request this via a sase question and wait for confirmation before dispatching.

3. **Dispatch the recovery publish path**:

   ```bash
   gh workflow run publish.yml -R sase-org/sase-github -f publish_existing=true
   ```

   This runs on master, presenting
   `job_workflow_ref: sase-org/sase-github/.github/workflows/publish.yml@refs/heads/master` with `environment: pypi` —
   matching the newly configured publisher exactly.

4. **Watch the run to completion** (`gh run list` to find it, `gh run watch <id> --exit-status`). Expected: release job
   skips → build (`uv build`) → install-smoke (fresh venv, wheel install against sase-core ref, entry-point
   verification) → publish (OIDC exchange, upload of wheel + sdist).

5. **Verify on PyPI** (same method as sase 0.1.5): poll `https://pypi.org/pypi/sase-github/json` until
   `info.version == "0.1.1"` with both files present in `releases["0.1.1"]`; confirm
   https://pypi.org/project/sase-github/0.1.1/ is live and shows trusted-publishing provenance.

6. **Independent install smoke** in a throwaway venv outside the repo:
   `uv venv /tmp/sase-github-011-verify && uv pip install --python /tmp/sase-github-011-verify/bin/python sase-github==0.1.1`
   (pulls `sase>=0.1.0` from PyPI — now satisfiable with the 0.1.5 wheel), then verify
   `importlib.metadata.version("sase-github") == "0.1.1"` and that the four plugin entry points (`sase_vcs`,
   `sase_workspace`, `sase_config`, `sase_xprompts`) resolve to the `sase_github` module, mirroring the workflow's smoke
   check. Clean up the venv afterwards.

## Contingencies

- **`invalid-publisher` again after the publisher is reconfigured**: capture the rendered claims from the failed run and
  diff field-by-field against the configured publisher (owner/repo/workflow/environment are all in the claims). If they
  match yet exchange still fails, stop and report — that would indicate a PyPI-side issue.
- **Partial upload (one file accepted, one rejected)**: PyPI files are immutable; report the exact file list under
  `releases["0.1.1"]` before any retry. Size preflight makes this unlikely (largest file 112 KB).
- **build/install-smoke failure**: report the failing job log; do not re-dispatch blindly since master HEAD would fail
  identically.
- **Environment approval gate**: if the `pypi` environment requires manual approval, surface it rather than waiting
  indefinitely.

## Out of Scope

- Merging release PR #2 (0.1.2) — stays open; once the publisher is fixed, the normal merge → push-triggered publish
  path will work for future releases.
- `sase-telegram` PyPI publishing (still 404 on PyPI; needs its own workflow + publisher setup).
- Fixing the oversized `sase` sdist left over from the 0.1.5 release (separate repo, separate task).
