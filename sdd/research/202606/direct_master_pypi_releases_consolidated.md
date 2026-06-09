# Direct `master` Pushes and Timely PyPI Releases

Date: 2026-06-09

## Request

SASE should become stable enough that users can install or update the standard PyPI packages and get the latest stable
version. The project already uses Release Please PRs. The concern is what happens when changes are merged or pushed
directly to `master`, which may remain allowed.

This consolidates the two prior research notes:

- `sdd/research/202606/direct_master_pypi_publish_options.md`
- `sdd/research/202606/direct_to_master_pypi_publishing.md`

## Bottom Line

Keep Release Please as the canonical stable-release mechanism, but add guardrails and backstops so direct `master`
pushes cannot silently become unreleased or wrongly packaged.

The current workflow already runs Release Please on every `master` push. Direct pushes are therefore not invisible.
They flow into a release only when their commit messages are parseable, classified as release-relevant, and the Release
Please PR is merged. That leaves three gaps:

- **Correctness:** bad or under-classified direct-push commit messages can be ignored by Release Please or omitted from
  release notes.
- **Timeliness:** an open Release Please PR can sit unmerged, so PyPI can lag behind `master` indefinitely.
- **Provenance/recovery:** the publish workflow must build the exact release tag/SHA and must have a replay path when a
  GitHub release exists but PyPI publication failed.

Recommended minimal path:

1. Enforce Conventional Commit subjects for commits entering `master` with a GitHub ruleset metadata restriction, plus a
   local `commit-msg` hook for fast feedback.
2. Add a release-PR staleness alert, then move to scheduled auto-merge or full auto-merge of Release Please PRs once CI
   confidence is high.
3. Harden `.github/workflows/release.yml` to skip stale queued push runs and to build from the Release Please tag/SHA,
   not from the triggering checkout.
4. Add a manual `release_tag` backfill path that builds from an existing tag and publishes through the same smoke/publish
   jobs.
5. Add a scheduled auditor for GitHub release/PyPI/version-file drift and cross-repo release ordering.

Do not publish every raw `master` commit as a stable PyPI release. That burns immutable public versions for ordinary
commit bursts and removes the release PR as the final version/changelog gate.

## Current SASE State

Verified from this workspace:

- `.github/workflows/release.yml` runs on `push` to `master` and `workflow_dispatch`.
- The `release` job runs `googleapis/release-please-action@v5`.
- `build`, `install-smoke`, and `publish` run only when `release_created == 'true'`.
- PyPI publish uses `pypa/gh-action-pypi-publish@release/v1`, `environment: pypi`, and job-scoped `id-token: write`.
- `release-please-config.json` uses `release-type: python`, `include-v-in-tag: true`,
  `include-component-in-tag: false`, `bump-minor-pre-major: true`, `bump-patch-for-minor-pre-major: true`, and an
  `extra-files` entry for `src/sase/__init__.py`.
- `.release-please-manifest.json`, `pyproject.toml`, and `src/sase/__init__.py` are at `0.1.3`.
- GitHub releases exist through `v0.1.3`; `v0.1.3` points at release PR merge commit
  `31f5b5b3545b2fd1e9b2e0838d9b494f041cbc8e`.
- PyPI still reports `sase==0.1.0`, uploaded on 2026-02-23. The PyPI artifact provenance points to
  `bbugyi200/sase`, `refs/tags/v0.1.0`, and `.github/workflows/publish.yml`, not the current `sase-org/sase`
  `release.yml`.
- `sase-core-rs` now exists on PyPI at `0.1.2` with the expected wheel/sdist set, satisfying SASE's
  `sase-core-rs>=0.1.1,<0.2.0` runtime range. This resolves the earlier missing-core blocker for backfilling
  `sase==0.1.3`.
- `sase-telegram` still 404 on PyPI; `sase-github` is still `0.1.0` and depends on `sase>=0.1.0`.
- There is currently an open Release Please PR, `sase-org/sase#160`, titled `chore(master): release 0.1.4`, with
  `autorelease: pending`.

The live drift is therefore concrete: the repository and GitHub releases are ahead of PyPI, and plugin CI already hit
that skew.

## How Direct Pushes Behave

Release Please parses git history for Conventional Commit messages and maintains a release PR. It does not publish to
package managers itself. When the release PR is merged, Release Please updates version/changelog files, tags the commit,
and creates a GitHub Release; SASE's workflow then builds/smokes/publishes in the same run when
`release_created == true`.

Direct pushes are parsed as commit messages, not PR titles. This matters because `.github/workflows/pr-title.yml`
validates only PR titles. A direct `git push` bypasses that check completely.

