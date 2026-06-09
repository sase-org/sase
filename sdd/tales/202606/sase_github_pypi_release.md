---
create_time: 2026-06-09 17:12:06
status: done
prompt: sdd/prompts/202606/sase_github_pypi_release.md
---
# Fix sase-github PyPI Release 0.1.1

## Context

`sase-github` has `pyproject.toml`, `.release-please-manifest.json`, and `CHANGELOG.md` updated to `0.1.1` after PR #1
was merged on 2026-06-09, but PyPI still only serves `sase-github==0.1.0`.

The failed publishing path is not a package build failure. The `Release` workflow run for merge commit
`6999291d07319abd8f527b3048468c56c0a2a309` completed successfully, but its `publish` job was skipped. There is also no
GitHub release for `v0.1.1`.

## Root Cause

The merge of PR #1 produced the version bump, manifest update, and changelog, but release-please did not create the
GitHub release. The decisive log line from run `27232229973` is:

```text
PR component: sase-github does not match configured component:
```

The repository's `release-please-config.json` declares the root package as `"."` with an empty package config. That
leaves release-please's configured component blank. The release PR itself was generated with component `sase-github`, so
the later push run found PR #1 but refused to classify it as the matching release PR. Because the workflow gates
publishing on `needs.release.outputs.release_created == 'true'`, the publish job never ran.

There is also a recovery gap: the current workflow has `workflow_dispatch`, but no safe manual path for publishing an
already-created version bump. If release-please misses the one push event that should create the release, the workflow
cannot publish `0.1.1` from the trusted GitHub Actions/PyPI environment without modifying the workflow or creating
another release event.

## Plan

1. Preserve the current repository state.
   - Work only in the numbered `sase-github_10` sibling workspace opened through
     `sase workspace open -p sase-github 10`.
   - Re-check `git status` before edits to avoid mixing in unrelated user changes.

2. Fix release-please package identity.
   - Add the root package component to `release-please-config.json`:

     ```json
     "packages": {
       ".": {
         "component": "sase-github"
       }
     }
     ```

   - Keep `include-component-in-tag: false` and `include-v-in-tag: true` so the release tag remains `v0.1.1`, matching
     the repo's existing tag convention and PyPI-facing package version.
   - Do not change `pyproject.toml`, `.release-please-manifest.json`, or `CHANGELOG.md`; those already represent the
     intended `0.1.1` release.

3. Harden the publishing workflow, matching the working `sase-telegram` pattern.
   - Rename `.github/workflows/release.yml` to `.github/workflows/publish.yml` and set the workflow name to `Publish`.
   - Add a required boolean `workflow_dispatch` input named `publish_existing`, with text specific to publishing the
     existing `0.1.1` artifacts.
   - Run release-please only on push events. On manual dispatch, skip release-please and default `release_created` to
     `false`.
   - Split the current single publish job into:
     - `build`: build the sdist/wheel artifact.
     - `install-smoke`: install the built wheel in a fresh Python 3.12 venv and verify the package imports and plugin
       entry points are discoverable.
     - `publish`: download the already-smoked artifact and publish to PyPI using trusted publishing.
   - Allow build/smoke/publish only when release-please creates a release on push, or when `workflow_dispatch` is run
     with `publish_existing=true`.

4. Validate locally before any remote release attempt.
   - Run `actionlint .github/workflows/publish.yml`.
   - Run `just install`, then `just check`.
   - Build artifacts with `uv build`.
   - Inspect wheel metadata to confirm `Name: sase-github` and `Version: 0.1.1`.
   - Smoke-install the built wheel into a fresh Python 3.12 venv and verify:
     - `import sase_github`
     - entry points for `sase_vcs`, `sase_workspace`, `sase_config`, and `sase_xprompts` expose the expected `github` /
       `sase_github` registrations.
   - Remove generated `dist/` and temporary smoke artifacts afterward.

5. Remote release recovery after the workflow/config fix is approved and committed.
   - Commit the workflow/config changes through the SASE commit workflow, then push.
   - Confirm the push-triggered `Publish` workflow succeeds and does not publish unless release-please creates a
     release.
   - Manually dispatch `Publish` with `publish_existing=true` to publish the already-bumped `0.1.1` artifacts from
     `master`.
   - Watch `build`, `install-smoke`, and `publish` to completion.

6. Confirm the final result.
   - Verify GitHub Actions run success.
   - Verify PyPI JSON and project page report `sase-github==0.1.1`.
   - Fresh-install `sase-github==0.1.1` from PyPI into a clean Python 3.12 venv and repeat import/entry point smoke
     checks.
   - Report the root cause, commit/run URLs if committed, PyPI verification, and any local validation caveats.

## Expected Outcome

The immediate missed release can be published as `sase-github==0.1.1` without changing the package version again, and
future release-please PR merges will create GitHub releases because the configured component now matches the release PR
component.
