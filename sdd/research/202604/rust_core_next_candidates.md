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

Status update (2026-05-01): the #2 query batch recommendation below has shipped through
the persistent-corpus migration in `plans/202604/query_batch_persistent_corpus.md`.
The TUI product path now uses cached Rust query corpora, and the public batch
compatibility wrapper compiles a temporary Rust corpus for one-off callers. The rest of
this file remains a research snapshot for the original candidate ranking.

Status update (2026-05-01): the #3 agent-loader orchestration recommendation was
attempted as bead `sase-1p` and then reverted. Do not retry the `agent_compose`
plan below as written. Treat the Python loader composition path as the product
oracle, migrate smaller colder slices first, require real TUI/status parity
before routing, preserve a kill switch, and keep the Python path until live-ish
end-to-end evidence passes.

## What's still Python today

Pulled from the Phase 8A operation disposition and a fresh code-map sweep of
`src/sase/`. "TUI-coupled" means it runs on the UI/event-loop thread today (or on
a worker that the user is waiting for). Sizes are LOC, not bytes.

| Subsystem | Path | LOC | TUI-coupled? | Notes |
|---|---|---|---|---|
| **Notification store (JSONL)** | `src/sase/notifications/store.py` + `senders.py` | ~480 | **Yes — modal actions, notification polling, and kill/dismiss persistence** | Whole-file rewrite on every state transition. Every dismissed/read/snooze touch parses the entire JSONL, mutates a row, and rewrites the file. The kill immediate stage has since moved this work to a worker, but the store still blocks notification-modal actions and can serialize the post-kill badge refresh. |
| **Query batch evaluation** | `src/sase/ace/query/context.py`, `evaluator.py`, `query_facade.py` | ~1,100 | **Yes — runs on every filter keystroke** | `evaluate_query_many` was deferred in Phase 8B because the prototype routed Rust path was 6–9× *slower* than the optimised Python batch (per-call `ChangeSpecWire` rebuild dominated). |
| **Agent loader orchestration** | `src/sase/ace/tui/models/agent_loader.py` (+ `_dedup.py`, `_loaders/*`) | ~1,800 | **Yes — runs on every refresh on a worker** | **Do not retry as written.** The `agent_compose` orchestration migration was attempted as `sase-1p` and reverted; keep Python composition as product/oracle and carve out smaller colder slices first. |
| **ChangeSpec graph index** | `src/sase/ace/tui/models/changespec_graph_index.py` (+ facade) | ~125 | Weak — rebuilt only per `_all_changespecs` list identity | Phase 8A explicitly kept this Python. The current TUI already caches the index in `_get_changespec_graph_index()`, so this is no longer a per-selection blocker. |
| **Agent supplement scan** | `src/sase/ace/tui/actions/agents/_snapshot_cache.py`, `src/sase/ace/dismissed_agents.py`, `src/sase/ace/agent_tags.py` | ~700 | **Yes — consulted on every refresh on a worker** | `attempts/<N>/attempt_meta.json`, `retry_state.json`, the sharded `dismissed_bundles/` tree, and `agent_tags.json`. The Python cache skips unchanged files, but cold/post-write refreshes still walk/stat/parse a large home tree. |
| **Agent artifact content reads** | `src/sase/agent/agent_artifacts_cache.py`, `src/sase/ace/tui/widgets/prompt_panel/*` | ~900 | **Yes — runs on debounced selection detail** | The immediate path is now header-only, but the full detail update still globs/reads prompt, response, chat, live-reply, and timestamp chunks on first touch. Rich rendering itself stays Python, but raw IO + chunk slicing can move. |
| **Notification senders / priority** | `src/sase/notifications/senders.py`, `priority.py` | ~260 | Indirect (background) | Append-side path; pairs with the store port. |
| **History / telemetry JSONL** | `src/sase/history/*`, `src/sase/telemetry/metrics.py` | ~1,800 | Mostly background | `chat.py` (495 LOC) is read by `prompt_panel`; the rest is write-mostly. |
| **xprompt / dynamic memory matcher** | `src/sase/memory/`, xprompt expansion | ~330 | Yes — every prompt submit | Already small; flagged "low ROI" in the Phase 0 memo, but it is on the user's submit path. |
| **File watcher** | `src/sase/ace/tui/util/fs_watcher.py` | ~250 | Yes (watch loop) | `notify` crate would replace `watchdog`. Not a CPU win — a robustness win on macOS / network mounts. |
| **VCS file-panel diff workers** | `src/sase/ace/tui/widgets/file_panel/_diff.py` | ~165 | Yes — worker | The cost is the `git` subprocess fork+exec, not the parse. Phase 5A already concluded this is not a Rust port. |

