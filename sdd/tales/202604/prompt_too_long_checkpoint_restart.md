---
create_time: 2026-04-21 19:09:06
status: done
prompt: sdd/prompts/202604/prompt_too_long_checkpoint_restart.md
---

# Plan: Auto-Recover Coder Agents from "Prompt is too long" via Checkpoint-Restart

## Problem

Coder agents run via `sase ace` under the Claude Code backend reliably hit Claude's `"Prompt is too long"` error partway
through multi-file implementation tasks, terminating the agent before the work is finished.

Incident that motivates this plan (2026-04-21, ~18:48):

- Coder was implementing `plans/202604/fast_dismiss.md` (220 lines, 12.7 KB).
- It successfully applied Fix 1, Fix 2, and Fix 3, wrote tests, and ran `just test` twice (the second run showed
  `All 31 tests pass`).
- The very next turn — "Let me run `just check`" — terminated with `Prompt is too long`. The agent is gone; the user has
  to manually pick up the remaining verification work.

This is the second recurrence of this class of failure in ~48 hours. `plans/202604/drop_coder_resume_prefix.md` (merged
2026-04-19, commit `d38b9a01`) removed the biggest contributor — the `#resume:<planner>` prefix that inlined the
planner's full chat into the coder's opening prompt — but the underlying window-exhaustion risk is structural and will
keep recurring on any plan whose coder work happens to cross the 200K boundary.

## Root Cause

`claude -p` runs the coder's entire implementation inside **one** Claude Code session
(`src/sase/llm_provider/claude.py:100-155`, fresh `--session-id` per `invoke()`, no cross-invocation session
continuity). Within that session, Claude Code runs its own internal agent loop: thinking blocks, tool calls, and tool
results all accumulate into Claude's context window. When cumulative input exceeds ~200K tokens, the Anthropic API
rejects the next turn with `"Prompt is too long"`, Claude Code exits non-zero, and sase raises
`subprocess.CalledProcessError`.

For the incident above, none of the _static_ prompt components are the culprit:

- `CLAUDE.md` → `AGENTS.md` + `memory/short/*.md` ≈ 7.7 KB total.
- Plan file ≈ 12.7 KB.
- Coder prompt scaffolding (`src/sase/axe/run_agent_exec_plan.py:410-415`) < 1 KB.
- `#resume:<planner>` already disabled by default (commit `d38b9a01`).
- `just check` already context-efficient via `tools/run_silent` (`Justfile:107-115`), so it contributes ~8 lines per run
  on success.

The bloat is **cumulative in-session context**: ~10-20 file reads (each injects the full file body), ~10-15 `Edit` calls
(each includes before/after), 2 verbose `just test` runs (per-test lines + coverage table), plus Grep/Glob results and
the model's own thinking. That total exceeds 200K after 40-60 minutes of coder work.

There is no in-process fix: once `claude -p` is running, sase cannot reach into its conversation to compact or prune.
Claude Code's own auto-compact (where it exists) must leave enough _non-compactable_ context to keep the current turn
under the limit — and on long coder sessions that non-compactable tail is itself the problem.

## Key Insight — Reuse the Existing Retry Infrastructure

sase already has a full retry-and-fallback pipeline at `src/sase/axe/run_agent_exec_retry.py` +
`src/sase/llm_provider/retry_config.py` (originally landed via `plans/202603/llm_retry_support.md` for rate-limit /
overload errors):

- Pattern-matched error recognition (`is_retryable_error`, case-insensitive substring match).
- Per-provider `max_retries`, `wait_times`, optional `fallback_model`.
- `RetryState` artifact (`retry_state.json`) surfaced in the TUI so the user sees "retrying 2/3 after <error>".
- Wired into the loop at `run_agent_exec.py:282`; on retry it re-enters the same agent step with the same
  `state.current_prompt` — i.e., **a fresh `claude -p` session re-running the same coder prompt**.

A fresh `claude -p` session with the same coder prompt is exactly the recovery we want for `"Prompt is too long"`: the
coder's on-disk progress (edited files, new test files, git index) is preserved across invocations, so a restarted coder
picks up naturally from whatever state the filesystem is in. The plan document is invariant, so there is nothing to
regenerate.

So the fix is not "build a checkpoint-restart system" — we already have one. The fix is **three small extensions to the
existing infrastructure**.

## Proposed Fix

### Fix 1 — Built-in retry defaults for context-overflow errors (primary)

Today, `get_retry_config(provider_name)` only returns a config if the user has one under `llm_provider.retry.<provider>`
in their sase config. `"Prompt is too long"` is a universal failure mode for Claude, not a user-specific choice, so it
should be recognized out of the box with no config required.

Add a module-level `_BUILT_IN_DEFAULTS: dict[str, ProviderRetryConfig]` in `retry_config.py` that seeds known
context-overflow patterns per provider:

| Provider          | Pattern(s)                                       | `max_retries` | `wait_times` |
| ----------------- | ------------------------------------------------ | ------------- | ------------ |
| `claude`          | `"Prompt is too long"`                           | 3             | `[0]`        |
| `codex`           | `"context_length_exceeded"`, `"tokens exceeded"` | 3             | `[0]`        |
| `external`/`gemini` | `"input token limit"`, `"request too large"`     | 3             | `[0]`        |

