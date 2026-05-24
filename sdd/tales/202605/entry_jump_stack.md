---
create_time: 2026-05-24 09:45:58
status: done
prompt: sdd/prompts/202605/entry_jump_stack.md
---
# Make double-apostrophe entry jumps stack-based

## Context

The `sase ace` entry-jump binding uses apostrophe in two stages:

- `'` enters one-key jump mode and paints per-row hints.
- Pressing apostrophe again while in jump mode (`''`) either jumps to the first visible target when there is no history,
  or returns to the single saved previous point when history exists.
- `ctrl+o` uses the same logic without painting hints by preparing the jump maps and dispatching the internal apostrophe
  handler.

Today the app keeps only one previous point:

- non-Agents tabs store one index per tab in `_entry_jump_last_index`;
- the Agents tab stores one richer `_entry_jump_last_agents_anchor`, because an Agents cursor can be an agent row or a
  collapsed banner in a tag panel.

That makes `''` a toggle. If a user jumps A -> B -> C, the next `''` returns to B but also overwrites the previous point
with C, so a second `''` goes forward to C instead of continuing back to A. The desired behavior is a stack: each real
jump pushes the origin; each `''` pops the most recent valid origin; repeated `''` walks backward through jump origins.

This is TUI navigation state, so it belongs in this repo. No Rust core or default keymap changes are needed.

## Proposed Semantics

1. Keep jump history session-local and tab-scoped.

   Each tab should maintain its own stack so Changespecs, Agents, and AXE jumps do not interfere with each other. The
   Agents tab still needs anchor values that include panel and banner state; non-Agents tabs can continue to use current
   row indexes unless a narrower grouped-Changespec anchor bug is intentionally addressed during implementation.

2. Push only origins for actual focus changes.

   A hinted jump, no-history `''` first-target fallback, sibling jump, panel jump, unread-done jump, or stopped-agent
   jump should push the point the user left when the destination is different. Avoid pushing duplicate top entries where
   possible so repeated no-op jumps do not create dead stack entries.

3. Make `''` pop instead of toggle.

   When stack history exists, `''` should restore the latest valid point and remove it from the stack. It should not
   save the current point while going back. This is the key behavior change from toggle history to stack history.

4. Treat stale history defensively.

   Agent lists, panels, grouped banners, CL lists, and AXE rows can change after a history entry is pushed. On `''`,
   discard stale top entries until a valid entry is found. If none remains, fall through to the existing first-target
   behavior (`key = "1"`).

5. Preserve existing fast-jump and footer behavior.

   `ctrl+o` should use the same stack pop / first-target path as `''`, still without painting hints or updating the jump
   footer. The footer can continue to show `' back` when the current tab has any stack history, and `' first` otherwise.

## Implementation Plan

1. Replace single previous-point app state with stacks.

   In `src/sase/ace/tui/actions/_state_init.py` and `src/sase/ace/tui/actions/navigation/_types.py`, replace the
   app-level `_entry_jump_last_index` / `_entry_jump_last_agents_anchor` state with:
   - a per-tab index stack for non-Agents entry jumps;
   - an Agents anchor stack for agent-row and banner anchors.

   Keep the state private to the TUI app. Modal-local jump histories can be left unchanged unless the implementation
   reveals that the user-facing behavior should be aligned there too; those are separate picker/modal interactions
   rather than the app-level double-apostrophe key path.

2. Add small helper methods in `EntryJumpNavigationMixin`.

   Centralize stack operations so all callers use the same rules:
   - read the current tab's stack;
   - push the current non-Agents index when a jump will move to a different index;
   - push the current Agents anchor through the existing `_current_agents_jump_anchor()`;
   - pop the next valid non-Agents index;
   - pop the next valid Agents anchor, validating agent indexes and panel indexes before restoring;
   - discard stale entries while popping.

   The existing `_save_agents_jump_anchor()` method should become a stack push helper so sibling, panel, unread, and
   stopped-agent navigation continue to seed `''` history through their current decoupled
   `getattr(..., "_save_agents_jump_anchor", None)` pattern.

3. Update entry-jump dispatch.

   In `src/sase/ace/tui/actions/navigation/_entry_jump.py`:
   - change the apostrophe branch to pop from the relevant stack;
   - remove the old "save current before jumping back" toggle behavior;
   - push origins before hinted jumps and no-history first-target jumps only when movement will change focus;
   - keep invalid-key cancellation and hint-map cleanup unchanged;
   - keep `action_jump_to_entry_fast()` delegating through `_handle_entry_jump_key("apostrophe")`.

4. Update UI copy and help documentation.

   The key binding itself does not change, but help text should stop implying a single previous point. Update the `?`
   help modal descriptions for Changespecs, Agents, and AXE to mention stack/back-stack behavior while staying within
   the existing help box width rules. The transient footer labels can remain `first` / `back` unless a clearer short
   label fits cleanly.

5. Update tests around history semantics.

   Adjust harness initialization and assertions from single previous-point fields to stack fields. Add focused coverage
   for:
   - non-Agents `''` with no history still jumps to the first visible target and pushes the origin;
   - non-Agents `''` with multiple stack entries pops them in LIFO order;
   - `ctrl+o` follows the same stack behavior without footer updates;
   - stale non-Agents entries are discarded before fallback or valid restore;
   - Agents sibling/panel/unread/stopped jumps push origins onto the Agents stack;
   - Agents `''` pops through multiple row/banner anchors instead of toggling;
   - stale Agents anchors are discarded without blocking fallback to hint `1`.

6. Verify narrowly, then run the repo check.

   Start with targeted tests:

   ```bash
   pytest tests/ace/tui/test_jump_to_entry_hints.py tests/ace/tui/test_jump_hints_for_folded_banners.py tests/ace/tui/test_agent_sibling_navigation.py tests/ace/tui/test_agent_unread_done_navigation.py tests/ace/tui/test_agent_stopped_navigation.py tests/ace/tui/test_agent_panel_first_selection.py
   ```

   Because this repo requires it after source changes, run `just install` if needed and then `just check` before
   finalizing.

## Non-Goals

- No keymap/default-config changes.
- No persisted jump history.
- No cross-tab stack for the grave-accent all-entry jump modal.
- No Rust core changes.
- No memory-file changes.
