---
create_time: 2026-06-26 16:34:51
status: done
prompt: sdd/prompts/202606/logs_admin_center_tab.md
---
# Plan: Migrate the `,L` Logs panel into the SASE Admin Center as a "Logs" tab

## 1. Goal

Retire the standalone `,L` Logs modal and re-home it as a new **Logs** tab in the SASE Admin Center (`#`), inserted
**immediately after the Config tab**. The new tab must reproduce _everything_ the old panel did, feel native to the
Admin Center, and be intuitive, reliable, and beautiful. The `,L` leader keymap is removed.

This is the exact same migration the **Projects** panel already underwent (its standalone `,p` modal was retired and
re-homed as the Admin Center's Projects tab). We deliberately follow that precedent end-to-end so the result is
consistent with the codebase's established pattern.

## 2. Background: what exists today

**The Admin Center** (`ConfigCenterModal`, `src/sase/ace/tui/modals/config_center_modal.py`) is a full-screen
`ModalScreen` hosting four tabs over a `ContentSwitcher`: `Config → Projects → Plugins → XPrompts`. Tabs are declared in
three parallel structures — `CenterTab` (a `Literal`), `_TAB_ORDER`, `_TAB_LABELS`, and `_TAB_COLORS` — rendered by a
clickable `_ConfigCenterTabStrip`, and switched with `[` / `]` (modulo-wrapping) or mouse clicks. Each tab is a
`Vertical` pane with `can_focus = False`, a `focus_default()` method, its own `BINDINGS`, and an `id` matching its tab
name. `#` opens the modal on Config.

**The Logs panel** (`LogModal`, `src/sase/ace/tui/modals/log_modal.py`) is a two-pane modal opened globally from any tab
via `,L`:

- **Left** — an `OptionList` of 8 curated log _sources_ from the backend registry (`src/sase/ace/tui/logs/sources.py`):
  Launch & Fan-out Failures (default), TUI Diagnostics, TUI Stalls, TUI External Tools, TUI Git Operations, Launch
  Timing, Agent Runs, Events. Each row is a two-line entry: a status glyph (`●` non-empty / `○` empty) + title, then a
  dim size · last-modified subtitle.
- **Right** — a `VerticalScroll` showing the selected source's colorized tail: a header (title, description,
  `~/.sase`-relative path, mtime, shown-line count) and the body. `text` sources render verbatim; `jsonl` sources are
  pretty-rendered one compact line per record. Severity colorization: red errors/tracebacks, gold warnings, cyan
  timestamps, dimmed stack frames and separators.
- **Behavior** — efficient `O(tail)` reads bounded to 500 lines (`read_tail_seek`); manual refresh (`r`) re-reads the
  highlighted source and rebuilds the rows (logs grow live); per-source scroll reset on selection; copy mode (`%`) for
  clipboard work. No filtering/search, no auto-refresh.
- **Keybindings** — `j/k` · `↓/↑` · `ctrl+n/p` navigate sources; `[` / `]` cycle sources (wrapping); `ctrl+d/u`
  half-page scroll the detail; `g` / `G` scroll detail to top/bottom; `r` refresh; `esc` / `q` close.

The pure rendering helpers in `log_modal.py` (`_render_log_detail`, `_styled_log_line`, `_line_severity_style`,
`_format_size`, `_format_mtime`, `_display_path`, `_empty_message`) are already module-level and unit-tested. The
backend registry `sources.py` is independent of the modal.

## 3. Design

### 3.1 Shape — a native Admin Center pane that preserves the two-pane layout

Create `LogsPane(Vertical)` modeled on `ConfigPane`, keeping the Logs panel's beloved two-pane layout but dressing it in
the Admin Center's visual idiom (pane title with a live count, "Sources"/"Detail" region headers, a bottom hints line
mirroring the Config pane's format):

