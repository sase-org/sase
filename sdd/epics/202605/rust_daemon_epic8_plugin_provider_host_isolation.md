---
create_time: 2026-05-14 05:02:58
status: wip
prompt: sdd/prompts/202605/rust_daemon_epic8_plugin_provider_host_isolation.md
---
# Plan - Rust Daemon Epic 8 Plugin and Provider Host Isolation

## Context

Epic 8 from `sdd/legends/202605/rust_daemon_indexed_projections_1.md` isolates provider and plugin execution so pure
read-query paths do not pay Python import, pluggy discovery, provider CLI, or plugin side-effect costs.

Current useful substrate:

- Provider and plugin systems are Python pluggy entry points:
  - `sase_llm` in `src/sase/llm_provider/`
  - `sase_vcs` in `src/sase/vcs_provider/`
  - `sase_workspace` in `src/sase/workspace_provider/`
  - maintained external GitHub implementations in `../sase-github`
- `../sase-core/crates/sase_core/src/host_bridge.rs` already defines command-backed helper bridge plumbing for mobile
  helper calls.
- `../sase-core/crates/sase_gateway/src/host_bridge.rs` already has command-backed mobile agent/helper bridges.
- Local daemon framed JSON already has health, capabilities, reads, writes, scheduler, event streams, contract
  snapshots, typed fallback errors, and Python client plumbing under `src/sase/daemon/`.
- Earlier epics intentionally keep provider, plugin, VCS, workspace, shell, Python workflow, and process side effects in
  Python while Rust owns deterministic state, queueing, validation, event append, and projections.

The migration should build one durable host boundary instead of adding one-off bridge commands for each provider. The
daemon can request host work, validate declared capabilities and side-effect intents, and decide whether to keep a
Python host warm. The Python host remains the implementation owner for existing providers/plugins.

## Goals

- Pure daemon-backed read APIs and ACE navigation must not import LLM/VCS/workspace/plugin packages.
- Preserve existing provider/plugin behavior, including built-in LLM providers, bare-git providers, GitHub plugin
  providers, xprompt/config plugin sources, and workflow step execution.
- Introduce stable versioned IPC schemas for provider/plugin calls, typed errors, structured logs, cancellation, and
  side-effect intents.
- Keep Rust responsible for host policy: capability checks, manifest checks, timeouts, cancellation, backpressure,
  daemon starvation protection, and validation before state mutation.
- Keep Python responsible for execution side effects: provider CLIs, VCS commands, workspace setup/submit, plugin
  discovery, Python/bash workflow steps, and compatibility with current pluggy hooks.
- Make the v1 contract compatible with a future WASM host, without requiring Extism/Wasmtime in this epic.

## Non-Goals

- Do not rewrite providers or plugins in Rust.
- Do not require all plugins to ship a new manifest before compatibility wrappers exist.
- Do not route launch/scheduler/workflow execution before Epic 7 queue and lifecycle contracts are ready.
- Do not remove no-daemon/direct Python fallback paths.
- Do not sandbox so aggressively in early phases that existing local providers stop working by default.
- Do not make SQLite projections depend on host-only data that cannot be rebuilt or revalidated.

## Cross-Phase Design

Use a single host IPC vocabulary across LLM, VCS, workspace, config/resource, xprompt, and workflow-step calls:

- `HostRequestEnvelope`: schema version, request id, deadline, cancellation token, actor/client metadata, operation,
  declared capabilities, workspace/project identity, environment policy, and JSON payload.
- `HostResponseEnvelope`: schema version, request id, status, result payload, typed error, captured logs, duration,
  resource usage where available, and side-effect intents.
- Operation families:
  - `llm.invoke`, `llm.resolve_model`, `llm.metadata`
  - `vcs.query`, `vcs.mutation`, `vcs.commit_dispatch`
  - `workspace.resolve_ref`, `workspace.setup`, `workspace.submit`, `workspace.metadata`
  - `xprompt.catalog`, `config.resources`
  - `workflow.step.python`, `workflow.step.bash`
