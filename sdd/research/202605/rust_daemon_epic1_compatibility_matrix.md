# Rust Daemon Epic 1 Compatibility Matrix and Gap Map

Bead: `sase-3e.1.1`
Date: 2026-05-13
Design: `sdd/epics/202605/rust_daemon_epic1.md`

## Contract

This is the Epic 1 baseline artifact for the Rust daemon and indexed projection rebuild. It reconciles the earlier
`sdd/research/202605/rust_daemon_epic0_compatibility_inventory.md` with the legend in
`sdd/legends/202605/rust_daemon_indexed_projections_1.md` and records what later daemon, projection, ACE, CLI, editor,
mobile, and recovery agents may rely on.

No production command, ACE path, mobile route, editor helper, provider/plugin path, axe scheduler path, recovery
command, or bead workflow has been rerouted by this phase. Current source stores remain authoritative. Any daemon or
projection state added by later epics must remain rebuildable from those stores until an approved migration explicitly
changes that rule.

Classifications:

- `unchanged`: keep the current Python/Rust facade behavior as-is.
- `daemon-read candidate`: later epics may serve hot reads from daemon projections with direct source fallback.
- `daemon-write candidate`: later epics may route mutations through daemon transactions that still update or export the
  current source stores.
- `host-adapter only`: behavior depends on subprocesses, providers, plugins, workflow side effects, UI rendering,
  editors, VCS commands, process control, or local file viewers and must stay host-owned.
- `deferred`: keep direct/fallback behavior until more contract or migration work exists.

Fixture coverage values:

- `existing`: representative fixtures, goldens, or parity tests exist today, though later phases may still expand them.
- `added by Phase 1B`: no complete Epic 1 fixture exists yet; Phase 1B must add it.
- `missing`: coverage is intentionally absent or too environment-specific; Phase 1B or Phase 1E must record the reason.

## Source Store Compatibility Matrix

