---
create_time: 2026-06-29 06:53:51
status: done
prompt: sdd/prompts/202606/update_availability_ux.md
---
# Plan: Reliable, Beautiful "Updates Available" UX (dev + published)

## Goal

Make the "SASE has an update" experience correct, persistent, and delightful for **every** install kind:

1. **Works for dev/editable installs as well as published releases.** Today the periodic check _detects_ a dev update on
   a fresh recompute, but the cached-snapshot revalidation that runs on every startup is install-type-blind and silently
   mis-handles editable checkouts — so dev users get flaky or absent notifications.
2. **The startup toast reappears on every launch until the user actually updates** — while still doing the expensive
   network/git-fetch work only every 10 minutes.
3. **A persistent top-right indicator** appears the moment an update is known and stays until the user updates —
   intuitive, reliable, and visually consistent with the existing top-bar badges and the Admin Center "Updates" tab.

## Current state (verified)

- **Detection** — `sase.updates.status.compute_update_status()` aggregates two independent, gracefully-degrading
  sources: SASE core (`sase`, `sase-core-rs`) and installed plugins. Core detection already routes **editable** packages
  through git: `sase.uv_tool.versions.enrich_core_versions_latest()` calls `sase.dev_update.detect.detect_dev_latest()`
  (git upstream `ahead/behind`) for editable records and PyPI version comparison for wheels. So _fresh detection_ is
  already install-type-aware.
- **Cadence/cache** — `sase.updates.cache.get_cached_update_status(ttl_seconds=600)` reads a JSON snapshot
  (`~/.sase/updates/status_snapshot.json`, `DEFAULT_UPDATE_STATUS_TTL_SECONDS = 10*60`). If the snapshot is fresh it is
  **revalidated** and returned; if stale it recomputes (the only "slow work"), writes the snapshot, and returns the
  revalidated result. The trigger is `sase ace` startup only (no daemon/in-session timer), off the event loop.
- **Toast** — `sase.ace.tui.actions.update_toast.UpdateToastMixin` runs the check in a startup worker thread and shows a
  12s `notify(...)` once per process (`_update_toast_shown`) when `status.has_updates`. Config:
  `ace.updates.startup_toast` and `ace.updates.check_ttl_minutes`.
- **Updates tab** — the Admin Center (opened with `#`) registers an **"Updates"** tab (accent `#AF87FF`, digit `5`)
  hosting `PluginsBrowserPane`. It **applies updates in-session** (`u` plugin, `U` all plugins, `S` sase core), then
  refreshes installed/latest versions and, when packages actually changed, restarts the TUI. A `sase update` CLI exists
  and handles both editable (git fast-forward via `execute_dev_update`) and uv-tool (`uv tool upgrade sase`) installs.
- **Top-bar indicators** — `app.py` composes a right-aligned cluster in `#top-bar` (task ⚙, llm-override, inactive IDLE,
  stashed ❄, notification ✉). Each is a `Static` that renders Rich `Text` (e.g. `bold #1a1a1a on <accent>`) and hides
  itself (`Text("")`) when there is nothing to show. Updates are pushed imperatively via `query_one(...).set_*()`.

## Root-cause analysis: why dev installs are unreliable

The decisive gap is **`revalidate_update_status()` in `sase.updates.cache`**, which runs on _every_ startup — both on a
cache hit (within the 10-minute window) and immediately after a fresh recompute. It decides "is this component still
outdated?" with:

```
live = importlib_metadata.version(component.distribution_name)
keep = is_newer(component.latest_version, live)
```

This is correct for **wheels** (after `uv tool upgrade`, `importlib` reports the new version and the row is dropped). It
is **wrong for editable installs**: a git checkout's installed version string is static (read from `pyproject.toml`) and
does **not** move when the checkout falls behind or catches up to its upstream. The cached `latest_version` for an
editable row is a git-derived display version, so `is_newer(git_display_version, static_pyproject_version)` is
semantically meaningless. The practical consequences:

- A genuine dev update can be **dropped on the very next cache hit** → the toast/indicator flicker or never appear.
- After the user runs `git pull` / `sase update`, the row may **never clear** (the version string never changed) → a
  "ghost" update that won't go away.

Two supporting gaps:

- The **snapshot does not persist** the fields needed to revalidate an editable row offline (`install_type`, git root,
  upstream ref), so a cache hit _cannot_ re-check git ancestry even if it wanted to.
- There is **no persistent indicator** — only the transient toast.

The fix for dev reliability **and** "show every startup until updated" is the same: revalidate each row using the
_correct, cheap, local_ signal for its install kind — and that local recheck is what makes the toast/indicator persist
across launches without redoing the slow work.

## Design

### Part 1 — Make detection correct & persistent for both install kinds (`sase.updates`)

