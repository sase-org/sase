---
create_time: 2026-05-14 10:22:19
status: proposed
legend_bead_id: sase-3e
tier: epic
epic_number: 11
source: sdd/legends/202605/rust_daemon_indexed_projections_1.md
prompt: sdd/prompts/202605/rust_daemon_epic11_rollout_controls.md
---

# Epic 11 Plan - Release Sequencing and Rollout Controls

## Source

This plan implements Epic 11, "Release Sequencing and Rollout Controls", from
`sdd/legends/202605/rust_daemon_indexed_projections_1.md`.

Epic 11 purpose: make adoption of the Rust daemon and indexed projections incremental, observable, and reversible.

## Current State

The daemon rebuild is already partially planned and implemented across prior epics:

- `../sase-core/crates/sase_core/src/projections/` contains event-backed projection modules, migrations, replay,
  rebuild, maintenance, read wires, and mutation/scheduler records.
- `../sase-core/crates/sase_gateway` contains local daemon lifecycle, framed JSON v1 transport, contract snapshots,
  capability advertising, projection/indexing services, host bridge scaffolding, and mobile gateway routes.
- this repo contains `src/sase/daemon/` client, read/write/scheduler facades, fallback helpers, path/layout helpers, and
  config readers.
- `src/sase/default_config.yml` already has daemon rollout knobs:
  - process paths and mobile HTTP disablement;
  - provider-host modes;
  - scheduler launch/lifecycle/axe modes;
  - read-through global and per-surface switches;
  - ACE daemon surfaces disabled by default.
- `src/sase/daemon/constants.py` and `../sase-core/crates/sase_gateway/src/wire.rs` currently pin local daemon wire
  schema version 1.
- Existing rollout gate work appears in prior epic plans:
  - Epic 5 Phase 5I for read rollout and perf gates.
  - Epic 6 Phase 6H for write rollout, doctor repair, and source-export compatibility.
  - Epic 7 Phase 7H handoff for scheduler rollout gates.
  - Epic 8 Phase 8H for provider-host rollout modes.
  - Epic 9 Phase 9F for ACE virtualization perf gates and default policy.
  - Epic 10 for sync, recovery, storage layout, doctor, rebuild, backup, and restore operations.

Epic 11 should not replace those phase-specific gates. It should centralize release state, compatibility checks,
milestone promotion policy, default-flip safeguards, and user-facing rollback behavior across them.

## Goals

- Define one rollout vocabulary shared by CLI, ACE, daemon reads, daemon writes, scheduler, provider host, mobile, and
  recovery commands.
- Make daemon adoption phaseable by milestone:
  - M0: daemon can shadow-index and report diffs.
  - M1: daemon read APIs power selected CLI/editor commands.
  - M2: ACE reads from daemon for Agents/Notifications/ChangeSpecs.
  - M3: selected writes move to daemon with source export.
  - M4: scheduler/launch/workflow state becomes daemon-owned.
  - M5: Python is provider/plugin/workflow host plus compatibility fallback.
- Ensure every milestone has explicit opt-out, fallback, parity, performance, recovery, and schema-compatibility gates.
- Prevent accidental default enablement for surfaces without corresponding CI/perf/parity coverage.
- Give users and release operators actionable diagnostics when daemon mode is unavailable, incompatible, degraded, or
  intentionally disabled.
- Keep all authoritative migrations preceded by shadow parity and reversible fallback.

## Non-Goals

- Do not implement the storage substrate, daemon transport, shadow indexers, read APIs, write APIs, scheduler, provider
  host, ACE virtualization, or recovery tools themselves; those belong to Epics 2-10.
- Do not delete current source stores, JSONL files, `.sase`/`.gp` files, artifact directories, or direct Python fallback
  paths.
- Do not make SQLite projections the sole source of truth.
- Do not flip every default in one phase.
- Do not introduce agent-runtime-specific rollout behavior. Claude, Gemini, Codex, Qwen, opencode, and future runtimes
  must use the same rollout gates.

## Cross-Cutting Design

Introduce a small rollout-control layer that composes existing feature flags rather than hiding them:

- A typed milestone model with `disabled`, `shadow`, `read_through`, `write_through`, and `daemon_authoritative` states.
  The exact persisted spelling may map to existing per-surface strings such as `direct`, `shadow`, `daemon`,
  `host-preferred`, and `host-required`, but the user-facing diagnostics should explain them consistently.
- A surface registry that records, for each daemon surface:
  - owner epic and minimum milestone;
  - config keys and environment overrides;
  - daemon capabilities required;
  - schema versions required;
  - direct fallback availability;
  - parity gate names;
  - perf gate names;
  - recovery commands;
  - whether default enablement is allowed.