| Source family | Source of truth | Current loader/mutator entry points | Classification | Direct fallback expectation | Later epic dependency | Fixture coverage |
|---|---|---|---|---|---|---|
| ChangeSpec `.sase` files | `~/.sase/projects/<project>.sase` and `<project>-archive.sase` | `src/sase/ace/changespec/`, `src/sase/core/parser_facade.py`, `src/sase/core/query_facade.py`, `src/sase/main/changespec_handler.py`, `../sase-core/crates/sase_core/src/parser.rs`, `project_spec.rs`, `query/` | `daemon-read candidate`; selected status/archive mutations are future `daemon-write candidate` | CLI, ACE, recovery, and migration commands must parse and mutate files directly when the daemon is missing, disabled, stale, or incompatible. | Epic 2 event/projection model; Epic 4 shadow diff; Epic 5 read APIs; Epic 6 write APIs | `existing` for canonical `.sase` via `tests/core_golden/` and `../sase-core/crates/sase_core/tests/fixtures/`; active/archive fixture breadth must be expanded by Phase 1B |
| Legacy ChangeSpec `.gp` files | `~/.sase/projects/<project>.gp` and `<project>-archive.gp` | Project-spec migration tests and parser compatibility paths under `src/sase/ace/` and `src/sase/core/` | `daemon-read candidate` for compatibility parsing; write migration remains `host-adapter only` until an explicit migration | Direct parsing and migration must continue; daemon projections cannot become the only way to view legacy projects. | Epic 2 parser compatibility; Epic 4 shadow diff; Epic 7/10 recovery | `added by Phase 1B` for portable active/archive `.gp` fixtures |
| VCS and CL/PR metadata | Git workspaces, bare-git provider state, hosted VCS plugin state, ChangeSpec commit drawers | `src/sase/vcs_provider/`, `src/sase/workspace_provider/`, `src/sase/ace/deltas/`, `src/sase/workflows/commit/`, commit/restore/revert handlers | `host-adapter only` for VCS side effects; `daemon-read candidate` for cached summaries | Commit, submit, restore, revert, status, diff, and hook workflows must call providers directly without requiring a daemon. | Epic 5 metadata reads; Epic 6/7 only after side-effect contracts exist; Epic 8 provider host isolation | `missing` for provider side effects; Phase 1B should only fixture parsed summaries where hermetic |
| Agent run artifacts | `~/.sase/projects/<project>/ace-run/<timestamp>/` and workflow artifact directories with metadata, prompts, replies, markers, HITL files, and attachments | `src/sase/agent/running.py`, `src/sase/ace/tui/models/agent_loader.py`, `src/sase/core/agent_scan_facade.py`, `../sase-core/crates/sase_core/src/agent_scan/` | `daemon-read candidate` for indexed list/search/detail; lifecycle mutation is future `daemon-write candidate`; process operations stay `host-adapter only` | CLI/ACE/mobile helpers must scan artifact directories directly when projection state is unavailable or stale. | Epic 2 agent/artifact events; Epic 4 watcher/shadow diff; Epic 5 read APIs; Epic 7 lifecycle ownership; Epic 9 ACE virtualization | `existing` for scanner parity helpers and `tests/agent_scan_golden/`; `added by Phase 1B` for waiting/HITL, retry, parent/child workflow, stale/missing artifact cases |
| Explicit artifacts | Agent artifact directories plus explicit artifact metadata and file associations | `src/sase/main/artifact_handler.py`, `src/sase/core/agent_artifact_explicit.py`, `src/sase/core/agent_artifact_*`, `src/sase/ace/tui/modals/agent_artifacts_modal.py` | `daemon-read candidate` for metadata; file copy/open/render remains `host-adapter only` | Direct metadata and file path access must remain for CLI, ACE, and local viewers. | Epic 2 artifact records; Epic 4 watcher; Epic 5 artifact reads; Epic 9 lazy detail/artifact loads | `added by Phase 1B` |
| Dismissed identities | Dismissed identity state for active and archived agents | `src/sase/ace/dismissed_agents.py`, `dismissed_agents_state.py`, `dismissed_agents_paths.py`, `src/sase/core/agent_cleanup_*`, Rust cleanup planners | `daemon-read candidate`; selected archive/dismiss mutations are future `daemon-write candidate` | ACE revive/cleanup and direct recovery must work from persisted identity state even if indexes are dropped. | Epic 2 archive projections; Epic 4 watcher; Epic 6 cleanup/dismiss writes; Epic 10 recovery | `existing` for focused dismissed-agent helpers; `added by Phase 1B` for daemon corpus coverage |
| Dismissed bundles | `~/.sase/dismissed_bundles/YYYYMM/*.json` plus legacy bundle layouts where supported | `src/sase/ace/dismissed_agents_bundles.py`, `dismissed_agents_migrations.py`, `src/sase/ace/dismissed_bundle_index/`, `../sase-core/crates/sase_core/src/agent_archive/` | `daemon-read candidate`; bundle persistence remains Python-owned until write contract | Revive/archive commands must read bundle JSON directly when indexes are absent, stale, or corrupt. | Epic 2 archive projections; Epic 4 shadow diff; Epic 6 archive writes; Epic 10 doctor/rebuild | `added by Phase 1B`, including legacy bundle layout |
| Notifications JSONL | `~/.sase/notifications/notifications.jsonl` | `src/sase/notifications/store.py`, `src/sase/core/notification_store_facade.py`, `src/sase/main/notify_handler.py`, ACE notification widgets/modals, `../sase-core/crates/sase_core/src/notifications/` | `daemon-read candidate`; mark/read/dismiss/snooze/action state is future `daemon-write candidate` | JSONL reads and state rewrites must continue directly, including corrupt/partial-row tolerance currently covered by store behavior. | Epic 2 notification events/projections; Epic 4 watcher; Epic 5 notification reads; Epic 6 notification writes | `existing` through `tests/fixtures/notifications/`, `tests/notification_store/`, and Rust parity tests; `added by Phase 1B` for stale/action-backed corpus breadth |
| Pending action stores | `~/.sase/pending_actions/actions.json` and legacy `~/.sase/telegram/pending_actions.json` | `src/sase/notifications/pending_actions.py`, mobile notification action side effects, `../sase-core/crates/sase_core/src/notifications/pending_actions.rs`, `../sase-core/crates/sase_gateway/src/host_bridge.rs` | `daemon-read candidate`; action response is future `daemon-write candidate` | Mobile, ACE, and CLI action handling must directly resolve current and legacy action files. | Epic 2 action events; Epic 5 action reads; Epic 6 action writes; Epic 10 recovery | `added by Phase 1B` |
| Bead stores | Checkout-local `sdd/beads/issues.jsonl`, `config.json`, metadata, optional SQLite/cache artifacts | `src/sase/main/parser_bead.py`, `src/sase/main/bead_fast_path.py`, `src/sase/bead/`, `src/sase/core/bead_*_facade.py`, `../sase-core/crates/sase_core/src/bead/` | `daemon-read candidate` for list/show/ready/blocked/stats; create/update/dep/work are future `daemon-write candidate`; work launch remains host-owned | `sase bead` must continue to operate on the current checkout store without reading sibling workspaces or daemon projections. | Epic 2 bead events/projections; Epic 4 watcher; Epic 5 bead reads; Epic 6 bead writes; Epic 7 bead work launch queue | `existing` through `tests/test_bead/golden/`, `tests/test_bead/`, and Rust bead parity tests; `added by Phase 1B` for work-plan outputs and corrupt/legacy rows in the daemon corpus |
| SDD documents | `sdd/prompts/`, `sdd/tales/`, `sdd/epics/`, `sdd/legends/`, `sdd/myths/`, `sdd/research/`, frontmatter, links | `src/sase/sdd/`, `src/sase/main/sdd_handler.py`, bead design links, plan/tale/epic automation | `unchanged`; later `daemon-read candidate` for catalog/search only | Files must stay human-editable and directly repairable; validation must not need daemon state. | Epic 4 file catalog shadowing; Epic 5 catalog reads; Epic 10 recovery docs | `added by Phase 1B` for daemon catalog inputs |
| Workflow runtime state | `workflow_state.json`, step markers, prompt/script output markers, HITL request/response files under artifact directories | `src/sase/xprompt/workflow_*`, `workflow_runner.py`, `workflow_hitl.py`, `src/sase/main/query_handler/_query.py`, ACE workflow models/actions, axe workflow runners | Execution is `host-adapter only`; state indexing is `daemon-read candidate`; HITL/state changes are future `daemon-write candidate` | Workflows must recover from files and markers directly; user-authored bash/Python steps stay out of the daemon. | Epic 2 workflow events/projections; Epic 4 watcher; Epic 6 workflow state writes; Epic 7 durable workflow scheduler | `added by Phase 1B` |
| Xprompt catalogs | Package xprompts, `src/sase/default_xprompts/`, project/user xprompt directories, `xprompts/`, config references, dynamic-memory-like inputs, skill refs | `src/sase/xprompt/loader*.py`, `catalog*.py`, `processor.py`, `src/sase/main/xprompt_handler.py`, `src/sase/integrations/xprompt_lsp.py`, `../sase-core/crates/sase_core/src/xprompt_catalog.rs`, `../sase-core/crates/sase_xprompt_lsp/` | `daemon-read candidate` for catalog/completion/search; expansion/execution remains host-owned | CLI/editor/LSP must still scan package, user, and project catalogs directly. | Epic 4 catalog watcher; Epic 5 editor/xprompt reads; Epic 8 plugin/resource host isolation | `existing` for xprompt loader/catalog tests; `added by Phase 1B` for portable multi-source catalog corpus |
| Prompt, chat, command, and file-reference history | `~/.sase/prompt_history.json`, `~/.sase/chats/YYYYMM/*.md`, command history, `~/.sase/file_reference_history.json`, VCS xprompt MRU | `src/sase/history/prompt.py`, `chat.py`, `command.py`, `file_references.py`, `vcs_xprompt_mru.py`, `src/sase/main/chats_handler.py`, `file_history_handler.py` | `daemon-read candidate`; writes stay host-owned until a history transaction contract exists | Run/resume and helper commands must read/write the JSON/Markdown history files directly. | Epic 2 history/file events; Epic 4 watcher; Epic 5 file-history reads | `existing` for history unit tests; `added by Phase 1B` for daemon fixture manifest |
| Axe scheduler state, checks, and logs | `~/.sase/axe/`, axe process/lock state, hook/mentor/comment/workflow outputs, chop/lumberjack configs, run logs | `src/sase/axe/`, `src/sase/main/axe_handler.py`, ACE axe widgets/actions, `src/sase/ace/scheduler/` | `host-adapter only` now; scheduler state is future `daemon-write candidate`; logs are deferred indexed reads | Scheduler start/stop/checks/chops must continue via current host files, locks, and subprocesses. | Epic 7 scheduler/lifecycle; Epic 10 log retention/recovery | `missing` for environment-specific subprocess/log behavior; Phase 1B may add small hermetic state/log fixtures |
| Mobile gateway state and routes | Existing `sase_gateway` `/api/v1` contract snapshot, pairing/session/push storage, audit log, notification/pending-action bridge files | `../sase-core/crates/sase_gateway/src/routes.rs`, `wire.rs`, `contract.rs`, `host_bridge.rs`, `storage.rs`, `src/sase/main/mobile_handler.py`, `src/sase/integrations/mobile_*` | Mobile API is `unchanged`; local daemon framed JSON must be additive and separate; host bridge side effects are `host-adapter only` | Existing HTTPS/SSE mobile routes and host bridge commands must continue without a local daemon read API. | Epic 1D local daemon contract; Epic 3 runtime/transport; Epic 5 mobile/read coexistence | `existing` for mobile gateway and mobile helper tests plus `../sase-core/crates/sase_gateway/contracts/api_v1/mobile_api_v1.json`; `added by Phase 1B` for source-store bridge fixtures |
| Editor helpers and LSP | Project filesystem, xprompt catalogs, helper bridge stdin/stdout JSON, LSP process state | `src/sase/main/parser_editor.py`, `src/sase/integrations/editor_helpers.py`, `src/sase/integrations/xprompt_lsp.py`, `../sase-core/crates/sase_core/src/editor/`, `../sase-core/crates/sase_xprompt_lsp/` | `daemon-read candidate` for catalogs/completion; editor protocol process remains `host-adapter only` | Editor helpers must retain direct scan/fallback paths and must not require ACE/Textual imports. | Epic 5 editor reads; Epic 8 provider/resource isolation | `existing` for editor/xprompt LSP helper tests; `added by Phase 1B` for daemon catalog snapshots |
| Provider subprocesses | Provider CLIs, environment variables, model configs, provider artifacts, runtime hooks and skills | `src/sase/llm_provider/`, subprocess wrappers, provider registry, plugin managers | `host-adapter only` | `sase run`, retry, workflows, axe, and mobile launches must invoke providers directly through the host adapter. | Epic 7 lifecycle coordination; Epic 8 provider host IPC | `missing`; should be tested through launch/provider unit fixtures, not daemon source-store fixtures |
| Plugin boundaries | LLM, VCS, workspace, config/resource plugins and discovery metadata | `src/sase/llm_provider/_plugin_manager.py`, `src/sase/vcs_provider/_plugin_manager.py`, `src/sase/workspace_provider/_plugin_manager.py`, `src/sase/main/plugin_discovery.py` | `host-adapter only`; daemon plugin IPC is deferred | Plugin discovery and execution must remain Python-owned until an explicit host IPC contract exists. | Epic 8 plugin/provider host isolation | `existing` for plugin-manager tests; daemon execution fixtures are `missing` |
| Recovery, doctor, logs, repair, and no-daemon commands | Current source stores, logs, artifact directories, bead stores, Rust health state | `src/sase/main/core_handler.py`, `src/sase/logs/`, `src/sase/agents/cli_index.py`, bead doctor/sync, SDD validate/repair | `unchanged`; always direct-source first | These commands must never require a healthy daemon; they are the repair path for daemon/projection failure. | Epic 10 recovery/operations; all later epics must preserve direct fallback | `existing` for logs, bead, agent index, and health tests in pieces; `added by Phase 1B` for integrated recovery corpus |

