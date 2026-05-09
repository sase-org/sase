---
create_time: 2026-05-09 15:12:38
status: wip
prompt: sdd/prompts/202605/telegram_auto_name_race.md
---
# Telegram Auto Name Race Plan

## Problem

Telegram inbound launches auto-assign an agent name by calling `get_next_auto_name()` and prepending `%n:<name>` before
calling `launch_agents_from_cwd()`. That turns an internally generated name into an explicit launch request. The
explicit name is then validated by the core launcher before the child agent has claimed the name, leaving a race where
another agent can reserve the same auto name first. The screenshot failure, `Agent name 'cp' is taken. Try 'cp1'.`,
matches that path.

## Goals

- Remove Telegram's pre-launch auto-name reservation path for ordinary prompts.
- Let the core agent runner assign and claim auto names under its existing allocation lock.
- Preserve Telegram launch notifications, resume/wait/kill/retry buttons, and multi-model notifications.
- Add regression coverage for the race-prone call shape so future changes do not reintroduce `get_next_auto_name()` in
  the Telegram pre-launch path.

## Approach

1. Update `sase-telegram` inbound launch logic so a prompt without `%name` is passed to `launch_agents_from_cwd()`
   without a prepended `%n:<auto>` directive, except for user-supplied names that should pass through unchanged.
2. After launch, resolve the actual spawned agent name from the result's artifact directory by polling `agent_meta.json`
   briefly. Fall back to existing directive-derived names when the metadata is not available yet.
3. Feed the resolved actual names into Telegram notification formatting so the visible `@name` and copy buttons still
   work for single-agent launches and fan-out slots.
4. Keep repeat prompts unchanged; repeat naming is already owned by core repeat fan-out.
5. Add tests proving Telegram no longer calls `get_next_auto_name()` or prepends `%n:<auto>` for unnamed prompts, and
   that notifications can use a name read from `agent_meta.json`.
6. Run the plugin repo checks. If core SASE files are touched, run the SASE repo `just install` and `just check` too.

## Validation

- Targeted pytest coverage in `sase-telegram`.
- `just check` in `../sase-telegram`.
