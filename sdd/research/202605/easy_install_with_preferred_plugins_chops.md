# Easy Install of SASE with Preferred Plugins and Chops

Date: 2026-05-28

## Question

How do we make installing `sase` together with a user's *preferred* plugins and/or chops as easy as possible — ideally
one command, reproducible across machines, with no footguns?

## Executive Summary

Today the canonical install path is `uv tool install sase --with sase-github --with sase-telegram`. It works but has
three problems that get worse as the plugin/chop ecosystem grows:

1. **The user must know exact package names and constraints.** There is no discovery surface.
2. **The same-environment requirement is an invisible footgun.** Plugins are discovered through Python entry points, so
   a plugin installed into a different env than `sase` silently does nothing (see
   [public_release_process_and_install_research](./public_release_process_and_install_research.md)).
3. **"Preferred set" is not expressible.** There is no way to say "this is my standard kit" and reproduce it on a new
   laptop or in CI.

Chops add a second wrinkle: installing a chop's *script* is not enough — a chop only runs if it is also **registered in
a lumberjack** in config. The good news is the `sase_config` entry-point already lets a plugin ship a `default_config.yml`
that self-registers its lumberjack/chop, so a well-packaged chop plugin is fully wired on install with zero user config.
That mechanism exists and works today (`src/sase/main/plugin_discovery.py`, `docs/plugins.md`).

The recommended direction is a layered answer, cheapest first:

1. **Define curated PyPI extras on `sase`** (`sase[github]`, `sase[telegram]`, `sase[recommended]`, `sase[all]`) so
   venv/pip users get named bundles and stop memorizing package names.
2. **Add a `sase plugin` command family** (`list`, `add`, `remove`) that detects how `sase` was installed
   (uv tool / pipx / venv) and installs the plugin **into that same environment automatically**, removing the
   same-env footgun. `sase plugin list` is already called out as a pre-1.0 blocker in prior research.
3. **Support a declarative plugin/chop manifest** (`~/.config/sase/plugins.toml` or a `plugins:` block in `sase.yml`)
   plus `sase plugin sync`, so a "preferred set" is reproducible across machines and CI.
4. **Keep chop wiring config-driven via `sase_config`** so installing a chop plugin schedules it automatically; reserve
   a `sase chop add` scaffolder only for *local* (non-packaged) user chops.

