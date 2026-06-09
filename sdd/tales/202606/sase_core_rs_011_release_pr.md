---
create_time: 2026-06-09 08:21:12
status: done
prompt: sdd/prompts/202606/sase_core_rs_011_release_pr.md
---
# sase-core-rs 0.1.1 release PR plan

## Goal

Create the minimal PR in `sase-org/sase-core` that causes the existing `Release-plz` workflow to create GitHub tag
`v0.1.1`, build the `sase-core-rs` wheel/sdist matrix, and publish `sase-core-rs==0.1.1` to PyPI through Trusted
Publishing.

This plan intentionally keeps publishing inside GitHub Actions. It does not use local `twine upload` or any long-lived
PyPI API token.

## Current state

- The `sase-core` remote `master` branch is at `c633d642d43f803140054402e76b8e61e36f30c2`
  (`chore: anchor release-plz tags on core crate`).
- That config fix is already on `origin/master`; it is not waiting on a PR.
- `release-plz.toml` now makes `sase_core` the single `v{{ version }}` Git tag/GitHub release anchor and keeps
  `sase_core_py` from creating a duplicate release.
- The workspace version is still `0.1.1`, and the PyPI distribution metadata name is `sase-core-rs`.
- There is currently no `v0.1.1` Git tag, no GitHub release for `v0.1.1`, and PyPI still returns 404 for
  `https://pypi.org/pypi/sase-core-rs/json`.
- The post-fix GitHub Actions run on `master` (`https://github.com/sase-org/sase-core/actions/runs/27205150059`) skipped
  the wheel and publish jobs. Its decisive release-plz log line is
  `skipping release: current commit is not from a release PR`.
- The installed `release-plz` source confirms the release gate when `release_always = false`: it checks the current
  commit's associated GitHub PRs and proceeds only when an associated PR head branch starts with the configured branch
  prefix, defaulting to `release-plz-`.
- The repository has a GitHub environment named `pypi`, and its deployment branch policy allows `master`.
- The existing publish job already has the correct Trusted Publishing shape: `environment: pypi`,
  `permissions: id-token: write`, and `pypa/gh-action-pypi-publish@release/v1`.
- PyPI's current docs say a first project can be created through a Pending Trusted Publisher, and that GitHub Actions
  Trusted Publishing must match the repository owner, repository, workflow filename, and optional environment.

## Release strategy

The direct-pushed config fix cannot itself trigger the release because release-plz sees no associated release PR for
`c633d64`. The recovery PR therefore needs to create a fresh commit on a branch whose name starts with `release-plz-`,
merge that PR into `master`, and let the normal `push` workflow run on the merge.

Because GitHub PRs and merge behavior are more predictable with a real diff than with an empty commit, use a small
docs-only change as the PR payload. The best low-risk candidate is the top-level `README.md` layout section, which still
describes `crates/sase_core_py` as a "PyO3 binding placeholder" even though it is now the real packaged PyO3 extension
crate. That documentation correction is true, release-adjacent, and does not alter package metadata, runtime behavior,
workflow gates, or generated changelogs.

Proposed branch and PR:

- Branch: `release-plz-recover-sase-core-rs-0.1.1`
- Base: `master`
- Commit title: `docs: refresh PyO3 package layout`
- PR title: `docs: refresh PyO3 package layout`
- PR body: explain that the branch intentionally uses the `release-plz-` prefix so the already-fixed release-plz
  configuration can create `v0.1.1` after merge.

Use a normal merge commit for the PR. Release-plz handles squash merges too, but a merge commit keeps this closest to
the release-plz path that the repository is already using.

## Preflight before opening the PR

1. Update local refs and confirm there are no unexpected changes in the `sase-core` workspace.
2. Confirm `origin/master` still points to `c633d64` or inspect any newer commits before proceeding.
3. Confirm `v0.1.1` still does not exist as a remote tag or GitHub release.
4. Confirm PyPI still does not have `sase-core-rs`.
5. Confirm the PyPI Pending Trusted Publisher exists before merge. The expected PyPI-side configuration is:
   - Project name: `sase-core-rs`
   - Owner: `sase-org`
   - Repository: `sase-core`
   - Workflow filename: `release-plz.yml`
   - Environment: `pypi`

