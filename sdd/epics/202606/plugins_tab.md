---
create_time: 2026-06-26 09:35:15
status: done
prompt: sdd/prompts/202606/plugins_tab.md
bead_id: sase-59
tier: epic
---
# Plan: Add a "Plugins" tab to SASE Config (manage plugins from the TUI)

## Goal

Add a third internal tab, **Plugins**, to the `sase ace` SASE Config modal (the full-screen modal opened with `#`),
placed **between `Settings` and `XPrompts`**. The tab must let a user do everything the `sase plugin` CLI can do —
browse the catalog, inspect a plugin, install (from index or git), and update one plugin or all of them — rendered as an
intuitive, reliable, and beautiful TUI experience that stays consistent with the CLI.

## Product context

`sase plugin` is the canonical way to manage SASE plugins. Its surface (confirmed from `src/sase/main/parser_plugin.py`)
is exactly four subcommands plus shared flags — there is **no** uninstall / enable / disable:

- **`list`** — catalog of all known plugins (GitHub `topic:sase-plugin`), split into **Built-in** (`sase-org`) and
  **Community** (third-party, shown with a warning). Marks installed (`●`), available (`○`), and update-available (`↑`).
  Flags: `-v/--verbose` (stars, last-updated, topics), `-o/--offline`, `-r/--refresh`, `-j/--json`.
- **`show <plugin>`** — rich detail for one plugin: description, install status + entry-point groups, latest version +
  source, repo/homepage, topics, stars, last update, license, community warning; ranked suggestions on a miss. Flags:
  `-o/--offline`, `-r/--refresh`, `-j/--json`.
- **`install <plugin>`** — install into sase's `uv tool` environment by reconstructing uv's `--with` set from the
  receipt. Flags: `-g/--git`, `-n/--dry-run`, `-r/--refresh`, `-j/--json`. Requires a managed `uv tool install sase`;
  otherwise fails fast with an actionable message. Handles already-installed and not-found-with-suggestions.
- **`update [<plugin>] | -a/--all`** — upgrade one installed plugin (or every one) while keeping sase core pinned.
  Flags: `-a/--all`, `-n/--dry-run`, `-r/--refresh`, `-j/--json`.

The Config Center modal (`src/sase/ace/tui/modals/config_center_modal.py`) is a `ModalScreen` hosting tabs over a
`ContentSwitcher`. Tabs are enumerated in five spots: the `CenterTab` `Literal`, `_TAB_ORDER`, `_TAB_LABELS`,
`_TAB_COLORS`, and `compose()`. `[` / `]` cycle tabs; a centered clickable tab strip and a header divider already exist.
The **XPrompts** tab (`xprompt_browser_pane.py`) is the closest analog: a master/detail pane (grouped `OptionList` +
scrollable preview/metadata) with a filter input, off-thread loading, and modal-driven actions. The **Settings** tab
(`config_pane*.py`) shows the established async pattern: paint cached data instantly, load off-thread via
`run_worker(thread=True)`, reconcile in `on_worker_state_changed`.

## How CLI flags map to the TUI (explicit decisions)

The TUI replicates every **operation**; the output-format flags map to UI affordances or are deliberately N/A:

- `-r/--refresh` → an in-pane **Refresh** action (`r`) that refetches catalog + latest versions.
- `-o/--offline` → an **Offline** toggle (`o`) with a visible indicator; cache-first loads otherwise.
- `-v/--verbose` (list) → a **verbose** toggle for the list rows (stars / updated); the detail panel always shows the
  full metadata, so `show -v`-equivalent richness is permanent.
- `-n/--dry-run` (install/update) → **subsumed into a confirm-with-preview modal**: every mutation first shows the exact
  `uv` command and the resolved plugin set, with Confirm / Cancel. The confirmation _is_ the dry-run, which is both
  safer and more discoverable than a hidden mode.
