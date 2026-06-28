---
create_time: 2026-06-28 14:54:21
status: done
prompt: sdd/prompts/202606/update_check_startup_toast.md
---
# Plan: "Updates available" startup toast + lightweight periodic version check

## 1. Summary

Add a lightweight, cached background check that compares the installed versions of **sase**, **sase-core
(`sase-core-rs`)**, and **every installed sase plugin** against their latest available versions. When the check finds
anything out of date, show a single, beautiful toast the first time the user opens the `sase ace` TUI in a session. The
toast tells them how many components are behind and how to reach the **Updates** tab of the **SASE Admin Center** —
using a tab shortcut that is _computed_, not hardcoded, so the message can never drift if the tab is reordered.

The good news from exploration: almost all of the hard work already exists. SASE already knows how to enumerate
installed packages/plugins, fetch latest versions from PyPI / git upstream, compare with PEP 440 rules, and cache
results. This feature mostly _composes_ that machinery into a single "is anything out of date?" answer and surfaces it
at startup. We deliberately avoid duplicating any of it.

## 2. Goals & non-goals

**Goals**

- Periodically (TTL-bounded) determine whether `sase`, `sase-core-rs`, or any installed plugin is behind its latest
  version.
- On the first TUI start of a session, if anything is behind, show one tasteful toast that (a) states how many updates
  are available, (b) names a few of them, and (c) tells the user how to open the Updates tab.
- Make the toast's "how to get there" instruction **self-correcting**: it must resolve the real shortcut for the Updates
  tab from the same source of truth that drives navigation, so adding a tab sorted alphabetically before "Updates"
  cannot make the message lie.
- Be **lightweight**: the common startup path does almost no work (a small cache read); network calls happen at most
  once per TTL window and always off the UI thread.
- Be **reliable**: the check can never block first paint, never crash startup, and degrades silently when offline / when
  tooling (`gh`) is missing.
- Be **beautiful**: a polished, on-brand toast worthy of a visual snapshot test.
- Be **consistent**: the toast's count must equal what the Updates tab shows.

**Non-goals (this change)**

- No auto-updating. The toast informs; the user updates from the Updates tab as today.
- No new "latest version" plumbing — we reuse the existing PyPI/git/dev-update detection.
- No mandatory new CLI command (a `sase update --check`-style surface is a natural follow-on and is called out under
  Future Work, but is out of scope).
- No re-check-while-running timer in the MVP (called out as optional Future Work); "periodic" is satisfied by
  TTL-bounded checks across launches.

## 3. Product / UX design

### When it fires

- Once per TUI session, after first paint, as a background task. If the check resolves to "nothing out of date" the user
  sees nothing.
- Governed by a config toggle (default on) and a TTL that bounds how often we actually go to the network.

### What it says

A single toast using the existing Textual notification system (`self.notify`, which already supports `title=` and
`timeout=` — see `src/sase/ace/tui/actions/event_refresh/_auto_refresh.py`). Shape:

- **Title:** `Updates available` (with the same `↑` update glyph used elsewhere in the Updates UI).
- **Body:** the count, a short bulleted list of up to ~3 components rendered as `name  installed → latest`, an
  `…and N more` overflow line when needed, and a final call-to-action line: `Press # then 5 to open the Updates tab`
  (the `5` is computed — see §4.4).
- **Accent:** use the Updates tab's existing accent color (`#AF87FF`, from `_TAB_COLORS["updates"]`) in the
  title/shortcut via Rich markup so it visually ties to the destination tab. (Verify Textual renders markup in
  notification bodies; if not, fall back to plain text + title — the feature does not depend on markup.)
- **Severity:** `information` (this is news, not a warning/error).
- **Timeout:** long enough to read comfortably (~12s); it auto-dismisses and can be cleared with the existing "dismiss
  toasts" action.

### Why this is intuitive

- It appears exactly when it is useful (you just opened the app and something is stale) and never nags within a session.
- It points to the place that already exists to act on it, and the pointer is always correct.
- The count matches the Updates tab, so there is no "the toast said 3 but I see 2" confusion.

## 4. Technical design

### 4.1 Where the logic lives (and the Rust-core boundary)

CLAUDE.md says shared backend/domain behavior belongs in the Rust core (`sase_core`). I considered putting the "is
anything out of date?" computation there, but the evidence says keep it in Python, as a _shared, frontend-agnostic_
module:

- The Rust core is **deliberately network-agnostic** — it has no HTTP client and never shells out to pip/PyPI; it only
  parses git output. A "fetch latest from PyPI / git upstream" check cannot live there without inverting that decision.
- The entire update/version domain already lives in Python and was placed there intentionally: `sase/version/`
  (installed inventory), `sase/plugins/` (catalog + PyPI latest + PEP 440 `is_newer` + latest cache), `sase/dev_update/`
  (editable/git-upstream "behind?" detection), and `sase/uv_tool/versions.py` (core-package latest enrichment).

