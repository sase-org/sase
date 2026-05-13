# Rust Daemon Epic 1 Readiness Review

Bead: `sase-3e.1.5`
Date: 2026-05-13
Design: `sdd/epics/202605/rust_daemon_epic1.md`

## Contract

Epic 1 is complete as a baseline and scaffolding workstream. It did not reroute any production command, ACE path,
mobile route, editor helper, provider/plugin path, recovery command, or bead workflow to a daemon. Current source stores
remain authoritative, and later daemon work must preserve direct source-store fallback until a later approved migration
changes that rule.

Primary artifacts:

- Compatibility matrix: `sdd/research/202605/rust_daemon_epic1_compatibility_matrix.md`
- Fixture manifest: `tests/fixtures/rust_daemon_epic1/manifest.json`
- Fixture validation: `tests/test_rust_daemon_epic1_fixtures.py`
- Perf harness: `tests/perf/bench_rust_daemon_epic1.py`
- Perf baseline: `tests/perf/baselines/rust_daemon_epic1_current.json`
- Perf recipe: `tests/perf/README.md`
- Local daemon contract snapshot: `../sase-core/crates/sase_gateway/contracts/local_daemon/v1/local_daemon_v1.json`
- Local daemon wire structs/tests: `../sase-core/crates/sase_gateway/src/wire.rs` and
  `../sase-core/crates/sase_gateway/src/contract.rs`

## Traceability

