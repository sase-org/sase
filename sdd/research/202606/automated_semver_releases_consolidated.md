# Automated SemVer Releases for SASE

Date: 2026-06-08

## Research Request

Find release automation options for `sase`, `sase-core`, and SASE plugins so new commits can produce new SemVer-style
versions, with the bump inferred from Conventional Commit prefixes, while staying in `0.y.z` zero-ver for now. End with
a recommended solution.

## Executive Summary

Use a release-PR model, not immediate publish-on-every-push, as the default. A bot should keep a release PR updated from
new default-branch commits; merging that PR creates the version bump, changelog, tag, and GitHub Release. That still
responds continuously to commits, but avoids burning immutable PyPI versions for every raw commit burst.

Recommended split:

| Repo | Recommendation | Why |
| --- | --- | --- |
| `sase` | Release Please, `release-type: python` | Good Python version/changelog/tag support and exact pre-1.0 bump controls. |
| `sase-github` | Release Please, `release-type: python` | Same as `sase`; existing tag-triggered PyPI publish already uses Trusted Publishing. |
| `sase-telegram` | Release Please, `release-type: python` | Same package shape as `sase-github`, but needs a PyPI publish workflow added first or during rollout. |
| `sase-core` | release-plz | Rust workspace support plus `cargo-semver-checks` API-break detection, which Release Please does not provide. |
| `sase-nvim` | Release Please, `release-type: simple` | Lua plugin with no package manifest found; use a `VERSION`/`version.txt`, changelog, tag, and GitHub Release. |

Add Conventional Commit enforcement before relying on automation. The release tools can only infer a correct bump if the
commit that reaches the default branch says what actually changed.

## Current State Checked

Local primary checkouts and this workspace show:

| Repo | Current version state | Current publish state |
| --- | --- | --- |
| `sase` | `pyproject.toml` version `0.1.0`; `src/sase/__init__.py` also has `__version__ = "0.1.0"` | `.github/workflows/publish.yml` runs on `v*` tags and uses PyPI Trusted Publishing. |
| `sase-core` | root Cargo workspace version `0.1.1`; `crates/sase_core_py/pyproject.toml` also has static `0.1.1` | `.github/workflows/release.yml` runs on `v*` tags, builds maturin wheels, and currently publishes through `PYPI_API_TOKEN` if present. |
| `sase-github` | `pyproject.toml` version `0.1.0`; no `__version__` string found in package init | `.github/workflows/publish.yml` runs on `v*` tags and uses PyPI Trusted Publishing. |
| `sase-telegram` | `pyproject.toml` version `0.1.0`; no `__version__` string found in package init | No `.github/workflows/` publish workflow found in the primary checkout. |
| `sase-nvim` | Lua plugin files only; no package manifest/version file found | No release workflow found. |

## Version Policy

SemVer says normal versions are `MAJOR.MINOR.PATCH`, with patch for compatible bug fixes, minor for compatible
functionality, and major for incompatible API changes. SemVer also says `0.y.z` is initial development and the public API
is not stable.

Conventional Commits maps `fix:` to patch, `feat:` to minor, and either `!` or a `BREAKING CHANGE:` footer to major.
Other types are allowed but have no inherent SemVer effect.

Recommended SASE zero-ver policy:

| Commit class | Normal SemVer | SASE zero-ver policy |
| --- | --- | --- |
| `fix:` / `perf:` | patch | patch |
| `feat:` | minor | patch |
| `type!:` / `BREAKING CHANGE:` | major | minor |
| `docs:` / `ci:` / `test:` / `chore:` / `refactor:` / `build:` | none by default | none by default |

The reason to make `feat:` a patch during `0.y.z` is dependency ergonomics: reserve `0.MINOR.0` as the compatibility
line. A breaking `sase-core-rs` release from `0.1.x` to `0.2.0` should force `sase` to review its dependency range;
compatible fixes and features can stay within `0.1.x`.

If you literally want every commit to create a public version, configure non-releasable types as patch releases. I do
not recommend that for SASE because PyPI versions cannot be replaced and doc/CI-only versions make the public changelog
noisy.

## Tooling Options

### Release Please

Release Please parses Conventional Commits, maintains release PRs, updates changelogs and language-specific version
files, tags merged release PRs, and creates GitHub Releases. It explicitly does not publish to package managers; your
workflow remains responsible for PyPI or other publishing.

Strengths:

