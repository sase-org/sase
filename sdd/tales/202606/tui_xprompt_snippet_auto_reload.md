---
create_time: 2026-06-28 15:37:20
status: done
prompt: sdd/prompts/202606/tui_xprompt_snippet_auto_reload.md
---
# ACE TUI: Auto-Reload Snippets & XPrompts Without Restart

## Problem & Product Context

When a user adds or edits a SASE **snippet** (in a config file) or an **xprompt** (in a config file or a markdown/YAML
xprompt file), the running `sase ace` TUI keeps serving the old data until it is restarted. The user wants any newly
added or modified xprompt/snippet to become fully usable across all TUI xprompt surfaces immediately — "as if it had
been defined a month ago" — and this MUST NOT degrade TUI performance or block the Textual event loop.

### Root cause (the bug is narrow)

The xprompt/snippet **loaders are already live** — they re-read disk on every call and are _not_ memoized:

- `src/sase/xprompt/loader.py` `get_all_xprompts()` / `get_all_prompts()` aggregate internal, default, plugin, config,
  project, and file-backed xprompts on every call.
- `src/sase/xprompt/processor.py` already calls `get_all_xprompts()` during submitted-prompt expansion, so a manually
  typed brand-new `#xprompt` already expands correctly at launch time even today.
- XPrompt modals/browser (`xprompt_select_modal.py`, `xprompt_browser_pane.py`, `xprompt_save_target_modal.py`) reload
  their catalog when they are (re)opened, so they already reflect new definitions on next open.

The "restart required" symptom comes from **two interactive caches that are never invalidated on external edits**:

1. **Snippet expansion cache** — `AceApp._snippets_cache` built lazily in `get_snippets()`
   (`src/sase/ace/tui/actions/startup.py`). It is invalidated only by _in-TUI_ snippet saves via
   `_refresh_snippet_caches()` (`src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt_snippets.py`), never
   by an external editor edit. It is seeded once at init from merged config `ace.snippets`
   (`src/sase/ace/tui/actions/_state_init.py`).
2. **XPrompt completion / argument-hint cache** — the per-`PromptTextArea` dict `_xprompt_arg_assist_entries_by_project`
   (`src/sase/ace/tui/widgets/prompt_text_area.py`, `src/sase/ace/tui/widgets/_xprompt_arg_hints.py`). Entries are built
   once per project and never invalidated; the existing warm worker explicitly skips a project that is already cached.

So the fix is **not** "reload everything." It is: detect when editable prompt sources change, rebuild the affected
catalogs **off-thread**, and **atomically swap** fresh immutable snapshots back onto the UI thread — keeping the last
good snapshot visible until the new one is ready.

There is a consolidated research note for this exact question at
`sdd/research/202606/tui_snippet_xprompt_auto_loading_consolidated_20260627.md`; this plan follows its recommendation.

## Goals

- Externally adding/editing a snippet (config `ace.snippets`) becomes usable in snippet expansion without restart.
- Externally adding/editing/renaming an xprompt (config `xprompts:`, a markdown/YAML xprompt file in a watched
  directory, or a project-specific xprompt) becomes usable in xprompt **completion** and **argument hints** without
  restart.
- Zero added work on the Textual event loop beyond cheap O(1) bookkeeping: no disk I/O, no YAML/Markdown parsing, no
  directory walks, no loaders run on the UI thread.
- The feature self-heals on platforms without inotify and on missed events.

## Non-Goals

- Hot-reloading **all** application config (themes, keymaps, agent runtime config, etc.). This is scoped to
  prompt/snippet catalog sources only.
- Reloading **built-in package** xprompts or **plugin package** resources. Those ship in packages and stay
  process-static; a plugin install/update remains a restart-level event.
- Changing the prompt **execution/expansion** context. `sase ace` deliberately disables CWD `sase.yml` inheritance via
  `set_include_local_config(False)` (`src/sase/main/ace_handler.py`); this plan must not make the execution context
  start inheriting repo-local `sase.yml` just because new directories are being watched.
- Rewriting the modal/browser catalog loading. Those already refresh on open; converting them to consume the shared
  snapshot is an explicit follow-up (see Phase 5), not part of the core fix.

## Architecture Decision (and Rust-core boundary)

