---
create_time: 2026-05-10 12:03:52
status: done
---
# Fix: TALE APPROVED reverts to PLAN APPROVED on `sase ace` restart

## Problem

After approving a plan as a Tale (pressing `t` in the Plan Review modal), the agent row shows status **TALE APPROVED**
in the live TUI. But after restarting `sase ace`, that same row reverts to **PLAN APPROVED**. The persisted "tale"
distinction is lost across restarts.

## Root cause

Two writers race on the same `plan_action` field in `agent_meta.json`, and the second writer doesn't know how to
distinguish "tale" from "approve":

1. **TUI writer** — `persist_plan_approved()` in `src/sase/ace/tui/actions/agents/_notification_modals.py:635`. Called
   from the background worker at line 511 with the value returned by `_plan_approval_persist_action(result)`. For a tale
   approval, this correctly inspects `result.choice == "tale"` (via `_plan_approval_choice_for_status`) and writes
   `plan_action="tale"`.

2. **Runner writer** — `update_meta_field(..., "plan_action", _accepted_plan_action_for_meta(plan_result))` in
   `src/sase/axe/run_agent_exec_plan.py:264-269`. The runner reads the response JSON written by the TUI
   (`_build_plan_approval_response`) and constructs its own `PlanApprovalResult` (in
   `src/sase/llm_provider/_plan_utils.py:236`). That JSON only carries `action`, `commit_plan`, `run_coder`,
   `coder_prompt`, `coder_model` — **the `choice` field is not propagated**.

   Today's `_accepted_plan_action_for_meta()` (lines 62-65):

   ```python
   def _accepted_plan_action_for_meta(plan_result: Any) -> str:
       if plan_result.action == "approve" and not plan_result.run_coder:
           return "commit"
       return str(plan_result.action)
   ```

   For a tale: `action="approve"`, `run_coder=True`, `commit_plan=True` → returns `"approve"`. For pure approve: same
   `action="approve"`, `run_coder=True`, `commit_plan=False` → also returns `"approve"`. The two are indistinguishable
   here.

The runner's write overwrites the TUI's correct `"tale"` with `"approve"`. Then on restart, `_plan_enrichment_status()`
in `src/sase/ace/tui/models/_loaders/_meta_enrichment.py:48-69` reads `plan_action="approve"`, finds no matching case,
and falls through to the default `"PLAN APPROVED"` at line 64.

The bug was introduced (or rather, exposed) by commit `42a3a49c` ("stabilize plan approval choices"), which added the
`tale` distinction in the TUI persist/status logic but did not update the runner-side
`_accepted_plan_action_for_meta()`. The recent keymap split commit `22eaf985` made the bug user-visible by giving "tale"
its own dedicated `t` key.

## Fix

Mirror the TUI's persist logic in the runner's `_accepted_plan_action_for_meta()` so the two writers agree on the same
value for tale approvals.

### Change 1 — `src/sase/axe/run_agent_exec_plan.py:62-65`

```python
def _accepted_plan_action_for_meta(plan_result: Any) -> str:
    if plan_result.action == "approve" and not plan_result.run_coder:
        return "commit"
    if (
        plan_result.action == "approve"
        and plan_result.commit_plan
        and plan_result.run_coder
    ):
        return "tale"
    return str(plan_result.action)
```

This matches the inference branch in `_plan_approval_choice_for_status()` (`_notification_modals.py:464-465`):

```python
if result.action == "approve" and result.commit_plan and result.run_coder:
    return "tale"
```

— which is the canonical "what does the response protocol mean?" rule. With this fix:

- **Tale** (`action=approve`, `commit_plan=True`, `run_coder=True`) → `"tale"`
- **Pure approve** (`action=approve`, `commit_plan=False`, `run_coder=True`) → `"approve"`
- **Plan committed** (`action=approve`, `run_coder=False`) → `"commit"`
- **Epic / Legend** (`action=epic|legend`) → `"epic"` / `"legend"` (unchanged)

### Why not pass `choice` through the response JSON instead?

That would also work, but it's a wider change: the response protocol is the TUI ↔ runner contract, and adding a new
field forces every consumer (mobile notification bridge, tests, integration docs) to learn about it. The
`(action, commit_plan, run_coder)` tuple already uniquely determines the choice via the existing inference rule — we
just need to apply that rule consistently on the runner side too.

## Tests

Add coverage for the four meaningful combinations of `_accepted_plan_action_for_meta`:

- `action=approve, commit_plan=True, run_coder=True` → `"tale"` _(new — the failing case)_
- `action=approve, commit_plan=False, run_coder=True` → `"approve"`
- `action=approve, commit_plan=True, run_coder=False` → `"commit"`
- `action=epic, ...` → `"epic"`

Place these next to the existing exec-plan tests (`tests/test_axe_run_agent_exec_plan_followup_approvals.py` already
asserts the `("plan_action", "epic")` write at line 51 — the new tests can live in the same file or a sibling).

Also add an end-to-end-flavored test that:

1. Builds a `PlanApprovalResult` with `choice="tale"`.
2. Runs `_build_plan_approval_response` to get the wire JSON.
3. Reconstructs the runner-side `PlanApprovalResult` from that JSON.
4. Asserts `_accepted_plan_action_for_meta()` of the reconstructed result is `"tale"`.

This pins the contract that "the runner can recover the correct `plan_action` from the response JSON alone" so future
drift between the two writers is caught immediately.

## Out of scope

- No changes to `_plan_enrichment_status()` — its current branches are correct; once the runner stops clobbering "tale"
  with "approve" the existing read path works.
- No changes to the response JSON schema. The contract stays `{action, commit_plan, run_coder, ...}`.
- No migration for existing on-disk `agent_meta.json` files where the bug has already corrupted the value to `"approve"`
  — those agents are visually shown as PLAN APPROVED today, and there's no signal in the meta to recover the original
  intent (we'd need the response JSON, which has been deleted). Going forward, new tale approvals will persist
  correctly.
