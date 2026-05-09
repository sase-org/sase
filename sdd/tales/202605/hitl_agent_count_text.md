---
create_time: 2026-05-09 17:22:53
status: done
prompt: sdd/prompts/202605/hitl_agent_count_text.md
---
# Plan: Rename Asking Agent Count Text To HITL

## Goal

Change the visible Agents-tab count wording from `asking` to `hitl` so the metric reads as human-in-the-loop rather than
a generic question/asking state.

## Context

Recent related commits introduced and refined the count surfaces:

- `164e3a13 feat: show asking count in agents tab` added shared `agent_is_asking()` semantics and the top metric-strip
  label.
- `1093c62e feat: show failed agent counts in ace` and `f2ab628b feat: color read agent count` established the top strip
  ordering and style tests.
- `63721ab5 feat: show per-panel agent count summaries` added compact per-panel title summaries with shorthand labels.

The existing implementation uses `asking` as an internal metric name in:

- `src/sase/ace/tui/widgets/agent_info_panel.py`
- `src/sase/ace/tui/actions/agents/_display_detail.py`
- `src/sase/ace/tui/actions/agents/_display_panels.py`

The status semantics live in `src/sase/agent/status_buckets.py` as `AGENT_ASKING_STATUSES` and `agent_is_asking()`.
Those names describe the current predicate and are not necessarily user-facing.

## Approach

1. Preserve the underlying behavior and counted statuses.
   - Do not change which agents count toward this metric.
   - Keep excluding these agents from the running count.
   - Keep top-level-only counting for panel summaries.

2. Rename only the user-visible count label from `asking` to `hitl`.
   - Top info panel should render examples like `2 hitl · 5 running`.
   - Per-panel compact summaries should use `H` instead of `A`, e.g. `#apple · 2 [H1 R1]`.

3. Keep internal names conservative unless a small local rename clearly improves clarity.
   - The predicate `agent_is_asking()` can remain because it is a semantic helper that predates this display wording.
   - The `asking` count parameter/field can remain if changing it would add churn without improving the UI contract.
   - If keeping internal `asking`, make tests clearly assert the UI text is now `hitl`.

4. Update focused tests that pin rendered text.
   - `tests/ace/tui/widgets/test_agent_info_panel.py` for the top strip.
   - `tests/ace/tui/test_agent_panel_titles.py` for per-panel shorthand labels.
   - Search for remaining user-facing `"asking"` expectations and update only the relevant count text.

5. Verify with targeted tests first, then repo checks.
   - Run the focused TUI tests that cover the changed rendering.
   - Because this repo requires it after file changes, run `just install` if needed and then `just check`.

## Risks

- `HITL` already has a narrower technical meaning for workflow approval steps, while the current count includes
  `PLANNING`, `QUESTION`, and `WAITING INPUT`. The requested wording treats this broader human-input pause bucket as
  human-in-the-loop. The implementation should not silently narrow the statuses unless the product intent changes.
- Compact per-panel `H` could be mistaken for hidden/help. Tests should pin it, and existing color styling should remain
  amber to preserve visual continuity.
