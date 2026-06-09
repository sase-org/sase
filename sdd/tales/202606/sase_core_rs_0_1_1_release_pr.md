---
create_time: 2026-06-09 08:33:03
status: done
prompt: sdd/prompts/202606/sase_core_rs_0_1_1_release_pr.md
---
# Plan: release `sase-core-rs` 0.1.1 via the recovery PR

## Objective

Release version `0.1.1` of the PyPI package `sase-core-rs` by using the already-open recovery PR in
`sase-org/sase-core`, then verify the GitHub release, wheel/sdist build matrix, PyPI publish, and install/import smoke
from PyPI.

## Current State

- The `sase-core` sibling workspace is `/home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_11`.
- `master` is at `c633d64 chore: anchor release-plz tags on core crate`.
- PR `sase-org/sase-core#7` is open, mergeable, non-draft, and green.
- PR #7 branch is `release-plz-recover-sase-core-rs-0.1.1`, which intentionally starts with `release-plz-`.
- PR #7 contains only a README wording refresh: `crates/sase_core_py/` is described as the PyO3 extension crate for the
  `sase-core-rs` package.
- GitHub repo settings allow squash merge only. That is acceptable: the squash commit should still be associated with PR
  #7, whose head branch matches release-plz's release-PR branch convention.
- The remote repository has no `v0.1.1` GitHub release and no `refs/tags/v0.1.1`.
- `https://pypi.org/project/sase-core-rs/` currently returns 404, so this is still the first-publish path.
- The release workflow publishes through environment `pypi` with `id-token: write`.
- User confirmation says the PyPI Pending Trusted Publisher exists for owner `sase-org`, repository `sase-core`,
  workflow filename `release-plz.yml`, and environment `pypi`, and authorizes merge once confirmed.
- Local non-mutating dry-run on PR #7's commit with `release-plz release --dry-run` reached the associated PR lookup,
  found PR #7, decided `should release: Yes`, and would create tag/release `v0.1.1` for `sase_core 0.1.1`.

## Implementation Plan

1. Re-check the remote state immediately before merge.
   - Confirm PR #7 remains open, mergeable, non-draft, and all required checks are passing.
   - Confirm `v0.1.1` still does not exist as either a tag or GitHub release.
   - Confirm PyPI still has no published `sase-core-rs` project/version, to avoid a duplicate-version publish attempt.

2. Merge PR #7 with GitHub's squash merge path.
   - Use `gh pr merge 7 --repo sase-org/sase-core --squash`.
   - Do not create additional commits or file changes unless the pre-merge checks show PR #7 has gone stale.
   - Do not delete the recovery branch during merge; keep it temporarily available until the release/publish workflow is
     verified.

3. Watch the `Release-plz` workflow triggered by the push to `master`.
   - Identify the run for the new squash commit on `master`.
   - Confirm `release-plz-release` reports `releases_created: true`.
   - Confirm logs show `sase_core 0.1.1` and creation of `v0.1.1`.
   - Confirm the wheel jobs run for Linux `x86_64`, Linux `aarch64`, macOS `universal2`, Windows `x86_64`, plus sdist.
   - Confirm `twine check` passes before publish.
   - Confirm `publish to PyPI` uses the `pypi` environment and succeeds.

4. Verify release artifacts after the workflow succeeds.
   - Check `gh release view v0.1.1 --repo sase-org/sase-core`.
   - Check the `v0.1.1` tag exists on GitHub and points to the expected release commit.
   - Check PyPI exposes project `sase-core-rs` version `0.1.1`.
   - Confirm PyPI includes the expected wheel set and sdist.
   - Run a fresh Python 3.12 install/import smoke from PyPI: `python -m venv`, `pip install sase-core-rs==0.1.1`, import
     `sase_core_rs`, and exercise `parse_query`.

5. Cleanup and final status.
   - Leave local worktrees clean.
   - Report the merged PR URL, release workflow URL, GitHub release URL, PyPI URL, and smoke-test result.
   - If everything is published, optionally delete the recovery branch after reporting that it is no longer needed.

## Failure Handling

- If PR #7 is no longer green or mergeable, stop before merging and inspect the changed checks or merge conflict.
- If release-plz skips with `current commit is not from a release PR`, do not make a new version bump. Diagnose the
  associated PR metadata first; if GitHub did not associate the squash commit with PR #7 as expected, create a second
  small `release-plz-...` recovery PR and merge it only after confirming the dry-run recognizes it.
- If tag/release creation succeeds but PyPI publish fails due Trusted Publisher configuration, fix the PyPI publisher
  externally and prefer rerunning failed jobs from the same workflow run so the successful release output and artifacts
  are reused. Do not merge another release-trigger PR until the immutable version/tag state is understood.
- If PyPI partially accepts files, do not retry blindly. Compare uploaded files against the workflow artifacts and only
  rerun or manually recover missing distributions after confirming PyPI's immutable file/version constraints.
