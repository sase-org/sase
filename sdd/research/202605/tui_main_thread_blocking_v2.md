# TUI Main-Thread Blocking — Fresh Audit (2026-05-15, v2)

## Why this exists

The Textual main thread runs the event loop, dispatches keypresses, drives reactive
watchers, and repaints widgets. Any synchronous work that takes more than a few
milliseconds turns into visible lag: keystrokes pile up, the j/k navigation
stutters, modal opens feel sluggish, the cursor freezes on tab switches.

A prior audit at `sdd/research/202605/tui_blocking_audit.md` enumerated ~11
findings. Many have been addressed since — the agent-load path now runs through
`asyncio.to_thread` (`_load_agents_async` in
`src/sase/ace/tui/actions/agents/_loading_disk.py:210`), the axe collector has an
async variant (`_load_axe_status_async` in
`src/sase/ace/tui/actions/axe_display/_loaders.py:219`), and there is a
process-wide `AgentArtifactCache`
(`src/sase/agent/agent_artifacts_cache.py:88`) that memoizes repeated reads of
artifact files keyed by `(path, mtime_ns, size)`.

This second pass is independent: rather than re-validate the v1 findings, it
re-greps the TUI for blocking patterns from scratch, focusing on what the cache
and async loaders **don't** cover — modal compose paths, callback bodies after
modal dismissal, action handlers triggered by single keypresses, and worker
completion hooks that still run sync collectors. Numbered findings are ranked
roughly by latency × frequency.

---

## Methodology

Patterns searched, in priority order:

1. `subprocess.run` / `subprocess.Popen` / `subprocess.check_output` reachable
   from a Textual action handler, modal compose, or worker `_done` hook.
2. `open(...)`, `json.load`, `json.dump`, `Path.read_text`, `Path.write_text`
   in `compose()` / `__init__` / modal callbacks / action handlers.
3. `os.listdir`, `os.walk`, `os.stat`, `os.path.exists`, `Path.glob`,
   `Path.rglob` on potentially-large directories from the main thread.
4. Sync entry points whose async sibling exists — i.e. someone is still calling
   the cheaper path.
5. `self.suspend()` regions and `subprocess.run` that intentionally freezes the
   UI (called out separately — not always a defect, but worth listing).

Files under `tests/`, `testing/`, `repro/`, and `*_test.py` were excluded.

---

## Findings, by severity

### Tier 1 — likely user-visible lag on common interactions

#### B1. `git pull --rebase` and `git push` run on the main thread

`src/sase/ace/tui/modals/xprompt_browser_actions.py:218-260`

The "offer to commit and push" callback that fires after editing an xprompt
runs `git add`, `git commit`, `git pull --rebase`, `git push`, and optionally
`chezmoi apply` — all via blocking `subprocess.run`. Network round-trips and
rebase resolution can take **seconds** each. Today it freezes the entire TUI
while the network call is in flight.

**Why this matters:** the user usually triggers this from the xprompt browser,
which is a context they expect to return to quickly. A push to a slow remote
or a chezmoi apply over NFS will look like a hang.

**Suggested fix:** wrap the whole `_on_commit_push_answer` body in
`self.run_worker(..., thread=True)` (Textual workers); funnel the result back
via `self.call_from_thread(self.notify, ...)`. The chezmoi apply can chain
after the worker resolves.

---

#### B2. `AgentRunLogModal.__init__` calls `load_all_agents()` synchronously

`src/sase/ace/tui/modals/agent_run_log_modal.py:175-198`

Opening the agent run-log modal (`R` from the changespecs tab) constructs the
modal in the main thread. `__init__` calls `_load_agents_for_cl` (line 190),
which calls `load_all_agents()`
(`src/sase/ace/tui/models/agent_loader.py:362`). That scans every project file,
all RUNNING / DONE markers, dismissed bundles, etc. — the same heavy walk that
the agents tab launches in a thread via `_load_agents_async`.

**Why it matters:** there is already a known-fast async path for this; this
modal is the only caller still using the sync facade. On a workspace with many
artifacts this is the single biggest sub-second freeze in the app.

**Suggested fix:** show the modal with a "Loading…" placeholder, kick off
`asyncio.to_thread(load_all_agents)` from `on_mount`, and call a
`_apply_loaded_log_data` method when the future resolves. Bonus: reuse the
cached `_agents` list from the main app if it is fresh enough (the modal already
has `self._cl_name`, so filtering can happen on whatever the agents tab last
loaded).

