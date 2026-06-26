# TUI startup-adjacent freeze on 2026-06-26

## Scope

Investigate the report that the ACE TUI froze and became unresponsive for about
a minute shortly after startup on Friday, June 26, 2026. This consolidates the
two independent research notes and rechecks their claims against the local logs
and source.

Required TUI performance context was reviewed with:

```bash
sase memory read tui_perf.md --reason "Need TUI performance context before consolidating startup-freeze research"
```

## Conclusion

The best match for the reported freeze is the `2026-06-26 10:18:02 EDT` stall
record for PID `739822`. It recovered after `73.020s`, matching "about a
minute."

The captured stack does not point at startup initialization. It points at an
Agents-tab `e` / `edit_spec` action opening a completed agent chat in an
external editor:

```text
action_edit_spec
  -> _open_agent_chat
  -> _open_agent_chat_paths
  -> subprocess.run([editor, *chat_paths], check=False)
  -> subprocess.wait/os.waitpid
```

That call is wrapped in `with self.suspend()`, so Textual intentionally hands
terminal control to the editor and stops reading input/output until the editor
exits. The event loop is parked for the editor lifetime; the watchdog currently
records that as a generic TUI stall.

## Evidence

The installed runtime that produced the logs is:

| Item | Value |
| --- | --- |
| executable | `/home/bryan/.local/bin/sase` |
| `sase` version | `0.5.0+167.g2479fbd4b` |
| runtime source | `/home/bryan/projects/github/sase-org/sase/src/sase` |
| runtime commit | `2479fbd4bc7da580d12e06338388e93d6b2b6dd5` |

The human-readable log gives the duration:

```text
2026-06-26 10:18:02 WARNING ... TUI event loop stall detected: 5.001s pid=739822
2026-06-26 10:19:10 WARNING ... TUI event loop recovered after 73.020s
```

The structured JSONL record at `~/.sase/logs/tui_stalls.jsonl` gives the cause:

| Field | Value |
| --- | --- |
| local time | `2026-06-26T10:18:02.004953-04:00` |
| activity state | `session_start` |
| current tab | `agents` |
| current index | `2` |
| last recorded action | `launch` / `bob-cli` |
| last keypress age | `4.706s` |
| captured blocking class | external subprocess/editor wait |

`activity_state=session_start` explains why this felt startup-related, but it
does not mean startup code was blocking. The watchdog stack shows that an early
session key action had already reached the editor-open path.

Relevant source in the runtime checkout:

```text
src/sase/ace/tui/actions/agents/_panel_detail.py
47: def action_edit_spec(self) -> None:
49:     if self.current_tab == "agents":
50:         self._open_agent_chat()
...
77: self._open_agent_chat_paths([os.path.expanduser(agent.response_path)])
...
119: def _open_agent_chat_paths(self, chat_paths: list[str]) -> None:
121:     editor = os.environ.get("EDITOR") or "nvim"
122:     with self.suspend():
123:         subprocess.run([editor, *chat_paths], check=False)
```

The key is easy to hit:

```text
src/sase/ace/tui/bindings.py:40
Binding("e", "edit_spec", "Edit Spec", show=False)

src/sase/default_config.yml:68
edit_spec: "e"
```

Textual's installed `App.suspend()` implementation publishes
`app_suspend_signal`, suspends application mode, yields to the caller's
synchronous code, resumes application mode, publishes `app_resume_signal`, and
refreshes. Its docstring explicitly says the app stops reading input and
emitting output while inside the block. That is the intended behavior for a
terminal editor, but the SASE watchdog is not suspend-aware yet.

## What this was not

This was not the older artifact-index startup-maintenance freeze. No stack for
the June 26 minute-scale stall passed through
`sync_dismissed_agent_artifact_index`, active-tier terminalization, or
`_on_auto_refresh`.

This was not the June 25 detail-header live `git diff` slowdown. The stack went
directly through the external editor path.

This was not j/k navigation or row rendering. The loop was blocked in
`subprocess.run(...).wait()`.

There was a second startup-adjacent stall in the same process at
`2026-06-26 10:28:43 EDT`, recovered after `15.005s`. That one was separate:
the artifact viewer was suspended and waiting in
`graphics/_viewer_loop.py::_read_single_key -> os.read(fd, 1)`.

## Secondary telemetry

Across all 56 structured stall records currently in `tui_stalls.jsonl`, the
classes are:

| Count | Class |
| ---: | --- |
| 40 | external subprocess/editor waits under suspend |
| 7 | artifact/image viewer key waits under suspend |
| 6 | synchronous Rust index terminalization calls |
| 2 | synchronous Rust index upsert calls |
| 1 | synchronous Rust dismissed-index replacement |

So 47 of 56 records are suspend-owned terminal handoffs that should not be
reported as generic event-loop freezes. The remaining 9 Rust-index records are
genuine accidental loop-thread stalls.

This resolves the only material conflict between the two intermediate notes:
the smaller June 25-26 subset is useful local context, but the full 56-record
classification is the better summary of watchdog pollution. The root cause of
the reported June 26 freeze is unchanged in both notes.

The TUI performance memory's core rule still applies: do not block the Textual
event loop. For external terminal tools, though, the correct UX may require
temporarily suspending Textual instead of simply moving the process wait to a
background thread. The missing piece is classification and user feedback, not
blind offloading of terminal-owning editors.

## Recommended solution

Make external-tool suspension explicit and make the stall watchdog
suspend-aware.

1. Add pause/resume support to `_EventLoopStallWatchdog`: while paused, skip
   generic stall recording; on resume, reset `_last_progress_mono`, clear any
   pending suspend-derived stall state, and let normal loop progress resume from
   the current monotonic time.
2. Wire that support to Textual's suspend lifecycle. The installed Textual
   runtime exposes instance signals `app_suspend_signal` and
   `app_resume_signal`; subscribe after the watchdog is created in
   `actions/startup.py`, or centralize SASE-owned terminal handoffs in a helper
   such as `suspend_external_tool(...)` that calls the watchdog guard around
   `with self.suspend():`.
3. Route editor and artifact-viewer handoffs through that helper, recording
   them as `external_tool_wait` telemetry with action/tool metadata and elapsed
   time instead of generic TUI freezes. Show a short pre-suspend status such as
   "Opening chat in editor..." so accidental `e` presses are obvious.
4. Add focused tests for the Agents `edit_spec` path and artifact viewer path:
   an intentional suspend should not create a generic stall record, and resume
   should reset watchdog timing.

Follow-up work should separately fix the genuine stalls surfaced by the same
telemetry: move Rust index maintenance calls off the event-loop thread with the
existing tracked/background task patterns. The artifact viewer should either
remain classified as an intentional suspend-owned terminal viewer or be reworked
so its key-read loop no longer runs on the Textual loop; it should not keep
appearing as a generic TUI freeze.
