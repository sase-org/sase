---
create_time: 2026-06-13 11:23:13
status: done
prompt: sdd/prompts/202606/tui_freeze_artifact_scan.md
---
# Plan: Fix `sase ace` TUI Freeze Caused by O(N) Artifact-Directory Re-Scans

## Summary

The `sase ace` TUI freezes because background worker threads continuously re-scan **~15,000 sibling agent-artifact
directories** in pure Python. Each tools-panel refresh walks the entire `ace-run/` parent directory, calling
`realpath` + `stat` and parsing up to two JSON files (`agent_meta.json`, `done.json`) for **every one of the 15,158
siblings**. This pure-Python CPU work holds the GIL and starves Textual's main UI/event loop, so the terminal stops
responding to input and redraws — what the user experiences as a "freeze."

This was diagnosed live against the frozen process (PID 764922), not from theory.

## Evidence (live diagnosis of PID 764922)

- Process was **alive, not deadlocked**: main thread sat in a normal asyncio `EpollSelector.select(timeout=0.083)`; the
  process burned ~27% CPU with one worker thread (`asyncio_1`) in kernel state **R (running)** and `schedstat` showing
  **6.07s of accumulated CPU across 3,973 scheduling slices** — continuous re-scheduling, the signature of a hot polling
  loop, not a single blocking call.
- `py-spy record` (6s @ 200Hz, 807 samples) attributed nearly all CPU to two disk-scanning code paths running on
  background threads:
  1. **Tools-panel path (~195 samples)**: `_fetch_tools_in_background` → `read_tool_calls_for_agent` →
     `discover_related_tool_artifact_dirs` → per-sibling `resolve()`/`realpath` (81 samples) +
     `_combined_artifact_metadata` → `_read_json_object` → `json.load`.
  2. **Agent-loader path (~170 samples)**: `_load_agents_from_disk_impl` → `load_tiered_agents` →
     `query_agent_artifact_index` + wire conversion (`_record_from_dict`).
- Disk scale on this machine:
  - `~/.sase/projects/sase/artifacts/ace-run/` holds **15,158 child directories** (15,076 with `agent_meta.json`),
    accumulated **2026-03-13 → 2026-06-13** with **no retention/cleanup**.
  - `agent_artifact_index.sqlite` is **116 MB**, alongside a **110 MB `.corrupt-20260610` backup** — i.e. the index has
    corrupted before.
  - 2,645 `tool_calls.jsonl` files totaling 181 MB.

## Root Cause

### Primary: `discover_related_tool_artifact_dirs` is O(all siblings) per call

In `src/sase/ace/tui/tools/reader.py`:

- `discover_related_tool_artifact_dirs` is meant to find only the sibling artifact dirs belonging to the same
  retry-chain / parent lineage. Instead it does `parent.iterdir()` over the whole `ace-run/` directory and, for
  **every** sibling, runs `sibling.is_dir()` (stat), `sibling.resolve(strict=False)` (realpath syscall), and
  `_artifact_dir_matches_roots`, which reads and JSON-parses `agent_meta.json` and `done.json`. At 15,158 siblings that
  is ~15K stat + ~15K realpath + up to ~30K JSON opens **per discovery call**.
- The intended cheap early-exit `if not root_ids: return [current]` is **dead code**: `_agent_root_ids` unconditionally
  adds `current.name`, so `root_ids` is never empty and the full walk always runs.
- The cost is fundamentally O(N) in the number of sibling dirs even when only a handful are actually related, because
  membership is determined by reading each sibling's metadata (a reverse lineage lookup over the filesystem).

### Why it re-runs constantly (trigger cadence)

- `_fetch_tools_in_background` keeps a parent-mtime + tool-call-mtime watermark cache, but it only _gates_ the read;
  when the watermark misses it calls `read_tool_calls_for_agent`, which **re-runs the uncached**
  `discover_related_tool_artifact_dirs` from scratch. The cheap `discover_related_tool_artifact_dirs_cached` result
  computed moments earlier in the same function is **discarded** rather than reused.
- For a **live/active agent** (one currently writing `tool_calls.jsonl`), the tool-call mtime changes on every poll, so
  the watermark misses every time → a full 15K-sibling walk on every refresh tick.
- The `ace-fs-watcher` thread plus the active `axe` daemon (`--restart-axe`) keep the `ace-run/` parent mtime and
  per-agent files changing, which also invalidates the discovery cache and schedules repeated agent-list and tools
  refreshes.

### Secondary: agent-loader index path scales with index size

The agent-list refresh queries a 116 MB SQLite index and wire-converts a large record set on each refresh. This is
index-backed (good) but still non-trivial pure-Python work that compounds GIL pressure during the same refresh storms.
The prior `.corrupt` index backup also shows that index health/repair is a real operational concern.

### Underlying scaling failure: unbounded flat artifact directory

15,158 dirs in a single flat `ace-run/` parent, growing unbounded over 3 months with no retention, is the structural
cause that turns any `iterdir()`-based code path into a performance cliff.

## Goals / Non-Goals

**Goals**

- The TUI must stay responsive (no GIL starvation) regardless of how many artifact directories have accumulated.
- Tool-call lineage discovery must be effectively O(lineage size), not O(all siblings).
- Repeated refreshes of an unchanged (or live) agent must not repeat full-directory walks.

**Non-Goals**

