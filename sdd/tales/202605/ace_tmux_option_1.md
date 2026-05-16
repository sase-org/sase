---
create_time: 2026-05-16 15:13:54
status: done
prompt: sdd/prompts/202605/ace_tmux_option_1.md
---
# Plan: `sase ace --tmux` Option

## Goal

Add a new `--tmux` (`-T`) option to `sase ace` so that an agent can launch the TUI in a fresh tmux window named
`sase_tmux_<N>` (lowest free positive integer) and receive — on stdout — the exact information it needs to:

1. Send emulated keypresses to the running TUI via `tmux send-keys`.
2. Capture the current visible TUI contents via `tmux capture-pane`.

The flag is intended to be used from agents that need to script/observe the ace TUI; for human use the existing default
behavior (`app.run()` inline) is unchanged.

## User-visible behavior

```
$ sase ace --tmux 'my-query'
sase_tmux_window=sase_tmux_3
sase_tmux_session=agent-session-7
sase_tmux_target=agent-session-7:sase_tmux_3
sase_tmux_pid=82317
$
```

- Window name is always `sase_tmux_<N>` where `<N>` is the lowest positive integer not currently used by another window
  in the target session.
- Output goes to stdout, one `key=value` per line — trivially parseable from a shell or from Python without taking a
  dependency on JSON.
- The new window runs `sase ace` with the same arguments as the caller minus `--tmux` (no infinite recursion).
- The caller's terminal is not stolen: tmux opens the window detached (`-d`), so the agent's own foreground session
  keeps control.
- Process exits 0 immediately after the window starts; the TUI lives in tmux.
- Errors (no tmux, no `$TMUX`, etc.) print a human-readable message to stderr and exit non-zero.

## Why a separate flag (not a separate command)

Keeps the surface tiny and reuses all of `ace`'s existing option plumbing (query, `--tab`, `--profile`,
`--vcs-provider`, etc.) by re-executing `sys.argv` minus `--tmux` inside the new tmux window. Agents already know how to
invoke `sase ace`; this only adds one flag.

## Tmux context: where does the window get created?

Two cases to handle:

1. **Inside tmux already (`$TMUX` is set).** Create the new window inside the _current_ session. This is the expected
   common case — sase agents run from terminal panes inside the user's existing tmux session, so the new ace TUI lives
   next to the agent's own window and the user can flip to it with normal tmux navigation. The session name is read from
   `tmux display-message -p '#{session_name}'`.

2. **Not inside tmux (`$TMUX` unset).** Create a _new detached session_ with a single window named `sase_tmux_<N>`.
   Session name is `sase_ace_agents` (created on demand). This keeps the feature usable from environments without a
   wrapping tmux (CI, remote-exec agents, etc.).

In both cases the output contract is identical (`session`, `window`, `target`), so callers do not branch.

## Race-free window naming

Several parallel agents may invoke `--tmux` at the same moment, so naïvely "list windows, pick lowest unused N, create
window" has a TOCTOU race.

Use tmux itself as the arbiter: tmux refuses to create a duplicate window name and exits non-zero. Loop:

```
for N in 1, 2, 3, ...:
    rc = tmux new-window -d -n sase_tmux_N -t <session> \
         -P -F '#{session_name}:#{window_id}' -- <relaunch-cmd>
    if rc == 0: success, capture printed target; break
    # Distinguish "name in use" from real errors by re-listing windows
    # — if sase_tmux_N now exists, retry with N+1; otherwise propagate.
```

Cap the loop at e.g. 1000 to prevent pathological infinite loops, and bail with a clear error if we hit the cap.

The `-P -F` flags make tmux print the new window's target on stdout, which we forward in our output (rather than
re-querying tmux afterward, which would re-introduce a race).

## What command runs inside the new window

The new window runs the same Python process that was invoked, with `--tmux` stripped from `sys.argv`:

```
relaunch = [sys.executable, "-m", "sase", "ace", *argv_without_tmux]
```

Using `sys.executable` ensures we stay inside the same workspace's venv (important per `memory/short/workspaces.md`).

We pass the relaunch as the trailing positional command to `tmux new-window` so tmux exec's it directly (no shell
interpolation, no quoting hazard).

## Files to change

### 1. `src/sase/main/parser_ace.py`

Add the `--tmux` flag alphabetically (between `--tab` and `--no-axe`):

```python
ace_parser.add_argument(
    "-T",
    "--tmux",
    action="store_true",
    help="Launch the TUI in a new tmux window named 'sase_tmux_<N>' and "
    "print its session/window target on stdout. Useful for agents that "
    "need to drive the TUI via 'tmux send-keys' and observe it via "
    "'tmux capture-pane'.",
)
```

