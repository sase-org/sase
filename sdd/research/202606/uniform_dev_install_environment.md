# Uniform Development Install for SASE, sase-core, and Plugins

Date: 2026-06-27
Status: Research / recommendation

## Question

What is the best way to install **development versions** of `sase`, `sase-core`, and SASE's first-party plugin
packages so that the experience is **uniform for every developer** working on SASE or on a SASE plugin? Bryan is uneasy
about the prior plan to make `sase-dev` the development executable and wants this decision re-examined against modern
best practices.

This note deliberately takes a different framing than the earlier `sase-dev` research
(`sdd/research/202606/sase_dev_install_strategy.md`, `sdd/research/202606/sase_update_dev_consolidated.md`). Those notes
answered "how do we ship a parallel runtime command beside stable `sase`." This note answers the narrower, more
fundamental question the contributor workflow actually needs: "how does a developer get one environment where their
edits to SASE, the Rust core, and the plugins all take effect at once."

## Short Answer

The unease is justified. `sase-dev` is the wrong primitive for the *development install* because it answers a different
question than the one developers ask day to day.

There are two separate problems hiding under one name:

1. **Dev install (the real question here).** "I am editing `sase` and/or `sase-core` and/or a plugin. Give me a single
   environment in which all of my edits are live." This needs nothing more than **one virtual environment with every
   interlocking package installed editable** into it.

2. **Parallel runtime identity (what `sase-dev` was actually about).** "I want a second command on my `PATH` that runs
   the dev build *simultaneously* with stable `sase`, with isolated state, config, workspaces, axe locks, and process
   discovery." This is what dragged in the heavy machinery: a renamed launcher, `SASE_PROFILE`, a current-runtime argv
   helper, rewriting every internal `["sase", ...]` subprocess, and Rust path parity.

Making `sase-dev` *the* development executable couples the everyday contributor loop to problem #2's plumbing. That is
the wrong dependency direction and the source of the unease.

**Recommendation:** Build the uniform developer experience entirely on problem #1 — a single editable environment whose
command is just `sase`. Keep the `sase-dev` parallel-runtime as an **optional, additive power-user feature** that the
dev install does not depend on. Concretely, support two editable surfaces, both already mostly built:

- **Inner loop (default):** extend `just install` so it editable-installs every *present* sibling plugin checkout in
  addition to today's editable `sase` + `maturin develop` of `sase_core_rs`. Develop via the repo `.venv`
  (`uv run sase` / activated venv). CI uses the same path.
- **Outer loop (on `PATH` everywhere):** `uv tool install --editable . --with-editable <sibling plugins>` plus the
  existing `just rust-install-uv-tool`. This produces a real global `sase` from editable sources that mirrors the exact
  production topology (one tool venv = `sase` + injected plugins), with no renamed command.

Neither surface requires renaming the executable to `sase-dev`, profile isolation, or subprocess rewriting. A developer
who works on a *plugin* gets the identical experience by running the same flow from the plugin repo with `sase` and
`sase-core` checked out as siblings.

## Why This Reframing Matters

The prior `sase-dev` plan is not wrong about its own goal — running stable and dev side by side, concurrently, on one
machine is a legitimate (if niche) want. The problem is **scope**. To make `sase-dev` safe as a *development* runtime,
that research correctly concluded SASE would first need to:

- add a current-runtime argv helper and migrate every literal `["sase", ...]` subprocess
  (commit, bead, restore, axe re-exec, dispatch);
- make `prog="sase"` in the parser dynamic;
- add `SASE_PROFILE` state/config/workspace derivation in Python **and** mirror it in the Rust core with parity tests;
- make axe process discovery and start/stop profile-aware.

That is a large, cross-language, high-blast-radius change set — and **none of it is needed to develop SASE**. A
developer does not need a differently-named binary or isolated state to see their edits run; they need their edits on
`sys.path` (and the Rust extension rebuilt). Tying the routine contributor onboarding flow to that machinery makes the
common case pay for the rare case. Decoupling them lets the uniform dev install ship now and lets `sase-dev` remain an
optional feature that can mature on its own timeline.

## Verified Baseline (current mechanics)

Checked in this workspace on 2026-06-27.

### Packaging

- `pyproject.toml`: distribution `sase` 0.5.0, build backend `hatchling`, hard dependency
  `sase-core-rs>=0.2.0,<0.3.0`, console script `sase = "sase.main.entry:main"`.
- **No `[tool.uv]`, no `[tool.uv.sources]`, no `[tool.uv.workspace]`.** `uv.lock` is a flat single-project registry
  lock, not a workspace lock. SASE does not currently use uv workspaces or path sources.