- `-g/--git` (install) → an **"install from git"** option offered in the install confirm modal.
- `-a/--all` (update) → an **Update all** action.
- `-j/--json` → **intentionally not replicated**: JSON is the CLI's machine-output seam for scripting and has no
  meaningful interactive analog; the TUI surfaces the same information visually. (Called out so this is a conscious
  decision, not an omission.)
- **No uninstall / enable / disable** — the CLI has none, so the tab has none (parity, not a gap).

## Design — UX (intuitive, reliable, beautiful)

**Layout: master/detail**, mirroring the XPrompts tab so the modal feels coherent.

- **Header summary line** (top): `N plugins · M installed · K updates available · <cache age>` — mirrors the CLI list
  footer so users orient instantly. An **Offline** badge appears here when offline mode is on; a stale-cache/warning
  hint appears here when present.
- **Filter input** (`/` to focus): case-insensitive match over name / description / topics.
- **Left list panel** (fixed width): a grouped `OptionList` with disabled `── Built-in ──` / `── Community ──` headers
  (community in a warning hue), each row = status glyph + name + version + `↑` update marker. Glyph semantics match the
  CLI exactly: `●` installed (green), `○` available (dim), `↑` update available (accent). Verbose toggle adds stars /
  updated columns.
- **Right detail panel** (flex): the `show`-equivalent — built by reusing the CLI's Rich detail/warning builders so the
  TUI and `sase plugin show` are visually identical. Community plugins lead with the same prominent warning.
- **Pane hints line** (bottom): context-sensitive actions for the highlighted plugin (e.g. `i install` only when not
  installed; `u update` only when an update is available), plus global `r refresh`, `o offline`, `/ filter`.

**Actions & keymaps** (pane-local `BINDINGS`, matching how the other panes self-register; **no** `default_config.yml`
change is expected because these are widget-local, but the implementer must verify):

- `i` — **Install** the highlighted plugin (only when not installed). Opens the confirm-preview modal; an in-modal
  toggle chooses index (default) vs. git.
- `u` — **Update** the highlighted plugin (only when installed; emphasized when an update is available).
- `U` — **Update all** installed plugins.
- `r` — refresh (refetch), `o` — toggle offline, `v` — toggle verbose, `/` — focus filter, `[` / `]` — switch tabs
  (forwarded from the filter input like the other panes), `esc` / `q` — close.

**Reliability behaviors:**

- When sase is **not** a managed `uv tool install`, the tab still browses normally, but install/update are disabled and
  the hints/detail explain why (the same actionable message the CLI gives), detected once via `probe_uv_tool_install`.
- Mutations always confirm first (preview), then run as **tracked background tasks** (top-right indicator + Task Queue),
  so a multi-second `uv` run never blocks the UI and is never silently lost. On completion: a success/error toast and an
  automatic catalog refresh so the row's status/version update in place.
- Not-found / suggestions, already-installed, not-installed, and no-plugins cases reuse the CLI's resolution outcomes so
  messaging matches the CLI verbatim.

## Design — technical (single source of truth; no reimplementation)

Two reuse seams keep the TUI thin and guarantee CLI/TUI parity, honoring the Rust-core-boundary rule's spirit (frontends
must not reimplement shared domain behavior):