- Re-architecting the entire artifact storage layout in this change (retention/sharding is proposed as a follow-up, not
  a prerequisite).
- Changing the visible tools-panel behavior or UX.

## Proposed Approach (high-level design)

The fix has three layers; layers 1–2 resolve the freeze, layer 3 prevents recurrence.

### Layer 1 — Make lineage discovery O(lineage), not O(all siblings) [core fix]

Per the repo's Rust-core backend boundary (`memory/short/rust_core_backend_boundary.md`): sibling/lineage artifact
discovery is shared backend behavior — any non-TUI frontend showing an agent's tool calls would need the same result —
so the scalable implementation belongs in `sase-core` and should be reached through the existing artifact-index query,
not a Python filesystem walk.

Design:

- Use the **agent artifact index** to resolve a lineage's member directories directly (by retry-chain root / parent /
  retry-of timestamps) instead of reverse-scanning every sibling's metadata on the filesystem. The index already knows
  these relationships; the query should return the related artifact dirs for an agent.
- Add/extend a core query (e.g. "related tool-call artifact dirs for agent X") exposed via
  `sase/core/agent_scan_facade.py` and the `sase_core_rs` binding, with the Python `discover_related_tool_artifact_dirs`
  becoming a thin adapter over it.
- Keep a bounded, correct **filesystem fallback** for when the index is missing/stale — but cap the number of siblings
  scanned and short-circuit using the already-known lineage timestamps so the fallback can never devolve into a 15K-dir
  storm.

### Layer 2 — Stop repeating the walk on the hot path [Python TUI]

- In `_fetch_tools_in_background`, **reuse** the `discover_related_tool_artifact_dirs_cached` result for the actual read
  instead of letting `read_tool_calls_for_agent` re-discover uncached. Thread the discovered dirs into the reader so a
  watermark miss re-reads files but does **not** re-walk the parent.
- Ensure the discovery cache is keyed so a live agent (changing `tool_calls.jsonl` mtime) does **not** force
  re-discovery of the sibling set — only re-reads the small set of known tool-call files.
- Confirm the agent-list refresh and tools-panel refresh remain coalesced/debounced and that heavy work stays off the UI
  thread (it already runs on workers; the fix is to make that work cheap so GIL hold-time per item is small).

### Layer 3 — Bound artifact growth (follow-up, prevents recurrence)

- Add a retention / cap policy (and/or sharded subdirectory layout) for `projects/*/artifacts/ace-run/` so a single
  parent never accumulates tens of thousands of flat children. This is core/storage behavior and belongs in `sase-core`.
- Surface index health (the existing `.corrupt` backup path suggests repair tooling already exists) and ensure a
  corrupt/missing index degrades to the **bounded** fallback, never the unbounded walk.

## Affected Areas

- `src/sase/ace/tui/tools/reader.py` — `discover_related_tool_artifact_dirs`,
  `discover_related_tool_artifact_dirs_cached`, `read_tool_calls_for_agent`, `_agent_root_ids`,
  `_artifact_dir_matches_roots`, `_combined_artifact_metadata`.
- `src/sase/ace/tui/widgets/tools_panel.py` — `_fetch_tools_in_background` (reuse cached discovery; cache keying).
- `src/sase/core/agent_scan_facade.py` + `sase_core_rs` binding and `../sase-core/crates/sase_core` — new/extended
  lineage-dirs query (Layer 1) and any retention/index-health work (Layer 3).
- `src/sase/ace/tui/models/agent_loader.py` — only if the loader index query needs bounding/caching tweaks for Layer 2.

## Risks & Considerations

- **Correctness of lineage results**: the index-backed query must return the same set of related dirs the current walk
  would (retry chains, parents, retries). Needs tests with multi-attempt / retry-chain fixtures.
- **Rust-core boundary**: Layer 1 and Layer 3 cross into `sase-core`; coordinate the wire API, bindings, and tests there
  before/with the Python adapter changes (use `sase workspace open -p sase-core <N>`).
- **Index staleness/corruption**: the fallback path must be provably bounded so a bad index never reintroduces the
  freeze.
- **`just check`** must pass; add a regression test that asserts discovery cost does not scale with sibling count (e.g.
  a fixture parent with many unrelated siblings yields a bounded number of metadata reads / no full-parent walk).

## Validation Plan

1. Unit/regression test: lineage discovery over a parent containing many unrelated siblings performs a bounded amount of
   work (no per-sibling JSON read) and returns the correct lineage set.
2. Manual: reproduce against a large `ace-run/` (15K dirs), open the tools panel on a live agent, and confirm `py-spy`
   no longer shows `discover_related_tool_artifact_dirs` /`realpath` dominating and the UI stays responsive.
3. `just check` (after `just install`) green.

## Open Question for the User

How ambitious should this change be?

- **(A)** Full fix: index-backed lineage discovery in `sase-core` (Layer 1) + reuse cached discovery in the TUI (Layer
  2). Resolves the freeze durably; touches Rust core.
- **(B)** TUI-only mitigation first: reuse the cached discovery and add a bounded, short-circuited filesystem walk in
  this repo (Layer 2 + a capped Layer 1 fallback), deferring the Rust-core query and retention to follow-ups.
- **(C)** A + Layer 3 retention/sharding to prevent unbounded growth recurring.

Recommendation: **(A)** as the primary fix (it respects the core boundary and removes the O(N) cliff), with Layer 3
retention tracked as a fast follow-up.