### Current dev install (`just install`)

`Justfile` `install` target (lines 80–85):

1. If `../sase-core` (resolved via `SASE_CORE_DIR` → `SASE_LINKED_REPO_SASE_CORE_DIR` → legacy `SASE_SIBLING_REPO_*`
   fallbacks → `../sase-core`) exists **and** `cargo` is on `PATH`, run `just rust-install`, which builds and installs
   `sase_core_rs` with `maturin develop --release` into the target venv (`rust-install` target, lines 350–369;
   `maturin` is auto-installed into the venv on demand).
2. `uv pip install --python .venv/bin/python --no-sources -e ".[dev]"`.

Two design choices are worth calling out because they shape the options below:

- **`--no-sources` is deliberate.** SASE pre-builds the Rust extension into the venv so the `sase-core-rs` dependency is
  already satisfied, then installs editable `sase` while *ignoring* any uv source overrides. This sidesteps uv trying to
  build `sase-core` itself (in release mode) during resolution.
- **`just install` does not install any plugin.** `sase-github`, `sase-telegram`, and `sase-nvim` are absent from the
  dev environment entirely. There is no uniform dev story for plugins today — this is the concrete gap.

`just rust-install-uv-tool` already exists: it builds `sase_core_rs` into the `uv tool` `sase` venv
(`$(uv tool dir)/sase`) so a `uv tool install`ed `sase` can run against a local `sase-core` checkout.

### Production install topology (what dev should resemble)

- Stable end users: `uv tool install sase --python 3.12` (one isolated tool venv).
- Plugins are **injected into that same venv**: `sase plugin install github` runs `uv tool install sase --with ...`,
  reconstructing the full `--with` set from `uv-receipt.toml` (`src/sase/uv_tool/commands.py`, `receipt.py`). uv's
  `--with` *replaces* the injected set, so SASE always re-passes the whole set.
- Crucially, that machinery **already renders editable primaries and editable plugins** (`--editable <path>` /
  `--with-editable <path>`; see `receipt.py` `with_args()` / `primary_args()`). The editable-everything dev topology is
  already expressible with existing code.

### Repo topology

`sase`, `sase-core`, `sase-github`, `sase-telegram`, `sase-nvim` are **separate git repositories**. SASE's own
linked-repos feature (`src/sase/linked_repos.py`, config key `linked_repos`, env `SASE_LINKED_REPO_<NAME>_DIR` and
`SASE_LINKED_REPOS_JSON`) and `sase workspace open -p <repo>` already clone/resolve them as sibling checkouts. The
"clone side by side under a common parent" convention is therefore *already standard* for SASE developers — which is
exactly the precondition modern uv cross-repo guidance asks for.

## Modern Best Practices (2025–2026)

### One venv, everything editable

Across the ecosystem the consensus for multi-package local development is a **single shared virtual environment with
every package installed editable**. uv workspaces make this the default: members share one `.venv` at the workspace
root, one lockfile, and inter-member dependencies are editable automatically — "Dependencies between workspace members
are editable." Whether or not SASE adopts uv *workspaces*, that end-state (one venv, all editable) is the target.

### Workspaces vs. path sources for *separate repos*

uv workspaces are designed for **packages that live inside one repository** (members are subdirectories of the workspace
root). The uv docs steer multi-repo cases elsewhere: "Workspaces are *not* suited for cases in which members ... desire a
separate virtual environment for each member. In this case, path dependencies are often preferable." For packages in
**sibling git repos**, the idiomatic tool is `[tool.uv.sources]` with an **editable path**:

```toml
[project]
dependencies = ["sase-github"]

[tool.uv.sources]
sase-github = { path = "../sase-github", editable = true }
```