## Where the TUI actually blocks today

`sase_perf_v2_research.md` is still the right source for "the user feels this",
but two follow-up fixes changed the exact shape:

1. **Notification mutation is still the most important backend blocker, but
   no longer for the exact reason the earlier note claimed.** Current
   `_do_kill_agent()` applies the optimistic UI mutation first, then schedules
   `_run_kill_persistence_async()`, so the kill keystroke itself no longer
   waits on `load_notifications()` / `_rewrite_notifications()`. The remaining
   blockers are the synchronous notification-modal state changes
   (`mark_dismissed`, `mark_muted`, `mark_snoozed`, `mark_all_read`), direct
   notification jumps that call `load_notifications()`, `expire_due_snoozes()`
   being invoked on the event loop after the async load, and post-kill badge
   refreshes waiting for the worker rewrite to release the file lock.
2. **The notification store has a correctness gap, not just a speed gap.**
   `_rewrite_notifications()` opens the JSONL with `"w"` and only then takes
   `flock(LOCK_EX)`. Opening with `"w"` truncates before the lock is held, so a
   concurrent reader or writer can observe an empty/intermediate file. A Rust
   port should not preserve this locking shape; it should use a stable lock
   file or open without truncation, lock, write a temp file, fsync, and rename.
3. **Filter typing still pays the Python batch evaluator.**
   `evaluate_query_many` runs on every `_filter_changespecs` invocation. The
   Phase 8B prototype showed that `sase_core_rs.evaluate_query_many(query,
   spec_dicts)` is 10× slower even when `spec_dicts` are precomputed, because
   PyO3/serde rebuilds `ChangeSpecWire` from Python dicts on every call. The
   *correct* Rust shape is a persistent corpus handle + compiled query; without
   that, deleting the Python path locks in a regression.
4. **Agents-tab refresh still does Python composition after the Rust scan.**
   `_load_agents_from_all_sources` already calls `scan_agent_artifacts` for
   `agent_meta.json`, `done.json`, `running.json`, `waiting.json`,
   `workflow_state.json`, `plan_path.json`, and `prompt_step_*.json`. It then
   builds Python `Agent` objects, runs `_filter_dead_pids`, the dedup passes,
   `_apply_status_overrides`, and `_sort_and_reorder`. On a large home tree,
   this is now the biggest fully-Python backend phase in the Agents refresh
   worker.
5. **Supplement and detail reads are still first-touch costs.**
   `AgentSnapshotCache` avoids re-parsing unchanged
   `attempts/<N>/attempt_meta.json`, `retry_state.json`, dismissed bundles, and
   `agent_tags.json`, so the old "parse thousands of files every refresh"
   claim is too strong. The cold/post-write path still walks/stat/parses those
   files. Separately, the agent detail immediate path is now header-only, but
   the debounced full detail render still reads prompt/reply/response/chat
   artifacts on first touch.

The previous analysis also overstated the ChangeSpec graph index. The current
TUI caches `ChangeSpecGraphIndex` by `id(_all_changespecs)` and passes the
prebuilt index to `update_relationships_from_index()`, so graph-index work is
not a top-five blocker on its own.

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

Historical priority order from the original research pass, with 2026-05-01
status notes folded in. Candidate #3 is no longer a straightforward next
migration; it is retained to document the reverted hypothesis and the safer
replacement direction.

### 1. Notification store (`sase.notifications.store`)

**This is the user's stated priority — the backend functionality that still
blocks notification-modal actions and serializes post-kill notification
persistence.** Whole-file JSONL parse + rewrite runs every time a notification
is read, dismissed, snoozed, or muted. The single-kill immediate stage has
already moved the disk work to a worker, but the store is still the slow and
fragile backend primitive behind the notification UI.

