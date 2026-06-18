---
create_time: 2026-06-18 09:05:09
status: done
prompt: sdd/prompts/202606/prompt_stash_bundles_1.md
---
# Prompt Stash Bundles Plan

## Context

The prompt input bar currently emits one `StashedPromptPane` per non-empty pane for `gS` / `Ctrl+G S`, and the app
persists each pane as an independent `PromptStashEntryWire`. Restore then selects and pops individual stash entry ids.
That preserves rough order through `(created_at, pane_index)`, but it breaks the user's mental model that the visible
prompt panes and the shared xprompt/frontmatter properties are one connected draft.

The existing stash store is a Rust-backed JSONL pile of `PromptStashEntryWire` rows. A row already has `text`,
`frontmatter`, `source`, `project`, and `pane_index`. The prompt stack already has a canonical representation for a
connected multi-prompt draft: shared frontmatter plus prompt bodies joined with `\n---\n`.

## Goal

Make `gS` / `Ctrl+G S` stash all visible non-empty prompt panes and their current shared xprompt properties as one stash
unit.

- The stash badge/count should increase by exactly one for one `gS` / `Ctrl+G S` action.
- `gp`, `gP`, `Ctrl+G p`, and `Ctrl+G P` should restore/load the whole unit at once.
- The stash selection modal should allow multi-select bulk restore only for rows that represent a single prompt. Bundle
  rows can still be restored by highlighting the row and pressing enter, and can be deleted as a unit.
- Existing stash rows should keep working. Already-separated old `gS` stashes cannot be retroactively reconnected, but
  they should remain restorable.

## Design

Use the existing wire shape instead of introducing a new Rust schema:

- Persist every new stash event as one `PromptStashEntryWire`.
- For `gs`, keep the same one-row behavior.
- For `gS`, create one row whose `text` is the canonical multi-prompt body produced from all captured pane texts
  (`pane0\n---\npane1...`) and whose `frontmatter` is the shared prompt-stack frontmatter from the xprompt property
  panel.
- Keep `source="all"` for `gS` bundles so UI copy can identify bundle rows; keep `source="current"` for `gs`.
- Use the existing Rust append/pop/read APIs unchanged. This avoids a `sase-core` wire migration and keeps older rows
  readable.

Add Python helpers near the stash TUI boundary:

- `entry_prompt_segments(entry)`: returns the effective prompt bodies for a stash row using the same protected
  multi-prompt splitter as `PromptStackState.from_text`. Single legacy rows return one body.
- `entry_is_bundle(entry)`: true when the effective segment count is greater than one.
- `entries_to_restore_items(entries)`: expands selected stash rows into `(text, frontmatter)` pane tuples, preserving
  entry order and then segment order inside each bundle.

## Implementation Steps

1. Update stash persistence in `PromptBarStashMixin._persist_stashed_panes` so it appends one row per `Stashed` event,
   not one row per pane. For multiple panes, join texts with the canonical separator and store the shared frontmatter
   once.

2. Adjust the stash notification and badge expectations. The badge naturally counts rows, so new `gS` captures add one.
   The toast can say either `Stashed prompt bundle` or `Stashed N prompts as a bundle` while still reflecting that the
   persisted stash unit is one row.

3. Update restore/load expansion:
   - Destructive restore pops selected row ids, then expands each removed row into pane tuples.
   - Non-destructive load reads selected rows from the snapshot, then expands the rows the same way.
   - Mounted prompt bars receive one pane per expanded segment and adopt the first non-empty frontmatter as today.
   - No-mounted-bar restore builds the same canonical combined text from expanded items.

4. Update `StashedPromptsModal` selection behavior:
   - `space` toggles only highlighted rows with exactly one effective prompt segment.
   - `a` toggles only selectable single-prompt rows.
   - `enter` with no selected rows restores the highlighted row, including bundle rows.
   - Delete marking remains row-based and can delete a bundle as a unit.
   - Row labels should make bundle rows recognizable, for example by showing a compact `N prompts` marker while keeping
     previews single-line and stable.

5. Update tests:
   - Widget capture tests should still assert that `PromptInputBar.Stashed` emits all captured panes; this remains the
     presentation contract.
   - Handler tests should assert that `gS` persistence writes one stash row with joined body/frontmatter/project/source,
     distinct id, and badge count increment of one.
   - Restore handler tests should cover destructive and non-destructive bundle restore into mounted and unmounted bars.
   - Modal tests should cover bundle row ordering, `space` being inert for bundle rows, `a` selecting only single rows,
     enter-on-highlight restoring a bundle, and delete marking a bundle row.
   - Core facade tests need only minor expectation updates if any; no Rust store behavior should change.

6. Verification:
   - Run the focused stash test set first:
     `pytest tests/ace/tui/widgets/test_prompt_stash_capture.py tests/ace/tui/actions/test_prompt_stash_handler.py tests/ace/tui/actions/test_prompt_stash_restore.py tests/ace/tui/modals/test_stashed_prompts_modal.py tests/test_core_facade/test_prompt_stash.py`
   - Run formatting/lint-relevant tests if touched files require it.
   - Because this repo requires it after file changes, run `just install` if needed and then `just check` before the
     final response.

## Risks And Notes

- Already-stashed old `gS` rows were written independently and cannot be safely regrouped without extra historical
  metadata. The fix applies to new `gS` / `Ctrl+G S` captures.
- The plan intentionally avoids a `sase-core` schema change. If we later need exact original pane metadata beyond the
  canonical multi-prompt representation, the follow-up would be an additive Rust/Python wire field such as explicit
  `panes`, but that is heavier and risks old bindings silently dropping new fields.
- Restore/load disk reads already run off-thread. The persistence path currently performs a Rust append synchronously;
  this change reduces `gS` from N appends to one append. I will avoid adding any extra synchronous disk work on TUI key
  paths.