| Compatibility matrix row | Fixture path | Normalized snapshot path | Perf harness | Contract surface | Later epic owner |
|---|---|---|---|---|---|
| ChangeSpec `.sase` files | `tests/fixtures/rust_daemon_epic1/sources/changespec/demo.sase`; `tests/fixtures/rust_daemon_epic1/sources/changespec/demo-archive.sase` | `tests/fixtures/rust_daemon_epic1/expected/changespec_snapshot.json` | `tests/perf/bench_rust_daemon_epic1.py` (`changespec_search_plain`) | `LocalDaemonCollectionWire::Changespecs`; `LocalDaemonList*`; `LocalDaemonEvent*` | Epic 2 events/projections; Epic 4 shadow diff; Epic 5 reads; Epic 6 writes |
| Legacy ChangeSpec `.gp` files | `tests/fixtures/rust_daemon_epic1/sources/changespec/legacy.gp`; `tests/fixtures/rust_daemon_epic1/sources/changespec/legacy-archive.gp` | `tests/fixtures/rust_daemon_epic1/expected/changespec_snapshot.json` | Not latency-critical except through ChangeSpec reads | `LocalDaemonCollectionWire::Changespecs`; direct fallback required | Epic 2 parser compatibility; Epic 4 shadow diff; Epic 7/10 recovery |
| VCS and CL/PR metadata | Covered only as parsed ChangeSpec commit drawers; VCS side-effect fixtures intentionally missing | `tests/fixtures/rust_daemon_epic1/expected/changespec_snapshot.json` | Not daemon latency-critical in Epic 1 | `LocalDaemonErrorCodeWire::HostAdapterRequired`; fallback signaling only | Epic 5 cached metadata reads; Epic 8 provider/host isolation |
| Agent run artifacts | `tests/fixtures/rust_daemon_epic1/sources/agent_artifacts/projects/demo/artifacts` | `tests/fixtures/rust_daemon_epic1/expected/agent_artifacts_snapshot.json` | Related: `tests/perf/bench_agent_scan.py`; `tests/perf/bench_tui_trace.py`; `tests/perf/bench_agent_launch.py` | `LocalDaemonCollectionWire::Agents`; `LocalDaemonCollectionWire::Workflows`; `LocalDaemonList*`; `LocalDaemonEvent*` | Epic 2 artifact/workflow events; Epic 4 watcher/shadow diff; Epic 5 reads; Epic 7 lifecycle; Epic 9 ACE |
| Explicit artifacts | `tests/fixtures/rust_daemon_epic1/sources/explicit_artifacts/index.jsonl`; `tests/fixtures/rust_daemon_epic1/sources/explicit_artifacts/artifacts/agents/demo/20260513092000/report.md` | `tests/fixtures/rust_daemon_epic1/expected/explicit_artifacts_snapshot.json` | Not latency-critical beyond agent/artifact listing harnesses | `LocalDaemonCollectionWire::Artifacts`; host adapter required for file open/copy/render | Epic 2 artifact records; Epic 4 watcher; Epic 5 reads; Epic 9 lazy details |
| Dismissed identities | `tests/fixtures/rust_daemon_epic1/sources/dismissed/dismissed_agents.json` | `tests/fixtures/rust_daemon_epic1/expected/dismissed_snapshot.json` | Related ACE/archive timings are covered by existing agent artifact startup recipe | `LocalDaemonCollectionWire::Agents`; future write contract required | Epic 2 archive projections; Epic 4 watcher; Epic 6 cleanup/dismiss writes; Epic 10 recovery |
| Dismissed bundles | `tests/fixtures/rust_daemon_epic1/sources/dismissed_bundles/202605/bundle-current.json`; `tests/fixtures/rust_daemon_epic1/sources/dismissed_bundles/legacy_bundle.json` | `tests/fixtures/rust_daemon_epic1/expected/dismissed_snapshot.json` | Related ACE/archive timings are covered by existing agent artifact startup recipe | `LocalDaemonCollectionWire::Agents`; future write contract required | Epic 2 archive projections; Epic 4 shadow diff; Epic 6 archive writes; Epic 10 doctor/rebuild |
| Notifications JSONL | `tests/fixtures/rust_daemon_epic1/sources/notifications/notifications.jsonl` | `tests/fixtures/rust_daemon_epic1/expected/notifications_snapshot.json` | `tests/perf/bench_rust_daemon_epic1.py` (`notify_list_json`, `notify_show_json`); related `tests/perf/bench_notification_store.py` | `LocalDaemonCollectionWire::Notifications`; `LocalDaemonList*`; `LocalDaemonEvent*`; mobile `/api/v1` remains separate | Epic 2 notification events; Epic 4 watcher; Epic 5 reads; Epic 6 writes |
| Pending action stores | `tests/fixtures/rust_daemon_epic1/sources/pending_actions/current/actions.json`; `tests/fixtures/rust_daemon_epic1/sources/pending_actions/legacy/pending_actions.json` | `tests/fixtures/rust_daemon_epic1/expected/pending_actions_snapshot.json` | Related: `tests/perf/bench_notification_store.py` for action/state latency | `LocalDaemonErrorCodeWire::HostAdapterRequired` until action write contracts exist; mobile `/api/v1/actions/*` unchanged | Epic 2 action events; Epic 5 reads; Epic 6 writes; Epic 10 recovery |
| Bead stores | `tests/fixtures/rust_daemon_epic1/sources/beads/config.json`; `tests/fixtures/rust_daemon_epic1/sources/beads/issues.jsonl` | `tests/fixtures/rust_daemon_epic1/expected/beads_snapshot.json` | `tests/perf/bench_rust_daemon_epic1.py` (`bead_list`, `bead_show`, `bead_ready`); related `tests/perf/bench_bead.py` | `LocalDaemonCollectionWire::Beads`; `LocalDaemonList*`; `LocalDaemonEvent*` | Epic 2 bead events; Epic 4 watcher; Epic 5 reads; Epic 6 writes; Epic 7 work launch queue |
| SDD documents | `tests/fixtures/rust_daemon_epic1/sources/sdd/prompts/202605/demo_prompt.md`; `tests/fixtures/rust_daemon_epic1/sources/sdd/epics/202605/demo_epic.md`; `tests/fixtures/rust_daemon_epic1/sources/sdd/research/202605/demo_research.md` | `tests/fixtures/rust_daemon_epic1/expected/sdd_snapshot.json` | Not latency-critical in Epic 1 | No dedicated collection yet; future catalog/search may use `LocalDaemonList*` | Epic 4 catalog watcher; Epic 5 catalog reads; Epic 10 repair |
| Workflow runtime state | `tests/fixtures/rust_daemon_epic1/sources/agent_artifacts/projects/demo/artifacts/workflow-review/20260513100000/workflow_state.json` | `tests/fixtures/rust_daemon_epic1/expected/workflow_snapshot.json` | Related: `tests/perf/bench_agent_launch.py`; `tests/perf/bench_workflow_complete.py` | `LocalDaemonCollectionWire::Workflows`; host adapter required for script execution | Epic 2 workflow events; Epic 4 watcher; Epic 6 state writes; Epic 7 scheduler |
| Xprompt catalogs | `tests/fixtures/rust_daemon_epic1/sources/xprompts/package/package_demo.md`; `tests/fixtures/rust_daemon_epic1/sources/xprompts/user/user_demo.md`; `tests/fixtures/rust_daemon_epic1/sources/xprompts/project/project_demo.md`; `tests/fixtures/rust_daemon_epic1/sources/.config/sase/xprompts/demo/config_demo.md` | `tests/fixtures/rust_daemon_epic1/expected/xprompts_snapshot.json` | `tests/perf/bench_rust_daemon_epic1.py` (`editor_xprompt_catalog`) | `LocalDaemonCollectionWire::Xprompts`; direct editor/LSP fallback required | Epic 4 catalog watcher; Epic 5 editor/catalog reads; Epic 8 plugin/resource host isolation |
| Prompt, chat, command, and file-reference history | `tests/fixtures/rust_daemon_epic1/sources/history/prompt_history.json`; `tests/fixtures/rust_daemon_epic1/sources/history/file_reference_history.json`; `tests/fixtures/rust_daemon_epic1/sources/history/command_history.json`; `tests/fixtures/rust_daemon_epic1/sources/history/vcs_xprompt_mru.json`; `tests/fixtures/rust_daemon_epic1/sources/history/chats/202605/demo-run-agent-20260513103000.md` | `tests/fixtures/rust_daemon_epic1/expected/history_snapshot.json`; `tests/fixtures/rust_daemon_epic1/expected/largeish_snapshot.json` | Not latency-critical beyond resume/listing paths in later read APIs | No dedicated collection yet; future reads may use list/event shapes with direct fallback | Epic 2 history events; Epic 4 watcher; Epic 5 file-history reads |
| Axe scheduler state, checks, and logs | `tests/fixtures/rust_daemon_epic1/sources/axe/scheduler_state.json`; `tests/fixtures/rust_daemon_epic1/sources/axe/checks.jsonl`; `tests/fixtures/rust_daemon_epic1/sources/logs/axe-run.log` | `tests/fixtures/rust_daemon_epic1/expected/axe_snapshot.json` | Not latency-critical for daemon reads in Epic 1; scheduler execution remains host-owned | `LocalDaemonErrorCodeWire::HostAdapterRequired`; future log summaries may use list/event shapes | Epic 7 scheduler/lifecycle; Epic 10 log retention/recovery |
| Mobile gateway state and routes | `tests/fixtures/rust_daemon_epic1/sources/mobile/bridge_state.json`; `tests/fixtures/rust_daemon_epic1/sources/mobile/audit.jsonl` | `tests/fixtures/rust_daemon_epic1/expected/mobile_snapshot.json` | Existing mobile perf remains outside local daemon baseline | Existing `/api/v1` snapshot stays at `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`; local daemon snapshot is separate | Epic 3 runtime/transport; Epic 5 mobile/read coexistence |
| Editor helpers and LSP | `tests/fixtures/rust_daemon_epic1/sources/editor/helper_request.json`; `tests/fixtures/rust_daemon_epic1/sources/editor/lsp_completion_request.json` | `tests/fixtures/rust_daemon_epic1/expected/editor_snapshot.json` | `tests/perf/bench_rust_daemon_epic1.py` (`editor_xprompt_catalog`) | `LocalDaemonCollectionWire::Xprompts`; editor protocol process remains host-owned | Epic 5 editor reads; Epic 8 resource host |
| Provider subprocesses | Intentionally missing from daemon corpus; remains covered by launch/provider tests outside Epic 1 daemon fixtures | None | Related: `tests/perf/bench_agent_launch.py` for launch preparation, not provider execution | `LocalDaemonErrorCodeWire::HostAdapterRequired` | Epic 7 lifecycle coordination; Epic 8 provider host IPC |
| Plugin boundaries | Intentionally missing from daemon corpus; plugin discovery/execution stays Python-owned | None | Not latency-critical for daemon source-store reads | `LocalDaemonErrorCodeWire::HostAdapterRequired` | Epic 8 plugin/provider host isolation |
| Recovery, doctor, logs, repair, and no-daemon commands | Covered indirectly by fixture families above plus direct fallback expectations in the matrix | Family-specific snapshots above | Not daemon latency-critical; these commands are direct-source repair paths | `LocalDaemonFallbackWire`; `daemon_unavailable`; `host_adapter_required` | Epic 10 recovery/operations |

