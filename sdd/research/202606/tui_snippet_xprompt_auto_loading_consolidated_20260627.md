---
create_time: 2026-06-27
updated_time: 2026-06-27
status: research
---

# ACE TUI Snippet and XPrompt Auto-Loading

## Question

When a user adds a new SASE snippet in config, or a new xprompt in config or a
markdown/YAML xprompt file, how should the ACE TUI make it available without a
restart and without hurting TUI performance?

## Consolidated Recommendation

Add an ACE-owned prompt catalog refresh path that watches editable snippet and
xprompt sources, rebuilds the relevant catalogs off the Textual event loop, and
atomically swaps immutable in-memory snapshots on success.

The narrow restart bug is caused by stale TUI caches, not by a permanently
stale loader:

- Snippets are cached in `AceApp._user_snippets` and `AceApp._snippets_cache`.
- Xprompt completion and argument hints are cached per prompt text area in
  `_xprompt_arg_assist_entries_by_project`.
- Submitted prompt expansion already calls `get_all_xprompts()` live, so a
  manually typed new `#xprompt` can be expanded by launch-time processing even
  when the interactive completion list is stale.

The performance-safe fix is not just "clear those caches." Clearing them lets
existing lazy fallback paths rebuild synchronously on the next prompt editing
operation. Instead, keep the last good snapshot visible, schedule a background
rebuild, and swap the new snapshot back onto the UI thread only after it is
complete and still current.

## Verified Current Shape

### Snippets

Snippet definitions come from merged config `ace.snippets` plus xprompts that
declare snippet frontmatter.

Current TUI ownership:

- `src/sase/ace/tui/actions/_state_init.py:598` loads `ace.snippets` once into
  `self._user_snippets`.
- `src/sase/ace/tui/actions/startup.py:81` lazily builds the merged snippet
  registry in `get_snippets()` by calling `get_xprompt_snippets()`, overlaying
  user snippets, resolving snippet references, and caching the result in
  `self._snippets_cache`.
