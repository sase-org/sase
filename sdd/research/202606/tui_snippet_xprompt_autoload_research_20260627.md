# TUI Auto-Loading of Snippets & XPrompts — Research

**Date:** 2026-06-27
**Status:** Research / design exploration (no implementation)
**Goal:** Pick a design that makes newly-defined snippets and xprompts usable in a
running `sase ace` TUI **without a restart**, while guaranteeing **zero impact on TUI
responsiveness** (no main-thread/event-loop blocking).

---

## 1. Executive Summary

Today, defining a new snippet (in a `sase.yml` `ace.snippets` mapping) or a new xprompt
(in an `xprompts/` markdown/yaml file or in `sase.yml`) requires restarting the TUI before
it can be used in the prompt input. The restart requirement is **not** caused by the
loaders themselves (they re-scan disk on every call) — it is caused by **two in-memory
caches that are never invalidated during a session**:

1. **Snippet registry cache** — `AceApp._snippets_cache` + `AceApp._user_snippets`.
2. **XPrompt completion / argument-hint cache** — `PromptTextArea._xprompt_arg_assist_entries_by_project`.

There is already a proven, non-blocking, **dependency-free inotify file watcher** in the
codebase (`ArtifactWatcher`, used for agent artifacts), plus an established
"invalidate-flag → background reload → atomic swap" refresh pattern documented in
`memory/tui_perf.md`. The recommended design reuses both.

**Recommendation (detail in §7):** Extend the existing `ArtifactWatcher` to watch the
snippet/xprompt source files, and on a (coalesced, debounced) change event, invalidate the
two caches on the UI thread (an O(1) operation) and let the existing lazy/worker rebuild
path repopulate them off-thread. Add a cheap **mtime-token correctness backstop** (mirroring
`current_config_token()`) so the feature self-heals on platforms where inotify is
unavailable (non-Linux). This keeps every expensive step (disk scan + markdown/YAML parse)
off the event loop.

---

## 2. Problem Statement

- **User-visible symptom:** "Every time I define a new snippet or xprompt in a config or
  markdown file, I must restart the TUI to use it."
- **Hard constraint:** The fix **must not** affect TUI performance — no synchronous disk
  I/O, parsing, or blocking work on the Textual event loop (the p95 < 16 ms/keystroke
  budget in `memory/tui_perf.md` must be preserved).
- **Scope:** The prompt-input editing surfaces (inline `#xprompt` completion, snippet
  expansion, argument hints). Modal browsers already reload on open (see §3.4).

---

## 3. Current Architecture (verified findings)

All paths relative to repo root; line numbers captured 2026-06-27.

### 3.1 Snippets — definition, load, cache, consume

**Where snippets come from**
- User snippets: `ace.snippets` mapping in the merged config — `~/.config/sase/sase.yml`,
  overlay `~/.config/sase/sase_*.yml`, local `./sase.yml`, plus `default_config.yml`
  (`src/sase/default_config.yml:31`).
- XPrompt-derived snippets: any xprompt markdown file with a `snippet:` front-matter field,
  discovered across the xprompt search paths (see §3.2).

**Load + cache (two-tier, lazy)**
- User snippets are read once at state init into `_user_snippets`, and the merged cache is
  left empty:
  - `src/sase/ace/tui/actions/_state_init.py:591-599`
    ```python
    user_snippets = ace_cfg.get("snippets", {}) ...
    # Defer the xprompt snippet scan ... Cold startup's first paint never needs snippets
    self._user_snippets = dict(user_snippets)
    self._snippets_cache: dict[str, str] | None = None
    ```
- The merged registry is built lazily and cached on first access:
  - `src/sase/ace/tui/actions/startup.py:81-102` — `get_snippets()` merges
    `get_xprompt_snippets()` + `_user_snippets`, runs `resolve_snippet_references()`, and
    stores the result in `self._snippets_cache`. Subsequent calls reuse the cache.
- XPrompt snippet source: `src/sase/xprompt/snippet_bridge.py` (`get_xprompt_snippets`,
  `get_xprompt_snippet_entries`, `_xprompt_to_snippet_template`).

