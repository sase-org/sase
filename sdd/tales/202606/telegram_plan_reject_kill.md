---
create_time: 2026-06-17 17:48:53
status: done
prompt: sdd/prompts/202606/telegram_plan_reject_kill.md
---
# Telegram Plan Reject Kill Fix

## Context

A recent Telegram plan notification (`1f97a232-9a95-493f-9b68-a93c8e35696e`, `frontmatter_panel_add_property_fix.md`)
was dismissed after a Telegram action, but the originating agent (`9u.cld`, PID `1333544`) stayed alive. Its artifacts
show a follow-up code phase (`9u.cld--code`) was launched and is still running under the same process tree. The response
directory for the plan approval session is empty, which means the file-based response was consumed or cleaned up, but
Telegram did not enforce the same explicit agent termination behavior as the TUI.

The TUI plan rejection path writes `plan_response.json` and then calls the agent kill flow for plain rejection without
feedback. Telegram currently only writes the response file for `plan:<prefix>:reject`; it does not kill the named agent.
That leaves correctness dependent on the blocked runner noticing and handling the response before any other continuation
path wins.

## Plan

1. Keep the existing file-response protocol intact:
   - `Reject` continues to write `{"action": "reject"}` to `plan_response.json`.
   - `Feedback` remains a replan path and must not kill the agent.
   - Approval actions (`Tale`, `Approve`, `Epic`, `Legend`) keep their current behavior.

2. Add an explicit Telegram-side kill for plain plan rejection:
   - After successfully writing the reject response, resolve the originating agent name from the pending PlanApproval
     action data.
   - Call SASE's existing `kill_named_agent` helper for that agent, using the same lifecycle path as `/kill` and TUI
     kill actions.
   - Treat missing agent metadata or already-stopped agents as non-fatal after the response file is written; Telegram
     should still acknowledge the reject.

3. Make the side effect testable without Telegram network calls:
   - Factor the post-response handling in `sase_tg_inbound` so plan reject can invoke the kill helper through a small
     local function.
   - Add focused tests that assert `plan:<prefix>:reject` writes the reject JSON, removes the keyboard/pending action,
     and calls `kill_named_agent` with the pending action's `agent_name`.
   - Add negative coverage that approvals and feedback do not call the kill helper.

4. Verify in the `sase-telegram` sibling workspace:
   - Run the focused inbound/formatting tests around plan callbacks.
   - Run the repo's standard check target if available.

5. Report the diagnosis with the concrete live evidence:
   - Notification id, response directory state, still-running agent PID, and the code-phase artifacts that show the
     rejected plan proceeded.
