---
create_time: 2026-04-27 10:33:46
status: done
prompt: sdd/prompts/202604/fix_jk_navigation_reliability.md
---
# Plan: Fix unreliable `j`/`k` navigation

## Problem

`j`/`k` navigation has been optimized into a cheap fast path: mutate `current_idx`, move the left-list highlight
immediately, and debounce expensive detail-panel work. That design is sound, but it is currently applied unevenly.

The ChangeSpecs tab fast path updates `ChangeSpecList.highlighted` directly in
`_refresh_changespecs_display_debounced()`. Unlike the full list rebuild path, it does not set the list widget's
`_programmatic_update` guard. Textual `OptionList` highlight changes can emit `OptionHighlighted`, and
`ChangeSpecList.on_option_list_option_highlighted()` turns those into app-level `SelectionChanged` messages whenever
`_programmatic_update` is false.

That means rapid `j`/`k` can queue stale selection events:

1. `j` sets app `current_idx` from 0 to 1 and sets widget highlight to 1.
2. Before Textual processes the resulting widget message, another `j` sets app `current_idx` to 2 and widget highlight
   to 2.
3. The old widget message for index 1 can still reach `on_change_spec_list_selection_changed()`, which sees
   `event.index != current_idx` and writes `current_idx` back to 1.

The result matches the user's report: navigation feels buggy or unreliable, especially during quick key bursts. Agents
and Axe already have explicit highlight-update helpers that suppress programmatic `OptionList` messages, so this is a
cross-tab consistency bug centered on ChangeSpecs.

## Scope

- Keep keymap semantics unchanged: `j` is next, `k` is previous.
- Keep the current performance architecture: immediate cursor/highlight update plus debounced detail refresh.
- Do not change grouping, jump mode, history navigation, or mouse selection behavior except to suppress synthetic
  programmatic highlight events.

## Implementation

1. Add a programmatic fast-highlight API to `ChangeSpecList`.
   - Mirror `BgCmdList.update_highlight()` and `AgentList.update_highlight()`.
   - Set `_programmatic_update = True`, assign `highlighted`, then clear the guard with `call_later()`.
   - Clamp to valid indices and no-op for empty lists.

2. Route ChangeSpecs `j`/`k` through that API.
   - Replace the direct `list_widget.highlighted = self.current_idx` assignment in
     `_refresh_changespecs_display_debounced()` with `list_widget.update_highlight(self.current_idx)`.
   - Preserve the immediate info-panel update and debounced detail refresh.

3. Add focused regression coverage.
   - Unit-test that `ChangeSpecList.update_highlight()` suppresses `SelectionChanged` messages for programmatic moves.
   - Test the app/mixin fast path with a fake `ChangeSpecList` to prove `j`/`k` uses the guarded API instead of writing
     `highlighted` directly.
   - Keep existing real mouse/keyboard highlight behavior intact: user-driven `OptionHighlighted` should still post
     `SelectionChanged` when `_programmatic_update` is false.

4. Re-run relevant tests.
   - First run the targeted TUI/keymap tests after installing this workspace if needed.
   - Then run the repo-required `just check` because this is a code change in the sase repo.

## Expected result

Rapid `j`/`k` on ChangeSpecs no longer queues stale synthetic selection messages that can move the app cursor backward
or to an older row. The three tab implementations become consistent: all programmatic fast-highlight updates are
guarded, while real user selection events still flow normally.