This is **TUI runtime glue**, not shared backend/domain logic. The catalog loaders it invokes (`get_all_xprompts`,
`get_all_prompts`, `get_xprompt_snippets`, `load_merged_config`, `current_config_token`) are existing Python functions,
and the new pieces — an inotify file watcher, a debounce/coalesce scheduler, an off-thread rebuild worker, an immutable
in-memory snapshot owned by the running `AceApp`, and the atomic UI-thread swap — are all presentation/runtime concerns
specific to keeping _this_ TUI fresh.

Per the repo's litmus test (would a web app/CLI/editor need this to match the TUI?): no. Other frontends call the live
loaders directly and don't hold a long-lived in-memory cache to invalidate. **No `sase-core` (Rust) changes are
required.** All work stays in the Python/TUI layer.

## Design

### 1. App-owned prompt catalog snapshot

Introduce a single app-level immutable snapshot, owned by `AceApp`, so that multi-pane invalidation is one swap instead
of N per-widget cache clears. Start minimal but keep the shape extensible for later modal/browser reuse.

```
PromptCatalogSnapshot (frozen):
    generation: int
    source_token: tuple[...]                      # cheap change-detection key
    snippets: Mapping[str, str]                   # merged + reference-resolved
    assist_entries_by_project: Mapping[str | None, tuple[XPromptAssistEntry, ...]]
```

App state added to `AceApp` (init in `_state_init.py`):

- `_prompt_catalog: PromptCatalogSnapshot | None`
- `_prompt_catalog_generation: int`
- `_prompt_catalog_rebuild_in_flight: bool`
- `_prompt_catalog_rebuild_pending: bool`
- `_prompt_catalog_projects: set[str | None]` — the project set to build for (always includes the default `None`; grows
  as panes request a project).

All getters return **memory-only** data. A getter for a project that is not yet in the snapshot schedules a background
warm build and returns the previous snapshot's value / global entries / empty per the existing caller's contract — it
must never run a loader synchronously.

### 2. Off-thread snapshot builder

Add a pure helper to `src/sase/xprompt/snippet_bridge.py` that derives snippet entries from an **already-loaded**
xprompt dict (e.g. `build_xprompt_snippet_entries_from_catalog(xprompts)`), so the builder loads xprompts **once** per
project instead of `get_xprompt_snippets()` re-scanning the same sources. (`get_xprompt_snippet_entries()` currently
calls `get_all_xprompts()` itself.)

A new app worker method (e.g. `_rebuild_prompt_catalog(generation, projects)`), run via `run_worker(..., thread=True)` /
`asyncio.to_thread`, does **entirely off-thread**:

1. Compute the prompt **source token** (see §4). If unchanged from the last successful build, return early — no rebuild.
2. For each requested project, load the xprompt catalog once (`get_all_xprompts` / `get_all_prompts`).
3. Build `XPromptAssistEntry` rows from each catalog (`build_xprompt_assist_entries`, reusing the loaded dict where
   practical).
4. Build xprompt-derived snippets from the loaded xprompt dict (the new pure helper), overlay user `ace.snippets` from
   `load_merged_config()`, then `resolve_snippet_references()`.
5. Return a complete immutable `PromptCatalogSnapshot` tagged with `generation`.

The UI-thread completion callback:

- **ignores stale generations** (`snapshot.generation != _prompt_catalog_generation`);
- **keeps the old snapshot on failure** (exception / invalid YAML) — soft-log or `notify(..., severity="warning")`,
  never publish an empty catalog;
- swaps `self._prompt_catalog = snapshot` and sets `self._snippets_cache = snapshot.snippets` (the rebuilt dict, **not**
  `None`, so the next `get_snippets()` never triggers a synchronous rebuild);
- refreshes only the **currently visible** prompt completion/arg-hint surface if one is open for the active project;
- if `_prompt_catalog_rebuild_pending` is set, schedules one trailing rebuild (last-request-wins coalescing, mirroring
  `_schedule_agents_async_refresh`).

