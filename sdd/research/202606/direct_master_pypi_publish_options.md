# Direct Master Pushes and Timely PyPI Releases for SASE

Date: 2026-06-09

## Research Request

Understand options for ensuring changes merged or pushed directly to `master` are published to PyPI in a timely and
correct fashion, while continuing to use Release Please for standard SASE releases.

## Executive Summary

Keep Release Please's release-PR model as the canonical stable-release path, but make the release PR low-friction and
add a safety net for direct `master` pushes.

Recommended shape:

1. Treat every `master` push as a release-candidate event, not an immediate package upload.
2. Let Release Please create or update the release PR from releasable Conventional Commit units.
3. Auto-merge the Release Please PR after required checks pass, or make it a one-click protected release gate.
4. Publish to PyPI in the same release workflow when `release_created == true`.
5. Harden the workflow so it builds the release tag/SHA emitted by Release Please, not whatever SHA happened to trigger
   the workflow run.
6. Add a scheduled release auditor/backstop that detects drift between GitHub releases, repository version files, and
   PyPI.
7. Use GitHub rulesets or branch protection to keep direct pushes structured without fully banning them.

This preserves the stable meaning of `pip install -U sase`: users get reviewed, versioned releases with changelogs, not
every raw `master` commit. It also means a direct `fix:` or `feat:` pushed to `master` should flow into a PyPI release
automatically once CI and release checks pass.

## Current SASE State

Local files checked:

- `.github/workflows/release.yml` runs on `push` to `master` and `workflow_dispatch`.
- The `release` job runs `googleapis/release-please-action@v5`.
- The `build`, `install-smoke`, and `publish` jobs only run when `release_created == 'true'`.
- PyPI publishing already uses `pypa/gh-action-pypi-publish@release/v1` with `environment: pypi` and
  `id-token: write`.
- `release-please-config.json` uses `release-type: python`, `include-v-in-tag: true`,
  `include-component-in-tag: false`, and the pre-1.0 controls:
  `bump-minor-pre-major: true` and `bump-patch-for-minor-pre-major: true`.
- `.release-please-manifest.json`, `pyproject.toml`, and `src/sase/__init__.py` are at `0.1.3`.
- PyPI currently reports `sase==0.1.0`, uploaded on 2026-02-23, with provenance pointing at the earlier
  `bbugyi200/sase` repository and `.github/workflows/publish.yml`.
- Local recovery notes already identify that GitHub releases exist through `v0.1.3`, but PyPI publication fell behind
  because the publish smoke gate failed and because a stale queued workflow run created a release while building an
  older package version.

The existing workflow is directionally right: publish from the same workflow that creates the release, not from a
separate tag-triggered workflow. The two main gaps are release-PR latency and release-artifact provenance.

## Release Invariants

For a stable PyPI release, require these invariants:

- The commit that reaches `master` has machine-readable release intent.
- The package version, changelog, Git tag, GitHub Release, and PyPI artifacts agree.
- The wheel/sdist are built from the exact tag or SHA represented by the GitHub Release.
- The same artifacts that pass install smoke tests are the artifacts uploaded to PyPI.
- A missed or failed publish is visible quickly and can be replayed safely from the release tag.

PyPI makes correctness more important than speed: released package contents cannot be modified in place under the same
filename/version. A bad upload requires a new version, a yank, or both.

## What Direct Master Pushes Change

Direct pushes bypass the PR title path, so the actual commit message on `master` becomes the release unit. Release Please
only infers releases from commits it can parse as releasable Conventional Commit units. In the generic Release Please
docs, `feat`, `fix`, and `deps` are releasable units; Python also treats `docs` as releasable. Other types such as
`chore`, `ci`, `test`, or `refactor` may not create a release unless they include breaking-change markers or explicit
configuration.

That is the real control point. If a maintainer pushes behavior-changing code directly as `chore: tweak stuff`,
Release Please can reasonably treat it as not releasable. To allow direct pushes without losing release correctness,
SASE needs commit-message enforcement or at least a fast alert when a direct `master` push has no corresponding release
path.

## Options

### Option 1: Release PR Canonical, Auto-Merged After Checks

Flow:

1. A PR merge or direct push lands on `master`.
2. Release Please runs and creates or updates the release PR if the new commits contain releasable units.
3. The release PR has auto-merge enabled, or a small release-steward workflow enables it only for Release Please PRs.
4. Required CI and release-specific checks run on the release PR.
5. When the release PR merges, Release Please creates the tag and GitHub Release.
6. The same workflow builds, smoke-tests, and publishes the release artifacts to PyPI.

Why this is the best default:

- Keeps Release Please's intended model: release PRs stay current as additional work lands, and merging the release PR is
  the act that tags the release.