1. **Carry install context on the component.** Extend `OutdatedComponent` with optional `install_type: str | None`,
   `source_root: str | None` (git root), `upstream_ref: str | None`. Populate them in `_core_component()` from
   `CorePackageVersion` (already has `install_type`, `git_root`, `upstream_ref`) and in `_plugin_component()` from the
   catalog entry's `latest` (editable plugins expose `git_root`/`upstream_ref`; wheels leave them `None`). Wheels keep
   `install_type` for clarity and `source_root=None`.

2. **Version the snapshot.** Bump `SCHEMA_VERSION` `1 → 2` and (de)serialize the new fields. Old v1 snapshots fail the
   `schema_version` check in `read_update_status_snapshot()` and are treated as a miss → a safe one-time recompute on
   first launch after upgrade. New fields are optional/tolerant on read.

3. **Make revalidation install-type-aware.** Split `_component_still_outdated()`:
   - **Editable + `source_root` present** → re-derive "still outdated" from **local git ancestry only**:
     `classify_git_upstream(Path(source_root))` (no `git fetch`; purely local `rev-list --left-right --count`, ~1s
     timeout) and keep the row **iff `strictly_behind`** — mirroring exactly what `detect_dev_latest` treats as
     `update_available`. Up-to-date / ahead / diverged / dirty → drop. On any git error/timeout → **keep**
     (conservative: never hide a real update because a probe momentarily failed).
   - **Wheel / unknown** → keep the existing `importlib_metadata.version` + `is_newer` path.
   - Factor a single shared predicate so detection (`detect_dev_latest`) and revalidation agree on "behind ==
     strictly_behind" and can't drift.

**Why this satisfies "slow work only every 10 minutes":** the expensive operations — PyPI lookups and `git fetch` — live
in `compute_update_status` / `detect_dev_latest` and remain gated behind the snapshot TTL. Revalidation only does
**cheap, local** work (an `importlib` lookup for wheels, a local `rev-list` ancestry check for editable) and is what
runs on every startup. This is the crux that lets the toast/indicator persist on every launch _and_ clear precisely when
the user updates — for both install kinds.

### Part 2 — Toast on every startup until the user updates

No new "seen/dismissed" persistence is needed (and it would be the wrong model — the requirement is "until they update,"
not "once"). The source of truth is simply "is there still an update?", now answered correctly by the revalidated
snapshot from Part 1.

