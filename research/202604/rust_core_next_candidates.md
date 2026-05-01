# Next Migration Candidates from `sase` (Python) → `sase-core` (Rust)

**Goal:** identify the next operations to port from `src/sase/` into `../sase-core/`,
prioritising work that **blocks the TUI on the user's input path**. End the analysis
with a ranked top-five list.

This is a follow-on to `rust_backend_migration.md` (Phases 0–8, all shipped) and the
performance findings in `sase_perf_research.md`, `sase_perf_v2_research.md`, and
`rust_backend_phase7_performance.md`. Phase 8 retired the Python halves of every
shipped operation; the Rust crate is now the only implementation of `parse_project_bytes`,
`parse_query`, `scan_agent_artifacts`, the status helpers, the Git query parsers, and
`plan_agent_cleanup`. The remaining surface is the *next* set of candidates against
that same wire-record + golden-corpus playbook.

## What's still Python today

Pulled from the Phase 8A operation disposition and a fresh code-map sweep of
`src/sase/`. "TUI-coupled" means it runs on the UI/event-loop thread today (or on
a worker that the user is waiting for). Sizes are LOC, not bytes.

| Subsystem | Path | LOC | TUI-coupled? | Notes |
|---|---|---|---|---|
| **Notification store (JSONL)** | `src/sase/notifications/store.py` + `senders.py` | ~480 | **Yes — blocks kill / dismiss persistence** | Whole-file rewrite on every state transition. Every dismissed/read/snooze touch parses the entire JSONL, mutates a row, and rewrites the file under `flock`. |
| **Query batch evaluation** | `src/sase/ace/query/context.py`, `evaluator.py`, `query_facade.py` | ~1,100 | **Yes — runs on every filter keystroke** | `evaluate_query_many` was deferred in Phase 8B because the prototype routed Rust path was 6–9× *slower* than the optimised Python batch (per-call `ChangeSpecWire` rebuild dominated). |
| **Agent loader orchestration** | `src/sase/ace/tui/models/agent_loader.py` (+ `_dedup.py`, `_loaders/*`) | ~1,800 | **Yes — runs on every refresh on a worker** | Consumes the Rust `scan_agent_artifacts` snapshot but then runs `_apply_status_overrides`, several `dedup_*` passes, and `_filter_dead_pids` in pure Python over the full agent list. |
| **ChangeSpec graph index** | `src/sase/ace/tui/models/changespec_graph_index.py` (+ facade) | ~125 | **Yes — rebuilt per `_all_changespecs` change** | Phase 8A explicitly kept this Python; it powers the Ancestors/Children panel selection path. |
| **Agent supplement scan** | `src/sase/ace/tui/actions/agents/_snapshot_cache.py`, `src/sase/ace/dismissed_agents.py`, `src/sase/ace/agent_tags.py` | ~700 | **Yes — runs on every refresh on a worker** | `attempts/<N>/attempt_meta.json`, `retry_state.json`, the sharded `dismissed_bundles/` tree, and `agent_tags.json`. JSON parse + tree walk; ~6.5k rows on a real home tree. |
| **Agent artifact reads** | `src/sase/agent/agent_artifacts_cache.py`, `src/sase/ace/tui/widgets/prompt_panel/*` | ~900 | **Yes — runs on selection** | TailCache, prompt globbing, response/chat JSON, timestamped reply chunks. Rich rendering itself stays Python, but raw IO + JSON does not have to. |
| **Notification senders / priority** | `src/sase/notifications/senders.py`, `priority.py` | ~260 | Indirect (background) | Append-side path; pairs with the store port. |
| **History / telemetry JSONL** | `src/sase/history/*`, `src/sase/telemetry/metrics.py` | ~1,800 | Mostly background | `chat.py` (495 LOC) is read by `prompt_panel`; the rest is write-mostly. |
| **xprompt / dynamic memory matcher** | `src/sase/memory/`, xprompt expansion | ~330 | Yes — every prompt submit | Already small; flagged "low ROI" in the Phase 0 memo, but it is on the user's submit path. |
| **File watcher** | `src/sase/ace/tui/util/fs_watcher.py` | ~250 | Yes (watch loop) | `notify` crate would replace `watchdog`. Not a CPU win — a robustness win on macOS / network mounts. |
| **VCS file-panel diff workers** | `src/sase/ace/tui/widgets/file_panel/_diff.py` | ~165 | Yes — worker | The cost is the `git` subprocess fork+exec, not the parse. Phase 5A already concluded this is not a Rust port. |