- Supports direct `master` pushes: they update the pending release PR.
- Preserves a clear version/changelog commit in the repo.
- Lets SASE choose the latency: manual merge, GitHub auto-merge, or bot-enabled auto-merge after required checks.
- Avoids burning immutable PyPI versions for every small raw commit.

Required hardening:

- Use a real `SASE_RELEASE_TOKEN` from a GitHub App or bot PAT, not only `GITHUB_TOKEN`, if Release Please PR checks and
  auto-merge should run without manual approval.
- Add release workflow concurrency. For release/publish work, prefer queueing over cancellation so an in-progress PyPI
  release is not interrupted. GitHub's current concurrency docs support `queue: max`; if not available in the target
  runner/account yet, use a single concurrency group plus a stale-head guard.
- Add a stale-head guard before invoking Release Please on `push`: compare `github.sha` to the current remote
  `refs/heads/master`; if the run is for an older queued push, skip release creation.
- Export Release Please outputs `tag_name`, `version`, and `sha`.
- Build with `actions/checkout` pinned to the release SHA or tag emitted by Release Please.
- Verify `pyproject.toml` and built artifact metadata match `steps.release.outputs.version`.
- Keep publish separate from build/test with artifact upload/download. The current workflow already follows this
  pattern.
- Keep `id-token: write` scoped only to the publish job. The current workflow already does this.
- Keep `skip_existing: false`; partial or duplicate uploads should fail loudly.

Timeliness:

- With auto-merge enabled for the Release Please PR, latency is roughly CI duration plus PyPI upload/indexing time.
- Without auto-merge, latency is human review time. That is still correct, but not automatic.

### Option 2: Continuous Stable Release on Every Releasable Master Push

This means `master` is treated as production and each releasable commit or batch is published without a release PR.

Possible approaches:

- Switch to a tool designed for push-to-release flows, such as Python Semantic Release.
- Write SASE-owned automation that computes the next version, edits version files/changelog, commits, tags, builds, and
  publishes.
- Try to split Release Please into separate "release PR only" and "GitHub release only" modes, but this is not a clean
  publish-every-push answer because Release Please's documented core model is still release PR first and package-manager
  publishing remains external.

Pros:

- Fastest path from `master` to PyPI.
- Lower release-PR bookkeeping.

Cons:

- Public stable releases become tied to every direct push burst.
- Any direct-push mistake consumes an immutable PyPI version.
- You must decide whether non-code commits publish. If yes, PyPI/changelog noise rises. If no, some direct pushes still
  will not produce a release.
- You lose the release PR as a final version/changelog review point.
- You would need to replace or wrap the current Release Please flow.

Use this only if SASE wants `master == stable production` with no explicit release decision.

### Option 3: Scheduled Release Auditor and Backstop

Add a scheduled workflow, for example every 15 or 30 minutes, that checks:

- latest GitHub release tag vs latest PyPI version,
- `pyproject.toml` and `.release-please-manifest.json` version vs PyPI,
- pending Release Please PR age,
- failed `Release` workflow runs since the latest tag,
- direct `master` commits since the latest release with releasable Conventional Commit types.

Actions it can take:

- re-run a failed release workflow,
- dispatch a manual publish-from-tag path for an already-created GitHub release,
- comment on or label a stale Release Please PR,
- enable auto-merge on the Release Please PR if policy allows,
- open an issue or send a notification when PyPI is behind.

Pros:

- Catches the exact current class of drift: GitHub release exists, PyPI is stale.
- Gives a recovery path for transient CI/PyPI failures.
- Keeps the primary release flow simple.

Cons:

- GitHub scheduled workflows run on the latest default-branch commit, can be delayed under load, and the shortest
  documented interval is five minutes.
- A sweeper is a backstop, not a substitute for a correct release workflow.

This should be added even if Option 1 is adopted.

### Option 4: Direct-Push Guardrails Without Fully Banning Direct Pushes

If direct `master` pushes remain allowed, use repository rulesets/branch protection to constrain them:

- Restrict who can update `master` directly; allow only Bryan and the release bot/App.
- Add a commit metadata ruleset requiring direct `master` commits to match a Conventional Commit regex, with an explicit
  bypass route for emergency commits.
- Evaluate the metadata ruleset first before enforcing it, because GitHub notes that all commits on a squash-merged
  branch must satisfy metadata requirements for the base branch.
- Require linear history to keep release calculation and rollback simple.
- Require signed commits if operationally practical.

This does not publish anything by itself. It makes direct pushes legible enough for release automation to do the right
thing.

### Option 5: Manual Publish-From-Tag Backfill

Add `workflow_dispatch` inputs such as:

- `release_tag`: required for backfill, e.g. `v0.1.3`;
- `publish_pypi`: boolean;
- `dry_run`: boolean.

When `release_tag` is set:

1. Skip Release Please.
2. Check out exactly that tag.
3. Verify tag exists and artifact metadata matches the tag version.
4. Build, smoke-test, and publish the artifacts through the same PyPI job.
5. Fail if the PyPI version already exists.

This is not the main answer for timely direct-push releases, but it is essential operational insurance. The current
`v0.1.3` situation needs this kind of path because Release Please will not emit `release_created=true` again for an
already-created GitHub release.

## Anti-Patterns to Avoid

- Do not rely on a separate `on: release` or `on: push: tags` publish workflow if the tag/release is created with the
  default `GITHUB_TOKEN`. GitHub documents that most events created by `GITHUB_TOKEN` do not trigger new workflow runs.
- Do not build from the default checkout after Release Please creates a release. Build from `tag_name` or `sha`; stale
  queued runs can otherwise create one release while building another version.
- Do not set `skip_existing: true` for the normal PyPI publish job. It can hide duplicate or partial-release mistakes.
- Do not disable the install smoke test just to publish faster. For SASE, the Rust runtime dependency makes install
  smoke a release blocker, not a nice-to-have.
- Do not publish local or ad hoc `twine upload` artifacts outside the GitHub Trusted Publishing path except as an
  explicitly approved emergency process.

## Recommended Implementation Plan

1. Fix release provenance in `.github/workflows/release.yml`.

   Add Release Please outputs for `tag_name`, `sha`, and `version`; check out that exact release ref in `build`; verify
   the package version and artifact metadata before smoke/publish.

2. Add stale-run protection.

   Before invoking Release Please on a `push`, compare the workflow's triggering SHA with the current remote `master`
   SHA. If they differ, exit successfully without creating a release.

3. Add a manual backfill path.

   Support `workflow_dispatch` with `release_tag`, and use it to publish existing GitHub releases such as `v0.1.3` after
   dependencies and Trusted Publishing configuration are ready.

4. Configure PyPI Trusted Publishing for the current repo identity.

   The old PyPI provenance points at `bbugyi200/sase` and `publish.yml`; current releases need PyPI to trust
   `sase-org/sase`, `.github/workflows/release.yml`, and environment `pypi`.

5. Enable release PR auto-merge or a release-steward workflow.

   Start conservatively: auto-merge only Release Please PRs from the release bot, only after required checks pass, and
   optionally only when the release diff touches expected files (`CHANGELOG.md`, version files, manifest).

6. Add a scheduled release auditor.

   Alert when GitHub release/PyPI drift exists, a Release Please PR is stale, or a direct `master` push contains
   releasable commits but no release PR/release is progressing.

7. Add direct-push commit guardrails.

   Use a GitHub ruleset commit-message regex or another server-side control to enforce Conventional Commit subjects for
   commits entering `master`, with a documented emergency bypass.

## Suggested Policy

- A direct `fix:` or `feat:` pushed to `master` should release automatically through the Release Please PR once checks
  pass.
- A direct `chore:`, `ci:`, or `test:` should not release unless it includes `Release-As: x.y.z` or a configured
  release type says it should.
- A direct push that changes runtime behavior but uses a non-releasable type is a policy violation; automation should
  flag it within minutes.
- PyPI publication must always be tied to a Git tag/GitHub Release and Trusted Publishing provenance.

## Sources

- Release Please README: https://github.com/googleapis/release-please
- Release Please Action README: https://github.com/googleapis/release-please-action
- Release Please manifest docs: https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md
- Release Please customizing docs: https://github.com/googleapis/release-please/blob/main/docs/customizing.md
- Conventional Commits 1.0.0: https://www.conventionalcommits.org/en/v1.0.0/
- Semantic Versioning 2.0.0: https://semver.org/
- GitHub `GITHUB_TOKEN` workflow-trigger behavior:
  https://docs.github.com/en/actions/concepts/security/github_token
- GitHub Actions concurrency:
  https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency
- GitHub scheduled workflows:
  https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- GitHub manual workflow dispatch:
  https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow
- GitHub environments:
  https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments
- GitHub rulesets:
  https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
- GitHub ruleset metadata restrictions:
  https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository
- PyPI Trusted Publishing:
  https://docs.pypi.org/trusted-publishers/using-a-publisher/
- PyPA PyPI publish action:
  https://github.com/pypa/gh-action-pypi-publish
- PyPI file-name reuse policy:
  https://pypi.org/help/#file-name-reuse
- Current PyPI `sase` project state checked on 2026-06-09:
  https://pypi.org/project/sase/