- Side-effect intent families:
  - filesystem writes/deletes/moves under declared roots;
  - process spawn/kill;
  - VCS mutation;
  - network request intent;
  - notification/pending-action mutation request;
  - workflow state transition request.
- Error families:
  - `host_unavailable`
  - `host_timeout`
  - `host_cancelled`
  - `plugin_not_found`
  - `operation_unsupported`
  - `capability_denied`
  - `network_denied`
  - `resource_limit_exceeded`
  - `invalid_side_effect_intent`
  - `host_protocol_error`
  - provider-specific execution failures with sanitized stderr/stdout summaries

The Rust daemon should never blindly apply host side effects. Host results either return pure data or return intents
that Rust validates against the request, manifest, current daemon state, and existing write/scheduler contracts.

## Phase 8A - Contract Inventory and Isolation Boundaries

Purpose: produce a complete compatibility map and choose the first narrow verticals before writing runtime machinery.

Primary ownership:

- `sdd/` planning or design notes for Epic 8
- focused test fixtures under this repo and optionally `../sase-github`
- no production routing changes

Deliverables:

- Inventory every pluggy hook and provider operation in `sase_llm`, `sase_vcs`, `sase_workspace`, `sase_config`, and
  `sase_xprompts`, including built-in and `../sase-github` entry points.
- Classify operations as pure metadata, pure query, bounded side-effect query, durable mutation, long-running execution,
  or workflow step execution.
- Record import-cost and command-cost baselines for representative pure read commands, daemon reads, `sase run`
  preflight, LLM metadata lookup, VCS detect/query, workspace resolve, and xprompt catalog load.
- Define which operations must be host-isolated in v1 and which remain direct Python fallback.
- Define manifest fields for v1: plugin id, version, operation families, network policy, filesystem roots, process
  policy, environment requirements, timeout hints, warm-host eligibility, and WASM-compatibility notes.
- Add compatibility fixtures for at least built-in bare-git, built-in LLM providers, and the GitHub plugin.

Acceptance gates:

- Each later phase can point at an operation inventory row, fixture, and compatibility expectation.
- The plan identifies the first low-risk routed operation and the first high-traffic routed operation.
- No command behavior changes yet.

Suggested phase prompt:

> Implement Phase 8A from `sase_plan_rust_daemon_epic8_plugin_provider_host_isolation.md`: inventory provider/plugin
> operations, classify side effects, define v1 manifest requirements, and add compatibility fixtures/baselines. Do not
> route production calls yet.

## Phase 8B - Shared Host IPC Contract and Capability Negotiation

Purpose: add versioned Rust/Python wire types and daemon capabilities without starting a real warm host.

Primary ownership:

- `../sase-core/crates/sase_core/src/host_bridge.rs` or new `provider_host` module
- `../sase-core/crates/sase_gateway/src/{wire.rs,contract.rs,local_transport.rs,metrics.rs}`
- `src/sase/daemon/` protocol/client models
- new Python host wire dataclasses under `src/sase/host/` or equivalent
- contract/unit tests only

Deliverables:

- Add shared serde wire structs for host request/response envelopes, operation selectors, deadline/cancellation fields,
  logs, typed errors, resource reports, manifest declarations, and side-effect intents.
- Add local daemon capability names such as `host.ipc.v1`, `host.manifest.v1`, `host.llm.metadata`, and
  `host.xprompt.catalog`, but advertise only foundation capabilities until routed verticals land.
- Add contract snapshot entries for the host IPC schema and error vocabulary.
- Add Python encode/decode helpers that preserve unknown fields for forward compatibility.
- Add validation helpers in Rust for operation family, request size, timeout bounds, declared capability checks, and
  side-effect intent shape.
- Add fake in-process host transport for Rust/Python tests.

Acceptance gates:

- Contract snapshot tests fail on accidental incompatible wire changes.
- Malformed host requests and invalid side-effect intents produce typed fallbackable daemon errors.
- No production provider/plugin call is routed yet.

