# SASE TUI Blocking-Logic Audit

**Date:** 2026-05-14  
**Follow-up audit:** 2026-05-15  
**Scope:** `src/sase/ace/` Textual TUI, adjacent models/providers called from
TUI handlers, and refresh/detail-render hot paths.  
**Goal:** Identify code paths that can run synchronous I/O, subprocesses, or
large CPU work on the Textual event loop, then rank the parts most likely to
produce visible UI freezes.

---

## TL;DR - Worst Offenders

The TUI has a solid async-refresh story: normal auto-refresh and inotify-driven
agent loads route the expensive disk scan through `asyncio.to_thread()` in
`_load_agents_async()` (`src/sase/ace/tui/actions/agents/_loading_disk.py:189-201`),
and detail panels debounce rapid `j`/`k` bursts (`src/sase/ace/tui/util/debounce.py:21-53`).

The remaining blocking risk comes from places that bypass those protections:

1. **Synchronous agent reload entry points** still call `_load_agents()` on the
   UI thread. This is the broadest offender because one call can perform
   dismissed-agent reads, ChangeSpec discovery, agent artifact scanning,
   dismissed-bundle signature walks, filtering, and full list/detail rendering.
2. **Agent-query content search** runs during list finalization on the UI
   thread. When an Agents-tab query is active, it can read up to 512 KiB per
   prompt/reply/attempt file for every candidate agent.
3. **Agent detail footer artifact discovery** synchronously synthesizes artifact
   lists during selected-agent detail updates. Cold cache misses read multiple
   JSON files and may glob/read prompt files.
4. **Workflow prompt/detail rendering** still opens/parses workflow JSON and
   prompt files synchronously during the debounced detail-render phase.
5. **ChangeSpec detail rendering** rereads the selected ProjectSpec file to
   render the RUNNING field.
6. **Agent run-log modal and static/modal file displays** can perform full
   agent scans or size-unbounded reads before modal/detail content paints.
7. **Clipboard/tmux subprocess calls** are mostly user-initiated, but the ones
   not wrapped in `suspend()` still block the event loop briefly.

Correction to the earlier audit: the dismissed-bundles `os.walk` and
dismissed-agents loads are real loader costs, but on the normal async refresh
path they run in a worker thread. They block the TUI primarily through the
remaining synchronous `_load_agents()` call sites.

---

## High Severity

### 1. Synchronous `_load_agents()` call sites

`_load_agents()` is a full disk-backed refresh path:

- merges external dismissals (`_merge_external_dismissals()`)
- calls `find_all_changespecs_cached()`
- calls `load_agents_from_disk_with_state(...)`
- applies/refilters/render-refreshes the agent list

All of that happens inline in `src/sase/ace/tui/actions/agents/_loading_disk.py:124-172`.

Known UI-thread callers:

| File:line | Trigger |
|-----------|---------|
| `src/sase/ace/tui/app.py:349-355` | First switch to Agents tab when no agent cache exists. |
| `src/sase/ace/tui/actions/agents/_filter_actions.py:12-26` | Toggle hidden/non-run agents and edit Agents query. |
| `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_submit.py:94-98` | Plan-feedback submit status update. |
| `src/sase/ace/tui/actions/agents/_notification_modal_flow.py:34-49` | Jumping to plan/question notification while hidden rows are filtered. |
| `src/sase/ace/tui/actions/agents/_notification_status_overrides.py:113-155` | Plan approval marker/response reconciliation. |
| `src/sase/ace/tui/actions/agents/_notification_question_modal.py:139-150` | Question-modal completion reconciliation. |
| `src/sase/ace/tui/actions/agents/_revive.py:393,539` | Revive flows with `full_history=True`. |
| `src/sase/ace/tui/actions/agents/_loading_filter.py:37-40` | Refilter fallback before the first full load. |

**Impact:** This is the top offender because it bypasses the async loader and
pulls every downstream loader cost back onto the Textual event loop. It also
explains why individual costs such as dismissed-agent loading or bundle walking
can still freeze the TUI even though auto-refresh itself is off-thread.

