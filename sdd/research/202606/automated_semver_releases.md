# Automated SemVer Releases from Conventional Commits (with 0ver)

**Goal:** Automatically cut new semantic-version releases of `sase`, `sase-core`, and
sase's plugins (`sase-github`, `sase-telegram`, `sase-nvim`) whenever commits land,
where the bump size (patch / minor / major) is derived from the Conventional Commit
prefix (`fix:` → patch, `feat:` → minor, breaking → major). All projects should stay
in **zero-version / 0ver** (`0.x.y`) for a while, so the normal "breaking → major"
rule must be remapped while the major version is `0`.

This file surveys the available tooling, explains the 0ver wrinkle (the only part of
this that is genuinely subtle), and ends with a concrete recommendation and rollout
plan.

---

## 1. Current state (what we're starting from)

All repos share the same **manual** release pattern today — there is no
version automation, no changelog generation, and no commit-message enforcement.

| Repo | Lang / build | Version source | Current ver | Release trigger | Publish target |
|------|--------------|----------------|-------------|-----------------|----------------|
| `sase` | Python / hatchling | static string in `pyproject.toml` **and** `src/sase/__init__.py:__version__` (must be kept in sync by hand) | `0.1.0` | manual push of a `v*` tag → `.github/workflows/publish.yml` | PyPI (trusted publishing / OIDC) |
| `sase-core` | Rust cargo workspace (4 crates) + maturin Python wheel | workspace `version` in root `Cargo.toml`, inherited by all crates via `version.workspace = true` | `0.1.1` | manual `v*` tag → `.github/workflows/release.yml` | PyPI wheel via maturin (`sase_core_py` is `publish = false`); crates.io currently unused |
| `sase-github` (and presumably `sase-telegram`, `sase-nvim`) | Python / hatchling | static string in `pyproject.toml` | `0.1.0` | manual `v*` tag → `publish.yml` | PyPI |

Key facts that shape the recommendation:

- **Separate repos, not a monorepo.** Each project releases independently, so
  monorepo-manifest features are a nice-to-have, not a requirement.
- **Existing publish workflows already fire on `push: tags: ['v*']`.** Any solution
  should *produce that tag* and let the existing, already-working publish jobs run —
  rather than reinventing the build/publish step.
- **`sase-core` is the shared Rust backend** (see `memory/short/rust_core_backend_boundary.md`).
  Its public API is what the Python/TUI frontends bind to, so *correctly detecting API
  breaking changes* there is worth more than in the leaf Python packages.
- **The team already writes Conventional Commits in practice** (recent log: `chore:`,
  `fix:`) but nothing *enforces* it. Automation quality is bounded by commit hygiene,
  so enforcement is a prerequisite, not an afterthought.

---

## 2. Background: Conventional Commits → SemVer, and the 0ver remap

### Standard mapping (version ≥ 1.0.0)

| Commit | Bump | Example |
|--------|------|---------|
| `fix:` | patch | 1.2.3 → 1.2.4 |
| `feat:` | minor | 1.2.3 → 1.3.0 |
| `feat!:` / `fix!:` / `BREAKING CHANGE:` footer | major | 1.2.3 → 2.0.0 |
| `chore:`/`docs:`/`refactor:`/`test:`/`ci:`/`style:` | (usually) none | — |

### The 0ver wrinkle

SemVer §4 says "anything MAY change at any time" while major is `0`, and the
Conventional Commits spec explicitly leaves the 0.x mapping to the tool. The behavior
we want during 0ver is:

| Commit | Desired 0ver bump | Example |
|--------|-------------------|---------|
| breaking | **minor** (NOT major — stay in 0.x) | 0.4.2 → 0.5.0 |
| `feat:` | patch (or minor — a taste choice) | 0.4.2 → 0.4.3 |
| `fix:` | patch | 0.4.2 → 0.4.3 |

The single most important configuration decision for this project is therefore:
**"do not promote to 1.0.0 on a breaking change; bump the minor instead."** Every tool
below supports this, but via a *different config knob* — those knobs are the crux of
the comparison and are tabulated in §5.

Promotion to `1.0.0` later is a deliberate, one-line config flip (or a manual
`set-version`) — covered per-tool in §5.

---

## 3. Candidate solutions

Two near-orthogonal design axes matter:

