---
bead_id: sase-3e.1
tier: epic
legend_bead_id: sase-3e
status: done
---
# Plan: Rust Daemon Epic 1 Baseline, Contracts, and Compatibility Inventory

## Goal

Implement Epic 1 from `sdd/legends/202605/rust_daemon_indexed_projections_1.md` as a planning and scaffolding workstream
only. This epic must make the compatibility, fixture, performance, and daemon-contract baseline explicit before later
epics build or route production daemon behavior.

No phase in this plan should reroute a production command, ACE path, mobile route, provider/plugin path, or recovery
command to a daemon. Current source stores remain authoritative.

## Current Context

- The repo already has a broad compatibility inventory in
  `sdd/research/202605/rust_daemon_epic0_compatibility_inventory.md`.
- The legend calls this Epic 1, but the inventory document calls similar work "Epic 0". Treat that as existing research
  input, not as completed implementation.
- The sibling Rust workspace `../sase-core` owns shared backend/domain behavior. Any daemon wire structs, gateway
  contract snapshots, or Rust-side test fixtures belong there when they are reusable by CLI, ACE, editor, mobile, or
  future frontends.
- This checkout does not currently contain the out-of-order
  `sdd/epics/202605/rust_daemon_event_projection_core_epic1.md` or `sase_core/src/projection/` modules referenced by the
  inventory research. Future agents should not assume that work exists.
- Existing useful anchors:
  - `docs/architecture.md`
  - `docs/rust_backend.md`
  - `docs/perf_runbook.md`
  - `tests/perf/README.md`
  - `tests/perf/bench_tui_trace.py`
  - `tests/perf/bench_agent_scan.py`
  - `tests/perf/bench_agent_launch.py`
  - `tests/perf/bench_notification_store.py`
  - `tests/perf/bench_bead.py`
  - `tests/test_bead/golden/`
  - `tests/fixtures/notifications/`
  - `../sase-core/crates/sase_core/tests/fixtures/`
  - `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`

## Phase Model

Each phase below is intended for a distinct agent instance. Phases should be run in order unless the user explicitly
parallelizes read-only review work. Each phase must leave a short handoff note in its main deliverable describing what
is complete, what is intentionally deferred, and which validation command was run.

## Phase 1A: Compatibility Matrix and Gap Map

### Purpose

Turn the existing compatibility research into an Epic 1 artifact that later daemon, projection, and ACE agents can cite
as the behavioral contract.

### Primary Write Scope

- `sdd/research/202605/rust_daemon_epic1_compatibility_matrix.md`
- Optional small updates to docs that only add cross-links, if needed.

Do not modify memory files.

### Work

1. Reconcile `rust_daemon_epic0_compatibility_inventory.md` with the legend's Epic 1 deliverables.
2. Produce a matrix covering at least:
   - CLI commands and command families;
   - ACE ChangeSpecs, Agents, Notifications, Artifacts, AXE, grouping/filtering, revive/cleanup, logs;
   - axe scheduler/checks;
   - ChangeSpec stores and legacy `.gp` files;
   - agent artifact directories, explicit artifacts, dismissed identities, dismissed bundles;
   - notification JSONL and pending action stores;
   - bead stores and work-plan outputs;
   - workflow state, HITL files, and xprompt catalogs;
   - mobile gateway routes and editor helpers;
   - provider/plugin boundaries;
   - recovery, doctor, logs, and no-daemon commands.
3. Classify every row as one of:
   - unchanged;
   - daemon-read candidate;
   - daemon-write candidate;
   - host-adapter only;
   - deferred.
4. For each row, record:
   - source of truth;
   - current loader/mutator entry points;
   - direct fallback expectation;
   - likely later epic dependency;
   - fixture coverage status: existing, added by Phase 1B, or missing.
5. Add a "Do Not Move Yet" section listing behavior that must remain Python/host-owned for now: provider subprocesses,
   plugin execution, workflow script steps, VCS side effects, Textual rendering, editor protocol process, local file
   open/viewer actions, recovery commands.

### Acceptance Gate

- A later epic can determine from the matrix whether a behavior is unchanged, moved later, or intentionally deferred.
- The matrix explicitly says no production routing changed.
- Validation: documentation link check or focused markdown/lint command available in this repo. If no focused command is
  practical, run `just check` after `just install`.

## Phase 1B: Representative Fixture Corpus

### Purpose

Create portable golden source-store fixtures and normalized expected snapshots for every source family that later
projection and daemon-read work must match.

### Primary Write Scope