```
Logs  [8 sources · N active]                 ← pane title (live count)
┌ Sources ───────────┐ ┌ Detail ──────────────────────────────┐
│ ● Launch & Fan-out  │ │ Launch & Fan-out Failures             │  ← gold
│   Failures          │ │ Every launch/fan-out… failure         │  ← dim
│   1.2 KB · 14:30    │ │ ~/.sase/logs/launch_failures.log · …   │  ← cyan
│ ○ TUI Diagnostics   │ │ ──────────────────────────────────────│
│   empty             │ │ [2026-06-17 14:30 UTC] …  (colorized)  │
│ ● TUI Stalls        │ │ …                                      │
│   …                 │ │                                        │
└─────────────────────┘ └────────────────────────────────────────┘
j/k: move   ctrl+d/u: scroll   g/G: top/bottom   r: refresh   [ / ]: tab   Esc: close
```

The pane reuses the existing `config-region-header` CSS class for the "Sources"/"Detail" headers so it is visually
identical to the other tabs, and the right detail keeps the same `scrollbar-gutter: stable` treatment as the Config
detail so content doesn't jump when the scrollbar appears.

### 3.2 Reuse, don't reimplement — move the rendering logic, keep the registry

- The backend registry `src/sase/ace/tui/logs/sources.py` is **unchanged** — it is already the backend↔UI contract and
  is independent of the modal.
- The pure rendering helpers move **as-is** from `log_modal.py` into the new `logs_pane.py` (they are already pure,
  module-level, and tested). This keeps the existing rendering unit tests valid with only an import-path change and is
  the lowest-risk way to guarantee pixel-level parity of the detail body.
- `log_modal.py` is deleted; `LogModal` is removed from `src/sase/ace/tui/modals/__init__.py`.

### 3.3 Key interaction decisions (the deliberate design calls)

1. **`[` / `]` belong to tab switching, not source cycling.** Inside the Admin Center, `[` / `]` is the universal
   "previous/next tab" gesture, and the `OptionList` doesn't bind those keys, so they bubble to the host modal
   automatically. The old panel's `[` / `]` source-cycling was functionally a duplicate of `j/k` (just with wrap), so
   **no capability is lost** — source selection remains fully available via `j/k`, `↓/↑`, and `ctrl+n/p`, all of which
   drive the same highlight→detail-update path. This is the single most important consistency decision: every Admin
   Center tab cycles with `[` / `]`, and Logs must too.

2. **Detail scrolling stays on the pane while the source list holds focus.** `ctrl+d/u`, `g`, `G`, and `r` are declared
   in `LogsPane.BINDINGS`; because Textual key events bubble from the focused `OptionList` up through its ancestor pane,
   these fire exactly as they did on the old modal — preserving the "browse on the left, scroll the right" feel with no
   focus juggling. These bindings are pane-scoped, so `g`/`r` here don't collide with the Config pane's `g` (migrate) /
   `r` (refresh).

3. **Copy mode (`%`) is preserved and scoped to the Logs tab.** `LogsPane` mixes in `CopyModeForwardingMixin` (the same
   mixin the old `LogModal` used). Put on the pane rather than the host modal, copy-mode forwarding activates only when
   focus is within the Logs tab — preserving the old capability without silently changing behavior on the
   Config/Projects/Plugins/XPrompts tabs.

4. **`esc` / `q` close the whole Admin Center**, handled by the host modal's existing bindings — no per-pane dismiss.
   (We do **not** reuse `OptionListNavigationMixin`, whose `escape`/`q` call `dismiss` and whose model is
   screen-oriented; the pane defines its own small navigation actions that delegate to the `OptionList` cursor, exactly
   as `ConfigPane` delegates to its `Tree`.)

5. **Logs gets its own tab color** in `_TAB_COLORS`: amber/gold `#FFD700`, echoing the warning/title color of the log
   palette for thematic continuity and staying visually distinct from the existing teal/orange/purple/cyan tabs. (Easy
   to retune during review.)

6. **`on_mount` selects the first source** (Launch & Fan-out Failures) and renders its detail, matching the old panel's
   default. `focus_default()` focuses the source `OptionList` (browse-first), matching every other tab.

### 3.4 Access path after `,L` is removed (mirrors the Projects migration)