`get_snippets()` becomes: return `self._prompt_catalog.snippets` if present; otherwise return the best
immediately-available value (previous cache or `_user_snippets`) and schedule a background rebuild. The catalog is also
warmed once during post-mount background loads so the snapshot is ready before the user types. (This strictly improves
on today's behavior, where the first snippet expansion does a synchronous disk scan on the event loop.)

### 3. Dedicated prompt-source inotify watcher

Reuse `src/sase/ace/tui/util/fs_watcher.py` (`ArtifactWatcher`) — the existing dependency-free Linux inotify watcher
with a daemon thread, coalescing, and `call_from_thread` dispatch. Create a **separate** watcher instance
(`self._prompt_source_watcher`) with its own callback `_on_prompt_source_change(changed_paths)`.

Do **not** route prompt-source paths through the existing `_on_artifact_change()`; that callback maps unknown paths to
agent/changespec dirty surfaces, and prompt catalog edits must not trigger unrelated refreshes.

Watch set:

- Config dir `~/.config/sase` (covers `sase.yml` and `sase_*.yml` overlays).
- File-backed xprompt search dirs from `get_xprompt_search_paths()`: `./.xprompts`, `./xprompts`, `~/.xprompts`,
  `~/xprompts`.
- Project-specific xprompt dirs `~/.config/sase/xprompts/{project}` for projects whose catalog has been requested.
- Parent directories of not-yet-existing xprompt dirs, so first-time creation of e.g. `~/.xprompts/` is detected
  (inotify on a parent fires for direct-child creation; `ArtifactWatcher` already auto-installs watches on newly created
  subdirectories).

Callback behavior (cheap, UI thread):

- filter changed paths to relevant suffixes (`.md`, `.yml`, `.yaml`) and the config files; if nothing relevant, return;
- debounce on top of the watcher's 50 ms coalesce (a short timer, ~250–400 ms) to absorb editor atomic-save bursts
  (write-temp + rename);
- bump `_prompt_catalog_generation` and schedule the off-thread rebuild with the in-flight/pending coalescing guard.

Start the watcher in `_start_post_mount_background_loads()` alongside `_start_artifact_watcher()`
(`src/sase/ace/tui/actions/startup.py`); stop it on unmount next to `_stop_artifact_watcher()`. A `False` start return
(no inotify) is non-fatal and falls through to the token fallback in §6.

### 4. Cheap source token (correctness backstop)

A pure, off-thread `prompt_source_token()` that combines:

- `sase.config.core.current_config_token()` (covers `sase.yml` + overlays);
- `stat_token` (`mtime_ns` + size) for `*.md` / `*.yml` / `*.yaml` files in the watched file-backed xprompt directories;
- `stat_token` for files under `~/.config/sase/xprompts/{project}` for each requested project.

The token is computed in the builder worker, never on the UI thread. It both short-circuits no-op rebuilds and powers
the non-inotify fallback.

### 5. PromptTextArea consumes app-owned entries

Change `src/sase/ace/tui/widgets/_xprompt_arg_hints.py` `_get_xprompt_arg_assist_entries()` to read the app snapshot
(`app._prompt_catalog.assist_entries_by_project`) instead of the per-instance dict, then merge the **live local**
xprompts (Frontmatter Panel `xprompts:` field) fresh on every call, exactly as today via `merge_local_xprompt_entries`.

- On a project miss, ask the app to warm that project off-thread and return local-only / empty until ready — **no**
  synchronous per-instance build.
- Remove the per-instance synchronous build path in `_get_xprompt_arg_assist_entries()` and the explicit-completion
  synchronous fallback in `src/sase/ace/tui/widgets/xprompt_completion.py`; both route through the app warm path.
- The per-instance `_xprompt_arg_assist_entries_by_project` / warming sets / `on_worker_state_changed` warm machinery in
  `_xprompt_arg_hints.py` is either removed or reduced to thin delegation to the app owner.

When the snapshot swaps (§2), the app refreshes the visible completion surface, so all panes reflect the new catalog
after one swap.

### 6. Non-inotify / missed-event fallback

If inotify is unavailable, or to guard against a missed event, add a token-on-access backstop: on a deliberate
completion/snippet action, if the watcher is inactive, compare a cached source token **off-thread**; when it has
changed, schedule a rebuild. The action itself never blocks — worst case the new data is "available on the next
deliberate action." (Alternatively, a slow off-thread token poll; either way poll only the cheap token, never the full
catalog.)

### 7. Optional: manual reload escape hatch

