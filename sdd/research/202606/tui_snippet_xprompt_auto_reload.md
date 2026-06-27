---
create_time: 2026-06-27
updated_time: 2026-06-27
status: research
---

# ACE TUI Snippet and XPrompt Auto-Reload Research

## Question

When a user adds a new SASE snippet in config, or a new xprompt in config or a
markdown/YAML xprompt file, how should the ACE TUI make it available without a
restart and without hurting TUI performance?

## Short Answer

Implement one app-owned prompt catalog service for the ACE TUI.

The service should:

- keep immutable in-memory snapshots of snippets, xprompts, workflows, and TUI
  completion metadata;
- watch only editable source locations with a coalesced background watcher;
- rebuild snapshots only in a Textual worker with `thread=True` or
  `asyncio.to_thread`;
- swap the completed snapshot onto the UI thread with a generation check;
- expose fast snapshot reads to prompt completion, snippet expansion,
  `#@`/xprompt selection, and the Config Center xprompt browser.

Do not reload snippets or xprompts directly from key handlers, modal
constructors, watcher callbacks, or prompt-completion code. Those paths should
read memory only.

## Verified Current Shape

### Snippets

`src/sase/ace/tui/actions/_state_init.py` reads `ace.snippets` once from the
merged config during app state initialization. It stores that map in
`self._user_snippets` and leaves `self._snippets_cache` empty so cold startup
does not scan xprompt files.

`src/sase/ace/tui/actions/startup.py:get_snippets()` lazily builds the runtime
snippet registry:

- `get_xprompt_snippets()` scans xprompt definitions and converts xprompts with
  `snippet` frontmatter into snippet templates.
- user `ace.snippets` override those xprompt-derived snippets.
- `resolve_snippet_references()` resolves `#[snippet]` references.
- the merged dict is cached in `self._snippets_cache`.

Internal "save as snippet" already refreshes this cache after it writes:
`src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt.py` reloads
merged config, refreshes `self._user_snippets`, and clears
`self._snippets_cache`.

That only covers TUI-initiated snippet writes. External edits to
`~/.config/sase/sase.yml` or overlay files remain invisible until restart or
until some explicit code path refreshes those fields.

### XPrompts and Workflows

`src/sase/xprompt/loader.py:get_all_xprompts()` and
`src/sase/xprompt/workflow_loader.py:get_all_workflows()` are uncached public
loaders. They walk config, package resources, plugin resources, user/home
directories, CWD directories, and project-specific sources every time they are
called.

The main editable sources are:

- `~/.config/sase/sase.yml`;
- `~/.config/sase/sase_*.yml` overlays;
- `~/.xprompts/` and `~/xprompts/`;
- current CWD `.xprompts/` and `xprompts/`;
- `~/.config/sase/xprompts/{project}/`;
- known project workspace `.xprompts/`, `xprompts/`, and `sase.yml` for
  project-local browser/catalog behavior.

Package built-ins and plugin resources can be treated as immutable for a TUI
process. A plugin install/update can still require a restart unless SASE grows
a broader plugin reload story.

`sase ace` disables local `./sase.yml` inheritance in
`src/sase/main/ace_handler.py` via `set_include_local_config(False)`. The
Config Center xprompt browser separately loads project-local `sase.yml` files
from known projects because those are intentionally visible as browseable
definitions even when the app does not inherit the current repo's config.

### TUI Consumers

Prompt auto-completion already has a warm-cache concept:
`src/sase/ace/tui/widgets/_xprompt_arg_hints.py` warms
`XPromptAssistEntry` lists in a Textual worker and automatic completion uses
warm entries only.

There are still synchronous cold paths:

- explicit xprompt completion can call `build_xprompt_assist_entries()`
  synchronously;
- `XPromptSelectModal.__init__()` calls `_load_prompts()`, which calls
  `get_all_prompts()`;
- `XPromptBrowserPane.__init__()` calls `_load_xprompts()`, which calls
  `get_all_prompts()` and `get_all_project_local_prompts()`;
- `XPromptBrowserPane._reload_xprompts()` rebuilds synchronously after edit/add.

Auto-reload should fix those paths too. Otherwise the TUI may no longer need a
restart, but it can still block when opening a selector or browser.

## Performance Constraint

The relevant TUI performance rule is strict: no disk I/O, YAML parsing, package
resource discovery, subprocess work, or broad catalog construction on the
Textual event loop.

The event loop should do only cheap operations:

- read the current immutable snapshot reference;
- update a widget from already-built rows;
- set a dirty flag or schedule a worker;
- swap a completed snapshot if its generation is current.

Everything else belongs off-thread.

## Recommended Design

### 1. Add a `PromptCatalogService`

Create an ACE app-owned service, likely under
`src/sase/ace/tui/prompt_catalog/` or `src/sase/ace/tui/util/`, with a small
surface:

- `get_snippets() -> dict[str, str]`
- `get_prompts(project: str | None = None) -> dict[str, Workflow]`
- `get_xprompt_assist_entries(project: str | None = None) -> list[XPromptAssistEntry]`
- `get_browser_items(project: str | None = None) -> list[BrowserItem]`
- `schedule_refresh(reason: str, changed_paths: tuple[Path, ...] = ()) -> None`

Each getter returns an already-built snapshot. If a project-specific snapshot is
missing, schedule a warm build and return either the global snapshot or an empty
list, depending on the caller's current behavior. Explicit user actions can show
a lightweight "loading" state, but keystroke paths should never block waiting
for a build.

The snapshot should be immutable by convention: replace the whole object on
success instead of mutating shared dicts/lists in place.

### 2. Build Catalogs Once Per Refresh

The worker should avoid calling the high-level loaders repeatedly. Today
`get_all_prompts()`, `get_xprompt_snippets()`, and
`build_xprompt_assist_entries()` can each trigger overlapping discovery.

The cleaner implementation is:

1. Load workflows once with `get_all_workflows(project)`.
2. Load xprompts once with `get_all_xprompts(project)`.
3. Combine them into `prompts` using the same precedence as
   `get_all_prompts()`.
4. Build xprompt-derived snippets from that xprompt dict.
5. Reload user `ace.snippets` from merged config.
6. Resolve merged snippet references.
7. Project TUI assist/browser rows from the combined prompt dict.

This likely requires a small refactor in
`src/sase/xprompt/snippet_bridge.py`: add a pure
`get_xprompt_snippet_entries_from_catalog(xprompts)` helper so the service can
reuse the xprompt dict it already loaded.

### 3. Watch Editable Sources, Not Consumers

Use the existing inotify pattern from
`src/sase/ace/tui/util/fs_watcher.py` as the model:

- a daemon worker thread blocks in `select`;
- events are coalesced over a short idle window;
- callbacks enter Textual through `call_from_thread`;
- unsupported platforms silently fall back to polling;
- no event processing does file parsing on the UI thread.

This can be a new generic watcher rather than overloading `ArtifactWatcher`.
The artifact watcher has artifact-specific startup recursion and watch caps.
The prompt catalog watcher needs simpler source filtering and parent-directory
watching.

Watch these direct locations when present:

- `~/.config/sase/` for `sase.yml`, `sase_*.yml`, and `xprompts/` directory
  creation/deletion;
- `~/.config/sase/xprompts/` and project subdirectories under it;
- `~/.xprompts/` and `~/xprompts/`;
- CWD `.xprompts/` and `xprompts/`;
- known project workspace roots for `sase.yml` and `xprompts` directory
  creation;
- known project workspace `.xprompts/` and `xprompts/` directories when they
  exist.

Also watch parent directories when the target directory may not exist yet:
home for `.xprompts`/`xprompts` creation, CWD for local xprompt directory
creation, and known workspace roots for project-local xprompt directory
creation. These are non-recursive direct-child watches and should filter
irrelevant paths before scheduling a catalog refresh.

### 4. Add a Cheap Source Token

The watcher should not rebuild the full catalog for every event. It should
schedule a worker that first computes a source token off-thread:

- `sase.config.core.current_config_token()`;
- names plus `mtime_ns`/size for `*.md`, `*.yml`, and `*.yaml` in watched
  xprompt dirs;
- stat tokens for known project `sase.yml` files that are part of the browser
  catalog;
- a known-project workspace token if project lifecycle changes can add/remove
  project-local xprompt sources.

If the token matches the last successful snapshot token, skip the rebuild. This
keeps noisy parent-directory watches cheap and handles delete/create/rename
events accurately.

All token work still happens off-thread. The UI thread should only compare or
store the completed token.

### 5. Coalesce and Gate Refreshes

Use last-request-wins semantics:

- `scheduled`: a refresh is queued but not running;
- `running`: a worker is building a snapshot;
- `pending`: a change arrived while a worker was running;
- `generation`: only the newest successful result may replace the snapshot.

If a worker fails because a user is mid-save and YAML is temporarily invalid,
keep the old snapshot and log/notify softly. Do not replace a good snapshot with
an empty or partial one.

When a snapshot lands, refresh only visible surfaces that need it:

- prompt completion gets the new data on the next context refresh or keypress;
- open `XPromptSelectModal` and Config Center xprompt browser can rebuild their
  option lists from the snapshot while preserving filter/highlight;
- snippet expansion simply reads the new snippet map on the next expansion.

Avoid forced UI rebuilds while the user is typing unless the affected widget is
already open and the update is cheap.

## Why This Is Better Than Alternatives

### Do Not Reload on Every `get_snippets()`