**Fix:** Replace UI-thread callers with `_schedule_agents_async_refresh()` or a
small async wrapper that preserves the caller's needed post-action behavior.
For actions that need immediate in-memory state changes, mutate the local state
first, patch the visible row if possible, then schedule the disk reconcile.

### 2. Agent-query content search reads files during finalization

When `_agent_search_query` is non-empty, `finalize_agent_list()` evaluates the
query on the UI thread (`src/sase/ace/tui/actions/agents/_loading_finalize.py:173-205`).
The evaluator calls `content_cache.get_haystack()` for bare string and `text:`
matches (`src/sase/ace/agent_query/evaluator.py:54-68`). The cache reads:

- `raw_xprompt.md`
- `live_reply.md`
- `agent_meta.json` to resolve `chat_path`
- `response_path`
- every prior attempt `live_reply.md`

The reads are bounded to 512 KiB per file but still synchronous
(`src/sase/ace/tui/models/agent_content_search.py:80-114,116-134`).

**Impact:** The first query after startup, or any query while many agents'
reply files are changing, can block list finalization and paint. It also runs
after async disk load returns, so the code can look "async" while the expensive
filtering is still on the main thread.

**Fix:** Move query evaluation/content reads into the worker-prep phase, or
split query evaluation into metadata-on-main and content-search-off-thread.
Keep the current cache, but make misses happen in a worker.

### 3. Artifact discovery on agent detail refresh

Every debounced selected-agent detail update calls `_apply_agent_detail_update()`.
As part of footer binding state, it calls `_list_selected_agent_artifacts()`
(`src/sase/ace/tui/actions/agents/_display_detail.py:128-147`).

On cache misses, `_list_selected_agent_artifacts()` calls
`read_agent_artifacts_for_tui()` (`src/sase/ace/tui/actions/agents/_panel_artifacts.py:190-235`),
which calls `list_agent_artifacts()` synchronously
(`src/sase/ace/tui/actions/agents/_artifact_provider.py:26-37`).
That path reads `done.json`, `agent_meta.json`, `plan_path.json`, markdown-PDF
index JSON, the explicit artifact index, and for legacy agents can glob and
read prompt files to discover image references
(`src/sase/core/agent_artifact_defaults.py:48-59,197-217,220-260`).

**Impact:** Cold selection of an agent with artifact metadata can stutter the
detail pane even after the j/k debounce. This was missed in the earlier audit
because the artifact list is only used to decide footer state, not to show the
artifact panel.

**Fix:** Compute artifact availability in the agent loader worker or through a
background artifact-provider read. The footer can initially render without the
artifact binding, then patch after the provider result arrives.

### 4. Workflow prompt/detail JSON loads

Top-level workflow rows render through `_update_workflow_display()`
(`src/sase/ace/tui/widgets/prompt_panel/_agent_display.py:99-108`). The workflow
display path still uses synchronous JSON/file reads:

- `workflow_state.json` is opened repeatedly:
  `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py:217-218,242-243,274-275,317-318,357-358`
- prompt files are globbed/read:
  `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py:302-307`
- `prompt_step_*.json` markers and `agent_meta.json` are read:
  `src/sase/ace/tui/widgets/prompt_panel/_workflow_display.py:404-449`
- embedded workflow metadata is read in helpers:
  `src/sase/ace/tui/widgets/prompt_panel/_helpers.py:209-256`

**Impact:** Detail updates are debounced, so this is no longer literally
per-keystroke during a long j/k burst. It still blocks the event loop on every
settled workflow-row selection and on full display refreshes.

**Fix:** Use the existing mtime JSON cache
(`src/sase/ace/tui/models/_loaders/_json_cache.py:31-68`) or the agent artifact
cache for these files, and collapse repeated `workflow_state.json` reads into
one read per render.

### 5. ChangeSpec detail RUNNING field rereads ProjectSpec