So the right move is to add a thin **reusable Python aggregator** that any Python frontend (the TUI today, a
CLI/`sase doctor` tomorrow) can call — not to reimplement domain logic, and not to bury this in TUI-only code. This
keeps us on the right side of the spirit of the boundary rule (no duplicated domain logic) while respecting the
established, deliberate placement of update logic in Python. _Flagging this as a design decision for review — if you'd
rather push the version-comparison/aggregation into `sase_core`, that is a larger effort and would need an HTTP story in
the core first._

### 4.2 New shared module: the update-status aggregator

Add a small package, e.g. `src/sase/updates/` with:

- A data model `UpdateStatus` describing the result:
  - `checked_at: float`
  - `components: tuple[OutdatedComponent, ...]` where each has `display_name`, `role` (`host` / `core` / `plugin`),
    `installed_version`, `latest_version`.
  - convenience: `has_updates`, `count`.
- `compute_update_status(*, offline=False, refresh=False) -> UpdateStatus` that composes the **exact same** sources the
  Updates tab uses, so the counts match:
  - **Core** (`sase`, `sase-core-rs`): `collect_installed_core_versions()` →
    `enrich_core_versions_latest(..., fetch_fn=fetch_latest_version, is_newer=...)` from `sase/uv_tool/versions.py`;
    take packages with `update_available`.
  - **Plugins**: `load_plugin_catalog()` → `enrich_with_latest()` from `sase/plugins/`; take installed entries with
    `update_available`.
  - Each source is wrapped independently so one failing (e.g. missing `gh` ⇒ no plugin catalog, or offline) degrades to
    "no data from that source" instead of raising. Notably this does **not** run the uv-tool probe (that is only needed
    to _perform_ updates, not to detect them), which keeps the check lighter than the Updates tab's own loader.

This function is pure-ish and injectable (same dependency-injection style as the surrounding modules) so it is
straightforward to unit test with stub fetchers.

### 4.3 Lightweight TTL gate + snapshot cache

To keep the common startup cheap and bound network usage, add a tiny snapshot cache under `~/.sase/updates/` (using the
existing `sase_subdir` / `ensure_sase_directory` helpers and an atomic JSON write, mirroring
`sase/plugins/latest_cache.py`). It stores the last `UpdateStatus` plus `checked_at`.

Startup decision flow (all off the UI thread):

1. Read the snapshot.
2. **Fresh** (`now - checked_at < ttl`, default 24h): use it directly — but first cheaply re-validate each listed
   component against the **live** installed version (read via `importlib.metadata`, no network) and drop any the user
   has since updated. This keeps a coarse 24h TTL accurate without a network round trip. (The underlying latest-version
   values are themselves already cached by `sase/plugins/latest_cache.py` with its own 6h TTL, so we layer cleanly.)
3. **Stale / missing**: call `compute_update_status()` (which itself reuses the catalog cache and the 6h latest cache,
   only hitting the network for genuinely stale entries), write the new snapshot, and use it.
4. If a result has updates → show the toast (see §4.5). On any failure → no toast; log at debug only. If a refresh fails
   but a prior snapshot exists, fall back to it (re-validated as in step 2) so the user is still informed; suppress only
   when there is no data at all.

### 4.4 Self-correcting Updates-tab shortcut (the "don't go out of date" guard)

The Admin Center's tab order lives in one place: `_TAB_ORDER` in `src/sase/ace/tui/modals/config_center_modal.py`, and
digit navigation is literally `_TAB_ORDER[number - 1]`. So the only correct way to say "press N for Updates" is to
derive N from that tuple.

- Add a small public helper in that module, e.g. `center_tab_shortcut(tab) -> int | None` returning
  `_TAB_ORDER.index(tab) + 1`, or `None` if the tab is absent.
- The toast builds its call-to-action from `center_tab_shortcut("updates")`:
  - present → `Press # then 5 to open the Updates tab` (with the live digit);
  - `None` (tab renamed/removed) → graceful fallback that names the destination without a digit:
    `Open the Updates tab in the SASE Admin Center (press #)`.
- Because the helper reads the same `_TAB_ORDER` that navigation uses, inserting a tab alphabetically before "Updates"
  automatically bumps the digit in the toast too — they cannot desync.
- **Regression protection (the real teeth):** a test that opens the Admin Center, presses the digit returned by
  `center_tab_shortcut("updates")`, and asserts the active tab is `updates` (reusing the existing pattern in
  `tests/ace/tui/test_config_center_tabs.py`, which already does `press("number_sign")` then `press("5")`). A second
  assertion checks the toast text contains that same digit. If anyone reorders tabs, the helper and the test move
  together; if anyone removes/renames the `updates` tab, the test forces the fallback path to be considered.

### 4.5 TUI integration

- Add a post-mount background worker (new small mixin/method, e.g. `src/sase/ace/tui/actions/update_toast.py`, launched
  from the existing post-mount background-loads path in
  `src/sase/ace/tui/actions/startup.py:_start_post_mount_background_loads`). Use
  `run_worker(..., thread=True, group="startup-loads")` since it does file IO and possibly network — never on the event
  loop, never before first paint.
- The worker reads config (toggle + TTL) via `load_merged_config()`, runs the §4.3 flow, and on a positive result
  marshals back to the UI with `call_from_thread(self._show_update_toast, status)`.
