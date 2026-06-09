---
create_time: 2026-06-09 08:01:04
status: done
prompt: sdd/prompts/202606/sase_core_rs_pypi_release_recovery.md
---
# sase-core-rs PyPI Release Recovery Plan

## Current Findings

- `https://pypi.org/pypi/sase-core-rs/json` returns 404, so `sase-core-rs==0.1.1` is not published on PyPI.
- `sase-org/sase-core#6` was merged on 2026-06-09 at 11:19:07Z as merge commit
  `277457141e7ebdbf4d4dbda490f97832c4bbe73d`.
- The post-merge `Release-plz` workflow run `27202587148` completed successfully, but all wheel, sdist, metadata-check,
  and PyPI publish jobs were skipped.
- The release-plz job output was `releases_created: false` and `releases: []`.
- The release-plz log contains the decisive line: `sase_core 0.1.1: no release method enabled`.
- There is no `v0.1.1` git tag, no GitHub release, and no release artifacts for this merge.

## Root Cause

The release workflow publishes to PyPI only when the `release-plz-release` job reports `releases_created == 'true'`.
Release-plz did not create a release because the package it selected for the shared version-group release was
`sase_core`, and `release-plz.toml` currently disables all release methods for `sase_core`.

The workflow itself already has the right general PyPI shape: it builds the wheel matrix, builds an sdist, runs
`twine check`, and publishes with `pypa/gh-action-pypi-publish` using OIDC. The missed publish is therefore not caused
by missing `twine upload`; it is caused by release-plz never reaching the publish path.

For a brand-new PyPI project, the preferred setup is still Trusted Publishing, not a local or long-lived-token
`twine upload`. PyPI supports creating a first project with a Pending Trusted Publisher. For this package, that pending
publisher should authorize:

- PyPI project: `sase-core-rs`
- GitHub owner: `sase-org`
- GitHub repository: `sase-core`
- Workflow: `.github/workflows/release-plz.yml`
- Environment: `pypi`

If that PyPI-side pending publisher is absent, the first publish attempt will fail at the PyPI authentication step even
after the GitHub workflow bug is fixed.

## Plan

1. Fix the release-plz release method selection.

   Update `release-plz.toml` so the package release-plz actually selects for the shared `sase-core` version group can
   create the single canonical `v{{ version }}` tag and GitHub release. Based on the failed run, that package is
   `sase_core`. Keep the workspace in `git_only` mode and keep Cargo publishing disabled; the GitHub release is only a
   trigger and provenance anchor for the Python wheel publish path.

2. Preserve a single release tag.

   Avoid enabling two packages to create the same `v{{ version }}` tag. Make one package the release anchor and keep the
   other package participating in version/changelog management without creating an additional tag or release.

3. Add or verify an explicit recovery path for the already missed `0.1.1` release.

   Because the original release PR has already merged, the safest recovery is either:
   - merge the release-plz config fix from a branch whose name starts with `release-plz-`, so `release_always = false`
     still treats the merged PR as release-triggering; or
   - add a manual workflow-dispatch backfill path that builds and publishes the current `0.1.1` package without relying
     on `releases_created == 'true'`.

   Prefer the first option if it is enough after a local dry-run confirms release-plz will create `v0.1.1`; use the
   manual backfill path if release-plz will not re-emit the missed release from the fixed config.

4. Validate locally before changing remote state.

   Run focused checks in the `sase-core` workspace:
   - TOML/YAML syntax checks for changed config/workflow files.
   - `cargo fmt --all -- --check`
   - `cargo clippy --workspace --all-targets -- -D warnings`
   - `cargo test --workspace`
   - a local `maturin` wheel build for `crates/sase_core_py`
   - fresh-venv import/query smoke against the built wheel
   - `twine check` on built distributions
   - release-plz dry-run where practical to confirm it will produce a release instead of `no release method enabled`

5. Publish through GitHub Actions, not local `twine upload`.

   Once the workflow/config fix is available on GitHub and PyPI has the Pending Trusted Publisher for `sase-core-rs`,
   trigger the recovery release path. Watch the run through:
   - release-plz creates `v0.1.1` or the manual backfill selects version `0.1.1`
   - Linux, macOS, Windows, and sdist artifacts are produced
   - `twine check` passes
   - `publish to PyPI` completes successfully

6. Verify the external result.

   After publish, verify:
   - `https://pypi.org/pypi/sase-core-rs/json` returns 200 and lists `0.1.1`
   - `pip`/`uv pip` can install `sase-core-rs==0.1.1` in a fresh Python 3.12 environment
   - `import sase_core_rs` works
   - representative exported functions, such as `parse_query('status:Ready')`, work

7. If Trusted Publishing blocks the run, stop at that boundary.

   If the publish job fails with an OIDC or trusted-publisher error, do not switch to ad hoc local `twine upload` unless
   explicitly requested. Instead, configure or correct the PyPI Pending Trusted Publisher and rerun the same GitHub
   Actions publish path so provenance and future releases stay consistent.
