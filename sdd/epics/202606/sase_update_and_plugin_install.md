---
create_time: 2026-06-25 21:15:25
status: wip
bead_id: sase-58
tier: epic
prompt: sdd/prompts/202606/sase_update_and_plugin_install.md
---
# Plan: `sase update` + `sase plugin install` / `sase plugin update`

## Goal

Give SASE first-class self-update and plugin-management commands for users who installed sase via `uv tool install sase`
(the canonical install path):

- **`sase update`** — upgrade sase **and every installed sase plugin together**, in one atomic operation, by delegating
  to `uv tool upgrade sase`.
- **`sase plugin install <plugin>`** — install a plugin **into the same environment as sase** (so its entry points are
  discovered at runtime), resolving the plugin name through the existing GitHub catalog.
- **`sase plugin update <plugin>`** — upgrade one already-installed plugin (and `--all` to upgrade every plugin) without
  disturbing the rest of the environment.

All three must **detect a non-`uv tool` install and fail fast with a beautiful, actionable error**, and all three must
have **excellent, concise, beautiful output** and **excellent `-h` help** (the bar set by the existing `sase plugin`
commands).

## The uv investigation that reshapes the design (read first)

I validated uv's actual behavior empirically (uv 0.11.24) before designing. Four findings drive everything below:

1. **A uv tool lives in its own venv, and the receipt is the source of truth.** `uv tool install sase` creates a venv at
   `<uv-tool-dir>/sase` (where `<uv-tool-dir>` is `uv tool dir`, default `~/.local/share/uv/tools`, overridable via
   `$UV_TOOL_DIR`). That directory holds a **`uv-receipt.toml`** whose `[tool].requirements` array records the primary
   package **plus every injected plugin**. Example from a real install:
   `requirements = [{ name = "sase" }, { name = "sase-github" }, { name = "sase-telegram" }]`. This receipt — not
   anything sase stores — is the authoritative record of "what is in sase's environment."

2. **`uv tool install --with X` REPLACES the injected set; it does not append.** Verified: installing a throwaway tool
   `--with pyfiglet`, then re-running it `--with six`, **uninstalled pyfiglet**. Consequence: to add one plugin we must
   re-run install with the **full** desired `--with` set (existing plugins + the new one). There is **no
   `uv tool inject`** subcommand (unlike pipx); `uv tool install --with` is the only injection mechanism.