## CLI and User-Facing Behavior Matrix

| Surface | Current behavior to preserve | Classification | Direct fallback expectation | Likely daemon dependency | Fixture coverage |
|---|---|---|---|---|---|
| `sase run` and plain prompt execution | Parses prompt text/directives, resolves refs, expands xprompts/workflows, writes history/artifacts, invokes provider, emits notifications | Execution is `host-adapter only`; preflight catalog/history/status reads are `daemon-read candidate` | Direct provider launch, workspace allocation, artifact writes, and history writes remain mandatory. | Epic 7 lifecycle queue; Epic 8 provider host isolation | `existing` for prompt/xprompt/launch pieces; `added by Phase 1B` for combined history/artifact fixture |
| Multi-agent prompts and xprompt workflows | Splits `---` segments, launches child agents/workflows, records parent/child metadata and workflow state | Spawning/execution is `host-adapter only`; lifecycle/state indexing is future `daemon-write candidate` | Parent/child metadata and workflow files remain readable without daemon state. | Epic 2 events; Epic 7 durable scheduler | `existing` for multi-prompt/xprompt workflow tests; `added by Phase 1B` for parent/child artifact corpus |
| Resume and retry | Loads chat/artifact history, prepares provider-specific continuation, writes new attempt state | Provider continuation is `host-adapter only`; lineage/history lookup is `daemon-read candidate` | Must recover from chat Markdown and artifact directories directly. | Epic 2 agent/history projections; Epic 5 reads; Epic 7 attempts | `existing` for history and mobile resume tests; `added by Phase 1B` |
| Plan/question/HITL commands | Write request/response files and actionable notifications, wait for human approval/feedback | UI/provider side effects are `host-adapter only`; action state is future `daemon-write candidate` | HITL files and notification JSONL must remain sufficient for direct handling. | Epic 2 notification/workflow events; Epic 6 action writes; Epic 7 workflows | `added by Phase 1B` |
| `sase changespec current/search/sync-deltas/migrate-extension` | Reads/searches project specs, computes deltas, migrates legacy extension state | Reads are `daemon-read candidate`; deltas/migrations are `host-adapter only` or future write candidate | Direct project-file parser/query path remains required. | Epic 5 ChangeSpec reads; Epic 6 status/comment writes | `existing` for parser/query/migration pieces; `added by Phase 1B` for legacy corpus |
| Commit, restore, and revert | Executes commit workflow, hooks, VCS side effects, archive/restore metadata | `host-adapter only` for execution; metadata reads are `daemon-read candidate` | VCS/workspace provider path stays authoritative for side effects. | Epic 6 after write contracts; Epic 8 provider isolation | `existing` for commit workflow fixtures; daemon coverage is `missing` |
| `sase agents` | Lists/shows/status/kills/tags/archive/index/rebuild/verify agent runs | List/show/status/archive reads are `daemon-read candidate`; kill/tag/archive writes are future write candidates; process kill is `host-adapter only` | Direct artifact scan and index rebuild/verify must stay available. | Epic 5 agent reads; Epic 7 lifecycle operations | `existing` for scan/index/tag/archive tests; `added by Phase 1B` for large representative corpus |
| `sase notify` and ACE/mobile notification actions | Lists/shows/sends/updates notifications and action-backed records | `daemon-read candidate`; state/action mutations are future `daemon-write candidate` | JSONL and pending-action direct paths remain required. | Epic 5 notification reads; Epic 6 notification/action writes | `existing`; Phase 1B expands corpus |
| `sase bead` | `init/create/list/show/ready/open/update/close/rm/dep/blocked/sync/stats/doctor/onboard/work` over checkout-local stores | Reads are `daemon-read candidate`; mutations are future `daemon-write candidate`; `work` launch is `host-adapter only` | Checkout-local JSONL/config operations must continue without daemon and without cross-workspace merge reads. | Epic 5 bead reads; Epic 6 bead writes; Epic 7 work launches | `existing` via golden/parity tests; Phase 1B adds daemon manifest coverage |
| `sase sdd` | Init/validate/links/list/repair SDD documents and frontmatter | `unchanged`; catalog/search later `daemon-read candidate` | Direct filesystem validation and repair remain required. | Epic 4 catalog watcher; Epic 10 repair | `added by Phase 1B` |
| `sase xprompt`, `sase editor`, and `sase lsp` | Expands/explains/graphs/catalogs xprompts; serves editor helper bridge and LSP | Catalog/completion reads are `daemon-read candidate`; protocol process and expansion remain host-owned | Direct catalog scan must stay available and lightweight. | Epic 5 editor/catalog reads; Epic 8 resource host | `existing`; Phase 1B adds project/user/package catalog fixtures |
| `sase mobile` | Starts gateway, handles agent/helper/notification bridges, preserves `/api/v1` contract | Existing mobile gateway is `unchanged`; local daemon API is separate | Mobile bridge commands continue to call host adapters and source stores directly. | Epic 1D contract; Epic 3 local daemon runtime | `existing` mobile tests and mobile contract snapshot; Phase 1B adds bridge fixtures |
| `sase axe` | Starts/stops scheduler, runs chops/lumberjacks/maintenance, executes checks and agents | `host-adapter only` initially; scheduler state is deferred daemon-write candidate | Current locks, process state, shell/provider execution, and logs remain direct. | Epic 7 scheduler/lifecycle | `missing` for daemon corpus; small hermetic state fixtures can be added by Phase 1B |
| `sase artifact`, `sase file`, `sase file-history`, `sase chats`, `sase logs`, `sase revive-log` | Creates explicit artifacts, lists file refs/history/chats/log bundles, opens local paths | Reads are possible `daemon-read candidate`; local file open/copy/log pack stays `host-adapter only` | Direct JSON/Markdown/filesystem operations remain required. | Epic 5 history/artifact reads; Epic 10 recovery/log retention | `existing` in unit tests; Phase 1B adds representative corpus |
| `sase core health`, `path`, `config`, `init-git`, `init-skills`, telemetry, repro | Health/config/dev/repro/setup surfaces | Mostly `unchanged` or `host-adapter only`; telemetry summaries may become read candidates later | These commands should avoid daemon dependence unless explicitly testing daemon health. | Epic 10/11 operations and rollout controls | `existing` in focused tests; daemon corpus generally `missing` |

