---
create_time: 2026-04-30 21:14:43
status: done
bead_id: sase-1n
prompt: sdd/prompts/202604/notification_rust_migration.md
---
# Notification Store Rust Migration Plan

## Background

The notification store is the top Rust migration candidate from `sdd/research/202604/rust_core_next_candidates.md`. Today
`src/sase/notifications/store.py` owns a JSONL file at `~/.sase/notifications/notifications.jsonl`. Every state mutation
(`mark_read`, `mark_dismissed`, `mark_muted`, `mark_snoozed`, `mark_all_read`, `expire_due_snoozes`, and bulk
agent-notification dismissal) loads the whole file, mutates Python dataclasses, and rewrites every row.

The performance issue is user-visible in the TUI notification modal, direct plan/question jumps, notification polling,
and post-kill badge refreshes. The correctness issue is more serious: `_rewrite_notifications()` opens the JSONL file
with `"w"` before taking `flock(LOCK_EX)`, so a concurrent reader/writer can observe an empty or partially rewritten
file.

This migration should follow the Phase 0-8 Rust-core playbook:

- Add golden/parity coverage before flipping call sites.
- Keep the core logic in `../sase-core/crates/sase_core` free of PyO3 types.
- Expose coarse PyO3 batch APIs from `../sase-core/crates/sase_core_py`.
- Route Python through a small facade that rehydrates typed Python records.
- Do not mix old Python file-lock semantics with new Rust rewrite semantics on the same store for longer than a single
  controlled flip phase.

Each phase below is designed for a distinct agent instance. Agents should run from the `sase_100` workspace, but Rust
changes land in sibling repo `../sase-core`. Every phase that changes code must end with relevant targeted tests plus
`just check` in `sase_100`; Rust-touching phases must also run the relevant `cargo test` commands in `../sase-core`.

## Goals

- Move notification JSONL parsing, append, and state mutation into Rust.
- Replace truncate-before-lock rewrites with lock-then-tempfile-rename semantics shared by append and rewrite.
- Preserve the existing JSONL file format and Python `Notification` public API.
- Add a snapshot/counts API so TUI count refreshes do not need to rehydrate and rescan every notification in Python.
- Move snooze expiry into the same Rust snapshot/update operation used by polling, so the event loop never performs the
  rewrite.
- Add concurrency and regression-floor coverage before deleting legacy Python store code.

## Non-Goals

- Do not port notification sender construction (`notify_*`) to Rust. Senders may continue to build Python `Notification`
  dataclasses and call `append_notification`.
- Do not move Rich/Textual rendering, notification modal layout, toast formatting, or action dispatch into Rust.
- Do not change the user-visible JSONL schema except by preserving existing optional/default fields (`read`,
  `dismissed`, `silent`, `muted`, `snooze_until`).
- Do not introduce runtime-specific behavior for Claude/Gemini/Codex; the store is runtime-neutral.

## Phase 1 - Contract, Fixtures, and Baselines

### Scope

Create the test and measurement contract before writing Rust store logic.

Python-side targets:

- `tests/test_notification_store.py`
- `tests/test_core_facade/` or a new `tests/test_core_notification_store.py`
- `tests/perf/` notification benchmark harnesses
- Optional fixture directory such as `tests/fixtures/notifications/`

Add fixtures that cover:

- Valid rows with every field set.
- Legacy rows missing `silent`, `muted`, and `snooze_until`.
- Invalid JSON lines and rows missing required fields.
- Dismissed rows, silent rows, muted rows, and snoozed rows.
- Priority actions/senders used by `sase.notifications.priority.is_priority`.
- Agent-linked notifications for `JumpToAgent`, `PlanApproval`, and `UserQuestion`, including timestamp normalization
  cases used by `_killing_utils.dismiss_notifications_for_agents`.

Add a synthetic corpus generator for at least 5k notifications. It should be usable by both Python and Rust tests
without depending on the user's real `~/.sase` tree.

### Tests and Measurements

- Preserve all existing `tests/test_notification_store.py` behavior.
- Add a concurrency test that demonstrates the desired final contract: concurrent append plus rewrite leaves a valid
  JSONL file with no empty-file observation and no lost rows. It can be marked as an expected failure or scoped to a
  helper that later phases enable, but the target behavior must be explicit.
- Add micro/end-to-end scripts for:
  - `notification_store_5k_load_snapshot`
  - `notification_store_5k_mark_dismissed_burst`
  - `notification_store_5k_mark_all_read`
  - `notification_store_append_plus_rewrite_concurrency`
- Document the current Python baseline numbers in the benchmark output or a small markdown note under `sdd/research/202604/`
  or `plans/202604/`.

### Deliverables

