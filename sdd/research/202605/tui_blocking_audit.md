# SASE TUI Blocking-Logic Audit

**Date:** 2026-05-14
**Scope:** `src/sase/ace/` (Textual TUI) and adjacent modules invoked from event handlers.
**Goal:** Identify code paths that run synchronous I/O, subprocess, or CPU-heavy
work on the Textual event loop, ranked by likelihood of producing visible UI
freezes.

---

## TL;DR — Worst Offenders

The codebase is generally good about offloading: ~60 sites use
`asyncio.to_thread` / `run_worker` / `run_in_executor` (Grep across
`src/sase/ace`). The remaining hot spots are concentrated in **three
systemic patterns** plus a small set of one-off subprocess calls:

1. **The dismissed-agents store is loaded synchronously on at least four
   paths** — startup, every agent refresh's merge path, the run-log modal, and
   indirectly from the 1 s countdown tick. With a large
   `~/.sase/dismissed_agents.json` (>1 MB), startup and every
   ~10 s refresh pay the cost on the main thread.
2. **The dismissed-bundles cache walks the entire bundles directory tree
   synchronously on every agents refresh** to compute its signature
   (`os.walk` + per-file stats in `_snapshot_cache.py`).
3. **The prompt/detail panels parse JSON synchronously while composing**
   — workflow state, embedded workflows, mentor outputs, read-state and
   acceptance-state files all hit disk on the render path triggered by `j`/`k`
   navigation.

Below: the ranked findings and the suggested fixes.

---

## HIGH severity — blocks on every refresh or fires per-keystroke

### 1. Dismissed-agents store loaded sync on hot paths

| File:line | What blocks |
|-----------|-------------|
| `src/sase/ace/tui/actions/_state_init.py:350-351` | `load_dismissed_agents()` + `dismissed_agents_file_signature()` called from `__init__`, blocking app startup. |
| `src/sase/ace/tui/actions/agents/_loading_disk.py:58,63` | Same two calls inside `_compute_external_dismissal_merge()`. Already offloaded in `_load_agents_async`, but the **synchronous `_load_agents` fallback** still pays the cost on main. |
| `src/sase/ace/tui/modals/agent_run_log_modal.py:67` | `load_dismissed_agents()` in modal mount — modal opens with a frame stutter. |

**Impact:** ~10 s auto-refresh interval and every modal open hit the disk
synchronously. Scales linearly with file size.

**Fix:** Always go through the async load path; for the modal, mount empty and
populate via `asyncio.to_thread` in `on_mount`.

### 2. Dismissed-bundles signature walk on every refresh

- `src/sase/ace/tui/actions/agents/_snapshot_cache.py:120`
  — `for root, _, files in os.walk(bundles_dir): ...` enumerates all `.json`
  files under the bundles tree to compute a cache-invalidation signature.
- `src/sase/ace/tui/actions/agents/_snapshot_cache.py:62-74`
  — companion loop: `os.listdir(attempts_dir)` plus a `stat` per entry to
  build the attempts signature.

Both run synchronously every time `dismissed_bundles()` is consulted, which
is on every agents-tab refresh. With a long-lived install, the bundles
directory grows monotonically; walks become multi-second.

**Fix:** Cap the walk's per-tick cost, or move signature computation into the
fs_watcher worker thread and let the cache consume signatures it produced
asynchronously.

### 3. Prompt-panel JSON parses during render

- `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py:217, 242, 274, 306, 317, 357, 406, 448`
  — eight `json.load()` sites in `_update_workflow_display()`, opening
  `workflow_state.json` and embedded workflow descriptors. Called whenever a
  workflow-style agent is selected; fires on each `j`/`k` keystroke.
- `src/sase/ace/tui/widgets/prompt_panel/_helpers.py:233-234, 248-249`
  — `load_embedded_workflows()` + sibling helpers, also called from
  compose/render.

**Fix:** Treat workflow JSON like attempt history — mtime-keyed cache (see
`_loaders/_json_cache.py`), and/or only parse the structural top of the file
synchronously, deferring heavier nested loads to a worker.

### 4. Mentor / read-state / acceptance-state reads during detail refresh

- `src/sase/ace/mentor_output.py:175, 316, 349`
  — `path.read_text()` + `json.loads()` on every detail-panel refresh. Triggered
  during `j`/`k` navigation.

**Fix:** Cache by `(path, mtime, size)` like the snapshot cache.

---

## MEDIUM severity — blocks on rare interactions but still freezes

### 5. Synchronous file reads in the file panel

- `src/sase/ace/tui/widgets/file_panel/_display.py:133, 213`
  — `open(expanded_path, encoding="utf-8").read()` in
  `display_static_diff` / `display_static_file`. Size-unbounded; a large diff
  hangs the UI for the duration of the read.

**Fix:** Stream the file via `asyncio.to_thread` and yield to the loop between
chunks.

### 6. fs_watcher tree install walk

- `src/sase/ace/tui/util/fs_watcher.py:256`
  — `for child in path.rglob("*")` recursively walks newly-created agent
  artifact trees to install inotify watches. Runs in response to inotify
  IN_MOVED_TO events.

