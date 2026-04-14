---
keywords: [axe, lumberjack, chop, agent, zombie]
---

# Axe Agent Runner

## Lumberjack Architecture

Orchestrator spawns lumberjacks as subprocesses, each running on a fixed interval: hooks (5s), waits (2s), checks
(300s), comments (60s), housekeeping (3600s). Each lumberjack runs eligible chops concurrently via `ThreadPoolExecutor`
with `as_completed()` — one slow chop can't block others.

Agent deduplication: `_agent_pids` tracks running PIDs per chop. `_is_agent_eligible()` probes with `os.kill(pid, 0)` —
if any live PID exists for a chop, it's skipped (singleton enforcement).

## Agent Runner Phases

1. **Workspace prep + dynamic memory + directives** — prepare workspace (skip for home mode), generate dynamic memory
   and inject into prompt. xprompt expansion happens BEFORE directive extraction, so xprompt-embedded directives like
   `%model:opus` are discovered. `claim_agent_name()` strips the name from older competing artifact entries to enforce
   uniqueness (skipped for `auto_dismiss` agents).

2. **Wait dependencies** — `wait_for_dependencies()` handles three types: agent name (wait for another agent to finish),
   duration floor (minimum elapsed time), and absolute time (`wait_until`).

3. **Reference resolution** — `resolve_agent_refs_in_prompt()` resolves `@name` references.

4. **Execution with retry** — `run_execution_loop()` with `RetryTracker`. Handles plan/question markers mid-execution.

5. **Completion + notifications** — build done marker, record metrics, send notifications, release workspace.

## Deferred Workspace

Agents with `%wait` don't hold a real workspace during the wait phase. A placeholder (`workspace_num=0`) is claimed
upfront. After dependencies are satisfied, `claim_deferred_workspace()` releases the placeholder and allocates a real
workspace. Wait polling: `_WAIT_POLL_INTERVAL=2s`, `_WAIT_MAX_TIMEOUT=86400s` (24h). The `waits` lumberjack runs at 2s
interval to check dependency satisfaction.

## Execution Loop Gotchas

- **Dual done-marker write**: multi-step workflows must write `done.json` to BOTH `current_artifacts_dir` AND root
  `ctx.artifacts_dir` — root write keeps name reserved in `_get_active_agent_names` and enables `find_named_agent`
  discovery
- **Killed flag reset**: `reset_killed()` MUST be called at start of each loop iteration; stale flag from previous retry
  or plan/question handoff causes false "killed" outcome
- **SIGTERM marker polling**: after soft kill, loop uses `read_and_delete_marker()` to atomically check for
  `.sase_plan_pending` / `.sase_questions_pending`; markers must be written BEFORE the runner reads them
- **Noop detection**: if `agents_launched == 0` after completed workflow (empty for-loop), outcome="noop"

## Retry & Fallback

`RetryTracker` retries `max_retries` (default 3) with configurable wait times (60s, 300s, 1800s), then switches to
`fallback_model` via `SASE_MODEL_OVERRIDE` env var (e.g. Claude falls back to sonnet, Gemini to flash). Re-prepares
workspace between retry attempts (but NOT for fallback switch). Error matched against per-provider retry configs;
`find_retry_config_for_error()` scans all providers for matching patterns.

## SIGTERM & Zombie Detection

- `install_sigterm_handler()` sets a soft kill flag; uses `sys.exit()` so `finally` blocks run for cleanup
- Agent runner installs with `soft=True` — sets flag without `sys.exit()`, detected via `was_killed()`
- Exit code: **143** (128 + 15)
- Zombie: comment entries older than `zombie_timeout_seconds` (7200s) or dead PIDs
- Cleanup: orchestrator escalates SIGTERM → 15s wait → SIGKILL

## Home Mode

Uses `running.json` marker (in `artifacts_dir`) instead of workspace tracking. No workspace allocation; deferred
workspace skipped entirely when `is_home_mode=True`.

## Known Bug Patterns

- **Rich markup injection**: error messages with brackets parsed as Rich `[style]` tags caused restart loop. Fix:
  `markup=False` on `console.print` (lumberjack.py)
- **Kill notification race**: runner's `finally` block sent "Agent failed" after user already dismissed from TUI. Fix:
  guard `notify_workflow_complete()` with `was_killed()` check
- **wait_checks arg order**: `log_callback` was called with `(chop_name, message)` instead of `(message, style)`,
  causing cascading failures in dependency resolution

## SharedRunnerPool

Uses `fcntl.flock` (LOCK_EX for writes, LOCK_SH for reads) on `~/.sase/axe/shared/runner_count`. Guards against negative
on release: `max(0, current - 1)`. No automatic slot expiration — runners must explicitly call `release_slot()`.

## Key Constants

zombie_timeout: 7200s · wait poll: 2s · wait max: 86400s · SIGTERM escalation: 15s · exit code: 143
