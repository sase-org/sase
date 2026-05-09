---
create_time: 2026-05-09 14:13:29
status: done
prompt: sdd/prompts/202605/telegram_multi_model_workspace_claim.md
---
# Plan: Fix Telegram multi-model workspace-claim failures by delegating to the canonical fan-out path

## Problem

When a Telegram message (especially an image with caption) contains a multi-model directive — e.g. `%m(opus,sonnet)` or
`%model(opus,sonnet)` — the first agent launches successfully but every subsequent agent fails with:

```
Failed to launch agent: Failed to claim an available workspace for <project> after <N> attempts;
axe workspaces may all be claimed or racing with other launches.
```

Reproduction: send a Telegram photo with caption like `%m(opus,sonnet) describe this image`. Agent 1 (opus) is spawned
and registers a Telegram launch message; agent 2 (sonnet) returns the workspace-claim error.

This is the same family of TOCTOU between `get_first_available_axe_workspace()` and `claim_workspace()` documented in
`sdd/tales/202605/axe_run_every_workspace_claims.md` and `sdd/tales/202605/workspace_allocation_retry.md` — but in a
path the prior fixes never covered.

## Root cause

The Telegram inbound script duplicates multi-model fan-out logic that already exists in the canonical sase launch
pipeline, and the duplicate path bypasses the batched workspace-allocation retries.

In `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py`:

- `_launch_agent` (~L663) calls `split_prompt_for_models(expanded)`. If multi-model directives are found, it dispatches
  to `_launch_multi_model_agents(model_prompts)` (~L841) and returns before the canonical pipeline gets the prompt.
- `_launch_multi_model_agents` is a sequential loop:
  ```python
  for i, model_prompt in enumerate(model_prompts):
      if i > 0:
          time.sleep(1)
      _launch_single_agent(model_prompt)
  ```
- Each call invokes `launch_agent_from_cwd(prompt)` independently. Each invocation re-enters the full pipeline,
  including alt-split detection in `src/sase/agent/launch_cwd.py` and `execute_launch_plan` workspace allocation in
  `src/sase/agent/launch_executor.py`.

Two design problems compound here:

1. **The canonical `launch_agents_from_cwd` already supports multi-model fan-out.** `launch_cwd.py:251` calls
   `plan_prompt_fanout_variants(query)` and dispatches the entire fan-out to `launch_multi_prompt_agents`, which spawns
   each slot through one shared `execute_launch_plan` invocation. That path uses a single timestamp allocator, batches
   name resolution through `apply_fanout_naming`, and serializes per-slot workspace allocation through one consistent
   retry budget. Telegram's pre-split short-circuits this — every model becomes its _own_ `launch_agent_from_cwd` call,
   with no shared coordination and no batched retry budget.

2. **A 1-second sleep is not a workspace-allocation barrier.** `launch_agent_from_cwd` returns once
   `spawn_agent_subprocess` returns, and `claim_workspace` runs as a synchronous claim callback inside
   `spawn_prepared_agent_process`, so in the happy path a sequential second call should observe agent 1's claim. In
   practice it does not — likely because of one or more of:
   - Naming/auto-name allocation collisions when each model goes through `_launch_single_agent` independently and
     `apply_fanout_naming` is re-run on a single-slot plan with different inputs across calls.
   - Project-context resolution shifting per-call in `ensure_project_file_and_get_workspace_num` (e.g. CWD-relative
     resolution returning a different `project_file` for the second call than for the first), so the second call's
     `claim_workspace` writes against a project file where workspace 100 still looks free, then races with the first
     agent's child claim.
   - `_should_retry_workspace_claim` returning `False` for the second call because some context flag (`is_home_mode`,
     `use_preallocated_workspace`, `deferred_workspace`) ends up set differently, exhausting retries on the first
     failure.

We do not need to enumerate the exact race to fix the bug — the design is wrong. The duplicate path is unnecessary
because the canonical pipeline already handles multi-model fan-out correctly and is the path covered by the existing
workspace-allocation retry tests.

## Goal

Eliminate the duplicate multi-model dispatch in the Telegram inbound script. Route multi-model launches through the
canonical `launch_agents_from_cwd` plural API so workspace allocation, naming, and retries are handled by the same code
that drives every other multi-model launch surface.

The fix should:

- Stop the recurring "unable to claim workspace" failure for Telegram multi-model prompts (image and text alike).
- Preserve the per-agent Telegram launch notifications, including kill / retry / resume / wait inline buttons and
  `pending_actions` registration.
- Keep single-model and single-agent launches unchanged.
- Keep `%r:N` repeat fan-out unchanged (already handled by the canonical pipeline).

## Proposed design

Replace the multi-model interception with a single "launch one or many" entry point that always goes through
`launch_agents_from_cwd` (plural).

1. **Drop `_launch_multi_model_agents` and the multi-model branch in `_launch_agent`.**

   `_launch_agent` becomes a thin wrapper that:
   - Normalizes the prompt as today (`normalize_launch_xprompt_at_refs`).
   - Calls a new `_launch_agents_with_notifications(prompt)` helper that always uses `launch_agents_from_cwd` and emits
     one Telegram notification per spawned `AgentLaunchResult`.