Suggested phase prompt:

> Implement Phase 8B from `sase_plan_rust_daemon_epic8_plugin_provider_host_isolation.md`: add shared provider/plugin
> host IPC wire contracts, daemon capability negotiation, validation helpers, Python wire models, and contract tests
> without routing production calls.

## Phase 8C - Python Host Subprocess Runtime

Purpose: create the isolated Python host process with timeout, cancellation, log capture, and optional warm reuse.

Primary ownership:

- new `src/sase/host/` package
- daemon host manager in `../sase-core/crates/sase_gateway`
- CLI entry point or hidden subcommand for the Python host process
- focused process/runtime tests

Deliverables:

- Add a Python host command that speaks framed JSON over stdio using the Phase 8B envelopes.
- Implement host-side operation dispatch scaffolding with no-op/fake operations and a narrow allowlist.
- Add plugin discovery inside the host process, not in daemon read paths.
- Add structured stdout/stderr/log capture with size limits and redaction hooks for tokens, provider secrets, and
  command-line credentials.
- Add per-call wall-clock timeout defaulting to 30 seconds, cancellation by request id, and child-process cleanup for
  operations that spawn commands.
- Add daemon-side host manager:
  - on-demand spawn;
  - optional warm process with idle shutdown;
  - bounded concurrent calls;
  - backpressure errors instead of blocking tokio workers;
  - health/status metrics.
- Add direct Python fallback so no-daemon commands still call existing providers exactly as today.

Acceptance gates:

- A fake operation can round-trip through a real Python host subprocess from the daemon with captured logs.
- Timeout and cancellation tests prove host calls cannot hang daemon request handling.
- Pure daemon read tests can run without importing `sase.llm_provider`, `sase.vcs_provider`, or plugin entry points.

Suggested phase prompt:

> Implement Phase 8C from `sase_plan_rust_daemon_epic8_plugin_provider_host_isolation.md`: add the Python host
> subprocess runtime, daemon host manager, timeout/cancellation/log capture, and fake-operation tests. Do not route real
> provider behavior yet.

## Phase 8D - Manifest and Resource Policy Enforcement

Purpose: make host execution policy explicit before routing side-effecting providers.

Primary ownership:

- `src/sase/host/` manifest loading and compatibility defaults
- built-in provider/plugin metadata in this repo
- optional `../sase-github` manifest metadata
- daemon policy enforcement in `../sase-core/crates/sase_gateway`

Deliverables:

- Add manifest discovery for installed plugins and built-in compatibility manifests for existing providers that do not
  ship manifest files yet.
- Enforce manifest-declared operation families before dispatch.
- Enforce network policy at the operation boundary:
  - v1 default is compatibility mode for known built-ins;
  - external plugins must declare network use before daemon-authoritative routing;
  - denied network operations return typed `network_denied`.
- Add resource-limit hooks:
  - wall-clock timeout from manifest/request bounded by daemon policy;
  - RSS soft cap where available;
  - cgroup v2 CPU quota on Linux where available;
  - seccomp/sandbox profile detection and opt-in enforcement where practical.
- Add user-facing diagnostics through daemon health/capabilities explaining which limits are active, unavailable, or in
  compatibility mode.
- Add tests with fake manifests for allowed, denied, and compatibility-mode operations.

Acceptance gates:

- A plugin cannot execute an undeclared operation through the daemon host path.
- Resource-limit support degrades explicitly on platforms where cgroup/seccomp/RSS enforcement is unavailable.
- Existing built-in and GitHub plugin behavior remains available through compatibility manifests.

Suggested phase prompt:

> Implement Phase 8D from `sase_plan_rust_daemon_epic8_plugin_provider_host_isolation.md`: add provider/plugin manifest
> discovery, capability checks, resource policy enforcement, and diagnostics, keeping existing providers compatible.

## Phase 8E - First Routed Vertical: Read-Only Metadata and Catalog Calls