## Where the TUI actually blocks today

`sase_perf_v2_research.md` is the source of truth for the remaining "the user
*feels* this" surfaces. Filtering its findings against what is still Python
after Phase 8:

1. **Kill / dismiss persistence triggers a full-notifications-file rewrite.**
   `dismiss_notifications_for_agent` → `load_notifications()` parses every JSONL
   line, mutates one, then `_rewrite_notifications()` writes them all back under
   `LOCK_EX`. This is on a worker thread post-v2-fix, but the next refresh of
   the unread badge still pays the full parse, and the kill keystroke is
   serialised behind it. With a multi-thousand-row notifications file, this
   shows up as visible lag between two consecutive `x` presses.
2. **j/k filter typing pays per-row Python wire conversion.**
   `evaluate_query_many` runs on every `_filter_changespecs` invocation. It
   calls `evaluate_query_with_context_python` per row over the whole project +
   archive. The Phase 8B prototype showed Rust at 8 µs/spec vs. Python at
   4–7 µs/spec, but only because each call rebuilt the wire record. The
   *correct* Rust shape is a persistent corpus handle + compiled query;
   without that, deleting the Python path locks in a regression.
3. **Agents-tab refresh pays Python orchestration on top of the Rust scan.**
   `_load_agents_from_all_sources` already calls `scan_agent_artifacts` (Rust)
   for the artifact tree, but then runs Python passes over the merged agent
   list: `_apply_status_overrides` (multiple O(N) sweeps + ordered sort by
   `run_start_time`), `dedup_axe_spawned_agents`, `dedup_by_pid`,
   `dedup_running_vs_workflow`, `dedup_workflow_entries`,
   `remove_vcs_workspace_claims`, `_filter_dead_pids`. On a 6.5k-agent home
   tree this is a measurable fraction of the refresh budget and runs on every
   poll.
4. **Selection paths read JSON the snapshot cache cannot help with on first
   touch.** `AgentSnapshotCache.dismissed_bundles()` walks `dismissed_bundles/`
   shards and parses every `.json` whose `(mtime_ns, size)` changed. The
   selection-time read of `attempts/<N>/attempt_meta.json` is similar. Python
   `json.loads` over hundreds of small files is ~10× slower than `simd-json`
   in Rust and runs on the user-visible refresh path the first time after a
   write.
5. **Ancestors/Children panel rebuilds on every selection.** After the
   Phase-2 detail-only refresh shipped, `ChangeSpecGraphIndex` is the
   per-selection Python work. A 1k-spec graph rebuild is sub-millisecond
   today, but the index is also recomputed inside `evaluate_query_with_context`
   (ancestor matching) — porting both behind one `GraphIndexWire` shape
   would let a single Rust pass amortise the cost across query eval and
   panel render.

The other items in the Python column (history, telemetry, file watcher,
notification senders, xprompt matcher) are real Python code, but none of them
land on a user-visible blocking path the way the five above do.

## Recommendation criteria

Same gates Phase 6+ used, ordered by what Phase 7 actually proved:

1. **End-to-end win on a routed surface, not microbench.** Phase 7C made
   `sase agents status -j` 2.59× faster cold while the operation microbench
   was only 1.21×. The user-facing surface is the gate; microbench is
   evidence.
2. **FFI granularity matters more than core speed.** The Phase 8B
   `evaluate_query_many` regression and the Phase 4 / Phase 5 sub-µs cores are
   the same lesson: a 3× faster Rust core that crosses the FFI boundary once
   per row is a regression. Design the API around batches or persistent
   handles before measuring.
3. **Unblock the user's input path first; shared-core hygiene second.** The
   Status / Git ports landed for shared-core hygiene at performance-neutral
   cost; that is fine *after* the user-blocking work is done. It is not a
   reason to start a new port today.
4. **Don't delete the Python implementation until the Rust replacement clears
   the Phase 7 regression floor.** Phase 8B's deferral is the template:
   ship Rust opt-in, measure, then retire Python.