Guidance on committing the override: "Check in the `[tool.uv.sources]` entry only if every developer on the team clones
the repos side by side; otherwise keep it out of version control and document the override as a local-development step."
SASE's sibling-checkout convention satisfies the "everyone clones side by side" condition — but note `uv pip install
--no-sources` (which `just install` already uses) intentionally ignores these, so committing them is compatible with
SASE's current pre-build-then-install approach.

### Compiled Rust extension (maturin)

A PyO3 extension is not a plain Python path package; the `.so` must be rebuilt when Rust changes. The relevant options:

- **`maturin develop`** builds and installs into the active venv (debug by default; `-r/--release` for optimized). This
  is what SASE already does. Fastest single rebuild; must be re-run after Rust edits.
- **`tool.uv.cache-keys`** to make `uv sync` rebuild on Rust changes:
  `cache-keys = [{file = "pyproject.toml"}, {file = "Cargo.toml"}, {file = "**/*.rs"}]`. Correct, but `uv sync` builds
  in **release** mode — slower iteration.
- **`maturin_import_hook`** (`uv run -m maturin_import_hook site install`) rebuilds the extension automatically on
  import in debug mode — best inner-loop ergonomics for active Rust work, at the cost of one-time setup.

These are complementary: SASE can keep `maturin develop` as the build step and offer the import hook to contributors who
are actively editing Rust.

### Renamed dev command is *not* a best practice

Nothing in modern Python/Rust tooling suggests renaming the executable for development. The universal pattern is to run
the project's normal entry point out of the dev venv (`uv run <cmd>`, activated venv, or `uv tool install --editable`). A
distinct command name is only introduced when you genuinely need two builds resolvable on `PATH` at once — i.e.
problem #2, not development.

## Options

### Option A — Status quo (`just install`, repo `.venv`, no plugins)

Editable `sase` + `maturin develop` of `sase_core_rs`; run via the repo venv.

- **Pros:** simplest; already works; CI-aligned; `--no-sources` avoids uv release-mode rebuilds.
- **Cons:** **no plugins** — the core gap. A plugin developer has no uniform path. Not "uniform for all developers."

### Option B — Extend `just install` to editable-install sibling plugins (inner loop)

After editable `sase`, also `uv pip install --no-sources -e <dir>` for each first-party plugin present as a sibling /
linked checkout (discovered via the existing `SASE_LINKED_REPO_*` / `linked_repos` mechanism, same way `../sase-core` is
found). Absent plugins are simply skipped (or pulled from PyPI on demand).

- **Pros:** smallest change that closes the gap; reuses existing discovery and the `--no-sources` + pre-build pattern;
  one venv, everything editable; symmetric — a plugin repo's Justfile can do the same to pull in editable `sase` +
  `sase-core`; no new command, no profile machinery.
- **Cons:** the dev `sase` lives in the repo `.venv` (run via `uv run`/activation), not on global `PATH`; plugin set is
  whatever is checked out (acceptable and explicit).

### Option C — `uv tool install --editable . --with-editable <plugins>` (outer loop, on `PATH`)

Install editable `sase` + editable plugins into a `uv tool` venv, then `just rust-install-uv-tool` to build
`sase_core_rs` into it.

- **Pros:** produces a real global `sase` from editable sources; **mirrors production topology exactly** (one tool venv
  = `sase` + injected plugins), so "what I test" == "what users run"; the receipt/`--with-editable` machinery already
  exists; still named `sase`.
- **Cons:** replaces the user's stable `sase` tool env (fine for a developer whose `sase` *is* the dev build; the
  stable-beside-dev want is exactly problem #2); needs the manual `rust-install-uv-tool` step after Rust edits.

### Option D — uv workspace "superproject"

Create a workspace root whose members are the SASE packages.

- **Pros:** one lockfile, editable members, idiomatic uv.
- **Cons:** workspaces want members **inside one repo**; SASE is polyrepo with independent release cadences and a
  compiled Rust member that maturin (not the workspace) must build. A workspace spanning sibling repos fights the model
  (members aren't subdirectories of the root); single `requires-python` intersection across members; large
  restructuring for little gain over path sources. Not a fit for SASE's polyrepo + maturin reality.

### Option E — Committed `[tool.uv.sources]` path-editable overrides

Add path-editable sources for siblings in each repo's `pyproject.toml`.

- **Pros:** idiomatic cross-repo uv; `uv sync` "just works" for anyone who cloned side by side; declarative.
- **Cons:** only honored by uv project workflows, and `just install` deliberately passes `--no-sources`; pulling uv into
  building `sase-core` reintroduces the release-mode rebuild problem the current flow avoids. Best treated as an
  *optional convenience layer* on top of B/C, not the mechanism.

### Option F — `sase-dev` parallel runtime as the dev executable (prior plan)

Renamed launcher + `SASE_PROFILE` + argv helper + subprocess migration + Rust path parity.

- **Pros:** enables true simultaneous stable+dev runtimes with isolated state.
- **Cons:** large, cross-language, high blast radius; solves problem #2, not development; couples routine onboarding to
  runtime-identity plumbing. Overkill — and miscast — as the *development* install.

## Recommended Solution

Adopt a **single editable development environment whose command stays `sase`**, exposed through two surfaces, and
**demote `sase-dev` to an optional add-on** that the dev install does not depend on.

### 1. Inner loop — extend `just install` (Option B)

Make `just install` the one uniform command that wires the whole editable world into the repo `.venv`:

- Keep today's behavior: `maturin develop` of `sase_core_rs` from the sibling `sase-core` when present + `cargo`
  available, then editable `sase` with `--no-sources`.
- **Add:** for each first-party plugin (`sase-github`, `sase-telegram`, `sase-nvim`) that is present as a linked/sibling
  checkout, `uv pip install --no-sources -e <dir>`. Discover paths with the existing `SASE_LINKED_REPO_<NAME>_DIR` /
  `linked_repos` machinery; skip cleanly when absent (fall back to PyPI only if explicitly requested).
- Develop via the repo venv: `uv run sase ...`, an activated `.venv`, or `.venv/bin/sase`. This is the default inner
  loop and what CI mirrors.

### 2. Symmetry for plugin developers (the "uniform for everyone" property)

Give each first-party plugin repo the **same** `just install` shape: build/install editable `sase-core`, install
editable `sase`, and install the plugin itself editable, when those repos are checked out as siblings. A developer whose
primary repo is `sase-github` then runs the identical command and gets the identical editable set. Uniformity comes from
*every repo sharing one install contract*, not from a special command.

### 3. Outer loop — document the editable `uv tool` install (Option C)

For developers who want the dev build as their everyday global `sase`:

```bash
uv tool install --editable . \
  --with-editable ../sase-github \
  --with-editable ../sase-telegram
