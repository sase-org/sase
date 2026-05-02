---
create_time: 2026-04-27 15:45:15
status: done
prompt: sdd/prompts/202604/tui_selection_drift.md
---
# Plan: Fix Random Selection Drift Across All TUI Tabs

## 1. Problem Statement

In the `sase ace` TUI (Textual-based), the **focused/selected entry randomly changes** without user input on all three
list-bearing tabs:

- **ChangeSpecs** tab — selected ChangeSpec jumps to a different row
- **Agents** tab — selected agent / workflow row jumps
- **AXE** tab — selected lumberjack / bgcmd entry jumps (a previous fix, commit `36c9a1d8`, did not solve it)

The drift is most visible during the periodic auto-refresh and after background events (axe daemon push, file watcher).
We want a unified diagnosis and fix that addresses all three tabs.

## 2. Architecture Recap

All three lists are Textual `OptionList` subclasses backed by a single shared app-level cursor `AceApp._current_idx`:

| Tab         | List widget                                     | Underlying data                      | Stable identity                                      |
| ----------- | ----------------------------------------------- | ------------------------------------ | ---------------------------------------------------- |
| ChangeSpecs | `ChangeSpecList` (`widgets/changespec_list.py`) | `self.changespecs: list[ChangeSpec]` | `cs.name`                                            |
| Agents      | `AgentList` (`widgets/agent_list.py`)           | `self._agents: list[Agent]`          | `agent.identity = (type, name, raw_suffix)`          |
| AXE         | `BgCmdList` (`widgets/bgcmd_list.py`)           | `self._axe_items: list[AxeItem]`     | `AxeItemKey` (parent / lumberjack name / bgcmd slot) |

App-level coordination lives in `tui/app.py:126-147` (manual `current_idx` setter that fans out to `watch_current_idx`)
and `tui/app.py:265-275` (per-tab debounced refresh dispatch).

The per-tab refresh pipeline goes through three layers:

1. **Data load** (`_load_changespecs` / `_load_agents` / `_apply_axe_status_data`) — replaces the underlying list and
   _attempts_ identity-based index restoration.
2. **App-state sync** — writes the new `current_idx` (via the manual setter, which fires `watch_current_idx`).
3. **Widget update** (`update_list` / `update_highlight`) — rebuilds the `OptionList` rows and sets
   `self.highlighted = row`.

## 3. Root-Cause Findings

The drift is **not one bug** — it is a cluster of related issues that all violate the same invariant: _"after any list
rebuild, the cursor lands on the same logical entry the user had selected, or on the nearest valid neighbor if that
entry is gone."_ Each tab violates this invariant in slightly different ways.

### 3.1 Identity preservation has gaps in some rebuild paths

The previous AXE fix (`36c9a1d8`) introduced `AxeItemKey` and `find_axe_item_idx`, but only wired them into **one** of
several rebuild paths:

- `_build_axe_items()` in `axe_display/_loaders.py:359` — restoration is _gated on_ `self.current_tab == "axe"`, so when
  called from `_apply_axe_status_data` while the user is on Agents/ChangeSpecs, no key is captured. The widget cursor
  and `_axe_items` may then drift relative to each other.
- `_expand_axe_fold()` / `_collapse_axe_fold()` (`axe_display/_folding.py:400, 417`) — call `_build_axe_items` directly.
  Because the identity capture happens _inside_ `_build_axe_items` based on the pre-rebuild list, these paths _do_
  benefit, but only on the AXE tab.
- The "hide bgcmd" toggle (`axe_display/_core.py:146`) — same caveat.

The AgentsList has `_load_agents` identity capture (`agents/_loading.py:132-134, 192-195`) and a "neighbor fallback" via
`_restore_focus_after_removal` (`agents/_loading_finalize.py:183-190`), but the capture only happens _if_
`on_agents_tab=True`. Cross-tab refreshes don't snapshot identity, so when the user returns to Agents the saved
`_agents_last_idx` may now point at a different agent.

The ChangeSpecList has identity preservation but **no nearest-neighbor fallback**: when the previously selected
ChangeSpec is filtered out (e.g. it was Submitted and `hide_submitted=True`), `_apply_reloaded_changespecs` falls back
to `new_idx = 0` (`changespec/_loading.py:183`). This is the single most user-visible drift on the ChangeSpecs tab — a
CL submission causes the cursor to jump to the top of the list.

### 3.2 Inconsistent message-suppression in widgets

Each widget guards rebuilds with `_programmatic_update`, but the three implementations differ:

| Widget           | `watch_highlighted` override?         | Flag clear strategy                    |
| ---------------- | ------------------------------------- | -------------------------------------- |
| `ChangeSpecList` | ✅ Yes (`changespec_list.py:422-426`) | `call_later(_clear_programmatic_flag)` |
| `BgCmdList`      | ✅ Yes (`bgcmd_list.py:279-283`)      | Synchronous `try/finally`              |
| `AgentList`      | ❌ **No**                             | `call_later(_clear_programmatic_flag)` |

