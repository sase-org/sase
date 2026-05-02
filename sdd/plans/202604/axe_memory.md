---
create_time: 2026-04-13 23:57:37
status: done
prompt: sdd/prompts/202604/axe_memory.md
---

# Plan: Improve Axe Agent Runner Long-Term Memory

## Goal

Rewrite `memory/long/axe_agent_runner.md` to maximize non-obvious domain knowledge and recurring gotcha coverage within
a 100-line budget. The current file is 44 lines and covers basics accurately but shallowly.

## What to Add

### Lumberjack Architecture (new section)

- Orchestrator spawns 4 default lumberjacks as subprocesses: hooks (1s), checks (300s), comments (60s), housekeeping
  (3600s)
- Each lumberjack runs chops concurrently via ThreadPoolExecutor; one slow chop can't block others
- Agent deduplication: per-chop singleton tracking via PID, checked with `os.kill(pid, 0)`

### Execution Loop Gotchas (new section)

- **Dual done-marker write**: multi-step workflows must write done.json to BOTH `current_artifacts_dir` AND root
  `ctx.artifacts_dir` — root write keeps name reserved in `_get_active_agent_names` and enables `find_named_agent`
  discovery
- **Killed flag reset**: `reset_killed()` MUST be called at start of each loop iteration; stale flag from previous retry
  or plan/question handoff causes false "killed" outcome
- **SIGTERM marker polling**: after soft kill, loop checks for `.sase_plan_pending` / `.sase_questions_pending`; markers
  must be written by `sase plan`/`sase questions` BEFORE the runner reads them (no wait/retry)
- **Noop detection**: if `agents_launched=0` after completed workflow (empty for-loop), outcome="noop"

### Retry & Fallback (new section)

- RetryTracker: tries `max_retries` with sleep, then switches to `fallback_model` via `SASE_MODEL_OVERRIDE` env var
- Re-prepares workspace (clean + checkout) between retry attempts
- Error matched against per-provider retry configs; falls back to `find_retry_config_for_error()` across all providers

### Known Bug Patterns (new section — things that actually broke in production)

- **Rich markup injection**: error messages with brackets embedded in Rich `[style]...[/style]` tags crash lumberjack;
  caused 3500+ restart loop. Fix: `markup=False` on `console.print`
- **Kill notification race**: runner's `finally` block sent "Agent failed" notification after user already dismissed
  from TUI. Fix: guard `notify_workflow_complete()` with `was_killed()`
- **wait_checks arg order**: `log_callback` called with `(chop_name, message)` instead of `(message, style)`, causing
  cascading failures in dependency resolution

### Home Mode (new section, brief)

- Uses `running.json` marker instead of workspace tracking; no workspace allocation; deferred workspace skipped entirely

### Enrich Existing Sections

- **Agent Runner Phases**: add that xprompt expansion happens BEFORE directive extraction (so xprompt-embedded
  directives are discovered); add that `claim_agent_name()` blocks duplicate named agents (skipped for auto_dismiss)
- **Deferred Workspace**: add wait polling constants (2s poll, 24h max timeout, wait_checks chop at 1s interval)
- **SharedRunnerPool**: add that it uses `fcntl.flock` on `~/.sase/axe/shared/runner_count`; guards against negative on
  release

### Key Constants (new section)

- zombie_timeout: 7200s, wait poll: 2s, wait max: 86400s, SIGTERM escalation: 15s, exit code: 143

## What to Cut or Compress

- Current SIGTERM section is 5 lines; compress to 2-3 lines since it's straightforward
- Zombie detection compress slightly (remove the bullet format, use inline)

## Line Budget

- Frontmatter: 3 lines
- Title: 2 lines
- Lumberjack Architecture: ~8 lines
- Agent Runner Phases: ~12 lines (expanded from 8)
- Deferred Workspace: ~8 lines (expanded from 4)
- Execution Loop Gotchas: ~12 lines
- Retry & Fallback: ~6 lines
- SIGTERM & Zombie: ~8 lines (merged, compressed)
- Home Mode: ~3 lines
- Known Bug Patterns: ~10 lines
- SharedRunnerPool: ~4 lines
- Key Constants: ~4 lines
- **Total: ~80 lines** (under 100)

## Steps

1. Rewrite `memory/long/axe_agent_runner.md` with the restructured content
2. Run `just check` to ensure no build issues
