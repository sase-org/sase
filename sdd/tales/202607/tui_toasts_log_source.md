---
create_time: 2026-07-07 13:46:49
status: done
prompt: sdd/prompts/202607/tui_toasts_log_source.md
---
# Plan: "TUI Toasts" Log Source in the SASE Admin Center Logs Tab

## Goal

Add a new source to the SASE Admin Center's **Logs** tab named **TUI Toasts** that shows the last **100** toast
notifications displayed to the user in the `sase ace` TUI — from the _current_ session **and** previous sessions — with
an unmistakable visual indication of which session each toast was shown in.

## Product Design

### Why this shape

Toasts are ephemeral by design: they appear for a few seconds and vanish, which makes them easy to miss ("what did that
error toast just say?"). This feature turns them into a browsable notification history, exactly like a phone/desktop
notification center. That analogy drives three design calls:

1. **Newest-first ordering.** Unlike the other log sources (which are chronological log files read with `G`-to-bottom),
   a notification history reads top-down from most recent. The Logs detail pane resets scroll to the top on selection,
   so the toast you just missed is the first thing you see. Sessions are ordered newest → oldest, and toasts within a
   session are also newest → oldest (one consistent "most recent first" rule; the timestamp column makes the direction
   obvious).
2. **Session grouping with a highlighted "this session" group.** Each session gets a full-width header rule; the current
   TUI process's session is visually distinct (bold gold, labeled `This session`) from earlier sessions (dim). This
   satisfies the "make it clear which session each toast was displayed in" requirement at a glance, without per-row
   session noise.
3. **N = 100.** 100 toasts comfortably covers several days of typical TUI use while keeping the backing file tiny (~25
   KB) and the render instant. The display limit and the on-disk retention are the same number, so "the panel shows the
   last 100 toasts" is literally true — no confusing "file has more than the panel shows" split.

### What the user sees

Selecting **TUI Toasts** in the Sources list (positioned right after "TUI Diagnostics") renders:

```
TUI Toasts
Toast notifications shown in this and previous TUI sessions
~/.sase/logs/tui_toasts.jsonl  ·  2026-07-07 09:14 UTC  ·  47 toasts
────────────────────────────────────────────────

━━ This session · started 2026-07-07 09:12 UTC · pid 1234 ━━━━━━━━━
 09:14:03  ✖  Workflow error: boom
 09:13:47  ⚠  PR is not set
 09:12:41  ·  Refreshed  ×3
 09:12:10  ·  Mailing my-change...

━━ Session · started 2026-07-06 22:01 UTC · pid 98111 ━━━━━━━━━━━━
 22:15:33  ·  Saved query to slot 2
 22:03:12  ⚠  ChangeSpec must be Ready to mail
```

Styling (reusing the pane's existing `_CYAN` / `_GOLD` palette so the tab stays coherent):

- **Session headers**: current session in `bold` gold with a `This session` label; earlier sessions dim. Headers show
  session start time (UTC, matching every other timestamp in the pane) and pid (disambiguates two sessions started the
  same minute, e.g. two terminals).
- **Severity glyph + color per row**: `·` (dim) for information, `⚠` (gold) for warning, `✖` (red) for error — message
  text inherits the severity color for warning/error, default for info. This mirrors the severity color language already
  used by the other log sources.
- **Timestamps** in cyan, `HH:MM:SS` UTC; if a toast's date differs from its session-start date (session spanned
  midnight), the row shows `MM-DD HH:MM:SS` instead.
- **Toast titles** (the optional Textual `title=` argument) render bold before the message, separated by `·`.
- **Consecutive duplicates collapse** (render-time only): identical consecutive (severity, title, message) rows within a
  session render once with a dim ` ×N` suffix and the most recent timestamp — so "Refreshed" spam doesn't drown real
  signal. The raw history file keeps every record.
- **Multi-line messages** wrap with continuation lines indented under the message column.
- **Empty state**: "No toasts yet — notifications shown in the TUI will appear here."

Everything else about the Logs tab (j/k source navigation, `ctrl+d/u` scrolling, `g/G`, `r` refresh, copy mode, footer
hints) applies unchanged — no new keymaps, so no `default_config.yml`, footer, or help-modal updates are needed.

## Technical Design

### Architecture placement (Rust core boundary)

Toast history is **TUI presentation telemetry**: the toast concept exists only in the Textual frontend, exactly like the
existing stall/git-op/launch-timing logs in `src/sase/logs/tui_telemetry.py` and the persisted Admin Center tab in
`src/sase/ace/admin_center_tab.py` (whose docstring documents this precedent). No other frontend would need matching
behavior, so this stays in the Python ACE layer — no `sase-core` changes.

### 1. New module: `src/sase/logs/toast_log.py` (persistence)

A sibling of `tui_telemetry.py`, following its conventions (module-level path override for tests, env-var override,
writers that never raise back into the TUI):

- **Path**: `tui_toasts_jsonl_path()` → `~/.sase/logs/tui_toasts.jsonl`, with `TUI_TOASTS_JSONL` module override and
  `SASE_TUI_TOASTS_PATH` env override. Exported from `sase.logs` like the other path helpers.
- **Record schema** (one JSON object per line): `timestamp` (UTC ISO-8601), `session_id` (opaque, e.g.
  `"20260707T091233Z-1234"`), `session_started_at` (UTC ISO of app start), `pid` (int), `severity` (Textual severity
  string), `title` (str, may be empty), `message` (str, may be multi-line).
- **Session identity**: `current_toast_session()` — a process-wide memoized value generated on first use (start time +
  pid). Both the writer (notify hook) and the reader/renderer (Logs pane, same process) use it, which is what makes the
  "This session" marker trivially correct even with multiple concurrent `sase ace` processes appending to the same file.
  Includes a test reset hook.
- **Writer**: `record_toast(message, title, severity)` builds the record and enqueues it on a tiny module-level
  `queue.Queue` drained by a lazily-started daemon writer thread. This is required by the TUI perf rules
  (`memory/tui_perf.md` rule 1: no synchronous disk I/O on the Textual event loop — `App.notify` runs on the loop). The
  thread appends under `fcntl.flock` (safe across concurrent TUI sessions, same as `_append_jsonl`) and swallows all
  errors with a debug log. A `flush_toasts(timeout)` helper (queue join) is used by tests and called best-effort on app
  shutdown so at most the final toast of a session can be lost.
- **Retention (exactly "last 100")**: `TOAST_HISTORY_LIMIT = 100`. After each append, if the file exceeds
  `TOAST_HISTORY_LIMIT + 50` lines, compact **in place** (truncate + rewrite last 100 lines) under the same exclusive
  flock — in-place rather than replace-file so the lock inode stays valid for concurrent writers. Compaction is
  amortized (every ~50 toasts, rewriting ≤ ~40 KB).
- **Reader**: `read_recent_toasts(limit=100)` → `list[ToastRecord]` (frozen dataclass), tailing via the existing
  `read_tail_seek` and skipping malformed lines tolerantly (mirrors `_render_jsonl_tail`).

### 2. Capture hook: `AceApp.notify` override in `src/sase/ace/tui/app.py`

`Widget.notify` delegates to `App.notify` in Textual 8.2.7, so a single override on `AceApp` captures **every** toast in
the app — action mixins, modals, widgets, and Textual internals alike (and stays uniform across all agent runtimes,
since capture is at the display layer, not at call sites):

```python
def notify(self, message, *, title="", severity="information", timeout=None, markup=True) -> None:
    super().notify(message, title=title, severity=severity, timeout=timeout, markup=markup)
    record_toast(message=message, title=title, severity=severity)  # enqueue; never raises
```

Signature mirrors Textual's exactly. `record_toast` is fire-and-forget and cheap (dict build + queue put), so the event
loop is untouched. App shutdown (the existing lifecycle teardown path) calls `flush_toasts(timeout=1.0)` best-effort.

### 3. Registry: `src/sase/ace/tui/logs/sources.py`

- Extend `RenderMode` to `Literal["text", "jsonl", "toasts"]`.
- Register the source in `log_sources()` right after the `tui` entry:
  `LogSource(id="tui_toasts", title="TUI Toasts", description="Toast notifications shown in this and previous TUI sessions", path=tui_toasts_jsonl_path(), render="toasts")`.
- `read_rendered_tail` treats `"toasts"` like `"jsonl"` as its plain-text fallback (keeps the `LogSource` contract
  total); the rich session-grouped rendering lives pane-side (below).

### 4. Rendering: new `src/sase/ace/tui/modals/logs_pane_toasts.py` + `logs_pane.py` branch

- New helper module (following the `*_rendering.py` companion-module convention) exposing
  `render_toast_detail_body(records, current_session_id) -> Text`: groups records by `session_id`, orders sessions and
  rows newest-first, collapses consecutive duplicates, and applies the styling described above using the pane's
  `_CYAN`/`_GOLD` palette.
- `logs_pane.py::_render_log_detail` branches on `source.render == "toasts"`: reads via
  `read_recent_toasts(TOAST_HISTORY_LIMIT)` and delegates the body to the toast renderer; the uniform header (title /
  description / path / mtime) stays, with the line-count metadata reading `N toasts` instead of `N lines`.
  `_empty_message` gains the toast-specific empty-state copy.
- All rendering still happens inside the pane's existing threaded load worker, so the panel stays responsive (no new I/O
  on the UI thread).

