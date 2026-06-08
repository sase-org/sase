---
create_time: 2026-06-08 12:29:08
status: done
bead_id: sase-4e
tier: epic
prompt: sdd/prompts/202606/automated_semver_releases.md
---
# Automated SemVer Release Rollout Plan

## Objective

Implement GitHub Actions release automation for `sase`, `sase-core`, `sase-github`, and `sase-telegram` so the next
releasable PR merged into each repo's default branch causes the appropriate release bot to open or update a release PR,
and merging that release PR creates the GitHub release/tag and publishes the package when publishing is configured.

This follows the prior research in `sdd/research/202606/automated_semver_releases_consolidated.md`. The prompt named
`sdd/research/202606/automated_semver_releases.md`, but that exact file is not present in this checkout.

The implementation should use a release-PR model, not publish directly from arbitrary pull-request events. PyPI versions
are immutable, and Release Please / release-plz are designed to infer a release from commits that have landed on the
default branch.

## Current Baseline

- `sase`
  - Default branch: `master`.
  - Local version: `pyproject.toml` `0.1.0`; `src/sase/__init__.py` also contains `__version__ = "0.1.0"`.
  - PyPI: `sase==0.1.0` exists.
  - Remote `v*` tags: none found with `git ls-remote --tags origin 'v*'`.
  - Existing `.github/workflows/publish.yml` publishes on `v*` tags using PyPI Trusted Publishing and includes a useful
    install smoke test.

- `sase-github`
  - Workspace path: open with `sase workspace open -p sase-github 10`.
  - Default branch: `master`.
  - Local version: `pyproject.toml` `0.1.0`.
  - PyPI: `sase-github==0.1.0` exists.
  - Remote `v*` tags: none found.
  - Existing `.github/workflows/publish.yml` publishes on `v*` tags using PyPI Trusted Publishing.
  - Existing CI workflow is currently configured for `main` even though `origin/HEAD` points to `master`; fix this
    before relying on release PR checks.

- `sase-telegram`
  - Workspace path: open with `sase workspace open -p sase-telegram 10`.
  - Default branch: `master`.
  - Local version: `pyproject.toml` `0.1.0`.
  - PyPI: package not found.
  - Remote `v*` tags: none found.
  - No `.github/workflows/` directory exists yet.

- `sase-core`
  - Workspace path: open with `sase workspace open -p sase-core 10`.
  - Default branch: `master`.
  - Cargo workspace version: `0.1.1`.
  - Python distribution metadata: `crates/sase_core_py/pyproject.toml` has static `version = "0.1.1"` for
    `sase-core-rs`.
  - PyPI: `sase-core-rs` not found.
  - Remote `v*` tags: none found.
  - Existing `.github/workflows/release.yml` builds the maturin wheel matrix on `v*` tags and optionally publishes with
    `PYPI_API_TOKEN`; this should be converted to Trusted Publishing as part of release automation.

## Shared Release Policy

- Use zero-ver SemVer for now:
  - `fix:` and `perf:` -> patch.
  - `feat:` -> patch while still on `0.y.z`.
  - `!` or `BREAKING CHANGE:` -> minor while still on `0.y.z`.
  - non-package changes should not normally release unless we intentionally force a bootstrap release.
- Use `vX.Y.Z` tags for every repo.
- Use one package/release component per repo.
- Build and publish in the same workflow run that creates the release, gated on release-tool outputs, rather than
  depending on a second workflow triggered by a bot-created tag.
- Keep `workflow_dispatch` on release workflows for manual recovery and dry-run diagnostics.
- Prefer a GitHub App/PAT secret such as `SASE_RELEASE_TOKEN` for the release bot token so release PR CI runs. Fall back
  to `secrets.GITHUB_TOKEN` only if the repo owner accepts that bot-created release PRs may not trigger checks.
- All repos need GitHub repository settings that allow Actions to create pull requests. All PyPI-published repos need a
  protected `pypi` environment and PyPI Trusted Publishing configured for the final workflow names.

## Phase 1: Shared Guardrails And Branch Hygiene

Scope: all four repos, minimal release-independent changes.

Deliverables:

- Add a lightweight PR-title Conventional Commit check to every repo. Use a small shell-based workflow rather than a new
  third-party action. It should validate PR titles that will become squash-merge commit titles.
- Make allowed types explicit: `feat`, `fix`, `perf`, `docs`, `ci`, `test`, `chore`, `refactor`, `build`, `deps`, and
  allow optional scopes plus `!`.
- Fix `sase-github` CI triggers from `main` to `master`.
- Do not add release config in this phase unless needed by the title check.

Verification:

