# Automated SemVer Release Research for the SASE Package Family

Date: 2026-06-08

## Question

What release automation should SASE use so `sase`, `sase-core`, and SASE plugins get new SemVer-style versions when
new commits land, with the bump inferred from Conventional Commit prefixes, while staying on `0.y.z` zero-ver for now?

## Current SASE Release Shape

This note builds on `sdd/research/202605/public_release_process_and_install_research.md`, which covered first-public
release packaging, PyPI, and install mechanics. This note focuses on recurring automated versioning and release
orchestration.

Current local state reviewed:

| Repo | Current version source | Current tags/workflow | Notes |
| --- | --- | --- | --- |
| `sase` | `pyproject.toml`: `0.1.0` | `v0.1.0`; `.github/workflows/publish.yml` publishes tag builds to PyPI via Trusted Publishing | Python host package with `sase-core-rs>=0.1.1,<0.2.0`. |
| `sase-core` | root `Cargo.toml` workspace version `0.1.1`; `crates/sase_core_py/pyproject.toml` also `0.1.1` | no local `v*` tags seen; `.github/workflows/release.yml` builds PyO3 wheels on `v*` tags | Publishes the Python distribution `sase-core-rs`; not currently a crates.io-oriented release. Workflow still uses a `PYPI_API_TOKEN` path. |
| `sase-github` | `pyproject.toml`: `0.1.0` | `v0.1.0`; publish workflow via PyPI Trusted Publishing | Python plugin package. Dependency still `sase>=0.1.0`. |
| `sase-telegram` | `pyproject.toml`: `0.1.0` | no local `v*` tags seen; no publish workflow found | Python plugin package with console scripts. Dependency still `sase>=0.1.0`. |
| `sase-nvim` | no package manifest/version file found | no local `v*` tags seen | Lua Neovim plugin; likely GitHub tags/releases only for now. |

## Baseline Version Policy

The SemVer spec maps normal releases as `MAJOR.MINOR.PATCH`, with major for incompatible API changes, minor for
backward-compatible functionality, and patch for backward-compatible bug fixes. It also explicitly says major version
zero is for initial development and the public API should not be considered stable.

Conventional Commits maps:

- `fix:` to patch.
- `feat:` to minor.
- `!` or `BREAKING CHANGE:` to major.
- Other types are allowed but have no inherent SemVer effect unless tooling assigns one.

For SASE's zero-ver period, use a stricter pre-1.0 policy than raw Conventional Commits:

| Commit class | Raw SemVer impact | Recommended zero-ver impact |
| --- | --- | --- |
| `fix:` / `perf:` | patch | patch |
| `feat:` | minor | patch |
| `type!:` / `BREAKING CHANGE:` | major | minor |
| `docs:` / `ci:` / `test:` / `chore:` / `refactor:` / `build:` | none by default | none by default |

Rationale: while the packages are `0.y.z`, reserve the minor component as the compatibility line. That means a
compatible feature in `0.2.1` can still satisfy plugin constraints like `sase>=0.2,<0.3`, while a breaking host change
goes to `0.3.0` and intentionally forces plugin dependency review.

If every commit must literally publish a new version, make non-releasable commit types patch releases. I do not
recommend that for SASE; PyPI versions are immutable, and burning public versions for doc-only or CI-only changes makes
rollback and user-facing changelogs noisier.

## Solution Options

### Release Please

Release Please parses Conventional Commits, maintains release PRs, updates changelogs and version files, then tags and
creates GitHub releases when the release PR is merged. It explicitly does not publish to package managers; publication
must be handled by your workflow.

Strengths for SASE:

- Native support for Python, Rust, and simple repositories.
- A release PR gives a review point before burning immutable PyPI versions.
- Supports manifest config even for single-package repos.
- Has zero-ver controls: `bump-minor-pre-major` and `bump-patch-for-minor-pre-major`.
- Has `Release-As: x.y.z` for manual overrides when commit prefixes are wrong or a coordinated release needs a fixed version.
- Existing SASE tag-triggered publish workflows can be refactored into downstream jobs after Release Please creates a release.

Important caveat: if Release Please uses the default `GITHUB_TOKEN`, the release PR/tag/release it creates will not
trigger separate GitHub Actions workflows. Either publish in the same workflow using Release Please outputs, or use an
explicit PAT/fine-grained token if you want generated tags/releases to trigger existing `on: push: tags` workflows.

Fit:

- Best general fit for this package family.
- For `sase`, `sase-github`, and `sase-telegram`, use `release-type: python`.
- For `sase-core`, use `release-type: rust` plus `cargo-workspace` where needed, and verify that both the root Cargo
  workspace version and `crates/sase_core_py/pyproject.toml` are updated. If the Rust strategy does not update the
  PyO3 package metadata, add `extra-files` or a small version-sync check.
- For `sase-nvim`, use `release-type: simple` and add a `CHANGELOG.md` plus optional `VERSION` file.