3. **`uv tool upgrade sase` re-resolves the whole environment** — sase core **and** all `--with` plugins — in one shot.
   This is exactly what `sase update` wants. For a **single** plugin,
   `uv tool install sase --with <full set> --upgrade-package <name>` (uv's `-P`) upgrades just that one and pins the
   rest.

4. **uv tool has no `--dry-run`.** So `sase ... --dry-run` must be implemented by sase: resolve the plan (target
   versions / the exact uv argv / the resulting plugin set) and print it **without executing**.

Two more facts that matter:

- **Editable / dev installs are real and must be preserved.** A developer's sase receipt can pin the primary package and
  plugins to local paths (`editable = "/path/..."`). Reconstructing the `--with` set must faithfully reproduce
  `--editable` / `--with-editable` and version specifiers/extras, or we would silently re-point a dev's editable install
  at PyPI. The reconstruction is derived **from the receipt**, so it round-trips whatever uv recorded.
- **The catalog already resolves names, and target plugins are on PyPI.** The existing `src/sase/plugins/` catalog maps
  a short name (`github`) → repo (`sase-github`) → GitHub URL, and marks installed status. `sase` and `sase-github` both
  resolve on PyPI (HTTP 200), so the default install source is the **distribution name** (PyPI), with a **git fallback**
  for catalog plugins not published to an index.

## Pivotal design decisions (I am leading these)

- **D1 — One shared "uv tool environment" engine.** All three commands sit on a single new pure-logic-plus-thin-
  subprocess module so detection, receipt parsing, command building, and output parsing can never drift and are unit-
  testable without touching a real install. New package: **`src/sase/uv_tool/`** (neutral location: `sase update`
  upgrades core, not only plugins, so this does not belong under `plugins/`).

- **D2 — The receipt is the source of truth for the injected set.** `sase plugin install/update` read
  `<uv-tool-dir>/sase/uv-receipt.toml` (structured TOML via `tomllib`), reconstruct the full `--with` set preserving
  editables/specifiers/extras, dedup by PEP 503-normalized name, then re-run `uv tool install`. We **cross-check**
  against `uv tool list --show-with --show-version-specifiers` for a friendly drift warning, but parse the structured
  receipt as primary (text parsing of `list` output is fragile).

- **D3 — `sase update` == `uv tool upgrade sase`.** This satisfies "update sase and any installed plugins" with one
  atomic re-resolve. We do **not** hand-roll per-package upgrades for the top-level command.

- **D4 — Detection is strict and pure.** "Installed via uv tool" ⇔ `uv` is on `PATH` **and** the running interpreter's
  `sys.prefix` resolves to `<uv-tool-dir>/sase` **and** that dir contains `uv-receipt.toml`. Implemented as a pure
  function over injected inputs (which-result, tool-dir, sys.prefix, receipt-exists) so it is fully testable. Anything
  else (pip/pipx/system, or running from a dev checkout's `.venv`) → fail fast with guidance. This correctly means the
  command **refuses when run from a dev workspace venv** and **works when run as the user's installed `sase`** — the
  safe behavior.

- **D5 — Non-interactive by default; `--dry-run` for preview.** sase is driven by agents in non-interactive shells, so
  the commands **do not prompt**. They execute and render. `-n|--dry-run` prints the resolved plan (exact uv argv +
  resulting plugin set + target versions where known) and exits without running uv. This is both the safety valve and a
  beautiful "explain what I'll do" affordance.

- **D6 — Stays in Python (boundary check).** Per `rust_core_backend_boundary.md`: managing sase's **own** Python/uv
  installation lifecycle is frontend-specific packaging behavior — no web app, editor, or other frontend needs to mirror
  "upgrade the sase python tool via uv" to match the TUI. The plugin **catalog** already lives in Python
  (`src/sase/plugins/`), so install/update naturally extend it. **No `sase-core` (Rust) changes.** (Called out so a
  reviewer can confirm with eyes open.)

## The shared engine — `src/sase/uv_tool/` (Phase 1)

A small package with a clean seam between pure logic (trivially testable) and the one subprocess boundary:

- **`detect.py`** —
  `detect_uv_tool_install(*, which_uv, tool_dir, sys_prefix, receipt_exists) -> UvToolInstall | NotUvToolInstall`. Pure;
  the caller injects the environment probes. Carries the reason for failure so the handler can render a precise message
  (uv-missing vs. wrong-prefix vs. no-receipt).

- **`receipt.py`** — `tomllib`-based parse of `uv-receipt.toml` into a `ToolReceipt`: the primary requirement and the
  ordered list of `Requirement`s (each with `name`, optional `editable` path, optional version specifier, optional
  `extras`). Helpers: `injected_plugins()` (everything that is not the primary `sase` package), and `with_added(spec)` /
  `with_upgraded(name)` that return the reconstructed requirement set, **deduped by normalized name** (warn on a
  conflicting editable-vs-index duplicate rather than silently picking one).

- **`commands.py`** — pure argv builders returning `list[str]`, never executing:
  - `build_upgrade_all()` → `["uv","tool","upgrade","sase"]`
  - `build_install(receipt, *, add=None)` → `uv tool install <primary> --with/--with-editable <each injected> ...`
    (primary rendered as `--editable <path>` or bare `sase`, faithfully from the receipt)
  - `build_upgrade_packages(receipt, names)` → `build_install(...)` + `--upgrade-package <name>` per name
  - Color is forced on for a TTY (`--color always`) and off otherwise, so our parser sees stable text.

- **`runner.py`** — the **only** subprocess code, following the repo's existing runner conventions (argv list,
  `check=False`, capture, timeout, `FileNotFoundError` → typed error). Parses uv's stdout/stderr (`+ pkg==X`,
  `- pkg==Y`, `Resolved`, `Installed`, `Uninstalled`) into a structured **`UvChangeSet`**: per package, classify as
  added / removed / upgraded (`old → new` when a name appears in both `-` and `+`) / unchanged.

- **`errors.py`** — `UvNotFoundError`, `NotAUvToolInstallError`, `UvCommandFailedError`, each carrying a
  ready-to-render, actionable message (the "crash with a good error message" requirement).