1. **Headless plugin operations layer.** Today the install/update _resolution_ and _orchestration_ live as private
   helpers inside `cli_install.py` / `cli_update.py`, interleaved with `Console` printing and JSON emission. Extract the
   pure logic into a new console-free module (e.g. `src/sase/plugins/operations.py`) exposing a **plan / execute**
   split:
   - `plan_install(query, *, git, refresh, offline) -> InstallPlan` where `InstallPlan` is a typed outcome:
     `NotUvTool | NotFound(suggestions) | AlreadyInstalled | Ready(argv, requirement, display_name, source)`.
   - `execute_install(plan) -> InstallOutcome` (runs uv, returns change-set / version / groups / elapsed).
   - `plan_update(query|all, *, refresh, offline) -> UpdatePlan`
     (`NotUvTool | NoPlugins | NotInstalled | Unknown(suggestions) | Ready(argv, targets, all)`).
   - `execute_update(plan) -> UpdateOutcome`.

   Keep the existing injectable seams (`load_fn`, `probe_fn`, `run_fn`, …) so unit tests can still inject fakes. Then
   **refactor `cli_install.py` / `cli_update.py` to delegate** to this layer and only handle rendering, JSON, and exit
   codes — preserving every existing JSON shape, exit code, and test. The TUI calls the same `plan_*` / `execute_*`
   functions: `plan_*` powers the confirm-preview (the dry-run), `execute_*` runs inside the tracked task. `list` /
   `show` data already has a clean console-free seam (`load_plugin_catalog`, `find_plugin`, `suggest_plugins`); reuse it
   as-is.

2. **Frontend-agnostic Rich renderables.** Promote the existing private builders in `render_catalog.py`
   (`_detail_panel`, `_community_warning_panel`, and the list section/table helpers) to public, console-free functions
   returning `RenderableType`. The CLI renderers print them; the TUI detail `Static` displays the same renderable. This
   yields visual parity for free and avoids a second rendering implementation.

**No Rust changes.** The plugin domain is already a shared _Python_ layer consumed by the CLI; the TUI consuming that
same layer (via seams 1 & 2) satisfies the cross-frontend-consistency litmus test without a Rust rewrite. Implementers
must **not** reimplement catalog/uv logic in the TUI and must **not** port plugin logic to `sase-core`.

**Performance (per `tui_perf.md`):** never block the event loop — catalog loads run off-thread
(`run_worker(thread=True)`, cache-first instant paint then background refresh); `uv` mutations run as tracked background
tasks (`_submit_tracked_task`); re-capture the highlighted plugin after every `await` before applying results; guard
`OptionList` programmatic-highlight echoes with a flag cleared in `finally`; debounce the detail panel while leaving the
highlight instant.

## Phases

Each phase is a self-contained unit for a distinct agent, ends green (`just install` then `just check`, plus visual
snapshots where UI changed), and builds on the previous.

### Phase 1 — Headless plugin operations layer + renderable promotion (no TUI)

Create the console-free operations layer (`operations.py`) with the `plan_*` / `execute_*` API and typed outcomes; move
the resolution/orchestration logic out of `cli_install.py` / `cli_update.py` and refactor those handlers to delegate
(behavior-, JSON-, and exit-code-preserving). Promote the Rich detail/list builders in `render_catalog.py` to public
console-free functions. Add unit tests for the new layer; all existing plugin CLI tests must pass unchanged. Foundation
only — no TUI files touched.

### Phase 2 — Plugins tab + read-only list browse

Register the new tab in all five enumeration spots (`CenterTab`, `_TAB_ORDER`, `_TAB_LABELS`, `_TAB_COLORS`,
`compose()`) **between `config` and `xprompts`**, and export a new `PluginsBrowserPane`. Build the pane skeleton: header
summary line, filter input, grouped filterable `OptionList` (Built-in/Community), pane hints. Wire cache-first
off-thread catalog loading with loading / empty / error states. Detail panel is a placeholder ("Select a plugin…") in
this phase. Add the `styles.tcss` section and `modals/__init__.py` export. Add visual snapshots for the list (loading /
populated / empty). Delivers the `list` experience.

### Phase 3 — Detail panel + navigation, refresh, offline, verbose

Render the `show`-equivalent detail panel by displaying the promoted Rich renderables, driven by the highlighted row
(debounced; highlight stays instant). Add `r` refresh, `o` offline toggle (with header badge), `v` verbose toggle, and
the live header summary counts. Handle the warnings/stale-cache surface. Add detail + offline/verbose snapshots.
Completes the read-only (`list` + `show`) experience.

