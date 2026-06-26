# TUI "Startup Freeze" Investigation — Editor Suspend & Watchdog False Positives

**Date:** 2026-06-26
**Author:** research agent
**Trigger:** User reported the `sase ace` TUI froze and was unresponsive for "about a
minute" immediately after starting it up.

---

## TL;DR

The freeze was **not** caused by startup/initialization work. The TUI's own
event-loop stall watchdog captured the exact blocking call stack: within ~5s of
launch, a keypress (`e`) opened a completed agent's chat transcript in an external
editor (`$EDITOR`, defaulting to `nvim`). That happens via
`App.suspend()` + a **synchronous** `subprocess.run([...])`, which intentionally
blocks the Textual event loop for the entire editor session. The "~1 minute freeze"
was the editor being open for ~73s before it was closed.

This is *working as designed* (suspend correctly hands the terminal to the editor),
but it is **misreported** as a TUI "stall/freeze" because the watchdog has no notion
of intentional suspend. It is also easy to trigger *accidentally* right after
startup because `e` is a single, unguarded key.

A secondary finding fell out of the same telemetry: **40 of 56** recorded stalls are
editor suspends (false positives), which drown out the **genuinely actionable**
stalls — synchronous Rust-core index calls and a blocking image-viewer read loop
that *do* freeze the event loop.

---

## How the cause was found

SASE ships an always-on **event-loop stall watchdog** for the TUI
(`src/sase/ace/tui/util/stall_watchdog.py`). A daemon thread schedules a cheap
beacon onto the Textual loop every 0.5s; if the beacon stops running for ≥5s, the
watchdog captures the **loop thread's full Python stack from outside the blocked
loop** and appends a durable JSONL record (`sase.logs.log_tui_stall`).

Two artifacts exist:

| File | Content |
|---|---|
| `~/.sase/logs/tui.log` | Human-readable `WARNING` lines: "stall detected" / "recovered after Ns" |
| `~/.sase/logs/tui_stalls.jsonl` | Structured records **including the captured stack trace** + context |

The `tui.log` warnings told us *when* and *how long*; the JSONL told us *what was
blocking*.

### Matching the report to a record

The most recent startup-time stall in `tui.log` matches the report exactly:

```
2026-06-26 10:18:02 WARNING ... TUI event loop stall detected: 5.001s pid=739822
2026-06-26 10:19:10 WARNING ... TUI event loop recovered after 73.020s
```

- `pid=739822`'s **first** log entry is `10:18:02` → this is right at process start.
- The JSONL record for that timestamp carries `activity_state: "session_start"` and
  `last_keypress_age_s: 4.706` → confirms it is the startup event, with a keypress
  ~5s in.
- `recovered after 73.020s` → ~1 minute and 13 seconds. Matches "about a minute."

### The captured stack (smoking gun)

From the `2026-06-26 10:18:02` record in `tui_stalls.jsonl`:

```
.../sase/ace/tui/actions/agents/_panel_detail.py", line 50, in action_edit_spec
    self._open_agent_chat()
.../sase/ace/tui/actions/agents/_panel_detail.py", line 77, in _open_agent_chat
    self._open_agent_chat_paths([os.path.expanduser(agent.response_path)])
.../sase/ace/tui/actions/agents/_panel_detail.py", line 123, in _open_agent_chat_paths
    subprocess.run([editor, *chat_paths], check=False)
.../python3.14/subprocess.py", line 1212, in communicate
    self.wait()
.../python3.14/subprocess.py", line 2041, in _try_wait
    (pid, sts) = os.waitpid(self.pid, wait_flags)   ←  blocked here for ~73s
```

Record context fields: `current_tab: agents`, `current_idx: 2`,
`last_action: launch`, `last_action_display_name: bob-cli`.

---

## Root cause

The code path is `e` → `action_edit_spec` → `_open_agent_chat` →
`_open_agent_chat_paths` (`src/sase/ace/tui/actions/agents/_panel_detail.py`):

