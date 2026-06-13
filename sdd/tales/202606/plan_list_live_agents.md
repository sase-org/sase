---
create_time: 2026-06-13 12:12:54
status: done
prompt: sdd/prompts/202606/plan_list_live_agents.md
---
# Plan: Filter plan proposals to live Agents-tab rows

## Context

`sase plan list` currently builds proposed-plan rows from every non-dismissed `PlanApproval` notification whose pending
action state is `available`. That path does not check whether the notification still maps to a live agent row. As a
result, old or orphaned pending actions can remain in the "Proposed" section even when no corresponding agent appears on
the TUI Agents tab.

The Agents tab itself is driven by the normalized agent loader pipeline: artifact/RUNNING-field sources, PID liveness
checks, deduplication, synthetic plan-child rows, and status overrides. Plan notifications already carry routing
metadata (`agent_cl_name`, `agent_timestamp`, `agent_root_timestamp`, and `agent_name`) that can be matched against that
loaded agent set.

## Goal

Make the `sase plan list` "Proposed" section show only pending plan approvals that are associated with a live,
non-terminal agent row that the Agents tab can represent. Keep `sase plan approve` in sync with the same candidate set
so hidden stale proposals do not affect selector resolution.

## Proposed design

1. Extract or centralize notification-to-agent matching.

   The TUI already has timestamp-based matching in `src/sase/ace/tui/actions/agents/_notification_navigation.py`. Move
   the reusable parts into a small shared helper, likely under `sase.notifications` or another non-widget module, so
   both the TUI and CLI can use one definition. The helper should normalize 13-character and 14-digit timestamps with
   the existing `normalize_to_14_digit()` logic.

   Matching should support:
   - `agent_cl_name` plus `agent_timestamp` or `agent_root_timestamp`, matching the existing TUI behavior.
   - `agent_name` plus timestamp, because plan notifications often display the planner identity through `agent_name`.
   - A conservative fallback only when no timestamp exists: require strong identity such as `agent_name` and project/cl
     context rather than matching broad project names alone.

2. Build proposed-plan rows from pending notifications intersected with live Agents-tab rows.

   In the plan inventory path, load normalized agents through the same data/model layer used by the Agents tab, not by
   walking notifications alone. Treat an agent as eligible when its status bucket is an active or blocked live state
   (`Stopped`, `Starting`, `Running`, or `Waiting`). This includes `PLAN`, which is the expected status for a planner
   waiting on plan review, while excluding terminal `Done` and `Failed` rows.

   The proposed section should then include only notifications for which at least one eligible loaded agent matches the
   notification routing fields. This preserves the current read-only behavior: orphaned notifications are hidden from
   the proposal list rather than mutated or dismissed.

3. Keep approval resolution aligned with listing.

   Update `sase plan approve` candidate resolution to use the same filtered pending-plan notification helper. This
   prevents old orphaned pending actions from causing "multiple pending plan proposals" when only one visible proposal
   remains, and ensures an ID copied from `sase plan list` resolves consistently.

4. Preserve approved and rejected inventory behavior.

   Approved plans can continue to come from `agent_meta.json` history. Inferred rejected rows can continue to be
   computed from archived plan files not represented by visible proposed rows or approved rows. Once orphaned proposed
   notifications are hidden, their archived plan paths may naturally fall into the inferred rejected section; that is
   acceptable because they are no longer actionable from a live agent.

5. Avoid TUI performance regressions.

   The change is in CLI inventory/approval paths, not Textual event handlers. The TUI side should only switch to the
   shared matcher and should not add synchronous disk scans to notification handlers. Existing async refresh paths
   remain unchanged.

## Tests

Add focused coverage for:

- `sase plan list` includes a pending plan notification when a matching live `PLAN`/active agent exists.
- `sase plan list` excludes an available `PlanApproval` notification with no matching live agent.
- Matching works through `agent_root_timestamp` as well as the current phase timestamp.
- Matching works for `agent_name` plus timestamp.
- `sase plan approve` with no selector ignores orphaned pending plan actions and succeeds when exactly one visible
  proposal remains.
- Existing TUI notification navigation tests still pass after moving the shared matcher.

## Verification

Run focused tests first:

```bash
pytest tests/test_plan_inventory.py tests/test_plan_approve_cli.py tests/ace/tui/test_agent_notification_status_overrides.py tests/test_plan_utils.py
```

Because this repo requires full checks after file changes, run:

```bash
just install
just check
```

## Risks and mitigations

- Risk: Importing the full TUI app stack from CLI code. Mitigation: keep the shared matcher free of widget/app imports
  and import the agent loader lazily inside inventory/approval helpers.
- Risk: Matching too broadly and keeping stale plans visible. Mitigation: require timestamp matches whenever
  notification timestamps are present, and keep fallback matching conservative.
- Risk: Matching too narrowly for older notifications without routing fields. Mitigation: hide those from "Proposed" by
  default because the requested invariant is that proposed rows correspond to live Agents-tab rows.
