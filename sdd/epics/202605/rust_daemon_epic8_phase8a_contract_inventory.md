---
create_time: 2026-05-14 11:30:00
status: done
bead_id: sase-3e.8.1
phase: 8A
---
# Rust Daemon Epic 8 Phase 8A Contract Inventory

Phase 8A defines the compatibility map for isolating provider and plugin work
behind a future host boundary. It does not route production calls.

## Artifacts

- Operation inventory: `tests/fixtures/rust_daemon_epic8_phase8a/operation_inventory.json`
- Compatibility manifests: `tests/fixtures/rust_daemon_epic8_phase8a/compatibility_manifests.json`
- Local command/import baselines: `tests/fixtures/rust_daemon_epic8_phase8a/import_command_baselines.json`
- Fixture validation: `tests/test_rust_daemon_epic8_phase8a_fixtures.py`

## Inventory Scope

The inventory covers all current pluggy hook specs in:

- `sase_llm`: 12 hooks from `src/sase/llm_provider/_hookspec.py`
- `sase_vcs`: 55 hooks from `src/sase/vcs_provider/_hookspec.py`
- `sase_workspace`: 14 hooks from `src/sase/workspace_provider/_hookspec.py`

It also records the resource-plugin operations used by:

- `sase_config`: plugin `default_config.yml` discovery and config-layer
  loading through `src/sase/main/plugin_discovery.py` and
  `src/sase/config/core.py`
- `sase_xprompts`: plugin `xprompts/` markdown/workflow resource discovery
  through `src/sase/xprompt/loader_sources.py`,
  `src/sase/xprompt/workflow_loader.py`, and
  `src/sase/xprompt/_catalog_sources.py`

Provider/plugin entry points inspected:

- Built-in LLM providers: `claude`, `codex`, `gemini`, `opencode`, `qwen`
- Built-in VCS provider: `bare_git`
- Built-in workspace providers: `bare_git`, `cd`
- Maintained GitHub sibling plugin in `../sase-github`: `github` VCS,
  `github` workspace, `sase_github` config resources, and `sase_github`
  xprompt resources

## Classification Rules

- `pure_metadata`: deterministic metadata or string shaping with no command
  execution and no filesystem dependency beyond already loaded code/config.
- `pure_query`: filesystem/config read with no subprocess and no writes.
- `bounded_side_effect_query`: read-only query that imports plugins, spawns a
  bounded local command, or touches external APIs while intending no durable
  mutation.
- `durable_mutation`: operation that may change files, VCS state, remote
  review state, workspace allocation, notification/pending-action state, or
  other persistent state.
- `long_running_execution`: operation that runs an agent/provider CLI or other
  cancellable execution path and may produce logs/artifacts.
- `workflow_step_execution`: direct Python/bash workflow step execution. No
  current pluggy hook maps exactly to this class, but the host v1 vocabulary
  keeps the category for later workflow-step routing.

## V1 Isolation Decision

Host-isolated in v1:

- LLM metadata and model resolution (`llm.metadata`, `llm.resolve_model`)
- Xprompt/config resource catalog loading (`xprompt.catalog`,
  `config.resources`)
- VCS/workspace metadata and read-only queries that currently import pluggy
  providers on hot paths (`vcs.query`, `workspace.metadata`,
  `workspace.resolve_ref`)
- LLM invocation and VCS/workspace durable mutations once timeout,
  cancellation, manifest, and side-effect-intent validation land in later
  phases

Direct Python fallback in v1:

- No-daemon direct command paths
- Existing provider invocations when daemon host capabilities are absent
- Compatibility-mode providers without an explicit manifest
- Workflow step execution until a dedicated workflow-step host adapter exists

First low-risk routed operation: `llm.metadata` provider-name/model metadata
lookup. It is read-only, has clear fallbacks, and exercises entry-point loading
inside the host without side-effect intent validation.

First high-traffic routed operation: `xprompt.catalog`. It runs during prompt
completion, workflow discovery, `sase run` preflight, and ACE workflows, and it
currently imports resource plugins on common read paths.

## Manifest V1 Requirements

The compatibility manifests pin the required v1 fields:

- `plugin_id`
- `manifest_version`
- `entry_points`
- `operation_families`
- `classification_summary`
- `network_policy`
- `filesystem_roots`
- `process_policy`
- `environment_requirements`
- `timeout_hints`
- `warm_host_eligible`
- `wasm_compatibility_notes`
- `compatibility_mode`

The daemon must treat manifest declarations as policy input, not as proof that
host results are safe. Durable host results must return side-effect intents that
Rust validates against the request, manifest, daemon state, and existing write
contracts before applying any mutation.

## Baselines

`import_command_baselines.json` records local median wall-clock timings from
three cold subprocess runs on 2026-05-14 after `just install`. These numbers are
not pass/fail thresholds. They identify the import and command surfaces later
phases should improve or at least avoid regressing when moving plugin discovery
out of daemon read paths.

Notable local medians:

- `sase bead list --status=open`: 246.2 ms
- `sase daemon status --json`: 232.2 ms
- `sase run -l`: 661.7 ms
- `import sase.daemon.read_facade`: 276.6 ms
- `import sase.llm_provider.registry`: 355.7 ms
- LLM provider metadata lookup: 361.8 ms
- VCS detect current repo: 128.3 ms
- VCS current branch query: 170.0 ms
- Workspace workflow-name metadata: 116.0 ms
- Xprompt catalog load: 337.4 ms