---

#### B3. Plan-approval modal reads the plan file in `compose()`

`src/sase/ace/tui/modals/plan_approval_modal.py:192-224`

`_read_plan_file()` does `open(expanded) ... f.read()` inside the modal's
`compose()`. Plan files commonly exceed several KB and the read happens before
the screen paints, so the modal "pop" is delayed by however long the disk read
plus markdown lex (`Syntax(content, "markdown", ...)`) take.

**Why it matters:** every plan approval pays this cost. The `Syntax` highlight
pass is itself non-trivial — for a 100KB plan it can dominate.

**Suggested fix:** in `compose()` yield an empty `Static` with placeholder text,
then in `on_mount` schedule `asyncio.to_thread` to read+highlight, and update
the Static via `self.call_from_thread`. (The modal already overrides
`on_mount`, line 205.)

---

#### B4. Workflow HITL modal reads each `path`-typed output in `compose()`

`src/sase/ace/tui/modals/workflow_hitl_modal.py:111-150`

`_get_path_files()` iterates `output_types`, opens every `path` field, reads
the entire file, and constructs a `Syntax` widget — all inside `compose()`.
Workflow outputs are commonly markdown reports or generated code, easily
hundreds of KB.

**Why it matters:** HITL pops up at the end of a workflow step. The whole
point of HITL is to give the human a fast review; a multi-second open lag
defeats it.

**Suggested fix:** identical to B3 — yield empty `Static`s in `compose()`,
load+highlight on a worker thread on `on_mount`, swap in via
`call_from_thread`.

---

#### B5. Notification-attachment file viewer reads on every j/k

`src/sase/ace/tui/modals/notification_modal_attachments.py:30-86`

`_display_file()` opens the attachment with `open(...) f.read()` synchronously
on the main thread every time the user navigates between attachments
(`action_next_file` line 146, `action_prev_file` line 155, initial
`_display_file` on modal mount line 190).

**Why it matters:** any attachment large enough to be interesting (a long
agent reply, a captured log) makes left/right navigation feel chunky.

**Suggested fix:** memoize via `AgentArtifactCache.read_text` (the cache
already exists and is process-wide — it does not have to be agent-scoped). For
the cold read, kick a worker and show "Loading file…" while it lands.

---

#### B6. Workflow subprocess launch is sync in the keypress handler

`src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py:228-340`

`_launch_workflow_subprocess` runs entirely on the main thread: writes the
`workflow.log` (open+truncate), forks via `subprocess.Popen(...,
start_new_session=True)`, then calls `claim_workspace` (which itself touches
disk). The forked process is detached, so we don't wait on it; but `Popen`
itself runs setup synchronously and `claim_workspace` is the slow part on
networked filesystems.

**Why it matters:** triggered every time the user runs an xprompt with a
changespec context. On Linux fork is cheap; on macOS or under heavy memory
pressure it isn't.

**Suggested fix:** wrap the body in `self.run_worker(thread=True)` and post
the result back. The user-facing notification + agent-list refresh
(`self.call_later(self._schedule_agents_async_refresh)`, currently at
`_launch_body.py:335`) already runs after the call returns, so the contract
survives.

---

#### B7. Axe worker completion calls the sync collector

`src/sase/ace/tui/actions/axe.py:281-293`

`_on_axe_worker_done` runs on the main thread (Textual delivers
`WorkerState` transitions to the UI) and unconditionally calls
`self._load_axe_status()` — the **sync** variant of the loader. The async
variant (`_load_axe_status_async` in
`src/sase/ace/tui/actions/axe_display/_loaders.py:219`) already exists.

**Why it matters:** every time the user starts/stops the axe daemon or a
bgcmd, the moment the worker resolves we re-collect all lumberjacks, all
bgcmd `output.log` tails (up to 500 lines each), and all chop-run snapshots —
synchronously. On a busy axe install this is the largest avoidable hitch.

**Suggested fix:** change line 293 to
`self.call_later(self._load_axe_status_async)` or
`self.run_worker(self._load_axe_status_async, exclusive=True)`. No semantic
change otherwise.

---

### Tier 2 — short blocking reads on user actions

#### B8. Rename callback reads+writes `agent_meta.json` on main thread

`src/sase/ace/tui/actions/rename.py:279-307`

`handle_name_result` is the modal-dismiss callback. It runs on the main
thread, reads `agent_meta.json`, claims the name (which itself touches disk in
`claim_agent_name`), then writes the file. Two opens, one parse, one dump.