Change `get_retry_config` to merge user-configured values on top of built-ins (user overrides take precedence; otherwise
the built-in pattern list is appended to whatever the user configured, deduplicated). The wait time is `0` because
"Prompt is too long" is not a rate-limit — waiting does not help; what helps is starting a new session.
`find_retry_config_for_error` also picks up built-ins automatically because it iterates `llm_provider.retry` values and
now calls the same merge helper.

Result: with no configuration change, a coder hitting `"Prompt is too long"` auto-restarts up to 3 times. A user who
wants to disable the behavior can set `max_retries: 0` in their config.

### Fix 2 — Continuation nudge on context-overflow retries (secondary)

A naive re-run of `state.current_prompt` works _most_ of the time because the coder reads files on demand and respects
the on-disk state it finds. But the prompt says "The above plan has been reviewed and approved. Implement it now." — a
coder starting fresh with that prompt can plausibly try to re-apply edits that are already in the working tree, conflict
with its own earlier work, or redo tests it already wrote.

Add a **continuation-nudge mechanism** to the retry config so specific error patterns can prepend a message to the retry
prompt:

```python
@dataclass
class ProviderRetryConfig:
    max_retries: int = 0
    error_patterns: list[str] = field(default_factory=list)
    wait_times: list[int] = field(default_factory=lambda: [30])
    fallback_model: str | None = None
    continuation_prompt: str | None = None   # NEW
```

The built-in defaults for context-overflow patterns set `continuation_prompt` to:

> Your previous attempt hit the model's context window limit. Any file edits, new tests, and other on-disk changes you
> made are preserved. Before making additional changes, run `git status` and `git diff` to see what is already in place,
> then continue implementing the plan from wherever you left off. Do not re-apply edits that are already present.

Wiring: `run_agent_exec_retry.handle_workflow_error` already has access to `state` and the active `ProviderRetryConfig`.
When a retry fires and `active_retry_cfg.continuation_prompt` is set, prepend it to `state.current_prompt` (once per
retry iteration — not cumulatively).

User config can override the nudge by specifying `continuation_prompt` under the provider's retry section.

### Fix 3 — Expose restart count in the agent artifacts and TUI

The retry infrastructure already writes `retry_state.json` during waits (status `"retrying"` / `"running_retry"` /
`"running_fallback"`). For context-overflow retries the wait is zero, so the TUI never sees the intermediate state. Two
visibility improvements:

1. Always write `retry_state.json` with the final `retry_count` at the end of a retry cycle, even for 0-wait retries, so
   the TUI can show "resumed 2× after context overflow".
2. Include the retry metadata in `done.json` (already happens via `_retry_meta` in `_finalize_loop` —
   `run_agent_exec.py:104-113` — so this is already covered; verify it renders in the agent-detail view).

Nice-to-have: a new retry status literal `"resumed_context_overflow"` (distinct from generic `"retrying"`) so the TUI
can use a different label / color for this class of retry. Optional; skip if it complicates the `Literal` type too much
for one use case.

## Design Details

### Merge semantics for built-in + user retry config

```python
_BUILT_IN_DEFAULTS: dict[str, ProviderRetryConfig] = {
    "claude": ProviderRetryConfig(
        max_retries=3,
        error_patterns=["Prompt is too long"],
        wait_times=[0],
        continuation_prompt=_CONTEXT_OVERFLOW_NUDGE,
    ),
    # codex, external, gemini analogues
}

def get_retry_config(provider_name: str) -> ProviderRetryConfig | None:
    user_cfg = _load_user_retry_config(provider_name)  # existing logic
    built_in = _BUILT_IN_DEFAULTS.get(provider_name)
    if user_cfg is None and built_in is None:
        return None
    if user_cfg is None:
        return built_in
    if built_in is None:
        return user_cfg
    # Merge: user wins on scalar fields; patterns are a dedup'd union.
    return ProviderRetryConfig(
        max_retries=user_cfg.max_retries,  # default 0 must still disable
        error_patterns=_dedup_ordered(built_in.error_patterns + user_cfg.error_patterns),
        wait_times=user_cfg.wait_times or built_in.wait_times,
        fallback_model=user_cfg.fallback_model or built_in.fallback_model,
        continuation_prompt=user_cfg.continuation_prompt or built_in.continuation_prompt,
    )
```

Edge case: a user with `max_retries: 0` must disable retries entirely — otherwise the built-in `max_retries: 3` would
override their opt-out. Treat "user set max_retries explicitly" as authoritative. Simplest approach: store `max_retries`
as `int | None` in the raw user config parse (None = unset, 0 = explicit disable), and only fall back to the built-in
when the user didn't set it.

### Continuation nudge injection point

`handle_workflow_error` already runs once per failure:

```python
# run_agent_exec_retry.py, before the sleep
if active_retry_cfg.continuation_prompt and state.current_prompt:
    if not state.current_prompt.startswith(active_retry_cfg.continuation_prompt):
        state.current_prompt = (
            f"{active_retry_cfg.continuation_prompt}\n\n{state.current_prompt}"
        )
```

The `startswith` guard keeps the nudge from compounding if the same retry path fires more than once in a session
(shouldn't happen given the early-return structure, but cheap insurance).

### Distinguishing real "Prompt is too long" from incidental substring matches

Low-risk: the pattern is specific and case-sensitive matches on actual Claude error payloads. The existing
`is_retryable_error` is case-insensitive, which is fine — other substrings like "the prompt is too long for my taste" in
a model response are not going to appear in `stderr` (which is what we match against).

### Provider coverage

Fix 1 lists patterns for all four providers, but external provider/Gemini/Codex are speculative — confirm exact error strings by
triggering each (or reading their SDK docs) before landing. For MVP, it's acceptable to ship the Claude entry only and
add the others as follow-ups; the core mechanism is provider-agnostic once in place.

### Infinite-loop protection

`max_retries: 3` caps the restart chain. If three fresh coder sessions all exhaust the context window, the plan
genuinely does not fit — surface the hard failure to the user with a link to the coder's chat history and `usage.json`
so they can split the plan manually.

## Non-Goals (Explicit Follow-Ups)

These are deliberately **out of scope** for this plan. Each is a separate initiative if/when the primary fix proves
insufficient:

- **Token-usage monitoring / proactive warnings (Approach B from the investigation).** Read `usage.input_tokens` from
  `artifacts/usage.json` after each invocation and surface a TUI banner at ≥80% of the window. Useful, but does not
  prevent the failure — only warns the user post-hoc. Ship the structural fix first.
- **Mid-session context injection.** Cannot be done without session continuity; not pursued.
- **Plan chunking guidance (Approach C).** A docs-level recommendation to planners to split 3000+ line plans into
  multiple `.md` files. Orthogonal; file separately if useful.
- **Changing Claude Code's internal auto-compact.** We don't control the subprocess's context policy. Out of scope.
- **Replacing `just test` verbose output with a context-efficient variant.** Possible follow-up if profiling shows
  `pytest -v` output is a leading bloat source. Not needed to fix the incident.

## Test Coverage

Add to `tests/test_llm_provider_retry_config.py`:

- Built-in default merge: no user config → returns built-in.
- User overrides max_retries to 0 → retries disabled (built-in does NOT re-enable).
- User appends custom pattern → final config has both built-in and user patterns, deduplicated.
- User sets `continuation_prompt: ""` → treated as override (empty string ≠ unset).

Add to `tests/test_axe_run_agent_exec_retry.py` (new file if needed):

- `handle_workflow_error` prepends `continuation_prompt` to `state.current_prompt` when pattern matches.
- `handle_workflow_error` does NOT double-prepend if called twice with the same nudge (idempotence guard).
- After `max_retries` exhausted, returns `"raise"` even when `continuation_prompt` is set.

Integration (mock-based, under `tests/`):

- Fake `ClaudeCodeProvider` that fails with stderr `"API Error: 400 - Prompt is too long"` on first invocation then
  succeeds on the second. Drive through `invoke_agent` → verify: retry fires, continuation nudge prepended to the second
  invocation's prompt, final result returned cleanly, `retry_metadata` recorded in the eventual `done.json`.

## Sequencing and Delivery

One PR, three commits:

1. **Fix 1**: `retry_config.py` built-in defaults + merge logic + tests. No user-visible behavior change if no Claude
   agent ever hits the error.
2. **Fix 2**: `ProviderRetryConfig.continuation_prompt` field, built-in nudge string, `handle_workflow_error` injection,
   tests. Now failures auto-recover with the right nudge.
3. **Fix 3**: `retry_state.json` writes for zero-wait retries + verification that `done.json` surfaces the retry
   metadata. TUI smoke-test to confirm the "resumed N× after context overflow" label renders.

Each commit runnable / shippable standalone.

## Validation

- Manual: re-run the fast_dismiss coder on a workspace seeded to near the limit (inject a large synthetic file read);
  confirm auto-restart, confirm the restarted coder sees its own git diff and does not re-edit.
- Automated: new unit + integration tests must pass; `just check` must pass.
- Regression: ensure existing rate-limit retry tests still pass (built-in merge must not break them).

## Files Touched (expected)

- `src/sase/llm_provider/retry_config.py` — built-in defaults, merge logic, `continuation_prompt` field.
- `src/sase/axe/run_agent_exec_retry.py` — prepend continuation nudge before sleep/restart.
- `src/sase/axe/run_agent_exec.py` — verify `retry_state.json` writes even on zero-wait; no functional change expected
  beyond that.
- `tests/test_llm_provider_retry_config.py` — merge logic tests.
- `tests/test_axe_run_agent_exec_retry.py` — injection + idempotence tests (new file if none exists).
- `tests/test_llm_provider_invoke.py` (or a new file) — integration test with fake provider.
- `docs/llms.md` or `docs/configuration.md` — document the `continuation_prompt` field and the built-in default
  behavior.