`ChangeSpecDetail._build_running_field()` calls `get_claimed_workspaces()` on
each detail render (`src/sase/ace/tui/widgets/changespec_detail.py:363-370`).
That helper opens and reads the whole ProjectSpec file
(`src/sase/running_field/_operations.py:30-46`).

ChangeSpec detail rendering is debounced (`src/sase/ace/tui/actions/changespec/_display.py:90-117`),
but a settled row change still performs this read even though the selected
`ChangeSpec` already came from a parsed ProjectSpec snapshot.

**Impact:** Usually smaller than agent-loader stalls, but it hits the primary
`j`/`k` workflow on the CLs tab and scales with ProjectSpec file size.

**Fix:** Carry RUNNING claims from the cached parse, or cache
`get_claimed_workspaces()` by `(project_file, mtime, size)` and invalidate with
the ChangeSpec snapshot cache.

---

## Medium Severity

### 6. Agent run-log modal full agent scan

Opening the ChangeSpec agent run-log modal constructs its data synchronously in
`__init__`:

- modal construction:
  `src/sase/ace/tui/modals/agent_run_log_modal.py:187-199`
- full source scan and dismissed-agent load:
  `src/sase/ace/tui/modals/agent_run_log_modal.py:34-80`
- manual modal refresh repeats the scan:
  `src/sase/ace/tui/modals/agent_run_log_modal.py:540-552`

This calls `load_all_agents()`, `load_dismissed_agents()`, and dismissed-bundle
summary loading before the modal can render.

**Impact:** User-initiated rather than periodic, but it is effectively another
sync agent-loader surface and can freeze on modal open for large histories.

**Fix:** Mount the modal with a loading row, populate its agent list via
`run_worker(thread=True)` or `asyncio.to_thread()`, and patch the option list
when the result arrives.

### 7. Dismissed-agent store and dismissed-bundle signatures

The dismissed-agent store is still loaded synchronously at startup:

- `src/sase/ace/tui/actions/_state_init.py:335-353`
- implementation: `src/sase/ace/dismissed_agents_state.py:27-28`

The external-dismissal merge also reads the signature and, on change, the full
store (`src/sase/ace/tui/actions/agents/_loading_disk.py:46-76`). On the normal
async refresh path this merge is off-thread
(`src/sase/ace/tui/actions/agents/_loading_disk.py:189-192`), but the sync
`_load_agents()` callers listed above run it on the UI thread.

Dismissed bundles are cached by file signatures, but computing the signature
walks the bundles tree every time the loader consults it
(`src/sase/ace/tui/actions/agents/_snapshot_cache.py:108-143`). Attempt-history
signatures similarly list/stat `attempts/` entries
(`src/sase/ace/tui/actions/agents/_snapshot_cache.py:53-84`).

**Impact:** These are not standalone "every refresh blocks the TUI" bugs on the
normal path anymore. They are still expensive under sync `_load_agents()`, and
they increase the runtime of the background refresh worker.

**Fix:** Remove sync loader callers first. Then move bundle/attempt signatures
to watcher-maintained dirty sets or cache directory signatures with a bounded
rescan cadence.

### 8. Static file/diff and precomputed diff reads

Static display paths read entire files synchronously:

- `display_static_diff()`:
  `src/sase/ace/tui/widgets/file_panel/_display.py:124-196`
- `display_static_file()`:
  `src/sase/ace/tui/widgets/file_panel/_display.py:198-260`
- precomputed `agent.diff_path` in `get_agent_diff()`:
  `src/sase/ace/tui/widgets/file_panel/_diff.py:111-116`

The active-agent live diff path is correctly off-thread via `run_worker()`
(`src/sase/ace/tui/widgets/file_panel/__init__.py:380-406`), but completed
agents with saved files/diffs can still block while the panel reads and builds
the renderable.

**Fix:** Read static files in the same background worker path used for live
diffs. Add a size cap or tail/preview mode before syntax rendering.

### 9. Attempt history reply rendering