- `sase`: run `just install` first if needed, then `just check`.
- `sase-github`: run `just check`.
- `sase-telegram`: run `just check`.
- `sase-core`: run `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and
  `cargo test --workspace`.

Handoff notes:

- This phase reduces the chance that later release bots produce no release because a squash title was not conventional.
- If the first implementation PR itself should trigger a release, the PR title must be a releasable type such as
  `fix(release): add automated release workflow`; `ci:` alone may not release.

## Phase 2: Pilot Release Please On `sase-github`

Scope: `sase-github` only.

Deliverables:

- Add `release-please-config.json` and `.release-please-manifest.json`.
  - Seed the manifest at `0.1.0` because PyPI already has `sase-github==0.1.0`.
  - Configure `release-type: python`, `include-v-in-tag: true`, `include-component-in-tag: false`,
    `bump-minor-pre-major: true`, and `bump-patch-for-minor-pre-major: true`.
  - Use a bootstrap SHA if needed to avoid dumping the entire repository history into the first release notes.
- Add `.github/workflows/release.yml`.
  - Trigger on pushes to `master` and `workflow_dispatch`.
  - Run `googleapis/release-please-action` in manifest mode. The Marketplace currently shows `v5.0.0` as latest; pin the
    chosen major deliberately, and verify inputs against the current action README before landing.
  - On `release_created`, build with `uv build`, upload `dist/`, and publish with
    `pypa/gh-action-pypi-publish@release/v1` using `id-token: write` and environment `pypi`.
- Retire or narrow `.github/workflows/publish.yml` so PyPI publishing is not split across both tag-triggered and
  release-output-triggered paths. If kept, document it as a manual/tag fallback and make duplicate publishing
  impossible.

Expected next version:

- Existing published version is `0.1.0`.
- Next `fix:`, `perf:`, or `feat:` after automation lands should produce `0.1.1`.
- Next breaking change should produce `0.2.0`.

Verification:

- Run `just check`.
- Run `uv build` and inspect wheel/sdist metadata for `Version: 0.1.0` before release automation changes any version.
- Validate JSON/YAML syntax for release config and workflows.

Handoff notes:

- Treat this repo as the pilot. If Release Please's Python strategy does not update `pyproject.toml` correctly in the
  release PR, fix that before copying the pattern to the other Python repos.

## Phase 3: Add Release Please To `sase`

Scope: `sase` only.

Deliverables:

- Add `release-please-config.json` and `.release-please-manifest.json`.
  - Seed the manifest at `0.1.0` because PyPI already has `sase==0.1.0`.
  - Use the same zero-ver and tag configuration from the `sase-github` pilot.
- Make `src/sase/__init__.py` version handling release-safe.
  - Either add a Release Please generic extra-file annotation to the `__version__` line, or remove the duplicate static
    source and load version through package metadata. Prefer the smaller change unless the codebase already has a clear
    metadata-version pattern.
- Replace the tag-triggered publish dependency with an integrated `.github/workflows/release.yml`.
  - Preserve the existing install smoke test from `.github/workflows/publish.yml`.
  - Build and publish only when Release Please reports `release_created`.
  - Keep Trusted Publishing with `id-token: write` and environment `pypi`.
- Retire or narrow the old `publish.yml` as in Phase 2.

Expected next version:

- Existing published version is `0.1.0`.
- Next `fix:`, `perf:`, or `feat:` should produce `0.1.1`.
- Next breaking change should produce `0.2.0`.

Verification:

- Run `just install`.
- Run `just check`.
- Run `uv build`.
- Run the same fresh-venv install smoke that the current publish workflow uses if practical locally; otherwise preserve
  the workflow smoke exactly and note local limitations.

Handoff notes:

- `sase` depends on `sase-core-rs>=0.1.1,<0.2.0`, but `sase-core-rs` is not currently on PyPI. Do not publish a `sase`
  release that cannot resolve its runtime dependency unless `sase-core-rs` has been published first or the publish smoke
  explicitly confirms the dependency can resolve.

## Phase 4: Add Release Please And First Publish Path To `sase-telegram`

Scope: `sase-telegram` only.

Deliverables:

- Add CI under `.github/workflows/ci.yml` if Phase 1 did not already add it.
  - Trigger on pushes and pull requests to `master`.
  - Use `uv`, `extractions/setup-just@v2` or the repo's established equivalent, `just lint`, and `just test`.
- Add `release-please-config.json` and `.release-please-manifest.json`.
  - Because PyPI has no `sase-telegram` package, bootstrap deliberately. The first automated publish should be `0.1.0`
    unless a product decision is made to skip to `0.1.1`.
  - Use Release Please bootstrap options (`initial-version`, empty manifest, or manual manifest seed plus `Release-As`)
    only after dry-running the behavior. Do not accidentally create `0.1.1` as the first public release unless that is
    explicitly accepted in the phase notes.
  - Use the same zero-ver and `vX.Y.Z` tag policy as the other Python repos.
- Add `.github/workflows/release.yml`.
  - Trigger on pushes to `master` and `workflow_dispatch`.
  - Build with `uv build`, upload artifacts, optionally perform a basic fresh-venv import/entry-point smoke, and publish
    with PyPI Trusted Publishing on `release_created`.

Expected next version:

- No published PyPI package exists.
- Preferred first public release is `0.1.0`.
- After `0.1.0` exists, the normal zero-ver mapping applies: compatible changes -> `0.1.1`, breaking -> `0.2.0`.

Verification:

- Run `just check`.
- Run `uv build`.
- Install the built wheel in a fresh venv and import `sase_telegram`; run command entry point help if dependencies
  allow.

Handoff notes:

- This phase requires PyPI Trusted Publishing to be configured for `sase-telegram`. If that is not ready, keep the
  workflow mergeable but document that publish will fail until the PyPI project/environment is created.

## Phase 5: Add release-plz To `sase-core`

Scope: `sase-core` only.

Deliverables:

- Add `release-plz.toml`.
  - Use `git_only = true` because `sase-core` is not publishing Rust crates to crates.io.
  - Use `release_always = false` so the release PR controls when version/changelog changes land.
  - Keep `features_always_increment_minor = false` for Cargo-style zero-ver behavior.
  - Use `git_tag_name = "v{{ version }}"` and `git_release_name = "v{{ version }}"`.
  - Use a version group for `sase_core` and `sase_core_py` so the Rust core and PyO3 package move together.
  - Include `sase_gateway` and `sase_xprompt_lsp` in that version group only if those binaries are intentionally part of
    the public `sase-core` release line.
- Convert `crates/sase_core_py/pyproject.toml` away from static duplicate versioning.
  - Prefer `dynamic = ["version"]` so maturin derives the Python distribution version from Cargo metadata.
- Add `.github/workflows/release-plz.yml`.
  - Trigger on pushes to `master` and `workflow_dispatch`.
  - Run `release-plz release` first and `release-plz release-pr` second, following release-plz's current quickstart.
  - Gate on `github.repository_owner == 'sase-org'`.
  - Use the release-plz action's release outputs (`releases_created`, `releases`) to decide whether to build/publish
    `sase-core-rs` wheels in the same workflow.
- Convert the existing maturin release workflow into either:
  - a reusable workflow called by release-plz when a release is created, or
  - the build/publish jobs inside `release-plz.yml`.
- Move PyPI publication from `PYPI_API_TOKEN` to Trusted Publishing with `id-token: write` and environment `pypi`.
- Keep the existing wheel matrix and smoke tests intact unless a simplification is required to make the workflow
  callable.

Expected next version:

- No `sase-core-rs` package is published on PyPI.
- Current Cargo/Python version is `0.1.1`, and `sase` already depends on `sase-core-rs>=0.1.1,<0.2.0`.
- Preferred first public release is therefore `0.1.1`.
- After `0.1.1` exists, compatible changes stay in `0.1.x`; breaking changes move to `0.2.0`.

Verification:

- Run `cargo fmt --all -- --check`.
- Run `cargo clippy --workspace --all-targets -- -D warnings`.
- Run `cargo test --workspace`.
- Build the local maturin wheel and run the import/query smoke from the existing workflow.
- Run release-plz locally in dry-run mode if available, or at least validate that `release-plz.toml` is accepted by the
  current release-plz action/CLI.

Handoff notes:

- This phase should happen before any new `sase` release that depends on the published Rust wheel.
- Watch for release-plz's workspace tag defaults. The config must produce `v0.1.1`, not `sase_core-v0.1.1`, unless the
  repo owner explicitly chooses component tags.

## Phase 6: End-To-End Release Audit

Scope: all four repos after Phases 1-5 have landed.

Deliverables:

- Confirm every release workflow targets `master`.
- Confirm every repo has exactly one automated PyPI publishing path.
- Confirm bot-created release PRs can run CI. If not, add/configure a GitHub App/PAT token and wire it into Release
  Please/release-plz.
- Confirm PyPI Trusted Publishing is configured for:
  - `sase` workflow `Release`.
  - `sase-github` workflow `Release`.
  - `sase-telegram` workflow `Release`.
  - `sase-core-rs` workflow name chosen in Phase 5.
- Confirm the first expected version per repo:
  - `sase`: next compatible release `0.1.1`.
  - `sase-github`: next compatible release `0.1.1`.
  - `sase-telegram`: first release `0.1.0` unless Phase 4 explicitly chose `0.1.1`.
  - `sase-core-rs`: first release `0.1.1`.
- Open or inspect the bot release PRs after one releasable commit lands and verify that changelog/version/tag names are
  correct before merging any release PR.

Verification:

- Use GitHub Actions run logs and release PR diffs as the source of truth.
- Check PyPI after publish:
  - `https://pypi.org/project/sase/`
  - `https://pypi.org/project/sase-github/`
  - `https://pypi.org/project/sase-telegram/`
  - `https://pypi.org/project/sase-core-rs/`
- Install the published packages into a fresh environment in dependency order: `sase-core-rs`, `sase`, then plugins.

## Reference URLs Consulted

- Release Please Action Marketplace / README: `https://github.com/marketplace/actions/release-please-action`
- Release Please manifest docs: `https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md`
- Release Please customizing docs: `https://github.com/googleapis/release-please/blob/main/docs/customizing.md`
- release-plz quickstart: `https://release-plz.dev/docs/github/quickstart`
- release-plz config: `https://release-plz.dev/docs/config`
- release-plz outputs: `https://release-plz.dev/docs/github/output`
- release-plz GitHub token note: `https://release-plz.dev/docs/github/token`