## Top 5 next things to migrate

Highest-priority first. Each entry names the wire surface, the user-visible
win, the FFI shape that will not regress, and the hard prerequisite before
the Python path can be deleted.

### 1. Notification store (`sase.notifications.store`)

**This is the user's stated priority — the backend functionality that blocks
the TUI on the kill / dismiss path.** Whole-file JSONL parse + rewrite under
`LOCK_EX` runs every time a notification is read, dismissed, snoozed, or
muted; the kill keystroke is serialised behind it.

- **Rust crate location:** `crates/sase_core/src/notifications/`.
- **Wire records:** `NotificationWire`, `NotificationStateUpdateWire`
  (`mark_read | mark_dismissed | mark_muted | mark_snoozed | expire_snoozes`),
  `NotificationStoreSnapshotWire`.
- **PyO3 surface:** `read_notifications_snapshot(path, include_dismissed)`
  returning a list of wire records, `apply_notification_state_update(path,
  update)` returning the new snapshot count + per-id outcome. Append stays a
  single small `f.write` in Python — no benefit to Rust there.
- **Why it wins:** `simd-json` per-line parse + an in-memory log-structured
  rewrite (parse once, mutate in place, write once) cuts the per-mutation
  cost dramatically and removes the Python `dataclasses.asdict` + `json.dumps`
  per-row tax. The unread-count refresh becomes a cheap Rust call instead of
  a full Python parse.
- **FFI shape:** the snapshot is a single `Vec<NotificationWire>` per call.
  The mutation API takes a typed update enum and returns the post-update
  snapshot; no per-row dispatch.
- **Prereq before Phase-8-style deletion:** the Phase 7 regression floor
  baseline includes a `notification_store_kill_burst` end-to-end timing on a
  synthetic 5k-notification corpus, and the dual-run drift log shows zero
  mismatches over a release cycle (the file format is user-visible — drift
  here corrupts notifications).
- **Estimated LOC:** ~300 Python → ~600 Rust (parser + mutator + tests).

### 2. Query batch evaluation with a persistent corpus handle

The Phase 8B re-port. The deferral was *exactly* the FFI-granularity
anti-pattern from §7 of `rust_backend_migration.md`. The right shape is the
one Phase 0 §4 sketched and Phase 2 partially landed for `parse_query`:
compile both the query and the corpus once, evaluate many.

- **Rust crate location:** `crates/sase_core/src/query/` (extend
  `query/program.rs` with a corpus-bound `Evaluator`).
- **Wire records:** `CorpusHandle` (opaque PyCapsule wrapping a
  `Vec<ChangeSpecWire>` + precomputed name/status/searchable maps),
  `QueryProgram` (already exists), `QueryEvaluationContextWire`.
- **PyO3 surface:** `compile_corpus(specs_wire) -> CorpusHandle`,
  `compile_query(query_str) -> QueryProgram`, `evaluate_many(program,
  corpus) -> Vec<bool>`. Python keeps the corpus handle alive across filter
  keystrokes; on `_all_changespecs` change, drop the handle.
- **Why it wins:** moves the wire conversion that killed Phase 8B's
  prototype to a one-time setup, then every filter keystroke is a single
  Rust call returning a packed `Vec<bool>`. Re-runs the Phase 7B
  `evaluate_query_many.synthetic_1000` and `synthetic_10000` benches with the
  amortised path; the gate is "≥2× faster than the optimised Python batch".
- **FFI shape:** one call per filter keystroke, no per-row crossings.
- **Prereq before Phase-8-style deletion:** beats `_evaluate_query_many_python`
  on `synthetic_100`, `synthetic_1000`, `synthetic_10000`, **and** the home
  tree at the regression floor; the corpus-handle invalidation contract is
  documented and tested against a forced-stale handle. (Phase 8B's
  acceptance criterion, restated.)
- **Estimated LOC:** ~700 Python → ~1,000 Rust + ~200 PyO3 glue.

### 3. Agent loader orchestration & status override pipeline

After Phase 3 the artifact scan is in Rust, but the merge / dedup /
status-override layer is still Python and runs over the union of every agent
the scan + ChangeSpec sweep produces. On a 6.5k-row home tree this is the
biggest fully-Python step on the refresh path.