- `tests/fixtures/rust_daemon_epic1/`
- `tests/test_rust_daemon_epic1_fixtures.py`
- Optional fixture mirror or manifest under `../sase-core/crates/sase_core/tests/fixtures/daemon_epic1/` if Rust tests
  need direct access now.

### Work

1. Add a fixture manifest describing every fixture family, source paths, expected snapshot paths, and covered matrix
   rows.
2. Add hermetic fixtures for:
   - project `.sase` active/archive files;
   - legacy `.gp` active/archive files;
   - notification JSONL with unread, read, dismissed, snoozed, stale, and action-backed notifications;
   - pending action files, including current and legacy Telegram locations;
   - agent artifact trees with running, waiting/HITL, done, failed, killed/stale, retry, parent/child workflow, and
     missing/stale artifact cases;
   - explicit artifact metadata and file associations;
   - dismissed identities and dismissed bundle JSON, including legacy bundle layout where supported;
   - bead `issues.jsonl` and `config.json` covering hierarchy, deps, ready/blocked, ChangeSpec metadata, epic/legend
     metadata, model routing, and corrupt/legacy rows;
   - workflow `workflow_state.json`, prompt/script step markers, HITL request/response files, and recovery cases;
   - xprompt package/user/project catalog inputs and dynamic-memory-like entries;
   - prompt history, chat history, and file-reference history.
3. Prefer small, composable fixtures over one giant fixture tree. Include at least one "large-ish" fixture for perf
   harnesses to scale up from.
4. Add tests that load the fixtures through current Python/Rust facades and compare normalized JSON snapshots. The tests
   should prove the fixture corpus is valid, not implement daemon behavior.
5. Reuse existing fixture/golden material where it already covers the contract:
   - `tests/test_bead/golden/`
   - `tests/fixtures/notifications/`
   - `../sase-core/crates/sase_core/tests/fixtures/`

### Acceptance Gate

- Every matrix source-store family is covered by at least one fixture or explicitly listed as missing with a reason.
- Normalized expected snapshots are deterministic and stable under repeated test runs.
- No fixture depends on the developer's real `~/.sase`.

## Phase 1C: Command-Level and Hot-Path Performance Baselines

### Purpose

Extend existing performance harnesses so later daemon agents have concrete p50/p95 baselines and targets for cold CLI,
warm mocked-daemon, ACE, agent launch, and notification-action latency.

### Primary Write Scope

- `tests/perf/`
- `tests/perf/baselines/`
- `docs/perf_runbook.md` or `tests/perf/README.md` for usage notes.

### Work

1. Add a command-level CLI startup harness that measures cold subprocess latency for representative commands:
   - plain Python startup;
   - importing `sase.main.entry`;
   - `sase --help` or equivalent cheap parser route;
   - ChangeSpec read/search route;
   - notification list/show route;
   - bead list/show/ready route;
   - editor helper/catalog route if currently scriptable.
2. Add a mocked warm-daemon round-trip harness. It should measure the client/request framing target shape without
   requiring the real daemon:
   - local request serialization/deserialization;
   - one health request/response;
   - one paged list response;
   - one delta/event payload.
3. Extend or document existing ACE measurements for:
   - first useful paint;
   - j/k key-to-paint;
   - no-change refresh;
   - large history search;
   - large reply/detail selection.
4. Extend or document agent-launch measurements for:
   - launch fan-out planning/preparation;
   - parent-side sleeps;
   - fake spawn/write path;
   - notification emission/action latency where feasible.
5. Add JSON baseline output and comparison guidance. Keep thresholds advisory in Epic 1 unless the current harness
   already has stable regression floors.
6. Record aspirational daemon targets from the legend alongside measured current baselines:
   - warm daemon-backed CLI/editor queries: roughly 5-30 ms for common reads;
   - ACE shell first useful paint under 100 ms;
   - active indexed data under 250 ms on large local histories;
   - no-change refresh near 0 ms for later event-driven paths.

### Acceptance Gate

- A future epic can run one documented command to regenerate Epic 1 baseline JSON.
- Baselines include p50 and p95 where the harness has multiple runs.
- Harnesses are hermetic by default and only touch real `~/.sase` data behind an explicit flag.

## Phase 1D: Daemon Wire Versioning and Contract Snapshot Scaffolding

### Purpose

Define the local daemon API contract strategy before implementing the daemon transport or routing production reads.

### Primary Write Scope