- Guards: a `self._update_toast_shown` session flag so it shows at most once; a top-level `try/except` so the check can
  never break startup; respect the config toggle.
- `_show_update_toast` formats the message (count, capped component list, computed shortcut, accent markup) and calls
  `self.notify(...)`.

### 4.6 Configuration

Add a nested section under `ace:` (this is TUI-startup behavior):

```yaml
ace:
  updates:
    startup_toast: true # show the "updates available" toast on TUI start
    check_ttl_hours: 24 # min hours between background latest-version checks
```

Two coordinated edits (the established pattern):

- Defaults in `src/sase/default_config.yml`.
- Field definitions in `config/sase.schema.json` (the `ace` object already lists `inactive_seconds`,
  `prompt_completion`, etc.) so the keys are validated and appear/editable in the schema-driven **Config** tab.
  (Top-level "unsupported key" detection only checks a fixed list, so nested `ace.updates.*` keys are not at risk there,
  but they should still be in the schema to be first-class.)

No Rust change is required: the config schema is a JSON document in this repo; the Rust inventory backend flattens
whatever schema it is handed.

## 5. Reliability & edge cases

- **Never blocks startup / first paint:** runs as a post-mount `thread=True` worker; everything wrapped so failures are
  silent (debug log only).
- **Offline / network errors:** `compute_update_status(offline=...)` and the underlying fetchers already degrade; we
  show no toast rather than a wrong one, and can fall back to a prior snapshot re-validated against live installs.
- **Missing `gh`:** plugin catalog load raises; we catch it, still report core updates, and stay consistent with the
  Updates tab (which is equally limited without `gh`).
- **Editable / dev checkouts:** these workspaces are editable installs; `sase/dev_update/detect.py` already only reports
  `update_available` when a checkout is _strictly behind_ its upstream (not for dirty/detached/ahead). The toggle lets a
  developer turn the toast off entirely.
- **Already-updated-since-check:** the re-validate-against-live-installed step in §4.3 prevents a stale snapshot from
  claiming an update the user already applied.
- **No spam:** once-per-session flag; TTL bounds network checks across launches.

## 6. Testing strategy

- **Unit — aggregator:** `compute_update_status` with stub fetchers/version records covering: all current; one core
  behind; one plugin behind; mixed; offline; catalog-unavailable (no `gh`); each source failing independently.
- **Unit — snapshot cache:** fresh vs stale vs missing; corrupt file tolerated; atomic write; re-validation drops
  components already updated locally.
- **Unit — message builder:** correct count/pluralization, list capping with `…and N more`, accent markup, and the
  shortcut text (present vs `None` fallback).
- **Unit — shortcut helper:** `center_tab_shortcut("updates")` value, and that it tracks a simulated reordering.
- **TUI integration:** drive `sase ace` with a stubbed status to assert the toast appears once when updates exist, does
  not appear when none/disabled, and never blocks startup. Plus the navigation regression test in §4.4 (press the
  computed digit ⇒ land on the Updates tab; toast text contains that digit).
- **Visual snapshot (beauty):** add a PNG snapshot of the toast under `tests/ace/tui/visual/` (harness/goldens at
  `tests/ace/tui/visual/snapshots/png/`, run via `just test-visual`; a config center visual helper already exists to
  follow), so its look is pinned and reviewable.
- Run `just check` (lint + mypy + tests) before completion, per repo rules.

## 7. Files expected to change (high level)

- **New:** `src/sase/updates/` — `UpdateStatus` model + `compute_update_status` aggregator + snapshot/TTL cache.
- **New:** `src/sase/ace/tui/actions/update_toast.py` — startup worker + toast builder/shower (wired into the existing
  post-mount loads in `actions/startup.py`; mixin registered on `AceApp` in `app.py`).
- **Edit:** `src/sase/ace/tui/modals/config_center_modal.py` — add/export `center_tab_shortcut`.
- **Edit:** `src/sase/default_config.yml` and `config/sase.schema.json` — new `ace.updates.*` settings.
- **New tests:** aggregator/cache/message/shortcut units; a TUI integration test (incl. the shortcut↔tab regression
  test); a visual snapshot test.

## 8. Open questions / decisions for review

1. **Boundary call (§4.1):** OK to keep the aggregator in a shared Python module given the core is intentionally
   network-agnostic, or do you want a core/HTTP story first?
2. **Defaults:** toast on by default and `check_ttl_hours: 24` reasonable? Should a dev/editable environment default the
   toast _off_ (since "behind upstream" is normal day-to-day), or keep it on and rely on the toggle?
3. **Scope of "periodic":** MVP does the check at startup, TTL-bounded across launches. Want an optional long-interval
   re-check timer while the TUI stays open (re-toast only on a newly-discovered update)? Currently Future Work.
4. **Reuse for a CLI:** want a `sase update --check` (or `sase doctor`) surface built on the same aggregator now, or
   leave as Future Work?

## 9. Future work

- `sase update --check` / `sase doctor` surface over the same aggregator.
- Optional in-session periodic re-check timer.
- Optional per-component snooze / "remind me later".