**Why it matters:** small JSON, but on a slow disk or when shared, the file
write fsync can stall a frame. More importantly, this is a frequent action.

**Suggested fix:** wrap the post-modal work in `self.run_worker(thread=True)`
with the notify+refresh wired through `call_from_thread`. Keep
`claim_agent_name` inside the worker since it raises on collision and the
notify path is identical.

---

#### B9. Wait action reads+writes JSON on main thread

`src/sase/ace/tui/actions/agents/_wait_resume.py:131-175`

`_apply_wait` opens `waiting.json`, mutates the dict, writes it; or writes
`ready.json` from scratch. Two file ops per keypress; runs in the modal
callback for the `w` action.

**Suggested fix:** same as B8 — worker thread; notify + refresh via
`call_from_thread`.

---

#### B10. Prompt panel reads attempt history files on each agent reselect

`src/sase/ace/tui/widgets/prompt_panel/_agent_display.py:44, 52, 239, 286, 467, 475`
`src/sase/ace/tui/models/agent_attempt.py:29-77`

`AttemptRecord.get_reply_content` and `get_timestamped_reply_chunks` do
`open(...)` synchronously every call. The `_agent_display.py` widget invokes
these from `compose()` / `render()` style hooks whenever the user selects an
agent with prior attempts.

**Note:** unlike `live_reply.md` / `response_path` (covered by
`AgentArtifactCache`), per-attempt files have no cache layer. The cache exists
but `agent_attempt.py` doesn't use it.

**Suggested fix:** route the per-attempt reads through `AgentArtifactCache`
(`read_text`, `read_reply_chunks`). The cache is keyed by `(path, mtime, size)`
so per-attempt files (which are immutable once written) become free on the
second access.

---

#### B11. Snapshot-cache signature scan walks `attempts/` and `bundles/` per refresh

`src/sase/ace/tui/actions/agents/_snapshot_cache.py:63, 120`

`AgentSnapshotCache.attempt_history_for` does `os.listdir(attempts_dir) + os.stat`
per attempt to compute a cache key; `dismissed_bundles()` does `os.walk` over
the bundles directory plus `os.stat` per `.json`. This is called from
`_loading_helpers.py:120` once per agent during every load.

**Status:** **the load is wrapped in `asyncio.to_thread`** via
`_load_agents_async`. So today this is fine. The risk is regressing if some
new caller invokes the sync `_load_agents`. Worth a docstring/assertion guard.

**Suggested action:** add a comment near `attempt_history_for` saying "must
only be called from a worker thread" or assert via Textual's
`is_running_on_loop()` so future regressions fail loudly.

---

### Tier 3 — `self.suspend()` regions (intentional but worth noting)

The codebase uses `self.suspend()` around subprocess calls that take over the
terminal (editor launches, tmux operations). This is the correct Textual
pattern — the screen is genuinely paused, not blocked silently — but the
**main thread is still blocked for the duration of the subprocess**. If the
user fat-fingers `q` while the editor loads, the keypress will still be
queued and replayed after suspend ends. Worth documenting but no fix needed:

- `src/sase/ace/tui/actions/workspace.py:92, 102, 108, 240, 250, 256` — tmux
  list/select/new-window inside `with self.suspend():`.
- `src/sase/ace/tui/modals/xprompt_browser_actions.py:52, 120, 155` — editor
  launches inside suspend.
- `src/sase/ace/tui/modals/task_queue_modal.py:355`,
  `agent_run_log_modal.py:520`, `notification_modal_attachments.py:188`,
  `xprompt_location_modal.py:468` — editor launches.

The one in this list that **isn't** wrapped in `suspend()` is the B1 chezmoi /
git push case — that needs the worker treatment.

---

### Tier 4 — minor / situational

#### B12. `bgcmd.read_slot_output_tail` is sync and re-reads up to 500 lines per call

`src/sase/ace/tui/bgcmd.py:196-217`

Called from `axe_display/_data.py:244` (inside the axe collector, which now
runs in a thread — fine) and from `actions/clipboard/_axe.py:23, 69` for
yank-output (`y`). The clipboard call **is not** in a worker and reads up to
10000 lines. For a long-running bgcmd this is a slow read.

**Suggested fix:** wrap the clipboard read+set in a worker.

---

#### B13. `notification_modal_flow._open_question_modal_from_marker` reads pending_question.json