- `../sase-core/crates/sase_core/src/` for shared local daemon wire types if useful immediately.
- `../sase-core/crates/sase_gateway/src/contract.rs`
- `../sase-core/crates/sase_gateway/src/wire.rs`
- `../sase-core/crates/sase_gateway/contracts/`
- Rust tests under `../sase-core/crates/sase_gateway/tests/` or crate-local tests.
- Optional Python docs/tests that read the contract snapshot.

### Work

1. Preserve the existing mobile `/api/v1` contract snapshot and add a separate local daemon contract snapshot. Do not
   blend mobile route compatibility with the local framed-JSON API.
2. Define a schema/versioning policy covering:
   - contract name;
   - schema version;
   - minimum/maximum compatible client version;
   - additive fields;
   - nullable fields;
   - enum compatibility;
   - deprecation/removal policy;
   - error shape;
   - snapshot and cursor identifiers;
   - no-daemon/fallback signaling.
3. Add initial local request/response shapes for contract testing only:
   - health;
   - capabilities/version;
   - mocked paged list request/response;
   - mocked event/delta/heartbeat record;
   - error response.
4. Shape the contract around the legend's future requirements:
   - pages and cursors;
   - snapshot IDs;
   - delta streams;
   - stable handles;
   - batch requests;
   - bounded payloads.
5. Add snapshot-generation tests that fail when the contract changes without intentional snapshot update.
6. Keep the implementation inert. Do not open a socket, auto-start a daemon, or reroute any caller.

### Acceptance Gate

- Existing mobile contract tests still pass.
- A new local daemon contract snapshot exists and is versioned separately.
- The contract explicitly states that production routing is not implemented by this phase.

## Phase 1E: Fixture/Perf/Contract Traceability and Readiness Review

### Purpose

Close Epic 1 by proving the matrix, fixtures, perf baselines, and wire contract point at each other and are ready for
Epic 2/3/4 agents.

### Primary Write Scope

- `sdd/research/202605/rust_daemon_epic1_readiness.md`
- Small cross-links in the Phase 1A-1D artifacts.

### Work

1. Create a readiness document with a traceability table:
   - compatibility matrix row;
   - fixture path;
   - normalized snapshot path;
   - perf harness or "not latency-critical";
   - contract surface if applicable;
   - later epic owner.
2. List gaps with severity:
   - blocking for Epic 2 event/projection work;
   - blocking for Epic 3 daemon transport work;
   - blocking for Epic 4 shadow indexers;
   - can defer until read/write routing epics.
3. Verify no production route changed by reviewing touched files and command/router diffs.
4. Run the focused test set added by earlier phases plus Rust contract tests if Phase 1D touched `../sase-core`.
5. Update the legend or create a short tale only if the user wants SDD progress captured beyond the plan artifacts.

### Acceptance Gate

- Every later epic has concrete fixture and baseline references or an explicit gap list.
- The readiness doc records which behavior is unchanged, intentionally moved later, or deferred.
- No production command is rerouted.

## Cross-Phase Validation Expectations

- If a phase changes this repo, run `just install` first if the workspace is stale, then run the narrowest relevant
  tests. Before handoff, run `just check` unless the user approves a narrower validation.
- If a phase changes `../sase-core`, run that repo's `just check` before handoff.
- Slow perf harnesses should not be added to the default fast test path unless they are bounded and stable.
- Fixture tests should be deterministic and should not read real home-directory state unless an explicit opt-in flag is
  passed.

## Risks and Constraints

- The existing "Epic 0" naming can confuse future agents. Phase 1A should state clearly that the legend's Epic 1 owns
  the baseline/contract gate regardless of earlier research names.
- Cross-repo work must respect the Rust core boundary: reusable backend contracts and shared wire records belong in
  `../sase-core`; Python-only harness glue and ACE measurements belong in this repo.
- Golden fixtures must avoid embedding developer-specific paths, hostnames, or secrets.
- The daemon contract must remain additive beside the current mobile gateway contract.
- Do not introduce runtime-specific branches for Claude, Gemini, Codex, Qwen, OpenCode, or plugin providers.

## Suggested Agent Assignment Order

1. Phase 1A agent: matrix and gap map.
2. Phase 1B agent: fixture corpus and normalized snapshots.
3. Phase 1C agent: perf baseline harnesses and docs.
4. Phase 1D agent: local daemon contract snapshot scaffolding in `../sase-core`.
5. Phase 1E agent: readiness review and traceability closure.

Phase 1B can begin after Phase 1A has a draft matrix. Phase 1C can start once Phase 1B has the fixture manifest, using
existing synthetic fixtures in the meantime. Phase 1D can start after Phase 1A identifies local API candidate surfaces.
Phase 1E should run last.
