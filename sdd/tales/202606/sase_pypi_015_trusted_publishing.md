---
create_time: 2026-06-11 07:53:50
status: done
prompt: sdd/prompts/202606/sase_pypi_015_trusted_publishing.md
---
# Plan: Fix PyPI Trusted Publishing for sase and Release 0.1.5

## Root Cause

The PR #164 merge run built and smoke-tested the 0.1.5 artifacts successfully, but the PyPI token exchange failed with
`invalid-publisher`. The OIDC claims from the failed job tell the whole story:

- `job_workflow_ref`: `sase-org/sase/.github/workflows/release.yml@refs/heads/master`
- `sub`: `repo:sase-org/sase:environment:pypi`

The trusted publisher configured on PyPI is:

- Repository: `sase-org/sase`
- Workflow: `publish.yml`
- Environment name: `pypi`

PyPI looks up GitHub trusted publishers by the workflow **filename** embedded in the `job_workflow_ref` claim. Our
publish job lives in `.github/workflows/release.yml`, so the token presents `release.yml`, no publisher matches, and
PyPI refuses the exchange. Repository, owner, and environment all already match; the workflow filename is the only
mismatch.

This is the identical failure `sase-telegram` hit for its 0.1.0 release (see `sase_plan_sase_telegram_pypi_010.md`).
That repo's fix — rename `release.yml` to `publish.yml` and add a guarded manual-publish path — is already live in
`sase-org/sase-telegram` and is the precedent to mirror here.

## Why a Rename Alone Is Not Enough

- Re-running the failed run cannot work: re-runs execute the workflow file from the original commit, which still
  presents the `release.yml` claim.
- The GitHub release/tag `v0.1.5` already exists, so after the rename lands, release-please will report
  `release_created=false` on subsequent pushes and the build/smoke/publish jobs would skip forever for 0.1.5.
- Therefore the workflow also needs a guarded `workflow_dispatch` path that can build, smoke-test, and publish the
  already-released version.

Current PyPI state (verified live): only `sase==0.1.0` exists; 0.1.3 and 0.1.4 were never published either. Publishing
0.1.5 brings PyPI current — there is no need to backfill the intermediate versions.

## Implementation

1. `git mv .github/workflows/release.yml .github/workflows/publish.yml` and change the workflow display name from
   `Release` to `Publish`, mirroring sase-telegram.

2. Add a guarded manual-publish input, matching the sase-telegram pattern:
   - `workflow_dispatch` input `publish_existing` (boolean, required, default `false`) with a version-agnostic
     description (e.g. "Publish the existing release version recorded on master").
   - `release` job: run the release-please step only on `push` events; expose
     `release_created: ${{ steps.release.outputs.release_created || 'false' }}`.
   - `build` and `publish` jobs: condition becomes
     `release_created == 'true' || (github.event_name == 'workflow_dispatch' && inputs.publish_existing == true)`.
   - `install-smoke` stays gated through `needs: build` as today.

3. Change nothing else: keep all build/twine-check/smoke/diagnostic steps, keep `environment: pypi` and
   `id-token: write` scoped to the publish job only.

## Validation (before pushing)

- `actionlint` on the renamed workflow, if available.
- `just install` then `just check` (required for file changes in this repo).
- Confirm `.release-please-manifest.json`, `pyproject.toml`, and `src/sase/__init__.py` on master still report `0.1.5`,
  so a dispatch build from master HEAD produces the v0.1.5 package. The fix commit touches only `.github/workflows/`, so
  package contents are identical to tag `v0.1.5`.

## Rollout and 0.1.5 Recovery

1. Commit and push via the SASE git commit workflow, scoped to the workflow rename/logic only.
2. The push itself triggers `publish.yml`; release-please reports no new release, so build/publish skip — expected.
3. Dispatch the manual path: `gh workflow run publish.yml -R sase-org/sase -f publish_existing=true`, then watch the run
   through release → build → install-smoke → publish.
4. The dispatch run presents `job_workflow_ref` ending in `.github/workflows/publish.yml@refs/heads/master` with
   `environment: pypi`, which matches the configured publisher exactly.
5. Verify externally: `https://pypi.org/pypi/sase/json` reports `0.1.5`, and a fresh venv `pip install sase==0.1.5`
   passes `sase version` / `sase core health --json` smoke checks.

## Contingencies

- If PyPI still returns `invalid-publisher`, compare the new run's rendered claims against the publisher config; any
  remaining mismatch (owner ID, environment) cannot be fixed repo-side — stop and report the exact claims.
- If PyPI reports duplicate/existing files, check whether 0.1.5 partially uploaded and report before retrying (PyPI
  files are immutable).
- Out of scope (tracked in `sdd/research/202606/direct_master_pypi_releases_consolidated.md`): stale-run guards,
  building from the release tag instead of master HEAD, release-PR auto-merge, and the release/PyPI drift auditor.
