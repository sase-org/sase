---
create_time: 2026-06-26 18:16:38
status: done
prompt: sdd/prompts/202606/admin_center_tabs.md
---
# Plan: SASE Admin Center — alphabetical numbered tabs, digit jumps, session memory

## Context

The **SASE Admin Center** is a full-screen `ModalScreen` (`ConfigCenterModal`) that hosts six internal tabs over a
`ContentSwitcher`: **Config, Tasks, Logs, Projects, Plugins, XPrompts**. It is opened from the main `sase ace` TUI with
`#` (`open_config_center`), navigated with `[` / `]` (modulo-wrapping), and closed with `escape` / `q`. A clickable
one-line tab strip renders the tabs; each tab has an accent color. Today the tab order is an ad-hoc "migration order"
(Config first, then the panels that were folded in), the modal is recreated fresh on every open (always landing on its
`initial_tab`, default `config`), and there are no per-tab number affordances or hotkeys.

This work makes the Admin Center's tab layout principled, keyboard-fast, and sticky within a session, while keeping the
surface beautiful.

### Key source touch-points (repo-relative)

- `src/sase/ace/tui/modals/config_center_modal.py` — the modal, tab order/labels/colors, tab strip renderer
  (`_ConfigCenterTabStrip`), `[`/`]` navigation, `_switch_to`, close.
- `src/sase/ace/tui/actions/base.py` — `action_open_config_center` (the `#` handler) and the fast-path openers
  `action_open_log_panel` / `action_open_tasks_panel` / `action_open_projects_panel`.
- `src/sase/ace/tui/actions/_state_init.py` — `_init_app_state`, the home for per-session app state.
- `src/sase/ace/tui/modals/help_modal/{changespecs,agents,axe}_bindings.py` — the help-popup row that documents `#`
  (must stay in sync per the ace `AGENTS.md` help-popup rule).
- Tests under `tests/ace/tui/` (unit, integration, and PNG visual snapshots — see Testing).

## Goals

1. **Sort the six tabs alphabetically**, left-to-right.
2. **Number each tab 1–6** (left-to-right), shown in the tab strip, with the matching digit bound as a hotkey that
   focuses that tab whenever the Admin Center is visible. `#3` (open with `#`, then press `3`) must open the Admin
   Center and land on the 3rd tab.
3. **Remember the active tab for the TUI session**: switch tabs, dismiss, reopen with `#` later in the same `sase ace`
   session → the same tab is focused.
4. Lead the design; make it intuitive, reliable, and beautiful.

## Design

### Decision 1 — Alphabetical order (by visible label)

New canonical order and numbering (alphabetical, case-insensitive, by the user-facing label):

| #   | tab id     | label    |
| --- | ---------- | -------- |
| 1   | `config`   | Config   |
| 2   | `logs`     | Logs     |
| 3   | `plugins`  | Plugins  |
| 4   | `projects` | Projects |
| 5   | `tasks`    | Tasks    |
| 6   | `xprompts` | XPrompts |

Implementation: reorder the single source of truth `_TAB_ORDER` (and the display list `_TAB_LABELS`) to this sequence.
`_TAB_COLORS` is keyed by tab id, so each tab keeps its own accent color — only the left-to-right sequence changes.
`ContentSwitcher`'s `initial=` selects by id, so the `compose()` yield order is cosmetic; reorder the yields to match
for readability. Default open tab stays `config` (still alphabetically first → tab 1), so plain `#` behaves as before on
a fresh session.

The position-derived numbering means "tab N" is always `_TAB_ORDER[N-1]` — one source of truth, no parallel number table
to drift.

### Decision 2 — Numbered, beautiful tab strip

Render each tab cell in the strip as `␣N␣Label␣` (number, then label), keeping the existing `│` separators in `#444444`
and the existing horizontal centering. Styling chosen so the number reads as a quiet hotkey hint, not clutter:

- **Active tab**: number in the tab's accent color (normal weight), label `bold {accent}`.
- **Inactive tab**: number in `#666666` (one notch dimmer than the label), label `#888888`.

