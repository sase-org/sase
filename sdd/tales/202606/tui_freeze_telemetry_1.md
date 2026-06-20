---
create_time: 2026-06-20 14:36:11
status: done
prompt: sdd/prompts/202606/tui_freeze_telemetry_1.md
---
# Plan: Always-On Telemetry to Diagnose `sase ace` TUI Freezes

## Motivation / Context

A `sase ace` TUI (PID 2960662, now dead) froze for >30s. I investigated and **could not identify the cause with
confidence**, because the data needed to answer "what was the main thread doing during the stall?" does not exist. This
plan adds that data.

### What the investigation found

- **No always-on freeze telemetry exists.** The only loop-stall instrumentation — `SASE_TUI_PERF=1`
  (`src/sase/ace/tui/util/perf.py`, per-keypress key→paint JSONL), `SASE_TUI_TRACE=1` (`src/sase/ace/tui/util/trace.py`,
  hot-path spans), and `sase ace --profile` — is **opt-in via env flags** and was not enabled for the frozen run. No
  `~/.sase/perf/*` artifact covers the freeze window.
- **The heartbeat files can't do forensics.** `tui_last_keypress` / `tui_last_activity` / `tui_idle_state`
  (`src/sase/ace/tui_activity.py`, written from `_on_countdown_tick` in `src/sase/ace/tui/actions/_event_activity.py`)
  are overwritten in place and describe the _current_ live PID, not a dead one. There is no per-PID history and nothing
  that records a stall event. I could not even establish _when_ PID 2960662 froze.
- **A plausible but unconfirmable suspect:** untimed synchronous git subprocess calls in
  `commit_bare_git_sdd_init_paths` (`src/sase/sdd/_commit.py:155-200`) — notably `git push origin HEAD` with **no
  `timeout=`** — invoked during agent-launch workspace prep (`ws_get_workspace_directory` →
  `ensure_bare_git_sdd_initialized`). The `home` project's bare-git remote (`/home/bryan/projects/git/home`) is failing
  pushes (recorded exit 1 at 12:37:57 in `~/.sase/logs/launch_failures.jsonl`). A push that _hangs_ (rather than
  fast-fails) here blocks indefinitely. **However**, this path runs in a Textual worker thread
  (`run_worker(..., thread=True)` via `_submit_launch_task`), so it would stall the _launch task_, not block keystroke
  handling — and the one recorded push failed fast, not hung. So it does not cleanly explain a full-UI freeze.
