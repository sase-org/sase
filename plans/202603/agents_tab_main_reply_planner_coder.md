---
create_time: 2026-03-30 10:26:50
status: done
---

# Plan: Aggregate Planner/Coder Replies in Main Agent "AGENT REPLY"

## Goal

On the `sase ace` Agents tab, when the user selects a **main plan agent entry** (top-level, not a nested step), make the
prompt panel's `AGENT REPLY` section include:

- the main planner agent reply
- follow-up planner replies (feedback rounds)
- coder reply

This should feel intuitive in the UI, be resilient to fold/filter state, and avoid changing nested step behavior.

## Product Decisions

1. Scope strictly to main plan entry:

- Apply aggregation only when selected agent is a top-level workflow/agent entry with `role_suffix == ".plan"` and
  `not is_workflow_child`.
- Do not aggregate when user selects nested workflow steps or follow-up child entries.

2. Keep one primary section title:

- Preserve existing section title (`AGENT REPLY` for active agents, `AGENT CHAT` for completed agents) to avoid
  relearning.
- Add clearly separated sub-blocks per related agent using compact labels (Planner/Coder + suffix + status + timestamp)
  so chronology is obvious.

3. Include all planner rounds + coder:

- Parent selected entry contributes its own reply/chat first.
- Related children are discovered by `parent_timestamp == parent.raw_suffix` and `parent_workflow is None`.
- Include children with numeric suffixes (`.2`, `.3`, ...) as planner rounds and `.code` as coder.
- Order by effective start time ascending so the story reads naturally.

4. Reliability over visibility state:

- Source related agents from `app._agents_with_children` (pre-fold list), falling back to `app._agents`.
- This prevents missing replies when children are folded in the list.

## Technical Design

### 1) Add a follow-up reply aggregation helper in prompt panel display mixin

In `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py`:

- Add helper to detect whether selected agent is eligible for aggregation (`is_main_plan_entry`).
- Add helper to collect related follow-up agents from app state.
- Add helper to read each related agent's content via existing methods:
  - prefer timestamped chunks (`get_timestamped_reply_chunks`)
  - else `get_live_reply_content` for active
  - else `get_response_content` for done

### 2) Render grouped sub-sections in AGENT REPLY / AGENT CHAT

When rendering selected main plan entry:

- Existing behavior for base agent remains.
- After base content, append related planner/coder blocks:
  - divider line
  - label line (role + status + time)
  - content (timestamped chunks or markdown content)
- If related agent has no content yet, show a dim waiting/empty indicator for that role.

### 3) Preserve behavior for nested entries and non-plan agents

- Early gating ensures no aggregation for:
  - workflow child steps
  - follow-up child entries themselves
  - unrelated running agents

### 4) Keep hints mode parity

`update_display_with_hints` should mirror the same aggregated content logic for consistency with `%f`/hint navigation
workflows.

## UX Details

- Visual language remains current (same colors/separators) for consistency.
- Role labels are concise and scan-friendly:
  - `Planner (.plan)` for parent
  - `Planner (.2)` / `Planner (.3)` for feedback rounds
  - `Coder (.code)` for coder
- Chronological ordering avoids cognitive jumps.

## Test Plan

Update `tests/test_ace_tui_widgets.py` with focused unit tests on `AgentPromptPanel`:

1. `test_main_plan_entry_aggregates_planner_and_coder_replies`

- Build parent `.plan` + children `.2` + `.code` with matching `parent_timestamp`.
- Verify rendered text includes all three reply blocks in order.

2. `test_nested_step_does_not_aggregate_followup_replies`

- Use a workflow child step as selected agent.
- Verify only its own content is rendered.

3. `test_non_plan_top_level_agent_does_not_aggregate`

- Top-level agent without `.plan` role suffix.
- Verify no aggregated follow-up blocks are injected.

4. `test_aggregation_uses_agents_with_children_when_available`

- Provide related agents only via mocked `app._agents_with_children`.
- Verify aggregation still appears even if filtered/folded from current visible list.

## Files Expected To Change

- `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py`
- `tests/test_ace_tui_widgets.py`

## Validation

- Run unit tests for changed areas.
- Run full repository check (`just check`) before responding.