If the Pending Trusted Publisher is absent or mismatched, create or fix it before merging the PR. Do not compensate by
switching to a token-based or local upload path.

## Implementation steps

1. In `/home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_11`, start from current `master` and create
   `release-plz-recover-sase-core-rs-0.1.1`.
2. Update only the top-level `README.md` layout description for `crates/sase_core_py`.
3. Run a focused local validation set appropriate for a docs-only diff:
   - `git diff --check`
   - `cargo fmt --all -- --check`
   - optionally skip full local clippy/test because CI will run them and the diff is documentation-only; run them
     locally if the change touches anything beyond README text.
4. Commit with `sase commit`, staging only `README.md`.
5. Push the branch and create the PR with `gh pr create`.
6. After the PR exists, run a local release-plz dry-run at the PR head:
   - `release-plz release --dry-run --git-token "$(gh auth token)" --repo-url https://github.com/sase-org/sase-core --forge github --output json -vv`
   - Expected result: release-plz no longer says `current commit is not from a release PR`, and the JSON includes a
     planned `sase_core` release for version `0.1.1` with tag `v0.1.1`.
7. Wait for PR checks:
   - `PR Title`
   - `CI / cargo fmt + clippy + test`
   - `CI / maturin build + import smoke`
8. If the dry-run or PR checks fail, do not merge. Fix the PR only if the cause is obvious and still within this plan's
   scope; otherwise stop and produce a revised plan.

## Merge and release steps

1. Merge the PR with a merge commit.
2. Watch the resulting `Release-plz` workflow run on `master`.
3. Confirm the `Release-plz release` job outputs:
   - `releases_created: true`
   - a release entry for `sase_core` version `0.1.1`
   - tag `v0.1.1`
4. Confirm the wheel/sdist jobs run instead of skipping:
   - Linux x86_64
   - Linux aarch64
   - macOS universal2
   - Windows x86_64
   - sdist
   - `twine check`
5. Confirm `publish to PyPI` completes successfully.

If release-plz still skips with `current commit is not from a release PR`, stop and do not create more tags manually.
The likely next plan would be a small explicit backfill workflow path, but that should be reviewed separately.

If release-plz creates `v0.1.1` but PyPI publish fails with a Trusted Publishing/OIDC error, fix the PyPI Pending
Trusted Publisher configuration and rerun the failed publish job from the same workflow run if possible. Avoid rerunning
the entire workflow after the tag exists, because a fresh release-plz job may report `releases_created: false` and skip
the publish matrix.

## Post-release verification

1. Confirm the GitHub tag exists:
   - `git ls-remote origin refs/tags/v0.1.1`
2. Confirm the GitHub release exists:
   - `gh release view v0.1.1 --repo sase-org/sase-core`
3. Confirm PyPI JSON returns 200 and contains version `0.1.1`:
   - `https://pypi.org/pypi/sase-core-rs/json`
4. Install from PyPI in a fresh Python 3.12 environment:
   - `uv venv -p 3.12 /tmp/sase-core-rs-0.1.1-smoke`
   - `/tmp/sase-core-rs-0.1.1-smoke/bin/python -m pip install sase-core-rs==0.1.1`
5. Smoke-test the module:
   - `import sase_core_rs`
   - `sase_core_rs.parse_query("status:Ready")`
   - verify an incomplete query such as `"("` raises `ValueError`

## Completion criteria

The work is complete when:

- A PR from `release-plz-recover-sase-core-rs-0.1.1` to `master` exists and is merged.
- The GitHub `Release-plz` workflow creates `v0.1.1` and publishes successfully.
- PyPI lists `sase-core-rs==0.1.1`.
- A fresh Python 3.12 environment can install and import `sase-core-rs==0.1.1`.
