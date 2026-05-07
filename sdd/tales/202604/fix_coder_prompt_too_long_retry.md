---
create_time: 2026-04-22 14:57:44
status: done
prompt: sdd/prompts/202604/fix_coder_prompt_too_long_retry.md
---

# Plan: Fix "Prompt is too long" Retry Failing for Coder Agents

## Problem

`sase ace` coder agents using the Claude backend still crash with `"Prompt is too long"` instead of auto-recovering,
even though commit `cbb98af7` ("feat: auto-recover claude agents from 'Prompt is too long' via built-in retry") was
supposed to handle this.

### Observed Incident

Agent `@f.plan` (a multi-step plan/code agent) failed with:

```
WorkflowExecutionError: Step 'main' failed: Error running LLM provider command (exit code 1)
stderr: [result] Prompt is too long
```

Timestamps:

- `BEGIN` 14:26:19
- `PLAN` 14:32:53 ← plan phase completed successfully
- `CODE` 14:37:36 ← coder spawned
- `END` 14:46:16 ← coder crashed ~9 minutes in, after many file reads / edits / test runs

No retry fired, despite the built-in `claude` retry config being set to `max_retries=3` with
`error_patterns=["Prompt is too long"]`.

## Root Cause — Two Intersecting Bugs

### Bug 1 — `state.allow_retry = False` blocks retries after phase transitions

`src/sase/axe/run_agent_exec_plan.py` sets `state.allow_retry = False` in three places after a phase transition writes a
new prompt into `state.current_prompt`:

| Line | Path                                   | When it fires                            |
| ---- | -------------------------------------- | ---------------------------------------- |
| 261  | `handle_plan_marker` → feedback branch | User requested plan changes via feedback |
| 417  | `handle_plan_marker` → approve branch  | User approved plan; coder prompt set     |
| 500  | `handle_questions_marker`              | User answered questions; Q&A appended    |

Then `src/sase/axe/run_agent_exec_retry.py:74` short-circuits:

```python
if not (state.allow_retry and active_retry_cfg):
    return "raise"
```

When the coder (or any post-phase-transition step) hits `"Prompt is too long"`, `handle_workflow_error` immediately
raises without consulting the retry config. The built-in retry silently no-ops for the exact workflow it was designed to
recover.

The pre-refactor code (commit `a93bb8c8`) had a now-revealing comment:
`_allow_retry = True  # Only retry initial execute_workflow calls`. That design dates to when retries were solely for
rate-limit / overload errors, which the original author felt were only safe to retry on the initial (pre-work) planner
call. The `cbb98af7` context-overflow work added the built-in retry on top of the existing machinery but did not revisit
these assignments — so the primary use case (a coder hitting the window limit partway through implementation) is
unreachable.

### Bug 2 — `prepare_workspace` in the retry handler wipes the coder's on-disk work

Even flipping `allow_retry` unblocks the retry path, `handle_workflow_error` calls `prepare_workspace` on every retry
(`run_agent_exec_retry.py:118-125` retry, `:147-154` fallback). `prepare_workspace` calls `run_sase_hg_clean` →
`provider.stash_and_clean`, which **stashes + cleans** the working tree. A retried coder would start against an empty
tree — directly contradicting the continuation nudge (`_CONTEXT_OVERFLOW_NUDGE` at `retry_config.py:86`) that tells the
fresh session:

> "Your file edits, new tests, and other on-disk changes you made are preserved. Before making additional changes, run
> `git status` and `git diff` to see what is already in place…"

`prepare_workspace` is already called once at startup (`run_agent_runner.py:187-197`) before the loop ever runs. The
in-loop repeat was defensible when retries only fired before the agent had done any work; for context-overflow retries
it is actively destructive.

## Key Insight

The two bugs are coupled. Fixing Bug 1 alone (letting retries fire post-plan-approval) exposes Bug 2 (the workspace gets
wiped and the continuation nudge lies to the coder about preserved edits). Fixing Bug 2 alone has no effect because the
retry never runs in the first place. Both must land together.

## Proposed Fix

Single PR, two focused commits.

### Commit 1 — Let retries fire across phase transitions

Remove the three `state.allow_retry = False` assignments in `src/sase/axe/run_agent_exec_plan.py`. With them gone, the
`allow_retry` field on `LoopState` is never set to anything but its default `True` and is therefore dead; remove:

- `LoopState.allow_retry` field in `src/sase/axe/run_agent_exec.py` (~line 81).
- The `state.allow_retry and` clause in the guard at `src/sase/axe/run_agent_exec_retry.py:74`. The remaining check
  (`if not active_retry_cfg: return "raise"`) correctly handles "no retry config available for this error."

Runaway-loop protection remains sound:

- `max_retries` on each `ProviderRetryConfig` caps retries per agent run.
- The retry budget is shared across phases (planner eats 2 retries → coder only has 1 left). That's the right trade-off:
  if the planner needed 2 restarts to fit the window, the plan itself is likely oversized and giving the coder more
  budget would only paper over the deeper issue.

### Commit 2 — Preserve workspace on retries that opt in

Add `preserve_workspace: bool = False` to `ProviderRetryConfig` in `src/sase/llm_provider/retry_config.py`. Default
`False` so existing user configs (rate-limit retries) see zero behavior change. Set `preserve_workspace=True` in the
built-in `claude` entry (alongside `continuation_prompt=_CONTEXT_OVERFLOW_NUDGE`), since "preserve on-disk work" and
"prepend the continuation nudge" always go together for context-overflow retries.