**Phase 1 ships no user-facing command** — only the engine and exhaustive unit tests (sample receipts incl. editable +
duplicate entries; sample uv stdout for install/upgrade/no-op; detection truth table). `just check` is green.

## `sase update` (Phase 2)

- **Parser** `src/sase/main/parser_update.py` → `register_update_parser` (top-level, alphabetical: between `telemetry`
  and `validate`). Flags (each with a short alias, sorted): `-j|--json`, `-n|--dry-run`, `-q|--quiet`. Rich
  `description` + `epilog` examples matching the `sase plugin` help bar.
- **Handler** `src/sase/main/update_handler.py` wired into `entry.py` (`args.command == "update"`).
- **Flow:** detect (D4) → on failure render the typed error and exit non-zero → else run `build_upgrade_all()` under a
  `rich` status spinner → parse `UvChangeSet` → render.
- **Beautiful output** (`render` in `src/sase/uv_tool/`): mirror the catalog renderer's grammar (Panel, borderless
  Table, glyphs `✓ · ⚠`, green/cyan/yellow/dim, `_humanize` helpers):

  ```
  ✓ sase           0.5.0 → 0.6.1
  ✓ sase-github    0.3.2 → 0.4.0
  · sase-telegram  0.1.0   (already current)

  Updated sase + 1 plugin in 4.2s · 1 already current
  Restart running sase agents to pick up the new version.
  ```

  Nothing-to-do renders a clean "Already up to date" state. `--json` emits a versioned, sorted machine payload
  (schema-version constant, like the catalog commands). `--dry-run` prints the planned uv argv + current versions and
  exits 0 without executing.

- **Tests:** handler with an injected fake runner asserts the uv argv, exit codes, the dry-run path, and rendered output
  (Console into a `StringIO`); `UvChangeSet` parsing snapshots. No real uv.

## `sase plugin install <plugin>` / `sase plugin update <plugin>` (Phase 3)