- Good fit for `sase`, `sase-github`, and `sase-telegram`.
- Supports `python`, `rust`, and `simple` strategies, though Rust workspace support requires manifest configuration.
- Has the exact zero-ver knobs SASE wants:
  - `bump-minor-pre-major: true`: breaking changes on `0.y.z` bump minor instead of `1.0.0`.
  - `bump-patch-for-minor-pre-major: true`: `feat:` on `0.y.z` bumps patch instead of minor.
- Supports `Release-As: x.y.z` for manual overrides.
- Supports `extra-files` for version strings that the built-in Python updater misses.

Caveats:

- It does not detect real API breaks; it trusts commit text.
- The Python strategy should be dry-run-verified on SASE's `src/` layout. If it does not update
  `src/sase/__init__.py`, either add `extra-files` annotations or remove the duplicate runtime version string and use
  package metadata as the single source of truth.
- Release Please docs note that Python can treat `docs` commits as releasable units. If SASE does not want doc-only
  package releases, use commit policy such as `chore(docs): ...` for non-package docs or verify/configure release note
  behavior during the pilot.

### release-plz

release-plz is the best fit for `sase-core`. It is Rust-specific, creates release PRs, updates Cargo versions and
changelogs, creates tags/GitHub Releases, supports workspaces, and integrates `cargo-semver-checks` to detect public Rust
API breaking changes.

Important verified details:

- Its default zero-ver behavior matches the recommended Rust policy: breaking changes move `0.x.y` to `0.(x+1).0`, while
  feature/fix commits stay in the patch component unless `features_always_increment_minor = true`.
- `cargo-semver-checks` is valuable but not perfect; it will not catch every possible semver violation.
- `release = false` is not the way to "skip cargo publish"; it disables package processing entirely, including version
  updates, tags, and releases.
- For a PyPI-wheel-only `sase-core`, use `git_only = true` so release-plz determines versions from git tags and skips
  cargo registry publishing. This is specifically for packages not published to crates.io.
- Set `release_always = false` if you want releases only when the release PR is merged. The release-plz default tries to
  release on every main-branch run.
- If the existing maturin workflow stays tag-triggered on `v*`, set `git_tag_name = "v{{ version }}"` and
  `git_release_name = "v{{ version }}"`; release-plz's default workspace tag can include the package name.
- Avoid duplicate `sase-core` version sources by changing `crates/sase_core_py/pyproject.toml` from a static
  `[project].version` to `dynamic = ["version"]`, letting maturin use the Cargo package version.

Minimal config shape to pilot, not copy-paste final:

```toml
[workspace]
git_only = true
release_always = false
features_always_increment_minor = false
git_tag_name = "v{{ version }}"
git_release_name = "v{{ version }}"

[[package]]
name = "sase_core"
version_group = "sase-core"

[[package]]
name = "sase_core_py"
version_group = "sase-core"
changelog_include = ["sase_core"]
```

Include `sase_gateway` and `sase_xprompt_lsp` in the same `version_group` only if those binaries should share the public
`sase-core` version line.

### Python Semantic Release

Python Semantic Release is the strongest Python-native alternative. It can update `pyproject.toml` plus version variables,
build, tag, create GitHub Releases, and publish from CI. In current docs, `allow_zero_version` defaults to false, so
zero-ver must be explicit:

```toml
[tool.semantic_release]
allow_zero_version = true
major_on_zero = false
```

Trade-offs:

- Very good for Python-only repos and for a fully hands-off push model.
- It does not solve `sase-core`'s Rust workspace/API-break problem.
- With `major_on_zero = false`, breaking changes avoid `1.0.0`, but `feat:` still bumps minor in `0.y.z`; it does not
  directly encode SASE's preferred `feat -> patch` zero-ver policy.

### Commitizen, Cocogitto, semantic-release, cargo-release

These are useful but not the best primary answer:

- Commitizen is excellent for authoring/linting Conventional Commits and can bump versions with
  `major_version_zero = true`, but it is less of a complete release-PR orchestrator.
- Cocogitto is a cross-language Conventional Commits toolbox with bumping, changelogs, and hooks, but SASE would own more
  custom file-stamping and publishing glue.
- semantic-release is mature and highly automated but introduces a Node-centric release stack for Python/Rust/Lua repos.
- cargo-release is a good manual/semi-automated Cargo release helper, but it does not infer the bump from Conventional
  Commits by itself.

## Integration Issues

### GitHub Actions Token Behavior

Events created with the default `GITHUB_TOKEN` generally do not trigger new workflow runs. If a release bot pushes a
`v*` tag using `GITHUB_TOKEN`, existing separate `on: push: tags: ["v*"]` publish workflows may not run.

Use one of these shapes:

1. Preferred: publish in the same workflow, gated by Release Please or release-plz outputs after a release is created.
2. Also acceptable: use a GitHub App token or PAT for the release bot so tag/release events trigger downstream publish
   workflows.
