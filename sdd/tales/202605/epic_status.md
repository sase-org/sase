---
create_time: 2026-05-04 14:50:13
status: done
prompt: sdd/prompts/202605/epic_status.md
---
# Plan: Keep `%epic` Plan Writers Running Until a Plan Is Submitted

## Problem

Agents launched with `%epic` are showing as `PLANNING` in `sase ace` while they are still actively drafting the plan.
That puts them in the `Needs Attention` bucket even though no user action is needed: `%epic` uses plan-specific
auto-approval, so once the agent submits a plan it should flow directly into the epic creation path.

## Current Findings

- `%epic` parsing is working as intended in `src/sase/axe/run_agent_phases.py`: it records `plan=true` and
  `auto_approve_plan_action="epic"` without enabling general `approve`.
- The auto-approval path is also working in `src/sase/llm_provider/_plan_utils.py` and
  `src/sase/main/plan_approve_handler.py`: `auto_approve_plan_action="epic"` returns a
  `PlanApprovalResult(action="epic")` without creating a plan approval notification.
- The likely root cause is the TUI metadata enrichment in `src/sase/ace/tui/models/_loaders/_meta_enrichment.py`: any
  live agent with `plan=true` and no `plan_approved` marker is changed from `RUNNING` to `PLANNING`, even before
  `plan_submitted_at` exists.
- Snapshot/wire loading mirrors that same logic in the same file, so both filesystem and `sase ace` snapshot paths need
  the same fix.

## Implementation Approach

1. Introduce a small helper in `src/sase/ace/tui/models/_loaders/_meta_enrichment.py` that decides whether a plan-like
   live agent is actually awaiting manual plan approval.
2. Only show `PLANNING` when the agent has submitted a plan for review and does not have an auto-approval path active.
   - Treat `plan_submitted_at` as the durable signal that a plan exists.
   - Treat `auto_approve_plan_action` and normal `approve` as non-actionable auto-approval modes.
   - Preserve existing `PLAN APPROVED`, `PLAN COMMITTED`, `EPIC APPROVED`, and `LEGEND APPROVED` handling when
     `plan_approved=true`.
   - Preserve `WAITING` precedence.
3. Apply the same logic to the filesystem and wire enrichment branches so snapshot loading and live artifact loading
   stay in lockstep.
4. Add focused regression tests:
   - A `%epic`/auto-epic live agent with `plan=true` but no `plan_submitted_at` remains `RUNNING`.
   - A normal manual `%plan` live agent with `plan=true` but no `plan_submitted_at` remains `RUNNING`.
   - A normal manual `%plan` live agent with `plan_submitted_at` and no approval becomes `PLANNING`.
   - Auto-epic with `plan_submitted_at` remains `RUNNING` until the existing approved/follow-up markers take over.
   - Mirror at least the core cases through `enrich_agent_from_meta_wire`.
5. Update comments/tests whose wording says `PLANNING` means active drafting; after this fix, `PLANNING` should mean the
   user needs to act on a submitted plan.

## Verification

- Run the targeted tests covering metadata enrichment and status bucketing.
- Run `just install` if needed for this workspace.
- Run `just check` before finishing because this repo requires it after file changes.
