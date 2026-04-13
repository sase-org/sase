---
keywords: [axe, lumberjack, chop, agent runner, scheduler, daemon, runner pool, zombie]
---

# Axe Agent Runner

## Agent Runner Phases

1. **Workspace prep + dynamic memory + directives** — prepare workspace (skip for home mode), generate dynamic memory
   and inject into prompt, then extract directives. Memory injection happens _before_ directive extraction, so memory
   content can contain directives like `%model` or `%wait`.

2. **Wait dependencies** — `wait_for_dependencies()` handles three types: agent name (wait for another agent to finish),
   duration floor (minimum elapsed time), and absolute time (`wait_until`).

3. **Reference resolution** — `resolve_agent_refs_in_prompt()` resolves `@name` references.

4. **Execution with retry** — `run_execution_loop()` with `RetryTracker`. Handles plan/question markers mid-execution.

5. **Completion + notifications** — build done marker, record metrics, send notifications, release workspace.

## Deferred Workspace

Agents with `%wait` don't hold a real workspace during the wait phase. A placeholder (`workspace_num=0`) is claimed
upfront. After dependencies are satisfied, `claim_deferred_workspace()` releases the placeholder and allocates a real
workspace via `get_first_available_axe_workspace()`.

## SharedRunnerPool Gotcha

**No automatic slot expiration** — runners must explicitly call `release_slot()` to decrement the counter.

## Zombie Detection

- **Stale timestamps** — comment entries older than 2 hours (default `zombie_timeout_seconds=7200`) are marked ZOMBIE
- **Dead PID checks** — processes that no longer exist
- Cleanup: orchestrator escalates from SIGTERM → 15s wait → SIGKILL

## SIGTERM Handling

- `install_sigterm_handler()` sets a soft kill flag (`_killed_state["killed"] = True`)
- Uses `sys.exit()` instead of re-raising so `finally` blocks run for workspace cleanup
- Exit code: **143** (128 + 15)
- Agent runner installs with `soft=True` — sets the flag without calling `sys.exit()`, allowing the runner to detect
  termination via `was_killed()` and clean up gracefully
