---
create_time: 2026-05-14 15:59:17
status: wip
prompt: sdd/prompts/202605/blazing_fast_ace_daemon.md
bead_id: sase-3i
tier: epic
---
# Blazing Fast ACE Daemon Read Plan

## Context

`aad.cld` and `aad.cdx` found two interacting failure modes in ACE daemon read-through:

1. When the local daemon is RPC-unhealthy, ACE pays the daemon timeout and then performs the direct read anyway. This
   made agents and ChangeSpecs roughly "direct mode plus ~1s" in the measured failing run.
2. When the daemon is healthy, ACE still issues too many foreground reads. Agents loops over every `~/.sase/projects/*`
   directory and every agent surface (`agent_active` and `agent_recent` by default). Notifications drains every page
   before first paint and then asks for counts. `read_or_fallback` also performs a capabilities RPC before each read.

There is a deeper Rust-side bottleneck: notification projection events currently store full notification snapshots for
rewrite/state-update events, and the read paths deserialize full notification JSON to compute filtered pages and counts.
That makes the daemon vulnerable to large event payloads, WAL growth, and long projection critical sections. Because
shared backend behavior belongs in `../sase-core`, the bold fix should move the expensive aggregation and compact read
models there instead of adding more Python-side workarounds.

The previously committed Python wire fix (`0bb6f21de`, omitting empty `data` for unit read surfaces) should be treated
as complete. This plan starts from the current `sase_102` workspace and sibling `../sase-core` checkout.

## Goals

- ACE daemon-backed startup must be faster than direct startup on a large real `~/.sase` tree.
- A saturated or rebuilding daemon must not make ACE slower than direct mode by more than one small probe budget.
- ACE first paint must use bounded reads only. Full notification or archive history should never block startup.
- Control-plane daemon RPCs (`capabilities`, basic `health`, status used by clients) must remain responsive while
  projection reads or indexing are slow.
- Perf gates should prevent default-enabling any ACE daemon surface unless daemon mode beats direct mode for that
  surface.

## Non-Goals

- Do not redesign the ACE UI. This is a data-path and projection-shape effort.
- Do not remove direct fallback. Direct mode remains the resilience baseline.
- Do not make runtime-specific behavior. All agents and providers must remain runtime-agnostic.
- Do not modify memory files.

## Phase 1: Fail Fast In Python, Then Measure

Owner: Python repo agent (`sase_102`).

Purpose: eliminate repeated timeout tax immediately and create a reliable measurement harness before larger backend work
lands.

Scope:

- Add a process-local daemon read session/circuit breaker in `src/sase/daemon/read_facade.py`.
  - Cache the capability set for the lifetime of one Python process or ACE startup session.
  - Cache a negative transport result after the first timeout/unavailable response.
  - Short-circuit remaining `read_or_fallback` calls to direct mode with a stable fallback reason such as
    `daemon_circuit_open`.
  - Keep explicit test clients isolated so unit tests can still assert request shape and fallback behavior
    deterministically.
- Make the client probe budget small for capability checks used only as routing gates. A bad daemon should cost tens of
  milliseconds once, not 1s per surface.
- Add diagnostics showing the circuit state in fallback metadata when `fallback_diagnostics` is enabled.
- Add a focused perf script or test helper that times:
  - direct ACE agents snapshot;
  - daemon ACE agents snapshot;
  - direct ChangeSpecs snapshot;
  - daemon ChangeSpecs snapshot;
  - notification count and first-page reads.

Acceptance:

- Unit tests prove only one capability/transport attempt is made after a timeout in an ACE startup-like sequence.
- Existing tests that inject fake clients continue to pass.
- The perf helper emits comparable JSON with direct vs daemon timings and fallback reasons.
- `just install` and `just check` pass in the Python workspace.

## Phase 2: Keep The Daemon Control Plane Responsive

Owner: Rust core/gateway agent (`../sase-core`).

Purpose: make health/capabilities/status cheap under load so clients can make routing decisions without getting stuck
behind projection work.

Scope:

- Audit `sase_gateway::local_transport` and `projection_service` for any control-plane path that can block on large
  projection reads or long DB locks.
- Keep `capabilities` purely in-memory. It should not wait for `ProjectionDb`.
- Keep basic `health(include_capabilities=false)` purely in-memory plus cached projection status.
- For detailed health, retain the existing timeout pattern but make the timeout short and ensure the response is still
  useful when diagnostics are unavailable.
- Add metrics and tests for control-plane latency while a blocking projection read holds the projection lock.
- Review socket accept/dispatch concurrency so one slow read does not starve capabilities/health clients.

Acceptance:

- Rust tests cover capabilities and basic health not waiting behind a blocked projection DB lock.
- A local stress script can hold or simulate a slow projection read while `capabilities` and basic health still return
  promptly.
- No read-model or event-log semantics change in this phase.

## Phase 3: Compact Notification Projection Events And Reads

Owner: Rust core/gateway agent (`../sase-core`).

Purpose: remove the huge notification payload source that made the daemon CPU-bound and WAL-heavy.

Scope:

- Replace full-snapshot notification state events with compact delta events where possible.
  - `notification.appended` should carry one notification.
  - read/dismiss/mute/snooze state changes should carry ids and changed state, not the full notification list.
  - full rewrite should remain available for rebuild/backfill but should be rare and intentionally named as a rewrite.
- Consider a migration/backfill strategy for older full-snapshot events.
  - Minimum acceptable approach: existing projections can replay old events, but new events are compact.
  - Better approach: add event-log compaction/checkpoint support for notification rewrites so old huge superseded
    payloads can be pruned or replaced by a compact checkpoint.
- Change notification counts to use SQL aggregates over indexed columns instead of deserializing every
  `notification_json`.
- Change notification list to filter/page in SQL first, deserialize only the returned page, and include counts from SQL
  aggregates.
- Add or verify indexes for notification list filters:
  - dismissed/read/silent/muted;
  - sender;
  - source order/timestamp;
  - FTS query path if search remains supported.
- Keep payload bounds meaningful: if a row/page is too large, return a bounded/truncated response instead of blocking
  startup with huge JSON.

Acceptance:

- Rust tests cover compact state-update events, old full-snapshot replay compatibility, SQL counts parity, and paged
  list parity.
- A synthetic large notification dataset shows counts and first page do not deserialize the entire store.
- Projection WAL growth for common read/dismiss/mute updates is proportional to changed ids, not total notification
  store size.

## Phase 4: Add A Daemon-Native ACE Agents Snapshot

Owner: Rust core/gateway agent (`../sase-core` first), then Python repo agent.

Purpose: replace project-count times surface-count RPC fan-out with one bounded global query.

Rust scope:

- Add a new read request/response, tentatively `ace_agent_snapshot`.
- Query active and recent agents globally across projects in one projection transaction.
- Preserve semantics ACE needs:
  - include hidden flag;
  - optional search query;
  - bounded limit;
  - stable cursor or next-page token;
  - snapshot id;
  - row handles sufficient for detail/artifact reads;
  - enough fields to build current `Agent` rows without filesystem fallback.
- Decide ordering explicitly:
  - active rows first by current ACE sort expectations;
  - recent rows by finished/timestamp;
  - deterministic tie-break by project/agent id.
- Avoid duplicates when an agent qualifies for multiple facets.

Python scope:

- Add `LocalDaemonReadMixin.ace_agent_snapshot`.
- Update `DaemonAgentsDataProvider._load_daemon_snapshot` to call the new global surface once.
- Keep old per-project reads as a compatibility fallback only when the daemon lacks the new capability/surface.
- Update rollout/capability mapping and tests.

Acceptance:

- Agents first snapshot uses one read RPC after capability cache warmup.
- Tests prove no per-project loop occurs when the daemon supports `ace_agent_snapshot`.
- Direct fallback remains correct for older daemons.
- Large-project fixture shows daemon agents startup beats direct agents startup.

## Phase 5: Bound ACE Notification Startup

Owner: Python repo agent, with Rust support if Phase 3 did not already provide the exact response shape.

Purpose: make ACE notification startup read one page plus counts, never full history.

Scope:

- Replace `daemon_notification_snapshot` startup behavior with a bounded first-page read.
- Use counts included in `notification_list` when available; otherwise do one `notification_counts` call through the
  cached/circuit-broken facade.
- Defer full notification history to explicit modal pagination or background refresh.
- Do not expire snoozes by scanning all notifications on first paint. Move due-snooze expiration to a background/store
  mutation path or a bounded daemon-side operation.
- Align direct and daemon provider semantics so direct mode also avoids startup-wide notification scans where possible.

Acceptance:

- Tests prove startup reads at most one notification list page.
- Counts remain correct for the badge.
- Opening notification detail or scrolling loads additional data on demand.
- ACE first paint with thousands of notifications is bounded.

## Phase 6: Batch Or Parallelize Remaining Startup Reads

Owner: Python repo agent.

Purpose: remove avoidable serial foreground latency once backend read shapes are fixed.

Scope:

- Share one `LocalDaemonClient` and one read-session/capability cache across ACE providers during startup.
- Where independent startup reads remain, either:
  - use daemon `batch` for multiple small read requests; or
  - run direct fallback loaders off the foreground paint path where ACE architecture permits.
