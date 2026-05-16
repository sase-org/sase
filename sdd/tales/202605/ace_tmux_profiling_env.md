---
create_time: 2026-05-16 15:58:44
status: done
prompt: sdd/prompts/202605/ace_tmux_profiling_env.md
---
# Plan: Enable TUI Profiling Env Vars for `sase ace --tmux`

## Goal

When an agent launches the TUI via `sase ace --tmux`, the new tmux window's `sase ace` process must run with
`SASE_TUI_TRACE=1` and `SASE_TUI_PERF=1` set in its environment. This guarantees that the trace/perf JSONL files
(`~/.sase/perf/tui_trace.jsonl` and `~/.sase/perf/tui_jk.jsonl`) are populated for every agent-driven TUI session
without the agent having to remember to export them.

Profiling instrumentation in the TUI is already wired up; this change is purely about who is responsible for setting the
env vars at launch time. Today: nobody — agents that forget end up with empty trace files. After this change: the
`--tmux` launcher always sets them by default.

## User-visible behavior

The output contract of `sase ace --tmux` is unchanged:

```
$ sase ace --tmux 'my-query'
sase_tmux_window=sase_tmux_3
sase_tmux_session=agent-session-7
sase_tmux_pid=82317
```

The only observable difference: after the agent uses the TUI inside that window, `~/.sase/perf/tui_trace.jsonl` and
`~/.sase/perf/tui_jk.jsonl` contain records for the session. Without `--tmux` (regular interactive use) nothing changes
— humans still get unprofiled TUI sessions unless they opt in by exporting the vars themselves.

## Key design decision: who sets the env vars

Two candidate mechanisms, both viable:

1. **`tmux new-window -e KEY=VAL`** — tmux propagates per-window env vars to the child process. Clean, leaves the
   relaunch shell command untouched, and is documented behavior. Requires bumping the `subprocess.run` command in
   `_claim_window` to inject `-e SASE_TUI_TRACE=1 -e SASE_TUI_PERF=1` before the relaunch positional.
2. **Prepend `KEY=VAL` to the shell command** in `_build_relaunch_cmd` — works but mixes "env" and "exec" concerns in a
   single string and is slightly harder to test.

**Pick option 1 (`tmux new-window -e ...`).** It keeps `_build_relaunch_cmd` purely about the Python exec line and makes
the env-var concern unit-testable by inspecting the constructed tmux argv vector, which is exactly the surface the
existing tests already assert on.

## Override semantics: respect the caller

