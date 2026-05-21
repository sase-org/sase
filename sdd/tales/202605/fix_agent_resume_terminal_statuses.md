---
create_time: 2026-05-21 12:35:31
status: done
prompt: sdd/prompts/202605/fix_agent_resume_terminal_statuses.md
---
# Plan: Fix ACE Agent Resume for Terminal Plan-Chain Statuses

## Problem

Pressing the `r` key on an agent row with status `TALE DONE` reports `Agent not finished yet`. The selected snapshot row
is a completed plan-chain/tale row, but the Agents tab resume action only treats plain `DONE` as a finished status after
a narrow coder-followup redirect branch.

## Root Cause

ACE has multiple completion predicates that disagree:

- `DISMISSABLE_STATUSES` treats `PLAN DONE` and `TALE DONE` as terminal/completed.
- Agent grouping and unread navigation also treat those statuses as done.
- `AgentWaitResumeMixin.action_resume_agent()` only resumes plain `DONE`, except for a non-root plan-handoff child that
  can be redirected to a coder follow-up.
- The footer and command palette expose `run_workflow`/`r` resume only for `DONE` rows with `response_path`, so
  discoverability can diverge from what the action should support.

For a focused family/root row like the snapshot's `@aww`, the code skips the handoff branch because it is the family
root, then falls through to `agent.status != "DONE"` and emits the misleading warning.

## Design

Use one explicit TUI-level predicate for "resumable terminal chat" instead of scattering plain `DONE` checks in action,
footer, and command palette code.

The predicate should:

- Allow normal `DONE` agents.
- Allow post-plan terminal handoff statuses `PLAN DONE` and `TALE DONE`.
- Preserve existing exclusions for `FAILED`, `PLAN REJECTED`, `PLAN COMMITTED`, and `EPIC CREATED`, because those are
  terminal for cleanup but not necessarily resumable chat continuations.
- Continue supporting active named agents by opening `#resume:<name> %w:<name>`.
- Continue preferring a coder follow-up when a selected non-root plan-chain row has one.

## Implementation Steps

1. Add small private helpers in `src/sase/ace/tui/actions/agents/_wait_resume.py`:
   - `_RESUMABLE_DONE_STATUSES = {"DONE", "PLAN DONE", "TALE DONE"}`
   - `_agent_resume_name(agent)` if needed to keep target-name resolution readable.
2. Update `action_resume_agent()` so `PLAN DONE` and `TALE DONE` rows can open a `#resume:<name>` prompt instead of
   warning.
3. Keep the existing coder-followup redirect for non-root plan-handoff rows, but make the fallback path handle family
   roots cleanly via `_agent_prompt_name()`.
4. Update `KeybindingFooter._compute_agent_bindings()` so `r resume` appears for resumable terminal statuses when a
   response/chat path exists, matching the existing `DONE` rule.
5. Update command palette availability so `app.run_workflow` is available for the same resumable terminal statuses.
6. Add focused tests for:
   - family/root `TALE DONE` resumes with the family name;
   - `PLAN DONE` resumes with the family name;
   - footer advertises `r resume` for `TALE DONE`;
   - command availability allows `run_workflow` for `TALE DONE` with a response path and still blocks it without a
     response path.
7. Run targeted pytest for the changed behavior, then run `just install` if needed followed by `just check` per repo
   instructions.

## Expected Outcome

On the snapshot row, pressing `r` should open the prompt bar with a resume prefix, e.g. `#resume:aww `, rather than
warning that the completed tale agent is unfinished. Footer and command palette availability should agree with the
action.
