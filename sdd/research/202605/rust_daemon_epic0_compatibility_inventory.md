# Rust Daemon Epic 0 Compatibility Inventory

Bead: `sase-3e.2.1`
Date: 2026-05-13

## Contract

This document records the current product contract before the Rust daemon and
indexed projections become part of production routing. It is an inventory and
behavior matrix only.

No production command, ACE path, editor helper, mobile route, provider, plugin,
or recovery command has been rerouted by this phase. Current source stores
remain authoritative. Any daemon or projection state introduced by later epics
must be rebuildable from those stores until a later approved migration changes
that contract explicitly.

Classification values used below:

- `unchanged`: leave behavior and current Python/Rust facade routing as-is for
  now.
- `daemon-read candidate`: later epics may serve hot reads from indexed daemon
  projections, with direct source-store fallback.
- `daemon-write candidate`: later epics may move mutations behind daemon
  transactions that still update current source stores.
- `host-adapter only`: behavior depends on local subprocesses, providers,
  plugins, UI rendering, editors, VCS commands, or workflow side effects and
  should stay in Python host adapters.
- `deferred`: keep direct/fallback behavior until more contract work exists.

## Source Store Families

| Store family | Source of truth | Rebuildable caches/indexes | Current loader/mutator entry points | No-daemon expectation |
|---|---|---|---|---|
| ChangeSpecs | `~/.sase/projects/*.sase` and legacy `*.gp`; archive files such as `<project>-archive.sase` / legacy `<project>-archive.gp` | In-memory parser/query caches; graph/query indexes; future projection DB | Python parser/model code in `src/sase/ace/changespec/`; Rust parser/query facades in `src/sase/core/parser_facade.py`, `src/sase/core/query_facade.py`, `../sase-core/crates/sase_core/src/parser.rs`, `project_spec.rs`, `query/`; CLI handlers in `src/sase/main/changespec_handler.py`; ACE loaders in `src/sase/ace/tui/models/` | Must parse and mutate files directly for CLI, ACE, recovery, and migration commands. |
| VCS state and CL/PR metadata | Underlying git/bare-git workspaces and provider-specific state | Deltas fields, query summaries, workflow check output | `src/sase/vcs_provider/`, `src/sase/workspace_provider/`, `src/sase/ace/deltas/`, `src/sase/ace/handlers/`, `src/sase/workflows/commit/` | Direct VCS provider calls must continue for recovery, commit, submit, status, and diff operations. |
| Agent artifacts | `~/.sase/projects/<project>/ace-run/<timestamp>/` and workflow artifact directories containing `agent_meta.json`, `running.json`, `done.json`, prompt files, reply files, step markers, HITL files | Rust artifact scan snapshot/index; ACE model caches; dismissed bundle index | Python listing in `src/sase/agent/running.py`; ACE loader in `src/sase/ace/tui/models/agent_loader.py`; Rust facade in `src/sase/core/agent_scan_facade.py`; Rust scanner/index in `../sase-core/crates/sase_core/src/agent_scan/` | CLI/ACE must still walk artifacts when daemon/index is missing or stale. |
| Explicit artifacts | Agent artifact directories plus explicit artifact metadata/files | `src/sase/core/agent_artifact_explicit.py` indexes | CLI handler `src/sase/main/artifact_handler.py`; artifact helpers in `src/sase/core/agent_artifact_*`; modal `src/sase/ace/tui/modals/agent_artifacts_modal.py` | Direct artifact path access stays available. |
| Dismissed agents and archive bundles | Dismissed identity state and `~/.sase/dismissed_bundles/YYYYMM/*.json`, with legacy top-level bundle files | SQLite summary index under dismissed bundle area; Rust archive query/FTS candidates | `src/sase/ace/dismissed_agents*.py`; `src/sase/ace/dismissed_bundle_index/`; Rust archive module `../sase-core/crates/sase_core/src/agent_archive/` | ACE revive/archive commands must work from bundle JSON even if indexes are absent. |
| Notifications | `~/.sase/notifications/notifications.jsonl` | Per-process stat cache; future projection; mobile list/detail views | Python store in `src/sase/notifications/store.py`; Rust facade in `src/sase/core/notification_store_facade.py`; Rust implementation in `../sase-core/crates/sase_core/src/notifications/`; CLI `src/sase/main/notify_handler.py`; ACE notification modal/indicator | Reads and state mutations must work directly against JSONL. |
| Pending mobile/host actions | `~/.sase/pending_actions/actions.json`; legacy `~/.sase/telegram/pending_actions.json` | None authoritative; future projection is rebuildable | Python `src/sase/notifications/pending_actions.py`; Rust `../sase-core/crates/sase_core/src/notifications/pending_actions.rs`; mobile gateway bridge `../sase-core/crates/sase_gateway/src/host_bridge.rs` | Direct JSON action resolution and cleanup must remain. |
| Beads | Current checkout `sdd/beads/issues.jsonl`, `config.json`, optional SQLite-compatible store behavior | Import/export or SQLite transition artifacts; future projection | CLI parsers/handlers in `src/sase/main/parser_bead.py`, `src/sase/bead/`; Rust bead modules in `../sase-core/crates/sase_core/src/bead/`; fast path `src/sase/main/bead_fast_path.py` | `sase bead` must continue to operate on the checkout store without a daemon. |
| SDD documents | `sdd/prompts/`, `sdd/tales/`, `sdd/epics/`, `sdd/legends/`, `sdd/research/`, frontmatter | Link validation output, future catalog projection | `src/sase/sdd/`; CLI `src/sase/main/sdd_handler.py`; bead links in `src/sase/sdd/beads.py` | Files remain human-editable and directly repairable. |
| Workflows | Xprompt workflow YAML/Markdown plus runtime `workflow_state.json`, step markers, HITL request/response files under artifacts | ACE workflow models; future workflow projection | `src/sase/xprompt/workflow_*`; `src/sase/xprompt/workflow_runner.py`; `src/sase/main/query_handler/_query.py`; ACE workflow models/actions; axe workflow runners | Workflow execution and recovery must continue from artifacts and workflow state files. |
| Xprompts/catalogs | Package xprompts in `src/sase/xprompts/`, project/user xprompt dirs, default xprompts, dynamic memory references, skill refs | Rendered xprompt catalog; LSP/editor indexes; future catalog projection | `src/sase/xprompt/loader*.py`, `catalog*.py`, `processor.py`; CLI `src/sase/main/xprompt_handler.py`; Rust `../sase-core/crates/sase_core/src/xprompt_catalog.rs`; editor helpers | Expansion/catalog commands must work by scanning current sources. |
| Prompt/chat/file history | `~/.sase/prompt_history.json`, `~/.sase/chats/YYYYMM/*.md`, `~/.sase/file_reference_history.json` | In-memory command pickers; future history projection | `src/sase/history/prompt.py`, `chat.py`, `file_references.py`; run/resume handlers; ACE modals | Direct JSON/Markdown history reads remain required. |
| Axe state and logs | `~/.sase/axe/`, hook/check/comment/mentor/workflow output files, chop/lumberjack config, process state, logs | Dashboard summaries and future scheduler projection | `src/sase/axe/`; ACE scheduler modules under `src/sase/ace/scheduler/`; TUI axe widgets/actions | Scheduler start/stop/checks must remain operable without daemon. |
| Mobile gateway state | `~/.sase/mobile_gateway/audit.jsonl`, gateway pairing/session/push state; notification JSONL and pending actions via bridge | Existing mobile API contract snapshot; push/session caches | Rust gateway in `../sase-core/crates/sase_gateway/src/routes.rs`, `host_bridge.rs`, `storage.rs`, `wire.rs`, `contract.rs`; Python launch handler `src/sase/main/mobile_handler.py` | Current loopback HTTPS/SSE mobile gateway stays intact and must keep direct host bridges. |
| Provider/plugin subprocesses | Provider CLIs, plugin discovery/config, local environment, tmux/process state | Agent metadata and logs | `src/sase/llm_provider/`; `src/sase/vcs_provider/`; `src/sase/workspace_provider/`; plugin discovery in `src/sase/main/plugin_discovery.py`; subprocess execution in axe/run paths | Host adapter behavior stays Python-owned. Daemon may coordinate but must not embed provider-specific assumptions. |

