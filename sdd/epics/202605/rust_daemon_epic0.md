---
create_time: 2026-05-13 15:27:52
status: wip
prompt: sdd/prompts/202605/rust_daemon_epic0.md
bead_id: sase-3e.2
tier: epic
legend_bead_id: sase-3e
---
# Plan: Epic 0 Baseline, Contracts, and Compatibility Inventory

## Context

Epic 0 from `sdd/legends/202605/rust_daemon_indexed_projections_1.md` is the prerequisite workstream for the Rust daemon
and indexed projection rebuild. Its job is to make the existing SASE behavior, source-store corpus, performance targets,
and daemon wire contract explicit before later epics change production routing.

This repo currently owns Python CLI/TUI orchestration, provider/plugin execution, workflow side effects, and Textual
rendering. Shared backend and deterministic data behavior belongs in the sibling Rust workspace
`../sase-core/crates/sase_core`, with `../sase-core/crates/sase_gateway` already providing the mobile gateway and an
existing route contract snapshot.

Important current assets to build on:

- `tests/perf/bench_tui_trace.py`, `tests/perf/bench_phase7_e2e.py`, `tests/perf/bench_agent_launch.py`,
  `tests/perf/bench_notification_store.py`, `tests/perf/bench_agent_scan.py`, and `tests/perf/bench_bead.py`.
- `tests/perf/fixtures.py` for in-memory ACE benchmark data.
- `tests/fixtures/notifications/store_contract.jsonl` and existing notification/pending-action parity tests.
- `tests/ace/tui/repro/fixtures/agents_tab_disappear_reappear_v1.json`.
- Existing Rust core surfaces for ChangeSpec parsing/query, notification store, bead reads/mutations, agent artifact
  scanning/indexing, agent archive, editor/xprompt catalog, and mobile host bridge wires.
- Existing gateway contract code in `../sase-core/crates/sase_gateway/src/contract.rs` and wire definitions in
  `../sase-core/crates/sase_gateway/src/wire.rs`.
- An Epic 1 plan already exists at `sdd/epics/202605/rust_daemon_event_projection_core_epic1.md`, and there is already
  some in-flight `../sase-core` projection work. Epic 0 should record and reconcile this out-of-order state rather than
  depending on it blindly.

## Goals

- Produce a compatibility matrix covering CLI, ACE, axe, ChangeSpecs, agents, artifacts, notifications, beads,
  workflows, mobile, editor helpers, providers, plugins, recovery commands, and direct/no-daemon fallbacks.
- Add representative golden source-store fixtures and expected behavior snapshots that later epics can use for parity
  and shadow-mode diffing.
- Extend performance harness coverage so later work has concrete cold/warm p50/p95 baselines and aspirational daemon
  targets.
- Define a daemon route/wire contract strategy, including local framed-JSON request/response, stream/delta shape, schema
  versioning, snapshot tests, and compatibility policy.
- Leave all production command behavior unchanged.

## Non-Goals

- Do not route any CLI, ACE, editor, mobile, bead, notification, ChangeSpec, or agent read/write through the new daemon.
- Do not implement event projection storage, file watching, daemon lifecycle, Unix sockets, or scheduler ownership here.
- Do not rewrite existing source stores or remove `.sase`, legacy `.gp`, JSONL, artifact, bead, workflow, or xprompt
  compatibility.
- Do not add runtime-specific assumptions. Claude, Gemini, Codex, Qwen, OpenCode, and future providers must remain
  treated as capability-equivalent host adapters.
- Do not modify memory files.

## Phase Split

Each phase is intended for a separate agent instance. Phases should land sequentially unless a later phase explicitly
states it can work against a prior phase's stable draft.

### Phase 0A: Compatibility Inventory and Behavior Matrix

Purpose: document the product contract before any daemon work is allowed to move behavior.

Primary write scope:

- `sdd/research/202605/rust_daemon_epic0_compatibility_inventory.md`
- optional support docs under `sdd/research/202605/`
- no production code changes

Tasks:

1. Inventory user-visible commands and surfaces:
   - `sase run`, multi-agent prompts, xprompts, workflows, plan/question/HITL, resume, retry, artifacts.
   - ACE tabs and modals for ChangeSpecs, Agents, Notifications, Artifacts, AXE, tags, grouping, filters, revive,
     cleanup, logs, and keyboard workflows.
   - Axe scheduling, hooks, mentors, workflow checks, cleanup, digests, and background automation.
   - ChangeSpec/VCS workflows, bead/SDD workflows, editor helpers, mobile gateway routes, providers, plugins, recovery
     and doctor commands.
2. For each surface, record:
   - current source stores and current loader/mutator entry points;
   - source-of-truth files versus rebuildable caches/indexes;
   - side effects that must stay in Python host adapters;
   - behavior that should remain unchanged, move to Rust core, move to the daemon, or be deferred;
   - current no-daemon/direct fallback expectation;
   - likely later epic dependency.
3. Reconcile current out-of-order state:
   - note that Epic 1 planning and some projection work already exist;
   - identify which Epic 0 artifacts Epic 1+ should retrofit into their tests.