- **Rust crate location:** `crates/sase_core/src/agent_compose/`.
- **Wire records:** consume the existing `AgentArtifactScanWire` from
  Phase 3 and the `ChangeSpecWire` list; produce
  `ComposedAgentListWire { agents: Vec<AgentWire>, workflow_steps,
  dropped: Vec<DropReasonWire> }`.
- **PyO3 surface:** `compose_agent_list(scan, changespecs, dismissed_set,
  options) -> ComposedAgentListWire`. Python keeps process-running checks
  (PID liveness is host-OS specific) but feeds them in via an
  `AlivePidPredicate` callback or a pre-collected set.
- **Why it wins:** removes the Python `_apply_status_overrides`,
  `dedup_axe_spawned_agents`, `dedup_by_pid`, `dedup_running_vs_workflow`,
  `dedup_workflow_entries`, `remove_vcs_workspace_claims`, and
  `_filter_dead_pids` passes from the worker. Gets us out of the
  "Python iterates 6,500 agents twice per refresh" regime, and produces a
  stable shape for `sase agents status -j` to render directly without a
  second Python sweep.
- **FFI shape:** one call per refresh; the result is a single owned
  `Vec<AgentWire>` plus a small drop log.
- **Prereq before Phase-8-style deletion:** Phase 7-style end-to-end
  regression floor on `sase agents status -j` and the TUI agents-tab
  refresh trace; parity tests covering the status-override edge cases
  (`PLANNING`, `PLAN APPROVED`, `EPIC CREATED`, `QUESTION`, RETRYING
  promotion) since these were historically the source of TUI status drift
  bugs.
- **Estimated LOC:** ~1,400 Python (loader + dedup + overrides) → ~1,800 Rust.

### 4. ChangeSpec graph index (`build_changespec_graph_index`)

Phase 8A kept this Python because it was sub-millisecond on a 1k corpus.
After candidate #2 above lands, the same maps the graph index builds
(`name_map`, `status_by_name`) are also live on the Rust corpus handle —
porting the index lets the Ancestors/Children panel and the query
context share one Rust-side build.

- **Rust crate location:** `crates/sase_core/src/changespec_graph/`.
- **Wire records:** `ChangeSpecGraphIndexWire { name_map, status_by_name,
  children_by_parent, siblings_by_base_name, terminal_count,
  submitted_count }`.
- **PyO3 surface:** `build_changespec_graph_index(specs_wire) ->
  GraphIndexHandle` (opaque) plus typed accessors (`children_of`,
  `siblings_of`, `is_ancestor`, `terminal_count`). The accessors keep the
  TUI from copying the whole map across FFI on each panel update.
- **Why it wins:** consolidates the per-selection panel rebuild and the
  ancestor membership check from candidate #2 onto one Rust structure;
  removes a duplicate Python build per `_all_changespecs` change.
- **FFI shape:** one build call per ChangeSpec list version; per-selection
  reads use the typed accessors and never serialise the full map.
- **Prereq before Phase-8-style deletion:** parity tests against
  `build_changespec_graph_index_python` over the golden corpus + the
  archive corpus; integration test that a `_all_changespecs` swap drops
  the prior handle (the index is large enough that leaking it across
  reloads matters).
- **Estimated LOC:** ~125 Python → ~250 Rust + accessor glue.

### 5. Agent supplement scan (`AgentSnapshotCache` payload)

`attempts/<N>/attempt_meta.json`, `retry_state.json`, the sharded
`dismissed_bundles/**/*.json`, and `agent_tags.json` are all small JSON
files read on every refresh that follows a write. Today the Python cache
keys by `(mtime_ns, size)` and skips re-reads, but the cold and post-write
hits run JSON parse on a worker thread the user is waiting for.

- **Rust crate location:** `crates/sase_core/src/agent_supplements/`
  (sibling to the existing `agent_scan/`).
- **Wire records:** extend `AgentArtifactScanWire` with
  `AgentSupplementsWire { attempt_history_by_dir, retry_state_by_dir,
  dismissed_bundles, agent_tags }` so one Rust call returns everything
  the loader needs.
- **PyO3 surface:** `scan_agent_supplements(root, options) ->
  AgentSupplementsWire`, GIL-released during the walk; the snapshot
  cache key becomes a single tree-signature hash returned alongside the
  payload.
