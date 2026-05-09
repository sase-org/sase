---
create_time: 2026-05-09 14:10:35
status: wip
prompt: sdd/prompts/202605/telegram_image_multi_model_workspace_claim.md
---
# Plan: Fix Telegram Image Multi-Model Workspace Claim Failures

## Problem

Telegram image prompts can wrap the user's caption in extra image-context text and still include a multi-model directive
such as `%model(opus,sonnet)` or repeated `%model:` directives. When that prompt is launched through SASE and a single
prompt segment fans out into multiple model slots, every slot should get an independent workspace claim.

The failure mode reported is that the first model agent starts, while later model agents fail because they cannot claim
the workspace. The relevant shared path is:

- `src/sase/agent/launch_cwd.py` dispatches prompts into the shared launcher.
- `src/sase/agent/multi_prompt_launcher.py` expands per-segment fan-out via `plan_prompt_fanout_variants()`.
- `_resolve_segment_vcs_context()` can return a preallocated VCS workspace (`workspace_num`, `workspace_dir`) for a
  segment containing a VCS ref.
- `execute_launch_plan()` then treats `use_preallocated_workspace=True` as a fixed workspace and does not retry or
  allocate per slot.

The root cause is that `multi_prompt_launcher` currently resolves the VCS workspace once per fan-out slot before any
slot is spawned, but the project file has not yet been updated with the first claim. If all slot contexts are resolved
up front, multiple model slots can observe the same first available workspace and then race against their own launch
batch. The first claim succeeds; later claims for that same workspace fail.

## Intended Behavior

For any prompt fan-out inside a multi-prompt segment:

- Each model/alt slot that targets a workspace-managed VCS ref gets a distinct workspace.
- The first successful launch claim is visible before the next slot chooses its workspace.
- Existing behaviors for home mode, `%wait` deferred workspaces, `#cd`, local xprompts, planned names, and timestamp
  batching remain unchanged.

## Implementation Approach

1. Add a focused regression test in `tests/test_multi_prompt_launcher_xprompts_models.py`.
   - Use a segment with an image-style preamble, a VCS ref, and `%model(opus,sonnet)`.
   - Mock `_resolve_segment_vcs_context()` or lower-level workspace resolution so both model slots would reuse the same
     workspace under the current eager-resolution behavior.
   - Simulate `spawn_agent_subprocess` rejecting a duplicate workspace claim.
   - Assert the fixed code launches both slots with distinct workspace numbers.

2. Change `src/sase/agent/multi_prompt_launcher.py` so workspace resolution for fan-out slots is lazy per slot instead
   of eagerly building all `LaunchExecutionContext` objects before `execute_launch_plan()`.
   - Preserve eager work that is safe and slot-local, such as planned names, local xprompt file serialization, and env
     construction.
   - Move `_resolve_segment_vcs_context()` into the `slot_context` callback so `execute_launch_plan()` resolves slot N's
     workspace immediately before spawning slot N.
   - This lets the previous slot's `claim_workspace()` write be visible before the next slot asks for the first
     available workspace.

3. Keep retry semantics intact.
   - If a slot context is dynamically allocated rather than preallocated, existing `_spawn_slot_with_workspace_retry()`
     behavior should continue to retry on claim collisions.
   - If a VCS resolver returns a concrete preallocated workspace, the lazy callback should make those concrete
     workspaces distinct in normal sequential launch.

4. Check whether the Telegram plugin still has redundant pre-splitting.
   - The immediate shared-launcher fix belongs in this repo because mobile/Telegram, TUI, and CLI fan-out all use this
     code path.
   - If plugin tests reveal an additional Telegram-only issue, make a minimal follow-up change in `../sase-telegram` and
     run that repo's `just check` as required by the external repo memory.

5. Verification.
   - Run the new targeted test.
   - Run existing multi-prompt/model launch tests.
   - Run `just check` in this repo after code changes, per repo instructions.
