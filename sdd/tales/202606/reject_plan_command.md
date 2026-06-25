---
create_time: 2026-06-25 15:01:00
status: done
prompt: sdd/prompts/202606/reject_plan_command.md
---
# Add `sase plan reject`

## Goal

Add a `sase plan reject [SELECTOR]` CLI command that rejects a pending plan proposal by notification id or unique
prefix, using the same pending-plan resolution model as `sase plan approve`.

The important behavioral requirement is that rejecting from the CLI must have the same durable effect as rejecting from
the ACE TUI: the runner receives `{"action": "reject"}`, the plan notification is dismissed, the matching planner agent
is user-killed when it is still running, and the matching Agents-tab row is hidden through the same dismissed-agent
persistence/index path that the TUI uses.

## Current Behavior

- `sase plan approve` is wired through `src/sase/main/parser_commands.py`, `src/sase/main/plan_command_handler.py`, and
  `src/sase/main/plan_approve_handler.py`.
- The CLI and mobile plan actions already share `src/sase/plan_approval_actions.py` for response-file creation and
  approval side effects.
- `execute_plan_approval_response(..., "reject")` already writes the correct runner protocol JSON, but its shared side
  effects only dismiss the notification. It does not perform the TUI-only kill/dismiss row behavior.
- The TUI reject-without-feedback branch in `src/sase/ace/tui/actions/agents/_notification_modals.py` currently:
  - writes `plan_response.json` with `{"action": "reject"}`;
  - dismisses the notification;
  - resolves the matching agent from the loaded Agents-tab rows;
  - clears status overrides;
  - calls `_do_kill_agent(agent)`.
- `_do_kill_agent` delegates durable cleanup to the existing kill pipeline: user-kill marker/process signaling,
  Rust-backed cleanup planning, dismissed-agent persistence, artifact-index sync, notification dismissal,
  workspace/artifact cleanup, and workflow-child cascade handling.

## Proposed Design

1. Add the CLI surface.
   - Add a `reject` child to `sase plan` in `register_plan_parser`.
   - Syntax: `sase plan reject [SELECTOR]`.
   - Match `approve` selector semantics: omitted selector only succeeds when exactly one visible pending plan proposal
     exists.
   - Keep help output complete and sorted. Update examples to include `sase plan reject abcdef12`.
   - No public options are needed for the initial command, so the short-option rule is unaffected.

2. Share pending-plan resolution.
   - Extract the selector resolution and availability checks currently private to `plan_approve_handler.py` into a small
     shared helper used by both approve and reject.
   - Preserve existing error codes/messages so `sase plan approve` behavior does not drift.
   - Keep filtering through `visible_pending_plan_notifications()` so orphaned pending plan notifications are not acted
     on by default.

3. Add a headless plan-rejection side-effect path.
   - Keep `execute_plan_approval_response(..., "reject")` responsible for the first critical operation: writing
     `plan_response.json` without overwriting an existing response.
   - After the response write, run durable rejection side effects that mirror the TUI:
     - dismiss the PlanApproval notification;
     - locate the matching live agent using the same notification identity fields (`agent_timestamp`,
       `agent_root_timestamp`, `agent_cl_name`, `agent_name`) used by the TUI and plan-list visibility checks;
     - signal the agent through `request_user_kill()` so `.sase_user_kill_pending` is written just like an explicit user
       kill;
     - execute the same Rust-backed cleanup plan and Python host-side persistence used by the TUI kill path;
     - add the affected identities to `dismissed_agents.json`;
     - sync the dismissed-agent projection in the artifact index so the ACE Agents tab hides the row on refresh;
     - dismiss related notifications for the killed/dismissed agent rows.
   - Factor reusable, UI-free pieces out of the TUI kill modules where needed instead of copy-pasting a CLI-only
     implementation. The CLI path should call the same durable transaction helpers the TUI uses, not approximate them.
   - If no matching agent can be found after the response is written, preserve TUI semantics: the plan rejection still
     succeeds and the notification is dismissed, but the CLI prints a warning that no Agents-tab row was found to
     dismiss.
   - If the process kill fails with permission or another hard error, return a nonzero CLI error after the response
     write and report that the plan was rejected but agent cleanup failed. Do not persist the row as dismissed unless
     the kill path reaches the same point where the TUI would persist it.

4. Wire `sase plan reject`.
   - Add `handle_plan_reject_command(args)` and `_reject_plan_from_cli(selector=...)`.
   - Use the shared resolver from step 2.
   - Call the shared response/side-effect function with `choice="reject"`.
   - Print a concise rich success line analogous to approve, including the notification id prefix and response path.
   - Include any warning from the rejection side-effect result, such as "agent not found".

5. Bring the TUI onto the shared rejection side-effect path where practical.
   - Replace the TUI’s bespoke reject-without-feedback side-effect block with the same shared helper, while preserving
     the TUI’s latency-sensitive ordering:
     - write the response first;
     - update in-memory row state immediately through the existing optimistic `_do_kill_agent` path when running inside
       the TUI;
     - keep blocking filesystem work off the Textual event loop.
   - If a full unification would make the TUI path larger or slower, keep the TUI immediate path as-is and extract only
     the durable transaction code shared by both paths. The acceptance criterion is identical durable state after
     refresh, without a synchronous TUI regression.

## Tests

Add or update focused tests:

- `tests/main/test_parser_plan.py`
  - `reject` parses with optional selector.
  - `sase plan --help` lists `approve`, `list`, `propose`, `reject`, and `search` alphabetically.
  - `sase plan reject --help` documents selector behavior and examples.
  - Long-option short-alias coverage still passes.

- `tests/test_plan_approve_cli.py` or a new `tests/test_plan_reject_cli.py`
  - `sase plan reject` by unique prefix writes exactly `{"action": "reject"}`.
  - omitted selector behavior matches approve.
  - duplicate/missing/stale response errors match approve.
  - approval metadata (`plan_approved`, `plan_action`, archived plan path) is not written for rejection.
  - notification is dismissed.
  - a matching live plan agent is user-killed and persisted into dismissed-agent state/artifact-index projection.
  - no matching agent produces a warning/result flag but still writes the rejection response.

- TUI rejection tests
  - Existing reject-without-feedback tests continue to assert `plan_response.json` is written before cleanup.
  - Add coverage that TUI rejection and CLI rejection invoke the same durable cleanup helper or produce the same
    dismissed identities.

- Mobile/shared plan-action tests if `execute_plan_approval_response("reject")` gains shared side effects
  - Mobile rejection still writes the same response JSON.
  - Shared reject side effects do not regress existing approval side effects.

## Verification

After implementation:

1. Run `just install`.
2. Run targeted tests:
   - `pytest tests/main/test_parser_plan.py tests/test_plan_approve_cli.py tests/test_plan_rejection_response.py tests/test_mobile_notifications_bridge.py`
3. Run `just check` before finishing, because code files will have changed.

## Notes and Risks

- The CLI should not import Textual app code or require a running TUI. It can reuse the same data model and durable
  cleanup helpers, but not UI-only methods.
- The TUI performance note matters: do not add synchronous disk I/O or process cleanup to the modal dismissal path. Keep
  the TUI’s immediate row removal and tracked background task behavior intact.
- The Rust core boundary is already partly satisfied by the existing agent cleanup planner. If new cleanup decision
  logic is needed, add it behind the existing core cleanup facade rather than implementing divergent Python rules.