## ACE, Axe, Mobile, and Editor Gap Map

| Surface group | Move/keep decision | Gap to close before routing |
|---|---|---|
| ACE ChangeSpecs | Indexed list/search/detail are `daemon-read candidate`; status/archive/comment mutations wait for write contracts. | Need `.sase` plus legacy `.gp` active/archive fixtures, shadow-diff tooling, paged query contract, and direct source fallback. |
| ACE Agents | Active/recent/archive list/search/detail are `daemon-read candidate`; kill/dismiss/revive/cleanup side effects stay host-owned until lifecycle/write epics. | Need artifact corpus covering running, waiting/HITL, done, failed, killed/stale, retry, parent/child workflow, explicit artifacts, dismissed identities, and bundles. |
| ACE Notifications | Counts/list/detail/actions are `daemon-read/write candidate` after notification and pending-action contracts. | Need action-backed, snoozed, dismissed, stale, duplicate, missing-target, and legacy pending-action fixtures. |
| ACE Artifacts | Metadata can be daemon-backed; image rendering, terminal viewers, file opens, and local copy/move stay host-owned. | Need explicit artifact association fixtures and lazy detail snapshots. |
| ACE AXE dashboard | Scheduler/check execution remains host-owned until Epic 7; indexed status/log summaries are deferred. | Need hermetic scheduler state/log fixtures and process-control boundary tests. |
| ACE grouping/filtering/search | Facets/counts/query handles are daemon-read candidates; selection/key handling remains Textual-owned. | Need paged/faceted read contract and no-change refresh perf baselines. |
| ACE revive/cleanup/dismiss | Archive and cleanup metadata can become daemon writes later; process kill/signals and confirmation UI stay host-owned. | Need bundle/identity fixtures and idempotent mutation contracts. |
| Mobile gateway | Existing `/api/v1` HTTP/SSE route contract remains unchanged. Local daemon framed JSON must be versioned separately. | Phase 1D must add a separate local daemon contract snapshot without blending it with mobile `/api/v1`. |
| Editor helpers/LSP | Catalog/completion reads can route to daemon later; LSP/editor protocol process and direct scan fallback stay. | Need catalog fixtures spanning package, project, user, config, dynamic-memory-like entries, and missing/invalid xprompts. |
| Axe scheduler/checks | Host-owned until daemon lifecycle and scheduler ownership are designed. | Need explicit scheduler state model and host side-effect IPC before daemon writes. |

