---
create_time: 2026-06-09 16:02:56
status: done
prompt: sdd/prompts/202606/sase_telegram_pypi_release.md
---
# Plan: Publish sase-telegram 0.1.0 to PyPI

## Current Findings

- `sase-telegram` does have release automation, but it is not configured quite like `sase` and it did not publish after
  PR #1.
- PR #1 merged as `chore(master): release 0.1.0` at commit `93f5a4f` on June 9, 2026.
- The Release workflow run for that commit succeeded overall, but the `publish` job was skipped because
  `googleapis/release-please-action` did not output `release_created=true`.
- The release-please log shows the root cause: it found PR #1 but reported
  `PR component: sase-telegram does not match configured component:`. The release PR branch was
  `release-please--branches--master--components--sase-telegram`, while `release-please-config.json` leaves the component
  empty.
- There is currently no GitHub release for `v0.1.0` in `sase-org/sase-telegram`.
- `https://pypi.org/pypi/sase-telegram/json` currently returns 404, so the first PyPI release has not been created yet.
  The project page URL is not yet a verified published package page.

## Implementation Plan

1. Fix release-please metadata so merged release PRs are recognized:
   - Set the package component in `release-please-config.json` to `sase-telegram` while keeping `include-v-in-tag: true`
     and `include-component-in-tag: false`, so the GitHub tag remains `v0.1.0` like the `sase` repo's tag format.
   - Keep the manifest at `0.1.0`; this should allow release-please to create the missing `v0.1.0` GitHub release from
     the already-merged release PR instead of inventing a new version.

2. Align PyPI release plumbing more closely with `sase`:
   - Split the Release workflow into `release`, `build`, `install-smoke`, and `publish` jobs.
   - Build the package once with `uv build`, upload `dist/` as an artifact, smoke-install that artifact in a fresh
     Python 3.12 venv, then publish the same artifact with `pypa/gh-action-pypi-publish@release/v1` from the `pypi`
     environment using OIDC trusted publishing.
   - Keep the smoke check focused on `import sase_telegram` plus both console entry points' `--help`, matching this
     plugin's runtime surface.

3. Improve the package metadata before the first upload:
   - Add `readme = "README.md"` so the PyPI page renders the project README.
   - Add project URLs for repository and issues so the PyPI sidebar points to the correct GitHub repo.

4. Validate locally before pushing:
   - Run formatting/lint/test as appropriate for the scoped metadata/workflow changes.
   - Run `uv build` and inspect the generated metadata to confirm the version is `0.1.0`, the long description is
     present, and the package name is `sase-telegram`.
   - Smoke-install the locally built wheel into a fresh temporary venv and run the import plus CLI help checks.

5. Publish:
   - Commit and push the release automation/package metadata fix to `master`.
   - Watch the Release workflow. If release-please creates the missing `v0.1.0` release on the push, let the
     build/smoke/publish chain publish to PyPI.
   - If the push only updates configuration without creating the release, manually dispatch the Release workflow after
     the fix lands so release-please can reprocess PR #1 with the corrected component.
   - If release-please still cannot backfill the first GitHub release, create `v0.1.0` on GitHub at the release PR merge
     commit using the PR #1 changelog, then trigger the workflow path needed to publish the existing `0.1.0` artifact
     through trusted publishing.

6. Verify externally:
   - Confirm a GitHub release/tag `v0.1.0` exists in `sase-org/sase-telegram`.
   - Confirm `https://pypi.org/pypi/sase-telegram/json` returns 200 and reports version `0.1.0`.
   - Open `https://pypi.org/project/sase-telegram/` and verify it is no longer a 404/pending page and shows the expected
     package/version/metadata.