- **Axis A — trigger model:**
  - *Push / publish-on-merge*: every push to `main` with a releasable commit
    immediately bumps, tags, and publishes. Most literal reading of "release whenever
    commits are made," but publishes a release per push and offers no review gate.
  - *Release-PR*: a bot maintains an open "release X.Y.Z" PR that accumulates the
    pending changelog + version bump; **merging that PR** cuts the release (creates the
    tag/GitHub Release). Batches rapid commits into one sensible release and gives a
    human review point. This is the current de-facto best practice.
- **Axis B — coverage:** one unified tool across Python + Rust, vs. best-of-breed per
  ecosystem.

### Python-oriented tools

**python-semantic-release (PSR)** — the mature Python-native option. Lives entirely in
`[tool.semantic_release]` in `pyproject.toml`. Default trigger model is *push*: a CI job
on `main` analyzes commits, bumps the version, updates the changelog, commits, tags,
builds, publishes to PyPI, and creates the GitHub Release — fully hands-off. Can update
multiple version locations (`version_toml = ["pyproject.toml:project.version"]` +
`version_variables = ["src/sase/__init__.py:__version__"]`), which exactly solves our
dual-version-string problem. 0ver via `allow_zero_version = true` (default) +
`major_on_zero = false`. *Limitation:* no "feat → patch in 0.x" knob — with
`major_on_zero=false`, both `feat:` and breaking map to a minor bump in 0.x (only `fix:`
is patch). Single-package focused (fine — our repos are separate).

**commitizen (`cz bump`)** — lighter; great at the *commit* end (interactive
`cz commit`, commit-message linting via `cz check`) and does version bump + changelog.
0ver via `major_version_zero = true`. Typically wired as: `cz bump` in CI creates the
tag, existing publish workflow does the rest. Less "all-in-one" publishing than PSR, but
pairs naturally with our existing tag-triggered publish jobs and doubles as the
commit-lint tool.

### Rust-oriented tools

**release-plz** — the Rust analog of release-please, purpose-built for cargo. Uses the
*Release-PR* model. Crucial differentiators for a *shared backend*:
- It determines the next version from **Conventional Commits *and* real API breaking
  changes detected by `cargo-semver-checks`** — so a genuine API break committed (wrongly)
  as `fix:` is still caught. No other tool here does this.
- **Its default 0ver behavior is already exactly what we want**: in 0.x, breaking → minor
  (0.1.0 → 0.2.0), `feat:`/`fix:` → patch. The `features_always_increment_minor` option
  (default `false`) flips feat→minor if ever wanted.
- Native cargo-**workspace** handling; `version_group` keeps multiple crates pinned to one
  shared version — a direct match for our current `version.workspace = true` setup.
- It compares against the **published registry** (crates.io) rather than git tags. If we
  don't publish crates, set `release = false` per package so release-plz only manages
  version + changelog + tag, and the existing maturin `release.yml` still does the PyPI
  wheel publish on the tag it creates.

*Other Rust options:* `cargo-release` (mechanical bump+publish, no commit-derived bump
decision — you tell it the level), `cargo-smart-release` (gitoxide; commit-derived but
less maintained/ergonomic than release-plz). release-plz is the clear front-runner.

### Language-agnostic tools

**release-please (Google)** — parses commit *text* only (language-independent), uses the
*Release-PR* model, and has first-class `release-type: python` and `rust` updaters plus a
monorepo manifest. 0ver via **both** `bump-minor-pre-major: true` (breaking → minor in
0.x) **and** `bump-patch-for-minor-pre-major: true` (feat → patch in 0.x) — giving exactly
breaking→minor / feat→patch / fix→patch. For Python it updates `pyproject.toml` and
`<pkg>/__init__.py:__version__` automatically. *Limitation for Rust:* it bumps from commit
text only — **no `cargo-semver-checks`**, weaker workspace handling, and no native
crates.io publish — so it's a poorer fit for `sase-core` specifically.

**semantic-release (JS)** — the original; extremely powerful plugin ecosystem but
Node-centric, push-model, heavier to operate for Python/Rust. Not recommended here.

**knope** — language-agnostic, Conventional-Commits-driven, supports both push and PR
models. Capable but smaller community than the release-please family; no decisive
advantage for us.

---

## 4. Trigger-model recommendation (Axis A)

Although the request says "release whenever new commits are made," the **Release-PR
model is the better fit** even for that goal:

- It still releases automatically — you just **merge the bot's PR** instead of cutting a
  tag by hand. The PR is kept continuously up to date on every push.
- It **batches** a burst of commits into one coherent release with one changelog, instead
  of emitting a PyPI/crates.io release per commit.
- It shows the **computed version and changelog before** anything is published — a cheap,
  valuable safety gate while in 0ver (and especially for the shared `sase-core` API).

If a truly zero-touch "publish on every push" flow is desired for the Python leaf
packages, **python-semantic-release in push mode** delivers exactly that — noted as the
alternative in §6.

---

## 5. Comparison & 0ver config cheat-sheet

| Tool | Ecosystem fit | Trigger model | Detects real API breaks | 0ver config | Promote to 1.0.0 |
|------|---------------|---------------|-------------------------|-------------|------------------|
| **release-plz** | Rust (cargo, workspaces, crates.io) | Release-PR | **Yes** (`cargo-semver-checks`) | **default** (breaking→minor, feat/fix→patch) | crosses 1.0 on a breaking change once at `0.x` you opt in, or `release-plz set-version 1.0.0` |
| **release-please** | Any (incl. Python, Rust) | Release-PR | No (commit text only) | `bump-minor-pre-major: true` + `bump-patch-for-minor-pre-major: true` | drop `bump-minor-pre-major` (next breaking → 1.0.0) |
| **python-semantic-release** | Python (pyproject-native) | Push (default) or PR | No | `allow_zero_version = true` + `major_on_zero = false` | set `major_on_zero = true` (next breaking → 1.0.0) |
| **commitizen** | Python (+ commit lint) | bump-in-CI (push or PR) | No | `major_version_zero = true` | remove `major_version_zero` via a breaking-change commit |

Notes:
- With **release-plz** and **release-please (both knobs)**, 0ver gives breaking→minor,
  feat→patch, fix→patch.
- With **PSR** and **commitizen**, 0ver gives breaking→minor, **feat→minor**, fix→patch
  (no "feat→patch in 0.x" knob). Both schemes are valid 0ver; the difference is only how
  fast the minor digit climbs.

---

## 6. Recommendation

**Adopt the release-please *family*, Release-PR model, across all repos — split by
ecosystem so each project gets the tool that actually understands it:**

1. **`sase-core` (Rust): use `release-plz`.**
   - It is purpose-built for cargo workspaces, **its default 0ver behavior is already
     exactly what we want**, and it is the *only* option that detects genuine API
     breaking changes via `cargo-semver-checks` — which matters most precisely here,
     because `sase-core` is the shared backend the frontends bind to.
   - Use `version_group` to keep the workspace crates in lockstep (mirrors today's
     `version.workspace = true`).
   - Set `release = false` (or rely on the per-crate `publish = false`) so release-plz
     manages version + changelog + tag only; the **existing `release.yml`** continues to
     build and publish the maturin PyPI wheel when the `v*` tag is created. (Optionally
     enable crates.io publishing for `sase_core` later — release-plz does it natively.)

2. **`sase` + Python plugins (`sase-github`, `sase-telegram`, `sase-nvim`): use
   `release-please`** with `release-type: python` and **both** `bump-minor-pre-major: true`
   and `bump-patch-for-minor-pre-major: true`.
   - It updates `pyproject.toml` *and* `src/<pkg>/__init__.py:__version__` automatically
     (solving the dual-string sync), opens a release PR, and on merge creates the `vX.Y.Z`
     tag/Release that fires the **existing `publish.yml`** unchanged.
   - It's the same Release-PR mental model and the same Conventional-Commit mapping as
     release-plz (release-plz is explicitly modeled on release-please), so the whole fleet
     behaves identically. (`sase-nvim` may carry Lua alongside its Python package; the
     Python release-type still drives the version, or use a generic/`simple` updater for
     any Lua version constant.)

3. **Enforce Conventional Commits** (prerequisite for any of the above to be trustworthy).
   Add a `commit-msg` lint — `commitizen check` or `commitlint` — via pre-commit and/or a
   CI check on PRs. The team already follows the convention; this just makes it a
   guarantee so the bump decision is never silently wrong.

### One critical integration gotcha (applies to all Release-PR tools)