### Phase 4 — Install action

Add a reusable **confirm-preview modal** that shows the exact `uv` argv + resolved plugin set with an index/git toggle
(built from `plan_install`). Wire `i` to: detect uv-tool-managed install (disable + explain otherwise), preview, then
`execute_install` inside a tracked background task, with success/error toast and automatic post-install refresh. Handle
already-installed and not-found/suggestions outcomes with CLI-matching messaging. Add snapshots for the preview modal
and the disabled/unavailable state.

### Phase 5 — Update actions (single + all)

Reuse Phase 4's confirm-preview modal and tracked-task pattern for `u` (single) and `U` (all), built from `plan_update`
/ `execute_update`. Handle not-installed, no-plugins, and unknown outcomes with CLI-matching messaging; refresh after.
Add update-preview / update-all snapshots.

### Phase 6 — Polish, help, docs, and final QA

Update the `?` help popup (per the ace AGENTS.md "Help Popup Maintenance" rule) and `docs/configuration.md` to document
the Plugins tab and its keymaps; finalize the pane hints; confirm no `default_config.yml` change is needed (and add one
if it turns out bindings are config-driven). Sweep all Config Center visual goldens for the now-three-tab header,
eyeball every one, and do an edge-case pass (offline, not-uv-tool, empty catalog, community warning, long descriptions).

## Affected files (indicative)

- `src/sase/plugins/operations.py` _(new)_ — headless plan/execute layer.
- `src/sase/plugins/cli_install.py`, `src/sase/plugins/cli_update.py` — delegate to the new layer.
- `src/sase/plugins/render_catalog.py` — promote detail/list builders to public renderables.
- `src/sase/ace/tui/modals/config_center_modal.py` — register the third tab (five spots).
- `src/sase/ace/tui/modals/plugins_browser_pane.py` _(new)_ — the Plugins pane.
- `src/sase/ace/tui/modals/plugin_action_confirm_modal.py` _(new)_ — confirm-preview modal (Phase 4, reused Phase 5).
- `src/sase/ace/tui/modals/__init__.py` — export the new pane/modal.
- `src/sase/ace/tui/styles.tcss` — `PluginsBrowserPane` + confirm-modal section.
- `src/sase/ace/tui/modals/help_modal.py`, `docs/configuration.md` — document the new tab (Phase 6).
- `tests/...` — unit tests for the operations layer; TUI/pane tests; new + regenerated Config Center PNG goldens.

## Verification

- Every phase: `just install` then `just check` (ruff + mypy + tests), green before handoff.
- UI phases: regenerate Config Center goldens with `just test-visual … --sase-update-visual-snapshots` and **eyeball
  every** golden (the header is now three tabs; nothing should clip or misalign).
- Confirm tab **click** hit-testing still selects the right tab with three centered tabs.
- Confirm install/update **always** preview before running and run as tracked tasks (never block the UI); confirm the
  non-uv-tool path disables mutations with the CLI's actionable message.
- Confirm CLI parity: existing `tests/test_plugin_cli_*.py` pass unchanged after the Phase 1 refactor.

## Risks & mitigations

- **CLI refactor regressions (Phase 1).** Mitigated by keeping injectable seams and treating the existing
  `test_plugin_cli_*` suite as the behavior-preserving safety net; no JSON/exit-code changes.
- **Blocking the event loop on slow network/`uv`.** Mitigated by off-thread cache-first loads and tracked-task mutations
  per `tui_perf.md`; re-capture selection after awaits; guard `OptionList` echoes.
- **Snapshot churn across all Config Center goldens.** Mitigated by regenerating and individually eyeballing each, and
  accepting only after visual confirmation.
- **Scope creep into uninstall/enable.** Out of scope by design (the CLI has neither); documented as deliberate parity.
- **Tab color / detail taste.** The Plugins tab accent and detail spacing are tunable at snapshot-review time.