2. **Refactor `_launch_single_agent` into `_launch_agents_with_notifications`.**

   The function should:
   - Expand xprompts once (as today) for directive inspection.
   - Run `extract_prompt_directives` on the expanded prompt to learn whether the user supplied `%name`, `%r`, `%model`,
     etc.
   - Auto-assign a `%n:<auto>` only when there is no explicit name AND the prompt is not a repeat AND the prompt does
     not contain a multi-model fan-out directive (since `apply_fanout_naming` will assign per-slot names with a shared
     base).
   - Resolve a label/provider for the **single-agent** case eagerly (current code uses `directives.model` to build a
     `format_provider_model_label`). For the multi-model case, defer label resolution to per-result post-processing
     using each result's `prompt`/workflow data.
   - Call `launch_agents_from_cwd(prompt)` and iterate over the returned `list[AgentLaunchResult]` (length 1 for
     single-agent, length N for multi-model and `%alt(...)`).
   - For each result, build the Telegram notification (label, name, workspace #, inline keyboard, `pending_actions`
     entry) using that result's `cl_name`, `workspace_num`, and the prompt that was actually dispatched. The prompt for
     each slot is recoverable either from the result's metadata or by re-running `plan_prompt_fanout_variants` on the
     original prompt and zipping with results.

3. **Send notifications after agents are spawned, not before.**

   The current `_launch_single_agent` builds the notification text from the _input_ `prompt`. For multi-model, the
   per-slot prompts differ (each carries its own `%model:X` and `%name:base.suffix`). Build the notification from the
   per-result data so each agent's message reflects the model it was launched with. The display-prompt portion can use
   either the per-slot prompt (preferred for transparency) or the original user-typed prompt (current behavior). Choose
   the per-slot prompt to mirror what the canonical TUI launch surface shows.

4. **Keep the original-prompt copy text for retry buttons.**

   Today the retry button copies the _original_ user prompt. Preserve that. Pass `original_prompt` (the full user prompt
   with `%m(...)`) through to each per-slot notification so a single Retry click re-launches the whole fan-out, which is
   the natural user expectation.

5. **Project context recording stays once per message.**

   `_record_project_context` is called once in `_handle_photo_message` / `_handle_text_message`. Do not move it inside
   the per-slot loop — the multi-model fan-out shares one user message and one project context.

## Files affected

- `sase-telegram/src/sase_telegram/scripts/sase_tg_inbound.py`
  - `_launch_agent` simplified.
  - `_launch_single_agent` replaced by `_launch_agents_with_notifications` (or refactored in place).
  - `_launch_multi_model_agents` deleted.
  - Imports: drop `split_prompt_for_models` from `_launch_agent`; the canonical pipeline owns it. Add
    `launch_agents_from_cwd` (plural) import in place of `launch_agent_from_cwd`.

No changes are needed in the sase repo (`sase_101`) — the canonical launch pipeline already supports the fan-out we are
delegating to. This makes the fix a pure cross-repo cleanup.

## Tests

In `sase-telegram/tests/test_inbound.py`:

1. **Multi-model text launch via `_launch_agent("%m(opus,sonnet) Do work")`** — assert `launch_agents_from_cwd` is
   called once with the original prompt, that two Telegram launch messages are sent, and that two `pending_actions`
   entries are registered with distinct agent names (e.g. `<auto>.cld-opus`, `<auto>.cld-sonnet`).
2. **Multi-model photo launch via `_handle_photo_message`** — same assertions, plus that `_record_project_context` runs
   exactly once and the photo file is referenced by the prompt passed to `launch_agents_from_cwd`.
3. **Single-model and single-agent launches** still call `launch_agents_from_cwd` and produce exactly one notification —
   regression coverage for the unification.
4. **Workspace claim robustness** — mock `launch_agents_from_cwd` to return two `AgentLaunchResult`s with workspace
   numbers 100 and 101 and assert both notifications carry the correct workspace numbers (catches the regression where
   the second slot's notification was lost or used a wrong workspace).

In `sase_101`, no new tests are required, but extend `tests/test_multi_prompt_launcher_xprompts_models.py` with a
"multi-model fan-out from a bare prompt (no `---` segments)" case if that scenario is not already covered by
`test_launch_multi_prompt_with_multi_model_segment`. This guards against a future regression where a Telegram-style
single-segment multi-model prompt stops dispatching through `launch_multi_prompt_agents`.

## Validation

After the cross-repo edits:

```bash
# In sase-telegram
cd ~/projects/github/sase-org/sase-telegram
just check  # or repo's standard test command

# In sase_101 (sanity)
cd ~/projects/github/sase-org/sase_101
just install
just check
```

Manual smoke test on the user's Telegram bot:

- Send a photo with caption `%m(opus,sonnet) describe this`. Both agents should launch, each with its own Telegram
  notification carrying the correct model label and a unique workspace #.
- Send a text prompt `%m(opus,sonnet) hello`. Same expectation.
- Send a single-model prompt `%m:opus hello` and a bare prompt `hello`. Each should launch exactly one agent — no
  regression.

## Non-goals

- Not redesigning workspace allocation. The canonical pipeline already retries and surfaces clear exhaustion errors per
  `sdd/tales/202605/workspace_allocation_retry.md`; we just stop bypassing it.
- Not changing how `apply_fanout_naming` constructs `<base>.<runtime>-<model>` suffixes. Whatever the canonical pipeline
  produces is what Telegram should report.
- Not adding cross-process workspace-claim coordination. Telegram inbound is a single process; the bug is purely a
  duplicate-path issue.
