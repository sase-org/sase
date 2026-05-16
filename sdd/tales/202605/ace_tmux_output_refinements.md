---
create_time: 2026-05-16 15:29:20
status: done
prompt: sdd/prompts/202605/ace_tmux_output_refinements.md
---
# Plan: Refine `sase ace --tmux` Output Contract

## Goal

Two small but useful adjustments to the `sase ace --tmux` output:

1. **Drop the redundant `sase_tmux_target` line.** A caller already gets `sase_tmux_session` and `sase_tmux_window`; the
   tmux target `<session>:<window>` is trivially `f"{session}:{window}"`. Emitting it as a third variable adds surface
   without information.

2. **Make `sase_tmux_pid` point at the `sase ace` Python process** (the one running inside the new tmux window), not at
   the launching parent. Today it's `os.getpid()`, which is the short-lived parent that exits ~immediately after
   spawning the window — useless for `strace`, `py-spy`, `/proc/<pid>/...`, etc. The whole point of exposing a PID is so
   an agent can attach a profiler/tracer to the live TUI.

## Updated user-visible behavior

```
$ sase ace --tmux 'my-query'
sase_tmux_window=sase_tmux_3
sase_tmux_session=agent-session-7
sase_tmux_pid=82317      # PID of `python -m sase ace …` running inside the window
$
```

Three lines instead of four. The PID is now attachable.

## How to resolve the ace PID reliably

The relaunched Python process runs inside the new tmux window. To learn its PID, the launching parent has two viable
sources:

- **A**: tmux's own `#{pane_pid}` format variable on the newly-created window.
- **B**: have the child write its PID to a temp file and have the parent read it.

**Choose A.** It's a single tmux query co-located with the `new-window` call we already make. (B) requires sync
primitives, error handling on missing files, cleanup — far heavier for the same answer.

### The catch with `#{pane_pid}` and how to handle it

`tmux new-window <cmd> <arg1> <arg2>` joins its trailing args into one shell command and runs them via `/bin/sh -c`.
That means `#{pane_pid}` is the PID of `/bin/sh`, **not** of the Python interpreter we actually want. The shell is also
a quoting hazard for any forwarded arg with spaces or shell metacharacters.

Fix both at once by passing a single shell command string built with `shlex.join`, prefixed with `exec`:

```python
import shlex
shell_cmd = "exec " + shlex.join([sys.executable, "-m", "sase", *forwarded])
```

- `shlex.join` quotes each argv element correctly, removing the quoting hazard.
- `exec` makes the shell replace itself with the Python interpreter, **preserving the PID**. So `#{pane_pid}` then
  reports the PID of `python -m sase ace ...` — exactly the one an agent wants to `strace`/`py-spy`.

The PID is captured atomically by extending the existing `-P -F` format on `new-window`:

```
-F '#{session_name}:#{window_id} #{pane_pid}'
```

Two whitespace-separated fields. Parse with a single `.split()` on the output line. No extra `tmux display-message`
round-trip, so no new race.

## Files to change

### 1. `src/sase/main/ace_tmux.py`

- `_build_relaunch_argv()` → rename / refactor to return a single shell command string (`exec <quoted argv>`). Move the
  `shlex.join` here.
- `_claim_window(session, relaunch_cmd)`:
  - Pass the single shell-cmd string as the final positional to `tmux new-window` (no `--` splitting).
  - Extend `-F` format to `'#{session_name}:#{window_id} #{pane_pid}'`.
  - Parse the two fields out of `result.stdout`. Return `(window_name, target, pane_pid)`.
- `launch_ace_in_tmux()` → unpack the new triple, pass `pane_pid` to `_print_target`.
- `_print_target(session, window_name, pane_pid)`:
  - Drop the `target` parameter and its line.
  - Replace `os.getpid()` with the parsed `pane_pid`.

### 2. `tests/main/test_ace_tmux.py`

- `_FakeTmux.__call__` `new-window` branch: return stdout in the two-field format (`"{target} {pid}\n"`). Add a
  synthesized fake PID counter so different windows get distinct PIDs.
- `test_returns_sase_tmux_1_on_fresh_session`:
  - Assert `sase_tmux_target` is **not** present.
  - Assert `sase_tmux_pid=<the fake pane pid>` (a specific number), not just `"sase_tmux_pid="` presence — this locks in
    that we report the child's PID, not the parent's.
- `test_strips_tmux_flags_from_relaunch_argv`:
  - The relaunch is now a single shell command string. Update the assertion: take the trailing positional from the
    `tmux new-window` argv and check it starts with `exec ` and, when parsed with `shlex.split()`, equals
    `[sys.executable, "-m", "sase", "ace", "my-query", "--tab", "agents", "--profile"]`.
- Other tests (`test_inside_tmux_uses_current_session`, `test_outside_tmux_creates_agents_session`,
  `test_outside_tmux_creates_session_when_missing`, `test_skips_occupied_window_numbers`,
  `test_exits_with_message_when_tmux_missing`) — touch only as needed for the `new-window` stdout shape change.

## Why not also write the PID from the child for safety?

`#{pane_pid}` after `exec` is reliable: the kernel guarantees PID preservation across `execve`, and tmux reads
`pane_pid` from its own fork bookkeeping, so the value is set the instant tmux returns from `new-window`. No race, no
temp file, no cleanup. Adding a "child also writes its PID" belt-and-suspenders path would just be code that never runs.

## Out of scope

- Changes to the `--tmux` flag itself, its parser entry, the `ace_handler.py` dispatch, or the in-tmux vs. outside-tmux
  session resolution. None of those need to move.
- Cleanup of `sase_tmux_<N>` windows. Still happens naturally when ace exits.
- Any documentation update beyond the help string — the `--tmux` help text already says "print its session/window target
  on stdout" which is still accurate.

## Rollout / verification

1. `just install` (fresh workspace).
2. `just check` after the change.
3. Manual smoke test inside tmux:
   ```
   sase ace --tmux 'foo'
   # Three key=value lines, no sase_tmux_target.
   # Verify the PID belongs to python:
   ps -p <printed-pid> -o comm=
   # → 'python' (or similar), NOT 'sh' and NOT the original sase parent.
   py-spy dump --pid <printed-pid>   # should attach successfully
   ```
4. Manual smoke test outside tmux (`TMUX= sase ace --tmux 'foo'`): same PID expectation.
5. Confirm constructing the target by hand (`<session>:<window>`) and using it with `tmux send-keys` still drives the
   TUI.