- A compatibility handshake:
  - Python package version and supported local daemon wire schema range.
  - `sase_core_rs` package version and projection/read/write schema versions.
  - gateway package/build version and supported client schema range.
  - typed `unsupported_client_version`, `unsupported_server_version`, and `projection_schema_mismatch` errors with exact
    upgrade/rebuild/fallback guidance.
- CI gates that fail when defaults are enabled ahead of coverage:
  - default config validation;
  - contract snapshot checks;
  - daemon/direct parity tests;
  - read/write/scheduler/ACE perf target registry checks;
  - mobile gateway contract snapshots;
  - no-daemon recovery tests.
- Release reports that summarize current milestone readiness without requiring operators to inspect many test modules.

## Phase 11A - Rollout Registry and Config Inventory

Owner: one agent.

Purpose: establish a single source of truth for rollout surfaces, modes, defaults, and prerequisites.

Primary write scope:

- new rollout module under `src/sase/daemon/` or `src/sase/release/`
- `src/sase/default_config.yml`
- focused config tests under `tests/`
- SDD/docs notes only if needed to explain the registry

Deliverables:

- Add typed rollout surface records for:
  - daemon process disabled/enabled/shadow availability;
  - shadow indexing and diff diagnostics;
  - CLI/editor reads by surface;
  - ACE reads by surface;
  - writes by surface;
  - scheduler launch/lifecycle/axe;
  - provider-host operation families;
  - mobile gateway contract dependence;
  - recovery/doctor/rebuild operations.
- Map each record to existing config keys and environment overrides such as `SASE_NO_DAEMON`, `SASE_DAEMON_READS`,
  `SASE_DAEMON_FORCE_DIRECT`, per-surface read env vars, and scheduler/provider-host modes.
- Add default policy metadata:
  - default-off surfaces;
  - default-on read surfaces that already have gates;
  - opt-in ACE surfaces;
  - direct-only fallback surfaces;
  - future authoritative-only candidates.
- Add tests proving the registry matches `src/sase/default_config.yml` and existing helper constants such as daemon read
  surface groups and scheduler modes.
- No default behavior change unless the registry exposes a mismatch that is already unsafe; in that case, make the
  conservative direct/fallback behavior explicit.

Acceptance gates:

- Tests fail when a daemon surface exists in config but not in the rollout registry, or vice versa.
- Tests fail when an ACE daemon surface is default-enabled without an explicit gate record.
- All rollout modes are runtime-agnostic.
- `--no-daemon`/`SASE_NO_DAEMON` remains the top-level escape hatch for daemon reads and writes.

Suggested phase prompt:

> Implement Phase 11A from `sase_plan_rust_daemon_epic11_rollout_controls.md`: add the rollout surface registry and
> config inventory tests. Do not flip behavior defaults beyond conservative corrections required by the registry.

## Phase 11B - Version Compatibility and Handshake

Owner: one agent after Phase 11A.

Purpose: make client/server/schema compatibility explicit before more surfaces become default-enabled.

Primary write scope:

- `src/sase/daemon/constants.py`
- `src/sase/daemon/client.py`
- compatibility helpers under `src/sase/daemon/` or `src/sase/core/`
- `../sase-core/crates/sase_gateway/src/{wire.rs,local_transport.rs,contract.rs}`
- `../sase-core/crates/sase_gateway/contracts/local_daemon/v1/local_daemon_v1.json`
- `../sase-core/crates/sase_core/src/projections/` schema/version exports if needed
- tests in both repos

Deliverables:

- Add explicit Python-supported local daemon schema range instead of a single unqualified constant where appropriate.
- Include Python client version, supported schema range, and optional `sase_core_rs` version in daemon request metadata
  or initial health/capabilities negotiation.
- Extend daemon health/capabilities responses with:
  - daemon package/build version;
  - supported local daemon client schema range;
  - projection schema/read/write schema versions;
  - storage migration state;
  - degraded/rebuild-required status.
- Add typed compatibility errors with fallback guidance:
  - client too old;
  - daemon too old;
  - projection schema too old/new;
  - `sase_core_rs` package outside supported range;
  - mobile contract unavailable or mismatched.
- Add tests for old/new client envelopes, schema mismatch, fallbackable direct-read/write paths, and actionable error
  messages.

Acceptance gates:

- Incompatible clients are rejected before a surface mutation or read is attempted.
- Fallbackable incompatibilities produce direct fallback metadata where a direct source path exists.
- Non-fallbackable incompatibilities name a repair action such as upgrade, restart daemon, rebuild projections, or use
  `SASE_NO_DAEMON=1`.