- Keep the per-process `_update_toast_shown` guard (don't spam within a single session).
- Because each `sase ace` launch is a fresh process, a still-outdated revalidated snapshot ⇒ the toast shows on every
  startup; once the user updates, revalidation drops the row ⇒ no toast. This already holds for published installs and
  becomes true for editable installs via Part 1.
- Confirm (with tests) the worker still passes the configured TTL and stays off the event loop in the `startup-loads`
  group. No cadence change.

### Part 3 — Persistent, beautiful top-right "Updates" indicator

1. **New widget** `UpdatesAvailableIndicator(Static)` (`src/sase/ace/tui/widgets/updates_indicator.py`), mirroring the
   existing indicator pattern:
   - `set_available(count: int)` renders `↑ {count}` as `bold #1a1a1a on #AF87FF`, and `Text("")` (hidden) when
     `count == 0`. This reuses the **Updates-tab accent `#AF87FF`** and the **`↑` glyph** already used by the toast
     title and the incoming-commits headers, giving toast + tab + indicator a single, recognizable identity.
   - Dynamic tooltip: e.g. `"2 updates available — open the Updates tab (click, or press # then 5)"`.
   - `on_click` opens the Admin Center on the Updates tab.
2. **Compose & style.** Yield it in `app.py`'s `#top-bar` at the **far right** (after the notification badge) — the
   corner the user pointed at, fitting for the highest-signal, most persistent badge; it rarely toggles so it adds no
   meaningful layout churn. Add `#updates-indicator { width:auto; content-align:right middle; }` to `styles.tcss` and
   export from `widgets/__init__.py`. (Placement is trivially reorderable if a different spot is preferred.)
3. **Open-the-tab action.** Add `action_open_updates_panel()` in `actions/base.py`
   (`push_screen(ConfigCenterModal(initial_tab="updates"))`), matching the existing projects/logs/tasks fast paths, and
   wire the indicator's click to it. Optionally add a leader keybinding; if added, update the `?` help per the ace
   help-maintenance rule.
4. **Drive the indicator.** Add a single `_refresh_updates_indicator(status)` helper (in `UpdateToastMixin` or a small
   sibling mixin) that sets the badge count from a status. Call it:
   - From the startup worker, right after `get_cached_update_status(...)`, via `call_from_thread` — alongside the toast.
     The indicator shows whenever `has_updates`, **independent of the `startup_toast` toggle**, gated only by a new
     `ace.updates.indicator` config (default `true`).
   - On Admin Center dismiss (and thus after any in-session update that did _not_ trigger a TUI restart): schedule a
     cheap **offline, cache-based revalidation** in a worker and update the badge, so applying an update clears the icon
     immediately. Package-changing updates already restart the TUI, which re-derives the icon from the snapshot on the
     next startup; this dismiss-refresh covers the no-restart cases and keeps it feeling live.
5. **Config.** Add `ace.updates.indicator: true` to `src/sase/default_config.yml` and `config/sase.schema.json`,
   resolved in the same style as the existing `ace.updates` knobs.

### Rust-core boundary (decision for review)

Per the `rust_core_backend_boundary` rule, shared backend behavior belongs in `sase-core`. I propose keeping detection
and revalidation in **Python `sase.updates`** and the indicator in **Python/Textual**, following the explicit precedent
set by the incoming-commits work (`sdd/tales/202606/updates_tab_incoming_commits.md`): the entire updates / dev-update /
uv-tool / `gh` domain already lives in Python and Rust core has no update-checking surface to extend. This is the one
architectural call to confirm at review; if a core seam is desired later, `sase.updates` is the clean place to move.

## Files (anticipated)

- **Edit** `src/sase/updates/status.py` — extend `OutdatedComponent`; populate new fields in `_core_component()` /
  `_plugin_component()`; shared "strictly-behind" predicate.
- **Edit** `src/sase/updates/cache.py` — bump `SCHEMA_VERSION` → 2; (de)serialize new fields; install-type-aware
  `revalidate_update_status` / `_component_still_outdated` (editable → local `classify_git_upstream` ancestry).
- **New** `src/sase/ace/tui/widgets/updates_indicator.py`; export from `src/sase/ace/tui/widgets/__init__.py`.
- **Edit** `src/sase/ace/tui/app.py` — compose the indicator into `#top-bar`.
- **Edit** `src/sase/ace/tui/styles.tcss` — `#updates-indicator` rule.
- **Edit** `src/sase/ace/tui/actions/update_toast.py` (and possibly a small `_updates_indicator.py` mixin) —
  `_refresh_updates_indicator`; set the badge from the startup status.
- **Edit** `src/sase/ace/tui/actions/base.py` (+ `bindings.py` if a keybinding is added) —
  `action_open_updates_panel()`, click wiring, dismiss-time indicator refresh.
- **Edit** `src/sase/default_config.yml` + `config/sase.schema.json` — `ace.updates.indicator`.
- **Edit** the ace `?` help content if a keybinding is added.

## Testing

- **Unit (`sase.updates`)** with injected git classifier / version fns (no real git, no network):
  - `revalidate_update_status`: editable row **kept** while local ancestry is strictly-behind; **dropped** when
    up-to-date / ahead / diverged / dirty; **kept** on git error/timeout; wheel rows still use the `importlib` path and
    drop after a version bump.
  - Snapshot v2 round-trips the new fields; a v1 snapshot is treated as a miss (forces recompute).
  - Component builders carry `install_type`/`source_root`/`upstream_ref` from both core and plugin sources.
- **Toast** (`tests/ace/tui/test_update_toast.py`): worker passes the configured TTL; toast shows on each fresh-process
  startup while the (revalidated) status still has updates; suppressed once updated; respects `startup_toast`.
- **Indicator widget**: render states (0 hidden, 1 singular, N plural), tooltip text, `on_click` opens the Updates tab;
  set from the startup status; cleared by the offline refresh after Admin Center dismiss; honors
  `ace.updates.indicator`.
- **Visual PNG snapshots**: add/refresh goldens for the top-right badge present/absent via
  `just test-visual --sase-update-visual-snapshots` (intentional visual change).
- Run `just install` then `just check` (and `just test-visual`) before completion. If `just check` stops at the known
  managed memory / llm-provider validation blocker, do not overwrite memory files; run `just test` separately and report
  the blocker (per repo memory notes).

## Risks & mitigations

- **Revalidation now shells `git` for editable rows on every startup.** Keep it in the off-thread startup worker, with
  the existing ~1s git timeouts, only for editable components, never on the event loop (TUI-perf rule 1). No `git fetch`
  in revalidation — local ancestry only.
- **Stale snapshot could momentarily show an already-installed update.** Local revalidation (git ancestry for editable,
  `importlib` for wheels) suppresses it before paint for both kinds.
- **Two violet badges** (updates `↑` vs stashed-prompts `❄`). Distinct glyphs; stashed-prompts is transient; identity
  consistency with the Updates tab outweighs the rare co-occurrence. Alternative (a distinct hue for updates) noted if
  preferred.
- **Indicator placement/jitter.** The right-anchored `1fr` tab-bar reflows the whole indicator cluster whenever any
  badge toggles; the updates badge is rare and persistent, so added churn is negligible; position is easy to change.

## Out of scope / future

- Any repeating in-session timer or daemon — the automatic check stays `sase ace`-startup-only (prior decision).
- Surfacing incoming commits inside the toast/indicator (the data layer exists; future enhancement).
- Moving the updates domain into Rust core (kept in Python per established precedent; revisit if a core seam is wanted).