**Consume**
- `src/sase/ace/tui/widgets/_snippets.py:35-74` — `SnippetExpansionMixin._try_expand_snippet()`
  calls `self._ace_app.get_snippets()`. Because it always reads through `get_snippets()`,
  **nulling `_snippets_cache` is sufficient to pick up changes** — no consumer-side wiring
  needed.

**Existing (partial) invalidation**
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt.py:259-280` —
  `_reload_user_snippets()` re-reads `load_merged_config()` into `_user_snippets` and sets
  `self._snippets_cache = None`. **This already does exactly what we need — it just only
  fires after an in-TUI "save xprompt" action, not on external file edits.**

**Rust boundary:** Snippet loading is **pure Python**; no `sase_core_rs` FFI involved.

### 3.2 XPrompts — discovery, load, cache, consume

**Discovery (search paths, priority order)**
- `src/sase/xprompt/loader_sources.py:151-176` — `get_xprompt_search_paths()`:
  1. `./.xprompts/` (CWD, hidden)
  2. `./xprompts/` (CWD)
  3. `~/.xprompts/`
  4. `~/xprompts/`
  5. `~/.config/sase/xprompts/{project}/`
  6. Built-in `src/sase/default_xprompts/*.md`
  7. Internal `src/sase/xprompts/*.md`
- Workflow `.yml`/`.yaml` files: `src/sase/xprompt/workflow_loader.py:265-290`
  (`_discover_workflow_files()`), same directory set.
- Config-sourced xprompts: `src/sase/config/core.py` (`load_xprompts_by_source()`), layered
  default → plugin → user → overlay → local.

**Load**
- `src/sase/xprompt/loader.py:98-150` — `get_all_xprompts(project)` aggregates all sources
  on **every call (no module-level cache)**. The only cached thing is project detection:
  `src/sase/xprompt/loader.py:63` — `@functools.cache def detect_project()`.
- Unified merge: `get_all_prompts()` (`loader.py:170-198`).

**Cache (the one that requires a restart)**
- `src/sase/ace/tui/widgets/prompt_text_area.py:136-140` — per-`PromptTextArea` dict:
  ```python
  self._xprompt_arg_assist_entries_by_project: dict[str | None, list[XPromptAssistEntry]] = {}
  self._xprompt_arg_assist_warming_projects: set[str | None] = set()
  self._xprompt_arg_assist_worker_projects: dict[str, str | None] = {}
  ```
- Populated lazily / warmed in a worker:
  - `src/sase/ace/tui/widgets/_xprompt_arg_hints.py:156-170` — `_get_xprompt_arg_assist_entries()`
    builds + caches per project (local frontmatter xprompts are merged fresh each call, but
    the **disk-backed catalog is cached and never invalidated mid-session**).
  - `_xprompt_arg_hints.py:179-200` — `_warm_current_xprompt_assist_entries()` /
    `_schedule_xprompt_assist_warm()` build the catalog in a background `run_worker`.
- Source of entries: `src/sase/ace/tui/widgets/_xprompt_arg_assist_catalog.py:18-46`
  (`build_xprompt_assist_entries`) → `src/sase/xprompt/catalog.py:95`
  (`build_structured_xprompts_catalog`) → `get_all_xprompts()` (uncached).

**Consume**
- Inline `#name` completion candidates: `src/sase/ace/tui/widgets/xprompt_completion.py:30`
  (`build_xprompt_completion_candidates`), fed by the cached assist entries above.
- Argument hints: `_xprompt_arg_hints.py` (`_refresh_xprompt_arg_hint_from_cursor`, etc.).
- `#name` expansion in submitted prompts: `src/sase/xprompt/processor.py:267-310`
  (`process_xprompt_references`) calls `get_all_xprompts()` live — so **submitted-prompt
  expansion is already fresh**; the staleness is in the *interactive completion/hint*
  surface only.

**Rust boundary:** XPrompt discovery/loading is **pure Python** (Rust core is used only for
frontmatter schema validation and agent-launch token scanning, not catalog building).

### 3.3 Why "restart required" — precise root cause

| Surface | Reads from | Cached? | Reflects new files w/o restart? |
|---|---|---|---|
| Submitted-prompt `#name` expansion | `get_all_xprompts()` live | No | **Yes (already)** |
| XPrompt select / browser modals | `get_all_prompts()` at modal construction | Per-modal, rebuilt on open | **Yes (reopen modal)** |
| Inline `#name` completion + arg hints | `_xprompt_arg_assist_entries_by_project` | **Yes, never invalidated** | **No** |
| Snippet expansion / completion | `_snippets_cache` + `_user_snippets` | **Yes, invalidated only on in-TUI save** | **No** |

So the work is narrowly scoped: **invalidate two caches when the underlying files change.**

### 3.4 Config merge already detects file changes cheaply

- `src/sase/config/core.py:61-83` — `current_config_token()` builds a cache key from a
  per-file `stat_token()` = `(path, mtime_ns, size)`. `load_merged_config()` already
  re-reads when this token changes. This is the model for an mtime-based correctness
  backstop, and means `_reload_user_snippets()` will pick up edited config files correctly
  *once it is triggered*.

---

## 4. Performance Constraints (from `memory/tui_perf.md`)

- **Never block the event loop.** No sync disk I/O, JSON/YAML parsing, subprocess, or
  `time.sleep` in action/message handlers. Push to `asyncio.to_thread()` /
  `run_worker(..., thread=True)`, marshal back with `call_after_refresh()` / `call_later()`.
- **Show cached instantly, reload in background; coalesce with last-request-wins flags.**
- **Debounce, don't block.** Detail/diagnostic surfaces debounce (~150 ms);
  per-keystroke target p95 < 16 ms.
- **Respect activity gates.** Defer non-urgent work while the user is mid-navigation
  (`NavigationGate`, 250 ms) or typing in the prompt input.

Implication: the *detection* may run on a background thread, but the *only* thing allowed on
the UI thread is the O(1) cache invalidation (setting a dict to `{}`/`None`). The actual
re-scan + parse must happen lazily on next access (already worker-backed for the assist
cache) or in an explicit worker.

---

## 5. Reusable Infrastructure (already in the repo)

- **`ArtifactWatcher`** — `src/sase/ace/tui/util/fs_watcher.py`
  - ctypes-based Linux **inotify** watcher (no external dependency).
  - Dedicated **daemon thread** with a `select()` loop (non-blocking).
  - **Event coalescing** (`DEFAULT_COALESCE_S = 0.05`) collapses bursts into one callback.
  - Thread-safe dispatch via `app.call_from_thread()`.
  - Watch budget cap (`MAX_INOTIFY_WATCHES = 4096`); handles recursively-created dirs.
  - `start()` returns `False` when inotify is unavailable (graceful no-op fallback).
- **Watcher wiring** — `src/sase/ace/tui/actions/startup.py:403-443`
  (`_start_artifact_watcher`) currently watches `~/.sase/projects/*/artifacts`, project
  `.sase` files, `sdd/beads/`, and `~/.sase/notifications/`.
- **Change routing** — `src/sase/ace/tui/actions/event_refresh/_watcher.py:17+`
  (`_on_artifact_change`) maps changed paths → dirty flags (`_dirty_changespecs`,
  `_dirty_agents`, ...), defers during j/k navigation and prompt typing. This is the exact
  pattern to extend.
- **Background patterns available:** `run_worker(thread=True)`, `asyncio.to_thread()`,
  `set_timer()` (debounce), `set_interval()` (poll), `call_from_thread()`.
- **Dependencies:** `pyproject.toml:36-51` — no `watchdog`/`watchfiles`; inotify is hand-rolled.
  (A new design should avoid adding a dependency; the in-tree watcher already covers Linux.)

---

## 6. Design Options

### Option A — Event-driven inotify (extend `ArtifactWatcher`) + dirty-flag invalidation

Add the snippet/xprompt source paths to the existing watcher. On a coalesced change event
(already marshalled to the UI thread), debounce briefly, then invalidate the two caches
(O(1)); the existing lazy/worker rebuild repopulates off-thread.

- **Pros:** Near-instant; zero polling overhead; reuses proven, dependency-free infra and
  the blessed dirty-flag pattern; expensive work stays off the event loop; coalescing +
  navigation/typing gates already implemented.
- **Cons:** Linux-only (inotify); needs care for editor atomic saves (temp-write + rename →
  rely on `IN_CREATE`/`IN_MOVED_TO`, which the watcher already handles) and for
  not-yet-existing dirs (watch the parent / handle `IN_CREATE` of the dir). Adds a few
  watches against the 4096 budget (xprompt dirs are few — negligible).

### Option B — Lazy mtime-token invalidation (poll-on-access)

No watcher. Store a `stat_token()`-style fingerprint of the relevant files alongside each
cache (mirroring `current_config_token()`). When a cache is *accessed*, cheaply recompute
the token; if it changed, mark dirty and rebuild **in a worker** (never synchronously).

- **Pros:** Cross-platform; no watcher thread; no inotify budget; self-correcting; matches
  an existing idiom. Stat of ~6–10 files is microseconds.
- **Cons:** Only refreshes when the surface is next used (acceptable — you only need fresh
  data when you actually complete/expand). Must be disciplined to offload the rebuild;
  naive implementation risks a synchronous re-scan on the completion path. Token recompute
  must stay off the per-keystroke hot path (gate it to completion-trigger events).

### Option C — Periodic background poll (`set_interval`)

A timer (e.g., every 2–5 s) recomputes the file tokens **in a worker**; on change,
invalidate caches.

- **Pros:** Simple; cross-platform; bounded cost; entirely off the keystroke path.
- **Cons:** Up to interval-length latency; periodic wakeups (tiny but nonzero, slightly at
  odds with idle-CPU goals); still needs the worker discipline of B.

### Option D — Explicit refresh (keybinding / on-modal-open only)

Add a "reload snippets/xprompts" keybinding that nulls the caches; keep the existing
modal-reopen behavior.

- **Pros:** Trivial; zero background cost.
- **Cons:** Not *auto*-loading — fails the stated goal. Useful only as a complementary
  manual escape hatch.

---

## 7. Comparison & Recommendation

| Criterion | A: inotify | B: poll-on-access | C: interval poll | D: manual |
|---|---|---|---|---|
| Latency to availability | ~instant | next access | ≤ interval | on demand |
| Event-loop blocking risk | none (O(1) on UI) | none if rebuild offloaded | none if offloaded | none |
| Background cost when idle | ~zero | zero | small periodic | zero |
| Cross-platform | Linux only | yes | yes | yes |
| Reuses existing infra | **yes** (`ArtifactWatcher`) | partial (`stat_token`) | partial | partial |
| New dependency | no | no | no | no |
| Meets "auto" goal | yes | yes | yes | **no** |
| Implementation complexity | medium | low–medium | low | trivial |

### Recommendation: **A as primary, with B as a correctness backstop, and D as a cheap extra**

1. **Primary — Option A (event-driven):** Extend `_start_artifact_watcher()` to also watch
   the snippet/xprompt source files/dirs, and add an `_on_config_source_change()` handler
   (alongside `_on_artifact_change()`) that:
   - runs on the UI thread but does **only** O(1) work: set `app._snippets_cache = None`,
     re-read `_user_snippets` via the existing `_reload_user_snippets()`, and clear each
     live `PromptTextArea._xprompt_arg_assist_entries_by_project` (+ warming/worker sets);
   - is **debounced** with `set_timer()` (~200–300 ms) so a flurry of saves collapses to one
     invalidation, and **deferred** while the user is mid-navigation or typing (reuse the
     `NavigationGate` / prompt-input deferral already in `_watcher.py`);
   - lets repopulation happen via the existing lazy path on next access and the existing
     `_schedule_xprompt_assist_warm()` worker — so **no scan/parse ever touches the event
     loop**.

2. **Backstop — Option B (mtime token):** Even with the watcher, store a lightweight
   `stat_token()` fingerprint of the watched files. When a cache is accessed, if the token
   changed but no event fired (inotify missed it, or platform without inotify), mark dirty
   and rebuild **in a worker**. This guarantees correctness when `ArtifactWatcher.start()`
   returns `False` (non-Linux) and covers any missed events — at the cost of a handful of
   `os.stat` calls gated to completion-trigger events (not per keystroke).

3. **Extra — Option D:** A manual "reload config" keybinding (the codebase already has an
   `action_reload_projects` precedent at `src/sase/ace/tui/modals/projects_pane.py:496`).
   Near-free, and a good escape hatch for power users / when watching is disabled. (Remember
   the gotcha: register any new keymap in `src/sase/default_config.yml`.)

Rationale: A gives the best UX and rides infrastructure already proven non-blocking; B makes
it robust and portable for negligible cost; D is a cheap belt-and-suspenders. The
combination keeps every expensive operation off the main thread, satisfying the hard
constraint.

---

## 8. Non-Blocking Flow (recommended path)

```
[file saved on disk]
        │  (kernel inotify; watcher daemon thread, select() loop)
        ▼