## Behavior Matrix

| Surface | Current user behavior | Source stores and entry points | Side effects that stay host-owned | Classification | Later dependency |
|---|---|---|---|---|---|
| `sase run` foreground prompt | Normalizes xprompts/workflows, records prompt history, creates artifacts, runs provider/workflow path, saves chat/artifact outputs | `src/sase/main/entry.py`, `src/sase/main/query_handler/_query.py`, `src/sase/xprompt/`, `src/sase/history/`, `~/.sase/projects/*/ace-run/*` | Provider subprocess invocation, workspace claiming, cwd/ref resolution, prompt/history writes, artifact file writes | host-adapter only for execution; daemon-read candidate for preflight catalog/history/status | Epic 1 events for workflow/agent lifecycle; Epic 2 local transport; Epic 4 CLI reads |
| Multi-agent prompts and xprompt expansion | `---` segments and multi-agent xprompts dispatch child agents/workflows with separate workspaces/artifacts | `src/sase/agent/multi_prompt.py`, `src/sase/agent/multi_agent_xprompt.py`, `src/sase/agent/launcher.py`, artifact dirs | Agent spawning, workspace allocation, provider subprocesses, parent/child metadata | host-adapter only for spawning; daemon-write candidate for lifecycle event append later | Epic 1 agent/workflow events; Epic 6 launch ownership |
| Xprompt workflows | YAML/Markdown workflows run prompt, script, embedded, parallel, and HITL steps; runtime state appears in ACE | `src/sase/xprompt/workflow_executor*.py`, `workflow_hitl.py`, `workflow_runner.py`; `workflow_state.json`; HITL request/response files | User-authored Python/bash steps, editor/HITL pauses, file writes, provider calls | host-adapter only for execution; daemon-read/write candidate for state indexing and HITL state | Epic 1 workflow projection; Epic 3 shadow diffs; Epic 6 scheduler/ownership |
| Resume/retry | Resume loads chat history; retry uses agent artifacts/lineage and provider-specific continuation semantics | `src/sase/main/query_handler/_resume.py`; `src/sase/history/chat.py`; `src/sase/agent/running.py`; mobile retry helpers | Provider continuation, prompt composition, artifact mutation | host-adapter only for provider call; daemon-read candidate for history/lineage lookup | Epic 1 agent/archive/history projections |
| Plan/question/HITL flows | Create actionable notifications, write request files, wait for user response, process approval/rejection/feedback | `src/sase/plan_chain.py`, `src/sase/main/plan_*`, `src/sase/main/questions_command_handler.py`, workflow HITL modules, notification store/pending actions | Response file writes, user prompts/modals, notification mutation, side-effect execution | daemon-write candidate for action state; host-adapter only for UI/provider side effects | Epic 1 notification/workflow projections; Epic 2/5 action route policy |
| ACE ChangeSpecs tab | Lists, filters, groups, selects, edits status, mail/reword/revert/restore, shows details, comments, commits, deltas, hooks, mentors | `src/sase/ace/changespec/`; `src/sase/ace/tui/widgets/changespec_*`; `src/sase/ace/tui/actions/`; `.sase`/legacy `.gp` files; VCS provider | VCS status/diff commands, editor launches, status file mutations, comments/hooks updates | daemon-read candidate for list/search/details; daemon-write candidate only after mutation contract; direct fallback required | Epic 1 ChangeSpec projection; Epic 3 shadow diff; Epic 4 ACE read APIs |
| ACE Agents tab | Lists running/waiting/done/failed agents, groups/folds, filters/searches, shows detail, reply/thinking, attempts, children, artifacts | `src/sase/ace/tui/models/agent_loader.py`; `src/sase/ace/tui/widgets/agent_*`; `src/sase/core/agent_scan_facade.py`; artifact dirs and indexes | Process liveness checks, kill/dismiss/revive, artifact opens, live file reads | daemon-read candidate for indexed list/search/detail; host-adapter for process operations | Epic 1 agent/archive projection; Epic 4/8 ACE data paths |
| ACE Notifications | Indicator and modal list/detail/actions; mark read/dismiss/snooze; attachment preview/download; plan/HITL/question actions | `src/sase/ace/tui/widgets/notification_indicator.py`; `src/sase/ace/tui/modals/notification_*`; notification JSONL; pending actions | Local file attachment access, response file writes, notification state mutations | daemon-read/write candidate, with direct JSONL fallback | Epic 1 notification projection; Epic 2 local contract; Epic 5 action routing |
| ACE Artifacts | Opens explicit artifacts, rendered image/sequence viewers, agent artifact modal | `src/sase/core/agent_artifact_*`; `src/sase/ace/tui/modals/agent_artifacts_modal.py`; `src/sase/ace/tui/graphics/` | Terminal/UI rendering, image viewer loops, file opens | daemon-read candidate for metadata; host-adapter only for rendering/opening | Epic 1 artifact projection; Epic 8 UI perf |
| ACE AXE dashboard | Shows scheduler status, chops, lumberjacks, logs/output; starts/stops/checks background jobs | `src/sase/ace/tui/widgets/axe_dashboard.py`; `src/sase/ace/tui/actions/axe*.py`; `src/sase/axe/` | Process control, shell scripts, check execution, log streaming | host-adapter only now; deferred daemon ownership until scheduler epic | Epic 6 scheduler ownership |
| ACE tags/grouping/filters/saved queries | Applies ChangeSpec and agent query languages, tag filters, folds, grouping, saved queries | `src/sase/ace/query/`; `src/sase/ace/agent_query/`; `src/sase/ace/tui/models/*fold*`; saved query/tag files | UI selection state and key workflows | daemon-read candidate for facets/counts/search; UI state unchanged | Epic 4 paged/faceted read APIs |
| ACE revive/cleanup/dismiss | Dismisses identities, archives bundles, revives from archive, cleans stale/running agents, shows cleanup plans | `src/sase/ace/dismissed_agents*.py`; `src/sase/ace/dismissed_bundle_index/`; `src/sase/core/agent_cleanup_facade.py`; Rust cleanup/archive modules | Process inspection, bundle JSON writes, kill signals, cleanup confirmation | daemon-write candidate for archive/cleanup events; host-adapter for process actions | Epic 1 archive/cleanup projections; Epic 6 operations |
| ACE logs/activity/keyboards/modals | Keyboard-first UI, modals, command palette, activity log, task queue, saved selections | `src/sase/ace/tui/app.py`, `bindings.py`, `keymaps/`, `modals/`, `commands/`, `activity_log.py` | Textual rendering, keyboard handling, modal state | unchanged / host-adapter only | Epic 8 UI integration only after daemon APIs exist |
| Axe scheduler and checks | Starts/stops orchestrator, runs hook/mentor/workflow/comment/pending checks, cleanup, suffix transforms, chops and lumberjacks | `src/sase/axe/orchestrator.py`, `hook_jobs.py`, `check_cycles.py`, `chop_runner.py`, `lumberjack.py`, `maintenance.py`; CLI `src/sase/main/axe_handler.py` | Subprocesses, timers, shell/VCS commands, mentor/provider calls, lock/process management | host-adapter only initially; daemon-write candidate for scheduler state later | Epic 6 scheduler/lifecycle |
| ChangeSpec CLI | `current`, `search`, `sync-deltas`, `migrate-extension` | `src/sase/main/parser_commands.py`, `changespec_handler.py`; parser/query facades; `.sase`/`.gp` files | VCS deltas sync, migration writes | daemon-read candidate for search/current; direct fallback mandatory | Epic 4 CLI reads; Epic 7 recovery |
| Commit/restore/revert workflows | Commit skill workflow, precommit hooks, CL/PR metadata, restore/revert archived changes | `src/sase/main/parser_commit.py`; `src/sase/workflows/commit/`; `src/sase/ace/revert.py`, `restore.py`; VCS providers | Git/bare-git commands, hooks, commits, PR operations | host-adapter only for execution; daemon-read candidate for metadata/status | Epic 6/7 after write contract |
| Bead workflows | `create/list/show/ready/update/close/dep/work`, plan/epic/legend/phase metadata, dependencies, model routing | `src/sase/main/parser_bead.py`; `src/sase/bead/`; Rust `../sase-core/crates/sase_core/src/bead/`; checkout `sdd/beads/*` | File mutations in checkout, agent launches from `bead work` | daemon-read candidate for list/show/ready; daemon-write candidate only after JSONL parity and locks | Epic 1 bead projection; Epic 3 fixtures; Epic 4 CLI reads |
| SDD workflows | SDD init/validate/list/links/repair and plan/prompt/tale/epic/legend files | `src/sase/main/parser_sdd.py`, `sdd_handler.py`; `src/sase/sdd/`; `sdd/**` | Human-authored file edits and repair writes | unchanged; daemon-read candidate for catalog/search later | Epic 1 catalog/file projection |
| Editor helpers and LSP | File completion, xprompt completion/hover/definition/diagnostics/args, helper bridge | `src/sase/main/parser_editor.py`, `parser_commands.py` `lsp`; `src/sase/integrations/editor_helpers.py`, `xprompt_lsp.py`; Rust editor modules | Editor protocol process, filesystem reads, project context | daemon-read candidate for catalog/completion; direct fallback mandatory | Epic 2 local transport; Epic 4 editor reads |
| Mobile gateway | Existing `/api/v1` HTTP/SSE routes for health, pairing/session/push, agents, helpers, xprompt catalog, beads, notifications, HITL/question actions | `../sase-core/crates/sase_gateway/src/routes.rs`, `wire.rs`, `contract.rs`, `host_bridge.rs`, `storage.rs`; Python bridge commands under `src/sase/integrations/mobile_*` | Host bridge subprocesses, notification/action file mutations, push provider calls | unchanged for mobile API; daemon local API must coexist, not replace it | Epic 0D contract; Epic 2 local transport |
| Providers | Claude, Gemini, Codex, Qwen, OpenCode, plain subprocess, streaming and artifact capture | `src/sase/llm_provider/`; provider config/plugins | Provider CLI invocation, env, streaming, retry, tool output artifacts | host-adapter only | Epic 6 may coordinate lifecycle but not special-case runtimes |
| Plugins | LLM/VCS/workspace plugin discovery and hook specs | `src/sase/llm_provider/_plugin_manager.py`, `src/sase/vcs_provider/_plugin_manager.py`, `src/sase/workspace_provider/_plugin_manager.py`, `src/sase/main/plugin_discovery.py` | Python plugin loading, subprocesses, local config | host-adapter only | Deferred until daemon plugin-host contract exists |
| Recovery/doctor/logs | `core health`, bead doctor, logs pack, revive-log, agent index rebuild/verify, migration/repair commands | `src/sase/main/core_handler.py`; `src/sase/logs/`; bead/admin handlers; agent index commands | Direct file reads/writes, diagnostics, bundle/log collection | unchanged / direct fallback | Epic 7 recovery/doctor |
| Direct no-daemon fallback | Any command must keep a path to current stores when daemon missing, stale, incompatible, or disabled | All current modules above | Direct filesystem/VCS/provider access | unchanged | All later epics |