If the caller (or the agent's shell) has explicitly exported `SASE_TUI_TRACE` or `SASE_TUI_PERF` already — including to
`0`, to disable — we should not stomp on that. Behavior:

- If the env var is **unset** in the launcher process, inject it as `=1` into the new tmux window.
- If the env var is **already set** (any value, including `0` or `""`), pass through the caller's value unchanged.
  tmux's `-e KEY=VAL` is the right primitive for this: we just forward what we read from `os.environ`.

Rationale: lets a developer running `SASE_TUI_TRACE=0 sase ace --tmux …` actually get a quiet session, e.g. when
diagnosing whether the JSONL writes themselves are masking a perf regression. Default-on, explicit-off.

## Files to change

### 1. `src/sase/main/ace_tmux.py`

Add a helper that resolves the env-var pairs to inject:

```python
_PROFILING_ENV_DEFAULTS = {
    "SASE_TUI_TRACE": "1",
    "SASE_TUI_PERF": "1",
}

def _profiling_env_args() -> list[str]:
    """Return ``-e KEY=VAL`` args for ``tmux new-window`` so the spawned TUI
    runs with profiling instrumentation enabled. Respects values already set
    in the launcher's environment."""
    args: list[str] = []
    for key, default in _PROFILING_ENV_DEFAULTS.items():
        value = os.environ.get(key, default)
        args.extend(["-e", f"{key}={value}"])
    return args
```

Wire the result into `_claim_window`'s tmux invocation:

```python
"tmux", "new-window", "-d",
*_profiling_env_args(),
"-n", window_name,
"-t", f"{session}:",
"-P", "-F", "#{session_name}:#{window_id} #{pane_pid}",
relaunch_cmd,
```

The constants are module-level rather than per-call so the test suite can reach for them if it needs to assert on the
canonical set.

### 2. `tests/main/test_ace_tmux.py`

Three new tests; the existing `_FakeTmux` infrastructure already records every `tmux` argv vector, so all assertions are
surface-level:

1. `test_sets_profiling_env_vars_by_default` — invoke with `SASE_TUI_TRACE` / `SASE_TUI_PERF` unset (use
   `monkeypatch.delenv(..., raising=False)`); assert the recorded `new-window` argv contains `-e SASE_TUI_TRACE=1` and
   `-e SASE_TUI_PERF=1`.
2. `test_respects_explicit_profiling_env_var` — `monkeypatch.setenv("SASE_TUI_TRACE", "0")`; assert the `new-window`
   argv contains `-e SASE_TUI_TRACE=0` (and `SASE_TUI_PERF=1`, since that one was unset).
3. `test_profiling_env_args_precede_window_name` — sanity check that the `-e` args come before `-n` so they apply to the
   new window, not as relaunch-command operands. Easy to get wrong; cheap to lock down.

Also update the three existing assertions on `new-window` argv (`test_returns_sase_tmux_1_on_fresh_session`,
`test_skips_occupied_window_numbers`, `test_strips_tmux_flags_from_relaunch_argv`,
`test_inside_tmux_uses_current_session`) so they continue to work with the longer argv vector. None of those tests
assert on the absolute index of `-n`/`-t` — they all locate the flag by name — so the only change needed is verifying
that the relaunch command is still the trailing positional. A quick read confirms this.

### 3. Documentation: `docs/ace.md`

`docs/ace.md` doesn't currently document `--tmux` at all (the SDD tale that added the flag deferred docs). This plan
does _not_ add that documentation — that's a separate concern with its own scope (CLI table entry, agent example, etc.).
We confine the doc footprint here to a single mention in the perf runbook:

`docs/perf_runbook.md` — add a one-line note under the existing "Enabling traces" section:

> Agents that launch the TUI via `sase ace --tmux` get `SASE_TUI_TRACE=1` and `SASE_TUI_PERF=1` injected automatically;
> export the variable to `0` before invoking to opt out.

If `docs/perf_runbook.md` doesn't have an obvious section for this, skip and rely on the inline comment in `ace_tmux.py`
instead. The behavior is self-documenting via the env var names.

### 4. SDD tale

After the implementation lands, file a short tale at `sdd/tales/202605/ace_tmux_profiling_env.md` linking back to this
plan. Standard format with the `prompt:` / `status:` frontmatter the other recent tales use.

## What we are NOT changing

- **`SASE_TUI_TRACE_PATH` / `SASE_TUI_PERF_PATH`** — these stay at their defaults (`~/.sase/perf/tui_trace.jsonl`,
  `~/.sase/perf/tui_jk.jsonl`). Per-window log paths would be useful if many agents run TUIs concurrently and we wanted
  to attribute samples back to a specific window, but JSONL is append-safe across processes on Linux for small writes
  and the schema already includes enough context (`current_tab`, action). Revisit only if cross-agent attribution
  becomes a real need.
- **Non-tmux launches.** Interactive humans running `sase ace` without `--tmux` are unaffected. They can still opt in
  via `SASE_TUI_TRACE=1 sase ace …` exactly as today. Adding implicit profiling for humans would create surprise
  (unbounded JSONL growth, write fan-out) for zero workflow gain.
- **The flag set.** Just the two env vars the user named — `SASE_TUI_TRACE` and `SASE_TUI_PERF`. If we discover during
  implementation that there's a third profiling toggle (e.g. a `SASE_TUI_PERF_WINDOW` for rolling window size, or future
  instrumentation flags), the `_PROFILING_ENV_DEFAULTS` dict is the obvious extension point.
- **Help/keybinding docs.** Per `src/sase/ace/AGENTS.md`, the `?` help modal documents in-TUI keybindings, not CLI
  options or env vars; nothing to update there.

## Rollout / verification

1. `just install` (workspace-fresh-clone hygiene).
2. `just check`.
3. Manual smoke from inside tmux:
   ```
   rm -f ~/.sase/perf/tui_trace.jsonl ~/.sase/perf/tui_jk.jsonl
   sase ace --tmux 'foo'
   # switch into the new window, navigate around with j/k, quit with q
   wc -l ~/.sase/perf/tui_trace.jsonl ~/.sase/perf/tui_jk.jsonl
   # both should be > 0
   ```
4. Manual opt-out smoke:
   ```
   SASE_TUI_TRACE=0 SASE_TUI_PERF=0 sase ace --tmux 'foo'
   # exercise the TUI, quit, confirm the JSONL files did not grow.
   ```
5. Confirm a regular `sase ace 'foo'` (no `--tmux`) with the env vars unset still produces no JSONL output — nothing
   should have changed for human use.