- Contract snapshots record all compatibility fields.

Suggested phase prompt:

> Implement Phase 11B from `sase_plan_rust_daemon_epic11_rollout_controls.md`: add explicit local daemon
> client/server/projection compatibility negotiation, typed mismatch errors, and contract tests.

## Phase 11C - Milestone Gate Model and CI Aggregation

Owner: one agent after Phase 11A. Can run in parallel with Phase 11B if write scopes stay disjoint.

Purpose: centralize readiness gates without moving ownership away from the implementation epics.

Primary write scope:

- rollout registry from Phase 11A
- `tests/perf/` gate registries
- Python tests under `tests/`
- CI workflow updates only if a new explicit job or check invocation is needed
- optional helper scripts under `tools/`

Deliverables:

- Add milestone records M0-M5 that enumerate required gates:
  - required capabilities;
  - required contract snapshots;
  - required parity tests;
  - required perf target names;
  - required doctor/rebuild/recovery checks;
  - required docs/runbook links.
- Add a testable aggregator that can answer:
  - which milestone is fully covered by tests;
  - which surfaces are eligible for default enablement;
  - which surfaces are blocked and why;
  - whether config defaults violate gate policy.
- Connect existing gate modules:
  - Epic 5 daemon read rollout perf gates.
  - Epic 7 scheduler rollout gates.
  - Epic 9 ACE virtualization perf gates.
  - Epic 10 recovery/sync gates.
  - write-through gates from Epic 6 once present.
- Add CI/default tests that fail when a surface is default-enabled without a matching gate set.
- Keep slow/soak benchmarks runnable but not necessarily part of default `just check`; default tests should validate
  gate names, policy, and sample/fake measurements.

Acceptance gates:

- A missing parity/perf/recovery gate blocks default enablement in tests.
- The milestone model can represent partial readiness without implying a default flip.
- CI can validate policy quickly, while longer perf/soak jobs remain opt-in or workflow-specific.

Suggested phase prompt:

> Implement Phase 11C from `sase_plan_rust_daemon_epic11_rollout_controls.md`: add the M0-M5 gate aggregator and tests
> that prevent ungated default enablement.

## Phase 11D - User-Facing Rollout Diagnostics

Owner: one agent after Phases 11A-11C.

Purpose: expose the rollout state in commands and diagnostics that users and release operators can act on.

Primary write scope:

- `src/sase/main/parser_daemon.py` or a focused daemon/release CLI module
- rollout registry and gate aggregator
- daemon client/facade diagnostics
- docs/help text
- tests under `tests/`

Deliverables:

- Add or extend a user-facing diagnostic command, for example `sase daemon rollout`, `sase daemon status --rollout`, or
  equivalent existing command output.
- Report:
  - current effective mode per surface;
  - config source and env override that selected the mode;
  - daemon capabilities observed;
  - compatibility status;
  - parity/diff status when available;
  - perf gate status when a benchmark report is supplied;
  - fallback path and recovery command for each blocked surface.
- Add JSON output suitable for CI/release automation.
- Add concise text output suitable for normal CLI use.
- Ensure diagnostics can run when:
  - daemon is stopped;
  - daemon is incompatible;
  - projections are missing/corrupt;
  - source stores are still directly readable.

Acceptance gates:

- Diagnostics never require Textual imports or plugin discovery on startup-sensitive paths.
- `SASE_NO_DAEMON=1` and `--no-daemon` produce an explicit disabled state, not a confusing daemon failure.
- Users can see exactly how to disable, rebuild, verify, diff, restart, or upgrade.

Suggested phase prompt:

> Implement Phase 11D from `sase_plan_rust_daemon_epic11_rollout_controls.md`: add user-facing rollout diagnostics for
> effective modes, capabilities, compatibility, gates, and recovery actions.

## Phase 11E - M0/M1 Read Rollout Hardening

Owner: one integration agent after Epic 4 shadow indexing and Epic 5 daemon reads are stable enough for the selected
surfaces. This phase should start only after Phases 11A-11D exist.

Purpose: make the first two milestones shippable and reversible.

Primary write scope:

- rollout registry/gates
- read facade fallback tests
- daemon diff/verify command tests
- selected CLI/editor read tests
- docs/runbook updates
- minimal fixes to read config/facades if gates expose gaps

Deliverables:

- Mark M0 readiness only when daemon shadow indexing can rebuild, verify, and diff against source stores without
  affecting production behavior.
