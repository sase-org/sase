---
create_time: 2026-06-27 15:59:52
status: done
prompt: sdd/prompts/202606/q_restart_self_sigterm_fix.md
---
# Fix: `Q` Restart Self-Kills the TUI on the Second Use (Axe Lock-Holder Mis-Attribution)

## Summary

After the new `Q` quit/restart panel shipped, restarting the TUI works **once** and then any subsequent `Q` choice makes
the TUI die with a non-zero exit code and no traceback ("crashes with no error"). This plan fixes the root cause: a
**self-`SIGTERM`**. When the re-exec'd TUI asks axe to stop or restart, the axe code resolves the running orchestrator's
PID as **the TUI's own PID** and sends `SIGTERM` to it. The TUI kills itself.

The fault is not in the restart wiring added by the `Q` panel — that mechanism is sound. The fault is a pre-existing bug
in axe's lifecycle-lock holder resolution that the restart feature newly exposes, because `os.execv` preserves the
process PID across restarts.

## Diagnosis (root cause, verified)

The crash was reproduced under a PTY against the real TUI and traced to the exact syscall. The chain:

1. **The TUI owns the axe lifecycle lock's PID identity.** When the TUI auto-starts (or starts) the axe daemon, it opens
   `~/.sase/axe/orchestrator.lock`, takes an exclusive `flock`, and hands that fd to the daemon via
   `subprocess.Popen(pass_fds=...)` (`src/sase/axe/_process_start.py`). The lock then lives on the daemon's inherited
   (shared) open file description; the TUI closes its own copy (`close_after_handoff` in `src/sase/axe/lock.py`).
   **However, Linux `/proc/locks` attributes that `FLOCK` to the PID that _originally acquired_ it — the TUI — not the
   daemon that now holds the inherited fd.** This was confirmed in isolation: with a parent that acquires the lock and a
   child that inherits it via `pass_fds`, `read_lock_holder_pid()` returns the **parent's** PID, while only the child
   still holds the fd. `_read_recorded_lock_holder_pid()` (the PID the daemon writes into the lock file via
   `write_holder_pid`) correctly returns the daemon — but `read_lock_holder_pid()` consults `/proc/locks` _first_ and
   short-circuits.

2. **`probe_orchestrator()` therefore resolves the orchestrator as the TUI's PID.** In `src/sase/axe/_process_probe.py`,
   `running_pid` is taken from `lock_holder_pid` (the `/proc/locks` answer) when that PID is alive — so it resolves to
   the TUI's PID.

3. **The stop path sends an unguarded `SIGTERM` to that PID.** `stop_axe_daemon_result()`
   (`src/sase/axe/_process_stop.py`) computes `pid = probe.running_pid or probe.lock_holder_pid` and calls
   `_terminate_process(pid, …)`. The orchestrator-termination path uses `prefer_group=False`, which goes straight to
   `os.kill(pid, SIGTERM)`. The self-protection guard (`pgid not in {os.getpgrp(), os.getpid()}`) **only exists on the
   `prefer_group=True` branch**, so the direct kill has no guard. The TUI signals its own PID.

4. **`os.execv` makes this collide across restarts.** The `Q` restart re-execs the TUI in place (`os.execv` in
   `src/sase/main/ace_handler.py`), which **preserves the PID**. So the PID that `/proc/locks` blames for the axe lock
   is exactly the PID of the live TUI in every later generation. When that generation restarts/stops axe, it targets —
   and kills — itself.

**Why "works once, fails the second time":** the first restart's _stop_ targets whatever process previously started the
daemon (often an external `sase axe` process, whose PID `/proc/locks` blames). That same restart's _start_ re-acquires
the lock **under the TUI's PID**, so from then on `/proc/locks` blames the TUI. The _next_ restart's stop self-targets.
When the TUI itself auto-starts the daemon on first launch, the lock is blamed on the TUI immediately and the **first**
restart already self-kills — both timings were reproduced.

**Confirming evidence (all reproduced locally, axe sandboxed via `SASE_HOME` so the real daemon was never touched):**