The numbers become self-documenting affordances: the user sees
`1 Config │ 2 Logs │ 3 Plugins │ 4 Projects │ 5 Tasks │ 6 XPrompts` and can read off the hotkeys. Click hit-testing in
`_ConfigCenterTabStrip.on_click` already maps x-ranges to tabs; extend each recorded range to span the whole `N Label`
cell so clicking the number selects the tab too.

(Considered and rejected a key-cap look like `[1] Config` — more discoverable but noisier; the plain dim-number prefix
is cleaner and keeps the strip elegant on a single line.)

### Decision 3 — Digit hotkeys 1–6 and the `#N` composition

`#N` is **composition, not a new prefix mode**: `#` opens the modal; while the modal is visible the digit `N` focuses
tab N. No app-level digit handling and no new leader mode are introduced — the modal owns digit→tab while it is the
active screen.

Add digit bindings to `ConfigCenterModal.BINDINGS`:

- `1`–`6` → `focus_center_tab(N)`, which switches to `_TAB_ORDER[N-1]` via the existing `_switch_to`.
- `7`,`8`,`9`,`0` → bound to the same action but ignored (N out of range): this **consumes** the digit so the app-level
  saved-query bindings (`load_saved_query_1..0`) cannot fire _behind_ the open modal. This mirrors the existing
  `help_modal` (`help_modal/modal.py`), which already rebinds all ten digits while open for exactly this reason — strong
  precedent that modals must claim digits.