For the Python strategy, SASE should treat `fix`, `feat`, `perf`, `deps`, `docs`, `revert`, and explicit breaking
markers as release-relevant unless local testing of Release Please proves otherwise. The Release Please README's
high-level troubleshooting text names `feat`, `fix`, and `deps`, and says Python also treats `docs` as releasable; the
current Python strategy source also exposes visible changelog sections for `perf` and `revert`. In contrast, direct
`chore`, `ci`, `test`, `build`, `style`, and `refactor` commits should not be relied on to publish unless they carry a
breaking marker or a `Release-As: x.y.z` footer.

Failure modes:

- `fixed the thing` is unparseable, so it can be ignored.
- `chore: repair user-visible install failure` is parseable but under-classified, so it may not bump/release.
- A multi-commit direct push can leak intermediate WIP messages into the release PR unless every commit is clean.
- Push CI runs after the commit is already on `master`, so it is detective for direct pushes, not preventive.
- If the Release Please PR is never merged, there is no tag and no PyPI release.

## Options

### A. Keep Release PRs, Add Auto-Merge or a Bounded Cadence

This is the best default.

Flow:

1. A PR merge or direct push lands on `master`.
2. Release Please updates the open release PR when releasable commits exist.
3. Required CI runs on the release PR.
4. The release PR is merged manually, on a schedule, or via auto-merge.
5. The merge triggers Release Please to create the Git tag and GitHub Release.
6. The same `release.yml` run builds, smoke-tests, and publishes the PyPI artifacts.

Timeliness choices:

- **Staleness alert:** notify when the open `autorelease: pending` PR is older than N hours/days or when PyPI trails the
  latest GitHub release. Lowest risk; still human-gated.
- **Scheduled auto-merge:** a daily or weekly workflow merges the release PR when checks are green and the diff is only
  expected release files. Bounded lag without per-commit release churn.
- **Full auto-merge:** enable GitHub auto-merge for Release Please PRs once required checks pass. This is the closest
  match for "users always get the latest stable."

Use `SASE_RELEASE_TOKEN` from a bot PAT or GitHub App rather than falling back to `GITHUB_TOKEN` if the release PR must
trigger required CI. GitHub's default token suppresses most workflow runs caused by resources it creates. Because SASE
publishes inside the same workflow that creates the release, this does not currently break PyPI publish directly, but it
does matter for release-PR CI and would matter if publishing moved to a separate tag/release-triggered workflow.

### B. Direct-Push Guardrails Without Fully Banning Direct Pushes

Use a GitHub repository ruleset targeting `master`:

- Add a `Restrict commit metadata` rule for commit messages.
- Set it to "Evaluate" first, then "Active".
- Require a Conventional Commit subject, for example:

  ```text
  ^(feat|fix|perf|deps|docs|ci|test|chore|refactor|build|style|revert)(\([A-Za-z0-9._/-]+\))?!?: [^[:space:]].*\n?$
  ```

- Keep the allowed type list broad enough for non-releasing work, but enforce that every direct-push commit has a
  machine-readable type.
- Add bypass for the release bot/App and document emergency bypass procedure.
- Consider requiring linear history so direct pushes cannot introduce merge commits full of uncurated commit messages.

This is preventive. A CI commitlint job on `push` is useful as an alert, but it cannot stop a bad direct push from
landing.

Back it with a local `commit-msg` hook or `pre-commit` hook so maintainers get immediate feedback before pushing.

### C. Harden the Existing Release Workflow

The current recovery tale shows a real stale-run/provenance hazard: a queued older push run can ask Release Please about
the newer default branch, create a newer GitHub release, and then the downstream `actions/checkout@v4` can build the
older triggering SHA. That can permanently upload artifacts whose version/tag do not match their source.

Add these invariants:

- Add workflow/job concurrency for the release path. GitHub now supports `queue: max`; use queueing instead of
  cancellation for release/publish work.
- Before invoking Release Please on a `push`, compare `github.sha` to the current remote `refs/heads/master`. If this is
  an older queued run, exit successfully before release creation.
- Expose Release Please outputs such as `tag_name` and `version`; use `sha` if available, or resolve `tag_name` after
  fetching tags.
- In `build`, check out the release tag/SHA, not the triggering commit.
- Verify `pyproject.toml`, `src/sase/__init__.py`, and built wheel/sdist metadata match the expected release version.
- Upload `dist/` once, smoke-test the uploaded artifact, then publish that same artifact.
- Keep `skip_existing: false`; duplicate/partial publishes should fail visibly because PyPI files cannot be re-uploaded.
- Keep `id-token: write` scoped only to the PyPI publish job.

### D. Manual Publish-From-Tag Backfill

Add `workflow_dispatch` inputs:

- `release_tag`, e.g. `v0.1.3`
- `publish_pypi`
- `dry_run`

