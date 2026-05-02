---
create_time: 2026-04-27 10:15:56
status: done
prompt: sdd/prompts/202604/ace_config_cache.md
---
# Cache merged-config / mentor-profile loads to speed up `sase ace` TUI tab switching

## Problem

Switching tabs in the `sase ace` TUI is several seconds slow on the user's other machine. The profile at
`.sase/home/tmp/sase/ace_profile_20260427_100850.txt` (52s wall, 68s CPU) shows the dominant cost on every tab switch
and on every changespec refresh:

```
AceApp.action_next_tab            2.10s
└─ AceApp.watch_current_tab       2.10s
   └─ AceApp._refresh_display     1.56s
      └─ ChangeSpecDetail.update_display
         └─ _build_display_content
            └─ build_mentors_section
               └─ format_profile_with_count   1.54s
                  └─ get_mentor_profile_by_name
                     └─ get_all_mentor_profiles
                        └─ _load_mentor_profiles  1.54s
                           └─ load_merged_config  1.40s   ← YAML-parses every layer
```

The same chain dominates `_apply_reloaded_changespecs` (5.4s on the slow refresh sample) and `action_prev_tab` (1.6s).
Across the 52s session, `load_merged_config()` and the mentor-profile parsing it feeds into account for the bulk of CPU
time.

### Why it's so slow

1. `load_merged_config()` (`src/sase/config/core.py`) re-reads and YAML-parses **every** config layer on every call:
   bundled `default_config.yml`, every plugin `default_config.yml`, `~/.config/sase/sase.yml`, every
   `~/.config/sase/sase_*.yml` overlay, and (when enabled) the local `./sase.yml`.
2. `_load_mentor_profiles()` (`src/sase/config/mentor.py`) calls `load_merged_config()` and then walks/validates every
   profile entry into `MentorProfileConfig` dataclasses — also non-trivial work.
3. `format_profile_with_count()` in `src/sase/ace/display_helpers.py` calls `get_mentor_profile_by_name()` (which calls
   `get_all_mentor_profiles()` → `_load_mentor_profiles()` → `load_merged_config()`) **once per visible profile token
   per mentor entry per render**. So a single render multiplies the YAML-parse cost N times.

### Why it's safe to cache

- `sase ace` calls `set_include_local_config(False)` once at startup (`src/sase/main/ace_handler.py:19`), so the local
  CWD `sase.yml` layer is permanently off for the TUI session.
- The remaining inputs (bundled default, plugin defaults, user `sase.yml`, overlays) almost never change during a
  session. When they do, `mtime` changes, so an mtime-keyed cache invalidates correctly.
- All other consumers of `load_merged_config()` are short-lived child processes (`workflows/commit/precommit_hooks.py`,
  `llm_provider/*`, `axe/config.py`, `xprompt/processor.py`, `telemetry/_config.py`, `main/config_handler.py`,
  `sdd/beads.py`). A process-wide cache fills once and the process exits — transparent and correct.
- A grep confirms no caller mutates the returned dict in place; every call site reads via `.get()`/key access.

## Goal

Make tab switching feel instant by eliminating the multi-second YAML re-parse cost, without changing user-facing
behavior or breaking other consumers of `load_merged_config()`. **Target: tab switch under ~50ms in the profile output
(down from ~2s).**

## Approach

Two layered, mtime-keyed caches plus a couple of small follow-ups.

### 1) Memoize `load_merged_config()` with mtime-based invalidation

**File**: `src/sase/config/core.py`

- Build a cheap cache key on each call:
  - `_include_local_config` (toggle controls one layer)
  - cwd (only when `_include_local_config=True`, since that affects `_get_local_config_path()`)
  - For each candidate file layer that exists, a tuple of `(path, st_mtime_ns, st_size)`. Stat is cheap (~µs) compared
    to a YAML parse. Use `(mtime_ns, size)` together to defeat coarse-grained filesystem timestamps.
  - The bundled `default_config.yml` and plugin `default_config.yml`s ship inside packages and never change at runtime —
    these load once at process start and need no mtime check.
- On cache hit, return the cached dict immediately.
- On miss, do the real load + deep-merge once, store the result, return it.
- Add a small `clear_config_cache()` helper for tests and any future explicit-refresh path.
- `set_include_local_config()` flipping is part of the cache key, so it invalidates naturally — no manual cache-clearing
  needed.
- The merged dict is small enough that returning the cached object directly is fine; no caller mutates it. (If a future
  caller does, switch to `copy.deepcopy` per call — still orders of magnitude faster than a re-parse.)

### 2) Memoize `_load_mentor_profiles()` with the same key

**File**: `src/sase/config/mentor.py`

- Cache the parsed `list[MentorProfileConfig]` keyed on the same mtime tuple `load_merged_config()` uses (export a
  `_current_config_token()` helper from `core.py`, or recompute the same key — pick whichever keeps the layering clean).
- This eliminates the ~0.5s of profile parsing/validation that remains after `load_merged_config()` is cached.
- Also stat-cache `_get_local_profile_names()`, which independently opens the CWD `sase.yml` even when
  `_include_local_config=False`. Same key shape: `(path, mtime_ns, size)`.

### 3) Small cleanups (free, since we're touching these files)

**File**: `src/sase/ace/display_helpers.py`

- Pull the per-call inner import `from sase.config.mentor import get_mentor_profile_by_name` up to the top of the
  module. Same for the inner import in `src/sase/ace/tui/widgets/mentors_builder.py`.

**File**: `src/sase/ace/tui/widgets/mentors_builder.py`

- Optional: in `build_mentors_section`, look up each profile's total once per render and reuse it across calls to
  `format_profile_with_count`. With caching in place this isn't load-bearing for performance, but it's a small
  readability and cost win.

## Verification

1. Re-run `sase ace --profile`; confirm `load_merged_config` and `_load_mentor_profiles` no longer dominate the
   tab-switch path. Tab switch should drop from ~2s to under ~50ms in the new profile.
2. `just check` (lint + mypy + tests).
3. Add unit tests near `tests/test_config.py` and `tests/test_mentor_config_loading.py` covering:
   - Cache hit returns the same data when nothing changed.
   - Cache invalidates when a layer file's mtime/size changes.
   - Cache invalidates when `set_include_local_config()` toggles.
   - Bundled and plugin layers are loaded once.
   - `clear_config_cache()` forces a reload.

## Risks / things to watch

- **Mutation of cached dict**: confirmed none today via grep, but worth documenting in a comment near the cache. Switch
  to `deepcopy` if a future caller mutates.
- **Coarse mtime resolution**: mitigated by combining `mtime_ns` with `st_size`.
- **Toggle ordering in `ace_handler`**: `set_include_local_config(False)` runs before any TUI work, so the first cache
  fill already reflects the toggle — verify with a quick trace.
- **`os.chdir()` inside a long-lived process**: cwd is part of the key when local config is enabled, so the cache
  invalidates correctly.

## Out of scope (call out, do not do here)

- Rewriting `_refresh_display` to be incremental / per-section. Once the config caches land, the dominant cost goes away
  — further optimization can wait for a follow-up profile.
- Async/background refresh strategy changes.

## Files touched (expected)

- `src/sase/config/core.py` — add cache + `clear_config_cache()`.
- `src/sase/config/mentor.py` — cache `_load_mentor_profiles()` and `_get_local_profile_names()`.
- `src/sase/ace/display_helpers.py` — hoist import.
- `src/sase/ace/tui/widgets/mentors_builder.py` — hoist import; optional per-render profile-total lookup table.
- `tests/test_config.py` (or new `tests/test_config_cache.py`) — new caching tests.