### Python Semantic Release

Python Semantic Release determines the next version, stamps configured version variables/files, builds a changelog,
commits, tags, and creates a GitHub release. It provides official GitHub Actions and can run a configured build command.
It has zero-version support; with `major_on_zero = false`, breaking changes on `0.y.z` are reduced to a minor bump.

Strengths:

- Very natural for `sase`, `sase-github`, and `sase-telegram`.
- Can write version values in `pyproject.toml` and other Python files.
- Can build inside the release step.

Weaknesses for SASE:

- Not a strong fit for the Rust/PyO3 workspace unless wrapped with custom scripts.
- No full monorepo support; multi-package releases require repeated action invocations.
- Its default model is a direct version commit/tag from CI, not a release PR review loop.
- Its zero-ver behavior does not provide the exact policy "feat -> patch, breaking -> minor" as directly as Release Please.

Fit:

- Good fallback if SASE wants direct fully automated releases with little review.
- Less attractive for a mixed Python/Rust/Lua package family.

### Cocogitto

Cocogitto is a Conventional Commits toolbox. `cog bump --auto` calculates the next version from commits since the latest
SemVer tag, updates the changelog, creates a version commit and tag, and can run pre/post bump hooks. It treats `0.y.z`
versions specially and will not auto-bump to `1.0.0`.

Strengths:

- One small Rust CLI can be used across Python, Rust, and Lua repos.
- Strong Conventional Commit validation and commit helper UX.
- Dry-run mode can expose the next version to custom scripts.
- Hooks can update arbitrary files.

Weaknesses for SASE:

- File stamping is hook/script-driven rather than ecosystem-native.
- Package publishing is entirely custom.
- Cocogitto's docs warn that post-bump hook failures can leave an undefined state.
- Its built-in zero-ver behavior avoids `1.0.0`, but does not directly encode "feat -> patch" in the same first-class way Release Please does.

Fit:

- Good for commit validation and local ergonomics.
- Viable as a scriptable release engine, but more custom glue than Release Please.

### semantic-release

semantic-release is the classic fully automated CI release tool. It runs after successful CI on release branches,
analyzes commits since the last tag, generates notes, tags, and publishes through plugins. By default, it uses the
Angular commit convention and maps `fix`/`feat`/breaking commits to patch/minor/major.

Strengths:

- Mature and widely used.
- Designed for "run on every successful release-branch build."
- Plugin architecture can support many ecosystems.

Weaknesses for SASE:

- Node-based toolchain for Python/Rust/Lua repos.
- Python and Rust support depends on plugins or custom `prepare`/`publish` commands.
- Direct auto-publish is higher risk with immutable PyPI releases.
- Zero-ver policy would need custom release rules/plugin configuration rather than being as direct as Release Please's pre-major flags.

Fit:

- Reasonable if SASE wants maximum automation and accepts more JavaScript-based release plumbing.
- Not my preferred path for this repo set.

### release-plz

release-plz is Rust-focused release automation. It creates release PRs from CI, updates Cargo package versions and
changelogs based on Conventional Commits, supports Cargo workspaces, can check Rust API breakage with
`cargo-semver-checks`, tags releases, and publishes to Cargo registries.

Strengths:

- Excellent for crates.io-oriented Rust workspaces.
- Strong Rust workspace and Cargo dependency behavior.
- Release PR model aligns with the desired review gate.

Weaknesses for SASE:

- `sase-core`'s public artifact is currently the PyPI package `sase-core-rs` built with maturin, not a crates.io release.
- Does not solve Python plugin or Neovim plugin releases.
- Would still need a separate PyPI wheel publishing pipeline.

Fit:

- Useful only if `sase-core` later publishes first-class crates to crates.io.
- Not enough as the shared release solution.

### cargo-release

`cargo-release` extends `cargo publish` with release validation, version changes, tagging, pushing, workspace support,
dependent crate updates, search/replace, and hooks. It is dry-run by default and executes only with `--execute`.

Strengths:

- Good manual or semi-automated Rust release helper.
- Mature Cargo workspace behavior.
- Useful if `sase-core` adds crates.io publishing.

Weaknesses for SASE:

- It does not infer the bump from Conventional Commits by itself.
- It is Rust-only.
- It does not handle PyPI wheel publishing.

Fit:

- Not a primary answer to this request.
- Could be used under Cocogitto hooks, but that is more custom than Release Please.

## Cross-Repo Coordination

No researched tool cleanly solves cross-repository dependency orchestration for this exact topology. Treat each repo as
independently releasable, and let dependency constraints define when dependents must release:

- `sase-core-rs` compatible patches can release independently while `sase` depends on a compatible range, for example
  `sase-core-rs>=0.1.1,<0.2.0`.
- A breaking `sase-core-rs` zero-ver minor release, for example `0.2.0`, needs a commit in `sase` updating the
  dependency range and adapting code. That commit then triggers a `sase` release.
