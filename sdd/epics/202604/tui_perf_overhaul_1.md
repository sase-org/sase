---
create_time: 2026-04-27 12:15:44
status: done
bead_id: sase-w
prompt: sdd/prompts/202604/tui_perf_overhaul_1.md
---
# Plan: TUI (`sase ace`) Performance Overhaul

## Goal

Significantly improve the perceived and measured performance of the `sase ace` TUI — j/k navigation latency,
startup/reload time, agent list responsiveness on large data sets, and idle CPU during auto-refresh.

This plan operationalizes `sdd/research/202604/sase_perf_research.md`. The research is the source of truth for _what_ to do; this
plan decides _how_ to slice the work into agent-sized phases and clarifies repo-specific paths (the research references
upstream paths; this repo has reorganized `actions/changespec_display.py` → `actions/changespec/_display.py` and
`actions/agents_display.py` → `actions/agents/_display.py`).

## Why phased

Each phase will be picked up by a _fresh_ agent (a different `claude` / `gemini` / `codex` invocation) with no carryover
context. Phases must therefore be:

- **Self-contained** — clear inputs, outputs, files touched, acceptance tests.
- **Independently shippable** — landable as its own commit / merge unit; later phases must continue to function if an
  earlier one was already partially done by a previous agent.
- **Bounded in scope** — sized so a single agent can finish + verify with `just check` and targeted pytest within one
  session.
- **Ordered by dependency** — earlier phases set up the measurement / primitives later phases rely on.

Phases 2–7 each begin with the same setup ritual: read `sdd/research/202604/sase_perf_research.md` (the corresponding P-section),
verify the P0 trace spans from Phase 1 fire on the targeted code path, write the phase, then re-run trace + targeted
benchmarks to confirm regression-free wins.

## Existing infrastructure (already in repo — do not rebuild)

A pre-flight survey confirmed the following are already in place and should be _extended_ rather than reinvented:

- `JKPerfTimer` in `src/sase/ace/tui/util/perf.py` — key-to-paint timing, rolling 200-sample window, JSONL at
  `~/.sase/perf/tui_jk.jsonl`, gated by `SASE_TUI_PERF=1`.
- `DetailPanelDebouncer` in `src/sase/ace/tui/util/debounce.py` — 150ms default; per-tab instances
  (`_changespec_detail_debouncer`, `_agent_detail_debouncer`).
- `AgentRenderCache` in `agent_list.py` + `_agent_list_rendering.py` — LRU caches for agent rows (512) and banner rows
  (128) with selective invalidation via `invalidate_agent(identity)`.
- `_MTimeJsonCache` in `actions/agents/_json_cache.py` — 4096-entry LRU keyed by `(path, mtime_ns, size)` for
  done/workflow/etc JSON.
- `fs_watcher.py` — Linux inotify (ctypes-based), 50ms event coalescing, polling fallback elsewhere.

The big remaining gaps (and what the phases below tackle) are: scoped tracing _beyond_ j/k key-to-paint, separation of
"selection changed" from "list shape changed" refreshes, parsed-ChangeSpec / query-evaluation caches, O(1) agent
list/panel lookups, incremental agent-loader refresh, lazy heavy-Rich rendering, and event-driven (rather than periodic)
auto-refresh.

---

## Phase 1 — Trace + Benchmark Foundation

**Why first.** Without scoped phase timers and synthetic-data benchmarks, all later phases will be impossible to
validate or to defend against regression. This is the only phase whose visible output is _infrastructure_, not
user-perceived speed.

**Deliverables.**

1. `SASE_TUI_TRACE=1` scoped span recorder in `src/sase/ace/tui/util/perf.py` (or a new sibling
   `src/sase/ace/tui/util/trace.py`). Provides a `tui_trace(name, **counters)` context manager that emits one JSONL line
   per span to `~/.sase/perf/tui_trace.jsonl` with `timestamp`, `span_name`, `duration_ms`, `current_tab`, counters
   dict.