- Golden fixtures and benchmark harnesses only.
- No production routing changes.
- Clear handoff notes naming the exact fixture paths and benchmark commands.

### Validation

- `pytest tests/test_notification_store.py`
- Relevant new notification fixture tests.
- `just check`

## Phase 2 - Pure Rust Notification Store Core

### Scope

Add a Rust notification module to `../sase-core/crates/sase_core`.

Suggested files:

- `../sase-core/crates/sase_core/src/notifications/mod.rs`
- `../sase-core/crates/sase_core/src/notifications/wire.rs`
- `../sase-core/crates/sase_core/src/notifications/store.rs`
- `../sase-core/crates/sase_core/tests/notification_store_parity.rs`

Core wire records:

- `NotificationWire`
- `NotificationCountsWire { priority, rest, muted }`
- `NotificationStoreSnapshotWire { notifications, counts, expired_ids, stats }`
- `NotificationStateUpdateWire`
- `NotificationUpdateOutcomeWire`

The state update enum should cover:

- `mark_read`
- `mark_all_read`
- `mark_dismissed`
- `mark_many_dismissed`
- `mark_muted`
- `mark_snoozed`
- `expire_snoozes`
- `dismiss_matching_agents`
- `rewrite_all`

Implement read behavior to match Python:

- Missing file returns an empty snapshot.
- Blank lines are skipped.
- Invalid JSON lines are skipped and counted in stats.
- Rows missing required `id`, `timestamp`, or `sender` are skipped.
- Missing optional fields default to Python values.
- `include_dismissed=false` filters dismissed rows from `notifications` while counts are computed on the included active
  rows.

Implement write behavior:

- Use a stable sidecar lock file, for example `notifications.jsonl.lock`, for append and rewrite/update.
- For append: lock, open with append/create, write one JSON line, flush.
- For rewrite/update: lock, read the current file under the same lock, mutate in memory, write a temp file in the
  notification directory, flush/fsync as appropriate, then rename over the JSONL file.
- Never open the JSONL file with truncation before the lock is held.

Priority counts should mirror `src/sase/notifications/priority.py`.

### Tests

Rust tests should use the Phase 1 fixtures and cover:

- JSONL round trip and legacy default fields.
- Invalid/malformed rows are skipped without aborting the snapshot.
- Each state update mutates only the intended rows.
- `mark_muted(false)` clears `snooze_until`.
- `mark_snoozed` sets both `muted=true` and an ISO timestamp.
- `expire_snoozes` handles naive and timezone-aware timestamps the same way the Python path does.
- `dismiss_matching_agents` covers `JumpToAgent`, `PlanApproval`, and `UserQuestion`.
- Append plus rewrite concurrency preserves valid rows.

### Deliverables

- Pure Rust core and tests.
- `pub use` exports from `../sase-core/crates/sase_core/src/lib.rs`.
- No Python/PyO3 production route yet.

### Validation

- `cargo test -p sase_core notification`
- `cargo test -p sase_core`

## Phase 3 - PyO3 Bindings and Python Facade

### Scope

Expose the Rust core through `sase_core_rs`, then add a Python facade without flipping `src/sase/notifications/store.py`
yet.

Rust PyO3 targets:

- `../sase-core/crates/sase_core_py/src/lib.rs`

Python targets:

- `src/sase/core/notification_store_wire.py`
- `src/sase/core/notification_store_facade.py`
- `tests/test_core_facade/test_notification_store.py`

PyO3 functions:

- `read_notifications_snapshot(path: str, include_dismissed: bool, expire_due_snoozes: bool = False) -> dict`
- `apply_notification_state_update(path: str, update: dict) -> dict`
- `append_notification(path: str, notification: dict) -> dict`
- `rewrite_notifications(path: str, notifications: list[dict]) -> dict`

The PyO3 layer must release the GIL for filesystem work and return plain dict records. The Python facade should
rehydrate dicts into typed dataclasses or small wire dataclasses; production call sites should still use the old store
until Phase 4.

### Tests

- Python facade parity against Phase 1 fixtures.
- Stale binding error messages follow existing `sase.core.rust` conventions.
- Dict shape/schema version tests so a stale wheel fails clearly.
- Targeted PyO3 unit tests in `sase_core_py` for JSON shape round trips.

### Deliverables

- Importable `sase_core_rs` bindings for notification store operations.
- Python facade with no broad call-site flip.
- Handoff note identifying any schema-version constants and install steps.

### Validation

- `cargo test -p sase_core_py notification`
- `pytest tests/test_core_facade/test_notification_store.py`
- `just install`
- `just check`

## Phase 4 - Atomic Store API Flip

### Scope

Route the existing public store API through Rust in one phase so append and rewrite share the same lock file semantics.

