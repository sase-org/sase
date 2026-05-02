---
create_time: 2026-03-30 19:32:21
status: done
---

# Make `sase ace` Agents Tab Much Faster (Pure Optimization)

## Problem Statement

The Agents tab is slow because every auto-refresh performs a full agent reload and full list rebuild, and the load path
does substantial repeated filesystem and config work. We need major speed improvements without changing behavior or
outputs.

## Key Findings

- `load_all_agents()` is the dominant cost on refresh.
- The heaviest hotspots are:
  - `load_workflow_agent_steps()` (large artifact scans and JSON reads)
  - `enrich_agent_from_meta()` called for many agents
  - Repeated `get_timezone()` calls during timestamp parsing from metadata (this reloads config repeatedly and is
    disproportionately expensive).
- Agent list rendering does redundant work per row (build display text for option and then rebuild similar text again
  for width measurement).
- Display refresh paths perform repeated linear index lookups for panel-local indices.

## Optimization Goals

- Preserve exact behavior and visual output.
- Reduce per-refresh CPU and I/O overhead.
- Keep changes local and low risk (refactoring + caching only).

## Proposed Changes

1. Add a fast, process-local cache for timezone lookup used in agent metadata parsing.

- Introduce a cached helper in `_artifact_loaders.py` (e.g., `@lru_cache(maxsize=1)` around timezone retrieval) and
  route `_parse_utc_to_eastern()` through it.
- This removes repeated config/YAML loads while preserving timestamp semantics.

2. Remove duplicate formatting work in `AgentList.update_list()`.

- Build each option once via `_format_agent_option(...)`.
- Derive width from the built option prompt (`Text.cell_len`) instead of re-constructing equivalent text in
  `_calculate_entry_display_width()`.
- Keep width padding and all displayed text unchanged.

3. Eliminate avoidable O(n^2) index lookups in agents display refresh.

- In `_refresh_agents_display(...)`, precompute global->local index maps for main and pinned panels and use O(1)
  lookups.
- In non-list-changed highlight updates, use the same maps instead of repeated `.index(...)` scans.

4. Small no-behavior micro-optimizations in hot loops.

- Avoid repeated set/list recomputation where equivalent precomputed values can be reused in `_load_agents()` and list
  update paths.
- Keep all branching logic and status behavior identical.

## Validation Plan

- Run targeted tests for agent loading/rendering behavior:
  - `tests/test_agent_loader_dedup_vcs_pid.py`
  - `tests/test_ace_tui_widgets.py`
  - `tests/test_agent_model.py`
  - `tests/test_pinned_agents.py`
- Run full required repo check:
  - `just install` (if needed for workspace parity)
  - `just check`
- Sanity profile before/after `load_all_agents()` to confirm meaningful speedup in hot path.

## Risk Management

- Caching scope remains process-local and read-only (no persistent cache).
- No schema, keymap, command, or functional-flow changes.
- If any display-related tests regress, prefer keeping behavior and reducing optimization scope to only proven-safe
  changes.