A manual "reload snippets/xprompts" action (keymap) is a useful escape hatch but not a substitute for auto-loading. If
added: it just bumps the generation and schedules the off-thread rebuild. Per repo conventions this requires updating
the default keymap in `src/sase/default_config.yml`, the `?` help modal, and the footer/help docs in `src/sase/ace/`.
Treat as optional.

## Phasing

1. **Snapshot owner + off-thread builder.** Add `PromptCatalogSnapshot`, app state, the pure `snippet_bridge` helper,
   `prompt_source_token()`, the rebuild worker, the generation-guarded swap, and warm-at-post-mount. Point
   `get_snippets()` at the snapshot. (Fixes snippets; sets up xprompts.)
2. **Prompt-source watcher.** Add the dedicated `ArtifactWatcher` + filtered, debounced callback that schedules
   rebuilds; start/stop in post-mount / unmount.
3. **PromptTextArea reads app entries.** Migrate completion + argument-hint reads to the snapshot; drop per-instance
   synchronous builds. (Fixes the xprompt completion/hint staleness.)
4. **Token fallback.** Add the non-Linux / missed-event token backstop.
5. **(Follow-up) Modals/browser** consume the shared snapshot, showing cached rows while a worker refreshes — removing
   their remaining on-open event-loop disk work.
6. **(Optional) Manual reload** keymap + help/docs/`default_config.yml` updates.

Phases 1–4 resolve the user-reported restart problem; 5–6 are quality follow-ups.

## Performance Safeguards (hard requirements)

Allowed on the UI thread: set a dirty flag, bump a generation, schedule/debounce a worker, read the current snapshot
reference, swap a completed snapshot after a generation check, update already-built rows in a visible widget.

Forbidden on the UI thread: `load_merged_config()`, `get_all_xprompts()` / `get_all_prompts()` / workflow discovery,
xprompt snippet discovery, source directory walks / `stat` loops, YAML/Markdown parsing. In particular,
`_refresh_snippet_caches()` must not be called from a watcher callback unless its disk read is moved into the worker and
only the dict swap lands on the UI thread.

Coalescing/back-pressure: rely on the watcher's 50 ms coalesce + a ~250–400 ms debounce + an in-flight/pending
trailing-rebuild guard so editor save bursts and overlapping changes collapse to a single rebuild. Respect existing
activity gates where a swap would touch a visible surface during j/k navigation or active typing (defer the visible
refresh, not the off-thread rebuild).

## Testing & Verification

Unit tests:

- `prompt_source_token()` changes for: config edit, overlay create/delete, xprompt file create/delete/rename,
  project-specific xprompt change; and is stable (unchanged) when nothing relevant changed.
- Watcher path filtering + coalescing with simulated changed paths.
- Generation guard: a slow older rebuild cannot overwrite a newer snapshot.
- Invalid YAML keeps the previous snapshot active (no empty publish).
- External snippet edit becomes visible to `get_snippets()` without restart.
- External xprompt create/edit updates completion + argument-hint entries without restart.
- After the refactor, `get_snippets()` and the completion paths do **not** call synchronous loaders on a cache miss.

TUI / perf checks:

- `SASE_TUI_PERF=1 sase ace` while typing, expanding snippets, and triggering `#` completion — no event-loop stalls.
- `SASE_TUI_TRACE=1 sase ace` while adding/editing xprompt files.
- Manual: edit `~/.xprompts/foo.md` and a config `ace.snippets` entry in an external editor; confirm `#foo`
  completion/hints and the new snippet trigger work in the already-running TUI within ~1s, with no restart.

Repo gates: run `just check` (after `just install`) for any non-bead / non-research file changes.

## Open Decisions

- Sub-second availability after save vs. "available on the next deliberate completion/snippet action" for the fallback
  path — the inotify path targets sub-second; the token fallback is action-triggered.
- Watch only the active project's sources, or also all known project-local sources for browser/Config-Center freshness
  (ties into Phase 5).
- Whether to ship the optional manual-reload keymap in this change or defer it.

## Bottom Line

Add an app-owned prompt-catalog snapshot, watch the editable snippet/xprompt sources with a dedicated inotify watcher,
rebuild catalogs in a worker keyed by a cheap source token, keep the last good snapshot on failure, and make the
prompt-input snippet/completion/hint surfaces read memory-only data. This makes newly added or modified snippets and
xprompts immediately usable in the running TUI without a restart and without adding any blocking work to the Textual
event loop.
