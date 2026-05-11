---
create_time: 2026-05-11 10:19:10
status: done
prompt: sdd/prompts/202605/parent_question_status.md
---
# Plan: Propagate `QUESTION` from follow-up child to parent workflow

## Problem

A root `.plan` workflow whose `.code` follow-up has an **unanswered question** is displayed as `PLAN DONE` in `sase ace`
instead of `QUESTION`.

Reproduction (matches the snapshot in the bug report):

- `@jf.plan` is a root plan workflow (raw status `DONE`).
- It has one follow-up: `@jf.code` (the coder).
- The coder has submitted a question — its raw status is `DONE`, it has a `questions_times` entry, and no `.q` follow-up
  has been created yet (the `.q` is only created after the user answers).
- Observed: parent shows `PLAN DONE`.
- Expected: parent shows `QUESTION` until the user answers, then snaps back to `PLAN APPROVED` (when the answer
  spawns/resumes the coder).

User confirms the `PLAN APPROVED` → `QUESTION` → `PLAN APPROVED` round-trip already works correctly on the _answer_ side
(resumed coder ends up active, which triggers the existing `PLAN APPROVED` override). Only the _outbound_ transition is
broken.

## Root cause

`src/sase/ace/tui/models/_agent_status_overrides.py::apply_status_overrides` applies overrides in this order:

1. **Follow-up override loop** (lines ~124-159). For each follow-up child:
   - If `child.status not in {DONE, FAILED}` → set `followup_override[parent_ts]` to `PLAN APPROVED` / `EPIC APPROVED` /
     etc. (active path).
   - Else → set `completed_followup_override[parent_ts]` based on the completed child (`EPIC CREATED` or `None`).
2. Lines ~190-194: apply `followup_override` to parents still in `DONE`.
3. Lines ~202-212: any root `.plan` workflow still in `DONE` whose suffix is in `parents_with_followup` becomes
   `PLAN DONE` (or `EPIC CREATED`).
4. Lines ~231-242: any agent that is `DONE` + has `questions_times` + has no follow-up of its own becomes `QUESTION`.

When the coder has an unanswered question, its raw status is still `DONE` at step 1, so it takes the "completed" branch
and the parent ends up `PLAN DONE` at step 3. The `QUESTION` override at step 4 only flips the _child_'s status, never
the parent's. The parent's `PLAN DONE` sticks.

`PLAN APPROVED → PLAN DONE` on question submission and the reverse on answer are the same underlying behavior: the
parent override looks at the child's _raw_ `DONE` status and is blind to the unanswered-question state, so it silently
demotes the parent from "child active" to "child completed."

## Fix

Treat a child with an unanswered question as **not yet completed** for the purposes of parent override, and route the
parent to `QUESTION`.

Concrete changes in `_agent_status_overrides.py::apply_status_overrides`:

1. **Pre-compute `parents_with_followup`** before the main follow-up loop so we can ask "does this child have a `.q`
   follow-up of its own?" while iterating. Today it is built incrementally inside the loop, so the check isn't reliable
   at iteration time.
2. **In the follow-up loop**, add a third branch alongside active/completed: if the child's raw status is `DONE` _and_
   it has `questions_times` _and_ it has no follow-ups of its own, set `followup_override[parent_ts] = "QUESTION"`. The
   follow-up is effectively "active, blocked on the user."
3. The existing apply step (lines 190-194) will then flip the parent's `DONE` to `QUESTION`, beating the `PLAN DONE`
   override at lines 202-212 (which only acts on parents still in `DONE`).
4. Keep the existing child-side `DONE → QUESTION` override (lines 231-242) unchanged so the child still renders as
   `QUESTION`.

The ordering by `run_start_time or start_time` already gives last-writer-wins across multiple follow-ups; the new
`QUESTION` override participates in the same precedence, so a later active coder correctly wins over an earlier question
on the same parent.

## Tests

Add to `tests/test_agent_loader_status_override_followups.py`:

1. `test_apply_status_overrides_parent_with_questioning_code_child_becomes_question` — root `.plan` workflow (`DONE`) +
   `.code` child (`DONE` + `questions_times`
   - no `.q` grandchild). Assert parent → `QUESTION`, child → `QUESTION`.
2. `test_apply_status_overrides_parent_with_answered_question_stays_plan_done` — same as above but the `.code` child has
   a `.q` follow-up. Assert parent → `PLAN DONE` (the existing terminal behavior is preserved).
3. `test_apply_status_overrides_parent_with_active_code_after_question_is_plan_approved` — `.code` child currently
   `RUNNING` (answer already in flight) with a `questions_times` entry. Assert parent → `PLAN APPROVED` (active path
   still wins; the question-override branch only fires for raw `DONE`).

## Out of scope

- The display/styling of `QUESTION` on the parent row. It's already a known status (the child renders it today), so the
  existing list-render code should handle it without changes; we verify visually but won't refactor styling.
- Other workflow statuses (`EPIC APPROVED`, `PLAN COMMITTED`, etc.) — the same blind spot may exist there in theory, but
  the bug report is scoped to `PLAN APPROVED ↔ QUESTION`. Broaden later if it actually surfaces.
- Anything in the Rust core. This is a TUI-presentation override (Python).

## Files touched

- `src/sase/ace/tui/models/_agent_status_overrides.py` — fix.
- `tests/test_agent_loader_status_override_followups.py` — three new tests.