- **Rust crate location:** `crates/sase_core/src/notifications/`.
- **Wire records:** `NotificationWire`, `NotificationStateUpdateWire`
  (`mark_read | mark_all_read | mark_dismissed | mark_many_dismissed |
  mark_muted | mark_snoozed | expire_snoozes | dismiss_matching_agents`),
  `NotificationStoreSnapshotWire`.
- **PyO3 surface:** `read_notifications_snapshot(path, include_dismissed)`
  returning a list of wire records plus precomputed counts
  `{priority, rest, muted}`, `apply_notification_state_update(path, update)`
  returning the updated counts + per-id outcome, and
  `append_notification(path, notification)` if the port also fixes locking
  for append/rewrite consistency. Keeping append in Python is acceptable only
  if rewrite locking moves to a separate lock file shared by both paths.
- **Why it wins:** `simd-json` per-line parse + an in-memory log-structured
  rewrite (parse once, mutate in place, write once) cuts the per-mutation
  cost dramatically and removes the Python `dataclasses.asdict` + `json.dumps`
  per-row tax. The unread-count refresh becomes a cheap Rust call instead of
  a full Python parse. More importantly, the port can replace the current
  truncate-before-lock rewrite with lock-then-tempfile-rename semantics.
- **FFI shape:** the snapshot is a single `Vec<NotificationWire>` per call.
  The mutation API takes a typed update enum and returns the post-update
  counts/snapshot; no per-row dispatch. `expire_snoozes` must run inside the
  same Rust mutation call, not as "load in thread, then maybe rewrite on the
  event loop".
- **Prereq before Phase-8-style deletion:** the Phase 7 regression floor
  baseline includes a `notification_store_kill_burst` end-to-end timing on a
  synthetic 5k-notification corpus, a `notification_modal_dismiss_burst`
  timing, and a concurrency test with one append process plus one rewrite
  process. The file format is user-visible and cross-process plugin-facing,
  so drift here corrupts notifications.
- **Estimated LOC:** ~300 Python → ~600 Rust (parser + mutator + tests).

### 2. Query batch evaluation with a persistent corpus handle

The Phase 8B re-port. The deferral was *exactly* the FFI-granularity
anti-pattern from §7 of `rust_backend_migration.md`. The right shape is the
one Phase 0 §4 sketched and Phase 2 partially landed for `parse_query`:
compile both the query and the corpus once, evaluate many.

- **Rust crate location:** `crates/sase_core/src/query/` (extend the existing
  `query/evaluator.rs`; `QueryProgram` and the pure Rust evaluator already
  exist, but the PyO3 layer only exposes the slow dict-deserializing batch).
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

### 3. Agent loader orchestration & status override pipeline -- do not retry as written

After Phase 3 the artifact scan is in Rust, but the merge / dedup /
status-override layer is still Python and runs over the union of every agent
the scan + ChangeSpec sweep produces. On a 6.5k-row home tree this is a large
fully-Python step on the refresh path, but the direct Rust orchestration port
described in this section was attempted as `sase-1p` on 2026-05-01 and then
reverted. Keep this section as a record of the original hypothesis, not as an
implementation plan to pick up unchanged.

**Postmortem-aware replacement direction:** keep Python composition as the
product path and oracle. If this area is revisited, first migrate smaller,
colder, easier-to-isolate slices around the loader rather than the whole
orchestration/status override pipeline: for example supplemental scan payloads,
content reads, or narrow pure-data helpers with stable fixtures. Any routed
Rust path must prove real TUI agents-tab and `sase agents status -j` parity,
including status text, ordering, dismissed rows, retry/workflow rows, and stale
PID handling. Preserve a runtime kill switch until after live-ish end-to-end
evidence passes, and do not delete the Python path while it is still needed as
the product oracle.

- **What not to do:** do not rebuild the whole merge/dedup/status-override
  layer in Rust as a single `agent_compose` route, do not treat an opt-in smoke
  run as product parity, and do not remove Python composition before the TUI
  and CLI surfaces have both run against realistic agent trees.
