---
create_time: 2026-05-12 10:11:59
status: done
prompt: sdd/prompts/202605/followup_planning_status_propagation.md
---
# Followup Plan -> Parent Workflow PLANNING Status Propagation

## Symptom

In the `sase ace` Agents tab, the parent workflow row `@oo.plan` is shown under the **Running** group with status
`RUNNING`, even though its `.2` feedback-round child `@oo.2` has just submitted a follow-up plan (the right-hand
agent-details panel confirms a `PLAN | 2026-05-12 09:43:33` timestamp and a plan artifact at
`~/.sase/plans/202605/unread_agent_marker_u.md`).

Other planners in the same snapshot (`@ou`, `@ot.1`, `@ot.2`) — which are first plan submissions, not follow-ups —
correctly render as `PLANNING`.

Expected: `@oo.plan` (and therefore the `oo` group) should render `PLANNING` while we are waiting for the user to
approve / reject the follow-up plan.

## Root cause

Three independent facts compose into the bug:

1. **Workflow agents stay RUNNING while the runner is alive.** `load_workflow_states()`
   (`src/sase/ace/tui/models/_loaders/_workflow_loaders.py:116-124`) maps `workflow_state.json.status == "running"` to
   display status `RUNNING`. While the runner is in its plan-approval poll loop, the workflow itself is still alive, so
   `@oo.plan` is loaded as `RUNNING`.