Python targets:

- `src/sase/notifications/store.py`
- `src/sase/notifications/__init__.py` if new helpers are exported
- `tests/test_notification_store.py`
- `src/sase/ace/tui/actions/agents/_killing_utils.py` if bulk dismissal gets a store-level helper in this phase

Keep these public functions stable:

- `append_notification(n: Notification) -> None`
- `load_notifications(include_dismissed: bool = False) -> list[Notification]`
- `rewrite_notifications(notifications: list[Notification]) -> None`
- `mark_read(notification_id: str) -> bool`
- `mark_dismissed(notification_id: str) -> bool`
- `mark_muted(notification_id: str, muted: bool = True) -> bool`
- `mark_snoozed(notification_id: str, until: datetime) -> bool`
- `expire_due_snoozes(notifications: list[Notification]) -> list[Notification]`
- `mark_all_read() -> int`

Add one bulk helper if it materially simplifies call sites:

- `dismiss_notifications_matching_agents(agent_keys: list[dict]) -> int`

Important compatibility details:

- Preserve the process-local cache behavior where it still helps reads, but invalidate it after every Rust-backed write.
- `expire_due_snoozes(notifications)` must still mutate the passed-in Python notification objects for compatibility with
  `_poll_agent_completions`.
- `rewrite_notifications` must remain available for callers that already build a full list, but internally it should use
  Rust `rewrite_all`.
- Do not keep the old `_rewrite_notifications` implementation reachable after this phase; mixed write semantics are the
  biggest risk.

### Tests

- Existing notification store tests stay green.
- Add explicit tests that append, rewrite, and mark operations all call the Rust facade rather than Python file
  rewriting.
- Add the concurrency test from Phase 1 as a normal passing test.
- Add tests for cache invalidation after Rust writes.
- Add bulk agent dismissal tests if the new helper is introduced.

### Deliverables

- Production store functions routed through Rust.
- Legacy truncate-before-lock rewrite removed or made test-only unreachable.
- No TUI behavioral changes beyond faster/safer store calls.

### Validation

- `pytest tests/test_notification_store.py`
- `pytest tests/test_agent_kill_phase1_async_io.py tests/test_agent_kill_bulk.py`
- `cargo test -p sase_core notification`
- `just check`

## Phase 5 - TUI Snapshot and Count Integration

### Scope

Use Rust snapshot/count APIs in the TUI so common notification UI paths avoid rehydrating every row and rescanning
counts in Python.

Targets:

- `src/sase/ace/tui/actions/agents/_notifications.py`
- `src/sase/ace/tui/modals/notification_modal.py`
- `src/sase/ace/tui/modals/notification_modal_actions.py`
- `src/sase/ace/tui/widgets/notification_indicator.py` if needed
- Tests around notification modal actions, indicator counts, and polling

Introduce store-level helpers such as:

- `read_notification_snapshot(include_dismissed: bool = False, expire_due_snoozes: bool = False)`
- `get_unread_notification_counts() -> tuple[int, int, int]`

Then route:

- `_refresh_notification_count` and `_refresh_notification_count_async` through counts returned by Rust instead of
  `load_notifications()` plus Python filtering.
- `_poll_agent_completions` through one snapshot call with `expire_due_snoozes=True`, executed off the event loop. The
  returned `expired_ids`/expired rows should drive the snooze-expiry bell without a second load/rewrite.
- `_show_notification_modal` through the snapshot rows it actually needs.
- `_jump_to_agent_notification` through an unread snapshot, keeping action dispatch in Python.

Keep priority classification source-of-truth aligned with Rust. Either duplicate the small predicate with tests against
`is_priority`, or have the snapshot return priority flags/counts so Python does not need to recompute them for the
indicator.

### Tests

- Indicator count tests for priority/rest/muted/silent/dismissed combinations.
- Polling test proving snooze expiry does not call the old `expire_due_snoozes()` event-loop rewrite path.
- Modal-open and direct-jump tests still dispatch the same actions and preserve PlanApproval/UserQuestion unread
  semantics.
- Regression test that muted priority notifications count as muted, not active priority.

### Deliverables

- TUI count and polling paths consume Rust snapshot/counts.
- Notification modal remains Python/Textual, with unchanged UX.
- Handoff note listing any still-Python notification call sites and why.

### Validation

- `pytest tests/test_notification_indicator.py tests/test_notification_modal_actions.py tests/test_notification_modal_jump.py`
- Relevant `_notifications.py` tests if present or newly added.
- `just check`

## Phase 6 - Bulk Agent Notification Dismissal and Kill Path Cleanup

### Scope

Close the last high-volume store mutation path: dismissing notifications that reference killed/dismissed agents.