Extras (#1) and `sase plugin` (#2) are the highest value-to-effort. The manifest (#3) is the piece that actually makes a
*preferred* set first-class.

## Background: How Install and Discovery Work Today

### Packaging topology

`sase` is a pure-Python host package. The Rust core (`sase-core-rs`) is a required wheel dependency. Plugins are
separate PyPI packages (`sase-github`, `sase-telegram`, …) discovered at runtime through entry-point groups
(`pyproject.toml`):

- Provider (pluggy) groups: `sase_llm`, `sase_vcs`, `sase_workspace`.
- Resource groups: `sase_xprompts`, `sase_config`.

Because discovery is `importlib.metadata.entry_points()` over the *current interpreter's* installed distributions, every
plugin must live in the **same environment** as `sase`. This is the single most important install constraint and the
source of the most common silent failure.

### Current install commands

From [public_release_process_and_install_research](./public_release_process_and_install_research.md):

```bash
# core only
uv tool install "sase>=0.2,<0.3"

# with plugins (verbose, name-memorization required)
uv tool install "sase>=0.2,<0.3" \
  --with "sase-github>=0.2,<0.3" \
  --with "sase-telegram>=0.2,<0.3"

# pipx equivalent
pipx install "sase>=0.2,<0.3"
pipx inject sase "sase-github>=0.2,<0.3"
pipx inject --include-apps sase "sase-telegram>=0.2,<0.3"
```

`docs/plugins.md` currently documents only `pip install sase` / `pip install sase-github`, which is the path *most*
likely to break for `uv tool`/`pipx` users because a bare `pip install sase-github` may land in a different env.

### How chops are wired

Chops are scheduled scripts. Two independent things must be true for a chop to actually run:

1. **The script is discoverable.** `src/sase/axe/chop_script_runner.py` looks for `sase_chop_<name>` first in
   configured `axe.chop_script_dirs`, then beside the active interpreter, then on `$PATH`. Any pip-installed package
   that exposes a `sase_chop_<name>` console script satisfies this automatically.
2. **The chop is registered in a lumberjack.** `src/sase/default_config.yml` lists built-in chops under five
   lumberjacks (`hooks`, `waits`, `checks`, `comments`, `housekeeping`). A chop not referenced by any lumberjack never
   gets scheduled (e.g. `pushgateway_cleanup` ships as a script but is in no default lumberjack).

The `sase_config` entry point closes the gap: a plugin can ship a `default_config.yml` that adds its own lumberjack or
appends a chop to an existing one, and it is deep-merged between core defaults and the user's `sase.yml`
(`docs/configuration.md` deep-merge). So a chop plugin can be **fully self-wiring** on install. See also the chop
packaging analysis in [sase_chops_rust_repo_research](./sase_chops_rust_repo_research.md) for the Rust-binary-wheel
variant of the same idea.

### What does not exist yet

- No `sase plugin` command of any kind (verified against `src/sase/main/parser.py`). `plugin_discovery.py` exposes
  `discover_plugin_resources(group)` but has no CLI surface.
- No PyPI extras defined on `sase` (`[project.optional-dependencies]` in `pyproject.toml` has only `dev`, `visual`,
  `terminal-smoke`, `docs`, `docs-pdf` — no plugin bundles).
- No declarative "preferred plugins" manifest. `sase init` onboarding (`init_registry.py`, `init_onboarding.py`) covers
  `memory`/`sdd`/`skills` but does not touch plugin installation.

## The Options

### Option A — PyPI extras (curated bundles)

Add optional-dependency groups to `sase`'s `pyproject.toml`:

```toml
[project.optional-dependencies]
github = ["sase-github>=0.2,<0.3"]
telegram = ["sase-telegram>=0.2,<0.3"]
recommended = ["sase-github>=0.2,<0.3"]
all = ["sase-github>=0.2,<0.3", "sase-telegram>=0.2,<0.3"]
```

Then:

```bash
pip install "sase[github,telegram]"
uv tool install "sase[recommended]"
pipx install "sase[all]"
```

**Pros**

- Zero new code. Pure metadata.
- Solves the same-env footgun for free: extras resolve into the *same* install transaction/environment, so a plugin can
  never land in the wrong env.
- Discoverable on the PyPI project page and in `pip install sase[`-style tooling.
- Works uniformly for `pip`, `uv tool`, and `pipx`.

**Cons**

- The set of extras is curated by the `sase` maintainer, not the user. Third-party/private plugins cannot be referenced
  through an extra.
- Adding a plugin after the fact still means re-running the install with the new extra (extras are resolved at install
  time, not incrementally added).
- Couples `sase`'s release cadence loosely to plugin version ranges (the extra pins a range; a plugin major bump needs a
  `sase` metadata update).

**Verdict:** Ship this. It is the cheapest win and the natural first thing a new user reaches for. It does **not** by
itself express a user's arbitrary preferred set, so it is necessary but not sufficient.

### Option B — A meta/bundle package (`sase-full`)

Publish a tiny package whose only content is dependencies:

```toml
# sase-full/pyproject.toml
[project]
name = "sase-full"
dependencies = ["sase", "sase-github", "sase-telegram"]
```

```bash
uv tool install sase-full
```

**Pros**: one command, one name to remember.

**Cons**: a separate package to version and release; another name in the namespace; still maintainer-curated, not
user-curated; strictly weaker than extras (an extra `sase[all]` achieves the same thing without a new distribution).

**Verdict:** Skip in favor of Option A's `sase[all]`. A meta-package only earns its keep if the bundle needs an
*independent* release cadence from `sase`, which is not the case here.

### Option C — `sase plugin` command family

Add a first-class command that owns plugin lifecycle and, crucially, **installs into the same environment as `sase`**.

```bash
sase plugin list                 # what's discovered now, by group, with versions
sase plugin add sase-github      # install into sase's own env, then verify discovery
sase plugin add ./my-chop-plugin # local path / VCS URL too
sase plugin remove sase-telegram
```

Implementation sketch:

- `sase plugin list` wraps `discover_plugin_resources` across all five groups plus `[project.scripts]`-based chops, and
  prints what loaded vs. what failed. This is the diagnostic that prior research flagged as a pre-1.0 blocker.
- `sase plugin add` detects the install method by inspecting `sys.prefix` / `sys.argv[0]`:
  - uv tool install → shell out to `uv tool install --upgrade sase --with <pkg>` (uv re-renders the tool env with the
    added `--with`).
  - pipx → `pipx inject [--include-apps] sase <pkg>`.
  - plain venv → `python -m pip install <pkg>` into the same interpreter.
  - After install, re-run discovery and report success/failure so the user gets immediate confirmation instead of a
    silent no-op.

**Pros**

- Eliminates the same-env footgun *and* works for arbitrary/private plugins (path, VCS URL, private index).
- Gives the missing discovery/diagnostic surface (`sase plugin list`).
- Natural home for chop-aware messaging ("installed `sase-github`; it registered lumberjack `gh_checks`").

**Cons**

- Detecting the host install method robustly is fiddly (uv tool vs pipx vs venv vs system Python vs the editable
  dev install used in this repo). Needs careful handling and clear errors when it can't tell.
- Shelling out to `uv`/`pipx` couples `sase` to those tools being on `PATH`.

**Verdict:** Build `sase plugin list` first (cheap, unblocks diagnostics). Then `add`/`remove`. This is the piece that
makes *post-install* plugin management painless and handles plugins extras can't name.

### Option D — Declarative manifest + `sase plugin sync`

Let the user *declare* their preferred set and reproduce it:

```toml
# ~/.config/sase/plugins.toml
[plugins]
sase-github = ">=0.2,<0.3"
sase-telegram = ">=0.2,<0.3"
"my-private-chop" = { git = "https://github.com/me/my-chop" }
```

```bash
sase plugin sync          # install/upgrade everything in the manifest into sase's env
sase plugin add --save X  # install X and record it in the manifest
```

**Pros**

- This is the only option that makes a *preferred set* a first-class, portable artifact: copy the file (or sync it via
  chezmoi, which `sase init` already uses for home files) and `sase plugin sync` rebuilds the kit on any machine or CI
  runner.
- Composes with Option C (`add --save`) and Option A (the manifest can target `sase[recommended]` as a baseline).

**Cons**

- Most moving parts. Needs a resolver story (does `sync` remove plugins not in the manifest? probably no by default).
- Overlaps conceptually with uv's own project/lock model — worth checking whether a `uv tool install` with a constraints
  file gets most of the benefit before building a bespoke manifest format.

**Verdict:** The right *eventual* shape for "preferred plugins," but sequence it after A and C. Reuse the existing
chezmoi-backed home-file deployment from `sase init` for cross-machine sync rather than inventing new transport.

### Option E — Bootstrap installer script (`curl … | sh`)

A rustup/uv-style one-liner that installs `uv` if missing, then `uv tool install sase[...]`, optionally interactive
about plugins.

**Pros**: best first-run UX for brand-new users on a clean machine; can bundle the `sase init` onboarding prompt.

**Cons**: a script to host, sign, and maintain; security-sensitive (`curl | sh`); prior research already lists "homebrew
formula or installer script" as *lower priority* relative to the PyPI + `uv tool` path.

**Verdict:** Defer. Revisit once A–D exist and there is evidence new users stall at "install uv first."

## Chops Specifically

"Install my preferred chops easily" splits into two cases:

1. **Packaged chops (shipped by a plugin).** Already solved by the existing mechanism: the plugin exposes
   `sase_chop_<name>` via `[project.scripts]` *and* ships a `sase_config` `default_config.yml` that registers the chop
   in a lumberjack. Installing the plugin (via any of Options A–D) both installs the script and schedules it, with the
   user able to override the schedule in `sase.yml`. No new mechanism required — the gap is **documentation and a couple
   of well-packaged examples**, not architecture. The Rust-binary-wheel packaging of built-in chops in
   [sase_chops_rust_repo_research](./sase_chops_rust_repo_research.md) is the same story with native binaries instead of
   Python console scripts.