- `src/sase/ace/tui/widgets/_snippets.py:37` consumes snippets through
  `app.get_snippets()`.
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt.py:264`
  already has a refresh helper for in-TUI snippet saves, but external file
  edits do not trigger it.

Important performance implication: the current `get_snippets()` cache miss does
disk-backed xprompt discovery synchronously. An auto-load implementation should
move that rebuild into a worker instead of creating more cache misses on prompt
input paths.

### Xprompts

The public xprompt loaders are mostly live loaders:

- `src/sase/xprompt/loader.py:98` `get_all_xprompts(project)` aggregates
  internal, default, plugin, config, project, and file-backed xprompts on every
  call.
- `src/sase/xprompt/loader.py:170` `get_all_prompts(project)` merges workflows
  and xprompts on every call.
- `src/sase/xprompt/workflow_loader.py:265` scans workflow `.yml` and `.yaml`
  files from the xprompt search paths.
- `src/sase/xprompt/processor.py:319` uses `get_all_xprompts()` during submitted
  prompt expansion.

The stale interactive surface is the prompt text area cache:

- `src/sase/ace/tui/widgets/prompt_text_area.py:136` initializes
  `_xprompt_arg_assist_entries_by_project`.
- `src/sase/ace/tui/widgets/_xprompt_arg_hints.py:164` synchronously builds and
  stores entries on a cold cache miss.
- `src/sase/ace/tui/widgets/_xprompt_arg_hints.py:183` also has an existing
  worker-backed warm path.
- `src/sase/ace/tui/widgets/_prompt_soft_completion.py:147` schedules that warm
  path when soft completion may need xprompt entries.
- `src/sase/ace/tui/widgets/xprompt_completion.py:48` can still call
  `build_xprompt_assist_entries()` synchronously when explicit completion is
  invoked without warm entries.

There are also synchronous modal/browser paths:

- `src/sase/ace/tui/modals/xprompt_select_modal.py:131` calls
  `get_all_prompts()` in modal construction.
- `src/sase/ace/tui/modals/xprompt_browser_pane.py:77` calls browser catalog
  loading during pane initialization.
- `src/sase/ace/tui/modals/xprompt_save_target_modal.py:360` loads prompt rows
  synchronously.

Those modal paths are not the root of the "restart required" complaint, because
they reload when opened, but they are still event-loop disk work. If this area
is being touched for a performance-sensitive fix, the better end state is one
shared background-built catalog snapshot consumed by both prompt editing and
modal surfaces.

### Source Scope

Editable sources that matter for auto-loading:

- `~/.config/sase/sase.yml` and `~/.config/sase/sase_*.yml` overlays.
- Config-defined xprompts in the merged `xprompts:` section.
- Project-specific files under `~/.config/sase/xprompts/{project}/`.
- Home file-backed xprompts: `~/.xprompts/`, `~/xprompts/`.
- Current workspace file-backed xprompts: `./.xprompts/`, `./xprompts/`.
- Known project-local `sase.yml` and xprompt directories only for browser
  catalog behavior that intentionally shows all known projects.

`sase ace` disables CWD `sase.yml` inheritance in
`src/sase/main/ace_handler.py:61` via `set_include_local_config(False)`. Do not
accidentally make the prompt execution context inherit repo-local config just
because the browser can display known project-local definitions.

Built-in package xprompts and plugin package resources can stay process-static.
A plugin install/update should remain a restart-level event unless SASE gets a
separate plugin reload design.

## Performance Requirements

The TUI performance memory is strict: no disk I/O, YAML/Markdown parsing,
subprocess work, broad directory scans, or sleeps on the Textual event loop.

Allowed on the UI thread:

- set a dirty flag;
- bump a generation/epoch;
- schedule or debounce a worker;
- read the current snapshot reference;
- swap in a completed snapshot after checking the generation;
- update visible widgets from already-built rows.

Not allowed on the UI thread:

- `load_merged_config()`;
- `get_all_xprompts()`, `get_all_prompts()`, or workflow discovery;
- xprompt snippet discovery;
- source-token directory walks;
- YAML/Markdown parsing.

This also means `_refresh_snippet_caches()` should not be called directly from a
watcher callback unless it is refactored so the disk read happens in a worker
and only the resulting dict swap happens on the UI thread.

## Recommended Design

### 1. Add a Prompt Catalog Snapshot Owner

Create a small ACE app-owned service or state object. It can start narrow and
grow, but the ownership should be app-level rather than per `PromptTextArea` so
multi-pane invalidation is one epoch bump.

Suggested snapshot fields:

```python
@dataclass(frozen=True)
class PromptCatalogSnapshot:
    generation: int
    source_token: tuple[object, ...]
    snippets: Mapping[str, str]
    assist_entries_by_project: Mapping[str | None, tuple[XPromptAssistEntry, ...]]
    prompts_by_project: Mapping[str | None, Mapping[str, Workflow]]
    browser_items_by_project: Mapping[str | None, tuple[BrowserItem, ...]]