## Gap List

### Blocking for Epic 2 Event/Projection Work

- None for source-store discovery. The fixture manifest covers the project specs, notifications, pending actions, agent
  artifacts, explicit artifacts, dismissed state, beads, workflow state, xprompts, histories, SDD docs, axe state,
  mobile bridge state, editor helper requests, and a large-ish scaling corpus.
- Remaining risk: VCS side effects, provider subprocess execution, and plugin execution are intentionally absent from
  the daemon source-store corpus. Epic 2 should model only parsed metadata/events for these areas and must not attempt
  to project live side effects.

### Blocking for Epic 3 Daemon Transport Work

- None for contract scaffolding. The local daemon contract records framed JSON, schema compatibility, health,
  capabilities, list, events, batch, payload bounds, snapshot IDs, cursors, stable handles, and explicit fallback
  signaling.
- Remaining risk: transport implementation is deliberately absent. Epic 3 must implement the socket/client framing and
  keep `/api/v1` mobile compatibility separate from `sase_local_daemon_framed_json_v1`.

### Blocking for Epic 4 Shadow Indexers

- None for initial shadow-index inputs. The corpus includes representative source families and normalized snapshots, and
  the perf harness provides current direct-read baselines.
- Remaining risk: large local histories are represented by a synthetic large-ish corpus, not a real worst-case user
  tree. Epic 4 should add opt-in real-home shadow-diff runs before trusting production-sized performance numbers.

