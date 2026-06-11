---
create_time: 2026-06-11 10:32:16
status: wip
prompt: sdd/prompts/202606/publish_sase_015_to_pypi.md
---
# Plan: Dispatch publish.yml to Release sase 0.1.5 to PyPI and Verify

## Goal

Execute the rollout step of the approved `sase_pypi_015_trusted_publishing` plan: manually dispatch the renamed
`publish.yml` workflow so the already-released v0.1.5 is built, smoke-tested, and published to PyPI via trusted
publishing, then verify the release is live at https://pypi.org/project/sase/.

This is an operational task — no repository file changes are needed (the only file created is this plan).

## Pre-flight State (verified live)

- The workflow fix commit `064e9bffc` ("chore: configure PyPI publish workflow") is on `origin/master`, and the
  `Publish` workflow is active on GitHub. Recent push-triggered runs complete in ~15s with success — these are the
  expected no-op runs (release-please reports `release_created=false`, build/publish skip).
- `.github/workflows/publish.yml` on master has the guarded `workflow_dispatch` input `publish_existing` (boolean,
  default false). `build` and `publish` run when `publish_existing == true`; `publish` uses `environment: pypi` with
  `id-token: write`.
- PyPI currently serves only `sase==0.1.0` (checked via `https://pypi.org/pypi/sase/json`).
- Master version files all report `0.1.5`: `.release-please-manifest.json`, `pyproject.toml`, `src/sase/__init__.py`.
- `git diff v0.1.5 origin/master -- src/ pyproject.toml README.md` is empty, so a build from master HEAD produces a
  package identical in content to tag `v0.1.5`. Building from master is therefore safe and matches the approved plan.

## Steps

1. **Dispatch the manual publish path** (exactly as the approved plan specifies):

   ```bash
   gh workflow run publish.yml -R sase-org/sase -f publish_existing=true
   ```

   This runs on the default branch (`master`), so the OIDC token presents
   `job_workflow_ref: sase-org/sase/.github/workflows/publish.yml@refs/heads/master` with `environment: pypi` — matching
   the configured trusted publisher exactly.

2. **Watch the run to completion.** Find the new run with
   `gh run list -R sase-org/sase --workflow=publish.yml --limit 3` (filter for `workflow_dispatch` event), then follow
   it with `gh run watch <run-id> -R sase-org/sase --exit-status`. Expected job flow: release (skipped step, outputs
   `release_created=false`) → build (uv build + twine check) → install-smoke (fresh-venv wheel install,
   `sase core health`, `sase version`, doctor + help smoke) → publish (OIDC token exchange, upload). If the `pypi`
   environment requires a manual approval, surface that to the user rather than waiting indefinitely.

3. **Verify on PyPI.** Poll `https://pypi.org/pypi/sase/json` until `info.version == "0.1.5"` and `0.1.5` appears in
   `releases` (allow a few retries for CDN cache). Also confirm the project page `https://pypi.org/project/sase/` shows
   0.1.5.

4. **Independent install smoke (final confirmation).** In a throwaway venv outside the repo:
   `uv venv /tmp/sase-015-verify && uv pip install --python /tmp/sase-015-verify/bin/python sase==0.1.5`, then run
   `/tmp/sase-015-verify/bin/sase version` and `/tmp/sase-015-verify/bin/sase core health --json`. Clean up the venv
   afterwards.

## Contingencies

- **`invalid-publisher` again**: capture the rendered OIDC claims from the failed publish job log and compare against
  the publisher config (repo `sase-org/sase`, workflow `publish.yml`, environment `pypi`). Any remaining mismatch is not
  fixable repo-side — stop and report the exact claims.
- **Duplicate/existing-file error from PyPI**: check whether 0.1.5 partially uploaded (PyPI files are immutable) and
  report the file list before any retry.
- **build/install-smoke failure**: report the failing job log; do not retry the dispatch blindly since the same master
  HEAD would fail identically.
- **Run not visible immediately after dispatch**: `gh workflow run` is async; retry the run-list lookup for a few
  seconds before concluding the dispatch failed.

## Out of Scope

- Backfilling 0.1.3/0.1.4 (intentionally skipped per the approved plan).
- Stale-run guards, tag-based builds, release-PR auto-merge (tracked in
  `sdd/research/202606/direct_master_pypi_releases_consolidated.md`).
