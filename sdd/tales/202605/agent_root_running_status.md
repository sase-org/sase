---
create_time: 2026-05-29 10:30:46
status: done
prompt: sdd/prompts/202605/agent_root_running_status.md
---
# Plan: Keep Root Agent Status Aligned With Active Child

## Problem

The Agents tab can show a root family row as `QUESTION` after a question has been answered and a follow-up child is
running. In the provided `sase ace` snapshot, `@boi` is shown as `QUESTION` even though its newest child `@boi-2` is
`RUNNING`, so the root row is bucketed under Stopped instead of Running.

## Findings

- The model-layer family aggregation in `src/sase/ace/tui/models/_agent_status_overrides.py` already mirrors the newest
  logical child onto the family root.
- A direct load of the live `@boi` artifacts computes the root as `RUNNING`, with `@boi-2` attached as the newest
  follow-up child.
- The stale status appears to come from the TUI in-session notification override path:
  - `_apply_notification_status_overrides()` records `QUESTION` for a matching root row when a `UserQuestion`
    notification is unread.
  - `finalize_agent_list()` and the worker-side finalize plan then reapply `_agent_status_overrides` to loaded agents
    unless the row is terminal.
  - That means a stale `QUESTION` override can mask a newer loader-computed `RUNNING` state after a follow-up child has
    started.

## Desired Behavior

Notification overrides should remain useful while the row is actively waiting for input, but they should not overrule a
newer source-of-truth status produced by the loader/family aggregation. Once a root family row has advanced to a running
follow-up, the root row should display and group as `RUNNING`.

## Implementation Approach

1. Add a small status-override reconciliation helper in the agents loading/finalize path.
   - It should decide whether an in-memory override is still allowed for a loaded agent.
   - It should specifically drop stale `QUESTION` overrides when the loaded agent status has advanced to an active
     non-question status such as `RUNNING`, `PLAN APPROVED`, `TALE APPROVED`, `EPIC APPROVED`, `LEGEND APPROVED`, or
     `PLAN COMMITTED`.
   - It should preserve existing behavior for true still-blocked `QUESTION` rows and for terminal cleanup.

2. Use the helper in both finalize implementations.
   - The synchronous path in `src/sase/ace/tui/actions/agents/_loading_finalize.py`.
   - The off-thread/precomputed path in `src/sase/ace/tui/actions/agents/_loading_compute_finalize.py`.
   - Keeping both paths aligned avoids a first-render versus refresh divergence.

3. Add focused regression tests.
   - A pure finalize-plan test proving a `QUESTION` override is cleared/ignored when the loaded root status is
     `RUNNING`.
   - A synchronous finalize or notification-status test covering the same root-family scenario at the app layer if an
     existing test harness makes that practical.
   - Keep existing tests that assert active question notifications create `QUESTION` overrides intact.

4. Verify with targeted tests first, then repository checks.
   - Run the directly affected tests around notification status overrides, question restoration, and loading finalize.
   - Because this repo requires it after source changes, run `just install` if needed and `just check` before finishing.

## Risk Notes

- The main risk is clearing a legitimate question override too early. The guard should only clear when the
  loader-computed status is a clear progression away from `QUESTION`, not for `DONE` rows with unanswered questions or
  current `QUESTION` rows.
- Since this is TUI presentation/status reconciliation, it belongs in this Python repo rather than the Rust core
  boundary.
