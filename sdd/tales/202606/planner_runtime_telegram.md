---
create_time: 2026-06-17 17:59:27
status: done
prompt: sdd/prompts/202606/planner_runtime_telegram.md
---
# Add planner runtime to Telegram plan approval messages

## Objective

Show the elapsed runtime of the planner agent in the Telegram plan approval message, using the same `Runtime: 4m32s`
style already used for agent completion Telegram messages. Here, "runtime" means elapsed planner duration, not the LLM
provider/runtime name.

## Current Behavior

- `sase plan propose <plan_file>` archives the plan and writes `.sase_plan_pending` under the current agent artifacts
  directory.
- `src/sase/axe/run_agent_exec_plan.py::handle_plan_marker` handles that marker, records `plan_submitted_at`, then calls
  `sase.llm_provider._plan_utils.handle_plan_approval(...)`.
- `handle_plan_approval(...)` creates a `PlanApproval` notification through
  `src/sase/notifications/senders.py::notify_plan_approval(...)`.
- `notify_plan_approval(...)` already includes planner identity metadata in `action_data`: `agent_name`, `model`,
  `llm_provider`, timestamps, project routing, and response directory. It does not include elapsed runtime.
- `sase-telegram` formats the outbound message in `src/sase_telegram/formatting.py::_format_plan_approval(...)`. It
  already displays the agent name and provider/model label. It also has precedent in `_format_workflow_complete(...)`
  for rendering `action_data["runtime"]` as `*Runtime:* ...`.
- The runner already records `run_started_at` before entering the execution loop, and `handle_plan_marker` records the
  plan endpoint (`plan_submitted_at`) when the plan is submitted for approval. Those two timestamps are the correct
  planner runtime segment.

## Proposed Design

1. Compute planner runtime at the plan marker boundary.

   In `src/sase/axe/run_agent_exec_plan.py`, after `plan_submitted_at = datetime.now(UTC).isoformat()`, calculate an
   optional compact runtime string for the planner phase. Reuse
   `sase.axe.run_agent_runtime.format_agent_run_runtime(...)` so formatting and fallback behavior match completion
   notifications:
   - `launch_timestamp_suffix=ctx.artifacts_timestamp`
   - `run_started_at=ctx.agent_meta.get("run_started_at")` when it is a non-empty string
   - `completion_time=plan_submitted_at` parsed/kept as the same `datetime` object used to record the timestamp

   This yields the duration from actual execution start to plan submission, not the later human approval wait.

2. Thread the runtime through the existing plan approval notification payload.

   Extend `sase.llm_provider._plan_utils.handle_plan_approval(...)` with an optional `agent_runtime: str | None = None`
   parameter and pass it to `notify_plan_approval(...)`.

   Extend `src/sase/notifications/senders.py::notify_plan_approval(...)` with the same optional argument and store it in
   `action_data["runtime"]` when present. Use the existing `runtime` key rather than adding a plan-specific key because
   Telegram completion notifications already use that field.

   Leave auto-approval behavior unchanged. Auto-approved plans skip notification creation today, so no runtime field is
   needed there.

3. Render runtime in Telegram plan approval messages.

   In `sase-telegram` workspace `sase-telegram_10`, update `src/sase_telegram/formatting.py::_format_plan_approval(...)`
   to append a header line when `n.action_data.get("runtime")` is present:

   ```text
   📋 CLAUDE(opus) Plan Review  @agent
   Runtime: 4m32s
   ```

   Keep the exact Telegram MarkdownV2 escaping pattern used by `_format_workflow_complete(...)`:
   `*Runtime:* {escape_markdown_v2(runtime)}`. Put the runtime before the notes/plan body so it is visible even when the
   plan content is long or truncated.

4. Preserve compatibility.

   If older SASE versions emit plan approval notifications without `runtime`, Telegram output should be unchanged. If
   runtime formatting returns `None` because timestamps are missing or malformed, omit the line instead of showing
   `unknown`.

## Tests

Core SASE:

- Add or extend a `tests/test_plan_utils.py` test proving `handle_plan_approval(...)` forwards an `agent_runtime`
  argument into `notify_plan_approval(...)`.
- Add or extend `tests/notification_store/test_senders.py::TestNotifyPlanApproval` to assert
  `notify_plan_approval(..., agent_runtime="4m32s")` stores `action_data["runtime"] == "4m32s"`.
- Add a focused test around `src/sase/axe/run_agent_exec_plan.py::handle_plan_marker` that patches
  `format_agent_run_runtime` and `handle_plan_approval`, then asserts:
  - the formatter receives the planner `run_started_at`, `ctx.artifacts_timestamp`, and the plan-submitted completion
    time
  - `handle_plan_approval` receives `agent_runtime="4m32s"`

Telegram:

- Add `tests/test_formatting.py::TestFormatPlanApproval` coverage that a plan approval notification with
  `action_data["runtime"] = "4m32s"` renders `*Runtime:* 4m32s`.
- Assert ordering: runtime appears after the title/name line and before the plan-ready note/body.
- Keep existing plan approval tests unchanged for notifications without runtime to preserve backwards compatibility.

## Validation

- In the core repo, run the focused tests first:

  ```bash
  just install
  just test tests/test_plan_utils.py tests/notification_store/test_senders.py tests/test_axe_run_agent_exec_plan_followup_metadata.py
  ```

  If the new `handle_plan_marker` test lands in a different nearby file, include that file instead of or in addition to
  `tests/test_axe_run_agent_exec_plan_followup_metadata.py`.

- In `sase-telegram_10`, run:

  ```bash
  just install
  just test tests/test_formatting.py
  ```

- Before completion after implementation, run `just check` in each repo touched, unless the eventual change remains
  limited to planning artifacts.

## Risks and Mitigations

- Runtime could accidentally include human approval wait time. Mitigation: compute it in `handle_plan_marker` before
  polling for approval, using `plan_submitted_at` as the endpoint.
- `runtime` could be confused with the provider/runtime label. Mitigation: only use `runtime` as the elapsed-duration
  action_data key, and keep provider/model in the existing `llm_provider` and `model` fields.
- Missing timestamps may occur in older or unusual agents. Mitigation: reuse `format_agent_run_runtime(...)`, which
  already returns `None` for malformed/missing inputs, and omit the Telegram line in that case.
- Cross-repo version skew is expected because `sase-telegram` depends on `sase>=0.1.0`. Mitigation: Telegram treats
  `runtime` as optional, so either package can roll forward independently.

## Implementation Order

1. Core payload plumbing: add optional runtime parameters to `handle_plan_approval(...)` and
   `notify_plan_approval(...)`.
2. Core runtime calculation: compute planner runtime in `handle_plan_marker` and pass it to `handle_plan_approval(...)`.
3. Core tests for payload storage and runtime propagation.
4. Telegram formatter change and formatting tests.
5. Focused validation, then full `just check` in touched repos.