`src/sase/ace/tui/actions/agents/_notification_modal_flow.py:117-118`

Sync read in modal-open flow. File is small (one question) so impact is
likely sub-millisecond, but the pattern is the same as B5 and a future
"include attached files inline" change would amplify it.

---

## Additional gaps from follow-up pass

These are findings missed by the first v2 pass. They are not numbered by
severity relative to B1-B13, but several belong in Tier 1/Tier 2 if this file
is later re-ranked.

#### B14. ChangeSpec query/history/navigation paths still call the sync disk reload

`src/sase/ace/tui/actions/changespec/_loading.py:124-126`
`src/sase/ace/tui/actions/changespec/_query.py:68, 187, 212`
`src/sase/ace/tui/actions/changespec/_core.py:140-171`
`src/sase/ace/tui/actions/navigation/_tree.py:272-275`
`src/sase/ace/tui/actions/navigation/_advanced.py:584-588`
`src/sase/ace/tui/actions/base.py:465-469`

`_load_changespecs()` still does `_read_changespecs_from_disk()` plus
`_apply_changespecs()` synchronously on the Textual thread. The async
machinery exists (`_reload_and_reposition_async` and
`_schedule_changespecs_async_refresh`), but common keypress flows bypass it:
saved query slots, query-history prev/next, query edit dismissal, ancestry /
child / sibling jumps that change the query, and hide reverted/submitted.

**Why it matters:** this is a full ChangeSpec reload and query-corpus/filter
pass in response to interactive navigation. The code comments already call a
duplicate startup parse "~37ms", which is well above the "few milliseconds"
budget even before accounting for larger `~/.sase/projects` directories or
network filesystems.

**Suggested fix:** split "change query and re-filter the current in-memory
snapshot" from "reload from disk". Query-only actions can apply
`_filter_changespecs(self._all_changespecs)` immediately, then schedule an
async refresh if disk freshness matters. For actions that genuinely require a
fresh disk snapshot, call `_schedule_changespecs_async_refresh()` and keep the
cursor stable via `_snapshot_active_changespec_name()`.

---

#### B15. `ProjectSelectModal.__init__` scans all projects and ChangeSpecs

`src/sase/ace/tui/modals/project_select_modal.py:57-66`
`src/sase/ace/tui/modals/project_select_modal.py:91-103`
`src/sase/ace/tui/modals/project_discovery.py:17-34`
`src/sase/ace/tui/actions/axe_bgcmd.py:114`
`src/sase/ace/tui/actions/agent_workflow/_entry_points.py:385`
`src/sase/ace/tui/actions/agents/_revive.py:174-175`

Constructing the project/CL picker calls `_load_items()` synchronously. That
walks `~/.sase/projects`, validates each launchable project by reading project
files / workspace paths / workflow type, and then calls `find_all_changespecs()`
to add active CL entries.

**Why it matters:** this modal is opened from user actions such as start bgcmd,
start custom agent, and revive dismissed agents. The screen does not paint until
the full project and CL scan completes.

**Suggested fix:** make the modal compose with a "Loading..." option, then run
`list_launchable_projects()` and `find_all_changespecs()` in a thread from
`on_mount`. Replace the option list when ready. If startup already has a fresh
`_all_changespecs`, pass that list into the modal and only discover launchable
projects off-thread.

---

#### B16. `XPromptBrowserModal.__init__` loads every xprompt and project-local config

`src/sase/ace/tui/modals/xprompt_browser_modal.py:79-97`

Opening the xprompt browser constructs the modal and immediately calls
`get_all_prompts()` plus `get_all_project_local_prompts()`. That path reads
config YAML, xprompt directories, plugin/default config resources, and all known
project-local `sase.yml` files before the modal can render.

**Why it matters:** xprompt browsing is an interactive command-palette-like
operation. A large plugin set or many project-local configs can make it feel
like the keypress was ignored.

**Suggested fix:** mirror the modal-loader pattern above: render an empty list
and spinner/placeholder, run `_load_xprompts()` in a thread from `on_mount`, then
rebuild groups/options on the app thread. Keep a process-wide catalog cache with
mtime/size invalidation for config and xprompt directories so repeated browser
opens are cheap.

---

#### B17. Prompt completion performs directory and xprompt-catalog scans on keypress