```

For a smaller first patch, only `snippets` and `assist_entries_by_project` need
to be implemented. Keep the shape compatible with later modal/browser use.

Getters must return memory-only data. If a requested project is missing, they
should schedule a warm build and return either the previous snapshot, global
entries, or an empty tuple according to the existing caller's behavior. They
must not run loaders synchronously.

### 2. Build Off-Thread and Swap Atomically

The worker should:

1. Compute a source token off-thread.
2. If the token is unchanged, return without rebuilding.
3. Load workflows and xprompts once for the needed project set.
4. Build prompt assist rows from that catalog.
5. Build xprompt-derived snippets from the already-loaded xprompt catalog.
6. Load user `ace.snippets` from merged config.
7. Resolve snippet references.
8. Return a complete immutable snapshot.

The UI completion callback should:

- ignore older generations;
- keep the old snapshot if parsing/loading fails;
- log or notify softly on invalid YAML rather than publishing an empty catalog;
- refresh only visible surfaces that are already open.

`src/sase/xprompt/snippet_bridge.py` currently exposes
`get_xprompt_snippets()` by calling `get_all_xprompts()`. Add a pure helper that
builds snippet entries from an already loaded xprompt dict so the snapshot
builder does not scan the same sources repeatedly.

### 3. Reuse the Existing Inotify Pattern

`src/sase/ace/tui/util/fs_watcher.py` already provides a dependency-free Linux
inotify watcher with a daemon thread, coalescing, and `call_from_thread`
dispatch. Reuse that implementation or extract a generically named wrapper for
prompt sources.

Prefer a separate prompt-source watcher/callback over blindly routing config
and xprompt paths through `_on_artifact_change()`. The artifact callback maps
unknown paths to agent/changespec dirty surfaces; prompt catalog changes should
not trigger unrelated refreshes.

Watcher behavior:

- watch existing source directories directly;
- watch parent directories for not-yet-existing xprompt dirs so creation is
  detected;
- filter changed paths before scheduling catalog work;
- debounce bursts from editor atomic saves;
- respect existing navigation and prompt-input gates before touching visible UI;
- stop the watcher on app shutdown.

Use a cheap source token as a correctness backstop:

- include `sase.config.core.current_config_token()`;
- include `mtime_ns` and size for `*.md`, `*.yml`, and `*.yaml` files in watched
  xprompt directories;
- include project-specific `~/.config/sase/xprompts/{project}` files when a
  project catalog has been requested;
- include known project-local files only for browser/all-project catalog
  snapshots.

The token calculation still belongs off-thread.

### 4. Provide a Non-Linux and Missed-Event Fallback

If inotify is unavailable, the feature should still self-heal. Use one of:

- token-on-access for deliberate completion/snippet actions, where the token
  check schedules a worker but never blocks the action; or
- a slow background token poll, also off-thread, that rebuilds only when the
  token changes.

Do not poll the full catalog. Poll only the cheap source token.

### 5. Optional Manual Reload

A manual "reload snippets/xprompts" action is useful as an escape hatch, but it
is not a substitute for auto-loading. If a keybinding is added, remember the
project gotcha: update `src/sase/default_config.yml` with the default keymap.

## What Not To Implement

- Do not clear `_snippets_cache` or `_xprompt_arg_assist_entries_by_project` and
  rely on current lazy rebuilds. Some lazy paths run synchronous loaders on the
  event loop.
- Do not call config or xprompt loaders from watcher callbacks, key handlers,
  modal constructors, or prompt completion code.
- Do not add `watchdog` or `watchfiles` just for this. The repo already has the
  needed inotify pattern and no runtime dependency is declared.
- Do not watch built-in package resource directories for this feature.
- Do not broaden this into all config hot reload unless that is an explicit
  separate goal.

## Suggested Phasing

1. Add prompt source token computation and a background snapshot builder for
   snippets plus xprompt assist entries.
2. Start a prompt-source watcher after first paint; on relevant changes,
   debounce and schedule a snapshot refresh.
3. Change `get_snippets()` and prompt text area xprompt assist reads to consume
   snapshots or app-owned warmed entries without synchronous fallback.
4. Add the source-token fallback for non-Linux or missed events.
5. Move `XPromptSelectModal`, `XPromptBrowserPane`, and save-target rows to
   consume prebuilt snapshots or show cached rows while refreshing in a worker.
6. Add optional manual reload.

This ordering fixes the restart problem first while creating the right end
state for the remaining synchronous catalog surfaces.

## Test and Measurement Plan

Unit tests:

- source-token changes for config edit, overlay create/delete, xprompt file
  create/delete/rename, and project-specific xprompt changes;
- watcher path filtering and event coalescing with simulated changed paths;
- worker generation behavior where an older refresh cannot overwrite a newer
  snapshot;
- invalid YAML keeps the old snapshot active;
- external snippet edit becomes visible without restart;
- external xprompt creation updates completion/argument-hint entries without
  restart;
- `get_snippets()` and completion paths do not call synchronous loaders on cache
  miss after the refactor.

TUI/perf checks:

- `SASE_TUI_PERF=1 sase ace` while typing, expanding snippets, and triggering
  `#` completion;
- `SASE_TUI_TRACE=1 sase ace` while adding/editing xprompt files;
- slow TUI benches if the implementation touches shared refresh, navigation, or
  widget construction paths.

## Open Decisions

- Is "available on the next deliberate completion/snippet action" acceptable, or
  should the watcher target sub-second availability after save?
- Should the initial implementation watch only active project sources, or also
  all known project-local sources for Config Center/browser freshness?
- Should modal/browser sync loading be fixed in the same change, or treated as a
  follow-up after prompt input auto-loading is working?

## Bottom Line

The best implementation is a prompt catalog snapshot owner, not scattered file
reloads. Watch editable sources, compute a source token and rebuild catalogs in
a worker, keep the old snapshot on failures, and make prompt-input consumers
read memory-only data. That solves auto-loading without adding event-loop work
to the TUI.
