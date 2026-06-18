---
create_time: 2026-06-18 08:38:56
status: done
prompt: sdd/prompts/202606/axe_orphan_stop.md
---
# Plan: Fix unstoppable orphaned `sase axe` processes

## Problem / product context

Sometimes a `sase axe` orchestrator (and its lumberjack children) gets started from an **ephemeral `sase_<N>`
workspace** (e.g. by a test or an agent running in `sase_10`). Those processes then become impossible to control:

```
❯ procs axe
 4039388 … sase_10/.venv/bin/sase axe start …       # orchestrator — ALIVE
 4039420 … sase_10/.venv/bin/sase axe lumberjack …  # lumberjacks — ALIVE
 …
❯ axe stop
Axe orchestrator is not running.                     # but it clearly is
```

The user can neither **stop** the running processes nor **start** a fresh orchestrator from `sase ace`. The processes
keep consuming resources and running chops from a throwaway workspace clone until manually `kill`ed.

## Root cause

Axe state is **global**, not per-workspace: `AXE_STATE_DIR = sase_home()/axe` (`~/.sase/axe`, since `$SASE_HOME` is
unset), shared by every workspace and the primary install. Within that dir the live orchestrator's existence is tracked
by **two independent signals that can desynchronize**:

1. **`orchestrator.lock`** — an exclusive `flock` held by the live orchestrator's open fd for its entire lifetime,
   released automatically by the kernel when the process dies. **Authoritative**, but its holder's PID is not recorded
   anywhere.
2. **`orchestrator.pid`** — a plain PID file written at startup but mutated _independently_ by `stop_axe_daemon`,
   `get_axe_pid`, and `_cleanup_pid_file` (which unlinks it whenever the recorded PID isn't running, and which `stop`
   calls _immediately after SIGTERM_, before the process has actually exited).

`get_axe_pid()` consults only the PID file (+ a legacy `pid` file); it never reconciles against the lock. This produces
a **deadlock when the two disagree** — e.g. an orchestrator started from `sase_10` is alive and holds the flock, but
`orchestrator.pid` has been removed (by a teardown `stop` that SIGTERM'd-then-cleaned but didn't kill it, by PID-file
cleanup, or by a cross-workspace race):

- **`axe stop`** → `get_axe_pid()` reads the (missing) PID file → `None` → reports _"Axe orchestrator is not running"_ →
  **no-op**; orchestrator + lumberjacks keep running.
- **`axe start`** (incl. `sase ace`'s start button) → `get_axe_pid()` is `None` so it tries to acquire the flock → **the
  live orchestrator still holds it** → `_acquire_lifecycle_lock_for_start` spins for 15s then returns `None` →
  `start_axe_daemon` returns `None` → TUI shows a bare _"Failed to start axe"_. Net: can neither stop nor start.

### Contributing causes (each independently worth fixing)

- **Orphaned lumberjacks are never swept.** The orchestrator spawns lumberjacks with plain `subprocess.Popen` (no
  `start_new_session`), so they share the orchestrator's process group (the orchestrator _is_ a session/group leader
  because the daemon path uses `start_new_session=True`). But `stop_axe_daemon` only ever does
  `os.kill(orchestrator_pid, …)` — never `os.killpg`. So when SIGTERM escalates to **SIGKILL on the single orchestrator
  PID**, or the orchestrator dies non-gracefully (crash / workspace teardown), the lumberjacks are orphaned and survive.
  Although each lumberjack writes `~/.sase/axe/lumberjacks/<name>/pid`, **nothing ever reads those PID files to kill
  survivors.**
- **PID file removed before exit is confirmed** (`_cleanup_pid_file()` runs right after the SIGTERM in
  `stop_axe_daemon`), widening the desync window.
- **Silent failure on start** — `start_axe_daemon` cannot distinguish "nothing running" from "a live orchestrator holds
  the lock but published no PID"; it just returns `None`.
- **Ephemeral-workspace ownership** — when the orchestrator is started from a workspace venv it launches
  `<workspace>/.venv/bin/sase axe lumberjack run …`; those long-lived daemons are bound to a throwaway clone and outlive
  both the agent/test that started them and the workspace itself.

## Goals

1. `sase axe stop` reliably stops **everything** axe-related — a live orchestrator _and_ any orphaned lumberjacks —
   regardless of the `orchestrator.pid` file's state, and reports what it actually killed.
2. `sase axe start` (CLI and `sase ace`) never deadlocks: it either starts, reports the live PID, or fails with an
   actionable message — never a silent `None`.
3. The orchestrator's liveness has a **single source of truth** (the lock), so stop/start/status agree.
4. Prevent recurrence at the source: an axe daemon started from an ephemeral `sase_<N>` workspace should not bind
   long-lived processes to that clone.

## High-level design

### A. Make the lock the authoritative, self-describing liveness signal

- After acquiring `orchestrator.lock`, **write the orchestrator's PID into the lock file's contents** (the flock and the
  bytes are independent; the holder can still write). On graceful exit, truncate it. This gives an authoritative PID
  tied to the actual lock holder.