**Note:** The fs_watcher itself runs in a worker thread, so this is mostly
worker-bound rather than main-thread, but deep trees still serialize event
delivery and delay UI updates.

### 7. AttemptRecord lazy file loads

- `src/sase/ace/tui/models/agent_attempt.py:32, 45, 111`
  — `open(self.live_reply_path).read()`, `open(self.timestamps_path).read()` on
  property access. Called from the detail view when inspecting prior attempts.

**Fix:** Property → coroutine, or pre-load through `_json_cache`.

### 8. Modal subprocess calls

- `src/sase/ace/tui/modals/task_queue_modal.py:355`
- `src/sase/ace/tui/modals/plan_approval_modal.py:221`
- `src/sase/ace/tui/modals/agent_run_log_modal.py:520`

Each uses synchronous `subprocess.run(...)` for editor spawn or clipboard. The
UI is frozen until the external command returns. Some are wrapped in
`with self.suspend():` (intentional, releases the terminal), but those that
aren't will freeze the app.

**Fix:** Editor-spawning calls should always use `app.suspend()`. Clipboard
calls should `asyncio.to_thread` them.

### 9. Bulk launch `time.sleep`

- `src/sase/ace/tui/actions/agent_workflow/_launch_bulk.py:77`
  — `time.sleep(1)` between fanout launches. Already inside
  `asyncio.to_thread`, so it blocks only the worker, but it serializes bulk
  launches.

### 10. Per-tick disk writes in countdown

- `src/sase/ace/tui/actions/_event_activity.py:24,38,40`
  — `write_last_keypress()`, `write_activity_timestamp()`, `write_tui_pid()`
  fire from `_on_countdown_tick` (1 s). Coalesced to a 10 s effective cadence
  by an internal guard, but every 10 s the main thread does three small disk
  writes.

**Fix:** Move the flush behind `asyncio.to_thread` — they're truly fire-and-forget.

---

## LOW severity / good design (informational)

- **`find_all_changespecs_cached`** at `src/sase/ace/changespec/__init__.py:194`
  is wrapped via `asyncio.to_thread()` from the mount path
  (`tui/actions/agents/_loading_disk.py:194`). The bare
  `find_all_changespecs()` still exists for CLI use but isn't on the TUI hot
  path.
- **`@work`-equivalent coverage**: 60 offload sites across 25 files. The TUI's
  primary load and refresh path is async-first; the leakage is in fallback /
  legacy synchronous paths, not in the design.
- **Editor and pager handlers** at `src/sase/ace/handlers/show_diff.py:75` and
  `reword.py:162` use `subprocess.run` — but they're invoked through
  `with self.suspend(): ...` in `src/sase/ace/tui/actions/base.py:132,169`,
  which is the correct pattern. Not a freeze.
- **`agent_content_search.py:108, 126-127`** — synchronous JSON parse on user
  search action. User-initiated, infrequent.

---

## Worst Offenders — Summary Ranking

Ranked by `severity × frequency × magnitude`:

1. **Dismissed-agents store sync loads** (4 sites) — Every refresh + startup +
   every modal open. Hits a file that grows unboundedly with use. _Highest
   blast radius._
2. **Dismissed-bundles `os.walk` signature** — Per refresh, scales with bundle
   directory size, no caching of the walk itself.
3. **Prompt-panel workflow-JSON parses** (8 sites in one function) — Per
   `j`/`k` keystroke on workflow agents; degrades the most visible interaction.
4. **Mentor/read-state JSON parses on detail refresh** — Same per-keystroke
   pattern, different file group.
5. **File panel static display reads** — Size-unbounded, no streaming.

Everything else is bounded, rare, or already offloaded.

---

## Suggested Order of Operations

Quick wins, in priority order:

1. Always route `_compute_external_dismissal_merge` through the async path;
   remove the sync `_load_agents` fallback or make it also offload.
2. mtime-cache the workflow-state and embedded-workflow JSON loads in
   `_workflow_display.py` and `_helpers.py`. The `_loaders/_json_cache.py`
   harness already exists — extend it to cover these files.
3. Move dismissed-bundles signature computation into the fs_watcher worker so
   the main thread only consumes precomputed signatures.
4. Move `mentor_output.py` reads through the same cache.
5. Stream large file-panel reads off-thread; tail-only display for files over
   ~1 MB.

---

## Method Notes

- Three Explore agents ran in parallel against
  `src/sase/ace/`, `src/sase/ace/handlers/`, `src/sase/bead/`, `src/sase/chats/`,
  `src/sase/agents/`, `src/sase/agent/`, and `src/sase/vcs_provider/`.
- Worker-coverage cross-check: `Grep` for `@work|run_in_executor|asyncio\.to_thread|run_worker` in `src/sase/ace`
  returned 60 hits across 25 files.
- Verified that `handle_show_diff` / `handle_reword_prepare` are invoked
  inside `self.suspend()` (see `src/sase/ace/tui/actions/base.py:132,169`),
  so they were downgraded from initial HIGH-severity flags to non-issues.