2. Spans wrapped around the hot-path functions enumerated in research §1 (refresh display / update list / update display
   / update relationships / filter / evaluate_query / agent loading / agent list update / panel updates / AXE
   rendering). The exact functions live in `actions/changespec/_display.py`, `actions/agents/_display.py`,
   `actions/agents/_loading*.py`, `widgets/changespec_list.py`, `widgets/agent_list.py`,
   `widgets/ancestors_children_panel.py`, the prompt / file / thinking panels, and `widgets/axe_dashboard.py`.
3. A reproducible **synthetic-data benchmark harness** under `tests/perf/` (or `scripts/perf/`) capable of generating
   fixture datasets (100 / 500 / 2,000 ChangeSpecs; 50 / 200 / 1,000 agents; 1 MB / 5 MB / 20 MB replies) and driving
   headless TUI scenarios: cold start, query change, 50-key j/k burst, auto-refresh with no changes, large-reply select.
   Captures the metric targets listed in research §"Benchmark targets".
4. A short `docs/perf_runbook.md` (or section in an existing doc) telling future-phase agents how to run the harness,
   where the JSONL lands, and which metrics gate each later phase.

**Acceptance.**

- `SASE_TUI_TRACE=1 sase ace`, exit, then a fresh `tui_trace.jsonl` shows spans for: one startup, one query change, one
  auto-refresh, and a 50 j/k burst.
- The benchmark harness produces a baseline numbers file the next phase can compare against.
- `just check` passes.

**Out of scope.** Any actual hot-path optimization. (Phase 1 only _measures_.)

---

## Phase 2 — ChangeSpec j/k Hot Path: Detail-Only Refresh + Row Patching + Cached Widget Refs

**Why now.** Research §"Suggested implementation order" identifies this as the fastest visible win for j/k. Today the
debounced selection path still calls the broad refresh which rebuilds the option list, even though list _shape_ didn't
change.

**Deliverables.**

1. New `_refresh_changespec_detail_only()` in `actions/changespec/_display.py` that updates only detail / ancestors /
   footer / info-panel for the new selection. Pure j/k navigation must NOT call `ChangeSpecList.update_list()`.
2. The full `_refresh_display()` is preserved and continues to be called for query/filter changes, fold-level changes,
   hint-mode toggles, mark/unmark, reload, and visibility toggles.
3. `patch_changespec_row(idx, changespec, *, selected, marked, hint)` on `widgets/changespec_list.py` — modeled on the
   existing `AgentList.patch_agent_row`. Maintains the row-index maps (`_option_idx_by_changespec_name`,
   `_last_row_signature_by_idx`, `_row_widths_by_idx`) needed to fall back to a full rebuild only when width grows
   beyond the cached list width, count/order changes, or global query/hint/fold state changes.
4. Stable widget-ref cache: after mount, the app holds `self._w_changespec_list`, `self._w_changespec_detail`,
   `self._w_ancestors_children`, `self._w_footer`, `self._w_agent_detail`, etc., used in place of repeat
   `query_one(...)` calls on hot paths.

**Acceptance.**

- Pytest: monkeypatch `ChangeSpecList.update_list` and simulate 50 `current_idx` changes — call count stays at 0;
  `update_highlight` runs once per nav event.
- Pytest: toggling mark on one visible ChangeSpec calls `patch_changespec_row` once and never `clear_options()`.
- `tui_trace.jsonl` from Phase 1 shows `query_one` count drop ~to zero on stable panels during a 50-key burst.
- 50-key j/k burst p95 paint < 16 ms on the 500-ChangeSpec fixture.
- `just check` passes.

---

## Phase 3 — ChangeSpec Data Layer: Snapshot Cache + Query Context + Graph Index