4. Add explicit compatibility risks:
   - multi-machine `~/.sase` sync and host-local runtime state;
   - legacy `.gp` support;
   - dismissed-agent identities and archive bundles;
   - pending mobile/notification actions;
   - workflow HITL files and provider subprocess contracts.

Acceptance:

- The matrix is specific enough that later phase prompts can name exact current entry points and source stores.
- Every legend Epic 0 surface has one of: unchanged, daemon-read candidate, daemon-write candidate, host-adapter only,
  deferred.
- The document clearly states that no production routing has changed.

### Phase 0B: Golden Source-Store Fixtures and Behavior Snapshots

Purpose: create the durable corpus later projections and daemon shadow indexers will diff against.

Primary write scope:

- `tests/fixtures/rust_daemon_epic0/`
- `tests/test_rust_daemon_epic0_fixtures.py` or focused tests under existing fixture/parity areas
- `sdd/research/202605/rust_daemon_epic0_fixture_contract.md`

Fixture corpus:

- Project files:
  - modern `.sase` active/archive files;
  - legacy `.gp` active/archive files;
  - ChangeSpecs with parent/child edges, comments, hooks, mentors, timestamps, deltas, commits, CL/PR metadata,
    suffixes, submitted/archive/reverted cases, and malformed-but-tolerated sections where current behavior permits
    them.
- Notifications:
  - JSONL rows for unread/read/dismissed/snoozed/expired;
  - pending actions for plan, question, and HITL flows;
  - mobile attachment manifests and stale action cleanup cases.
- Agents and artifacts:
  - active running marker, done marker, waiting/question marker, failed/killed cases;
  - retry attempts, parent/child workflow edges, explicit artifacts, raw/submitted prompts, large reply snippets;
  - dismissed identities, dismissed bundles, revived bundle cases, stale/missing artifact dirs.
- Beads:
  - JSONL/config/SQLite-compatible store with dependencies, ready/blocked states, epic/legend/tale/task tiers,
    ChangeSpec metadata, model routing, work-plan outputs, import/export edge cases.
- Workflows and catalogs:
  - `workflow_state.json`, HITL request/response files, step transitions, retry/resume markers;
  - project/user xprompts, default xprompts, slash skills, dynamic memory/catalog inputs, file-history entries.

Tasks:

1. Add a fixture generator or clearly documented static fixture layout.
2. Add expected JSON snapshots emitted through existing Python facades and Rust bindings where available.
3. Add smoke tests proving fixtures remain parseable and current loaders produce stable normalized snapshots.
4. Redact or synthesize all paths, timestamps, tokens, and user-specific content so fixtures are portable.
5. Document the fixture contract and how later epics should add surface-specific expected snapshots without changing the
   source fixture corpus unnecessarily.

Acceptance:

- Fixtures cover all source-store families named in the legend Epic 0 deliverables.
- Fixture tests pass without requiring a live daemon, live LLM provider, real user `HOME`, network, tmux, or mobile
  device.
- Later Epic 1/Epic 3 agents can use the corpus for projection replay and shadow diff tests.

### Phase 0C: Performance Harnesses, Baselines, and Threshold Policy

Purpose: make current latency costs and daemon targets measurable before optimization begins.

Primary write scope:

- `tests/perf/bench_daemon_epic0.py` or focused additions to existing `tests/perf/` harnesses
- `tests/perf/baselines/rust_daemon_epic0*.json`
- `tests/perf/check_daemon_epic0_regression.py`
- `sdd/research/202605/rust_daemon_epic0_perf_baselines.md`

Measurements to capture:

- Cold Python CLI startup for representative commands:
  - minimal `sase --help` or equivalent parser path;
  - `sase run` startup to provider boundary using a deterministic no-network path;
  - `sase agents status -j`;
  - notification list/detail/action path;
  - bead list/ready/show;
  - editor helper/xprompt catalog command.
- Warm daemon round-trip target harness:
  - initially mocked/in-process or loopback-only;
  - measures serialization/deserialization and request dispatch shape without real daemon state.
- ACE responsiveness:
  - first useful paint;
  - j/k key-to-paint;
  - no-change refresh;
  - large history search/list;
  - large reply/detail select.
- Agent launch fan-out and notification action latency:
  - deterministic fake subprocess/provider;
  - no live LLM/network/provider credentials.

Tasks:

1. Reuse existing Phase 7 perf infrastructure and metadata conventions where possible.
2. Add command-level subprocess timing where import/startup cost matters.
3. Add synthetic workload sizes and, where practical, a documented manual home-tree recipe for real-history validation.
4. Record current p50/p95 and aspirational daemon targets separately. Initial aspirational targets should align with the
   legend: 5-30 ms warm common reads, ACE shell under 100 ms, indexed active data under 250 ms.
5. Add a checker with conservative smoke thresholds suitable for CI only if the numbers are stable. Otherwise, mark
   unstable measurements as manual or artifact-only.
6. Store raw artifacts in a stable location and summarize them in the research doc.

Acceptance:

- Every later epic can cite at least one baseline and target for the surface it changes.
- Benchmarks are deterministic enough for local comparison and do not call live providers.
- The research summary identifies which measurements are CI-enforceable and which are manual/diagnostic.