- **Primary:** `#` opens the Admin Center; `]` once lands on Logs (it is the tab immediately right of Config).
- **Fast path:** a **keyless command-palette entry** "Open logs panel" (aliases like `logs`, `log panel`,
  `launch failures`, `diagnostics`) that opens the Admin Center pre-focused on Logs — exactly mirroring the existing
  keyless "Open project management panel" command. Backed by a new `open_log_panel` app action that does
  `ConfigCenterModal(initial_tab="logs")`.
- **Failure toasts** that today say "press ,L for the log" (`failure_messages.py`, used by ~10 launch/chop failure
  sites) are updated to point at the new home, e.g. `LOG_PANEL_HINT = "see Logs in SASE Admin Center (#)"`. The hint
  stays a single short clause appended to the existing error text.

## 4. Functionality parity checklist (nothing left out)

| Old `,L` capability                         | New Logs tab                                            |
| ------------------------------------------- | ------------------------------------------------------- |
| 8 log sources, launch-failures default      | ✅ same registry, same default via `on_mount`           |
| Two-line source rows (glyph + size · mtime) | ✅ rendering moved verbatim                             |
| Colorized detail header + body              | ✅ pure render helpers moved verbatim                   |
| `text` verbatim / `jsonl` pretty-render     | ✅ unchanged (registry)                                 |
| Severity colors (error/warn/timestamp/dim)  | ✅ unchanged                                            |
| `O(tail)` bounded 500-line reads            | ✅ unchanged                                            |
| `j/k` · `↓/↑` · `ctrl+n/p` source nav       | ✅ pane nav actions → OptionList cursor                 |
| `[` / `]` source cycle                      | ➡️ replaced by `j/k` (no loss); `[`/`]` now cycles tabs |
| `ctrl+d/u` detail half-page scroll          | ✅ pane bindings                                        |
| `g` / `G` detail top/bottom                 | ✅ pane bindings                                        |
| `r` refresh (re-read + rebuild rows)        | ✅ pane action                                          |
| Per-source scroll reset on select           | ✅ in detail-update handler                             |
| Copy mode (`%`)                             | ✅ `CopyModeForwardingMixin` on the pane                |
| Opens from any context                      | ✅ `#` from any tab; keyless command anywhere           |
| `esc`/`q` close                             | ✅ host modal bindings                                  |

## 5. Implementation breakdown

### Create

- **`src/sase/ace/tui/modals/logs_pane.py`** — `LogsPane(CopyModeForwardingMixin, Vertical)`: `compose()` (title +
  Sources/Detail panels + hints), `on_mount` (highlight source 0, render its detail), `focus_default` (focus source
  list), navigation actions (delegate to the `OptionList` cursor), detail-update + scroll-reset on
  `OptionList.OptionHighlighted`, and actions `refresh`/`scroll_detail_down`/`scroll_detail_up`/`scroll_to_top`/
  `scroll_to_bottom`. The pure render helpers move here from `log_modal.py`.

### Modify

- **`config_center_modal.py`** — add `"logs"` to `CenterTab`, `_TAB_ORDER` (position 2, after config), `_TAB_LABELS`,
  `_TAB_COLORS`; import `LogsPane`; `yield LogsPane(id="logs")` as the second pane in the `ContentSwitcher`.
- **`styles.tcss`** — add `ConfigCenterModal LogsPane { width/height: 100% }` to the shared pane rule, plus
  `LogsPane`-scoped rules for the panels, source rail (fixed-ish width like the old 38-col list), and detail scroll
  (mirroring the `ConfigPane` detail). Remove the old `LogModal … ` block.
- **`actions/base.py`** — replace `action_show_log_panel` (push `LogModal`) with `action_open_log_panel` →
  `ConfigCenterModal(initial_tab="logs")` (mirrors `action_open_projects_panel`).
- **`commands/catalog.py`** + **`commands/_app_metadata.py`** — add a keyless `_iter_logs_command` registered in
  `build_command_catalog`, mirroring `_iter_projects_command`; optionally add `logs` to the `open_config_center`
  aliases.
- **`modals/__init__.py`** — drop the `LogModal` import/export.
- **`failure_messages.py`** — update `LOG_PANEL_HINT` to point at the Admin Center Logs tab.