These are **non-priority** bindings (same as the modal's existing `[` / `]` / `q`). Consequences, verified against the
panes:

- No Admin Center pane binds a bare digit, so when a list pane (e.g. Logs/Tasks `OptionList`) has focus the digit
  bubbles to the modal screen and switches tabs — exactly like `[` / `]` do today (proven by existing nav tests).
- Several panes (Config, Projects, Plugins, XPrompts) contain filter `Input`s. A focused `Input` consumes printable
  digits first, so the user can still type digits into a filter; tab-jump only happens when focus is not in a text
  field. This is the intuitive behavior and matches how `q`/`[`/`]` already behave around inputs.

Digit bindings are intentionally **modal-local** (not in `default_config.yml`), consistent with the modal's existing
`[`/`]`/`q`/`escape`. No `default_config.yml` change is required.

### Decision 4 — Per-session active-tab memory

Because the modal is recreated on every open, the remembered tab must live on the long-lived app.

- Add one attribute in `_init_app_state` (`src/sase/ace/tui/actions/_state_init.py`):
  `self._admin_center_tab: str = "config"` (plain str default; the modal already coerces an unknown `initial_tab` back
  to `config`, so this is safe).
- `action_open_config_center` (the `#` handler) reads it: `ConfigCenterModal(initial_tab=self._admin_center_tab)`.
- The modal writes it back through a small guarded helper `_remember_active_tab()` that sets
  `self.app._admin_center_tab = self._active_tab`, called from **`on_mount`** and from the end of **`_switch_to`**. Net
  rule: _the remembered tab always equals the last tab the user was viewing_, regardless of how the modal was opened or
  how it closed (escape, `q`, or otherwise). The helper is wrapped defensively so unmounted unit-test instances (no live
  app) are unaffected.

**Scope of memory — explicit design call:** the fast-path commands `action_open_log_panel` / `action_open_tasks_panel` /
`action_open_projects_panel` still open directly on their named tab (honoring the explicit request, not the remembered
tab). Because memory updates on mount, ending a session on, say, Logs via the "logs panel" command makes the next plain
`#` reopen on Logs. This keeps one simple, predictable mental model — "the Admin Center always reopens where you left
off" — rather than special-casing which entry points count. (Alternative considered: only remember tab changes made
_inside_ the modal and ignore fast-path landings. Rejected as more surprising and harder to reason about. Flagging here
in case you'd prefer that variant.)

### Boundary & non-goals

- **No Rust `sase-core` change.** Tab ordering, numbering, keymaps, and _within-session_ UI memory are presentation-only
  Textual state — a web/CLI frontend would not need to mirror "which Admin Center tab is focused this session." This
  stays in Python per the core-backend litmus test.
- **No persistence across `sase ace` restarts** — the requirement is explicitly per-session.
- **No new app-level keymap / `default_config.yml` entry** — digit jumps are modal-local.

## Implementation outline

1. **`config_center_modal.py`**
   - Reorder `_TAB_ORDER` and `_TAB_LABELS` to the alphabetical sequence; reorder the `compose()` yields to match.
     Update the module docstring (order, `#`/digit usage, session memory).
   - `_ConfigCenterTabStrip._build_content`: render `N Label` per cell with the active/inactive number+label styles
     above; keep separators and centering; record each click range across the full cell.
   - Add digit bindings to `BINDINGS` and implement `action_focus_center_tab(number)` (maps 1–6 → `_TAB_ORDER[N-1]` →
     `_switch_to`; ignores 7/8/9/0 to swallow them).
   - Add `_remember_active_tab()`; call it from `on_mount` and at the end of `_switch_to`.
2. **`actions/base.py`** — `action_open_config_center` passes `initial_tab=self._admin_center_tab`. Leave the three
   fast-path openers unchanged.
3. **`actions/_state_init.py`** — initialize `self._admin_center_tab = "config"`.
4. **Help popup** — update the `open_config_center` row in `help_modal/{changespecs,agents,axe}_bindings.py` to reflect
   the new order and advertise the digit jump, e.g. `"Admin Center: 1-6 jumps to tab"` (≤ 32 chars per the ace
   `AGENTS.md` help-formatting rule). Optionally enrich the command-palette label in `commands/_app_metadata.py`.

## Testing

### Unit / integration (`tests/ace/tui/`)

- **Order**: assert `_TAB_ORDER == ("config","logs","plugins","projects","tasks","xprompts")` and that it is sorted by
  label. Update the now-stale assertions in `test_log_panel_keymap.py` (`test_logs_tab_sits_immediately_after_config`,
  `test_tasks_tab_sits_immediately_after_config`) to the new positions (logs → index 1, tasks → index 4), or replace
  them with the alphabetical-order assertion.
- **`[` / `]` sequence**: update `test_projects_pane.py::test_admin_center_reaches_logs_then_projects_tab_from_config`
  (and its left-bracket sibling) — from Config, `]` now visits Logs → Plugins → Projects; rename/retitle accordingly.
- **Digit jump**: open the modal, press `3`, assert active tab is `_TAB_ORDER[2]` (`plugins`); spot-check a couple more
  digits; assert `7` is a no-op (still on the same tab) and does not switch the main app tab behind the modal.
- **`#N` composition** (AcePage): press `#` then `3`, assert the modal is open on `plugins`.
- **Session memory** (AcePage): `#` → switch to a non-default tab → close → `#` again → assert the same tab is focused.
  Also assert the remembered value survives close via both `escape` and `q`.
- **Numbered strip**: assert the rendered tab-strip plain text contains the `N Label` cells in order (e.g. starts with
  `1 Config`), guarding the numbering/order.

### PNG visual snapshots (`tests/ace/tui/visual/`)

The numbered, reordered tab strip is the shared header of every Admin Center snapshot, so all
`test_ace_png_snapshots_config_center_*` goldens (config, edit, logs, plugin_actions, plugins, projects, tasks) will
change. Plan:

- Run `just test-visual` to see the diffs; inspect `.pytest_cache/sase-visual/` actual/expected/diff to confirm the
  numbered strip looks clean and the new order is correct.
- Regenerate goldens with the update flag (`--sase-update-visual-snapshots`) **only after** visually confirming the
  change is the intended one, then re-run `just test-visual` green.

### Gate

Run `just check` (after `just install`) and `just test-visual`. Keep the ace help popup, footer, and docstrings in sync
per `src/sase/ace/AGENTS.md`.

## Reliability / edge cases

- Digits must not leak to the app's saved-query loader while the modal is open → covered by swallowing `7`/`8`/`9`/`0`
  and by the explicit "press 7 is a no-op" test.
- Typing digits into a pane filter `Input` must still work → guaranteed by non-priority bindings; add a focused-filter
  regression check if a pane filter test harness makes it cheap.
- Unmounted `ConfigCenterModal` unit instances (no live app) must not crash on write-back → the guarded
  `_remember_active_tab()` helper.
- `#` on a brand-new session lands on Config (tab 1) → default `_admin_center_tab = "config"`.
