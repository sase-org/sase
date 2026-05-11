---
create_time: 2026-05-11 10:36:34
status: done
---
# Plan: Restore `TALE APPROVED` (not `PLAN APPROVED`) when an answered question resumes the coder

## Problem

The previous fix (commit `7fc23da4`) routed a root `.plan` workflow to `QUESTION` while its `.code` follow-up has an
unanswered question. That fixed the outbound transition `TALE APPROVED → PLAN DONE`. But on the answer side, the parent
row now snaps to `PLAN APPROVED` instead of `TALE APPROVED`. The user expected the full round-trip
`TALE APPROVED → QUESTION → TALE APPROVED`.

Note: the original bug report described the flow as `PLAN APPROVED → PLAN DONE → PLAN APPROVED`, but the actual user
snapshot was a Tale-approved plan (`t` keymap, not generic approve). The previous plan addressed the outbound but did
not specifically handle the Tale variant.

## Root cause

There are two paths by which the parent can render as `TALE APPROVED`:

1. **In-session override**: pressing `t` writes `_agent_status_overrides[parent.identity] = "TALE APPROVED"` in
   `_notification_modals.py`. `finalize_agent_list` applies this AFTER `apply_status_overrides` runs, masking whatever
   the override loop computed for `parent.status`.

2. **Disk persistence**: `persist_plan_approved` writes `plan_action="tale"` into the parent's `agent_meta.json`. On
   reload, `_plan_enrichment_status()` in `_loaders/_meta_enrichment.py` maps `plan_action="tale"` to `TALE APPROVED` —
   but only when `agent.status == "RUNNING"`. A root workflow whose `workflow_state.json` reports `completed` arrives at
   the enricher as `DONE`, so the enrichment branch never fires.

Inside `apply_status_overrides`, the active-follow-up branch decides `TALE APPROVED` vs `PLAN APPROVED` purely from
`parent.status` (lines 159-164). For a DONE workflow parent, `parent.status` is `DONE` at that point — never
`TALE APPROVED` — so the branch always returns `PLAN APPROVED`. The in-session override later masks it back to
`TALE APPROVED`, which is why the user sees the right status pre-question. Across `sase ace` restart,
`_agent_status_overrides` is empty (`_state_init.py:342`), the override mask is gone, and the parent stays at
`PLAN APPROVED`.

So the bug surfaces in two cases:

- **After a question is answered, even in-session.** The `apply_status_overrides` follow-up loop writes `PLAN APPROVED`
  to the override map; the apply step (line ~211) sets `parent.status = "PLAN APPROVED"`. The in-session override mask
  in `finalize_agent_list` would normally restore `TALE APPROVED`, and in fact this case is already partially handled by
  the previous fix (because `QUESTION` is not in `DISMISSABLE_STATUSES`, the override is preserved). So the in- session
  answer-side already round-trips correctly today _via the override_.
- **After `sase ace` restart.** The override is gone. The disk-persisted `plan_action="tale"` is unreachable for a DONE
  parent. Parent renders as `PLAN APPROVED` instead of `TALE APPROVED`. This is the case the previous fix doesn't
  actually solve.

## Fix

Promote `plan_action` from a status-enrichment-only signal to a persistent agent property that `apply_status_overrides`
can consult directly, so the active follow-up branch picks `TALE APPROVED` regardless of whether the in-session override
happens to be present.

### Changes

1. **Add `plan_action: str | None = None` to `Agent`** (`src/sase/ace/tui/models/agent.py`). Mirror the existing
   `auto_approve_plan_action` field placement and serialization treatment.

2. **Populate `agent.plan_action` unconditionally from meta**, in both enrichers in
   `src/sase/ace/tui/models/_loaders/_meta_enrichment.py`:
   - `enrich_agent_from_meta` (filesystem): assign `agent.plan_action = data["plan_action"]` when the value is a non-
     empty string. Place above the existing `_plan_enrichment_status` gate (the gate stays untouched — it controls live
     status mapping only).
   - `enrich_agent_from_meta_wire` (snapshot): mirror the assignment from `meta.plan_action`. The file's docstring
     emphasizes keeping the two variants in lockstep.