- Add a helper (e.g. `read_lock_holder_pid()` / `probe_orchestrator()`) that reports liveness by: (a) trying a
  **non-blocking flock** — if it _fails_, an orchestrator is alive; (b) reading the PID from the lock contents; (c)
  cross-checking the PID file. Treat axe as running if _either_ the lock is held _or_ a recorded PID is alive.
- `get_axe_pid()` is rewritten on top of this probe so stop/start/status never disagree.

### B. `stop_axe_daemon`: robust, group-aware, always sweeps orphans

- Resolve the orchestrator via the probe (lock-holder PID first, then PID file). SIGTERM it for graceful child shutdown;
  on timeout, **SIGKILL the process group** (`os.killpg(os.getpgid(pid), …)`) so children die with it.
- **Always** finish with an orphan sweep independent of the orchestrator: iterate `list_lumberjack_names()` →
  `read_lumberjack_pid()`, and SIGTERM→SIGKILL any still-live lumberjack PIDs (by group where possible), then clear
  their PID files. This catches already-orphaned lumberjacks even when no orchestrator exists.
- Only remove `orchestrator.pid` (and clear the lock contents) **after** confirming exit.
- Return success if it terminated _anything_ (orchestrator or orphans) and surface counts, so the handler can print e.g.
  "stopped orchestrator + 9 lumberjacks" vs. "swept 9 orphaned lumberjacks (no orchestrator)".

### C. `start_axe_daemon`: fail loud, optionally self-heal

- Distinguish the deadlock case: lock not acquirable **and** no live published PID ⇒ a stale/ orphaning orchestrator
  holds the lock. Return a typed result/clear error instead of `None` so callers can tell the user to run
  `sase axe stop` (or `--force`). The `sase ace` start/stop workers and the CLI handler surface that message instead of
  a bare "Failed".

### D. `sase axe stop --force` (`-f`)

- Default `stop` already sweeps orphans (B). Add `-f|--force` to additionally **break a held lock whose holder is
  gone/unkillable** and kill by process-group / `sase axe lumberjack run` match as a last resort, then reset all
  PID/lock state. (CLI conventions: `cli_rules.md` requires a short alias for every public long option and alphabetized,
  colored `-h` output. If this changes the CLI surface, regenerate per-runtime skills per `generated_skills.md`, and
  update the `sase ace` `?` help/footer only if a TUI keymap changes — likely none here.)

### E. Prevent recurrence: don't bind daemons to ephemeral workspaces

Pick one (Option 1 preferred; can land as a follow-up):

1. **Re-exec via the canonical install.** When `sase axe start`/`start_axe_daemon` detects it is running from a
   `sase_<N>` workspace clone (path under the workspaces root, or `$SASE_AGENT`/ workspace env set), spawn the
   orchestrator using the user's canonical `sase` (`~/.local/bin/sase` / uv tool) instead of the workspace venv, so the
   long-lived daemon and its lumberjacks never reference a throwaway clone.
2. **Refuse + warn.** Detect the workspace context and refuse to start (clear message pointing at the canonical
   install), leaving axe a primary-install-only daemon.

## Files in scope

- `src/sase/axe/process.py` — `stop_axe_daemon`, `start_axe_daemon`, `get_axe_pid`, `_cleanup_pid_file`,
  `_wait_for_exit`; new orphan-sweep + group-kill + probe helpers.
- `src/sase/axe/lock.py` — write/read/clear lock-holder PID in the lock file.
- `src/sase/axe/orchestrator.py` — record PID in lock on start, clear on exit; optionally have the orchestrator's
  SIGTERM handler kill its process group as a backstop.
- `src/sase/main/axe_handler.py` — richer `stop` reporting; `-f|--force`; loud start failures.
- `src/sase/main/parser_*.py` (axe parser) — wire `-f|--force` for `axe stop`.
- `src/sase/ace/tui/actions/axe.py` — surface actionable start/stop messages.
- Recurrence guard (E) in `process.py` / `axe_handler.py`.

## Boundary note (Rust core)

Per `rust_core_backend_boundary.md`: this is **OS process supervision** (flock, `os.kill`, `os.killpg`, PID files),
which already lives entirely in Python `src/sase/axe/` and has no `sase_core` counterpart. Keep the fix Python-side;
only the liveness/lifecycle _contract_ would move to Rust if/when a web/CLI frontend needs to match it — out of scope
here.

## Testing

- `stop` with: (a) live orchestrator (graceful), (b) dead orchestrator + orphaned lumberjacks (sweep), (c) **lock held
  but PID file missing** (the reported deadlock), (d) lock held by a dead holder (`--force` breaks it).
- `start` while the lock is held but no PID is published → actionable error, not silent `None`.
- Group-kill: SIGKILL escalation reaps lumberjacks (no orphans left).
- Recurrence guard: starting from a simulated `sase_<N>` workspace path re-execs/ refuses per (E).
- Run `just check` (after `just install`) before finishing.

## Out of scope

- Redesigning per-workspace `SASE_HOME` isolation for axe.
- Changing the lumberjack scheduling model or chop semantics.