## Current Move/Keep Decisions

| Surface group | Decision |
|---|---|
| CLI status/search/list commands over ChangeSpecs, agents, notifications, beads, xprompt/editor catalogs | `daemon-read candidate` after fixtures, projection parity, and local contract snapshots exist. |
| CLI/ACE/mobile writes to notification state, pending actions, beads, ChangeSpec status/archive, workflow/HITL state, agent lifecycle/archive/dismiss/revive | `daemon-write candidate` only after event transaction semantics preserve source-store writes and direct recovery. |
| Provider calls, plugin execution, workflow script steps, VCS commands, editor process protocol, Textual rendering, local file open/viewer actions, process kill/start/stop | `host-adapter only`. The daemon may coordinate or index results, but Python remains the compatibility host. |
| Mobile `/api/v1` HTTPS/SSE surface | `unchanged`. Local daemon framed JSON must be additive and coexist with the mobile route contract. |
| Recovery, doctor, migration, logs, import/export, source-store repair | `unchanged`. These commands must never require a healthy daemon. |
| Fully daemon-authoritative state or removal of `.sase`, legacy `.gp`, JSONL, artifact, bead, xprompt, workflow, or pending-action stores | `deferred` and out of scope for Epic 0. |

## Out-of-Order State to Reconcile

Epic 1 planning already exists at
`sdd/epics/202605/rust_daemon_event_projection_core_epic1.md`, and the sibling
Rust workspace already contains projection modules under
`../sase-core/crates/sase_core/src/projection/` for event, store, schema,
ChangeSpec, notification, and agent work. This is ahead of Epic 0 fixture and
contract artifacts.