ArtifactWatcher coalesces (50 ms)            ← background thread, no UI cost
        │  app.call_from_thread(_on_config_source_change, paths)
        ▼
_on_config_source_change(paths)              ← UI thread, but only:
    • if navigating/typing → stash paths, set_timer to retry (defer)
    • else set_timer(~250 ms) debounce
        ▼
_apply_config_source_invalidation()          ← UI thread, O(1):
    • app._snippets_cache = None
    • app._reload_user_snippets()            (re-reads merged config via mtime token)
    • for each PromptTextArea: _xprompt_arg_assist_entries_by_project.clear()
                               (+ clear warming/worker tracking sets)
        ▼
next completion/expansion access  →  lazy build + _schedule_xprompt_assist_warm worker
                                     (get_all_xprompts / get_snippets)   ← background thread
        ▼
atomic cache swap on worker completion  →  fresh candidates available
```

Only the middle box runs on the event loop, and it is constant-time dict/attribute
mutation. The disk scan + markdown/YAML parse always run on a worker or lazily on the next
deliberate user action.

---

## 9. Edge Cases & Risks

- **Editor atomic saves** (write tmp → rename): handle via `IN_CREATE` / `IN_MOVED_TO`, not
  just `IN_MODIFY`. The existing watcher already tracks these — verify when wiring xprompt
  dirs.
- **Directories that don't exist yet** (`./xprompts/` created later): watch the parent dir
  and react to dir-creation, or (re)install a watch on `IN_CREATE` of the directory.
  `ArtifactWatcher._add_watch_tree()` already supports recursive post-creation watches.
- **inotify watch budget** (`MAX_INOTIFY_WATCHES = 4096`): snippet/xprompt dirs are few;
  cost is negligible, but count them deliberately.
- **Project-keyed cache:** `_xprompt_arg_assist_entries_by_project` is keyed by project;
  invalidate **all** entries (simplest) or the affected project only.
- **Multiple `PromptTextArea` instances:** several prompt bars/panes may exist; invalidation
  must iterate all live instances (or have them read through an app-level accessor that owns
  the cache + an epoch counter, so a single bump invalidates everyone — cleaner long-term).
- **Debounce vs. perceived latency:** keep debounce small (~200–300 ms) so the UX feels
  "instant" without thrashing on multi-file saves.
- **Config token already handles edits:** because `load_merged_config()` keys on
  `current_config_token()`, `_reload_user_snippets()` will reflect edited config — but only
  when called. The watcher is what makes it get called.
- **Non-Linux fallback:** if `ArtifactWatcher.start()` returns `False`, the feature must
  degrade to Option B (poll-on-access) so it still works (just lazily) — don't leave it
  silently dead.
- **Don't watch built-in/internal xprompt dirs** (`src/sase/default_xprompts`,
  `src/sase/xprompts`): they ship with the package and won't change at runtime.

---

## 10. Rust Core Boundary

`memory/rust_core_backend_boundary.md` says shared backend/domain behavior belongs in
`../sase-core`. This feature is **presentation-layer**: it is TUI cache invalidation +
file-change detection driving Textual surfaces. The snippet/xprompt **loading logic is
already pure Python** in this repo, so this change does **not** cross the boundary and does
not require Rust changes. (If, separately, the xprompt/snippet *catalog* were ever moved
into the Rust core, the watcher/invalidation glue here would stay Python and call through
the binding — but that is out of scope.)

---

## 11. Suggested Phasing (for a future plan)

1. **Phase 1 — Snippets (lowest risk):** Watch config + xprompt-snippet source files; on
   change, call the existing `_reload_user_snippets()` (already nulls `_snippets_cache`).
   Snippets consume through `get_snippets()`, so nothing else needs wiring.
2. **Phase 2 — XPrompt completion/arg-hints:** Invalidate
   `_xprompt_arg_assist_entries_by_project` (all live prompt panes) on change; rely on the
   existing warm-worker + lazy rebuild. Consider centralizing the cache behind an app-level
   accessor with an epoch counter so a single bump invalidates all panes.
3. **Phase 3 — Backstop + fallback:** Add the `stat_token()` correctness check on access and
   the non-inotify periodic-poll fallback (Option C) for non-Linux.
4. **Phase 4 — Manual reload keybinding (Option D)** + `default_config.yml` keymap entry +
   help-modal/footer updates per `src/sase/ace/AGENTS.md`.

---

## 12. Open Questions (for the user / design review)

1. **Acceptable latency:** Is "appears within ~300 ms of save" the target, or is
   "appears next time I trigger completion" (pure Option B, simplest, zero watcher) good
   enough? The latter is materially less code.
2. **Scope of watched config:** Watch only `ace.snippets`/`xprompts` source files, or all
   config files (so e.g. keymap/model changes also hot-reload)? This research scopes to
   snippets/xprompts only.
3. **Non-Linux importance:** How much do we care about macOS/other (no inotify)? If "Linux
   only is fine," we can skip the poll fallback and lean entirely on Option A.
4. **Centralize the assist cache?** Moving `_xprompt_arg_assist_entries_by_project` to an
   app-level owner with an epoch counter is cleaner for multi-pane invalidation but is a
   small refactor; acceptable now or defer?

---

## Appendix — Key File References

| Concern | File:Line |
|---|---|
| User snippets loaded at init | `src/sase/ace/tui/actions/_state_init.py:591-599` |
| Snippet registry build + cache | `src/sase/ace/tui/actions/startup.py:81-102` (`get_snippets`) |
| Snippet cache invalidation (exists) | `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_xprompt.py:259-280` (`_reload_user_snippets`) |
| Snippet consumption | `src/sase/ace/tui/widgets/_snippets.py:35-74` |
| XPrompt search paths | `src/sase/xprompt/loader_sources.py:151-176` |
| Workflow file discovery | `src/sase/xprompt/workflow_loader.py:265-290` |
| XPrompt aggregate loader (uncached) | `src/sase/xprompt/loader.py:98-150` |
| Project detection cache | `src/sase/xprompt/loader.py:63` (`@functools.cache`) |
| XPrompt completion/arg-hint cache | `src/sase/ace/tui/widgets/prompt_text_area.py:136-140`; `_xprompt_arg_hints.py:156-200` |
| Assist entries source | `_xprompt_arg_assist_catalog.py:18-46` → `src/sase/xprompt/catalog.py:95` |
| Inline `#name` expansion (live) | `src/sase/xprompt/processor.py:267-310` |
| Config merge mtime token | `src/sase/config/core.py:61-83` (`current_config_token`) |
| inotify watcher (reusable) | `src/sase/ace/tui/util/fs_watcher.py` |
| Watcher wiring at startup | `src/sase/ace/tui/actions/startup.py:403-443` (`_start_artifact_watcher`) |
| Artifact change routing (pattern) | `src/sase/ace/tui/actions/event_refresh/_watcher.py:17+` |
| Manual reload precedent | `src/sase/ace/tui/modals/projects_pane.py:496` (`action_reload_projects`) |
| Perf constraints | `memory/tui_perf.md` |
| Rust boundary | `memory/rust_core_backend_boundary.md` |
