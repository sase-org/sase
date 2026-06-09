---
create_time: 2026-06-09 07:12:04
status: wip
prompt: sdd/prompts/202606/pypi_release_recovery.md
---
# PyPI Release Recovery Plan

## Problem Summary

`sase` is tagged and released on GitHub through `v0.1.3`, but PyPI still only has `sase==0.1.0`. The immediate failure
is not that release-please failed to bump the Python package version. It did bump `pyproject.toml`,
`src/sase/__init__.py`, `.release-please-manifest.json`, and `CHANGELOG.md`.

The publish path failed after the GitHub release was created:

- The `v0.1.1`, `v0.1.2`, and `v0.1.3` release runs all failed or skipped before PyPI publish.
- The failing gate was `install-smoke`, where `uv pip install dist/sase-*.whl` could not resolve
  `sase-core-rs>=0.1.1,<0.2.0`.
- PyPI has no `sase-core-rs` distribution yet.
- The sibling `sase-org/sase-core` repo has an open, mergeable release-plz PR (`sase-org/sase-core#6`,
  `chore: release v0.1.1`) whose checks are green. Until that PR is merged and its release workflow publishes
  `sase-core-rs==0.1.1`, the `sase` wheel is intentionally uninstallable from PyPI and the smoke gate correctly blocks
  publication.

There is also a workflow race:

- The run that created the `v0.1.3` GitHub release was queued for an older push and built `sase==0.1.2`.
- `release-please-action` found the newly merged release PR on `master` and created the `v0.1.3` GitHub release, but the
  downstream `actions/checkout@v4` defaulted to the triggering SHA, not the release tag/SHA.
- The later run for the actual release PR merge saw that `v0.1.3` already existed, so `release_created` was false and
  build/smoke/publish were skipped.

Finally, PyPI provenance for the old `sase==0.1.0` upload points at `bbugyi200/sase` and
`.github/workflows/publish.yml`. The current workflow uses `sase-org/sase` and `.github/workflows/release.yml`. Once the
smoke gate is fixed, PyPI trusted publishing may still need to be updated in PyPI project settings to authorize the
current repository/workflow/environment.

## Plan

1. Recover the missing runtime dependency first.

   Merge the green `sase-org/sase-core#6` release PR or otherwise release the same `sase-core-rs` package version that
   `sase` depends on. Verify `sase-core-rs==0.1.1` appears on PyPI and can be installed on the platform used by `sase`'s
   release smoke test.

2. Harden `sase`'s release workflow against stale-run releases.

   Update `.github/workflows/release.yml` so a push run only invokes release-please when the triggering SHA is still the
   current head of the target branch. This prevents an older queued push from creating a release for a newer release PR
   merge.

3. Build from the released source, not from the workflow-triggering SHA.

   Extend the release job outputs to include the release tag/SHA from `release-please-action` (`tag_name`, `sha`, and
   `version`). Update the build job to check out that release ref when a release was created. Add a lightweight
   verification step that the package version being built matches the release version.

4. Add a manual backfill path for existing GitHub releases.

   Add a `workflow_dispatch` input for an existing release tag, for example `v0.1.3`. When provided, the workflow should
   skip release-please, build exactly that tag, run the same smoke test, and publish the resulting distributions to
   PyPI. This is needed because `v0.1.3` already exists on GitHub, so release-please will not emit
   `release_created=true` again.

5. Re-run publication for `sase==0.1.3`.

   After `sase-core-rs==0.1.1` is visible on PyPI and the workflow hardening is merged, dispatch the `sase` Release
   workflow with `release_tag=v0.1.3`. Confirm the artifact is `sase-0.1.3`, the install smoke passes, and PyPI shows
   `sase==0.1.3`.

6. Handle PyPI trusted publishing if it surfaces.

   If the publish job fails with an OIDC/trusted-publisher error, update PyPI's trusted publisher for project `sase` to
   the current owner/repository/workflow/environment: `sase-org/sase`, `.github/workflows/release.yml`, environment
   `pypi`. Then re-run the manual `release_tag=v0.1.3` backfill.

7. Verify the end state.

   Check PyPI release history for both `sase-core-rs==0.1.1` and `sase==0.1.3`, install `sase==0.1.3` in a fresh Python
   3.12 environment, and run `sase core health --json`.