## Do Not Move Yet

The following behavior must remain Python/host-owned for now, even if later daemon APIs index its metadata:

- Provider subprocess invocation for Claude, Gemini, Codex, Qwen, OpenCode, plain subprocess, and plugin providers.
- Plugin discovery and execution for LLM, VCS, workspace, config/resource, and xprompt providers.
- User-authored workflow script steps, shell/Python steps, external command execution, HITL prompts, and workflow side
  effects.
- VCS side effects: commit, amend, submit/mail, restore, revert, sync, diff, branch/worktree operations, hooks, and PR
  metadata updates.
- Textual rendering, keyboard handling, command palette state, modal state, terminal graphics, and viewer loops.
- Editor protocol/LSP process ownership and local editor bridge process lifetime.
- Local file open/viewer actions and explicit artifact copy/move operations.
- Axe process control, scheduler start/stop, checks, chops, lumberjacks, mentors, and log streaming.
- Recovery, doctor, migration, import/export, log pack, source-store repair, and no-daemon fallback commands.

## Phase 1B Fixture Backlog

Phase 1B should add a fixture manifest under `tests/fixtures/rust_daemon_epic1/` that maps each family above to source
paths, normalized expected snapshots, and matrix rows. The highest-priority missing fixtures are:

- Legacy `.gp` active/archive project specs beside canonical `.sase` active/archive specs.
- Notification JSONL rows covering unread, read, dismissed, snoozed, stale, attachment-backed, and action-backed states.
- Current and legacy pending-action files, including already-handled, missing-target, duplicate, and ambiguous-prefix
  cases.