### Remove `,L`

- **`src/sase/default_config.yml`** (line ~211) and **`keymaps/types.py`** (line ~452) — delete `log_panel: "L"` from
  leader-mode keys (kept in parity, per the keymap convention).
- **`actions/agent_workflow/_leader_mode.py`** — delete the `log_panel` dispatch branch.
- **`widgets/_keybinding_modes.py`** — delete the `bindings.append((k("log_panel"), "log panel"))` leader-footer entry.

### Help docs

- Remove the three `,L` "Log panel (launch failures)" entries in `help_modal/agents_bindings.py`,
  `changespecs_bindings.py`, `axe_bindings.py`.
- Update the `#` help description (3 files) from "SASE Admin Center / Projects / Plugins / XPrompts" to include "Logs"
  (e.g. "… / Config / Logs / Projects / …"), keeping the 57-char box width.

### Delete

- **`src/sase/ace/tui/modals/log_modal.py`** (logic moved to `logs_pane.py`).

## 6. Tests

- **Migrate** `tests/ace/tui/test_log_modal.py` → `test_logs_pane.py`: rendering unit tests re-point imports to
  `logs_pane`; pilot tests open `ConfigCenterModal(initial_tab="logs")` and assert: first source selected + detail
  rendered, `j/k` updates detail, `r` refreshes, `ctrl+d/u` and `g/G` scroll the detail, `focus_default` focuses the
  list.
- **Rewrite** `tests/ace/tui/test_log_panel_keymap.py` → drop `,L` assertions; add a regression test that `log_panel` is
  **not** in leader-mode keys (mirroring `test_leader_mode_drops_project_management_key` in
  `tests/test_keymaps_defaults.py`), that the Admin Center exposes a Logs tab after Config, and that the keyless
  command + `open_log_panel` action open the Admin Center on Logs.
- **Update tab-order tests** that will break:
  - `tests/ace/tui/test_plugins_browser_pane_loading.py` — the `next/prev` cycle must become
    `config → logs → projects → plugins → xprompts → config`.
  - `tests/ace/tui/test_projects_pane.py` — `]` from Config now lands on **Logs** (not Projects), and `[` from Projects
    lands on **Logs** (not Config); update these two assertions (or open `initial_tab="projects"` directly).
- **Visual snapshot** — remove `tests/ace/tui/visual/test_ace_png_snapshots_log_panel.py` and its golden
  `log_panel_120x40.png`; add a Logs-tab snapshot mirroring `test_ace_png_snapshots_config_center_config.py` (add a
  `_open_logs_modal` helper to `_ace_config_center_png_snapshot_helpers.py`, seed sample logs). Generate the new golden
  with `--sase-update-visual-snapshots`.
- Confirm `just check` (lint + mypy + `just test`) is green; run `just test-visual` for the PNG suite. Run
  `just install` first (ephemeral workspace).

## 7. Boundary & risk notes

- **Rust core boundary:** none crossed. Log _reading_ already lives in Python (`logs/sources.py` + `read_tail_seek`) — a
  deliberate, documented decision (see `sdd/epics/202606/log_panel.md`). This change is presentation-only Textual state
  (a tab swap), so no `../sase-core` changes are needed.
- **Risk — broken tab-order/navigation tests:** inserting a tab shifts the `[`/`]` neighbors of Config and Projects.
  Identified above; all affected tests are listed and updated as part of the change.
- **Risk — copy mode placement:** scoping `CopyModeForwardingMixin` to the pane (not the host modal) keeps other tabs'
  behavior unchanged; verified by the bubble-up event model the old modal already relied on.
- **Risk — help-modal width:** adding "Logs" to the `#` description must stay within the 57-char box;
  truncate/abbreviate the tab list if needed.

## 8. Out of scope (possible future polish, not in this change)

- A `/` source filter on the Logs tab (every other Admin Center tab has one); marginal value over 8 fixed sources, so
  deferred to keep this change a faithful, reliable migration.
- Live auto-refresh/tailing (the old panel was deliberately manual-refresh).
- Making the detail pane independently focusable for native PageUp/PageDown.