- Mark M1 readiness only for selected CLI/editor read surfaces that have:
  - daemon capability advertisement;
  - direct fallback;
  - byte-compatible or intentionally documented output differences;
  - p95 warm-read perf gates;
  - projection rebuild/verify/diff recovery.
- Add end-to-end tests that run:
  - daemon unavailable fallback;
  - incompatible daemon fallback or actionable failure;
  - projection degraded fallback;
  - `--no-daemon`/`SASE_NO_DAEMON`;
  - successful daemon read for each default-enabled M1 surface.
- Keep non-ready surfaces opt-in or direct-only.

Acceptance gates:

- M0 and M1 can be independently disabled.
- No milestone requires deleting existing source state.
- A user can recover from projection loss with documented commands.
- Default-enabled read surfaces are exactly those allowed by the gate model.

Suggested phase prompt:

> Implement Phase 11E from `sase_plan_rust_daemon_epic11_rollout_controls.md`: harden M0/M1 shadow and selected
> CLI/editor read rollout with end-to-end fallback, compatibility, parity, perf, and recovery gates.

## Phase 11F - M2 ACE Rollout Hardening

Owner: one integration agent after Epic 9 surface work and Phase 11E.

Purpose: govern ACE daemon-backed reads without regressing the keyboard-first TUI.

Primary write scope:

- ACE data-provider rollout config
- ACE perf/trace tests
- rollout registry/gates
- selected ACE provider fallback tests
- docs/runbook updates
- minimal fixes to ACE daemon provider code if gates expose gaps

Deliverables:

- Mark M2 readiness per ACE surface, not globally.
- Require for each promoted ACE surface:
  - page/snapshot/delta or bounded refresh contract;
  - no UI-thread blocking daemon calls;
  - direct-loader fallback;
  - no-change refresh avoids broad source-store reloads;
  - j/k key-to-paint and first indexed snapshot gates;
  - projection degraded/incompatible fallback tests;
  - selection/detail stale-load cancellation behavior where relevant.
- Keep `ace_agents`, `ace_changespecs`, `ace_notifications`, `ace_artifacts`, and `ace_archive_search` independently
  gateable.
- Add tests that prevent ACE daemon defaults from flipping before their perf/parity gates are registered and passing.

Acceptance gates:

- ACE remains functional with daemon unavailable.
- Default-enabled ACE surfaces cannot trigger broad disk hydration during no-change refresh.
- Config can roll back one ACE surface without disabling unrelated CLI daemon reads.

Suggested phase prompt:

> Implement Phase 11F from `sase_plan_rust_daemon_epic11_rollout_controls.md`: harden M2 ACE daemon-read rollout with
> per-surface gates, trace assertions, fallback tests, and rollback-safe defaults.

## Phase 11G - M3/M4 Write and Scheduler Rollout Hardening

Owner: one integration agent after Epic 6 write-through phases and Epic 7 scheduler phases are stable enough for the
selected surfaces.

Purpose: make state-changing daemon modes safe to promote and easy to roll back.

Primary write scope:

- write facade/config tests
- scheduler config/fallback tests
- daemon doctor/rebuild/retry tests
- rollout registry/gates
- contract snapshots if write/scheduler compatibility fields change
- docs/runbook updates
- minimal fixes to write/scheduler rollout helpers if gates expose gaps

Deliverables:

- Mark M3 readiness per write surface only when:
  - read parity exists for the same surface;
  - daemon write capability is advertised;
  - idempotency and stale-source conflict tests pass;
  - source-export outbox recovery tests pass;
  - direct fallback remains available for rollout modes that promise fallback;
  - doctor can report or repair pending exports.
- Mark M4 readiness per scheduler/workflow surface only when:
  - queued/running/waiting/completed state survives daemon restart;
  - direct/shadow/daemon scheduler modes are tested;
  - launch fan-out does not block ACE/mobile/CLI callers;
  - kill/dismiss/cleanup fallback semantics are explicit;
  - host IPC/provider execution failures do not corrupt daemon state.
- Add rollback tests:
  - daemon write succeeds then process restarts;
  - daemon write crashes before source export and doctor repairs;
  - daemon scheduler unavailable falls back or reports non-fallbackable action depending on mode;
  - mode returns to direct without losing source-store readability.

Acceptance gates:

- No write/scheduler surface can become daemon-authoritative before shadow/read parity and recovery gates pass.
- Retried writes are idempotent.
- Rolling back to direct mode leaves existing source files usable.
- User-facing errors name the repair command or the opt-out command.

Suggested phase prompt:

> Implement Phase 11G from `sase_plan_rust_daemon_epic11_rollout_controls.md`: harden M3/M4 write-through and scheduler
> rollout with idempotency, source-export repair, daemon restart, fallback, and rollback tests.

## Phase 11H - M5 Provider Host and Release Closeout

Owner: one final integration/release agent after Epic 8 and Phases 11E-11G.

Purpose: close the rollout epic with the final compatibility posture: Python as provider/plugin/workflow host plus
direct fallback where retained.

Primary write scope:

- provider-host rollout registry/gates
- host manifest/capability diagnostics
- release docs/runbook
- packaging/version checks
- CI/release workflow checks if needed
- SDD closeout notes

Deliverables:

- Mark M5 readiness only when provider/plugin/workflow host routing has:
  - manifest/capability checks;
  - timeout/cancellation/resource diagnostics;
  - direct fallback where promised;
  - daemon-authoritative restrictions for side effects;
  - tests proving hot read commands avoid plugin imports.
- Add a release checklist generated from or aligned with the rollout registry:
  - current defaults;
  - supported schema ranges;
  - migration/rebuild steps;
  - rollback commands;
  - known opt-in surfaces;
  - required CI/perf/soak evidence.
- Update docs/runbook so users understand:
  - how to disable daemon behavior globally;
  - how to disable or enable one surface;
  - when to run rebuild/verify/diff/doctor;
  - what version mismatch errors mean;
  - how source files remain recoverable.
- Add packaging/version guard tests so `sase` and `sase-core-rs` dependency ranges do not drift from daemon contract
  support without an intentional update.

Acceptance gates:

- M0-M5 status can be reported from one command or test helper.
- Release docs match the effective defaults and supported schema ranges.
- Hot read paths remain free of provider/plugin imports unless their surface explicitly requires host routing.
- Every authoritative migration has recorded shadow parity evidence and rollback guidance.

Suggested phase prompt:

> Implement Phase 11H from `sase_plan_rust_daemon_epic11_rollout_controls.md`: close Epic 11 with M5 provider-host
> rollout gates, release checklist/docs, packaging compatibility guards, and final milestone status reporting.

## Dependency Graph

1. Phase 11A should land first; it gives later agents a stable registry and policy vocabulary.
2. Phase 11B can start after 11A and should land before any broad default flip.
3. Phase 11C can start after 11A and can run in parallel with 11B if it does not edit handshake code.
4. Phase 11D depends on 11A-11C and benefits from 11B compatibility fields.
5. Phase 11E depends on 11D plus enough Epic 4/Epic 5 surface readiness.
6. Phase 11F depends on 11E plus Epic 9 ACE surface readiness.
7. Phase 11G depends on 11B-11D plus Epic 6 and Epic 7 surface readiness.
8. Phase 11H runs last after Epic 8 and the earlier milestone hardening phases.

## Verification Strategy

Each phase should run the narrowest useful checks in the affected repos. For this repo, run `just install` before
repo-level checks in a fresh workspace and run `just check` before handing off implementation changes. For Rust changes,
run the targeted `cargo test` package first and `just rust-test` or `cargo test --workspace` before final integration
where practical.

Default verification categories:

- Python unit tests for rollout registry/config/env behavior.
- Python fake-transport tests for daemon compatibility and fallback errors.
- Rust contract snapshot tests for local daemon and mobile gateway schemas.
- Rust projection/version tests for schema compatibility and migration state reporting.
- End-to-end daemon tests for rebuild, verify, diff, read, write, scheduler, fallback, and no-daemon paths.
- Perf gate registry tests that validate required gate names in default CI.
- Optional slow/soak runs for large histories before any default promotion.

## Rollback Requirements

Every phase that promotes a surface must preserve:

- global opt-out with `--no-daemon` where available and `SASE_NO_DAEMON=1`;
- per-surface config rollback for read/ACE/write/scheduler/provider-host modes;
- direct source-store fallback for non-authoritative phases;
- `sase daemon rebuild|verify|diff|doctor` recovery guidance;
- source files and JSONL stores as inspectable recovery artifacts;
- clear typed errors for incompatible daemon/client/core versions.

## Completion Definition

Epic 11 is complete when SASE has a tested rollout registry, compatibility handshake, milestone gate model, user-facing
diagnostics, release checklist, and per-milestone hardening for M0-M5 such that:

- users can opt out or recover at each milestone;
- no milestone requires deleting existing state;
- every authoritative migration has a preceding shadow parity phase;
- default enablement is blocked by tests unless parity, performance, compatibility, and recovery gates exist;
- release documentation matches the effective defaults and supported schema ranges.
