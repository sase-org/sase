---
create_time: 2026-06-12 12:38:57
status: done
prompt: sdd/prompts/202606/agents_zoom_keymap.md
---
# Plan: `z` (Zoom) Keymap for the Agents Tab

## Goal

Add a `z` keymap to the Agents tab of `sase ace` that zooms the **largest detail panel** — the agent metadata (prompt)
panel or the file/tools panel, as determined by the current `p` (Toggle Layout) state — into a near-fullscreen popup.
The popup must be unmistakably a "zoom view", carry several useful keymaps (`q` to close among them), stay live for
running agents, and look great.

## Product Context

The Agents tab detail area (`AgentDetail`, `src/sase/ace/tui/widgets/agent_detail.py`) stacks two panels:

- **Metadata panel** (`AgentPromptPanel`, `#agent-prompt-scroll`) — agent header, status, prompt, workflow steps,
  attempt history, replies.
- **File or Tools panel** (`AgentFilePanel` / `AgentToolsPanel`, `#agent-file-scroll` / `#agent-tools-scroll`) — live
  diff/plan/file content, or the tool-call timeline.

The `p` keymap (`action_toggle_layout`, `actions/agents/_panel_detail.py:145`) flips which panel gets priority: default
= metadata 3fr / file-or-tools 7fr; swapped = 7fr / 3fr (tracked by `AgentDetail._layout_swapped`). Even the 7fr panel
is cramped for long diffs, tool timelines, and chat replies. Zoom gives the dominant panel essentially the whole
terminal with one keystroke.

## UX Design

### Trigger & target selection

Pressing `z` on the Agents tab zooms the panel the user is most plausibly reading — the largest one:

| Current detail state                                | Zoom target                                                 |
| --------------------------------------------------- | ----------------------------------------------------------- |
| Default layout (metadata 30 / file-or-tools 70)     | File panel, or Tools panel if tools mode active             |
| Swapped layout (`p` pressed; metadata 70)           | Metadata panel                                              |
| INFO mode / prompt expanded (no file/tools visible) | Metadata panel (it is the only panel)                       |
| Attempt-pinned view (`current_attempt_number` set)  | Metadata panel                                              |
| No agent selected                                   | No popup; `notify("No agent selected", severity="warning")` |

Once inside the popup, `]` / `[` cycle the zoom target across metadata → file → tools (skipping panels with no content),
so the initial pick is a smart default, never a trap.

### The popup

A new `ZoomPanelModal(ModalScreen[None])` — the largest surface in the app (existing max is 95%/95%) so it reads as
"almost the entire screen" while the dimmed app edge underneath still says "popup, `q` gets you back":

```
╔══════════════════════════════════════════════════════════════════╗
║ ⛶ ZOOM — FILE (2/3)                       my-agent.refactor ▶ RUNNING ║  ← header strip
║──────────────────────────────────────────────────────────────────║
║                                                                  ║
║   (full-width panel content, scrollable)                         ║  ← VerticalScroll
║                                                                  ║
║──────────────────────────────────────────────────────────────────║
║ j/k g/G ^D/^U scroll  ]/[ panel  ^N/^P file  E edit  y copy  q close ║  ← hints footer
╚══════════════════════════════════════════════════════════════════╝
```

Visual identity (what makes it _clearly_ the zoom view and beautiful):

- **Size**: `width: 98%; height: 96%` — visibly bigger than every other modal.
- **Border**: `border: thick $accent` — deliberately different from the `$primary` border used by ordinary modals, so
  zoom is recognizable at a glance.
- **Header strip**: one-line `Horizontal` with an accent-tinted background: left side `⛶ ZOOM — METADATA` /
  `⛶ ZOOM — FILE (i/n)` / `⛶ ZOOM — TOOLS` (bold), right side the agent name and live status badge. Panel names match
  the existing cycle terminology ("file → tools → metadata" from the `]`/`[` help text).
- **Subtitle**: the container's `border_subtitle` mirrors the base panel's contextual info (file path and trim counts
  for file zoom), centered like `#agent-prompt-scroll` does today.
- **Hints footer**: muted `Label` following the exact `TaskQueueModal` hints convention.

### Keymaps inside the popup

All bindings are modal-local (`BINDINGS` on the screen), consistent with codebase conventions:

| Key                         | Action                                                                                           |
| --------------------------- | ------------------------------------------------------------------------------------------------ |
| `q`, `escape`, `z`          | Close, return to Agents tab (`z` makes zoom a toggle — same key in, same key out)                |
| `j` / `k` (and `down`/`up`) | Scroll one line                                                                                  |
| `ctrl+d` / `ctrl+u`         | Scroll half page (codebase-wide modal convention)                                                |
| `g` / `G`                   | Scroll to top / bottom (matches `scroll_to_top`/`scroll_to_bottom`)                              |
| `]` / `[`                   | Cycle zoomed panel: metadata → file → tools (matches the base-tab panel-cycle keys)              |
| `ctrl+n` / `ctrl+p`         | Next / previous file (file zoom only; matches `next_agent_file`/`prev_agent_file`)               |
| `=` / `-`                   | Show all file lines / reset trim (file zoom only; matches base-tab keys)                         |
| `E`                         | Open zoomed content in `$EDITOR` (matches `edit_panel`; reuses `get_editor_file_info` semantics) |
| `y`                         | Copy zoomed content to clipboard (`copy_to_system_clipboard`, as in `TaskQueueModal`)            |
| `r`                         | Force-refresh content now                                                                        |

Closing restores the Agents tab exactly as it was — the modal never mutates base-screen layout state.

## Technical Design

### 1. Resolving the `z` key conflict (fold mode)

`z` is currently bound to `start_fold_mode` globally. Fold mode only cycles **ChangeSpec section** folds
(commits/hooks/mentors/timestamps/deltas) — it has no visible effect on the Agents tab. The codebase already scopes
shared keys per tab via `AceApp.check_action()` (app.py:233 — how `s` serves `change_status` on changespecs and
`save_marked_agents` on agents). Apply the same pattern:

- New action `zoom_panel` bound to `z`; `check_action` returns `False` unless `current_tab == "agents"`.
- `check_action` returns `False` for `start_fold_mode` when `current_tab == "agents"`, so Textual falls through to the
  `zoom_panel` binding there. Fold keeps working everywhere else (`z c`, `z z`, …), and remains reachable on the agents
  tab through the command palette (`fold_mode_key` executor), which bypasses bindings.

Keymap plumbing (all four places must stay in sync — enforced by the module-level `_BINDING_META`/`AppKeymaps`
consistency check):

- `keymaps/types.py`: add `("zoom_panel", "Zoom", False)` to `_BINDING_META` and `zoom_panel: str` to `AppKeymaps`.
- `src/sase/default_config.yml`: add `zoom_panel: "z"` in the agents keymap section (per gotchas.md, default_config.yml
  is the source of truth).
- `bindings.py`: add the fallback `Binding("z", "zoom_panel", "Zoom", show=False)`.
- `commands/catalog.py`: add `("zoom_panel", "Zoom largest panel", ..., ("agents",), ())` so the command palette can
  discover/run it.

### 2. The action

`action_zoom_panel` lives in `actions/agents/_panel_detail.py` next to `action_toggle_layout`. It:

1. Guards `current_tab == "agents"` and a selected agent.
2. Reads `AgentDetail` state (`is_info_mode()`, `is_file_visible()`, `is_tools_visible()`, `is_layout_swapped()`,
   attempt pin) to pick the target per the table above.
3. Captures lightweight seed state from the base panels (current renderable for instant first paint, file list + index,
   attempt view mode) and pushes `ZoomPanelModal`.
4. Passes an **agent provider callable** (re-resolves the agent by identity from the app's in-memory agent list) rather
   than a frozen `Agent` object, so refresh ticks see fresh data.

### 3. The modal: host real panel instances, drive its own refresh

Key constraint discovered during exploration: while any modal is on top, `_refresh_agents_display_impl` skips (its
`query_one("#agent-detail-panel")` raises `NoMatches`), so the base panels are frozen underneath. A renderable snapshot
alone would therefore go stale for running agents. Instead:

- The modal **mounts its own instance** of the relevant panel widget class (`AgentPromptPanel` / `AgentFilePanel` /
  `AgentToolsPanel`) inside `VerticalScroll #zoom-panel-scroll`. Zero duplicated rendering logic; the zoom view
  automatically inherits every future panel improvement.
- On mount it seeds the hosted panel with the base panel's current renderable (instant, identical paint — no flash of
  "Loading"), then calls the panel's normal `update_display(agent, ...)`, whose disk/subprocess work already runs
  off-thread via workers.
- A `set_interval(max(app.refresh_interval, 2))` timer re-resolves the agent via the provider and re-invokes
  `update_display`, mirroring the `TaskQueueModal` live-output pattern. Timer stops in `on_unmount`.
- Panel messages (e.g. `AgentFilePanel.FileVisibilityChanged`, normally handled by `AgentDetail`) bubble to the modal
  instead; the modal handles the relevant ones (empty-state display when a file disappears) and stops propagation so
  nothing leaks to app-level handlers.
