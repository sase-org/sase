# ACE TUI Slowdown — Artifact-Index Broad-Load Diagnosis

**Date:** 2026-06-25
**Author:** automated perf investigation (driven `sase ace --tmux`)
**Status:** Research / diagnosis — recommends a concrete next step
**Related prior research:** `agents_tui_full_refresh_audit.md`, `deep_ace_tui_perf_fix.md`,
`ace_progressive_slowdown_debugging.md` (this report supersedes their open question of *why* broad
loads keep firing in a live session).

---

## TL;DR

The TUI feels slow because of **periodic ~200 ms event-loop stalls roughly every 10–20 s**, not because
steady-state j/k is slow (steady j/k is ~2–3 ms). Each stall is a **full "tier1 broad load" of the agents
list that takes 1.2–1.7 s**, and these broad loads fire **far more often than they should**.

Two independent defects stack:

1. **Frequency defect** — the inotify watcher fires when live agents write to disk, but ACE's
   artifact-path classifier (`_agent_artifact_delta_dir_for_path`) cannot map most of those paths to a
   specific artifact dir, so it returns `unknown_watcher_path` and **falls back to a full broad load**
   instead of a cheap targeted delta. In the captured session, **12 of 15 broad loads were
   `unknown_watcher_path` fallbacks; only 2 cheap delta loads ever succeeded.**

2. **Cost defect** — each broad load is expensive: **~1.0 s in the Rust
   `query_agent_artifact_index` call over a 148 MB SQLite index**, plus **~0.6 s of Python
   filesystem churn** (8,088 `posix.stat` calls, ~15k `Path` objects) to enrich ~571 records — even
   though only **31 agents** are actually displayed.

**Recommended next step:** fix the **frequency** defect first — make the watcher path classifier resolve
the enclosing artifact dir (or safely ignore irrelevant paths) so live-agent writes drive *delta* loads
instead of broad-load fallbacks. It is the highest-leverage, lowest-risk, easiest-to-verify change and
directly removes most of the user-visible stalls. The cost defect (index size + Python stat churn) is the
necessary follow-up.

---

## Methodology

- Launched the TUI with `sase ace --tmux`, which auto-injects `SASE_TUI_TRACE=1` and `SASE_TUI_PERF=1`
  (see `src/sase/main/ace_tmux.py`). Drove it via `tmux send-keys` with a paced, **read-only** key script
  (`drive.sh`): heavy `j`/`k` navigation, fold/expand (`h`/`l`/`H`/`L`), grouping cycles (`o`/`O`), tab
  switches, detail scrolling, panel focus, and help/notification modals — across all three tabs.
  Destructive keys (`x` kill, `s`/`S` status, `M` mail, `Q` stop-axe, `space`/`+` agent launch) were
  deliberately excluded because the session ran against the user's live environment (2–3 running agents).
- Collected three datasets:
  - `tui_jk.jsonl` — per-keystroke key-to-paint latency (target: p95 < 16 ms).
  - `tui_trace.jsonl` — hot-path span durations + refresh-decision trace records.
  - A standalone **cProfile** of `load_tiered_agents(full_history=False)` (the auto-refresh broad-load
    body) to attribute the 1.5 s, because pyinstrument's async mode samples only the main thread and the
    load runs on an `asyncio.to_thread` worker.
- Inspected `~/.sase/agent_artifact_index.sqlite` directly (row counts, byte distribution).

Raw artifacts and scripts: `~/.sase/perf/research_20260625_ace_tmux/`
(`drive.sh`, `analyze.py`, `profile_load.py`, `tui_jk.run.jsonl`, `tui_trace.run.jsonl`,
`analysis_summary.txt`, `profile_load_output.txt`).

---

## Evidence

### 1. Key-to-paint latency (n = 257)

| metric | value |
|---|---|
| p50 | 13.9 ms |
| p95 | **34.3 ms** (target < 16) |
| p99 | 162 ms |
| max | 818 ms (one-off: first changespec-tab load) |
| keystrokes > 16 ms | **74 / 257 (29%)** |

By tab: agents p95 36 ms / max 212 ms; axe p95 28 ms / max 33 ms. The worst agents-tab samples
(212, 199, 162, 160 ms) line up in time with the broad-load cycles below.

Note the **inverted** display-cost numbers: `agents.refresh_display` with `highlight_only` (the *cheap*
j/k path) averaged 46 ms across 6 samples, while `display_full_rebuild` averaged only 4.6 ms — because the
list is tiny (7–14 visible rows). **The rebuild itself is not the problem; the data load behind it is.**

### 2. Trace spans by total time

| span | count | sum ms | p50 | p95 | max |
|---|--:|--:|--:|--:|--:|
| `agents.load_from_disk` | 6 | **5881** | 1467 | 1745 | **1745** |
| `widget.agent_detail.update_display` | 22 | 1266 | 32 | 105 | 314 |
| `widget.prompt_panel.update_display` | 22 | 1229 | 32 | 104 | 311 |
| `agents.refresh_debounced` (the j/k immediate path) | 245 | 607 | **2.3** | 3.5 | 22 |
| `agents.live_hint_refresh` | 4 | 494 | 126 | 139 | 139 |
| `agents.worker_prep` | 4 | 402 | 82 | 197 | 197 |
| `agents.refresh_panel_highlights` | 251 | 291 | **1.0** | 1.5 | 20 |