`src/sase/ace/tui/widgets/file_completion.py:80-143`
`src/sase/ace/tui/widgets/file_completion.py:153-162`
`src/sase/ace/tui/widgets/_file_completion.py:358-360, 419, 464-466, 525`
`src/sase/ace/tui/widgets/xprompt_completion.py:44`
`src/sase/ace/tui/widgets/xprompt_arg_assist.py:94-99`
`src/sase/xprompt/_catalog_sources.py:59-76`

Path completion calls `os.scandir()` and `entry.is_dir()` synchronously. While a
completion panel is active, `_update_file_completion_for_current_cursor()` can
re-run this on each input change. File-history completion also loads the
recency store synchronously. Xprompt and slash-skill completion rebuild
assist entries via `build_structured_xprompts_catalog()`, which gathers
workflows, xprompts, and project-local prompts.

**Why it matters:** completion runs directly in text-input handling. A slow
directory (`~/Downloads`, repo roots with many entries, remote mounts) or
xprompt catalog rebuild will stall typing and tab completion.

**Suggested fix:** introduce a completion service with debounced worker jobs and
stale-result dropping, similar to the static file panel. Cache directory
listings per `(expanded_dir, show_dotfiles, directory mtime/size if available)`
with a short TTL, cap the initial entries scanned before yielding, and reuse the
same xprompt catalog cache proposed in B16.

---

#### B18. Agent file-hint rendering can run live diff synchronously

`src/sase/ace/tui/actions/hints/_files.py:60-68`
`src/sase/ace/tui/widgets/prompt_panel/_agent_display_hints.py:114-118`
`src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py:47-63`
`src/sase/ace/tui/widgets/prompt_panel/_agent_deltas.py:144-150`
`src/sase/ace/tui/widgets/file_panel/_diff.py:95-154`

`action_view_files()` on the Agents tab re-renders the prompt panel with inline
hints. That calls `build_detail_header_summary()`, which calls
`agent_delta_entries()`, which calls `get_agent_diff()`. For agents without a
precomputed `diff_path`, `get_agent_diff()` can run provider live diff with a
10-second timeout. The file panel correctly fetches diffs in a worker, but this
hint-render path bypasses that protection.

**Why it matters:** file hints are normally invoked by a single keypress while
the user is inspecting an agent. On a dirty workspace or slow VCS provider, the
TUI can freeze for the full diff call.

**Suggested fix:** never compute live diffs from hint rendering. Reuse an
already-cached diff from the file panel if present; otherwise render hints for
the prompt/chat/artifact paths first and append DELTAS hints asynchronously when
the worker result arrives. For precomputed `diff_path`, route the read through
`AgentArtifactCache` or the static file worker.

---

#### B19. Re-running a bgcmd starts the subprocess synchronously in the modal callback

`src/sase/ace/tui/actions/axe_bgcmd.py:364-379`
`src/sase/ace/tui/bgcmd.py:323-348`

The initial bgcmd launch path was fixed to submit `_bgcmd_launch_task()` to a
background task. The re-run path for a completed bgcmd still calls
`start_background_command()` directly from the confirmation callback. That
function truncates `output.log`, opens it, calls `subprocess.Popen`, and writes
PID/info files synchronously.

**Why it matters:** this is shorter than the first launch path because there is
no clean/checkout, but it can still stall on filesystem I/O or process spawn,
and it is an avoidable inconsistency beside the already-correct launch path.

**Suggested fix:** route re-run through `_start_bgcmd()` or a small worker that
wraps `start_background_command()` plus the subsequent `_load_bgcmd_state()` /
`_switch_to_axe_view()` UI update.

---

## Cross-cutting recommendations

1. **Lint rule.** Add a custom check (ruff plugin or simple AST grep) that
   flags `open(`, `json.load`, `json.dump`, `subprocess.run`, `subprocess.Popen`
   appearing in any function under `src/sase/ace/tui/` whose name matches
   `compose|__init__|on_|action_|watch_|render|_apply_.*|handle_.*_result`,
   unless the body also contains `run_worker`, `asyncio.to_thread`,
   `call_from_thread`, or `self.suspend(`. This would have caught B1, B3, B4,
   B5, B7, B8, B9 mechanically.

2. **`assert not on_event_loop` guards.** Add a cheap helper that asserts when
   called from the Textual event loop, and sprinkle it inside the heavy
   loaders (`load_all_agents`, `collect_axe_status_data`,
   `AgentSnapshotCache.attempt_history_for`, `enrich_agent_from_meta`'s
   `waiting.json` read). Today the only thing preventing regression is
   reviewer vigilance.