- Compatible `sase` patch releases should not force plugin releases if plugin dependencies are constrained like
  `sase>=0.2,<0.3`.
- Breaking `sase` zero-ver minor releases, for example `0.3.0`, should trigger plugin compatibility commits and plugin
  releases.
- `sase-nvim` can tag independently unless it requires a new `sase lsp` surface.

Use Renovate, Dependabot, or a small SASE-owned "release coordinator" workflow later to open dependency bump PRs across
repos. Do not make that a prerequisite for the first automation pass.

## Recommended Implementation Shape

1. Add Release Please to every public repo.

   Use manifest configuration even for one-package repos. Configure:

   ```json
   {
     "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
     "include-v-in-tag": true,
     "bump-minor-pre-major": true,
     "bump-patch-for-minor-pre-major": true,
     "packages": {
       ".": {
         "package-name": "sase",
         "release-type": "python"
       }
     }
   }
   ```

   Adjust `package-name` and `release-type` per repo:

   | Repo | Release Please type |
   | --- | --- |
   | `sase` | `python` |
   | `sase-core` | `rust`, with workspace/PyO3 pyproject sync verified |
   | `sase-github` | `python` |
   | `sase-telegram` | `python` |
   | `sase-nvim` | `simple` |

2. Keep the release PR gate.

   On every push to `main`, Release Please should open or update a release PR containing the version bump and
   changelog. The release happens when that PR is merged. This still responds continuously to commits, but avoids
   publishing immutable package versions with no human review.

3. Publish from the same workflow after Release Please reports a release was created.

   Prefer a combined workflow shape:

   - `release-please` job opens/updates release PRs or reports `release_created`.
   - if `release_created == true`, downstream build/smoke/publish jobs run.
   - Python packages use `pypa/gh-action-pypi-publish@release/v1` with `id-token: write` and a protected `pypi`
     environment.
   - `sase-core` builds the maturin wheel matrix, smokes wheels, runs `twine check`, then publishes with PyPI Trusted
     Publishing instead of `PYPI_API_TOKEN`.
   - `sase-nvim` only needs a GitHub Release unless a plugin-manager registry is introduced later.

   If SASE keeps separate tag-triggered publish workflows, Release Please must use a PAT/fine-grained token whose
   generated tags can trigger those workflows. That adds credential management; the same-workflow approach is cleaner.

4. Enforce Conventional Commits before merge.

   Use a PR title or merge-commit check so the commit that lands on `main` is conventional. Prefer squash-merge for
   public repos so a PR's final merged commit is the release-note unit. Allow manual overrides with `Release-As: x.y.z`
   for coordinated releases and corrections.

5. Encode the SASE zero-ver policy in docs.

   Document the rule clearly:

   - While major is `0`, breaking changes bump minor.
   - While major is `0`, compatible features and fixes bump patch.
   - `1.0.0` is manual only, via an explicit release PR or `Release-As: 1.0.0`.

## Recommended Solution

Use Release Please as the common version/changelog/tag front-end across `sase`, `sase-core`, `sase-github`,
`sase-telegram`, and `sase-nvim`, configured with `bump-minor-pre-major: true` and
`bump-patch-for-minor-pre-major: true`. Keep package publishing as explicit GitHub Actions jobs gated on Release Please's
`release_created` output, using PyPI Trusted Publishing for Python artifacts and the existing maturin wheel matrix for
`sase-core`.

This gives SASE the Conventional Commit-derived bumping the user wants, preserves zero-ver until an intentional
`1.0.0`, works across Python/Rust/Lua repos with the least custom glue, and avoids the biggest operational risk:
automatically burning immutable PyPI versions from every raw default-branch push.

## Sources

- Semantic Versioning 2.0.0: https://semver.org/
- Conventional Commits 1.0.0: https://www.conventionalcommits.org/en/v1.0.0/
- Release Please README: https://github.com/googleapis/release-please
- Release Please Action README: https://github.com/googleapis/release-please-action
- Release Please manifest docs: https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md
- Python Semantic Release GitHub Actions docs: https://python-semantic-release.readthedocs.io/en/stable/configuration/automatic-releases/github-actions.html
- Python Semantic Release configuration docs: https://python-semantic-release.readthedocs.io/en/latest/configuration/configuration.html
- Cocogitto automatic versioning docs: https://docs.cocogitto.io/guide/bump
- Cocogitto configuration reference: https://docs.cocogitto.io/reference/config.html
- semantic-release README: https://github.com/semantic-release/semantic-release
- release-plz docs: https://release-plz.dev/docs
- release-plz GitHub quickstart: https://release-plz.dev/docs/github/quickstart
- cargo-release README: https://github.com/crate-ci/cargo-release
- Cargo publishing docs: https://doc.rust-lang.org/cargo/reference/publishing.html
- PyPI Trusted Publishers docs: https://docs.pypi.org/trusted-publishers/