Attempt metadata loading is cached/off-thread during agent loading, but
rendering merged/pinned attempts reads the captured reply/timestamp files
synchronously:

- `src/sase/ace/tui/models/agent_attempt.py:29-77`
- called from `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py:29-55`

**Impact:** Mostly affects failed agents with multiple large attempts and users
who enable merged attempt history or pin an attempt. It is debounced, but still
main-thread work.

**Fix:** Reuse `AgentArtifactCache.read_reply_chunks()` / `read_text()` for
attempt records, or preload attempt reply summaries in the loader worker.

### 10. Plan/modals and attachment reads

Several modal compose/action paths read full files synchronously:

- plan approval modal reads the whole plan file during compose:
  `src/sase/ace/tui/modals/plan_approval_modal.py:217-224`
- notification attachments:
  `src/sase/ace/tui/modals/notification_modal_attachments.py:60-61`
- workflow HITL modal:
  `src/sase/ace/tui/modals/workflow_hitl_modal.py:143-144`
- xprompt config/location modals:
  `src/sase/ace/tui/modals/xprompt_config_yaml.py:64`,
  `src/sase/ace/tui/modals/xprompt_location_modal.py:552`

**Impact:** User-initiated and modal-scoped, but large plans/attachments can
freeze the UI before the modal paints.

**Fix:** Mount with a loading state and populate content via `run_worker()` or
`asyncio.to_thread()`. Add maximum inline display size with an editor fallback.

### 11. Startup and watcher setup

Cold startup still performs several small config/state reads in `__init__`:

- grouping modes:
  `src/sase/ace/tui/actions/_state_init.py:264-293`
- query history/selections/saved queries:
  `src/sase/ace/tui/actions/_state_init.py:450-466`
- merged config and keymap registry:
  `src/sase/ace/tui/actions/_state_init.py:473-507`
- keymap defaults read bundled YAML:
  `src/sase/ace/tui/keymaps/loader.py:41-59`

Post-mount watcher startup also lists project/artifact roots on the UI thread
before starting the watcher thread:

- project/artifact root collection:
  `src/sase/ace/tui/actions/startup.py:270-307`
- shallow artifact-directory watch install:
  `src/sase/ace/tui/util/fs_watcher.py:120-155,222-242`

Recursive watch installation for newly-created trees happens later in the
watcher path (`src/sase/ace/tui/util/fs_watcher.py:244-288`), so that part is
not a startup full-tree walk.

**Impact:** Usually acceptable, but large config overlays or many projects can
stutter first paint/post-first-paint setup.

**Fix:** Defer nonessential config history reads to `on_mount()` workers, and
move watcher `start()` itself behind `run_worker()` while dispatching only the
ready state to the UI.

---

## Low Severity / Mostly Correct

### Suspended editors and pagers

Most long-lived editor/pager subprocesses are correctly wrapped in `suspend()`,
which intentionally gives the terminal to the external program rather than
presenting as a TUI freeze. Examples:

- base handlers:
  `src/sase/ace/tui/actions/base.py:106,132,169,338`
- task queue editor:
  `src/sase/ace/tui/modals/task_queue_modal.py:351-356`
- agent run-log editor:
  `src/sase/ace/tui/modals/agent_run_log_modal.py:516-520`
- xprompt/location editors:
  `src/sase/ace/tui/modals/xprompt_browser_actions.py:51-155`,
  `src/sase/ace/tui/modals/xprompt_location_modal.py:467-468`
- notification error/tmux actions:
  `src/sase/ace/tui/actions/agents/_notification_handlers.py:80-85,187-190`

These should not be ranked as blockers unless a specific call site lacks
`suspend()` or is meant to be fire-and-forget.

### Clipboard and short tmux subprocesses

Clipboard helpers call `subprocess.run()` synchronously:

- core clipboard:
  `src/sase/core/clipboard.py:22-29`
- copy-mode tmux pane capture:
  `src/sase/ace/tui/actions/clipboard/_helpers.py:19-34`