- Keep provider boundaries intact, but avoid each provider constructing a fresh client and re-probing capabilities.
- Ensure fallback behavior is coherent: one open circuit should route all providers direct without each paying its own
  timeout.

Acceptance:

- ACE daemon startup request count is visible in tests or trace output.
- With agents, ChangeSpecs, notifications, artifacts, and archive/search enabled, startup does not perform more than the
  expected bounded request count.
- No UI regressions in existing ACE provider tests.

## Phase 7: Rollout Policy And Performance Gates

Owner: Python repo agent, with benchmark data from Rust/Python phases.

Purpose: prevent this regression class from returning.

Scope:

- Make ACE daemon surface defaults conditional on explicit M2 perf gates, or temporarily revert ACE surfaces in
  `src/sase/default_config.yml` to disabled until gates are satisfied.
- Update `tests/perf/test_ace_ui_virtualization_rollout.py` or adjacent gate helpers with concrete budgets:
  - ACE agents first daemon snapshot p95 below direct p95 and below an absolute target.
  - ACE notifications first page/count p95 below direct p95 and below an absolute target.
  - Open-circuit fallback adds at most one small probe budget across all enabled surfaces.
- Add a benchmark artifact workflow for real `~/.sase/projects` shape and synthetic large-notification shape.
- Update rollout diagnostics to report request count, circuit state, fallback reason, and whether each ACE surface
  passed its perf gate.

Acceptance:

- Default enablement is blocked if gates are missing or failing.
- Rollout diagnostics explain why ACE daemon reads are disabled or safe to enable.
- Benchmarks can be run by future agents without manually reconstructing the `aad.cld`/`aad.cdx` investigation.

## Phase 8: Re-Enable One Surface At A Time

Owner: final validation agent.

Purpose: turn performance work into a safe default user experience.

Sequence:

1. Enable daemon ChangeSpecs first if already faster and bounded.
2. Enable daemon notifications after Phase 3 and Phase 5 gates pass.
3. Enable daemon agents after `ace_agent_snapshot` gates pass.
4. Enable artifacts/detail only after selected-agent detail latency is bounded.
5. Enable archive/search only after global search/archive pagination has explicit budgets.

Acceptance:

- `sase daemon status --json` returns quickly with a healthy daemon.
- `sase daemon rollout --json` shows all enabled ACE surfaces have required gates.
- Real ACE startup with all enabled surfaces is measurably faster than direct mode.
- If the daemon is killed, wedged, or rebuilding, ACE startup falls back with only one small probe penalty.

## Suggested Agent Ordering

1. Phase 1 Python fast-fail and benchmark harness.
2. Phase 2 Rust control-plane responsiveness.
3. Phase 3 Rust notification compaction and SQL reads.
4. Phase 4 Rust global ACE agents read.
5. Phase 4 Python adapter for global ACE agents read.
6. Phase 5 Python bounded notification startup.
7. Phase 6 Python startup batching/session sharing.
8. Phase 7 and Phase 8 rollout gates, diagnostics, and staged enablement.

Phases 2 and 3 can run in parallel if their agents coordinate on
`../sase-core/crates/sase_gateway/src/local_transport.rs` and notification projection files. Phase 4 Rust should wait
until Phase 2 establishes the control-plane behavior, but it does not need to wait for Phase 3 unless both agents touch
common wire exports. Python phases after Phase 1 should wait for the corresponding Rust wire shape to land.

## Verification Matrix

- Python unit tests:
  - `pytest tests/test_daemon_read_facade.py -q`
  - `pytest tests/ace/tui/test_agents_data_provider.py tests/test_notification_tui_daemon_provider.py -q`
- Python full check:
  - `just install`
  - `just check`
- Rust targeted tests:
  - `cargo test -p sase_gateway local_transport`
  - `cargo test -p sase_core projections::notifications`
  - `cargo test -p sase_core projections::agents`
- Manual diagnostics:
  - `sase daemon status --json`
  - `sase daemon rollout --json`
  - run the new ACE direct-vs-daemon perf helper with daemon healthy, daemon stopped, and daemon wedged/rebuilding.

## Risks

- Notification event compaction changes replay semantics. Keep old event replay support and add parity tests before
  changing writers.
- A global agents snapshot may subtly change ordering or child visibility. Encode the intended ordering and row-handle
  contract in tests before replacing the Python loop.
- Disabling ACE daemon defaults may look like backing away from daemon rollout, but it is the right product behavior
  until the daemon path is faster by construction.
- Batch requests reduce socket round trips but can hide server-side N+1 work. Prefer daemon-native global projection
  reads for hot ACE startup paths.