Thread the new field through the three merge helpers (`_clone_config`, `_config_from_user_dict`, `_merge_with_built_in`)
so user configs can override.

In `src/sase/axe/run_agent_exec_retry.py` wrap the two `prepare_workspace` calls:

```python
if ctx.update_target and not ctx.is_home_mode and not active_retry_cfg.preserve_workspace:
    prepare_workspace(...)
```

Apply in both the retry path (~line 118) and the fallback path (~line 147) so fallback-model retries also respect the
setting.

### Why per-config opt-in rather than always-preserve

Rate-limit retries (the original use case) run on transient errors where the previous session may have partially applied
changes that are inconsistent in ways the agent didn't observe — wiping is a defensible default. Context- overflow
retries run on sessions that completed substantial coherent work up to the window limit — preserving is defensible.
Different policies; per-config flag is the cleanest encoding.

Changing rate-limit retries to also preserve work is plausibly desirable but is a behavior change for existing users and
should be discussed separately.

## Test Coverage

Add to `tests/test_llm_provider_retry_config.py`:

- Built-in `claude` config has `preserve_workspace=True`.
- `_merge_with_built_in` preserves `preserve_workspace=True` from built-in when user config omits it.
- User explicit `preserve_workspace=False` overrides the built-in (key-presence check, consistent with existing
  `max_retries` / `continuation_prompt` override semantics).
- `_clone_config` copies the field defensively.

Add to `tests/test_axe_run_agent_exec_retry.py`:

- `handle_workflow_error` with `preserve_workspace=True` does NOT call `prepare_workspace` during retry.
- `handle_workflow_error` with `preserve_workspace=True` does NOT call `prepare_workspace` during fallback.
- `handle_workflow_error` with `preserve_workspace=False` (default) STILL calls `prepare_workspace` — no regression.
- Remove the now-irrelevant check of `state.allow_retry` if any existing test asserts it.
- New test: retry fires successfully when `LoopState` is in its post-phase-transition shape (specifically, simulate a
  post-approval state — `agent_step=2`, a coder-style `current_prompt` — and verify retry proceeds).

Existing tests that pass `_make_state()` (default `allow_retry=True`) keep passing unchanged; removal of the field
requires no test updates beyond those calls.

Integration-level: the existing zero-wait built-in retry test (`test_prepends_nudge_on_zero_wait_retry`) already covers
the happy path; update it to assert `prepare_workspace` is not invoked under the built-in `claude` config.

## Non-Goals / Out of Scope

- **Token-usage monitoring / proactive warnings.** Already deferred by
  `plans/202604/prompt_too_long_checkpoint_restart.md`.
- **Changing rate-limit retries to also preserve workspace.** Conservative default; revisit in a separate thread.
- **New `"resumed_context_overflow"` `RetryStatus` literal.** Nice-to-have TUI label distinction; not load-bearing.
- **external provider / Gemini / Codex context-overflow patterns.** Original plan noted these as speculative and out of scope;
  handle when each provider's exact error string is confirmed.
- **`state.allow_retry` as a general kill-switch.** If a future scenario genuinely needs to suppress retries
  selectively, re-introduce it scoped to that scenario; don't keep a dead field "just in case."

## Files Expected to Change

- `src/sase/axe/run_agent_exec_plan.py` — remove three `state.allow_retry = False` lines
- `src/sase/axe/run_agent_exec.py` — remove `allow_retry: bool = True` from `LoopState`
- `src/sase/axe/run_agent_exec_retry.py` — drop `allow_retry` guard; gate both `prepare_workspace` calls on
  `not active_retry_cfg.preserve_workspace`
- `src/sase/llm_provider/retry_config.py` — add `preserve_workspace` field to `ProviderRetryConfig`; set `True` in
  built-in `claude`; thread through `_clone_config` / `_config_from_user_dict` / `_merge_with_built_in`
- `tests/test_axe_run_agent_exec_retry.py` — new tests for preserve-workspace gating and post-phase retry
- `tests/test_llm_provider_retry_config.py` — new tests for `preserve_workspace` merge semantics

## Validation

- `just check` must pass (lint + type + tests).
- Manual verification: construct a `LoopState` representing a post-approval coder (non-empty `current_prompt`,
  `agent_step=2`, `current_role_suffix=".code"`), patch `execute_workflow` to raise
  `WorkflowExecutionError("Step 'main' failed: ... Prompt is too long")` on first call and return success on second,
  assert the second call sees the continuation nudge prepended and that no file in the fake workspace was touched by
  `prepare_workspace`.
- Regression sanity: existing rate-limit retry tests must still pass. The `preserve_workspace=False` default keeps those
  paths identical.

## Sequencing

Two commits in one PR:

1. **Commit 1 — `allow_retry` removal.** Delete the three assignments, the field, and the guard. Tests that assert the
   guard are updated; new tests covering post-phase retry are added.
2. **Commit 2 — `preserve_workspace` field + built-in.** Schema change, merge logic, retry-handler gate, and tests.

Each commit is individually runnable but the pair is the shippable unit — Commit 1 alone exposes Bug 2 for coders with
`update_target` set.
