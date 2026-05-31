---
create_time: 2026-05-31 12:09:34
status: done
prompt: sdd/prompts/202605/killed_agents_terminate.md
---
# Plan: Make Killed SASE Agents Actually Terminate

## Context

Two `bqb` agents were launched for the same diagnostic task:

- `bqb.cld` received SIGTERM at `2026-05-31T15:48:45Z`, finalized with `done.json` outcome `killed`, and did not have a
  plan submission marker in its metadata.
- `bqb.cdx` also logged `Received SIGTERM - agent was killed` at `2026-05-31T15:48:45Z`, but the Codex subprocess
  continued running. It later executed `sase plan`, which submitted
  `~/.sase/plans/202605/ace_prompt_primary_artifact.md` and produced a plan approval notification at
  `2026-05-31T11:51:29-04:00`.

The current runner uses SIGTERM for two different meanings:

- A user-requested kill from the TUI, CLI, or mobile bridge.
- An intentional handoff from `sase plan` / questions, where the agent writes a marker and SIGTERMs the runner so the
  runner can transition into plan approval or question handling.

Because the runner records only a boolean `was_killed()`, a user kill that happens before a late plan marker can be
misinterpreted as a plan handoff after the provider subprocess returns.

## Goals

1. A user kill must win over any later plan/question marker written by a still-running provider subprocess.
2. A plan/question handoff must keep working when the marker was written before the SIGTERM.
3. Killing an agent should stop the runner and provider subprocess promptly, rather than merely hiding/releasing it in
   the UI.
4. The fix should apply uniformly across runtimes and entrypoints: ACE TUI, `sase agents kill`, mobile agent kill, and
   any shared cleanup paths.

## Proposed Design

### 1. Track Kill Timing in the Runner

Extend `sase.axe.runner_utils` so the SIGTERM handler records a timestamp in addition to the existing boolean killed
flag.

Expose helpers along these lines:

- `killed_at()` returns the timestamp of the most recent SIGTERM, or `None`.
- `reset_killed()` clears both the boolean flag and timestamp.
- Existing `was_killed()` behavior stays compatible for current callers.

Then update the plan/question marker handling path in `sase.axe.run_agent_exec`:

- Read `.sase_plan_pending` / `.sase_questions_pending` as it does today.
- Compare marker `timestamp` against `killed_at()`.
- Treat a marker as a handoff only when it existed before, or effectively at, the SIGTERM that interrupted the runner.
- If a marker timestamp is newer than the recorded user kill, ignore/delete it and finalize the loop as `killed`.

This directly fixes the `bqb.cdx` timeline: user SIGTERM at `15:48:45Z`, marker written around `15:51:29Z`, so the late
plan marker cannot override the earlier kill.

### 2. Write Explicit User-Kill Intent Before Signalling

Add a small shared helper for user kill requests that writes a kill-intent artifact before sending signals. Use this
from:

- `src/sase/agent/running.py::kill_named_agent`
- `src/sase/ace/tui/actions/agents/_killing.py`
- mobile kill paths, if they bypass `kill_named_agent`

The artifact can be a JSON file in the agent artifact directory, for example `.sase_user_kill_pending`, containing
timestamp, pid, source, and optional reason. This gives the runner and diagnostics a durable signal that the SIGTERM
came from a user kill, not a control-plane plan/question handoff.

Use this marker as an additional guard in `_handle_killed_iteration`: if a user-kill intent exists, finalize as `killed`
without processing plan/question markers.

### 3. Harden Process Termination

Introduce a shared process termination helper for user kills:

- Send SIGTERM to the runner process group.
- Poll briefly for exit.
- If the process group is still alive after a short grace period, send SIGKILL.
- Keep this helper separate from `sase.main.utils.kill_agent_runner_group`, because `sase plan` intentionally needs a
  soft SIGTERM handoff.

For TUI kills, avoid freezing Textual by doing the wait/escalation in a short background task/thread while preserving
the existing optimistic UI update. For CLI/mobile kills, a brief synchronous wait is acceptable and gives a more
truthful result.

### 4. Preserve Existing Completion Semantics

The graceful path should still let the runner write `done.json` with `outcome: killed` when it can. SIGKILL escalation
is only a fallback for non-cooperative providers or stuck runner states.

When escalation is required, make sure the kill helper leaves enough artifact evidence for status/debugging:

- The user-kill intent marker.
- The kill helper result/status if practical.
- Existing workspace release/dismissal behavior should remain idempotent.

### 5. Tests

Add focused tests for the regression and the new kill behavior:

- Runner state records and resets `killed_at()`.
- A plan marker older than the SIGTERM is treated as a valid plan handoff.
- A plan marker newer than the SIGTERM is ignored and finalizes as `killed`.
- A user-kill intent marker causes `_handle_killed_iteration` to return `killed` even if a plan marker exists.
- `kill_named_agent` writes user-kill intent before signalling.
- The shared termination helper sends SIGTERM first and SIGKILL only after the process remains alive past the grace
  period.
- TUI kill path uses the shared user-kill request helper rather than raw `os.killpg`.

## Verification

Run focused tests first:

```bash
uv run pytest tests/test_axe_runner_utils.py tests/test_axe_run_agent_exec_plan_followup_approvals.py tests/test_kill_named_agent_dismiss.py tests/test_agent_kill.py
```

Then run the repo-required checks after implementation:

```bash
just install
just check
```

Manual verification should include launching a test `#plan` agent, killing it while the LLM is still drafting, and
confirming:

- No plan approval notification is created after the kill.
- The agent reaches `DONE (killed)`.
- `ps` no longer shows the runner PID or child provider process.