### 5. Tests

- **`tests/logs/test_toast_log.py`** (new): path + env overrides; record schema; session-id memoization + reset;
  enqueue/flush writer round-trip; compaction keeps exactly the last 100 and triggers only past the slack threshold;
  malformed lines skipped on read; writer never raises on unwritable paths; two interleaved writers (simulated
  concurrent sessions) don't corrupt the file.
- **`tests/ace/tui/logs/test_sources.py`**: update the registry-shape expectations (new id/order: `tui_toasts` after
  `tui`), render mode, and path-override tracking.
- **`tests/ace/tui/test_logs_pane.py`**: seed a toast file containing the current session plus two earlier sessions;
  assert session headers with "This session" marker first, newest-first ordering, severity glyph/color styling, `×N`
  duplicate collapse, midnight-crossing date display, and the empty-state copy.
- **Capture test** (AcePage-based, alongside the existing TUI app tests): call `app.notify(...)` with each severity,
  `flush_toasts()`, and assert the JSONL records carry the current session id and correct fields.
- **PNG visual snapshots** (`tests/ace/tui/visual/`): extend `_seed_logs_tab_files` to seed a deterministic
  `tui_toasts.jsonl` (two sessions, all three severities, a ×N duplicate, a multi-line message; session id pinned via
  the test reset hook so "This session" renders deterministically), add
  `test_config_center_logs_tab_toasts_png_snapshot` that navigates the source list to TUI Toasts and snapshots
  `config_center_logs_tab_toasts_120x40`. **Note:** the existing `config_center_logs_tab_120x40` golden must be
  regenerated with `--sase-update-visual-snapshots` — the new source row changes the Sources list and the
  `Logs [9 sources · …]` title on that snapshot.

### 6. Verification

- `just check` (per repo policy; `just install` first in a fresh workspace).
- `just test-visual` for the PNG suite, accepting the two intentional golden changes.
- Manual smoke: run `sase ace`, trigger a few toasts (e.g. `r` refresh → "Refreshed"), open the Admin Center → Logs →
  TUI Toasts, confirm the current-session group renders with the newest toast on top; relaunch the TUI and confirm the
  prior session appears as an earlier-session group.

## Explicitly Out of Scope

- No Rust core (`sase-core`) changes — TUI presentation telemetry (see Architecture placement).
- No new keybindings, footer entries, or help-modal content (no options changed; no docs enumerate log sources).
- No capture of toasts from other frontends/processes (only the ace TUI displays toasts).
- No user-facing configuration of N (a module constant keeps the story simple; trivially configurable later if wanted).
