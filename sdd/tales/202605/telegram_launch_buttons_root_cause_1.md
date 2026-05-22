---
create_time: 2026-05-22 11:22:33
status: done
prompt: sdd/prompts/202605/telegram_launch_buttons_root_cause_1.md
---
# Plan: Eliminate the Telegram Launch Button Race by Returning the Agent Name From the Launcher

## Problem

After the previous fix (commit `709bfacf1`, which moved `agent_meta.json` publication ahead of
`prepare_workspace_if_needed()`), Telegram launch confirmation messages still come back without inline keyboard buttons.
The most recent example is agent `a0v`, launched at 10:56:23 EDT on 2026-05-22 via Telegram. The on-disk
`agent_meta.json` for that run (`~/.sase/projects/sase/artifacts/ace-run/20260522105619/agent_meta.json`) contains
`"name": "a0v"`, yet the Telegram message attached to that launch had no Resume/Wait/Kill/Retry buttons.

The Telegram chop run log shows a `Tick overrun: took 7.0s but interval is 5s` warning aligned with the launch tick, so
the inbound chop did spend the full notification window working.

## Why the Previous Fix Was Not Enough

The previous fix tightened ordering inside the child runner so workspace cloning could not block metadata publication.
That removed the slowest single step from the critical path, but it did not change _who_ owns name allocation: the child
is still the first place a name is claimed.

Concretely, for a Telegram-initiated launch the order of events that must complete before the file exists with a name is
still:

1. Parent (sase-telegram) calls `launch_agents_from_cwd()` and returns an `AgentLaunchResult` (no name field).
2. The Rust FFI spawns a detached Python child running `run_agent_runner.py`.
3. The child cold-starts Python and imports the entire `sase.axe.run_agent_runner` graph (heavy: xprompt, agent name
   registry, telemetry, llm provider registry, etc.).
4. The child runs `init_telemetry`, `setup_artifacts_directory`, `preprocess_prompt_xprompts`, `apply_dynamic_memory`,
   then enters `extract_directives_and_write_meta`.
5. Inside `extract_directives_and_write_meta` it expands xprompts a second time (for directive discovery), parses
   directives, resolves the LLM/VCS providers, takes the global agent-name allocation lock, calls `get_next_auto_name`,
   `claim_agent_name`, and finally `write_agent_meta`.
6. The parent (Telegram) starts polling `agent_meta.json` for the `name` field via `_resolve_launch_result_agent_name`
   with a 3.0 s deadline (`sase_tg_inbound.py:828-853`).

Steps 3–5 together can comfortably exceed 3 seconds on a cold subprocess, especially when the launch prompt includes a
non-trivial xprompt such as `#gh:sase`. When that happens, the Telegram poller returns `None`,
`_send_launch_notification` falls through the `if agent_name:` branch, and the message is sent with `reply_markup=None`.
The same path also drops the `_@<agent>_` line, matching the user's screenshot from the earlier tale.

The 3.0 s window is fundamentally a guess about how fast a cold Python subprocess can do all of the above. Even if we
bump it, the race remains: a slow disk, contention on the agent-name file lock, or any future addition to the
pre-extract path can blow past any timeout we pick. The race is structural.

## Approach

Move agent-name allocation up into the parent process so the name is known synchronously by the time
`launch_agents_from_cwd()` returns. The child still owns _final_ claiming and writes the durable `agent_meta.json`, but
when the parent has already chosen a name and shipped it through the existing `SASE_AGENT_PLANNED_NAME` env var, the
child treats that name as authoritative. The parent then returns the name on `AgentLaunchResult`, and Telegram reads it
directly with no polling.

This builds on infrastructure that already exists for multi-prompt fanout (`PlannedNameAllocator` /
`allocate_auto_names` / `SASE_AGENT_PLANNED_NAME`); the change is to extend it from the "next segment needs the previous
name" case to _all_ launches that go through the canonical launch pipeline.

Concrete pieces:

1. **Parent-side planning**: In the canonical launch pipeline (somewhere before `spawn_agent_subprocess` in
   `launch_spawn.py` / `multi_prompt_launcher.py`), compute a planned agent name for every slot. Reuse
   `extract_static_name_directive` for explicit `%name:` directives and `PlannedNameAllocator.planned_name_for_prompt`
   for auto-named slots. Bail to the existing child-side path only when the prompt is ambiguous (contains an unexpanded
   `#xprompt` that may itself supply a name) — the same condition `planned_name_for_prompt` already detects.

2. **Wire the planned name to the child**: The existing `SASE_AGENT_PLANNED_NAME` env var is already honored by
   `extract_directives_and_write_meta` (it is preferred over `get_next_auto_name` when no explicit directive is set).
   Make sure it is set in `extra_env` for every slot whose name was planned in step 1, not only fanout slots that the
   _next_ segment depends on. Keep the child-side `claim_agent_name` call as the durability boundary.

3. **Return the planned name on the launch result**: Add `agent_name: str | None = None` to `AgentLaunchResult` and
   populate it in `spawn_agent_subprocess` (and any equivalent paths) from the planned name computed in step 1. When the
   parent cannot plan (ambiguous prompt), leave it as `None` and current behavior holds.

4. **Telegram reads the name synchronously**: Update `_launch_agents_with_notifications` in
   `sase-telegram_11/src/sase_telegram/scripts/sase_tg_inbound.py` to prefer `result.agent_name` when present and skip
   the file poll entirely in that case. Keep `_resolve_launch_result_agent_name` as a fallback for ambiguous prompts so
   we do not regress when the parent cannot plan. Optionally raise its timeout modestly (e.g. 8–10 s) so that fallback
   path is also more forgiving.

5. **Name-claim semantics in the child**: Audit `claim_agent_name` so that if the planned name has already been reserved
   by `allocate_auto_names` in the parent, the child's claim does not double-count it or treat it as a collision. The
   current `_auto_reserved` tracking in `PlannedNameAllocator` reads `get_active_agent_names()` once per allocator, so a
   single auto name should be safe; verify with a test that two back-to-back single launches do not pick the same name.

6. **Tests**:
   - Unit test: `AgentLaunchResult.agent_name` is populated for a single-prompt launch whose prompt has no explicit name
     directive.
   - Unit test: For a prompt with `%name:foo`, the launch result carries `foo` and `SASE_AGENT_PLANNED_NAME=foo` is in
     the child env.
   - Unit test: For a prompt whose name is only resolvable after xprompt expansion (e.g. an xprompt that injects
     `%name:`), `agent_name` is `None` and child-side behavior is unchanged.
   - Telegram-side test: `_launch_agents_with_notifications` builds a button keyboard when `result.agent_name` is set,
     even when `agent_meta.json` has not yet been written.
   - Existing regression in `tests/test_axe_run_agent_runner_started_at.py` (metadata before workspace prep) must remain
     green.

7. **Telemetry / fallbacks**: Add a single log line when the Telegram fallback poller fires (i.e. `result.agent_name` is
   `None`) so we can spot any regression where planning silently stops working. Counter-style metric is not necessary; a
   structured log entry is enough.

## Out of Scope

- Changing where `agent_meta.json` lives or what fields it carries beyond `name`.
- Touching the deferred-workspace (`%wait`) or retry-spawn paths beyond what is required for the planned name to flow
  through unchanged. The previous tale already validated those, and this change layers on top of that ordering.
- Telegram-side keyboard layout or button semantics.

## Validation

- `just check` in `sase_11` (workspace clone). Must run `just install` first per workspace contract.
- `just check` in `sase-telegram_11` if the Telegram side is touched.
- Manual smoke: from a fresh Telegram message, launch a single agent with a `#gh:sase` prompt; confirm the returned
  message has the `_@<name>_` line and all four buttons. Repeat with an explicit `%name:foo` prompt; confirm the name in
  the notification matches the explicit directive.
- Inspect `~/.sase/projects/sase/artifacts/ace-run/<ts>/agent_meta.json` to confirm `name` matches the name shown in
  Telegram (i.e. parent and child agree).