**Why now.** With Phase 2 making selection cheap, the next bottleneck moves to filter / refresh / query-evaluation work.
Research §P2 (#5–#7) targets parse, filter, and graph builds.

**Deliverables.**

1. `ChangeSpecSnapshotCache` in `src/sase/ace/changespec/cache.py` keyed by `(path, mtime_ns, size)`. Exposes
   `find_all_changespecs_cached()` and `get_file_specs(path)`. Optional persistent backing at
   `~/.sase/cache/changespecs-v1.json`, used only when _all_ file signatures match. TUI loading switches from
   `find_all_changespecs()` to the cached variant.
2. `QueryEvaluationContext` dataclass + `build_query_context()` + `evaluate_query_with_context()` in
   `src/sase/ace/query/evaluator.py`. Holds `name_map`, `status_map`, `searchable_text`, `searchable_lower`,
   `ancestor_memo`. Filtering builds context once per ChangeSpec-list version and reuses it across rows.
3. `ChangeSpecGraphIndex` in `src/sase/ace/tui/models/changespec_graph_index.py` with `name_map`, `children_by_parent`,
   `status_by_name`, `siblings_by_base_name`, `terminal_count`, `submitted_count`. Built once per `_all_changespecs`
   change. `AncestorsChildrenPanel` gains `update_relationships_from_index()`.

**Acceptance.**

- Pytest: warm `find_all_changespecs_cached()` makes zero `parse_project_file()` calls when nothing changed; editing one
  `.gp` file reparses only that file.
- Pytest: for N ChangeSpecs, `build_name_to_base_status` runs once per filter refresh, not once per row;
  `_get_searchable_text` ≤ 1 call per ChangeSpec per list version; ancestor query over 1k specs does not rebuild a name
  map 1k times.
- Pytest: selecting 100 different ChangeSpecs does not rebuild the children map / status map 100 times.
- Phase 1 trace: warm ChangeSpec reload < 100 ms at 1k specs.
- `just check` passes.

---

## Phase 4 — Agent Panel & List: O(1) Highlight, Lookup, Counts

**Why now.** Phases 2–3 leave the agent tab as the main remaining not-O(1) hot path. Research §P3 (#8, #9).

**Deliverables.**

1. `AgentPanelIndex` in `src/sase/ace/tui/models/agent_panel_index.py` (built once per `_agents` list identity +
   grouping/fold signature). Carries `keys_per_agent`, `panels: dict[PanelKey, PanelSlice]`, `non_child_indices`,
   `completed_count`. Used by: `_refresh_panel_widgets`, `_refresh_panel_highlights`, `_try_patch_agent_row`,
   `_update_agents_info_panel`, dismiss/status math.
2. Inside `widgets/agent_list.py`: build `_row_by_agent_attempt: dict[(int, int|None), int]`,
   `_row_by_agent_idx: dict[int, int]`, `_banner_row_by_key: dict[BannerKey, int]` during `update_list()`.
   `update_highlight()`, `_row_index_for_agent()`, `patch_agent_row()` use these maps instead of scanning row entries.

**Acceptance.**

- Pytest: `_refresh_panel_highlights` allocates no new `global_indices` list on j/k; `_update_agents_info_panel` never
  scans every agent for non-child position; completed/dismissable count is precomputed once per snapshot.
- Pytest: with 1,000 agents, 100 highlight moves perform zero linear scans of `_row_entries`.
- Phase 1 trace: agent-tab j/k p95 paint < 16 ms at 1,000 agents.
- `just check` passes.

---

## Phase 5 — Incremental Agent Loading + Deferred Heavy Detail

**Why now.** Background refresh is now the dominant cost source: agent loading rescans projects, artifact dirs, attempt
history, retry state, dismissed bundles every refresh. Detail panels also start expensive workers mid-burst that get
superseded ms later. Research §P4 (#10, #11).

**Deliverables.**

1. `AgentSnapshotCache` in `src/sase/ace/tui/actions/agents/_snapshot_cache.py` (or near the existing loader module)
   keyed by signatures of: project files, agent artifact dirs, attempt metadata files, `retry_state.json`, dismissed
   bundles, tag file. Exposes `load_agents(*, changespec_snapshot, force=False)`.
   - Pass cached ChangeSpec snapshot through; do NOT re-call `find_all_changespecs()` inside the loader when one is
     supplied.
   - Cache `load_attempt_history(artifacts_dir)` by attempt-dir/file mtimes.
   - Cache retry state by `(path, mtime_ns, size)`.
   - Defer dismissed-bundle expansion until the dismissed panel is visible.
   - Use the existing `fs_watcher` to invalidate affected agents instead of dropping the whole snapshot.
2. Agent-detail two-phase update in `widgets/agent_detail.py` + `actions/agents/_display.py`:
   - **Immediate**: title/status + cached prompt summary.
   - **Idle/debounced**: file/thinking/diff workers fire only after the existing detail debouncer settles, gated by a
     monotonically-increasing `_agent_detail_generation` token; stale-generation worker results are dropped.

**Acceptance.**

- Pytest: agent auto-refresh with no FS changes performs zero ChangeSpec parses.
- Pytest: agent auto-refresh with one updated live reply reloads only that agent's volatile artifact data.
- Pytest: attempt history is not re-read for every agent on every refresh.
- Pytest: 50-agent j/k burst spawns file/thinking workers only for the _final_ selected agent.
- Phase 1 trace: idle auto-refresh shows ~zero work when nothing changed.
- `just check` passes.

---

## Phase 6 — Artifact + Render Caching: Large Prompts/Replies/Diffs/Logs

**Why now.** With background and selection costs handled, the remaining visible jank comes from re-rendering big Rich
`Syntax` blocks and re-reading large artifact files. Research §P5 (#12, #13, #14).

**Deliverables.**

1. `AgentArtifactCache` in `src/sase/agent/agent_artifacts_cache.py` keyed by
   `(agent identity, artifacts_dir, file path, mtime_ns, size, attempt, view mode, terminal width)`. Caches: prompt-file
   selection result, prompt content, raw xprompt content, response content, chat response content, timestamped reply
   chunks, live-reply tail, prebuilt Rich renderables where safe. Live-reply path uses a
   `TailCache(path, size, offset, text)` to read only appended bytes when size grows; resets when size shrinks.
2. Lazy / capped Rich `Syntax`:
   - `SYNTAX_HIGHLIGHT_MAX_BYTES = 64_000`, `SYNTAX_HIGHLIGHT_MAX_LINES = 1_500`.
   - Above cap: render as plain `Text` with a small "Large output rendered without syntax highlighting" notice;
     optionally schedule highlight after idle if selection stays stable.
   - Diffs: highlight only the visible/trimmed line range first.
   - Apply in `widgets/prompt_panel/_agent_display.py`, `widgets/file_panel/_display.py`, and
     `widgets/axe_dashboard.py`.
3. Diff worker dedupe + cache in `widgets/file_panel/_diff.py`:
   - `DiffCacheKey = (agent_identity, workspace_path, vcs_provider_name, worktree_fingerprint)` where fingerprint starts
     as workspace path + `.git/index` (mtime, size) + a 2-second TTL fallback for active agents.
   - `self._inflight_diff_tasks: dict[DiffCacheKey, Worker]` so concurrent selections of the same target attach to one
     worker.

**Acceptance.**

- Pytest: re-selecting the same agent doesn't re-glob prompt files; `Syntax` creation count drops on repeat selection;
  live-reply refresh doesn't reread the full file when only appended.
- Pytest: a 5 MB response paints immediately as plain text and never freezes the UI; first paint p95 stays under j/k
  target.
- Pytest: re-selecting the same active agent with unchanged worktree does not call `diff_with_untracked()` again;
  navigating away mid-diff does not paint the wrong agent's panel.
- `just check` passes.

---

## Phase 7 — Event-Driven Auto-Refresh + Small Wins

**Why last.** With the heavy paths cached, the remaining gain is replacing periodic polling with watcher-driven
invalidation, plus a sweep of cheap fixes. Research §P6 + §P7 (#15–#20).

**Deliverables.**

1. **Event-driven auto-refresh** in `actions/event_handlers.py` + `util/fs_watcher.py`. Track `_dirty_changespecs`,
   `_dirty_agents`, `_dirty_axe`, `_last_full_sanity_refresh`. Watcher events flip dirty flags; auto-refresh only does
   the refreshes whose flag is set, plus a slow `FULL_SANITY_REFRESH_SECONDS = 60` floor. Falls back to existing polling
   when watcher inactive (non-Linux).
2. **AXE list rendering disk-free**. `widgets/bgcmd_list.py` + `actions/axe_loaders.py`: parent option formatting uses
   precomputed counts (`len(lumberjack_names)`) — no `load_axe_config()` during row render.
3. **ANSI parse cache** for AXE output keyed by `(source_id, mtime_ns, size, tail_hash)` in `widgets/axe_dashboard.py`.
   Append-only logs parse only new tail; fixed 500-line tails reuse cached parse on hash match.
4. **Saved-query cache**. `SearchQueryPanel.render` no longer calls `load_saved_queries()`; `actions/startup.py` loads
   them once into `self._saved_queries`. Invalidated only on explicit save/delete.
5. **Idempotent footer**. `widgets/keybinding_footer.py` stores `_last_bindings_signature`, `_last_status_signature`;
   skips updates on match; caches child widget refs in `on_mount`.
6. **Lazy startup data**. Defer xprompt snippet loading and custom keymap resolution until prompt entry / help / footer
   first needs them.

**Acceptance.**

- Pytest: with watcher active and no FS changes, auto-refresh performs no full `load_agents_from_disk`; a changed agent
  artifact triggers an agents refresh; a changed `.gp` triggers a ChangeSpecs refresh; AXE running state still updates
  while AXE is active.
- Pytest: `BgCmdList.update_list()` performs no disk config reads.
- Pytest: refreshing unchanged AXE output never calls `Text.from_ansi`; appending one line doesn't reparse unrelated
  dashboard sections.
- Pytest: repeated detail renders don't call `load_saved_queries()`; 100 j/k moves with unchanged bindings don't rebuild
  full footer text 100 times.
- Phase 1 trace: cold startup first paint doesn't depend on snippet loading unless prompt UI is visible.
- `just check` passes.

---

## Cross-cutting conventions for every phase agent

- **Read first**: `sdd/research/202604/sase_perf_research.md` (whole file is short enough), the relevant phase section above, and
  `memory/short/build_and_run.md` (workspace + `just install` requirement before `just check`).
- **No new comments / docstrings unless WHY is non-obvious** — this repo's AGENTS.md is firm on that.
- **No backwards-compat shims** for removed code; delete cleanly.
- **Tests live alongside the unit you changed** (`tests/...`), with perf-style tests under `tests/perf/` only when they
  don't slow the default test run materially. Default to fast unit-level assertions on call counts / cache hits.
- **Always finish with `just check`** before reporting done.
- **Report the Phase 1 numbers before/after** in the PR/commit body so the next agent (and the user) can audit progress.

## Risk + sequencing notes

- Phase 1 is a hard prerequisite for all later phases — the trace and benchmark harness are how every later phase proves
  it didn't regress another path.
- Phases 2 and 3 should land in order (detail-only path before query context) so each is clearly attributable in the
  trace.
- Phases 4 and 5 can technically swap but Phase 4's `AgentPanelIndex` makes Phase 5's incremental loader changes much
  easier to reason about, so prefer the listed order.
- Phase 6 depends on Phase 5's `_agent_detail_generation` token being in place to discard stale results from artifact /
  diff workers.
- Phase 7 deliberately bundles small + small; if its agent runs out of budget, items 4/5/6 (saved-query, footer,
  lazy-startup) are the safest to defer to a follow-up.