2. **Local user chops (a script the user wrote, not a published package).** Here the friction is real and unaddressed:
   the user must drop the script somewhere on `axe.chop_script_dirs`/`$PATH`, mark it executable, *and* hand-edit
   `sase.yml` to add it to a lumberjack. A small `sase chop add` scaffolder could:
   - register a directory in `axe.chop_script_dirs` (or accept an explicit script path),
   - append the chop to a named lumberjack in `sase.yml` (deep-merge friendly),
   - verify the script resolves via the same `discover_chop_script()` logic the scheduler uses, and
   - optionally `sase axe lumberjack run <lumberjack>` once to smoke-test.

   This mirrors the plan/apply discipline already established for `sase init` (`init_plan.py`) — read-only detection of
   what config would change, then apply.

A useful diagnostic either way: extend `sase plugin list` (or add `sase axe lumberjack doctor`, already suggested in the
chops research) to resolve every configured chop name to a concrete path and language, so "my chop isn't running" has a
one-command answer.

## Recommended Sequencing

1. **Now (metadata + docs):** add `sase` extras (`github`, `telegram`, `recommended`, `all`); update `docs/plugins.md`
   and the README to lead with `uv tool install "sase[recommended]"` and to state the same-env rule loudly. Add one
   end-to-end example of a self-wiring chop plugin (`sase_chop_*` script + `sase_config` lumberjack registration).
2. **Next (diagnostics):** ship `sase plugin list` (groups + chop scripts, loaded vs failed, versions). This is already a
   named pre-1.0 release blocker.
3. **Then (lifecycle):** `sase plugin add/remove` with host-install-method detection so post-install plugin management
   never lands in the wrong env.
4. **Later (preferred set):** declarative manifest + `sase plugin sync` (with `add --save`), reusing chezmoi for
   cross-machine sync. Evaluate a uv constraints-file shortcut before committing to a bespoke manifest format.
5. **Only for local chops:** `sase chop add` scaffolder over the existing plan/apply pattern.
6. **Defer:** `sase-full` meta-package (extras cover it) and a `curl | sh` bootstrap (revisit on evidence).

## Open Questions

- Can a `uv tool install sase --with-requirements plugins.txt` (or uv constraints file) deliver Option D's reproducibility
  without a bespoke manifest format? If so, Option D shrinks to "document the uv pattern + a thin `sase plugin sync`
  wrapper."
- Should `sase plugin add` refuse to run in the editable dev workspace (this repo's `just install` setup) to avoid
  polluting a developer venv, or just warn?
- For extras, should `recommended` equal `all` for the first public release (only `sase-github` is public-safe today per
  prior research), and grow apart only when more audited plugins exist?
- Does the same-env detection need to handle the case where `sase` is on `PATH` via one method but the user invokes a
  different interpreter's `pip`? The detector should key off `sys.prefix` of the running `sase`, not ambient `pip`.

## Sources

Local code and docs reviewed:

- `pyproject.toml` — entry-point groups, console-script chops, existing `optional-dependencies` (no plugin extras).
- `src/sase/main/plugin_discovery.py` — `discover_plugin_resources`, disable env vars; no CLI surface.
- `src/sase/main/parser.py` — confirms no `sase plugin` command exists.
- `src/sase/main/init_registry.py`, `init_onboarding.py`, `init_plan.py` — existing plan/apply onboarding pattern to mirror.
- `src/sase/default_config.yml` (axe section) — lumberjack/chop registration; `chop_script_dirs`.
- `docs/plugins.md` — entry-point groups, current install docs, `sase_config`/`sase_xprompts` discovery.
- `docs/configuration.md` — deep-merge chain (referenced).

Related prior research:

- [public_release_process_and_install_research](./public_release_process_and_install_research.md) — install commands,
  same-env constraint, `sase plugin list`/`sase --version` as pre-1.0 blockers, `sase[github]` extra suggestion.
- [sase_chops_rust_repo_research](./sase_chops_rust_repo_research.md) — chop discovery contract, binary-wheel packaging,
  `lumberjack doctor` diagnostic idea.
- [../202602/sase_plugin_specifics.md](../202602/sase_plugin_specifics.md) — `sase_config`/`sase_xprompts` entry-point
  design and the self-wiring chop/metahook config contribution model.
- [sase_init_onboarding](./sase_init_onboarding.md) — registry + read-only plan/apply pattern reusable for `sase chop add`.