- **Parser** — extend `register_plugin_parser` with `install` and `update` subparsers; update the group metavar to the
  **sorted** `{install,list,show,update}` and add epilog examples. The existing bare-`sase plugin` → `list` default is
  untouched (the central `_default_list_subcommands` keys off the exact `list` child).
  - `install`: positional `<plugin>`; flags `-j|--json`, `-n|--dry-run`, `-r|--refresh` (catalog refetch), `-g|--git`
    (force install from the repo's git URL).
  - `update`: positional `<plugin>` (optional when `-a|--all`); flags `-a|--all`, `-j|--json`, `-n|--dry-run`,
    `-r|--refresh`.
- **Handler** — extend `plugin_handler.py` to dispatch `install` → `cli_install.py`, `update` → `cli_update.py` (new
  modules in `src/sase/plugins/`, alongside `cli_list.py`/`cli_show.py`).
- **Name → install-spec resolution** (its own documented function):
  1. If `<plugin>` is already a requirement/URL (`==`, `>=`, `/`, `git+`, `://`) → passthrough.
  2. Else resolve through the catalog (`find_plugin`): found → spec is the **distribution name** (e.g. `sase-github`);
     with `--git` or when the entry is not on an index → `git+<url>`.
  3. Not found → the existing ranked **"did you mean…?"** miss view (`suggest_plugins` / `render_show_not_found`
     pattern) + non-zero exit.
- **install flow:** detect (D4) → resolve spec → read receipt → if already injected and unchanged, render an idempotent
  "already installed — run `sase plugin update <name>` to upgrade" and exit 0 → else `build_install(receipt, add=spec)`
  (the **full** reconstructed `--with` set, per finding #2) under a spinner → render the result (✓ installed `name`
  vX.Y.Z, plus the **new entry-point groups** it contributes, parsed from the post-install inventory) with a next-step
  hint.
- **update flow:** detect → resolve → ensure injected (else suggest `install`) →
  `build_upgrade_packages(receipt, [name])`; `--all` upgrades every injected plugin while leaving sase core pinned
  (per-package `-P`, **not** `uv tool upgrade`, so "update plugins" never silently bumps core) → render the `old → new`
  change set.
- **Housekeeping:** update the catalog `show` view's `_install_hint()` (today: "install it from its repository, then run
  `sase doctor`") to point at the real `sase plugin install <name>`, closing the loop between discovery and install.
- **Tests:** spec resolution (catalog name / raw spec / git / miss); receipt reconstruction preserves editables, dedups,
  and adds the new plugin; install/update argv built correctly; idempotent + not-installed branches; dry-run; rendering.

## End-to-end verification + polish (Phase 4)

The Phase 2/3 agents run inside dev-checkout venvs and **cannot** safely exercise the real `uv tool install sase` path.
This phase closes that gap **without ever touching the real sase install**, using a disposable tool as a stand-in:

- **Real-uv behavioral harness** (a throwaway tool, e.g. `cowsay`, installed/upgraded/uninstalled in the test) asserting
  the load-bearing assumptions on the actual uv binary: (a) reconstruct-then-install preserves a previously-injected
  plugin (guards finding #2); (b) `--upgrade-package` upgrades exactly one injected package (pin an intentionally old
  `--with` version, then upgrade it); (c) `uv tool upgrade <tool>` bumps an injected package. Gated to skip cleanly when
  `uv` is absent (CI parity).
- **Holistic beauty + `-h` sweep** across all three commands: options sorted and short-aliased, descriptions/epilogs at
  the `sase plugin` bar, colored output coherent with the catalog renderer, consistent glyph/color legend.
- **Docs:** add mkdocs pages (or extend the plugins page) for `sase update` and `sase plugin install/update`; confirm
  top-level `sase --help` / `-H` list `update` (automatic via registration). Verify no `SKILL.md` documents these
  commands (the CLI/skill-sync rule is scoped to `sase commit`); if any does, regenerate via `sase skill init --force`.
- Final `just install && just check` green; a short manual smoke of `--dry-run` for all three.

## CLI-rules compliance (applies to every phase)

- `-h|--help` excellent, complete, scannable; subcommands and options **sorted alphabetically**; every public long
  option has a short alias; prefer beautiful colored output. (Plugin metavar becomes `{install,list,show,update}`.)
- `sase update` is a plain top-level command (no `list` child) — the bare-group→`list` machinery does not apply.

## Files expected to change / add (Python only — no Rust)

- **New** `src/sase/uv_tool/{__init__,detect,receipt,commands,runner,errors,render}.py` — the shared engine + update
  rendering.
- **New** `src/sase/main/parser_update.py`, `src/sase/main/update_handler.py`; register in `src/sase/main/parser.py` and
  route in `src/sase/main/entry.py`.
- **New** `src/sase/plugins/cli_install.py`, `src/sase/plugins/cli_update.py`.
- **Edit** `src/sase/main/parser_plugin.py` (install/update subparsers + sorted metavar/examples),
  `src/sase/main/plugin_handler.py` (dispatch), `src/sase/plugins/render.py` (install/update result rendering + fix
  `_install_hint`).
- **Tests** under `tests/` for the engine, both new commands, spec resolution, rendering, and the Phase-4 real-uv
  harness.
- **Docs** under the mkdocs tree.

## Out of scope (possible follow-ups)

- `sase plugin uninstall <plugin>` (the natural symmetric command — reconstruct `--with` set minus the plugin). Easy on
  this engine; deferred to keep this change focused.
- Migrating/repairing a non-uv install (e.g. offering to run `uv tool install sase` for a pip user) — for now we only
  detect and guide.
- Pinning plugins to explicit versions in `sase plugin install <name>==x.y` beyond raw-spec passthrough (works via
  passthrough already, but no first-class `--version` flag in v1).
- Neovim/editor or web surfaces — none; this is Python-CLI installer lifecycle only.

## Suggested phasing (each independently shippable; `just check` green at every phase)

1. **Engine** — `src/sase/uv_tool/` (detect, receipt, commands, runner, errors) + exhaustive unit tests. No CLI surface.
2. **`sase update`** — parser/handler/render/json/dry-run on the engine; wire into `parser.py`/`entry.py`; tests; docs.
3. **`sase plugin install` + `sase plugin update`** — subparsers, catalog spec-resolution, handlers, `--all`, dry-run,
   rendering, `_install_hint` fix; tests; docs.
4. **Verification + polish** — real-uv throwaway-tool harness, holistic `-h`/beauty sweep, mkdocs pages, final green
   run.