- Agent artifact trees for running, waiting/HITL, done, failed, killed/stale, retry, parent/child workflow, missing
  artifacts, stale markers, explicit artifacts, dismissed identities, dismissed bundle JSON, and legacy bundle layout.
- Bead stores covering hierarchy, dependencies, ready/blocked, ChangeSpec metadata, epic/legend metadata, model routing,
  work-plan outputs, corrupt rows, and legacy schema rows.
- Workflow `workflow_state.json`, step markers, prompt/script outputs, HITL request/response files, recovery cases, and
  partial runs.
- Xprompt package/user/project catalogs, invalid/missing xprompts, config references, dynamic-memory-like entries, skill
  references, prompt history, chat history, command history, VCS xprompt MRU, and file-reference history.
- Small hermetic axe scheduler/log fixtures that avoid launching real background jobs.

## Later Epic Readiness

Later epics can use this matrix as follows:

- Epic 2 should use source-family rows as the event/projection boundary and keep source-store replay deterministic.
- Epic 3 should keep the existing mobile gateway route contract separate from the local daemon framed JSON contract.
- Epic 4 should shadow-index these source families and diff daemon projections against current loaders before routing
  user-visible reads.
- Epic 5 should start with `daemon-read candidate` rows that already have fixtures and byte-compatible output tests.
- Epic 6 should only migrate `daemon-write candidate` rows after idempotency, source export, locks, and direct fallback
  are explicit.