`agents.load_from_disk` dwarfs everything. Steady-state j/k (`refresh_debounced`,
`refresh_panel_highlights`) is genuinely fast — the slowness is the recurring load plus its UI-thread
post-processing (`worker_prep`, `live_hint_refresh`).

The `update_display` (detail/prompt panel) spikes of 80–314 ms occur **only in the first ~4 s** of the
session (cold cache) and settle afterward — a first-touch cost, not a steady-state one. Lower priority.

### 3. What the 1.5 s broad load actually does (cProfile)

```
1.709 s total
  1.018 s  sase_core_rs.query_agent_artifact_index        <-- ~60%, pure Rust (over 148 MB index)
  0.605 s  _load_agents_from_all_sources (Python)
    0.390 s  load_workflow_agent_steps_from_snapshot (424 records)
    0.338 s  enrich_agent_from_meta (2038 records)
    0.129 s  posix.stat            (8088 calls)
    ~0.13 s  pathlib overhead      (~15k Path objects: _parse_path, __str__, drive, _load_parts)
  0.079 s  find_all_changespecs
```

The load returns **31 agents** but processes **571 records / 2,038 meta enrichments / 424 workflow
records** and issues **8,088 `stat` calls** — re-statting the filesystem the index already describes.

### 4. The artifact index is 148 MB

`~/.sase/agent_artifact_index.sqlite`:

| table | rows | bytes |
|---|--:|--:|
| `agent_artifacts` | 19,045 | **134.7 MB** (~7 KB/row of blobs) |
| `dismissed_agents` | 43,752 | 2.5 MB |
| indexes | — | ~10 MB |

There is also a **`agent_artifact_index.sqlite.corrupt-20260610` (110 MB)** backup — this index has a
history of corruption (cf. the `ace_macbook_sqlite_sigbus` / `revive_empty_artifact_index` plans). The
query is slow because of **bytes read/deserialized per call**, not row count: ~7 KB/row blobs in a
134 MB table.

### 5. Why broad loads fire so often — the decisive table

Refresh-decision trace records, grouped:

| count | stage | data_cost | source | fallback_reason |
|--:|---|---|---|---|
| **12** | fallback | tier1_broad_load | auto_refresh | **`unknown_watcher_path`** |
| 15 | data_loaded | tier1_broad_load | auto_refresh | — |
| **2** | scheduled | artifact_delta_load | watcher | — |
| 2 | data_loaded | artifact_delta_load | watcher | — |

The watcher **is** active (it delivered events and produced these fallbacks), but its paths classify as
`unknown_watcher_path`, so auto-refresh takes the broad path almost every time an agent touches disk.
On top of that, `FULL_SANITY_REFRESH_SECONDS = 60` forces a broad load at least once a minute regardless.

---

## Root-cause chain

```
live agent writes a file under ~/.sase/projects/.../artifacts/...
        │
        ▼
inotify watcher fires with the changed path
        │
        ▼
_agent_artifact_delta_dir_for_path() can't map it to an artifact dir
   → returns (None, affects_agents=True, …)  → "unmapped_agents_path"
        │
        ▼
_agent_artifact_delta_dirs_for_paths() → fallback_reason = "unknown_watcher_path"
        │
        ▼
auto-refresh skips the cheap delta path, runs a FULL tier1 broad load
        │
        ├── 1.0 s  Rust query over 148 MB sqlite index  (GIL released → not a full block)
        └── 0.6 s  Python stat/meta churn (GIL held) + UI-thread post-processing
                   (worker_prep ~197 ms, live_hint_refresh ~139 ms, apply ~29 ms)
        │
        ▼
event loop stalls in ~150–210 ms chunks every ~10–20 s
        │
        ▼
29% of keystrokes miss the 16 ms paint budget → "the TUI feels slow"
```

The event loop is *not* blocked for the full 1 s (worst agents-tab paint was 212 ms, not ~1000 ms), which
indicates the Rust binding releases the GIL during the query; the visible jank comes from the ~0.6 s
GIL-held Python portion plus the UI-thread post-processing.

### Where the classifier loses the path

`src/sase/ace/tui/actions/event_refresh/_artifact_delta.py`:

```python
# _agent_artifact_delta_dir_for_path(...)
if "artifacts" in path.parts:
    ...
    directory_dir = artifact_dir_from_directory_path(path)
    if directory_dir is None:
        return None, True, False        # affects agents but UNMAPPED → broad fallback
    ...
projects_root = sase_projects_dir()
if projects_root in (path, *path.parents):
    return None, True, False            # UNMAPPED → broad fallback
return None, True, False                # UNMAPPED → broad fallback
```