GitHub Actions **does not** trigger further workflows from events created with the default
`GITHUB_TOKEN` (anti-recursion). So a tag pushed by release-please/release-plz using the
default token will **not** fire the existing `on: push: tags: ['v*']` publish jobs. Fix
with one of:
- Give the release bot a **GitHub App token or PAT** (recommended) so its tag push
  triggers the downstream publish workflow; or
- Switch the publish workflows to `on: release: types: [published]` and ensure the Release
  is created with a non-default token; or
- Fold the publish step into the release workflow itself.

This is a small, well-trodden config detail but **must** be handled or releases will tag
without publishing.

### Strong alternative (Python only)

If you'd rather configure everything for the Python repos in `pyproject.toml` with a
single Python-native tool, or you want genuinely hands-off **publish-on-every-push**
(no PR to merge), use **python-semantic-release** with `allow_zero_version = true` +
`major_on_zero = false`. Trade-offs vs. release-please: a different mental model from the
Rust side, and `feat:` bumps minor (not patch) in 0ver. `sase-core` should still use
release-plz regardless — no Python tool understands the cargo workspace or detects Rust
API breaks.

### Why not "one tool everywhere" (release-please for Rust too)?

Tempting for uniformity, but release-please bumps Rust from commit text only — no
`cargo-semver-checks`, weaker workspace handling, no native crates.io publish. The shared
backend is exactly the place to *not* compromise on breaking-change detection. The
release-please↔release-plz pairing already gives a uniform PR-based workflow and identical
commit semantics, so we keep the uniformity benefit without giving up Rust correctness.

---

## 7. Suggested rollout

1. **Pilot on one Python plugin** (e.g. `sase-github`): add `release-please` config
   (`release-please-config.json` + `.release-please-manifest.json` with the two 0ver
   knobs) and a release workflow using a PAT/App token; confirm a `feat:`/`fix:` produces
   a correct release PR and that merging it triggers the existing `publish.yml`.
2. **Add commit-message enforcement** (commitizen/commitlint) repo-wide once the pilot
   confirms the mapping.
3. **Roll release-please to `sase` and the remaining plugins** (same config, adding the
   `__init__.py` version updater where present).
4. **Set up `release-plz` on `sase-core`**: add `release-plz.toml` with `version_group`
   and `release = false`, plus the release-plz GitHub Action; verify it opens a release
   PR and that merging tags → existing maturin `release.yml` publishes the wheel.
5. **Document the 1.0.0 promotion procedure** per repo (flip the 0ver knob — §5) for when
   each project stabilizes.

## 8. Open questions for Bryan

- **Trigger model:** Release-PR (merge the bot's PR to cut a release; recommended) vs.
  fully automatic publish-on-every-push (PSR push mode)?
- **`feat:` in 0ver:** bump patch (release-please/release-plz default) or minor (PSR/cz)?
  Affects how fast the minor digit climbs before 1.0.0.
- **crates.io:** publish `sase_core` (and siblings) to crates.io, or keep PyPI-wheel-only
  and use release-plz purely for version/changelog/tag management?
- **Scope of "every commit":** should `chore:`/`docs:`/`ci:` ever trigger a release? (All
  tools default to "no release" for these — recommended to keep.)

---

## Sources

- [python-semantic-release — Configuration (`major_on_zero`, `allow_zero_version`)](https://python-semantic-release.readthedocs.io/en/latest/configuration/configuration.html)
- [release-please-action (googleapis)](https://github.com/googleapis/release-please-action) · [release-please customizing.md](https://github.com/googleapis/release-please/blob/main/docs/customizing.md) · [Major-version-zero support (issue #558)](https://github.com/googleapis/release-please/issues/558)
- [release-plz — homepage](https://release-plz.dev/) · [docs](https://release-plz.dev/docs) · [config (`features_always_increment_minor`, `version_group`, `release`)](https://release-plz.dev/docs/config) · [GitHub](https://github.com/release-plz/release-plz)
- [Fully Automated Releases for Rust Projects — Orhun's Blog](https://blog.orhun.dev/automated-rust-releases/)
- [commitizen — bump (`major_version_zero`)](https://commitizen-tools.github.io/commitizen/commands/bump/) · [Breaking changes below v1 (issue #501)](https://github.com/commitizen-tools/commitizen/issues/501)
- [semantic-release (JS)](https://github.com/semantic-release/semantic-release)
- [Semantic Versioning 2.0.0](https://semver.org/)