Later Epic 1+ work should retrofit the following Epic 0 artifacts into tests:

- Use the Phase 0B fixture corpus for replay-vs-live projection tests instead
  of only synthetic inline Rust fixtures.
- Add ChangeSpec tests that include both canonical `.sase` and legacy `.gp`
  active/archive files.
- Add notification tests that cover JSONL state rewrites, snooze expiry,
  dismissed rows, pending actions, and legacy Telegram pending-action merge.
- Add agent/artifact/archive tests that include active markers, waiting/HITL,
  failed/killed/done markers, retries, parent/child workflow entries,
  dismissed bundle JSON, and stale/missing artifact dirs.
- Add bead tests that compare Rust bead read/mutation behavior against checkout
  `sdd/beads/issues.jsonl` semantics, dependencies, ready/blocked logic, epic
  tiers, design links, and model routing.
- Add workflow/catalog/file-history tests that replay `workflow_state.json`,
  HITL request/response files, project/user/package xprompts, dynamic-memory
  catalog input, prompt history, chat history, and file-reference history.

## Compatibility Risks

- Multi-machine `~/.sase` sync: projections and lock files are host-local.
  Later daemon work must include host identity and refuse unsafe shared-WAL
  ownership. Source stores must remain syncable and repairable.
- Legacy `.gp` support: migration is still a compatibility path. Daemon
  projections must parse both `.sase` and `.gp` active/archive stores until a
  separate approved migration removes legacy support.