Purpose: prove real provider/plugin routing on low-risk read-only calls and remove plugin imports from common read
paths.

Primary ownership:

- `src/sase/llm_provider/registry.py`
- `src/sase/xprompt/` catalog callers and daemon read adapters
- `src/sase/daemon/` host client helpers
- host operation handlers under `src/sase/host/`
- daemon local read/host handlers as needed

Deliverables:

- Route selected read-only calls through host IPC when daemon capability is present:
  - LLM provider metadata: provider names, model aliases, short labels, status colors, autodetect metadata, retry
    defaults;
  - model resolution helpers used during launch preflight;
  - xprompt/config/resource catalog calls that currently rely on plugin entry points.
- Keep direct Python fallback for no-daemon mode, unsupported host capability, and tests that intentionally exercise
  direct registries.
- Add import guard tests proving daemon-backed pure reads and ACE initial data loads do not import provider/plugin
  packages.
- Add parity tests comparing direct registry outputs to host-routed outputs for built-in providers and GitHub plugin
  fixtures.
- Add cache invalidation policy for host metadata keyed by plugin manifest fingerprint, environment, config version, and
  xprompt/resource source paths.

Acceptance gates:

- Pure daemon-backed read commands do not import LLM/VCS/workspace/plugin modules.
- Host-routed metadata matches direct Python results for fixtures.
- If the host is unavailable, existing command behavior falls back without user-visible regression.

Suggested phase prompt:

> Implement Phase 8E from `sase_plan_rust_daemon_epic8_plugin_provider_host_isolation.md`: route low-risk read-only LLM
> metadata and xprompt/config catalog calls through the isolated Python host with parity, fallback, and import-guard
> tests.

## Phase 8F - VCS and Workspace Host Calls with Validated Intents

Purpose: isolate side-effect-capable VCS/workspace providers while preserving Rust validation before durable state
changes.

Primary ownership:

- `src/sase/vcs_provider/`
- `src/sase/workspace_provider/`
- `src/sase/host/`
- daemon host validation and scheduler/write integration in `../sase-core/crates/sase_gateway`
- GitHub plugin compatibility tests in `../sase-github`

Deliverables:

- Route VCS/workspace pure query operations through host IPC in daemon-enabled paths:
  - VCS detect/classify;
  - branch/revision/change metadata;
  - diff/stat/file-at-revision queries;
  - workspace metadata, ref resolution, workspace directory calculation.
- Represent VCS/workspace mutations as host results plus side-effect intents where Rust needs to validate or sequence
  durable state changes.
- Keep dangerous mutations direct or shadow-routed until the matching Epic 6 write and Epic 7 scheduler surfaces can
  validate them end to end.
- Add manifest capability checks for VCS/workspace filesystem roots and network use.
- Add parity tests for built-in bare-git and `../sase-github` query operations.
- Add structured error mapping for provider command failures without leaking credentials.

Acceptance gates:

- Daemon-enabled VCS/workspace query paths use the host without importing plugin packages in the daemon process.
- Side-effect-capable operations cannot mutate daemon state unless Rust accepts the declared intent.
- Bare-git and GitHub plugin query behavior matches direct providers for fixtures.

Suggested phase prompt:

> Implement Phase 8F from `sase_plan_rust_daemon_epic8_plugin_provider_host_isolation.md`: route VCS/workspace query
> operations through the provider host, introduce validated side-effect intent handling, and keep dangerous mutations in
> direct/shadow mode until write/scheduler integration is ready.

## Phase 8G - LLM Invocation and Workflow-Step Host Integration

Purpose: move high-cost provider execution and workflow-step execution behind the same host boundary once scheduler
backpressure exists.

Primary ownership:

- `src/sase/llm_provider/`
- `src/sase/agent/` invocation paths
- `src/sase/xprompt/workflow_executor*.py`
- `src/sase/daemon/scheduler_host.py`
- daemon scheduler/host integration in `../sase-core/crates/sase_gateway`

Deliverables:

- Route `llm.invoke` through host IPC for daemon-scheduled agent launches, preserving prompt preprocessing,
  postprocessing, logging context, provider retry config, model override resolution, and usage reporting.
- Route Python/bash workflow step execution through host IPC where Epic 7 workflow scheduling is enabled.
- Add streaming/log events from host calls into daemon lifecycle/workflow projections without blocking scheduler queues.
- Enforce host concurrency and backpressure so misbehaving provider calls cannot starve daemon reads, writes, or event
  streams.
- Preserve direct invocation for no-daemon mode and emergency fallback.
- Add end-to-end tests for one provider per runtime family with fake provider implementations, plus cancellation,
  timeout, retry, and log-capture tests.

Acceptance gates:

- Existing provider behavior remains available for direct and daemon-scheduled launches.
- A timed-out or cancelled provider/workflow call records a durable typed failure without wedging the daemon.
- ACE/mobile/CLI scheduler status can show host call progress and failure summaries from daemon projections.

Suggested phase prompt:

> Implement Phase 8G from `sase_plan_rust_daemon_epic8_plugin_provider_host_isolation.md`: route daemon-scheduled LLM
> invocation and Python/bash workflow-step execution through the isolated host with streaming logs, cancellation,
> backpressure, and direct fallback.

## Phase 8H - Selective High-Traffic Migration and Rollout Gates

Purpose: turn isolated host routing on by default only where parity, performance, and recovery are proven.

Primary ownership:

- rollout config/defaults in this repo
- daemon capability and health reporting in `../sase-core/crates/sase_gateway`
- performance and soak tests across this repo, `../sase-core`, and `../sase-github`

Deliverables:

- Add feature flags/config for host routing modes:
  - `direct`
  - `shadow`
  - `host-preferred`
  - `host-required` for tests only
- Add shadow comparison for routed metadata/query operations where safe.
- Add performance gates:
  - pure daemon reads do not import provider/plugin packages;
  - host warm call latency stays within agreed thresholds;
  - host cold start is measured and visible;
  - daemon read/write/scheduler p95 is not affected by stuck host calls.
- Add operations diagnostics:
  - host process status;
  - active calls;
  - timeout/cancellation counts;
  - resource-limit availability;
  - manifest denial summaries.
- Enable host routing by default only for low-risk metadata/catalog/query paths after parity passes.
- Leave mutation-heavy provider paths gated until corresponding Epic 6/Epic 7 acceptance gates pass.

Acceptance gates:

- Hot read commands and ACE initial navigation stay plugin-import-free with host routing enabled.
- Misbehaving plugins produce bounded, typed failures and do not starve daemon runtime.
- Rollback to direct mode is one config/env change.

Suggested phase prompt:

> Implement Phase 8H from `sase_plan_rust_daemon_epic8_plugin_provider_host_isolation.md`: add rollout modes,
> diagnostics, shadow comparison, performance gates, and default-enable only the proven low-risk host-routed paths.

## Dependency Notes

- Phase 8A should land first.
- Phase 8B and 8C can be implemented by separate agents after 8A, but 8C should consume the final Phase 8B wire names.
- Phase 8D should precede side-effect-capable routing.
- Phase 8E can start after 8B/8C and can initially run without full resource limits if it is read-only.
- Phase 8F requires 8D for manifest enforcement and should stay query-focused until Epic 6 write validation can consume
  side-effect intents.
- Phase 8G should wait for enough Epic 7 scheduler/backpressure substrate to avoid reintroducing blocking launch paths.
- Phase 8H is the rollout phase and should not begin until at least one real vertical has parity and fallback tests.

## Cross-Repo Verification Expectations

For any phase that edits this repo, run `just install` first if the workspace has not been prepared, then run focused
tests and `just check` before completion.

For any phase that edits `../sase-core`, run the relevant Rust unit/contract tests and that repo's `just check`.

For any phase that edits `../sase-github`, run its focused tests and `just check`.

Each implementation phase should state whether it changed production routing, which capability flags it advertises, and
how direct fallback was verified.