just rust-install-uv-tool   # build sase_core_rs into the tool venv
```

This mirrors the production one-venv-`sase`+plugins topology with everything editable, and keeps the command named
`sase`. Wrap it behind a Justfile target (e.g. `just install-tool`) that auto-discovers sibling plugins, for parity with
the inner-loop command.

### 4. Optional Rust ergonomics

Offer (do not require) the `maturin_import_hook` for contributors actively editing Rust, and consider adding
`tool.uv.cache-keys` (`Cargo.toml`, `**/*.rs`) so any future `uv sync`-based flow rebuilds correctly. Keep `maturin
develop` as the canonical build step.

### 5. Keep `sase-dev` as an optional feature, fully decoupled

If/when someone needs stable and dev SASE running **simultaneously** with isolated state, build that as the separate
`sase-dev` / `SASE_PROFILE` feature the prior research describes — but as an additive layer the dev install never
touches. The everyday developer should never need to know it exists.

### Why this is the right call

- **Closes the actual gap** (plugins were missing from dev) with the smallest change, reusing machinery that already
  exists (`--no-sources` pre-build pattern, linked-repo discovery, `rust-install-uv-tool`, editable `--with-editable`
  receipts).
- **Uniform across all developers** — sase, sase-core, and plugin contributors run one install contract and get one
  editable environment.
- **What you test is what ships** — the outer-loop surface reproduces the exact production install topology.
- **No renamed executable, no profile/subprocess/Rust-parity prerequisites** for development. The heavyweight `sase-dev`
  work becomes optional rather than load-bearing — directly resolving the unease.

## Sources

Internal:

- `pyproject.toml`, `Justfile` (`install`, `_setup`, `rust-install`, `rust-install-uv-tool`), `uv.lock`
- `src/sase/uv_tool/commands.py`, `src/sase/uv_tool/receipt.py`, `src/sase/uv_tool/render.py`
- `src/sase/linked_repos.py`, `src/sase/sibling_repos.py`, `src/sase/default_config.yml`
- `docs/development.md`, `docs/rust_backend.md`, `docs/plugins.md`, `docs/vcs.md`, `docs/workspace.md`
- Prior research: `sdd/research/202606/sase_dev_install_strategy.md`,
  `sdd/research/202606/sase_update_dev_consolidated.md`

External (accessed 2026-06-27):

- uv workspaces — https://docs.astral.sh/uv/concepts/projects/workspaces/
- uv dependencies / `tool.uv.sources` — https://docs.astral.sh/uv/concepts/projects/dependencies/
- uv tools — https://docs.astral.sh/uv/concepts/tools/
- Cross-repo uv path-editable pattern — https://pydevtools.com/handbook/how-to/how-to-manage-cross-repo-python-dependencies-with-uv/
- uv monorepo / workspaces walkthrough — https://pydevtools.com/handbook/how-to/how-to-set-up-a-python-monorepo-with-uv-workspaces/
- maturin local development — https://www.maturin.rs/local_development.html
- uv + maturin integration (cache-keys, import hook) — https://quanttype.net/posts/2025-09-12-uv-and-maturin.html
- maturin import hook — https://www.maturin.rs/import_hook.html
</content>
</invoke>
