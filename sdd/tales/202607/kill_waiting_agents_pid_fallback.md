---
create_time: 2026-07-07 00:31:47
status: done
prompt: sdd/prompts/202607/kill_waiting_agents_pid_fallback.md
---
# Fix Telegram `/kill` Failing With "Could not find PID" for Waiting/Queued (Fork) Agents

## Problem

Killing agents from Telegram fails for fork/queued agents. Reproduced by the user on 2026-07-07:

1. User sends `/kill` in Telegram; the bot lists agents `08.f2`, `08.f1`, `08`, `07`, `04`. The two fork agents
   (`08.f1`, `08.f2`, both launched with a `#fork:08` prompt that adds `wait_for: ["08"]`) show `?` for duration.
2. User taps `08.f1` and gets: `⚠️ Kill failed: Could not find PID for agent '08.f1'`.

## Root Cause

Telegram's `/kill` (both the command and the Kill button callback in the sase-telegram plugin's `sase_tg_inbound.py`)
calls `kill_named_agent()` in `src/sase/agent/running.py`. That function resolves the target PID from exactly two
sources:

- **home project** (`project_name == "home"`): read `pid` from `running.json` in the agent's artifacts directory.
- **non-home projects**: scan the project file's RUNNING field for a workspace claim whose `artifacts_timestamp`
  matches.

Agents launched with a wait dependency (Telegram Fork/Wait buttons, `#fork`, `%wait`) run with a **deferred workspace**
(`SASE_AGENT_DEFERRED_WORKSPACE=1`). In `src/sase/axe/run_agent_runner.py` the runner:

1. skips workspace prep, writes `agent_meta.json` (which **does** contain the runner `pid`),
2. parks in `wait_for_dependencies()` (`src/sase/axe/run_agent_wait.py`), writing `waiting.json`,
3. only **after** the wait resolves calls `claim_deferred_workspace()` (RUNNING-field claim) and proceeds.

So during the entire waiting phase there is **no `running.json` and no RUNNING-field claim** — `kill_named_agent()`
finds no PID and returns the `missing_pid` failure, even though the runner process is alive and its PID is sitting in
`agent_meta.json` (and `workflow_state.json`).

Verified on live artifacts: while waiting, `.../ace-run/202607/07/20260707001816` (agent `08.f2`) contained only
`agent_meta.json` (pid 4001633, alive), `waiting.json`, `workflow_state.json`, and prompt files — no `running.json`; the
RUNNING claim (workspace `home_10`) appeared only after the wait resolved.

This is also why the experience is inconsistent across frontends:

- The **listing** path (`_running_info_from_running_record()` in `src/sase/agent/running.py`) already prefers
  `agent_meta.json`'s `pid` and filters via `is_process_alive()` — so waiting agents _appear_ in the Telegram `/kill`
  list (with `?` duration, since `run_started_at` is unset while waiting).
- The **TUI** kill flow works because it signals the in-memory `agent.pid` (loaded from `agent_meta.json`), not the
  `kill_named_agent()` lookup.
- Only the shared **kill-by-name** path (Telegram/mobile bridge, CLI) lacks the meta-PID fallback.

### Secondary issue: stale "ghost" agents are unkillable

Agent `08.f1`'s runner process later died without writing a `done.json`. Such an artifact still resolves via
`find_named_agent()` as a live (non-done) agent, but every kill attempt fails with `missing_pid` — there is no way to
clear it from Telegram. The kill path should treat "no live process anywhere" as a successful cleanup (the agent is
already dead) rather than a hard failure.

## Fix

All changes are in the primary sase repo; the sase-telegram plugin needs no changes for the core fix (it already renders
success/failure from the `KillResult`). This stays within the existing Python lifecycle code:
`src/sase/agent/running.py`'s module docstring explicitly keeps process-liveness checks and RUNNING-field parsing in
Python, so no sase-core (Rust) change is needed.

### 1. Meta-PID fallback in `kill_named_agent()` (`src/sase/agent/running.py`)

After the existing two PID lookups fail, fall back to reading `pid` from the agent's `agent_meta.json`, validated with
`is_process_alive()` from `sase.agent.names` (which already guards against PID recycling via `/proc/<pid>/cmdline` and
respects `stopped_at`). If alive, kill it through the existing
`request_user_kill(pid, artifacts_dir=..., source="agents_kill", wait=True)` flow.

