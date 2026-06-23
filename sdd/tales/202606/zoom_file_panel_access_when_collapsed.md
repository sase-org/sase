---
create_time: 2026-06-23 08:27:28
status: done
prompt: sdd/prompts/202606/zoom_file_panel_access_when_collapsed.md
---
# Fix: ACE Agents-tab zoom modal can't reach the file panel when it opens on metadata

## Problem

On the **Agents** tab of the `sase ace` TUI, pressing `z` (zoom) opens the near‑fullscreen detail zoom modal. The modal
opens focused on whichever base detail panel was "dominant". When the **file panel is collapsed / not visible** at `z`
time (the base detail panel is in INFO mode, layout‑swapped, in TOOLS mode, or in AUTO mode with no file shown), the
modal correctly opens focused on the **metadata** panel — but the **file panel can never be reached or loaded** inside
the modal. The file content is never displayed and the `<ctrl+n>` / `<ctrl+p>` file keymaps do nothing.

Desired behavior:

- When `z` is pressed while the file panel is collapsed/not visible, the **metadata** panel is focused (this already
  happens and should stay).
- The **file panel should still be accessible from inside the modal via `<ctrl+n>` / `<ctrl+p>`**: pressing them should
  reveal/switch to the file panel and load the agent's file content, then continue to page between files as usual.

## Root cause (confirmed by reading the code)

The zoom modal (`src/sase/ace/tui/modals/zoom_panel_modal.py`) tracks one active "target" panel
(`ZoomPanelTarget.METADATA | FILE | TOOLS`). The initial target is chosen in
`AgentPanelDetailMixin._zoom_target_for_detail()` (`src/sase/ace/tui/actions/agents/_panel_detail.py`): for a collapsed
file panel it returns `METADATA` (via the info / layout‑swapped / final‑fallback branches). That part is already
correct.

Two things then block file access while the target is `METADATA` (or `TOOLS`):

1. **`<ctrl+n>` / `<ctrl+p>` are inert unless the target is already `FILE`.** Both handlers hard‑gate on the active
   target:

   ```python
   def action_next_file(self) -> None:
       if self._target != ZoomPanelTarget.FILE:
           return
       self.query_one("#zoom-file-panel", _ZoomFilePanel).next_file()
       self._update_header()
   ```

   So on the metadata panel the file keymaps silently no‑op — there is no path to switch to the file panel.

2. **The `FILE` target may not even be reachable, and its content is never loaded.** `_available_targets()` includes
   `FILE` only when `self._has_file_content` is true. That flag is seeded from the base panel's visibility
   (`_zoom_seed_from_detail()` → `has_file_content = is_file_visible() or agent_detail._has_file_content`). For a panel
   that was collapsed and never reported file content (e.g. INFO mode entered before any diff loaded), the seed flag is
   `False`, so `FILE` is excluded from the panel cycle and `_show_target(FILE)` would fall back to metadata. Separately,
   the modal's periodic/initial refresh (`_refresh_active_panel`) only refreshes the _active_ target, so the file
   panel's content is never loaded while metadata is active.

Net effect: when zoom opens on metadata for a collapsed file panel, the file panel is unreachable and unloaded, exactly
as reported.

(Note: in some "collapsed" cases — e.g. TOOLS mode, or INFO mode entered _after_ a diff had already been shown — the
base `_has_file_content` is already `True`, so `FILE` is in the cycle and `]`/`[` can reach it; but
`<ctrl+n>`/`<ctrl+p>` are still inert because of cause #1. The fix must cover both.)

## Architecture boundary note

This is purely Textual presentation glue inside the zoom modal (active‑target selection, reveal, and file‑panel
loading). It does **not** cross the Rust core backend boundary — no `sase-core` wire/API/binding changes are needed.

## Fix

All changes are in `src/sase/ace/tui/modals/zoom_panel_modal.py`. The idea: make the file keymaps _reveal_ the file
panel on demand (loading its content) whenever the agent actually has files, instead of being inert off‑target.

### Part 1 — `<ctrl+n>` / `<ctrl+p>` reveal and switch to the file panel

Rework `action_next_file()` / `action_prev_file()` so they behave as follows:

- **If the active target is already `FILE`** → page files exactly as today (`next_file()` / `prev_file()` + header
  update). No behavior change.
- **If the active target is not `FILE`** (metadata or tools) → attempt to _reveal_ the file panel:
  - If the agent has files (see Part 2), set the modal's `_has_file_content = True` (so `FILE` enters
    `_available_targets()`), switch the active target with `_show_target(FILE)`, and load the current file via the
    existing non‑forced refresh path (`_refresh_active_panel(force=False)` → `_refresh_file`). This reuses the exact
    load path that `]`/`[` cycling already uses (`set_file_list(...)` for completed agents, `update_display(...)` for
    active agents), including the existing deferred‑trim handling for a just‑unhidden panel.
  - If the agent has no files → leave the target on metadata and `notify("No files for this agent", severity="warning")`
    so the no‑op is discoverable.

**Reveal semantics (decision):** the first reveal press _opens_ the file panel on its current/seeded file index and does
**not** advance; subsequent presses (now on the `FILE` target) page normally. This is the most intuitive behavior since
the file content hasn't been shown yet — "show me the files" rather than "skip the first one". (Alternative considered:
reveal _and_ advance/retreat by one on the first press. Rejected as more surprising, and a no‑op for single‑file
agents.)