3. Avoid relying on default-token tag pushes to trigger separate publish jobs.

For Python packages, prefer PyPI Trusted Publishing with `id-token: write` and a protected `pypi` environment. `sase` and
`sase-github` already use this pattern; `sase-core` should move away from long-lived `PYPI_API_TOKEN` when practical.

### Cross-Repo Coordination

No reviewed tool cleanly handles dependency choreography across these separate repositories. Treat each repo as
independently releasable:

- `sase-core-rs` patch releases within a zero-ver minor can publish independently while `sase` depends on a compatible
  range such as `>=0.1.1,<0.2.0`.
- A breaking `sase-core-rs` zero-ver minor release should be followed by a `sase` commit updating the dependency range and
  adapting code; that commit creates a `sase` release.
- Compatible `sase` patch releases should not force plugin releases if plugin dependency constraints permit them.
- Breaking `sase` zero-ver minor releases should trigger plugin compatibility commits and plugin releases.

Add Renovate, Dependabot, or a small SASE-owned coordinator later to open cross-repo dependency update PRs. Do not make
that a prerequisite for first release automation.

### Commit Enforcement

Enforce the commit that lands on the default branch, not only local developer commits. With squash merge, a PR-title check
is often the highest leverage because the squash commit title becomes the release unit.

Recommended:

- Add `commitizen check`, `commitlint`, or equivalent in CI for PR titles or merge commits.
- Document the SASE zero-ver mapping.
- Use `Release-As: x.y.z` for explicit overrides and the eventual `1.0.0` promotion.

## Recommended Rollout

1. Pilot Release Please on `sase-github`.
   - Add `release-please-config.json` and `.release-please-manifest.json`.
   - Configure `bump-minor-pre-major: true` and `bump-patch-for-minor-pre-major: true`.
   - Publish in the same workflow on `release_created`, or use a GitHub App/PAT if keeping the tag workflow separate.

2. Add commit enforcement.
   - Enforce Conventional Commit PR titles for squash merges.
   - Decide whether `docs:` should release Python packages; if not, use `chore(docs):` for non-package docs.

3. Roll Release Please to `sase` and `sase-telegram`.
   - For `sase`, verify `src/sase/__init__.py` version handling or remove the duplicate string.
   - For `sase-telegram`, add the missing PyPI publish workflow, preferably Trusted Publishing.

4. Add release-plz to `sase-core`.
   - Use `git_only = true`, `release_always = false`, explicit `v{{ version }}` tags, and `version_group`.
   - Convert the maturin package version to `dynamic = ["version"]`.
   - Move the PyPI wheel publish path to Trusted Publishing or run publish in the same release workflow.

5. Add Release Please `simple` to `sase-nvim`.
   - Add a small version file plus `CHANGELOG.md`.
   - Publish a GitHub Release/tag only unless a plugin-manager registry is introduced.

## Final Recommendation

Use the release-PR model across the package family. Use Release Please for `sase`, `sase-github`, `sase-telegram`, and
`sase-nvim`; use release-plz for `sase-core`.

This split preserves a uniform operational workflow while giving the Rust backend the one capability that matters there:
real API-break detection through `cargo-semver-checks`. Configure zero-ver so breaking changes stay in `0.y.z` by bumping
minor, compatible features/fixes bump patch, and `1.0.0` happens only through an explicit override or config change. Add
commit enforcement and handle the GitHub token/publish-workflow issue during the first pilot.

## Sources

- [Semantic Versioning 2.0.0](https://semver.org/)
- [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)
- [Release Please README](https://github.com/googleapis/release-please)
- [Release Please manifest docs](https://github.com/googleapis/release-please/blob/main/docs/manifest-releaser.md)
- [Release Please customizing docs](https://github.com/googleapis/release-please/blob/main/docs/customizing.md)
- [Release Please Action README](https://github.com/googleapis/release-please-action)
- [release-plz configuration](https://release-plz.dev/docs/config)
- [release-plz semver check](https://release-plz.dev/docs/semver-check)
- [release-plz GitHub quickstart](https://release-plz.dev/docs/github/quickstart)
- [release-plz rationale](https://release-plz.dev/docs/why)
- [maturin Python metadata](https://www.maturin.rs/metadata.html)
- [Python Semantic Release configuration](https://python-semantic-release.readthedocs.io/en/latest/configuration/configuration.html)
- [Commitizen bump docs](https://commitizen-tools.github.io/commitizen/commands/bump/)
- [GitHub Actions workflow triggering](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/)