`OptionList`'s parent `watch_highlighted` posts an `OptionHighlighted` message every time `self.highlighted` is
assigned. Two widgets override that watch to swallow the message during programmatic updates; **AgentList does not**.
AgentList instead checks `_programmatic_update` _inside_ the message handler — but because the flag is cleared via
`call_later`, there is a real possibility that the deferred clear fires _before_ the queued `OptionHighlighted` message
is processed (the call_later callback and the message pump are different schedulers in Textual). When that happens, the
message handler sees `_programmatic_update == False`, calls `post_message(SelectionChanged(event.option_index))`, and
the app's `on_agent_list_selection_changed` handler overwrites `self.current_idx` — typically with the auto-highlighted
row 0 from the just-completed `clear_options() + add_option(...)`.

This is a strong candidate for the "selection randomly jumps to row 0 on Agents tab" symptom.

### 3.3 Multiple non-unified rebuild triggers

For each tab, more than one code path can rebuild the list:

- **ChangeSpecs**: periodic timer, file watcher (`_on_artifact_change`), tag/status events.
- **Agents**: periodic timer, file watcher, fold/group changes, dismiss/kill actions, query edits.
- **AXE**: periodic timer, axe daemon push (`_apply_axe_status_data`), fold toggles, hide toggles.

Identity capture/restore is attached to _some_ of these paths but not all, and is implemented redundantly (duplicated
logic in `_loading.py`, `_loaders.py`, `_finalize.py`). Each path has its own subtle drift mode.

### 3.4 Ordering instability amplifies any gap