- file-hint clipboard:
  `src/sase/ace/tui/actions/hints/_files.py:118-149`
- tmux notification bell:
  `src/sase/ace/tui/actions/agents/_notification_polling.py:162-180`

These are user-initiated or notification-arrival paths, so they are lower
severity than refresh/detail blockers. They can still hang if a clipboard tool
blocks on Wayland/X11 availability.

**Fix:** Put clipboard writes and tmux bell calls behind `asyncio.to_thread()`
or a tiny fire-and-forget worker.

### Artifact viewer tmux state checks

When an artifact viewer pane is tracked, normal agent display/navigation checks
whether that tmux pane still exists:

- TUI calls:
  `src/sase/ace/tui/actions/agents/_panel_artifacts.py:144-167`
- tmux subprocess:
  `src/sase/ace/tui/graphics/_viewer_launch.py:519-530`

This only matters while the artifact viewer split is live. It is worth caching
or event-notifying, but it is not a broad idle-refresh offender.

---

## Revised Ranking

Ranked by `event-loop impact x frequency x amount of work`:

1. **Synchronous `_load_agents()` entry points** - broadest blocker; pulls the
   entire loader and render pipeline onto the UI thread.
2. **Agent-query content search in finalization** - file reads for every agent
   while a query is active, after async disk load returns.
3. **Agent artifact discovery in detail/footer update** - cold selected-agent
   details can synchronously read/glob several artifact files just to decide
   footer state.
4. **Workflow prompt/detail JSON reads** - repeated sync JSON/file reads on
   workflow-row detail paint.
5. **ChangeSpec RUNNING field rereads** - primary CL navigation path still
   opens the ProjectSpec on settled detail refresh.
6. **Agent run-log modal full scans** - modal-scoped but as expensive as a
   loader pass.
7. **Static file/diff reads** - size-unbounded but narrower, tied to file panel
   displays.
8. **Modal full-file reads** - user-initiated, but can freeze before modal
   content appears.
9. **Clipboard/tmux subprocesses** - short and user-initiated, but should move
   off-thread for consistency.

---

## Suggested Order of Operations

1. **Eliminate UI-thread `_load_agents()` calls.** Convert the filter,
   notification, revive, first-agent-tab, and plan-feedback paths to schedule
   async refreshes. This reduces the blast radius of every loader-side cost.
2. **Move agent-query content filtering off-thread.** The existing cache and
   512 KiB cap are good; the cache misses just need to stop happening during
   main-thread finalization.
3. **Decouple artifact availability from detail rendering.** Footer state can
   patch after a provider result rather than forcing cold artifact discovery
   during selection.
4. **Cache workflow JSON and consolidate reads.** Replace repeated
   `workflow_state.json` opens with one cached read per render.
5. **Cache ChangeSpec RUNNING claims.** Use ProjectSpec `(mtime, size)` or
   fold it into the ChangeSpec snapshot cache.
6. **Move run-log modal loading and static/modal reads off-thread.** These are
   straightforward, localized cleanups after the main hot-path fixes.
7. **Move clipboard writes off-thread.** Clipboard failures should not stall the
   event loop while probing multiple platform tools.

---

## Method Notes

- Re-read the existing audit and `sdd/research/README.md`; kept the same file
  path under `sdd/research/202605/`.
- Grepped `src/sase/ace`, `src/sase/ace/tui`, `src/sase/core`, and
  `src/sase/agents` for synchronous I/O, subprocess, sleeps, glob/walk/listdir,
  and async offload patterns.
- Traced normal refresh flow from `on_mount()` and `_on_auto_refresh()` through
  `_load_agents_async()` and confirmed its disk phase is off-thread.
- Traced `j`/`k` paths for Agents and ChangeSpecs and confirmed both use a
  150 ms detail-panel debounce, so many earlier "per keystroke" findings are
  better described as "per settled selection/detail paint."
- Cross-checked editor/pager subprocesses for `suspend()` wrappers and
  downgraded the wrapped ones to informational.
