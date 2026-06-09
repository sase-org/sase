---
create_time: 2026-06-09 16:26:03
status: done
prompt: sdd/prompts/202606/sase_telegram_pypi_010.md
---
# Plan: release sase-telegram 0.1.0 to PyPI

## Context

The previous GitHub Actions publish attempt built and smoke-tested the `sase-telegram` 0.1.0 artifacts successfully, but
PyPI rejected the OIDC exchange with `invalid-publisher`. The failed job rendered these claims:

- `repository`: `sase-org/sase-telegram`
- `repository_owner`: `sase-org`
- `workflow_ref`: `sase-org/sase-telegram/.github/workflows/release.yml@refs/heads/master`
- `environment`: `pypi`

The pending publisher now configured on PyPI is:

- Repository: `sase-org/sase-telegram`
- Workflow: `publish.yml`
- Environment name: `pypi`

That means the remaining repo-side mismatch is the GitHub Actions workflow filename. Rerunning the old failed run is not
sufficient, because it would continue to present the old `release.yml` workflow claim. A fresh run from
`.github/workflows/publish.yml` is required.

There is one additional release-flow wrinkle: the GitHub release/tag `v0.1.0` already exists. A new push that only
renames the workflow will probably make `release-please` report `release_created=false`, so the current
build/smoke/publish jobs would skip. The workflow therefore needs an explicit, guarded manual publish path for an
existing release/version.

## Implementation

1. Rename `.github/workflows/release.yml` to `.github/workflows/publish.yml` in the `sase-telegram_12` workspace and
   update the workflow display name to `Publish` for clarity.

2. Preserve the existing push-driven release behavior:
   - On `push` to `master`, run `release-please`.
   - Build, smoke-install, and publish only when `release-please` creates a release.
   - Keep the PyPI publish job bound to the `pypi` environment with `id-token: write`.

3. Add a guarded `workflow_dispatch` path for the already-created `0.1.0` release:
   - Add a required boolean input such as `publish_existing`.
   - Let build, install-smoke, and publish run when either `release_created == true` or the workflow is manually
     dispatched with `publish_existing == true`.
   - Avoid running `release-please` during manual existing-version publishes.

4. Validate locally before pushing:
   - `actionlint .github/workflows/publish.yml`
   - `just install` if the workspace dependencies are not already installed
   - `just check`
   - clean `dist/`, `uv build`
   - inspect generated metadata for `Name: sase-telegram` and `Version: 0.1.0`
   - fresh Python 3.12 venv install from the built wheel plus import and both console-script `--help` smoke checks

5. Commit and push using the SASE git commit workflow, with the commit scoped to the workflow rename/logic only unless
   validation exposes another release-blocking issue.

6. Trigger a fresh GitHub Actions run from `.github/workflows/publish.yml` using `workflow_dispatch` with
   `publish_existing=true`, then watch the run through build, install-smoke, and publish.

7. After publish succeeds, verify PyPI externally:
   - `https://pypi.org/pypi/sase-telegram/json` returns HTTP 200 and reports version `0.1.0`
   - `https://pypi.org/project/sase-telegram/` returns HTTP 200, not 404
   - install `sase-telegram==0.1.0` from PyPI in a fresh venv and rerun the import/CLI-help smoke checks

## Contingencies

- If PyPI still rejects the token, inspect the new failed log claims. The expected `workflow_ref` and `job_workflow_ref`
  must contain `.github/workflows/publish.yml`, and `environment` must be `pypi`.
- If PyPI reports that the project name has been claimed or the pending publisher is no longer valid, that cannot be
  fixed purely from the repo; stop and report the exact PyPI error.
- If PyPI reports duplicate files, verify whether the project page has become live. If version `0.1.0` exists and its
  artifacts are correct, treat publishing as complete and document the duplicate rerun behavior.