When `release_tag` is supplied:

1. Skip Release Please.
2. Check out exactly that tag.
3. Assert the tag exists.
4. Build from that tag.
5. Assert artifact metadata name/version match the tag.
6. Smoke-install the artifact.
7. Publish through the same Trusted Publishing job.
8. Fail if the version already exists on PyPI.

This is not the primary steady-state release path, but it is required for the current `v0.1.3` recovery because Release
Please will not emit `release_created=true` again for a GitHub release that already exists.

### E. Scheduled Auditor and Backstop

Add a scheduled workflow. GitHub scheduled workflows run on the latest default-branch commit and the shortest documented
interval is five minutes; a daily or hourly cadence is enough for SASE.

Check:

- latest GitHub release tag vs latest PyPI version,
- version files vs PyPI,
- open `autorelease: pending` PR age,
- release workflow failures since the latest tag,
- direct `master` commits since the latest release that are release-relevant but not yet in a merged release,
- `sase-core-rs` -> `sase` -> plugin publish ordering.

Actions:

- notify via the normal SASE notification path,
- label/comment on the release PR,
- enable/perform auto-merge if policy allows,
- dispatch publish-from-tag for an already-created GitHub release after prerequisites pass.

This catches the exact present class of drift: GitHub releases through `v0.1.3`, PyPI still at `0.1.0`.

### F. Optional TestPyPI Dev Stream

If early adopters need every `master` commit installable, publish `.devN` or timestamped pre-release builds to TestPyPI
on every `master` push. Keep this separate from stable PyPI:

- Normal users keep `pip install -U sase` stable-only.
- Early adopters can opt in with `--pre` and the TestPyPI index.
- Avoid local-version segments such as `+gHASH` for public indices; use a valid public dev/pre-release version.
- Do not upload every commit to real PyPI. PyPI artifacts are immutable and deleted files cannot be re-uploaded.

This is a preview channel, not the answer for stable releases.

## Anti-Patterns

- Do not publish every direct `master` push to real PyPI as a stable version.
- Do not make `chore`, `ci`, `test`, `build`, or `refactor` automatically release just to compensate for weak commit
  discipline.
- Do not rely on a separate tag/release workflow when tags/releases are created by `GITHUB_TOKEN`.
- Do not build from the default checkout after Release Please creates a release.
- Do not hide duplicate uploads with `skip_existing: true`.
- Do not bypass the install-smoke gate to make PyPI catch up. A missing or incompatible `sase-core-rs` package is a
  valid release blocker, not noise; now that `sase-core-rs==0.1.2` is on PyPI, the next recovery step should be the
  guarded `sase==0.1.3` backfill.

## Recommended Implementation Order

1. Backfill `sase==0.1.3` from tag once workflow hardening is in place. The earlier `sase-core-rs` prerequisite is now
   satisfied by PyPI `sase-core-rs==0.1.2`.
2. Harden `release.yml`: stale-head guard, queued concurrency, release-ref checkout, metadata assertions, and
   `release_tag` backfill.
3. Update PyPI Trusted Publishing for current identity if needed: project `sase`, owner/repo `sase-org/sase`, workflow
   `.github/workflows/release.yml`, environment `pypi`.
4. Add the `master` commit-message ruleset and local hook.
5. Add release PR staleness auditor; then choose scheduled auto-merge or full auto-merge for Release Please PRs.
6. Codify package-family order: `sase-core-rs` first, then `sase`, then plugins with dependency bounds pointing at
   published versions.

## Sources

- Release Please README: https://github.com/googleapis/release-please
- Release Please Action README: https://github.com/googleapis/release-please-action
- Release Please Python strategy source:
  https://raw.githubusercontent.com/googleapis/release-please/main/src/strategies/python.ts
- GitHub rulesets / metadata restrictions:
  https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository
- GitHub available rules for rulesets:
  https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets
- GitHub Actions concurrency:
  https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
- GitHub scheduled workflows:
  https://docs.github.com/actions/using-workflows/events-that-trigger-workflows#schedule
- GitHub auto-merge:
  https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request
- PyPI Trusted Publishing:
  https://docs.pypi.org/trusted-publishers/using-a-publisher/
- PyPI file reuse / deletion policy: https://pypi.org/help/
- pip pre-release behavior: https://pip.pypa.io/en/stable/cli/pip_install/
- Current PyPI `sase` state checked on 2026-06-09: https://pypi.org/project/sase/
- Current PyPI JSON endpoints checked on 2026-06-09:
  https://pypi.org/pypi/sase/json,
  https://pypi.org/pypi/sase-core-rs/json,
  https://pypi.org/pypi/sase-github/json,
  https://pypi.org/pypi/sase-telegram/json