- **Safer first slices:** prefer cold-path supplement scanning, detail content
  reads, or small pure-data helpers whose inputs and outputs can be replayed
  against the Python loader without changing the product route.
- **Parity floor before routing:** capture fixtures that include planning
  states, approved plans, created epics, questions, retry promotion,
  workflow-spawned rows, dismissed bundles, stale PIDs, and VCS workspace
  claims. Validate both row content and ordering against the Python route.
- **Routing discipline:** if a future slice earns routing, keep the switch
  narrow and reversible. Treat Python as the oracle until live-ish TUI
  refreshes and `sase agents status -j` runs pass against the same home-tree
  corpus, with status labels and dismissed-row behavior included in the gate.

### 4. Agent supplement scan (`AgentSnapshotCache` payload)

`attempts/<N>/attempt_meta.json`, `retry_state.json`, the sharded
`dismissed_bundles/**/*.json`, and `agent_tags.json` are all small JSON
files consulted by the Agents tab. Today `AgentSnapshotCache` keys by
`(mtime_ns, size)` and skips re-reads for unchanged files, so this is not an
every-refresh JSON storm. It is still the cold/post-write work the user waits
for during refresh, and it is the natural sibling to the existing Rust
artifact scanner.

- **Rust crate location:** `crates/sase_core/src/agent_supplements/`
  (sibling to the existing `agent_scan/`).
- **Wire records:** extend `AgentArtifactScanWire` or add a companion
  `AgentSupplementsWire { attempt_history_by_dir, retry_state_by_dir,
  dismissed_bundles, agent_tags, tree_signature }`. Do not duplicate marker
  files already covered by `AgentArtifactScanWire` (`agent_meta`, `done`,
  `running`, `waiting`, `workflow_state`, `plan_path`, `prompt_step_*`).
- **PyO3 surface:** `scan_agent_supplements(root, options) ->
  AgentSupplementsWire`, GIL-released during the walk; the snapshot
  cache key becomes a single tree-signature hash returned alongside the
  payload.
- **Why it wins:** `walkdir` + `rayon` + `simd-json` for the same trees
  that Phase 3 already ports for the artifact scan; keeps the loader's
  worker step single-FFI; replaces the cold/post-write Python walk/stat/parse
  path for large home trees without regressing the existing unchanged-file
  cache behavior.
- **FFI shape:** one call per refresh, alongside (or merged into) the
  existing `scan_agent_artifacts` call.
- **Prereq before Phase-8-style deletion:** parity tests against the
  Python `AgentSnapshotCache` accessors on the home-tree fixture; the
  Phase 7 floor includes a cold `agents-tab refresh post-write` timing
  so the JSON-parse savings are visible above noise.
- **Estimated LOC:** ~700 Python → ~1,100 Rust.

### 5. Agent artifact content snapshot / tail reads

The previous pass listed this but did not rank it. That missed the current
selection/detail shape: `AgentDetail.update_display_immediate()` is now
header-only, but the debounced full detail update still calls the prompt panel,
which may glob and read prompt files, raw xprompt, response/chat Markdown,
live reply text, and timestamped reply chunks on first touch. Python caching
helps repeat selections; Rust can make first-touch IO and chunk slicing cheaper
without moving Rich rendering out of Python.

- **Rust crate location:** `crates/sase_core/src/agent_content/`.
- **Wire records:** `AgentContentRequestWire { artifacts_dir, response_path,
  attempt_number, include_prompt, include_raw_xprompt, include_response,
  include_chat, include_live_reply, include_timestamp_chunks, max_bytes }`,
  `AgentContentSnapshotWire { prompt, raw_xprompt, response, chat_response,
  live_reply, timestamp_chunks, file_sigs, truncated }`.
- **PyO3 surface:** `read_agent_content_snapshot(request) ->
  AgentContentSnapshotWire`, GIL-released. Keep `TailCache` semantics by
  passing the prior `(path, offset, size)` state and returning the next tail
  state, or leave live-reply tailing in Python for the first cut and port the
  immutable prompt/response/chat reads first.