```python
def _open_agent_chat_paths(self, chat_paths: list[str]) -> None:
    """Open one or more chat paths in a single editor invocation."""
    editor = os.environ.get("EDITOR") or "nvim"
    with self.suspend():               # hands terminal to the editor
        subprocess.run([editor, *chat_paths], check=False)   # blocks the loop
```

- `e` is bound to `edit_spec` (`src/sase/ace/tui/bindings.py:40`,
  `src/sase/default_config.yml:68`). On the **agents** tab it opens the selected
  *completed* agent's chat transcript in `$EDITOR`.
- `with self.suspend():` is correct Textual usage — it publishes an app-suspend
  signal, releases the terminal to its pre-app state, runs the body, then resumes
  and repaints. While suspended, the asyncio event loop is *intentionally* parked on
  `os.waitpid`, so nothing else (input, repaint, refresh) runs until the editor
  exits.
- The stall watchdog has no concept of "suspended," so it sees the loop go quiet for
  ≥5s and records a "stall" that lasts the whole editor session.

**This is not a regression.** `git log` shows `with self.suspend()` has wrapped this
`subprocess.run` since the file's introduction (`48f957ce6`,
`ede7a25f2`). The behavior is long-standing.

### Why it was *perceived* as a startup freeze

`suspend()` works, so the editor genuinely takes over the screen. For the user to
read this as a "frozen TUI" rather than "I'm in nvim," one of the following applies:

1. **Accidental keypress at startup.** `e` is a single, unguarded key. A stray /
   buffered keystroke (or muscle memory) right after launch opens the editor
   unexpectedly. The JSONL confirms a keypress occurred ~5s into the session
   (`last_keypress_age_s: 4.706`).
2. **Slow editor cold-start on a large transcript.** Agent chat transcripts
   (`agent.response_path`) can be multi-megabyte. `nvim` with treesitter / LSP /
   syntax on a large file can take many seconds to become interactive — during which
   the screen looks frozen. The selected agent here (`bob-cli`, idx 2) was a recently
   launched agent whose transcript may be sizable.

Either way, the *mechanism* is unambiguous: an external editor held the suspended
terminal for ~73s.

---

## Secondary finding: the watchdog is polluted with false positives

Categorizing **all 56** records in `tui_stalls.jsonl` by the deepest blocking frame:

| Count | Blocking call | Real freeze? |
|---:|---|---|
| **40** | `subprocess.run([...])` under `self.suspend()` (editor/pager) | ❌ No — intentional suspend |
| 7 | `graphics/_viewer_loop.py:623 _read_single_key → os.read(fd, 1)` | ⚠️ Synchronous blocking key-read loop |
| 6 | `core/agent_scan_facade.py:176 terminalize_stale_active_agent_artifact_index_rows → rust_terminalize(...)` | ✅ Yes — sync Rust call on loop thread |
| 2 | `core/agent_scan_facade.py:142 upsert_agent_artifact_index_row → rust_upsert(...)` | ✅ Yes |
| 1 | `core/agent_scan_facade.py:195 replace_agent_artifact_index_dismissed_agents → rust_replace(...)` | ✅ Yes |

Observations:

- **71% of "stall" records are editor suspends** — pure noise. They make the stall
  telemetry untrustworthy and bury the real problems.
- The **9 Rust-core records** are genuine event-loop stalls: synchronous
  `require_rust_binding(...)` SQLite-index calls
  (`src/sase/core/agent_scan_facade.py`) executed *on the loop thread* rather than via
  `asyncio.to_thread`. Per `memory/rust_core_backend_boundary.md`, the calls
  themselves belong in the Rust core; the fix here is the Python-side scheduling
  (offload to a thread), which is presentation/glue and stays in this repo.
- The **7 viewer-loop records** come from `_read_single_key`, which puts the terminal
  in raw mode and does a blocking `os.read(fd, 1)` to wait for a keypress in the
  image/text viewer — another synchronous loop that parks the asyncio loop.