`agent_loader` sorts agents by `start_time` descending, so newly arriving agents bubble to the top. Lumberjack and bgcmd
lists can reorder when slots/services come and go. Even a _brief_ gap in identity restoration (e.g. one rebuild path
that doesn't preserve identity) shows up as drift because the underlying list keeps reshuffling.

### 3.5 Splitting selection between app state and widget state

The app holds `current_idx` (data row) while each widget holds `OptionList.highlighted` (visual row, which may include
banners and spacers in `AgentList`). They are kept in sync only at refresh time. Whenever a widget rebuild
auto-highlights row 0 _before_ the app's restoration pass writes the correct index, and the OptionHighlighted message is
not properly suppressed (see §3.2), the widget's transient state **wins** and overwrites the app's cursor.

## 4. Solution: Unified "Selection Identity" Model

### Design principles

1. **Single source of truth for identity per tab.** Each tab has a stable identity type — `cs.name` (ChangeSpec),
   `agent.identity` tuple (Agent), `AxeItemKey` (AXE). Already exists.
2. **Always capture identity _before_ mutating the list.** Every rebuild path must snapshot the identity, not the index.
3. **Always restore by identity _after_ mutating the list, with a deterministic neighbor-based fallback.** When the item
   disappears, land on the same visible row position (clamped), not on row 0.
4. **App owns `current_idx`. Widgets own `highlighted`. Updates always flow app → widget, never widget → app during a
   programmatic update.** This eliminates the "widget event overwrites app state" feedback loop.
5. **Suppress widget→app feedback synchronously and uniformly.** All three list widgets must override
   `watch_highlighted` and gate it on a synchronous `_programmatic_update` flag — no `call_later`-deferred clearing.

### 4.1 Selection-preservation helper (shared)

Introduce a small reusable helper module `tui/util/selection.py` exposing one entry point per tab — or a single generic
one parameterized by an `identity_fn`:

```python
def restore_selection_by_identity(
    new_items: Sequence[T],
    *,
    prior_identity: K | None,
    prior_visual_row: int | None,
    identity_fn: Callable[[T], K],
) -> int:
    """Return the row index to focus in `new_items`.

    1. If `prior_identity` is found in `new_items`, return its index.
    2. Else if `prior_visual_row` is in range, clamp to it (nearest-neighbor).
    3. Else return 0 (or len-1 if nonempty), as a final fallback.
    """
```

Call sites: every rebuild path on every tab. This deletes ~3 inline copies of similar logic.

### 4.2 Per-tab rebuild-path audit

For each tab, document **every** rebuild trigger and ensure it routes through `restore_selection_by_identity` before
writing `current_idx`:

- **ChangeSpecs**: `_apply_reloaded_changespecs`, plus any direct mutation paths.
- **Agents**: `_apply_loaded_agents_prepared`, plus fold-state changes, dismiss/kill (already partially covered by
  `_restore_focus_after_removal`), query edits, grouping mode changes.
- **AXE**: `_build_axe_items` (collapse the gating: capture identity _before_ the rebuild regardless of `current_tab`,
  and restore unconditionally — when off-tab, write to the persisted `_axe_last_item_key` only).

### 4.3 Widget message-suppression hardening

For all three widgets:

1. **Add `watch_highlighted` override** on `AgentList` matching the pattern in `ChangeSpecList` / `BgCmdList`. This is
   the smallest, most surgical fix and is independently shippable.
2. **Switch to synchronous `try/finally` flag management** in all three widgets. Replace
   `self.call_later(self._clear_programmatic_flag)` with a `try/finally` block around the highlight assignment. This
   eliminates the call_later-vs-message-pump race entirely.
3. **Audit auto-highlight on rebuild.** Examine OptionList behavior on `clear_options()` followed by `add_option(...)`:
   if Textual auto-highlights the first option, ensure the auto-highlight is either suppressed (via `watch_highlighted`)
   or immediately overwritten by the explicit `self.highlighted = row` assignment _before_ the message pump runs.

### 4.4 Cross-tab safety

When a rebuild trigger fires on a tab the user is _not_ viewing (e.g. axe daemon push while on ChangeSpecs):

- Identity capture must use the tab-specific saved key (`_axe_last_item_key`, `_agents_last_identity`,
  `_changespecs_last_name`), not `current_idx`.
- The rebuild must update the saved-key _and_ the saved-index for that tab, so that returning to the tab via
  `action_next_tab` lands on the right row.
- `current_idx` (which is shared and currently owned by whatever tab is active) must not be mutated for off-tab
  rebuilds.

This requires introducing `_changespecs_last_name` and `_agents_last_identity` (the AXE tab already has
`_axe_last_item_key` from commit `36c9a1d8`). These mirror the existing `_agents_last_idx` / `_axe_last_idx` pattern.

## 5. Implementation Plan

### Phase 1 — Diagnostic instrumentation (one commit)

Add structured trace logging (gated on `SASE_TUI_TRACE`) at every selection-mutation point: the manual `current_idx`
setter, all three widgets' `watch_highlighted`, and `on_option_list_option_highlighted`. Each log line names the path
and includes old/new index plus the identity key. This will let us _prove_ (not guess) which path is dropping selection
in any future regression.

### Phase 2 — Widget-layer fix (one commit, smallest blast radius)

Apply §4.3 to all three widgets:

- `AgentList`: add `watch_highlighted` override.
- All three: switch `_programmatic_update` flag clearing from `call_later` to synchronous `try/finally`.

This alone is expected to eliminate the "Agents tab cursor jumps to row 0 on auto-refresh" symptom (the single most
common drift mode).

### Phase 3 — Shared selection helper (one commit)

Introduce `tui/util/selection.py::restore_selection_by_identity` per §4.1. Pure-data, easy to unit-test.

### Phase 4 — Wire helper into all rebuild paths (one commit per tab)

For each tab, route every rebuild path through the helper. Add the missing per-tab "last identity" attributes (§4.4).
Remove the gating on `current_tab == "axe"` in `_build_axe_items` so identity is preserved regardless of which tab the
user is on.

### Phase 5 — Regression coverage (folded into each commit)

Tests to add:

- **Unit**: `restore_selection_by_identity` with present identity, missing identity, empty list, identity at row 0/end.
- **Integration** (per tab): start with selection on row N, fire a refresh that reorders / inserts / removes, assert the
  visible cursor stays on the same logical entry. The existing `tests/ace/tui/test_axe_selection_identity.py` is the
  template — replicate for ChangeSpecs and Agents.
- **Cross-tab**: start on Agents tab with row 5 selected, fire an `_apply_axe_status_data` that reorders AXE items,
  switch to AXE tab, assert previously-selected lumberjack is still focused.
- **Widget**: programmatic `update_list` followed by no user input must not produce a `SelectionChanged` message (verify
  via Textual's pilot harness).

## 6. Risks & Tradeoffs

- **Synchronous flag clearing** may reorder Textual internal events. The original `call_later` choice was likely
  defensive; we need to verify that no message that _should_ fire (genuine user-driven OptionHighlighted) gets
  swallowed. The integration tests above cover this.
- **Cross-tab last-identity attributes** add three new fields to `AceApp` state. They must be persisted across tab
  switches but not across app restarts — i.e. live in memory only. This matches the existing `_axe_last_item_key`.
- **Removing the `current_tab == "axe"` gate** in `_build_axe_items` means identity capture runs on every call. This is
  cheap (one tuple comparison per item) but worth measuring for tabs with hundreds of bgcmds.
- **Scope discipline.** The temptation will be to refactor selection state into a per-tab class. _Do not._ The existing
  shared `current_idx` works; the bug is in the rebuild paths, not the architecture. Keep the diff focused.

## 7. Out of Scope

- Replacing `OptionList` with a different widget.
- Persisting selection across TUI restarts.
- Refactoring per-tab state into separate dataclasses.
- Performance work beyond what §4.4 requires.

## 8. Acceptance Criteria

- Sitting idle on any tab for the full auto-refresh interval does not move the visible cursor (assuming the selected
  entry still exists).
- When the selected entry is filtered/dismissed/archived, the cursor lands on the _same visible row position_ in the new
  list, not on row 0.
- Background rebuilds (axe daemon push, file watcher) on a tab the user is not viewing leave the user's saved cursor on
  that tab unchanged, verified by tab-switching back.
- All three tabs' integration tests pass.
- No new `SelectionChanged` messages are emitted during programmatic widget updates.