3. **Branch on `parent.plan_action` in the active follow-up override** in
   `src/sase/ace/tui/models/_agent_status_overrides.py` (current lines 159-164):

   ```python
   else:
       followup_override[agent.parent_timestamp] = (
           "TALE APPROVED"
           if parent.plan_action == "tale" or parent.status == "TALE APPROVED"
           else "PLAN APPROVED"
       )
   ```

   The `or parent.status == "TALE APPROVED"` clause preserves the existing in-memory path (a RUNNING planner whose
   enrichment already mapped it to `TALE APPROVED`).

4. **No change to the QUESTION branch.** The previous fix's QUESTION literal stays as-is — the displayed status during
   the question is out of scope here (separate finalize-layer concern; see "Out of scope").

5. **No change to `_plan_enrichment_status`.** Its `RUNNING` gate must stay so live planner status decisions don't
   shift. We are only making `plan_action` itself independently inspectable.

6. **No change to `persist_plan_approved` or the in-session override setters.** They already keep disk and memory in
   sync.

## Tests

Add to `tests/test_agent_loader_status_override_followups.py`:

1. `test_apply_status_overrides_active_code_child_with_tale_plan_action_is_tale_approved` — parent has
   `plan_action="tale"`, status `DONE`, child is `.code` `RUNNING`. Assert parent → `TALE APPROVED`.
2. `test_apply_status_overrides_active_code_child_without_plan_action_is_plan_approved` — regression guard for the
   generic-approve case: parent has `plan_action=None`, child `RUNNING`. Assert parent → `PLAN APPROVED`.
3. `test_apply_status_overrides_active_code_child_with_parent_status_tale_approved` — keep the in-session-mask path:
   parent.status starts as `TALE APPROVED` (no `plan_action`). Assert parent → `TALE APPROVED`.
4. `test_apply_status_overrides_questioning_code_with_tale_plan_action_still_becomes_question` — the QUESTION branch
   continues to fire even when `plan_action="tale"`: parent has `plan_action="tale"`, child is `DONE` with
   `questions_times` and no `.q` follow-up. Assert parent → `QUESTION`.

Add to `tests/test_enrich_agent_wait_duration.py` (or a new sibling file if the existing one is wait-specific): write an
`agent_meta.json` with `plan_action="tale"` and a non-RUNNING status, call `enrich_agent_from_meta`, assert
`agent.plan_action == "tale"`. If the wire variant has comparable test coverage nearby, mirror the assertion for
`enrich_agent_from_meta_wire`.

## Out of scope

- **Parent's displayed status _during_ the question state.** The previous fix routes parent to `QUESTION` in the apply
  layer; whether `finalize_agent_list` then masks that to `TALE APPROVED` via the in-session override dict is unchanged.
  Letting apply-layer `QUESTION` win over the in-session override is a finalize-layer change — separate work.
- **Other plan-action variants.** `EPIC APPROVED`, `LEGEND APPROVED`, `PLAN COMMITTED` have the same restart-blindness
  in theory, but the user-reported bug is scoped to Tale. Broaden later if it surfaces.
- **Migration for already-broken on-disk meta.** Any pre-fix Tale parents whose `plan_action` was clobbered by the prior
  `tale_approved_persistence` bug remain unrecoverable. Going forward, new Tale approvals will round-trip correctly.
- **Rust core.** This is a TUI presentation/override change (Python only).

## Files touched

- `src/sase/ace/tui/models/agent.py` — add `plan_action` field.
- `src/sase/ace/tui/models/_loaders/_meta_enrichment.py` — populate `agent.plan_action` in both enrichers.
- `src/sase/ace/tui/models/_agent_status_overrides.py` — branch on `parent.plan_action` in the active follow-up
  override.
- `tests/test_agent_loader_status_override_followups.py` — four new tests.
- `tests/test_enrich_agent_wait_duration.py` (or a new sibling) — enrichment-side coverage for `plan_action`.