### Phase 0D: Daemon Route/Wire Contract Snapshot Scaffolding

Purpose: define the versioned API contract style before local daemon transports and read APIs are implemented.

Primary write scope:

- `../sase-core/crates/sase_gateway/src/contract.rs`
- `../sase-core/crates/sase_gateway/src/wire.rs` only for contract/version marker structs if needed
- `../sase-core/crates/sase_gateway/tests/` contract tests
- `../sase-core/crates/sase_gateway/contracts/` or another stable snapshot directory
- optional Python notes under `sdd/research/202605/rust_daemon_epic0_wire_contract.md`

Contract strategy:

- Keep the existing mobile `/api/v1` HTTP/SSE route contract intact.
- Add a local-daemon contract namespace that describes, but does not implement production routing yet:
  - framed JSON request/response over Unix socket or platform-local equivalent;
  - health/capabilities/version handshake;
  - snapshot/page request conventions;
  - delta stream envelope;
  - error envelope;
  - schema version and compatibility policy;
  - no-daemon fallback expectation for Python clients.
- Use shared serde structs and JSON snapshot tests so mobile and local contracts cannot drift silently.

Tasks:

1. Add or extend contract snapshot generation for local daemon API v0/v1 planning artifacts.
2. Define version marker structs/enums only as needed for compile-time snapshot tests. Do not implement socket serving,
   daemon lifecycle, storage, watchers, or command routing in this phase.
3. Add snapshot tests for:
   - schema version values;
   - optional-field/null policy;
   - route/request/response names;
   - error envelope;
   - delta/event envelope shape.
4. Document compatibility policy:
   - additive fields are allowed;
   - removing/renaming fields requires schema bump;
   - incompatible client/server versions must fail with actionable errors;
   - recovery commands must retain direct source-store access.
5. Record how later Epic 2/Epic 4 work should extend the snapshot as routes become real.

Acceptance:

- Existing mobile gateway contract tests continue to pass.
- A committed local daemon contract snapshot exists and is stable.
- The contract is explicit enough for later agents to implement lifecycle/transport/read APIs without inventing a new
  versioning scheme.
- No production client calls the local daemon contract yet.

### Phase 0E: Epic 0 Integration, Handoff Prompts, and Approval Package

Purpose: make the outputs consumable by the separate agents that will implement later epics.

Primary write scope:

- `sdd/research/202605/rust_daemon_epic0_handoff.md`
- updates to the Epic 0 plan or generated epic document if needed
- no production code routing changes

Tasks:

1. Verify all Epic 0 artifacts point at each other:
   - compatibility inventory;
   - fixture contract;
   - perf baseline summary and raw artifacts;
   - wire contract strategy/snapshot.
2. Add handoff guidance for later epics:
   - Epic 1 should retrofit projection tests onto the fixture snapshots.
   - Epic 2 should extend the local contract with real health/lifecycle/transport behavior.
   - Epic 3 should use fixture snapshots for shadow-index diffs.
   - Epic 4/Epic 8 should use perf baselines for read-path and ACE acceptance.
3. Create phase prompts for the next implementation agents if the local SDD workflow expects them.
4. Run appropriate checks:
   - focused fixture/perf/contract tests added by Epic 0;
   - `cargo test -p sase_gateway` for Rust gateway contract work when Phase 0D changes Rust;
   - `just check` for Python/SDD changes in this repo after `just install` if needed.
5. Record known gaps, unstable measurements, and deferred surfaces.

Acceptance:

- Epic 0 can be marked complete with no production command rerouted.
- Later workstreams have concrete fixtures, p50/p95 baselines, target thresholds, and route/wire compatibility policy.
- The final handoff calls out any already-landed Epic 1 projection code that lacks Epic 0 fixture coverage.

## Cross-Phase Rules

- Preserve source stores as source of truth. New snapshots and baselines are test artifacts, not replacement state.
- Keep fixture generation deterministic and portable. No absolute user paths in committed expected outputs.
- Prefer current facades and Rust bindings over duplicate parsers or ad hoc string parsing.
- Treat Python host adapters as the home for providers, plugins, subprocesses, workflow side effects, and UI rendering.
- Keep benchmark harnesses honest about process boundaries: subprocess when measuring CLI startup, in-process only when
  intentionally isolating UI or serialization work.
- If an agent discovers production behavior differs from the intended contract, update the inventory and fixture
  snapshots first; do not silently "fix" behavior as part of Epic 0.

## Final Acceptance Gates

- Compatibility matrix covers every surface named in the legend Epic 0 deliverables.
- Golden fixtures exist for project specs, notifications/pending actions, agents/artifacts/dismissals, beads, workflows,
  xprompts/catalogs, and recovery-relevant edge cases.
- Perf artifacts include cold Python startup, mocked warm daemon round-trip, ACE first paint/navigation/refresh/search,
  agent launch fan-out, and notification action latency.
- Daemon route/wire contract strategy has committed snapshot scaffolding and a documented version compatibility policy.
- No production command, ACE path, editor helper, mobile route, provider, plugin, or recovery command is rerouted.