- **Other equally-plausible event-loop suspects exist and cannot be disambiguated:** a synchronous artifact-index sync
  against the 136 MB `~/.sase/agent_artifact_index.sqlite` (the perf memory's canonical example of a "felt like
  rendering" stall that was really a sync), or a full agent-list rebuild. With no main-thread stack capture, choosing
  between these is guesswork.

### Guiding principle (from `memory/tui_perf.md`)

> "Measure, don't guess. Perceived causes are frequently wrong." The goal of this plan is to make the _next_ freeze
> self-diagnosing: when the loop stalls, the system should record exactly what the main thread was executing, with
> enough context to act — without anyone having to reproduce it under a profiler.

## Goals

1. The next >Ns freeze writes a durable, structured record containing the **main-thread stack** at the time of the stall
   — turning "I think it was X" into "here is the stack."
2. The record survives the process and is attributable to a PID and a moment, so a _dead_ TUI can still be diagnosed
   after the fact.
3. Close the specific hang vector found (untimed git network calls in the launch/SDD-init path) and make slow launches
   attributable, so we can tell "the UI froze" apart from "a background launch was slow."

## Non-Goals

- Fixing a specific confirmed freeze (none is confirmed — that is the point).
- Replacing or changing the opt-in `SASE_TUI_PERF` / `SASE_TUI_TRACE` / `--profile` tooling. The new watchdog is
  complementary: always-on and stack-capturing, where those are sampling and opt-in.
- A general APM/metrics system. Scope is loop-stall forensics plus the one concrete hang vector.

## Design

### Component 1 — Always-on event-loop stall watchdog (the centerpiece)

A daemon thread that detects when the Textual asyncio event loop stops making progress and, on a stall, captures the
main thread's stack.

**Why a separate thread:** `_on_countdown_tick` already runs every second, but it runs _on_ the event loop — a blocked
loop stops ticking, so the loop can never report its own stall. The detector must run off-loop.

**Mechanism (liveness beacon):**

- On TUI startup (alongside `write_tui_pid()` in `src/sase/ace/tui/actions/startup.py`), start a daemon thread holding a
  reference to the running loop.
- The watchdog periodically schedules a trivial callback onto the loop via `loop.call_soon_threadsafe(...)` that stamps
  a shared "last loop progress" monotonic timestamp. Each watchdog poll compares now vs. that stamp. If the gap exceeds
  a threshold (default **5s**, configurable), the loop is stalled.
- On a detected stall, the watchdog captures the **main thread's** stack via `sys._current_frames()[main_thread_ident]`
  (alternatively `faulthandler.dump_traceback`), plus context, and appends one JSONL record to a stall log.
- A single stall emits **one** record (with final duration logged when the loop recovers, or at process exit). Watchdog
  overhead while healthy is one cheap scheduled callback per poll interval — negligible.

**Stall record (`~/.sase/logs/tui_stalls.jsonl`):**

```json
{
  "ts": 1718900000.0,
  "pid": 2960662,
  "stall_seconds": 34.2,
  "current_tab": "agents",
  "last_action": "launch",
  "last_keypress_age_s": 35.0,
  "main_thread_stack": ["...frame...", "...frame..."],
  "sase_version": "..."
}
```

- `pid` + persisted file = the dead-process forensic path we lacked.
- `current_tab` / `last_action` come from the existing trace context (`set_trace_context` in `trace.py`) and the
  activity log (`ActivityEventType` in `src/sase/ace/activity_log.py`); thread the most recent action through so the
  stack has situational context.
- **Always-on**, but follows the established JSONL conventions of `perf.py`/`trace.py` (env-overridable path via e.g.
  `SASE_TUI_STALL_PATH`, env to tune the threshold, env to disable as an escape hatch). Log file is size-capped /
  rotated so it can't grow unbounded.

**Open design question for review:** confirm `sys._current_frames()` reliably captures the blocking frame for
synchronous C-level subprocess waits (the suspected git-push case). If a native `wait()` masks the Python frame, fall
back to also recording the most recent `tui_trace` span as the "last known operation."

### Component 2 — Bound and instrument the launch/SDD-init git calls (the concrete suspect)

In `commit_bare_git_sdd_init_paths` (`src/sase/sdd/_commit.py`) and the sibling git helpers there:

- Add a `timeout=` to every `subprocess.run`, with a generous-but-finite bound for the network calls (`git push`, and
  any `fetch`) and a tighter bound for local calls (`add`/`commit`/`diff`). On timeout, raise a typed, clearly-messaged
  error and emit a structured slow/timeout record so a hang becomes a fast, logged failure instead of an unbounded
  block.
- Emit a duration breadcrumb (reuse the existing `tui_trace` span helper, or a structured log line) for the push/fetch
  so "git push took 28s" is recorded even when it eventually succeeds.

**Rust-core boundary note (`memory/rust_core_backend_boundary.md`):** SDD init/commit/push is shared backend behavior —
a web/CLI frontend launching agents would want the same bound. Per the litmus test this leans toward `../sase-core`. The
planning decision: implement the timeout/telemetry where the canonical commit/push logic currently lives, and if that
logic is (or is being) migrated to `sase-core`, add the timeout there and thread telemetry back through the binding
rather than duplicating it in Python. Flag for confirmation during implementation.

### Component 3 — Launch / workspace-prep timing breadcrumbs

The launch path logs _failures_ to `~/.sase/logs/launch_failures.jsonl` but records no _success-path_ timing. In
`_run_agent_launch_body` (`src/sase/ace/tui/actions/agent_workflow/_launch_body.py`) and the workspace-prep steps it
drives (preclaim → SDD init/push → xprompt expansion → spawn):

- Wrap each stage in a `tui_trace` span (or structured timing log) and emit a per-launch summary (total + per-stage
  durations) via the tracked-task framework (which already records success/error).
- This makes a slow launch attributable and — critically — lets us distinguish "the whole UI froze" (Component 1 fires)
  from "a background launch task was slow" (no loop stall, but a long launch span).

## Affected Areas

- **New:** `src/sase/ace/tui/util/stall_watchdog.py` (watchdog thread + stall-record writer), mirroring
  `perf.py`/`trace.py` conventions.
- **Startup wiring:** `src/sase/ace/tui/actions/startup.py` (start watchdog with the loop; stop in
  `src/sase/ace/tui/actions/lifecycle.py` next to `remove_tui_pid`).
- **Context plumbing:** `src/sase/ace/tui/util/trace.py` (`set_trace_context`) and `src/sase/ace/activity_log.py`
  (last-action) — read by the watchdog for the stall record.
- **Git hardening:** `src/sase/sdd/_commit.py` (timeouts + slow-op telemetry); possibly mirrored in `../sase-core` per
  the boundary note.
- **Launch timing:** `src/sase/ace/tui/actions/agent_workflow/_launch_body.py`.

## Validation

- **Unit/integration:** a test that submits a callback which sleeps N>threshold seconds on the loop and asserts exactly
  one stall record with a non-empty main-thread stack and correct `pid`/`current_tab`; a test that the watchdog emits
  nothing during normal operation; a `_commit.py` test asserting a hung push (fake long-running git) raises a timeout
  error within the bound rather than blocking.
- **Manual:** run `sase ace`, trigger a deliberate synchronous sleep on the loop (debug hook), confirm a
  `tui_stalls.jsonl` record with a readable stack. Re-run the `home`-project launch that originally failed and confirm
  the push now fast-fails/timeouts with a structured record.
- **Regression guard:** confirm watchdog overhead doesn't regress the j/k benches
  (`pytest -s -m slow tests/ace/tui/bench_tui_jk.py`, target p95 < 16 ms) — the always-on path must stay negligible.

## Outcome

Next time a `sase ace` TUI freezes, `~/.sase/logs/tui_stalls.jsonl` will contain the PID, duration, and the main-thread
stack at the moment of the stall — answering "why did it freeze?" directly instead of by inference. The untimed git-push
hang vector is closed, and slow launches are distinguishable from true event-loop freezes.