- `sase ace --no-axe` → restart repeatedly: no crash (the TUI never owns the lock).
- `Q` → "Restart TUI" (option 2, never touches axe): no crash across many generations.
- `Q` → "Restart TUI & axe" (option 3): TUI dies by signal 15. `strace` shows a TUI **worker thread**
  (`clone3(… CLONE_THREAD …)` off the TUI's PID) issue `kill(<TUI_pid>, 0)` then `kill(<TUI_pid>, SIGTERM)` — an
  in-process self-kill from the restart-axe worker.

This also means **option 1 ("Quit & Stop axe")** is affected: it stops axe (resolving its own PID) and would deliver a
self-`SIGTERM`, turning what should be a clean exit into a signal-15 exit — consistent with the user's "with any
option".

## Goals

- Restarting via `Q` (any option) is robust across arbitrarily many consecutive restarts, with axe running and with the
  TUI as the daemon's starter.
- The axe stop/restart machinery never signals the calling process, and resolves the orchestrator to the **daemon's**
  PID, not the lock's original acquirer.
- The fix is correct for the non-TUI callers too (`sase axe stop`, `sase axe restart`), not just the TUI path.

## Non-Goals

- No change to the `Q` panel UX, the three options, labels, keymaps, or the re-exec mechanism — they are correct.
- No change to how the daemon is launched or to `start_new_session`/`pass_fds` handoff semantics (the daemon must keep
  inheriting the lock).

## Design

Two complementary fixes — a correctness fix (resolve the right PID) and a defense-in-depth guard (never kill self). Both
are in the axe backend (`src/sase/axe/`); neither touches the TUI restart wiring.

### 1. Resolve the lock holder to the daemon, not the lock's original acquirer (primary fix)

In `src/sase/axe/lock.py`, `read_lock_holder_pid()` currently prefers the `/proc/locks` answer
(`_find_proc_lock_holder_pid()`) and falls back to the recorded PID. The `/proc/locks` answer is unreliable precisely
because of the `pass_fds` handoff: it reports the acquirer (the TUI), while the **recorded** PID (written by the daemon
via `write_holder_pid`) is authoritative for "who is the orchestrator".

Make the resolution refuse a `/proc/locks` PID that is the **calling process itself** (it can never be the daemon — the
caller is asking _about_ the daemon), preferring the recorded daemon PID in that case. Concretely: if
`_find_proc_lock_holder_pid()` returns `os.getpid()`, treat it as "unknown from `/proc/locks`" and use
`_read_recorded_lock_holder_pid()`. Keep `/proc/locks` authoritative for all other (genuinely external) holders so
crash-staleness handling is unchanged. Liveness of whatever PID is returned is still validated downstream in
`probe_orchestrator()`.

This restores correct behavior for **all three options**: the stop now targets the real daemon (e.g. the previous
orchestrator `O2`), so "stop axe" and "restart axe" actually stop/restart the daemon instead of the TUI.

### 2. Never signal the calling process (defense in depth)

In `src/sase/axe/_process_stop.py`, extend `_send_signal()` so the **direct** `os.kill(pid, sig)` path also refuses to
signal `os.getpid()` (today only the group path is guarded). If a future resolution bug ever points the stop at the
caller's own PID again, the worst case is "failed to stop" — never "killed the UI". This guard is cheap, local, and
makes the whole stop subsystem self-safe regardless of caller.

Consider treating "resolved PID == our own PID" as a _no-orchestrator_ signal (so the stop reports nothing to stop
rather than silently skipping), keeping `AxeStopResult` honest.

### 3. (Evaluate, likely keep) the `prefer_group=False` orchestrator termination

The orchestrator is terminated with `prefer_group=False`, which is why the existing group-guard never ran. The two fixes
above make the resolved PID correct and add a same-PID guard, so this can stay as-is. The plan should note it explicitly
so the reviewer agrees the group path isn't the right lever here (the daemon legitimately runs in its own
session/process group, so a group kill is not what we want for the orchestrator PID).

## Files Likely Touched

- `src/sase/axe/lock.py` — `read_lock_holder_pid()` ignores a `/proc/locks` hit that equals `os.getpid()` and prefers
  the recorded daemon PID.
- `src/sase/axe/_process_stop.py` — `_send_signal()` (and/or `_terminate_process`) never signals `os.getpid()` on the
  direct-kill path; resolution treats own-PID as no-daemon.
- Tests under `tests/axe/` (new/extended) — see below.

No changes expected in `src/sase/ace/tui/**` or `src/sase/main/ace_handler.py`.

## Testing

- **Unit — lock-holder attribution:** a test that mirrors the daemon handoff (acquire the lifecycle lock, hand the fd to
  a child via `pass_fds`, `close_after_handoff` in the parent) and asserts `read_lock_holder_pid()` returns the
  **child** (daemon) PID, never the parent's — the exact reproduction that exposed the bug. Cover both "recorded PID
  present" and a fallback case.
- **Unit — self-kill guard:** assert `_send_signal(os.getpid(), SIGTERM)` (direct path) does **not** raise and does
  **not** deliver the signal (monkeypatch `os.kill`/install a `SIGTERM` handler and assert it never fires), and that
  `stop_axe_daemon_result()` with a probe that resolves to our own PID reports "nothing stopped" rather than killing the
  caller.
- **Regression — stop targets the real daemon:** with a sandboxed `SASE_HOME` and a stub/dummy daemon holding the lock
  via `pass_fds`, `stop_axe_daemon_result()` resolves and signals the **daemon** PID, not the caller.
- **Manual / `/verify` (sandboxed `SASE_HOME` so the real daemon is untouched):** drive `sase ace` under a PTY, press
  `Q` → option 3 several times in a row, and confirm the TUI survives every restart (no signal-15 exit). Repeat for
  option 1 (clean exit 0, axe actually stopped) and option 2 (already known-good). A PTY repro harness already exists
  from the diagnosis and can be adapted.
- `just check` (after `just install`) before finishing.

## Risks & Mitigations

- **Changing `read_lock_holder_pid()` ordering affects crash-recovery semantics.** Mitigation: only _override_ the
  `/proc/locks` answer when it equals `os.getpid()` (an impossible "the daemon is me, the prober" case); leave all
  genuinely-external holders authoritative, and keep the downstream liveness validation in `probe_orchestrator()`.
- **A stale recorded PID could be returned when we fall back.** Mitigation: `probe_orchestrator()` already validates
  liveness (`is_process_running`) and cleans stale PID files, so a dead recorded PID is filtered out exactly as today.
- **Over-broad self-guard could mask a legitimate "kill my own group" case.** Mitigation: the guard is scoped to the
  single-PID direct-kill equalling `os.getpid()`; the group path keeps its existing, separate guard.
- **The two fixes are partly redundant.** That is intentional: fix #1 makes behavior correct; fix #2 ensures a future
  resolution regression can never again kill the UI.