Runner-side termination is already graceful for waiting agents: the runner installs a soft SIGTERM handler
(`install_workspace_release_sigterm_handler`), and `wait_for_dependencies()` polls `was_killed()` every 2 seconds, so
the runner exits its wait and finalizes (done marker, notifier) through its normal shutdown path.

Also apply the same home/non-home cleanup that already exists, but make it conditional on what is actually present (a
waiting deferred-workspace agent has no `running.json` to delete and no workspace claim to release — both cleanups are
already idempotent). Defensively remove a leftover `waiting.json` only if the process is confirmed dead after the kill
wait, then update the artifact index via `update_agent_artifact_index_for_marker_mutation()` (mirroring the existing
home-mode `running.json` cleanup).

### 2. Stale-agent cleanup instead of `missing_pid` failure

When no PID can be found anywhere, or the meta PID is confirmed dead: instead of returning the `missing_pid` failure,
clean up and report success:

- remove stale `waiting.json` / `running.json` markers (idempotent), update the artifact index,
- record the dismissal via the existing `_record_dismissal(cl_name, timestamp)`,
- return `KillResult(success=True, status="not_running", changed=True, ...)` with a message like
  `"Agent '<name>' was not running; cleaned up stale state"`.

Keep `reason="missing_pid"` reserved for genuinely ambiguous cases only if any remain; the expectation is that this
branch now always succeeds. Downstream mapping in `src/sase/integrations/_mobile_agent_lifecycle.py`
(`raise_lifecycle_error`, which maps `missing_pid` → `MobileAgentNotRunningError` / bridge exit code 5) stays for
compatibility but should no longer trigger from stale agents. The Telegram plugin then shows the normal "💀 Agent
terminated" confirmation (with Redo button) instead of a failure.

Note for `_kill_result` consumers: `kill_mobile_agent()` and `retry_mobile_agent()` (`kill_source_first=True`) both
benefit — retry-after-kill of a stale agent currently degrades the same way.

### 3. Optional polish: waiting status in the Telegram kill list

The `/kill` list renders `gpt-5.5, ?` for waiting agents because `RunningAgentInfo.duration` is `"?"` outside RUNNING
status. Small UX improvement (separate commit, or skip if noisy): surface `status` (e.g. `WAITING`/`STARTING`) in the
Telegram list line instead of a bare `?`, using the `status` field that `list_all_agents()` already returns. The
rendering lives in the sase-telegram plugin (`_format_agent_description` in `sase_tg_inbound.py`); if changed, open the
linked repo through the standard `sase workspace open` flow.

## Tests

Extend `tests/test_kill_named_agent_dismiss.py` (fixtures for home/non-home artifact layouts already exist there):

1. **Waiting agent, live meta PID (home project)**: artifacts dir with `agent_meta.json` containing a pid +
   `waiting.json`, no `running.json`, no RUNNING claim → `kill_named_agent` succeeds, kills the process group (patched
   `os.killpg` / `request_user_kill`), records dismissal.
2. **Waiting agent, live meta PID (non-home project)**: same, with a project file lacking any RUNNING claim for the
   timestamp.
3. **Stale agent, dead meta PID**: `is_process_alive` false → success with `status="not_running"`, stale `waiting.json`
   removed, dismissal recorded.
4. **Update** `test_kill_named_agent_does_not_write_dismissal_when_pid_missing`: behavior intentionally changes — a
   PID-less non-done artifact is now cleaned up and dismissed. Rewrite it to assert the new contract.
5. **PID-recycling guard**: meta PID alive but not a sase/python process → treated as dead (stale cleanup), no signal
   sent.

Update `tests/test_mobile_agent_kill_retry.py`: the parametrized `missing_pid` → exit-code-5 row reflects the old
contract; keep the mapping test for the error type itself but add/adjust a test asserting the stale-kill bridge path now
returns the success payload.

Manual verification: launch a throwaway fork agent waiting on a long-running agent (`#fork`-style prompt with
`wait_for`), then `sase agents kill <name>` (or Telegram `/kill`) while it is waiting; confirm the process dies, a done
marker appears, and the agent leaves the `/kill` list. Repeat for a hand-crafted stale artifact (meta with dead pid, no
done marker).

Run `just install` then `just check` before finishing.