### Deferrable Until Read/Write Routing Epics

- Daemon write transactions, locks, idempotency, source export, and rollback are not defined. Epic 6 owns these.
- Provider, plugin, VCS, workflow script execution, file viewers, ACE rendering, editor process ownership, axe process
  control, and recovery commands remain host-owned.
- Stable regression floors are not enforced by Epic 1. Current baseline thresholds are advisory until a later phase has
  enough signal to avoid noisy CI failures.

## Production Routing Review

Phase 1E reviewed the artifacts and current working tree with the explicit goal of finding unintended production route
changes:

- Phase 1A produced only the compatibility matrix.
- Phase 1B added `tests/fixtures/rust_daemon_epic1/` and `tests/test_rust_daemon_epic1_fixtures.py`; the tests use
  current direct loaders/facades and do not add daemon routing.
- Phase 1C added `tests/perf/bench_rust_daemon_epic1.py`, `tests/perf/baselines/rust_daemon_epic1_current.json`, and
  perf README notes; the harness uses a hermetic `HOME`/`SASE_HOME` by default and does not start a daemon.
- Phase 1D added local daemon wire structs and contract snapshots in `../sase-core/crates/sase_gateway/`; the snapshot
  says `transport.implemented = false` and production routing is not implemented.
- Phase 1E changed documentation and bead metadata only.

No production command, router, ACE data path, mobile route, editor helper, provider/plugin path, or recovery command is
routed to the local daemon by Epic 1.

## Later Epic Readiness

- Epic 2 can start from the compatibility matrix rows and Phase 1B fixture families to define replayable source events.
- Epic 3 can implement the local daemon transport against the separate `sase_local_daemon_framed_json_v1` snapshot
  without changing mobile `/api/v1`.
- Epic 4 can build shadow indexers from the fixture corpus and compare against the normalized snapshots before touching
  user-visible reads.
- Epic 5 can choose daemon-read candidates that already have fixture rows and current direct-read perf baselines.
- Epic 6 must design write transactions before moving any `daemon-write candidate` behavior.
- Epic 7 should keep provider/workflow/axe side effects in host adapters until lifecycle ownership is explicit.
- Epic 8 should isolate providers/plugins uniformly across runtimes; do not add runtime-specific capability branches.
- Epic 9 should adapt ACE through paged/delta providers while preserving direct loader fallback.
- Epic 10 should treat recovery, doctor, source repair, log pack, and no-daemon commands as direct-source operations.
- Epic 11 can define rollout modes using this baseline's disabled, fallback, advisory-perf, and contract-only state.

## Validation

Focused validation commands for the Epic 1 closure:

```bash
just install
.venv/bin/pytest -q tests/test_rust_daemon_epic1_fixtures.py
.venv/bin/pytest -q -m slow tests/perf/bench_rust_daemon_epic1.py
cd ../sase-core && cargo test -p sase_gateway contract
cd ../sase-core && cargo test -p sase_gateway local_daemon_wire_json_snapshot
just check
```

The final Phase 1E run recorded these results:

- `just install`: passed.
- `.venv/bin/pytest -q tests/test_rust_daemon_epic1_fixtures.py`: passed.
- `.venv/bin/pytest -q -m slow tests/perf/bench_rust_daemon_epic1.py`: passed.
- `cd ../sase-core && cargo test -p sase_gateway contract`: passed.
- `cd ../sase-core && cargo test -p sase_gateway local_daemon_wire_json_snapshot`: passed.
- `just check`: passed.

## Phase Handoff

Complete:

- Created the Epic 1 traceability table connecting matrix rows, fixture source paths, normalized snapshots, perf
  harnesses, local daemon contract surfaces, and later epic owners.
- Classified remaining gaps by Epic 2, Epic 3, Epic 4, and later routing work.
- Recorded the no-production-routing review and the direct fallback requirement.

Intentionally deferred:

- No daemon process, transport startup, projection store, production read route, production write route, ACE routing
  change, mobile route migration, provider/plugin IPC, or recovery-command migration was implemented.