The watchdog itself is well-built (out-of-thread stack capture is exactly what made
this diagnosable). The startup path (`actions/startup.py::on_mount`) is also already
well-engineered: it `await asyncio.to_thread(...)`s its disk reads and defers heavy
loads via `call_after_refresh`, so initialization is **not** the culprit.

---

## Recommended solution

### 1. (Primary) Make the stall watchdog suspend-aware

Stop classifying intentional `App.suspend()` intervals (editor/pager handoff) as
stalls. Textual publishes signals around suspend that the watchdog can subscribe to:

- `app.app_suspend_signal` — published *before* the terminal is released.
- `app.app_resume_signal` — published *after* the app resumes.

Implementation sketch:

- Add a thread-safe `pause()` / `resume()` (or a `_suspended` flag) to
  `_EventLoopStallWatchdog`. While paused, skip `_record_stall`, and on `resume()`
  reset `_last_progress_mono = time.monotonic()` so the resume tick is not counted as
  a 73s gap.
- In `on_mount` (where the watchdog is already started,
  `actions/startup.py:231`), wire the subscriptions:
  `self.app_suspend_signal.subscribe(self, lambda *_: wd.pause())` and the mirror for
  resume.

Effect: the user's reported event stops being recorded/surfaced as a "freeze," and
the remaining stall records become trustworthy signal.

### 2. (Optional UX) Guard accidental editor-open at startup

If the open was unintentional, reduce the chance of a single stray key dropping the
user into an editor seconds after launch:

- Drop/ignore key input for the first ~250ms after `on_mount` completes (debounce
  buffered keystrokes), **or**
- Run the editor `subprocess.run(...)` with a sane working state and show a brief
  status hint ("opening chat in $EDITOR…") so the handoff is obviously
  user-initiated, not a hang.

This is lower priority and independent of #1.

### 3. (Follow-up bead) Fix the *genuine* stalls

Out of scope for the reported symptom but surfaced by the same data — worth a
separate bead:

- Offload the synchronous `agent_scan_facade` index calls
  (`terminalize_stale_active_agent_artifact_index_rows`,
  `upsert_agent_artifact_index_row`,
  `replace_agent_artifact_index_dismissed_agents`) off the event-loop thread via
  `asyncio.to_thread`, matching how `on_mount` already threads its disk reads.
- Make the image-viewer `_read_single_key` loop non-blocking (e.g., `select`-based or
  run under suspend like the editor path) so it does not park the asyncio loop.

---

## Appendix: evidence & reproduction

**Read the human log:**
```bash
tail -40 ~/.sase/logs/tui.log
```

**Pull the structured record + captured stack for a given stall:**
```bash
python3 - <<'PY'
import json, datetime
with open('/home/bryan/.sase/logs/tui_stalls.jsonl') as f:
    recs=[json.loads(l) for l in f if l.strip()]
for r in recs:
    dt=datetime.datetime.fromtimestamp(r['ts']).strftime('%Y-%m-%d %H:%M:%S')
    if dt=='2026-06-26 10:18:02':
        print('\n'.join(r['main_thread_stack']))
PY
```

**Relevant source:**
- Watchdog: `src/sase/ace/tui/util/stall_watchdog.py`
- JSONL sink: `src/sase/logs/tui_telemetry.py` (`tui_stalls_jsonl_path`, `log_tui_stall`)
- Editor open path: `src/sase/ace/tui/actions/agents/_panel_detail.py`
  (`action_edit_spec` → `_open_agent_chat_paths`)
- Keybinding: `src/sase/ace/tui/bindings.py:40`, `src/sase/default_config.yml:68`
- Startup/mount + watchdog start: `src/sase/ace/tui/actions/startup.py`
- Genuine stalls: `src/sase/core/agent_scan_facade.py`,
  `src/sase/ace/tui/graphics/_viewer_loop.py`

**Watchdog tuning env vars** (from `stall_watchdog.py`): `SASE_TUI_STALL_DISABLE`,
`SASE_TUI_STALL_THRESHOLD_SECONDS`, `SASE_TUI_STALL_POLL_INTERVAL`.