2. **The `PLANNING` override in `apply_status_overrides` requires `status == "DONE"`.** The "plan-only workflow"
   override (`src/sase/ace/tui/models/_agent_status_overrides.py:245-254`) only promotes a root plan workflow from
   `DONE` to `PLANNING`. A workflow row that is already `RUNNING` is never promoted, which is fine for _first_ plan
   submissions (the workflow steps marker writer flips the parent's state transitions). But for **follow-up**
   submissions the parent's `workflow_state.json` is unchanged — the feedback loop reuses the same workflow state file
   with status `running`.

3. **The notification-based override no longer matches the parent row.** After the SASE_AGENT_TIMESTAMP per-phase fix
   (`src/sase/axe/run_agent_exec.py:_publish_phase_env`), the PlanApproval notification emitted by a follow-up phase
   carries `agent_timestamp = T2` (the follow-up artifacts dir's basename). `_apply_notification_status_overrides`
   (`src/sase/ace/tui/actions/agents/_notifications.py:203-208`) requires
   `agent.cl_name == cl_name AND agent.raw_suffix == agent_timestamp`. The visible parent `@oo.plan` row has
   `raw_suffix = T1`, so the override skips it. The follow-up workflow-step row (loaded with `raw_suffix = T2`) has
   `cl_name = step_name` (`_workflow_step_loaders.py:119`), which is NOT the original `cl_name` carried in
   `action_data.agent_cl_name`, so the step row is skipped too.

Net result: the visible row for the workflow stays at the loader-derived `RUNNING` and never advances to `PLANNING`
while we wait on follow-up approval. The notification is still rung and the inbox count is still incremented; only the
inline status badge / group placement is wrong.

The first plan works because at that point `agent_timestamp == raw_suffix == T1` and the matcher succeeds against the
parent row directly.

### Why `@ot.1` / `@ot.2` / `@ou` are unaffected

Those rows in the snapshot are first plan submissions for distinct planner agents; their `agent_timestamp` is also their
`raw_suffix`. No follow-up, no divergence, override fires normally.

## Fix design

Three plausible directions. Recommendation: a combination of **A** and **B**.

### Option A (recommended): include the root workflow timestamp in PlanApproval / UserQuestion action data

In the notification senders that read `SASE_AGENT_TIMESTAMP` for routing (`src/sase/llm_provider/_plan_utils.py` ~ line
170; `src/sase/axe/run_agent_helpers.py` ~ line 473), also publish a second key — e.g. `root_agent_timestamp` — derived
from the runner's _original_ launch timestamp (the one we already snapshot at `run_execution_loop` startup as
`state.original_agent_timestamp`, `src/sase/axe/run_agent_exec.py:600`).

The runner is the right place to set this because it already maintains the "original vs. current phase" distinction. The
simplest path is to expose the snapshot via env (`SASE_AGENT_ROOT_TIMESTAMP`, set once and never updated by
`_publish_phase_env`).

Then in `_apply_notification_status_overrides` extend the matcher: a notification matches an agent when `cl_name`
matches AND (`agent.raw_suffix == agent_timestamp` OR `agent.raw_suffix == root_agent_timestamp`). With this, the parent
`@oo.plan` row (raw_suffix = T1 = root_agent_timestamp) matches the follow-up's PlanApproval and gets the `PLANNING`
override.

This keeps the existing per-phase routing (so per-step UI elements that target the follow-up step itself still work)
while adding a fallback that lets the visible parent row reflect the planning state.

### Option B (recommended companion): make `apply_status_overrides` promote a RUNNING root plan workflow to PLANNING when a feedback child has a fresh, unanswered plan

Even without notifications, the on-disk evidence for "follow-up plan submitted, awaiting feedback" exists: the
feedback-round child's `agent_meta.json` (or follow-up artifacts dir) records the latest `plan_time` / `plan_path` and
there is no newer `feedback_submitted_at` for the same round. The existing pipeline already propagates feedback child
`plan_times` to the parent (`_agent_status_overrides.py:86-93`).

Extend the `is_root_plan_workflow` override block (lines 245-254) to also fire when `agent.status == "RUNNING"` AND the
parent has a feedback child whose `plan_times[-1] > feedback_times[-1]` (i.e. the most recent event on the feedback
round was a plan submission, not a feedback acceptance). Keep the "active feedback round" demotion (line 102-103) for
the inverse case (feedback round still composing the plan).

Option B is robust to notification-loss / restart-of-ace and is the correctness backbone; Option A keeps the latency low
(status flips immediately on notification arrival instead of waiting for a refresh that reloads the meta files).

### Option C (not recommended): match notifications by parent_timestamp chain

Relax the matcher to walk the workflow_step → parent_workflow chain by `parent_timestamp` and apply the override to
whichever ancestor row has `cl_name == agent_cl_name`. Works, but couples notification routing to the workflow-step
internal representation, which is fragile across the "workflow vs follow-up agent" refactors we've already done this
cycle.

### Recommended path

Ship A + B. A fixes the visible row latency immediately on notification arrival. B makes the status correct even when
the notification has been read-but-not-acted (or when ace restarts mid-flow), and is a small, local extension of the
existing override.

## Implementation outline

### 1. Publish the root timestamp (Option A)

- `src/sase/axe/run_agent_exec.py`: set `os.environ["SASE_AGENT_ROOT_TIMESTAMP"] = ctx.timestamp` (normalized to
  14-digit) at the top of `run_execution_loop`, alongside the existing per-phase env publishing. Pop it in
  `_finalize_loop`.
- Audit / verify that `_publish_phase_env` does NOT touch `SASE_AGENT_ROOT_TIMESTAMP`.

### 2. Carry the root timestamp in notifications

- `src/sase/notifications/senders.py` (`notify_plan_approval`, `notify_user_question`): accept an optional
  `agent_root_timestamp` and stash it into `action_data["agent_root_timestamp"]`.
- `src/sase/llm_provider/_plan_utils.py:170`: read `SASE_AGENT_ROOT_TIMESTAMP` alongside `SASE_AGENT_TIMESTAMP` and pass
  it to `notify_plan_approval`.
- `src/sase/axe/run_agent_helpers.py:473`: same for `notify_user_question`.

### 3. Relax the TUI matcher

- `src/sase/ace/tui/actions/agents/_notifications.py:_apply_notification_status_overrides`: read
  `root_timestamp = action_data.get("agent_root_timestamp")`, normalize it the same way. Match condition:
  `agent.raw_suffix in {agent_timestamp, root_timestamp}` (when set). When the parent row matches via `root_timestamp`,
  apply the same `PLANNING` / `QUESTION` override.
- Apply the same change to `_jump_to_agent_notification` (lines ~488-505) so Enter-to-jump on the parent row finds the
  notification too.

### 4. On-disk fallback (Option B)

- `src/sase/ace/tui/models/_agent_status_overrides.py`: in the existing feedback-round propagation block (lines 80-103),
  after merging `plan_times` / `feedback_times` into the parent, compute
  `is_awaiting_plan_review = parent.plan_times and (not parent.feedback_times or parent.plan_times[-1] > parent.feedback_times[-1])`.
- In the root-plan-workflow override block (lines 245-254), expand the guard from `status == "DONE"` to
  `status in {"DONE", "RUNNING"}` and apply `PLANNING` when `is_awaiting_plan_review` is true. Make sure the existing
  "active feedback round demotes to RUNNING" semantics still win in the inverse case (i.e. the feedback round is still
  composing).

### 5. Tests

- Unit test for the matcher (Option A):
  - Construct two agents: a parent with `raw_suffix=T1, cl_name="oo"`, and a workflow-step child with
    `raw_suffix=T2, cl_name="sase"`.
  - Build a PlanApproval notification with `agent_cl_name="oo"`, `agent_timestamp=T2`, `agent_root_timestamp=T1`.
  - Assert `_apply_notification_status_overrides` sets the parent's status override to `PLANNING`.
- Unit test for the on-disk fallback (Option B): construct a root plan workflow + feedback round child with
  `plan_times=[t]` and no later `feedback_times`; assert `apply_status_overrides` promotes parent from `RUNNING` to
  `PLANNING`.
- Visual / PNG snapshot test for the agents-tab grouping: a workflow with a follow-up plan should render under
  `Stopped > Planning`, not `Running`. Update the existing affected baselines via `just test`.

### 6. Manual verification

- Launch a planner (`sase a foo`), submit a plan, reject with feedback, wait for the follow-up plan, observe the row
  settles in `Planning` / `Stopped` not `Running`.
- Confirm `j` / Enter on the parent row still opens the plan-approval modal for the follow-up plan.

## Out of scope

- Re-architecting how workflow_state.json transitions between phases. The parent workflow remaining `running` while
  waiting for plan approval is load-bearing for the workflow runner; this plan adapts the TUI side.
- Changing how `@oo.2` step rows are rendered. The fix only changes the parent row's status / group placement; the child
  step row continues to render as-is (DONE).
- Notification routing for question/feedback rounds at depths greater than 2. Option A's root-timestamp fallback handles
  arbitrary depth because all follow-up phases share the same `SASE_AGENT_ROOT_TIMESTAMP`.

## Risks

- **Stale `SASE_AGENT_ROOT_TIMESTAMP` after the runner exits.** Mitigated by popping the env var in `_finalize_loop`.
- **Subprocesses inheriting the env var.** Already an accepted pattern for the per-phase `SASE_AGENT_TIMESTAMP`; same
  behavior applies here.
- **Visual snapshot churn.** Touching parent group placement will move some rows from Running → Planning. Expect to
  refresh affected PNG baselines.