(`-T` is currently unused among ace short flags.)

### 2. `src/sase/main/ace_handler.py`

At the very top of `handle_ace_command`, before any TUI imports or state mutation:

```python
if getattr(args, "tmux", False):
    from sase.main.ace_tmux import launch_ace_in_tmux
    launch_ace_in_tmux(args)
    sys.exit(0)
```

Doing it first means we never spin up Textual, axe, profilers, etc. in the caller process when we're just going to fork
into tmux.

### 3. `src/sase/main/ace_tmux.py` (NEW)

Single small module that owns the tmux interaction. Roughly:

```python
def launch_ace_in_tmux(args: argparse.Namespace) -> None:
    _require_tmux_binary()
    session = _resolve_or_create_session()
    relaunch = _build_relaunch_argv()  # sys.argv minus '--tmux'/'-T'
    window_name, target = _claim_window(session, relaunch)
    _print_target(session, window_name, target)
```

Helpers:

- `_require_tmux_binary()` — `shutil.which("tmux")` check; raises a clean error message + exits 2 otherwise.
- `_resolve_or_create_session()` — returns the session name. Uses `$TMUX` detection; ensures `sase_ace_agents` exists
  when not inside tmux (idempotent `tmux new-session -d -s sase_ace_agents -n placeholder` and then we just add windows
  to it; the placeholder can be killed when the real window opens or left as-is — pick "leave it" for simplicity,
  matching the user's existing per-project tmux conventions).
- `_build_relaunch_argv()` — filters `sys.argv` for `--tmux`/`-T`. Returns the full argv to exec inside the new window,
  prefixed with `sys.executable -m sase`.
- `_claim_window(session, relaunch)` — the race-free loop described above. Returns `(window_name, "session:window_id")`.
- `_print_target(...)` — writes the `key=value` lines to stdout.

This isolation keeps `ace_handler.py` unchanged in spirit and gives the new behavior a small, easily-tested surface.

### 4. Tests — `tests/main/test_ace_tmux.py` (NEW)

Test approach: mock `subprocess.run` (mirroring the patterns already used by existing tmux-action tests in this repo)
and assert on the constructed argv vectors and the parsed output, rather than spinning up a real tmux. Cover:

- Returns `sase_tmux_1` on a fresh empty session.
- Skips occupied numbers — given `sase_tmux_1` already exists, claims `sase_tmux_2`.
- Strips `--tmux` and `-T` from the relaunch argv (and only those — leaves the query and other flags alone).
- Inside-tmux path uses current session; outside-tmux path creates/uses `sase_ace_agents`.
- Exits non-zero with a useful stderr message when `tmux` binary is missing.

### 5. `src/sase/ace/tui/modals` help popup — _NOT_ changed

The `?` help modal in the TUI documents in-TUI keybindings, not CLI options. The `--tmux` flag has no in-TUI behavior,
so per the rule in `src/sase/ace/AGENTS.md` ("conditional keymaps belong to the footer; global behaviors to the help
modal"), nothing in the modal needs to move. This is worth re-checking once the implementation is in: if there is any
_user-facing_ CLI option reference embedded in the help modal we'd update it, but a grep shows the modal is purely
keybinding-oriented.

## Out of scope

- Any logic for the calling agent to actually emit `tmux send-keys` / `tmux capture-pane`. That is the agent's
  responsibility once `--tmux` has handed it `target`.
- Cleanup of `sase_tmux_<N>` windows. They die naturally when their `sase ace` process exits, which already happens on
  `q`/Ctrl-C. Adding active cleanup would just complicate the contract.
- A `--tmux-session NAME` override for picking the destination session. Defer until someone actually needs it; current
  two-case detection covers observed agent workflows.

## Rollout / verification

1. `just install` (per workspace conventions).
2. `just check` after the change.
3. Manual smoke test from inside tmux:
   ```
   sase ace --tmux 'foo'
   # window 'sase_tmux_1' appears in current session; output parseable.
   tmux send-keys -t <printed-target> q
   # TUI exits, window goes away.
   ```
4. Manual smoke test without `$TMUX`:
   ```
   TMUX= sase ace --tmux 'foo'
   tmux attach -t sase_ace_agents
   ```
5. Parallel race smoke test: spawn 10 `sase ace --tmux` invocations simultaneously and confirm the assigned `N`s are
   unique and contiguous.
