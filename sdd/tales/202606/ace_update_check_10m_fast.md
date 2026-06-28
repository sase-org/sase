---
create_time: 2026-06-28 15:58:56
status: done
prompt: sdd/prompts/202606/ace_update_check_10m_fast.md
---
# ACE Update Check Cadence and Speed Plan

## Context

The startup update toast currently runs from the ACE TUI post-mount startup path:

- `src/sase/ace/tui/actions/startup.py` schedules `_schedule_startup_update_toast_check()` after first paint.
- `src/sase/ace/tui/actions/update_toast.py` runs the check in a Textual worker thread and calls
  `get_cached_update_status()`.
- `src/sase/updates/cache.py` stores the high-level update-status snapshot and defaults its TTL to 24 hours.
- `src/sase/default_config.yml` and `config/sase.schema.json` expose `ace.updates.check_ttl_hours`, also defaulted
  to 24.
- `src/sase/updates/status.py` computes status from two independent sources: SASE core packages and installed plugins.

The important performance rule from `memory/tui_perf.md` is that startup work must not block the Textual event loop. The
existing toast check is already off-thread and post-first-paint, so the plan should preserve that shape.

## Goals

1. Make the automatic update-status check eligible every 10 minutes instead of every 24 hours.
2. Keep the automatic check scoped to `sase ace` startup only. This should not create a daemon, a repeating in-session
   timer, or background checks from non-ACE commands.
3. Make the fresh-check path faster where it is practical, especially because lowering the TTL from 24 hours to 10
   minutes increases how often the fresh path runs.
4. Preserve current best-effort behavior: failures should fall back to cached status or stay silent, never breaking ACE
   startup.

## Proposed Semantics

The 10-minute cadence should mean:

- When `sase ace` starts, the post-mount worker reads the update-status snapshot.
- If the snapshot is younger than 10 minutes, revalidate it against local installed versions and show the toast if it
  still contains updates.
- If the snapshot is older than 10 minutes, recompute the snapshot in the existing worker thread, write the cache, then
  show the toast if updates are found.
- If ACE stays open for longer than 10 minutes, no automatic repeat check is scheduled. A user can still manually
  refresh the Updates tab with its existing keybinding.
- Non-ACE commands should not call `get_cached_update_status()` as part of this work.

This matches the user's "only when the `sase ace` command is run" constraint and avoids introducing new live-session
work.

## Implementation Plan

### 1. Change the default cadence to 10 minutes

- Replace the 24-hour default in `src/sase/updates/cache.py` with a 10-minute default:
  `DEFAULT_UPDATE_STATUS_TTL_SECONDS = 10 * 60`.
- Update ACE config defaults in `src/sase/default_config.yml`.
- Prefer adding a clearer `ace.updates.check_ttl_minutes` setting with default `10`.
- Keep backward compatibility for existing `ace.updates.check_ttl_hours` configs:
  - If `check_ttl_minutes` is present, use it.
  - Else if `check_ttl_hours` is present, use the old hours value.
  - Else use 10 minutes.
- Update `config/sase.schema.json` so both keys validate. Mark `check_ttl_hours` as legacy/deprecated in its description
  and expose `check_ttl_minutes` as the primary setting.
- Internally carry the parsed value as seconds to avoid unit mistakes in the TUI worker.

If the config surface should stay minimal, an acceptable fallback is to keep only `check_ttl_hours` and set the default
to `0.1666666667`; however, the minutes setting is clearer and less surprising for a 10-minute cadence.

### 2. Keep the automatic trigger ACE-only

- Leave `_schedule_startup_update_toast_check()` wired only from ACE startup.
- Do not add any repeating `set_interval`, scheduler, daemon, notification poller, or CLI hook.
- Add or update tests that prove `_run_startup_update_toast_check()` passes a 600-second TTL to
  `get_cached_update_status()` by default.
- Keep the worker `thread=True`, `exclusive=False`, and in the existing `startup-loads` group so it does not cancel
  other startup workers.

### 3. Make fresh checks faster where the current architecture allows

The expensive fresh path is `compute_update_status()`:

- Core status can hit PyPI for `sase` and `sase-core-rs`.
- Plugin status is already mostly cache-first:
  - `load_plugin_catalog(refresh=False)` uses the catalog cache when present.
  - `enrich_with_latest(refresh=False)` uses the existing per-package latest-version cache and fetches misses in
    parallel.

Recommended speed work:

- Reuse the existing latest-version cache for core PyPI lookups, or extract that cache behind a neutral helper if the
  current `sase.plugins.latest_cache` name is too plugin-specific.
- The startup status recompute should avoid network calls for core packages when a latest-version cache entry is still
  fresh.
- Keep manual refresh behavior distinct: explicit Updates-tab refreshes can continue to force fresh metadata as they do
  today.
- If measurement shows core and plugin status are still independently slow, consider computing the core and plugin
  components concurrently inside `compute_update_status()` with a small `ThreadPoolExecutor`. Only do this if it reduces
  wall time without duplicating expensive inventory scans or creating unsafe shared writes.

This gives the 10-minute snapshot cadence without turning every eligible ACE startup into guaranteed PyPI traffic.

### 4. Preserve cache and fallback behavior

- Keep `read_update_status_snapshot()` tolerant of missing or corrupt cache files.
- Keep `write_update_status_snapshot()` best-effort and atomic.
- Keep `get_cached_update_status()` returning a revalidated stale snapshot if recomputation fails.
- Continue dropping cached components that no longer look outdated locally before showing a toast.

### 5. Update tests

Add or update focused tests for:

- `DEFAULT_UPDATE_STATUS_TTL_SECONDS == 600`.
- Freshness behavior around a 600-second boundary.
- Config parsing:
  - default is 10 minutes;
  - `check_ttl_minutes` overrides the default;
  - legacy `check_ttl_hours` still works;
  - `check_ttl_minutes` takes precedence if both are set.
- Startup worker passes the expected TTL seconds to `get_cached_update_status()`.
- A cached core latest-version lookup avoids calling the PyPI fetch function on the fresh snapshot path.
- Existing fallback-on-compute-failure behavior still returns the previous snapshot.

Run the existing update-toast and update-status tests after edits:

```bash
pytest tests/test_update_status.py tests/ace/tui/test_update_toast.py
```

Then run the repo-required checks:

```bash
just install
just check
```

If `just check` stops at the known managed memory/provider shim validation, do not overwrite memory files without user
approval; run `just test` separately and report the validation blocker.

## Risks and Mitigations

- More frequent checks could increase network traffic. Mitigate by using latest-version caches for core and plugins, and
  by keeping the automatic trigger ACE-startup-only.
- Adding `check_ttl_minutes` could clutter the Config tab if the schema renders every field. Mitigate by keeping
  descriptions explicit and treating `check_ttl_hours` as legacy compatibility.
- Parallelizing core/plugin computation might duplicate inventory work. Treat concurrency as optional and measurement
  driven, not required for the cadence change.
- A stale snapshot may briefly show an update that was already installed. Existing local revalidation should continue to
  suppress that case before displaying the toast.

## Acceptance Criteria

- A default ACE startup update-status check recomputes only when the previous snapshot is at least 10 minutes old.
- The check is still scheduled only from `sase ace` startup and still runs off the Textual event loop.
- Core package latest-version checks avoid unnecessary PyPI fetches when cached latest data is fresh.
- Existing user configs with `ace.updates.check_ttl_hours` continue to work.
- Focused tests pass, and full repo verification is attempted according to project rules.