- **Why it wins:** removes first-touch `os.listdir`, `os.stat`, full-file
  reads, JSONL timestamp parsing, and byte-offset slicing from the Textual
  detail update path. It also creates a backend surface reusable by a future
  web/mobile detail view.
- **FFI shape:** one call per selected agent detail refresh; no per-file FFI
  calls. Return text/chunks only, not Rich renderables.
- **Prereq before Phase-8-style deletion:** TUI trace covers
  `widget.prompt_panel.update_display` on cold, cached, and growing-live-reply
  scenarios; parity tests cover malformed timestamp JSONL, truncated UTF-8,
  missing prompt files, and attempt-pinned views.
- **Estimated LOC:** ~450 Python IO/cache logic → ~800 Rust + small Python
  adapter.

## What I deliberately did not recommend

- **Notification senders / priority** — pairs with #1, but the senders
  path is not on the blocking input path; do it as part of #1's package
  if scope allows, otherwise leave it.
- **History / telemetry JSONL** — write-mostly; the read paths are mostly
  detail-panel displays or offline history commands. Below the user-perceived
  bar for this migration.
- **xprompt / dynamic memory matcher** — flagged as low ROI in Phase 0
  and the data confirms it. Submit-time, sub-frame.
- **File watcher** — switching from `watchdog` to `notify` would be a
  robustness improvement, not a TUI-blocker fix; treat as a separate
  initiative.
- **VCS diff parsing** — Phase 5 closed this. Subprocess fork+exec
  dominates. Reopening only makes sense behind a `gix` epic against a
  measured workload, not as a port of more parsers.
- **ChangeSpec graph index as a standalone port** — the earlier ranking
  overstated this. `_get_changespec_graph_index()` already caches the index
  per `_all_changespecs` list identity; port it only as an add-on to the
  persistent query corpus handle, where the same Rust-side maps can serve
  both query `ancestor:` checks and relationship-panel accessors.
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
   corpus. For any future work near #3, start with the postmortem fixture:
   real TUI agents-tab refreshes, `sase agents status -j`, dismissed rows,
   retry/workflow rows, stale PIDs, and ordering. For #4, a home-tree fixture
   with attempt history, retry state, dismissed bundles, and tags. For #5,
   cold/cached/growing-live-reply prompt-panel fixtures.
3. **Design for FFI granularity first.** None of these should call Rust
   per row, per file, or per spec. The persistent-handle pattern in
   candidate #2 is the template.
4. **Add the regression floor entry before deleting Python.** Phase 7E's
   `tests/perf/baselines/phase7_regression_floor.json` is the contract;
   each new port should land its own floor row and a CI job that fails
   on regression.
5. **Sequence around the user's blocking path.** #1 first because it is
   the remaining backend primitive behind notification UI stalls and
   post-kill persistence. #2 next because every keystroke into the filter
   input pays `evaluate_query_many`. Do not treat the old #3 direct
   orchestration port as the next agents-refresh step; after the `sase-1p`
   revert, prefer #4 and #5-style cold slices or narrower helpers that leave
   Python composition in charge. #5 affects selection/detail latency rather
   than the list refresh itself.

## References

- `sdd/research/202604/rust_backend_migration.md` — Phases 0–8 history and
  forward plan.
- `sdd/research/202604/rust_backend_phase7_performance.md` — realised Phase 7
  numbers and gate-vs-realised verdicts.
- `sdd/research/202604/rust_backend_phase2_query_handoff.md` — wire-record
  contract for the query path; reused by candidate #2.
- `sdd/research/202604/sase_perf_research.md` — original TUI hot-path memo;
  candidates #4 and #5 still address items P2.7 and P4.10, while the old #3
  P2.5 direction now requires the postmortem constraints above.
- `sdd/research/202604/sase_perf_v2_research.md` — second-pass audit;
  candidate #1 closes out the remaining notification-store I/O finding
  after the kill immediate-stage fix.
- `plans/202604/rust_backend_phase8_phase8a_handoff.md` — Phase 8A
  operation disposition (what is shipped vs. deferred vs. unported).
- `plans/202604/rust_backend_phase8_phase8b_handoff.md` —
  `evaluate_query_many` deferral; the candidate-#2 design picks up where
  this left off.