### Part 2 — Determine whether the agent has files (reachability)

Add a small helper, `_agent_has_files(agent) -> bool`, used by the reveal path:

- Return `False` when an attempt is pinned (`self._seed.attempt_number is not None`) — the file target is intentionally
  force‑hidden in that mode by the existing `_refresh_file` guard, so reveal must be blocked to avoid a flicker.
- Return `True` when `self._has_file_content` is already true (file content known to exist).
- Return `True` when `agent.all_files` is non‑empty (authoritative for completed/non‑active agents: diff path + extra
  files).
- Return `True` when the agent is in an active status (`_ACTIVE_STATUSES`): such agents may have a live diff not yet
  reflected in `all_files`; the load attempt is allowed to proceed and the panel's existing
  `FileVisibilityChanged(has_file=False)` message self‑corrects back to metadata if the live diff turns out empty.
- Otherwise `False`.

This keeps the reveal correct for completed agents (no false positives), while letting active agents optimistically open
the live diff.

### Why this is safe / minimal

- `_available_targets()` is **not** changed directly; `FILE` is added to the cycle only as a side effect of the reveal
  flipping `_has_file_content`. So `]`/`[` panel cycling and the header `(position/total)` counter are unchanged until
  the user actually reveals the file panel, after which `FILE` joins the cycle consistently.
- The initial focus is **unchanged**: `_zoom_target_for_detail()` is untouched, so `z` on a collapsed file panel still
  opens on metadata.
- Reveal reuses the existing load path (`_refresh_file`), so seeded `_file_list` / index, deferred trim sizing for a
  newly‑unhidden panel, active‑vs‑completed dispatch, and the `FileVisibilityChanged` self‑correction all keep working.
- The pinned‑attempt mode is explicitly excluded, matching the existing `_refresh_file` behavior that hides the file
  target in that mode.

## Files to change

- `src/sase/ace/tui/modals/zoom_panel_modal.py` — rework `action_next_file()` / `action_prev_file()` to reveal the file
  panel when off‑target; add `_agent_has_files()` and a small `_reveal_file_panel()` helper.

No keymap, footer, or `?` help‑popup changes: the `<ctrl+n>`/`<ctrl+p>` bindings already exist (default config:
`next_agent_file`/`prev_agent_file`), and the zoom modal's own in‑modal hint label already reads `^N/^P file`, which
still describes the (now strictly more capable) behavior.

## Tests

Add to `tests/ace/tui/test_agents_zoom_panel.py` (and keep existing tests green):

1. **`<ctrl+n>` reveals the file panel from metadata (collapsed‑file regression).** A completed (DONE) agent with
   on‑disk `extra_files`. Open `ZoomPanelModal` with `initial_target=METADATA` and a seed that simulates the collapsed
   case (`has_file_content=False`, empty `file_list`). Assert the modal starts on `METADATA` and `FILE` is _not_ in
   `_available_targets()`. Press `ctrl+n`; assert the target becomes `FILE`, `FILE` is now available, and the file body
   renders (no `r`/force refresh).

2. **`<ctrl+p>` also reveals the file panel from metadata.** Same setup; press `ctrl+p` and assert the target becomes
   `FILE` and content loads.

3. **Reveal then page.** Completed agent with two `extra_files`, seed `METADATA` + `has_file_content=False`. Press
   `ctrl+n` (reveals file index 0, does not advance — assert `current_file_index == 0` and first file body shown). Press
   `ctrl+n` again and assert it advances to index 1 with the second file body.

4. **No‑files agent is a discoverable no‑op.** A completed agent with no diff path and no extra files
   (`all_files == []`). Open on `METADATA` with `has_file_content=False`. Press `ctrl+n`; assert the target stays
   `METADATA` and the file scroll stays hidden (and a "No files" warning is emitted — capture via a recorded `notify`).

5. Confirm the existing `test_agents_zoom_panel.py` tests still pass, including
   `test_action_zoom_panel_selects_expected_initial_target` (initial focus unchanged) and the existing `<ctrl+n>` paging
   / show‑all‑survives‑refresh tests.

Also run the ACE PNG visual snapshot suite for the file zoom modal
(`tests/ace/tui/visual/snapshots/png/agents_file_zoom_modal_120x40.png`): this change does not alter the on‑open render
of an agent that opens on the file target, so no golden update is expected.

## Validation

- `just install` then `just check` (lint + mypy + tests).
- `just test-visual` for the zoom snapshot suite; expect no golden change.
- Manual smoke in `sase ace`: select a completed agent, collapse the file panel (INFO mode / layout swap / tools), press
  `z` → modal opens on metadata; press `<ctrl+n>` → file panel appears with content (no `r`); `<ctrl+n>`/`<ctrl+p>` page
  files; `]`/`[` now also reach the file panel; on an agent with no files, `<ctrl+n>` stays on metadata and warns.

## Out of scope / notes

- The base (non‑zoom) Agents‑tab `<ctrl+n>`/`<ctrl+p>` behavior (`action_next_agent_file` / `action_prev_agent_file`) is
  unchanged — this fix is confined to the zoom modal.
- No change to initial zoom‑target selection; `z` still focuses metadata when the file panel is collapsed.
- No `sase-core` changes (presentation‑only).