This would be simple but wrong. Snippet expansion is on an interactive prompt
path, and xprompt-derived snippets require walking and parsing xprompt sources.
Even if config cache tokens make some config reads cheap, xprompt file discovery
is still not appropriate for key handling.

### Do Not Poll the Full Catalog

A periodic full reload would be functionally correct but wastes CPU and can
contend with TUI work through the GIL. Polling is acceptable only as a fallback
that computes a cheap source token off-thread at a low cadence, then rebuilds
only on token change.

### Do Not Put Watcher Callback Work on the Event Loop

The watcher callback should not call `load_merged_config()`, `get_all_prompts()`,
or YAML parsers. It should only mark the catalog dirty and schedule the worker.

### Do Not Add `watchdog` Just For This

The project already has a direct inotify implementation and `watchdog` is not a
declared runtime dependency in `pyproject.toml`. Reusing the existing pattern
keeps the dependency surface stable and matches current TUI refresh design.

### Do Not Only Fix Snippets

Snippets and xprompts share sources and caches. Xprompt-derived snippets depend
on the xprompt catalog, and prompt completion/modal surfaces need the same
fresh data. A snippet-only reload would solve the smallest visible case while
leaving `#` completion and xprompt selectors stale.

## Implementation Sketch

1. Add a pure snapshot builder module.

   Suggested type:

   ```python
   @dataclass(frozen=True)
   class PromptCatalogSnapshot:
       generation: int
       project: str | None
       source_token: tuple[object, ...]
       prompts: Mapping[str, Workflow]
       assist_entries: tuple[XPromptAssistEntry, ...]
       snippets: Mapping[str, str]
       browser_items: tuple[BrowserItem, ...]
   ```

2. Refactor `snippet_bridge` so xprompt snippets can be built from an already
   loaded xprompt catalog.

3. Add `PromptCatalogService` to ACE app state during `_init_app_state()`.
   `StartupMixin.get_snippets()` should delegate to it instead of owning
   `_user_snippets` and `_snippets_cache` directly.

4. Start a prompt-catalog watcher after first paint, next to
   `_start_artifact_watcher()`. Startup should not wait for it. Initial warming
   should run in a worker after mount.

5. Replace prompt text area xprompt-assist caches with service snapshots. Local
   frontmatter xprompts should remain live and be merged over the service
   snapshot exactly as they are today.

6. Change `XPromptSelectModal` and `XPromptBrowserPane` to accept prebuilt
   catalog rows or a catalog service reference. Their constructors should not
   call `get_all_prompts()` synchronously.

7. Make internal save/edit flows call `schedule_refresh(reason=...)` after the
   write returns. The watcher should also catch the same write, so this is a
   latency optimization, not the only invalidation path.

8. On app shutdown, stop the prompt-catalog watcher just like the artifact
   watcher.

## Test Plan

Add focused tests before broader TUI perf testing:

- unit test source-token changes for config edit, overlay create/delete, xprompt
  file create/delete/rename, and project-local `sase.yml` edit;
- unit test watcher filtering and coalescing with simulated changed paths;
- service test: external snippet edit refreshes `get_snippets()` without
  restarting the app;
- service test: external xprompt file creation refreshes assist entries and
  prompt maps;
- generation test: slow older refresh result cannot overwrite newer snapshot;
- invalid YAML test: old snapshot remains active and no empty catalog is
  published;
- prompt completion test: automatic completion does not call synchronous
  catalog loaders when the warm snapshot is cold;
- modal test: constructing `XPromptSelectModal` and `XPromptBrowserPane` from a
  snapshot does not call `get_all_prompts()`;
- save-flow test: "save as snippet" and "save as xprompt" schedule catalog
  refresh and update visible data.

Then run the TUI perf checks that matter for the requested constraint:

- `SASE_TUI_PERF=1 sase ace` around prompt typing and `#` completion;
- `SASE_TUI_TRACE=1 sase ace` while adding/editing xprompt files;
- the slow TUI benches if the implementation touches shared navigation or
  refresh plumbing.

## Risks and Open Questions

The biggest design risk is source scope. Watching every known project workspace
could grow the watch set in large installations. Start with active known
projects only, reuse a watch cap, and keep a slow off-thread token poll as the
fallback for missed sources.

The second risk is replacing good data with bad data during partial writes.
This should be handled by keeping the old snapshot on load/parse errors.

The third risk is config/plugin reload ambiguity. User config and file-backed
xprompts should auto-reload. Plugin package resources and built-in package
resources should stay process-static unless SASE later adds explicit plugin
reload support.

## Bottom Line

The best implementation is not "watch files and call the loaders." It is
"watch files, coalesce invalidations, rebuild one shared catalog snapshot
off-thread, and make every TUI consumer read that snapshot."

That gives immediate availability for new snippets and xprompts while keeping
the prompt input path, modal construction, and Textual event loop free of disk
work.
