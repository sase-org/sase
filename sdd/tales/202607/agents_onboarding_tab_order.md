---
create_time: 2026-07-01 05:55:59
status: done
---
# Agents Onboarding Tab Order Plan

## Goal

Make the Agents-tab onboarding message list the tabs in the same visible order as the ACE tab bar: Agents, PRs, AXE. The
referenced screenshot shows the top bar already starts with Agents, while the onboarding "The three tabs" section lists
PRs first, creating avoidable confusion for new users.

## Current Understanding

- The visible tab bar order is centralized in `src/sase/ace/tui/tab_order.py` as
  `TAB_ORDER = ("agents", "changespecs", "axe")`.
- `src/sase/ace/tui/widgets/tab_bar.py` renders labels from that shared order, mapping `changespecs` to the visible
  label `PRs`.
- `src/sase/ace/tui/widgets/agent_onboarding.py` builds the onboarding tab list with hard-coded rows, and those rows
  currently appear as PRs, Agents, AXE.
- Existing unit coverage only checks that the onboarding content includes the three labels, not their order.
- Existing visual PNG coverage includes the empty Agents onboarding screen, so the accepted snapshot will likely need to
  change after the copy order changes.

## Proposed Approach

1. Update the onboarding tab-list construction so row order follows the shared `TAB_ORDER`.
   - Keep the onboarding-specific descriptions local to `agent_onboarding.py`.
   - Use a small metadata mapping keyed by tab name for label, color, and copy.
   - Iterate over `TAB_ORDER` when appending rows, so future tab-order changes do not silently drift from the onboarding
     guide.

2. Preserve the current visible labels and descriptions, only changing the row order.
   - Agents: "Inspect prompts, diffs, tools, and artifacts. You are here."
   - PRs: "Browse ChangeSpecs: commits, hooks, mentors, and status."
   - AXE: "Monitor the Axe daemon and automation."

3. Strengthen focused unit coverage in `tests/ace/tui/widgets/test_agent_onboarding.py`.
   - Add an assertion that the tabs card renders rows in the exact visible order Agents, PRs, AXE.
   - Keep the existing inclusion and keymap tests intact.

4. Refresh or inspect visual coverage for the onboarding screen.
   - Run the focused widget test first.
   - Run the onboarding PNG snapshot test.
   - If the PNG snapshot fails only because the tab rows are intentionally reordered, update the
     `agents_onboarding_120x40` golden using the existing snapshot update flow.

5. Run repository checks required for SASE code changes.
   - Run `just install` first because this is an ephemeral workspace.
   - Run focused tests during development.
   - Run `just check` before finishing, since this change touches source/tests outside the documented exceptions.

## Validation Plan

- `just install`
- Focused unit test for the onboarding widget.
- Focused PNG snapshot test for the Agents onboarding screen.
- `just check`

## Risks and Notes

- The implementation should avoid changing tab navigation, startup tab state, or the top-bar rendering path; those
  already have Agents first.
- The PNG snapshot is expected to be the only broad visual artifact affected.
- If snapshot output changes beyond the intended row order, inspect the diff before accepting any golden update.