- Dismissed-agent identities and archive bundles: ACE depends on persisted
  bundle JSON and suffix identities. An index must not become the only copy of
  reviveable history.
- Pending mobile/notification actions: action state is inferred from both
  notification rows and side-effect files. Shadow tests must cover already
  handled, stale, missing-target, ambiguous-prefix, and duplicate-full-id cases.
- Workflow HITL files: `hitl_request.json`, `hitl_response.json`,
  plan/question request/response files, and artifact directories are part of
  the current contract. Daemon actions must write the same files or retain a
  direct bridge to the host adapter.
- Provider subprocess contracts: all supported runtimes are capability
  equivalent. Do not introduce daemon branches that assume Claude, Gemini,
  Codex, Qwen, OpenCode, or plugin providers lack hooks, skills, artifacts, or
  commit workflow support.
- Cold-start imports versus direct fallback: a daemon client may improve hot
  reads, but commands must fail open to direct source-store reads when daemon
  version, schema, socket, or lock state is unavailable.
- Mobile route compatibility: the existing gateway contract under
  `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json` must
  remain stable while local daemon contract snapshots are added.

## Phase Handoff

- Phase 0B should turn each source-store family above into portable fixtures
  and expected normalized snapshots. It should not change production routing.
- Phase 0C should map each daemon-read candidate to at least one current p50/p95
  baseline and an aspirational target.
- Phase 0D should define a local framed-JSON contract that is additive beside
  the current mobile `/api/v1` contract.
- Phase 0E should verify the inventory, fixture contract, perf baseline, and
  wire contract documents cross-link and explicitly list any surfaces still
  missing fixture coverage.
