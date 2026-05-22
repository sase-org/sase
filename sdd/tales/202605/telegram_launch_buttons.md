---
create_time: 2026-05-22 10:46:09
status: done
prompt: sdd/prompts/202605/telegram_launch_buttons.md
---
# Plan: Restore Telegram Launch Buttons

## Problem

Telegram launch confirmation messages are delivered, but their inline keyboard buttons are missing. The launch
notification builder only attaches Resume, Wait, Kill, and Retry buttons when it has an agent name. The screenshot's
launch message also lacks the `_@agent-name_` line, confirming that Telegram sent the message before it could resolve
the spawned agent's name.

Current Telegram code deliberately avoids preallocating names itself. It calls the canonical `launch_agents_from_cwd()`
path, derives the launch artifact directory from the result, then polls `agent_meta.json` for the actual claimed name.
That is the right ownership boundary, but the runner writes `agent_meta.json` only after it completes workspace
preparation. For VCS-backed launches, workspace preparation can take longer than Telegram's short polling window, so
Telegram sends an unnamed launch message and intentionally omits buttons.

## Approach

Move generic runner metadata publication earlier in the child agent lifecycle:

1. Keep the canonical launcher as the owner of workspace allocation and keep the child runner as the owner of final
   agent name claiming.
2. In `run_agent_runner`, change the pre-execution order so the child enters its already-created workspace, applies
   dynamic memory, extracts directives, claims the agent name, and writes `agent_meta.json` before running normal
   workspace preparation.
3. Preserve the existing deferred-workspace behavior: `%wait` launches should still publish placeholder metadata before
   waiting, then refresh workspace metadata after the real workspace is claimed.
4. Preserve retry-spawn behavior: retry children should still record retry ancestry after initial metadata exists and
   continue to skip workspace preparation when preserving the parent's edits.
5. Add regression coverage that proves `agent_meta.json` is written before `prepare_workspace_if_needed()` runs, so
   launch surfaces can resolve the name while workspace preparation is still in progress.
6. Keep Telegram-side button construction unchanged except for tests if needed: it should continue using the actual
   claimed name from `agent_meta.json`.

## Validation

- Run focused runner tests covering the new ordering.
- Run focused Telegram tests around launch notifications/name resolution if touched.
- Because this changes the primary `sase` repo, run `just install` and `just check` there before finishing.
- If the Telegram sibling repo is changed, run its `just check` as well.