- **Why it wins:** `walkdir` + `rayon` + `simd-json` for the same trees
  that Phase 3 already ports for the artifact scan; keeps the loader's
  worker step single-FFI; removes ~6,500 small Python `json.loads` calls
  on a real home-tree refresh.
- **FFI shape:** one call per refresh, alongside (or merged into) the
  existing `scan_agent_artifacts` call.
- **Prereq before Phase-8-style deletion:** parity tests against the
  Python `AgentSnapshotCache` accessors on the home-tree fixture; the
  Phase 7 floor includes a cold `agents-tab refresh post-write` timing
  so the JSON-parse savings are visible above noise.
- **Estimated LOC:** ~700 Python → ~1,100 Rust.

## What I deliberately did not recommend

- **Notification senders / priority** — pairs with #1, but the senders
  path is not on the blocking input path; do it as part of #1's package
  if scope allows, otherwise leave it.
- **History / telemetry JSONL** — write-mostly; the read paths are
  `prompt_panel` displays, which are already debounced into the detail
  worker. Below the user-perceived bar.
- **xprompt / dynamic memory matcher** — flagged as low ROI in Phase 0
  and the data confirms it. Submit-time, sub-frame.
- **File watcher** — switching from `watchdog` to `notify` would be a
  robustness improvement, not a TUI-blocker fix; treat as a separate
  initiative.
- **VCS diff parsing** — Phase 5 closed this. Subprocess fork+exec
  dominates. Reopening only makes sense behind a `gix` epic against a
  measured workload, not as a port of more parsers.
- **Workflow state machine / dispatch** — large, Python-host-coupled
  (plugin entry points, subprocess management); does not fit "below
  plugins" the way the parser/query/scan/cleanup ports did.

## How to actually do this without breaking the TUI

The Phase 0–8 discipline still applies. Rephrased for these candidates:

1. **Land each port behind a facade with golden tests before flipping any
   default.** The facade pattern (`src/sase/notifications/store_facade.py`,
   `src/sase/core/query_corpus_facade.py`, etc.) keeps the TUI on the
   Python implementation while Rust is being measured.
2. **Capture the workload before writing Rust.** For #1, that is a real
   `notifications.jsonl` snapshot from a heavy user (sanitised) plus a
   synthetic 5k corpus. For #2, the Phase 7B query benches plus a home-tree
   corpus. For #3, the Phase 7C `sase agents status` baseline. For #4,
   the existing `tests/perf/bench_core_parse.py` corpus. For #5, a
   home-tree fixture similar to Phase 3.
3. **Design for FFI granularity first.** None of these should call Rust
   per row, per file, or per spec. The persistent-handle pattern in
   candidate #2 is the template.
4. **Add the regression floor entry before deleting Python.** Phase 7E's
   `tests/perf/baselines/phase7_regression_floor.json` is the contract;
   each new port should land its own floor row and a CI job that fails
   on regression.
5. **Sequence around the user's blocking path.** #1 first because it is
   the only entry on the list that the user feels on a single keystroke
   today. #2 next because every keystroke into the filter input pays
   `evaluate_query_many`. #3 and #5 next as the agents-refresh
   double-feature; they share a fixture and an FFI call shape. #4 last
   because it is the smallest and only justifies the port once #2 lands.

## References

- `research/202604/rust_backend_migration.md` — Phases 0–8 history and
  forward plan.
- `research/202604/rust_backend_phase7_performance.md` — realised Phase 7
  numbers and gate-vs-realised verdicts.
- `research/202604/rust_backend_phase2_query_handoff.md` — wire-record
  contract for the query path; reused by candidate #2.
- `research/202604/sase_perf_research.md` — original TUI hot-path memo;
  candidates #3, #4, #5 close out items P2.5, P2.7, P4.10.
- `research/202604/sase_perf_v2_research.md` — second-pass audit;
  candidate #1 closes out the kill-path notification I/O finding.
- `plans/202604/rust_backend_phase8_phase8a_handoff.md` — Phase 8A
  operation disposition (what is shipped vs. deferred vs. unported).
- `plans/202604/rust_backend_phase8_phase8b_handoff.md` —
  `evaluate_query_many` deferral; the candidate-#2 design picks up where
  this left off.