- Epic 7 should own scheduler/agent/workflow lifecycle only after host-adapter subprocess and provider boundaries are
  structured.
- Epic 8 should isolate provider/plugin host calls without assuming any supported runtime lacks hooks, skills,
  artifacts, or commit workflow support.
- Epic 9 should adapt ACE through paged/delta data providers while preserving the current loader fallback.
- Epic 10 should treat recovery, doctor, source repair, and no-daemon commands as non-negotiable direct paths.
- Epic 11 should expose rollout controls for disabled, shadow, read-through, write-through, and authoritative modes.

## Phase Handoff

Complete:

- Reconciled the Epic 0 inventory with the Epic 1 legend and the current `docs/architecture.md` /
  `docs/rust_backend.md` boundary.
- Produced an Epic 1 compatibility matrix that records classifications, source of truth, loader/mutator entry points,
  direct fallback expectations, later epic dependencies, and fixture coverage status.
- Added a Do Not Move Yet section explicitly preserving Python/host-owned behavior and no-daemon recovery paths.

Intentionally deferred:

- No production routing, daemon transport, projection store, fixture corpus, perf harness, or contract snapshot was
  implemented in this phase.
- Fixture creation belongs to Phase 1B; performance baselines belong to Phase 1C; local daemon wire snapshots belong to
  Phase 1D.

Validation:

- Run `just check` after the required workspace install step for repository-level validation.