3. **Generalize `AgentArtifactCache` to the attempt/wait files.** The cache
   already keys by `(path, mtime_ns, size)` and is process-global. Routing
   `agent_attempt.py`, `_meta_enrichment.py`'s waiting.json read, and the
   notification-attachment viewer through it would let "re-select the same
   agent" be O(1) instead of O(files).

4. **Audit the worker-`_done` hooks.** B7 demonstrates the failure mode:
   worker completes off-thread, posts a `WorkerState` message that lands on
   the main thread, the handler invokes the sync version of the same job.
   Every `_on_*_worker_done` should be audited for this pattern.

5. **Treat modal constructors as no-I/O zones.** B2, B15, and B16 all share the
   same shape: `push_screen(SomeModal(...))` blocks before the first frame
   because `__init__` does discovery work. Modals that need disk/catalog data
   should accept optional preloaded data, render a placeholder, and load in
   `on_mount`.

6. **Deprecate sync reload facades in TUI code.** `_load_changespecs()` and
   `_load_axe_status()` are too easy to call from key handlers. Prefer names
   that encode thread expectations, e.g. `_load_changespecs_from_disk_sync` and
   `_schedule_changespecs_async_refresh`, and add a main-thread guard to the
   sync helpers.

---

## Out of scope / not findings

- The `parse_thinking_blocks` / `read_codex_thinking` functions in
  `src/sase/ace/tui/thinking/parser.py` look blocking but are dead code —
  nothing imports them outside their own package. Either delete or wire up,
  but they aren't a live blocker today.
- `AgentArtifactCache` reads themselves block on the **first** access; the
  cache mitigates re-selects but not the cold path. A pre-warming pass on
  newly-discovered agents (in the background thread) would close that gap.

---

## File:line index

| Tag | Location |
| --- | --- |
| B1  | `src/sase/ace/tui/modals/xprompt_browser_actions.py:218-260` |
| B2  | `src/sase/ace/tui/modals/agent_run_log_modal.py:175-198` |
| B3  | `src/sase/ace/tui/modals/plan_approval_modal.py:192-224` |
| B4  | `src/sase/ace/tui/modals/workflow_hitl_modal.py:111-150` |
| B5  | `src/sase/ace/tui/modals/notification_modal_attachments.py:30-86` |
| B6  | `src/sase/ace/tui/actions/agent_workflow/_workflow_exec.py:228-340` |
| B7  | `src/sase/ace/tui/actions/axe.py:281-293` |
| B8  | `src/sase/ace/tui/actions/rename.py:279-307` |
| B9  | `src/sase/ace/tui/actions/agents/_wait_resume.py:131-175` |
| B10 | `src/sase/ace/tui/models/agent_attempt.py:29-77` |
| B11 | `src/sase/ace/tui/actions/agents/_snapshot_cache.py:63, 120` |
| B12 | `src/sase/ace/tui/bgcmd.py:196-217`, `actions/clipboard/_axe.py:23, 69` |
| B13 | `src/sase/ace/tui/actions/agents/_notification_modal_flow.py:117-118` |
| B14 | `src/sase/ace/tui/actions/changespec/_loading.py:124-126`, `_query.py:68, 187, 212`, `_core.py:140-171`, `navigation/_tree.py:272-275`, `navigation/_advanced.py:584-588`, `actions/base.py:465-469` |
| B15 | `src/sase/ace/tui/modals/project_select_modal.py:57-66, 91-103`, `modals/project_discovery.py:17-34` |
| B16 | `src/sase/ace/tui/modals/xprompt_browser_modal.py:79-97` |
| B17 | `src/sase/ace/tui/widgets/file_completion.py:80-143, 153-162`, `widgets/_file_completion.py:358-360, 419, 464-466, 525`, `widgets/xprompt_completion.py:44`, `widgets/xprompt_arg_assist.py:94-99` |
| B18 | `src/sase/ace/tui/actions/hints/_files.py:60-68`, `widgets/prompt_panel/_agent_display_hints.py:114-118`, `widgets/prompt_panel/_agent_display_parts.py:47-63`, `widgets/prompt_panel/_agent_deltas.py:144-150`, `widgets/file_panel/_diff.py:95-154` |
| B19 | `src/sase/ace/tui/actions/axe_bgcmd.py:364-379`, `src/sase/ace/tui/bgcmd.py:323-348` |