- Scroll-position helpers that look up containers via `app.query_one("#agent-tools-scroll")` resolve against the top
  screen; inside the modal they fail soft (existing `try/except` returns `None`). The modal owns its scroll state
  directly.

### 4. Styling

New section in `styles.tcss` following existing modal conventions (`align: center middle`, `background: $surface`,
scrollbar-gutter stable), with the accent-border + header-strip treatment described above. Title/hints widgets get
`#zoom-panel-*` ids consistent with the `#task-queue-*` naming pattern.

### 5. Documentation & discoverability (mandated by ace/AGENTS.md)

- **Help modal** (`modals/help_modal/agents_bindings.py`): add `z` ("Zoom largest panel (popup)") under Agent Actions,
  respecting the 57-char box constraints.
- **Footer**: follow the `toggle_layout` (`p`) precedent — not shown in the conditional footer; documented in help
  instead. Verify during implementation that this matches the footer rules.
- Changespecs help section for fold mode needs no change (fold keys unchanged there).

## Files Touched

| File                                                    | Change                                                     |
| ------------------------------------------------------- | ---------------------------------------------------------- |
| `src/sase/ace/tui/modals/zoom_panel_modal.py`           | New `ZoomPanelModal`                                       |
| `src/sase/ace/tui/modals/__init__.py`                   | Export                                                     |
| `src/sase/ace/tui/actions/agents/_panel_detail.py`      | `action_zoom_panel` + target selection                     |
| `src/sase/ace/tui/app.py`                               | `check_action` gating for `zoom_panel` / `start_fold_mode` |
| `src/sase/ace/tui/bindings.py`                          | Fallback binding                                           |
| `src/sase/ace/tui/keymaps/types.py`                     | `_BINDING_META` + `AppKeymaps.zoom_panel`                  |
| `src/sase/default_config.yml`                           | `zoom_panel: "z"`                                          |
| `src/sase/ace/tui/commands/catalog.py`                  | Palette entry (agents tab)                                 |
| `src/sase/ace/tui/modals/help_modal/agents_bindings.py` | Help entry                                                 |
| `src/sase/ace/tui/styles.tcss`                          | Modal styling                                              |
| `tests/...`                                             | See below                                                  |

## Testing

- **Pilot tests** (pattern: `tests/ace/tui/test_agent_tag_modal_pilot.py`):
  - `z` on agents tab opens the modal; `q`, `escape`, and `z` each close it and land back on the agents tab with layout
    state intact.
  - Target selection: default layout → file zoom; after `p` → metadata zoom; tools mode → tools zoom; INFO mode →
    metadata zoom; no agent → warning, no modal.
  - In-modal keys: scrolling (`j/k`, `ctrl+d/u`, `g/G`), `]`/`[` panel cycling, `ctrl+n/p` file cycling, `y` copy.
  - Regression: on the changespecs tab `z` still enters fold mode (`z c` cycles commits fold).
- **Keymap/config tests**: loader consistency (the `_BINDING_META`/`AppKeymaps` import-time check covers omissions),
  `check_action` gating both ways.
- **PNG visual snapshots** (`tests/ace/tui/visual/test_ace_png_snapshots.py`): one snapshot of the file zoom and one of
  the metadata zoom over a populated agents tab — this locks in the "beautiful" requirement.
- `just check` before finishing (after `just install`).

## Performance & Reliability Notes (per `memory/long/tui_perf.md`)

- Opening the modal is pure UI mutation + in-memory renderable seed — no event-loop I/O.
- All content fetching reuses the panels' existing off-thread worker paths; the refresh timer only re-invokes those,
  never reads disk synchronously.
- The modal is fully self-contained: its own widgets, own timer (stopped on unmount), no new app-level refresh code
  paths, no mutation of base-screen state — so closing it cannot leave the agents tab in a weird layout.
- No footer/highlight hot paths are touched; j/k key-to-paint on the base tab is unaffected.

## Edge Cases

- Agent dismissed/finished while zoomed: provider returns the refreshed record (status badge in the header updates) or,
  if gone, the modal keeps the last content and dims the header status.
- Image files in the file panel: zoom shows the file panel's normal rendering for images; the dedicated artifact/tmux
  zoom flow is untouched.
- Huge diffs: the file panel's trim machinery is preserved (`=` / `-` available), so zoom can't freeze the loop on a
  giant render.
- Terminal resize while open: percentage sizing adapts automatically.

## Out of Scope

- Zooming panels on the ChangeSpecs or AXE tabs (the modal is built generically enough to extend later, but `z` stays
  fold mode there).
- Editing content inside the zoom view (read + `E` to editor only).
- User-configurable zoom size.