Any artifact-related path that doesn't match a known marker or `artifact_dir_from_directory_path` shape
becomes "affects agents but unmapped," and `_agent_artifact_delta_dirs_for_paths` escalates a *single*
unmapped path in a batch to a full `unknown_watcher_path` broad load.

---

## Proposed fixes (by leverage × risk)

### Fix A — make the watcher classifier resolve the artifact dir (frequency) ★ recommended first
Teach `_agent_artifact_delta_dir_for_path` to walk up `path.parents` to the enclosing
`artifacts/<project>/<workflow>/<timestamp>` directory for the path shapes that currently return
`(None, True, False)`, and to treat genuinely-irrelevant paths as `affects_agents=False` (skip) rather
than unmapped (broad fallback). Add the offending real-world paths as test fixtures.
**Impact:** converts most of the 12 broad-load fallbacks into 2–10 ms delta loads.
**Risk:** low — narrows an over-broad fallback; existing broad path remains the safety net.
**Verify:** re-run `drive.sh`; expect `unknown_watcher_path` → ~0 and `artifact_delta_load` to dominate.

### Fix B — shrink / bound the artifact index (cost)
Prune dismissed/archived/old `agent_artifacts` rows, stop storing large text blobs inline (store a
pointer/hash; hydrate on demand), and `VACUUM`. Today's 148 MB → target single-digit MB for the hot
working set. Also prune the 43k `dismissed_agents` rows.
**Impact:** cuts the 1.0 s Rust query substantially even when a broad load *is* required (startup, 60 s
sanity, search).
**Risk:** medium — schema/lifecycle change; coordinate with `agent_artifact_index_lifecycle`.

### Fix C — eliminate Python filesystem churn in the load (cost)
`enrich_agent_from_meta` + workflow-step building issue 8,088 `stat`s and build ~15k `Path` objects per
load. The index already carries this metadata; the post-processing should read from the index payload
rather than re-statting disk. Per `memory/rust_core_backend_boundary.md`, this loading belongs in the
Rust core — push the projection/enrichment into `sase-core` so it returns display-ready records.
**Impact:** removes most of the 0.6 s GIL-held portion (the part that actually stalls the event loop).
**Risk:** medium — crosses the Rust/Python boundary; needs wire + binding + test updates in `sase-core`.

### Fix D — relax the broad-load floor (frequency, cheap)
With Fix A landed, consider raising `FULL_SANITY_REFRESH_SECONDS` (60 → e.g. 180) and/or gating the
sanity broad load to when the user is on the agents tab. Cheap, but only meaningful after A.

### Out of scope / lower priority
Detail/prompt-panel first render (~100–314 ms) is a cold-cache, first-touch cost that settles after a few
seconds of use; defer until A–C land and re-measure.

---

## Recommendation — the single next best step

**Implement Fix A: repair the watcher artifact-path classifier so live-agent writes drive incremental
delta loads instead of `unknown_watcher_path` broad-load fallbacks.**

Rationale:
- It targets the **dominant trigger** (12 of 15 broad loads in the captured session).
- It is **low-risk** (tightens an over-conservative fallback; the broad load remains as a safety net) and
  **presentation/glue-layer** (no Rust/schema change), so it can ship without touching `sase-core`.
- It is **directly measurable**: re-run `drive.sh` and confirm `unknown_watcher_path` drops to ~0,
  `artifact_delta_load` dominates, broad loads fall to ~1/60 s (the sanity floor), and key-to-paint p95
  returns under 16 ms with the periodic stalls gone.

Sequence after A: **B** (shrink the index) and **C** (move enrichment off the Python stat path into
`sase-core`) to make the *remaining* broad loads (startup, 60 s sanity, active-search) cheap as well.

### Suggested first action
Capture a few real `unknown_watcher_path` paths (add a one-line debug log of the offending path in
`_agent_artifact_delta_dir_for_path`'s unmapped branches, or read `tui_trace.run.jsonl`), then write a
`/sase_plan` for Fix A driven by those concrete path shapes as test fixtures.

---

## Appendix — reproduction

```bash
# 1. Launch driven TUI (auto-enables trace + perf JSONL)
sase ace --tmux                      # prints sase_tmux_window / _session / _pid
# 2. Drive it (read-only nav across all tabs)
bash ~/.sase/perf/research_20260625_ace_tmux/drive.sh <window-id> 0.09
# 3. Analyze
python ~/.sase/perf/research_20260625_ace_tmux/analyze.py
# 4. Attribute the broad load directly (pyinstrument can't see the to_thread worker)
python ~/.sase/perf/research_20260625_ace_tmux/profile_load.py
```

Key files:
- `src/sase/ace/tui/actions/event_refresh/_auto_refresh.py` — broad-vs-delta dispatch
- `src/sase/ace/tui/actions/event_refresh/_artifact_delta.py` — watcher path classifier (Fix A)
- `src/sase/ace/tui/models/agent_loader.py` — `load_tiered_agents` / broad load body
- `src/sase/core/agent_scan_facade.py` — `query_agent_artifact_index` (Rust boundary, Fix B/C)
- `src/sase/ace/tui/util/{perf,trace}.py` — instrumentation
