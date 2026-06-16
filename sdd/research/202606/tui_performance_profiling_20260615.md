# ACE TUI Performance — Live Profiling Research (2026-06-15)

**Author:** agent-driven profiling session
**Method:** `sase ace --tmux --profile`, driven via `tmux send-keys`, analyzed from the
pyinstrument profile + `SASE_TUI_PERF`/`SASE_TUI_TRACE` JSONL.
**Goal:** Rank the most impactful changes to make the ACE TUI feel fast.

---

## TL;DR — the three changes that matter

1. **Stop re-reading & re-deserializing the whole agent artifact snapshot on every
   refresh.** `load_tiered_agents` cost **2.1 s on average and ran 31 times** in a 233 s
   session (**~66 s of background CPU**), even though it already uses the artifact index and
   nothing on disk changed between most loads. There is **no mtime-keyed cache** at this
   layer (violates `tui_perf.md` gotcha #7). This is the single biggest lever.
2. **Move bulk agent/artifact loading + JSON→dataclass deserialization into the Rust core
   (`sase-core`).** The hot path is 100% pure-Python `json.loads` + dataclass construction
   (`agent_artifact_from_dict`, `_read_index_unlocked`, `_optional_str`). Because it holds the
   GIL in a worker thread, it **starves the Textual event loop** — that is the root cause of
   the j/k latency, not "slow rendering."
3. **Throttle the per-second countdown repaint.** `_on_countdown_tick` repaints every running
   agent's elapsed-time every second, forcing full compositor work even while the user is idle.
   This is why ~25 s of layout/compositing accumulated over a mostly-idle session.

The j/k key-to-paint **median is 33 ms — 2× the 16 ms target** — *before* counting the
spikes (one `prev` keystroke took **1033 ms**). The cause is event-loop starvation from #1/#2
plus the idle repaint churn from #3.

---

## How the data was collected

```bash
# Launched in a detached tmux window; --tmux auto-sets SASE_TUI_TRACE=1 + SASE_TUI_PERF=1
sase ace --tmux --profile /tmp/sase/ace_profile_research_20260615.txt -t agents
```

The TUI ran against the real local store (**27–28 agents**, 4 running, groups, detail panels)
at a realistic **205×65** pane. It was then driven through the hot paths via `tmux send-keys`:
heavy `j`/`k` navigation (paced ~110 ms apart so each keystroke produces a distinct paint),
expand-all / collapse-all (`L`/`H`), tools/thinking toggles (`]`/`[`), detail scroll
(`ctrl+d`/`ctrl+u`), tab switches (`Tab`/`BTab` across PRs/Agents/AXE), manual refresh (`y`),
notifications (`i`), help (`?`), and several auto-refresh + "starting-poll" cycles. Quitting
flushed the pyinstrument profile.

**Profile summary:** `Duration 233.21 s · CPU 76.94 s · 37,046 samples`. 149 j/k samples and
**5,516 trace spans** were captured for this run.

> **Caveat (instrumentation overhead):** `--tmux` forces `SASE_TUI_TRACE=1`, so the trace
> machinery itself shows up in the numbers (`trace._write` ≈ 0.67 s self-time; the countdown
> path's `tui_trace` context manager ≈ 1.4 s). In production (tracing off) those vanish; the
> relative rankings below are unaffected.

---

## Evidence

### 1. j/k key-to-paint latency (target: p95 < 16 ms)

| tab | action | n | p50 ms | p95 ms | max ms |
|-----|--------|---|-------|-------|-------|
| agents | next | 84 | **33.3** | 54.4 | 142.4 |
| agents | prev | 35 | **32.6** | 75.9 | **1033.5** |
| axe | next | 16 | 33.2 | 40.5 | 61.7 |
| axe | prev | 12 | 31.5 | 40.2 | 115.5 |
| changespecs | prev | 1 | 500.2 | 500.2 | 500.2 |

The in-memory model mutation is trivial (`model_ms` p95 ≈ 0.16 ms). **All** the latency is
between "model updated" and "painted" — i.e. event-loop scheduling + Textual paint, inflated
when a background load is holding the GIL.

### 2. Trace spans ranked by total time over the session

| span | n | sum ms | mean ms | p95 ms | max ms |
|------|---|-------|--------|-------|-------|
| `agents.load_from_disk` | 31 | **66,276** | 2138 | 3111 | 3402 |
| `widget.agent_detail.update_display` | 47 | 7,567 | 161 | 252 | 387 |
| `widget.prompt_panel.update_display` | 47 | 6,628 | 141 | 246 | 257 |
| `agents.live_hint_refresh` | 35 | 6,208 | 177 | 374 | 730 |
| `agents.load_artifact_delta_from_disk` | 6 | 3,299 | 550 | 1304 | 1304 |
| `agents.refresh_display` | 47 | 2,465 | 52 | 223 | 392 |
| `agents.worker_prep` | 30 | 1,389 | 46 | 58 | 58 |
| `widget.tools_panel.update_display` | 50 | 983 | 20 | 39 | 129 |
| `widget.agent_list.patch_agent_row` | 1806 | 552 | 0.3 | 0.7 | 1.2 |

The selective-update primitives the codebase already invested in are healthy:
`patch_agent_row` (1806 calls) and `update_info_panel` (703 calls) are ~0.3–0.7 ms each. The
cost is concentrated in **disk-load + deserialize** and **detail-panel repaint**.

Every `load_from_disk` record carried `data_cost=tier1_broad_load`, `tier=tier1`,
`used_artifact_index=true` — so even the *indexed* "broad" path costs ~2 s. Triggers seen:
`source=startup`, `source=auto_refresh` (every 10 s), and `source=starting_poll` (fires while
any agent is in STARTING state).

### 3. pyinstrument event-loop CPU breakdown (`Handle._run` = 42.0 s of wall-on-loop)

```
42.02  Handle._run
29.11    Timer._run_timer                         <- periodic refresh timer
25.53      Screen._on_timer_update
17.50        Screen._refresh_layout
11.53          Screen._compositor_refresh  -> render_update 11.08
 5.68          Compositor.reflow -> _arrange_root 5.66   <- FULL layout re-arrange
 8.00          Screen._compositor_refresh (2nd) -> render 7.58
 3.16        AceApp._on_countdown_tick              <- per-second elapsed-time repaint
 1.59          _update_agents_info_panel  (1.41 of it = tui_trace overhead)
 1.54          _patch_agent_runtime_rows -> patch_agent_row
 9.79    run_app -> _process_messages              <- keystroke/event pump
 7.71      _dispatch_message -> on_event 4.95
 1.45      DetailPanelDebouncer._fire
 2.74    Screen._process_messages (modal/worker callbacks)
```

The most expensive single widget render is `AgentToolsPanel.render_lines` (**6.7 s**) inside
the compositor. `epoll.poll` accounts for 190.6 s of wall time — the main thread sitting idle
**or blocked on the GIL** while worker-thread loads run.

### 4. Top sase-owned CPU frames (main thread)

```
0.80  agent_artifact_from_dict   core/agent_artifact_types.py:88
0.40  _read_index_unlocked       core/agent_artifact_explicit.py:238
0.27  _optional_str              core/agent_artifact_types.py:162
0.13  list_agent_artifacts       core/agent_artifact_defaults.py:200
0.11  _discover_prompt_image_paths core/agent_artifact_defaults.py:223
```

These are JSON→dataclass deserialization of the artifact index/snapshot. They appear even on
the main thread (detail/apply paths); the *same code* dominates the invisible worker-thread
66 s. **No call into `sase_core_rs` exists anywhere in the agent-loading path** — confirmed by
grep across `actions/agents/` and `models/_loaders/`.

---

## Root-cause analysis

**`load_tiered_agents` → `_load_agents_with_load_state` → `_artifact_snapshot_for_tui_load`**
rebuilds the entire artifact snapshot from scratch on every call
(`src/sase/ace/tui/models/agent_loader.py:480`). The artifact index it reads
(`_read_index_unlocked`, `core/agent_artifact_explicit.py:238`) is a **JSONL file parsed
line-by-line** — `json.loads(line)` + `agent_artifact_from_dict(...)` for every row — under a
file lock, with **zero memoization across refreshes**. An `agent_artifact_index.sqlite` file
exists in the store, but the TUI read path goes through the line-by-line JSONL parse, not a DB
query.

Because this runs in an `asyncio.to_thread` worker, it is "off the event loop" in the
structural sense, but Python's GIL means a worker spending 2 s in `json.loads`/object
construction **still blocks the event loop** from painting the next j/k frame. That is why the
j/k median sits at 33 ms and spikes to 1033 ms: the work was moved to a thread, but not out of
the GIL. The recent commit `94af72277` (defer live-diff hints out of the startup loader)
helped startup but `live_hint_refresh` still spikes to 730 ms in steady state.

Separately, `_on_countdown_tick` re-patches every running agent's "🏃 4m26s" elapsed time
**every second** and walks the compositor, so even an idle TUI keeps doing layout+composite
work (the 25 s of timer-driven compositing). A `Compositor.reflow`/`_arrange_root` full layout
pass (5.7 s) running on refresh suggests the refresh path is re-arranging layout that did not
structurally change.

---

## Recommendations (ranked by impact)

### Tier 1 — do these first

**R1. mtime/version-keyed cache for the agent artifact snapshot.**
Memoize the deserialized snapshot returned by `_artifact_snapshot_for_tui_load` keyed by the
artifact index file's `(mtime, size)` and per-artifact-dir mtimes. When unchanged, return the
cached objects instantly and re-deserialize only changed rows. Expected effect: collapses the
2.1 s mean broad load to near-zero on the common "nothing changed" refresh, removing the bulk
of the 66 s background CPU and the GIL stalls behind it. *Directly closes `tui_perf.md`
gotcha #7.*

**R2. Move artifact-index read + deserialization into `sase-core` (Rust).**
This is textbook core-backend logic by the `rust_core_backend_boundary.md` litmus test (every
frontend needs it to match the TUI). A Rust loader that parses the index and returns a wire
struct **releases the GIL during the heavy work**, so even a full reload no longer freezes
navigation. Pair with R1 (Rust owns the cache and returns deltas). Bonus: replace the
line-by-line JSONL re-parse with the existing SQLite index or a Rust-owned store. This is the
structural fix for the j/k latency.

### Tier 2 — high value, smaller blast radius

**R3. Throttle / gate the per-second countdown repaint.** `_on_countdown_tick` (3.16 s, plus
the compositor work it triggers) should: (a) only `patch_agent_row` for rows whose *rendered*
elapsed-time string actually changed; (b) skip entirely when the user is mid-navigation
(`NavigationGate`) or the window is unfocused. Removes most of the idle compositing churn.

**R4. Eliminate the full `Compositor.reflow`/`_arrange_root` on refresh.** Investigate why a
structure-unchanged refresh triggers a full layout re-arrange (5.7 s). If row contents change
but the tree shape doesn't, the refresh should be a content repaint, not a relayout. Cache
`AgentToolsPanel` rendered strips (6.7 s, the single most expensive widget) when its content
hash is unchanged.

### Tier 3 — targeted polish

**R5. Trim the detail-panel paint** (`agent_detail.update_display` 161 ms +
`prompt_panel.update_display` 141 ms per navigation settle). These do Rich syntax highlighting
(`_CachedSyntaxRenderable`, `lazy_syntax`). Verify the highlight cache is keyed by
(file, content-hash) and that `DetailPanelDebouncer` truly collapses a held j/k to one final
paint.

**R6. Use the delta path for `starting_poll`.** Polling a STARTING agent currently fires full
`tier1_broad_load`s. Replace with `load_artifact_delta_from_disk` (or a status-only stat) so a
single starting agent doesn't trigger repeated 2 s broad reloads. Note the delta path itself
still costs 550 ms mean / 1.3 s max — it benefits from R1/R2 too.

---

## Suggested validation

After R1/R2, re-run this exact harness and compare:

- `agents.load_from_disk` mean should drop from ~2100 ms to <100 ms on unchanged-disk loads.
- j/k `paint_ms` p50 should fall from 33 ms toward the <16 ms target; the 1033 ms spike should
  disappear.
- `SASE_TUI_PERF=1` bench: `pytest -s -m slow tests/ace/tui/bench_tui_jk.py`.

Profiling artifacts for this run (ephemeral `$SASE_TMPDIR`):
`ace_profile_research_20260615.txt`, plus `run_jk.jsonl` / `run_tr.jsonl` deltas extracted
from `~/.sase/perf/tui_{jk,trace}.jsonl`.