Targets:

- `src/sase/ace/tui/actions/agents/_killing_utils.py`
- `src/sase/ace/tui/actions/agents/_kill_persistence.py`
- `src/sase/ace/tui/actions/agents/_dismiss_persistence.py`
- Rust `dismiss_matching_agents` update from Phase 2
- Tests for kill/dismiss persistence and notification dismissal

Replace the Python load/mutate/rewrite loop in `dismiss_notifications_for_agents()` with a single Rust state update that
takes the relevant agent identities. Keep Python responsible for extracting agent identity fields and timestamp
normalization input; Rust should receive a small typed/bare wire list and perform the JSONL mutation in one locked
transaction.

This phase should also audit notification-related action paths for accidental double refreshes now that counts are
cheap:

- Bulk kill should still schedule one persistence task.
- Post-kill badge refresh should not serialize behind Python rewrite logic.
- Dismissed-done flows should use the same bulk helper.

### Tests

- `dismiss_notifications_for_agents()` parity for all supported action shapes.
- Bulk kill/dismiss tests prove one Rust mutation per persistence batch.
- Existing async-kill tests still prove no notification I/O on the immediate UI stage.
- Concurrency test with a bulk dismiss update racing an append.

### Deliverables

- No Python full-file rewrite loop remains in agent kill/dismiss notification cleanup.
- Bulk mutation count is observable in tests via facade patching.

### Validation

- `pytest tests/test_agent_kill_phase1_async_io.py tests/test_agent_kill_bulk.py tests/test_agent_kill_dismiss_fast_path.py`
- New targeted bulk-dismiss tests.
- `just check`

## Phase 7 - Regression Floor, Cleanup, and Deletion

### Scope

Only after Phases 4-6 are routed and green, remove compatibility scaffolding and lock in performance/correctness gates.

Targets:

- `tests/perf/baselines/phase7_regression_floor.json` or the current regression-floor successor file
- Notification benchmark harnesses from Phase 1
- `src/sase/notifications/store.py`
- `src/sase/core/notification_store_facade.py`
- `../sase-core` docs/README as needed

Tasks:

- Add regression-floor entries for:
  - `notification_store_5k_load_snapshot`
  - `notification_store_5k_mark_dismissed_burst`
  - `notification_modal_dismiss_burst`
  - `notification_store_append_plus_rewrite_concurrency`
- Remove dead Python parser/rewrite helpers and any opt-in/shadow code.
- Update comments/docstrings to state that `sase_core_rs` is the production store backend.
- Confirm all notification writes use the Rust lock-file/tempfile-rename path.
- Update sdd/research/plans handoff notes with measured before/after results.

Acceptance gates:

- The 5k mutation benchmarks are materially faster than the Phase 1 Python baseline. Treat a flat or slower result as a
  blocker unless there is a clear correctness-only justification.
- The concurrency test passes repeatedly.
- No production notification code opens `notifications.jsonl` with `"w"`.
- No TUI notification modal action performs Python JSONL parse/rewrite on the event loop.

### Tests

- Full notification test suite.
- Full TUI notification-related tests.
- Rust workspace tests.
- Regression-floor command used by this repo.

### Deliverables

- Dead Python store implementation removed.
- Performance floor committed.
- Final migration note with measured numbers and residual risks.

### Validation

- `cargo test --workspace` in `../sase-core`
- `just check` in `sase_100`
- Notification perf/regression command from the current perf harness

## Ordering and Handoff Rules

- Phases 1-3 must land in order.
- Phase 4 is the critical safety flip: append and rewrite must move together so there is no long-lived mixed-lock
  deployment.
- Phase 5 can start after Phase 4, and Phase 6 can start after Phase 4. If run concurrently, they must coordinate edits
  to `store.py` and `_notifications.py`.
- Phase 7 must be last.
- Each phase agent should include in its final handoff:
  - changed files in `sase_100` and `../sase-core`;
  - commands run and any failures;
  - remaining TODOs for the next phase;
  - whether `just install` was needed to refresh the editable Rust wheel.

## Risk Notes

- The largest behavioral risk is silent JSONL schema drift. Keep fixtures shared across Python and Rust tests.
- The largest correctness risk is mixed locking. Avoid partial production routing where Python append and Rust rewrite
  both write the same file with different locks.
- The largest performance risk is FFI shape. TUI paths should call Rust once per snapshot/update, not once per
  notification row.
- `expire_due_snoozes()` has a compatibility side effect: it mutates the already-loaded Python objects. Preserve that
  wrapper behavior until all call sites use snapshots directly.
- Priority counts duplicate a small Python predicate. Pin this with parity tests so red/gold/muted badge behavior does
  not drift.
