---
create_time: 2026-06-09 11:52:44
status: done
prompt: sdd/prompts/202606/doctor_command_mvp.md
bead_id: sase-4i
tier: epic
---
# Plan: Ambitious MVP for `sase doctor`

## Objective

Add a top-level `sase doctor` command that becomes the first troubleshooting command for SASE users. The MVP should be
fast, read-only, reliable in broken environments, pleasant to read in a terminal, and stable enough to attach as a
support artifact through JSON output.

The implementation should be split across independent phase agents. Each phase below is intentionally scoped so a
distinct agent can finish it, run checks, and leave a coherent commit before the next phase starts.

## Product Contract

The command shape for the MVP is:

```bash
sase doctor
sase doctor -j|--json
sase doctor -v|--verbose
sase doctor -D|--deep
sase doctor -s|--strict
sase doctor -L|--list-checks
sase doctor -C|--check <id-or-group>
sase doctor -p|--project <project>
```

All new options need both short and long forms, per `memory/short/gotchas.md`.

Default `sase doctor` is read-only and bounded. It must not launch agents, call LLM APIs, run tests, run linters, repair
state, clone workspaces, materialize sibling project metadata, or scan full artifact history.

Default exit behavior:

- `OK`, `WARN`, and `SKIP` exit `0`.
- `ERROR` exits `1`.
- `-s|--strict` makes `WARN` exit `1`.
- Argparse usage errors remain exit `2`.

Severity meanings:

- `OK`: check passed.
- `WARN`: degraded, optional, stale, or likely-to-confuse state; normal use may still work.
- `ERROR`: a required readiness condition failed.
- `SKIP`: intentionally not checked because the subsystem is not configured, not applicable, or not selected.

## UX Design

The default human output should be a polished Rich report, not a wall of text. It should show a concise summary panel,
then grouped check tables. In normal mode, show all non-OK checks and enough OK rows to prove core readiness. In verbose
mode, show every OK check and bounded detail.

Recommended visual shape:

```text
SASE Doctor  WARN

Runtime
  OK     runtime.core            sase_core_rs loaded; 4/4 probes passed
  WARN   runtime.environment     active import root differs from this checkout
         next: run `just install` in this workspace

Providers
  OK     llm.default             codex selected; executable found on PATH

State
  OK     state.agent_index       schema 3; 4313 visible rows; no repair recommended

Summary: 9 OK, 2 WARN, 0 ERROR, 1 SKIP
```

Design rules:

- Use restrained Rich styling: green/yellow/red/dim statuses, cyan section borders, no emoji dependency.
- Prefer grouped tables over nested panels.
- Fold long paths cleanly.
- Put exact next-step commands near the check that failed.
- Do not expose secrets, tokens, raw env dumps, provider API keys, cookies, or auth material.
- JSON output must contain the full machine-readable report and no Rich markup.

## JSON Contract

Use a stable schema from the first phase:

```json
{
  "schema_version": 1,
  "command": "doctor",
  "status": "WARN",
  "generated_at": "2026-06-09T16:00:00Z",
  "cwd": "/path/to/workspace",
  "project": "sase",
  "sase_home": "/home/user/.sase",
  "deep": false,
  "strict": false,
  "selected_checks": [],
  "counts": { "OK": 9, "WARN": 2, "ERROR": 0, "SKIP": 1 },
  "checks": [
    {
      "id": "runtime.core",
      "group": "runtime",
      "status": "OK",
      "title": "Rust core health",
      "summary": "sase_core_rs loaded; 4/4 probes passed",
      "details": [],
      "next_steps": [],
      "data": {},
      "duration_ms": 12
    }
  ]
}
```

Keep `data` values bounded. Large inventories should appear only in verbose mode or as summarized counts.

## Important Existing Context

Read before implementing:

- `sdd/research/202606/sase_doctor_command_consolidated.md`
- `memory/short/build_and_run.md`
- `memory/short/gotchas.md`
- `memory/short/rust_core_backend_boundary.md`

Relevant source surfaces:

- CLI registration: `src/sase/main/parser.py`, `src/sase/main/entry.py`
- Existing plugin doctor: `src/sase/plugins/doctor.py`, `src/sase/plugins/render.py`, `src/sase/main/plugin_handler.py`
- Core health: `src/sase/core/health.py`, `src/sase/main/core_handler.py`
- Runtime inventory: `src/sase/version/inventory.py`, `src/sase/version/render.py`
- Config layers: `src/sase/config/core.py`, `src/sase/main/config_handler.py`
- Init planners: `src/sase/main/init_registry.py`, `src/sase/main/init_plan.py`, `src/sase/main/init_onboarding.py`
- Providers: `src/sase/llm_provider/registry.py`, `src/sase/llm_provider/config.py`
- Projects/workspaces: `src/sase/main/project_handler.py`, `src/sase/main/workspace_handler_context.py`,
  `src/sase/workspace_provider/registry.py`, `src/sase/workspace_provider/store.py`
- Agent index: `src/sase/agents/cli_index.py`
- Telemetry: `src/sase/telemetry/cli_status.py`, `src/sase/telemetry/cli_health.py`, `src/sase/telemetry/_config.py`
- Beads: `src/sase/bead/cli_admin.py`, `src/sase/bead/project.py`
- Memory episodes doctor: `src/sase/memory/episodes/_auto_build_doctor.py`

Critical reliability note: `src/sase/main/workspace_handler_context.py::resolve_project_context` can materialize sibling
ProjectSpec metadata. `sase doctor` must stay read-only, so default project/workspace checks should not call that
resolver directly. Prefer `list_project_records`, marker inference, direct ProjectSpec reads, and pure `WorkspaceStore`
resolution. Likewise, do not call workspace materialization or repair helpers in default mode.

## Check Catalog for the MVP

Default checks:

- `runtime.version`: collect SASE host/core/plugin inventory and package warnings.
- `runtime.core`: adapt `check_backend_health()`.
- `runtime.environment`: Python version, executable/import root, current checkout root, source-root drift.
- `state.paths`: required state/config/project paths exist or are writable when they must be.
- `vcs.git`: `git` executable, current repo detection, git identity warnings for git-backed projects.
- `config.layers`: config layer visibility, invalid/unreadable YAML, unsupported keys, active local config.
- `config.init`: summarize read-only init planners.
- `config.sdd`: run or adapt SDD validation only when an SDD tree exists.
- `llm.registry`: provider plugin registry can load metadata.
- `llm.default`: effective default provider can be resolved and its CLI executable is present when required.
- `plugins.doctor`: adapt existing plugin doctor checks into the shared model.
- `project.current`: current project inference, lifecycle state, launchability, parse warnings.
- `workspace.registry`: read-only registry summary for the current or selected project.
- `state.agent_index`: adapt lightweight agent index status payload.
- `project.beads`: skip when `sdd/beads` is absent; otherwise adapt bead doctor output.
- `ops.telemetry_status`: skip when telemetry is disabled; otherwise check configured endpoints with short timeouts.

Deep checks behind `-D|--deep`:

- `state.agent_index_verify`: full agent index verify.
- `workspace.repair_dry_run`: read-only/dry-run repair summary, only if the existing API can do this without writes.
- `workspace.cleanup_dry_run`: stale workspace cleanup candidates, no deletion.
- `memory.episodes`: adapt `build_episode_auto_doctor_report(..., repair=False)` when project episode state exists.
- `ops.telemetry_health`: adapt telemetry health JSON/status.
- `ops.axe`: summarize axe/lumberjack runtime state if configured.
- `providers.cli_version`: cheap provider `--version` probes with short timeouts.
- `tools.optional`: optional tools such as `tmux`, `bat`, `pandoc`, `pdftoppm`, `kitten`, PDF tooling, and `prettier`,
  with affected feature names.

## Phase 1: Shared Diagnostics Foundation

Goal: create the reusable diagnostics model, renderer, and registry without adding the top-level command yet.

Files to add:

- `src/sase/diagnostics/__init__.py`
- `src/sase/diagnostics/models.py`
- `src/sase/diagnostics/render.py`
- `src/sase/diagnostics/registry.py`
- `tests/test_diagnostics_models.py`
- `tests/test_diagnostics_render.py`

Design:

- Define `CheckStatus = Literal["OK", "WARN", "ERROR", "SKIP"]`.
- Define immutable dataclasses for `DiagnosticCheck`, `DiagnosticReport`, and `CheckSpec`.
- Include fields from the JSON contract: id, group, status, title, summary, details, next_steps, data, duration_ms.
- Implement aggregation, counts, strict exit-code calculation, all-skipped behavior, JSON serialization, and redaction
  helpers.
- Implement a Rich human renderer with deterministic grouping and a compact default mode.
- Implement a registry abstraction that can list default/deep checks, select by id or group, and preserve stable order.
- Add a helper that wraps each check runner so an unexpected exception becomes one `ERROR` check instead of aborting the
  entire doctor run.

Acceptance:

- Unit tests cover aggregation, strict exit codes, all-skipped reports, JSON shape, redaction, selected check filtering,
  group ordering, and human rendering without Rich markup in JSON.
- No existing CLI behavior changes.
- `just install` and `just check` pass.

## Phase 2: CLI Skeleton and Core Runtime Checks

Goal: add `sase doctor` as a real top-level command with the foundational default checks.

Files to add/change:

- `src/sase/main/parser_doctor.py`
- `src/sase/main/doctor_handler.py`
- `src/sase/doctor/__init__.py`
- `src/sase/doctor/checks_runtime.py`
- `src/sase/doctor/checks_config.py`
- `src/sase/doctor/runner.py`
- `src/sase/main/parser.py`
- `src/sase/main/entry.py`
- `tests/main/test_doctor_command.py`
- focused unit tests under `tests/doctor/`

Checks in this phase:

- `runtime.version`
- `runtime.core`
- `runtime.environment`
- `state.paths`
- `vcs.git`
- `config.layers`
- `config.init`
- `config.sdd`

Implementation notes:

- Reuse `collect_runtime_version_inventory()` and `check_backend_health()`.
- Detect source-root drift by comparing the current checkout root with the host package import/source root from runtime
  inventory. When drift is found in an editable/source install, warn with `just install`.
- Extend or wrap `load_config_layers()` so doctor can distinguish a missing optional layer from an invalid/unreadable
  existing file. Today `_load_yaml_file()` returns `None` for both cases, so this phase should add non-breaking metadata
  rather than relying only on merged config.
- Use init planners directly through `iter_init_command_specs()`; do not shell out to `sase init -c` unless a direct
  planner is unavailable.
- `config.sdd` may call a direct SDD validation helper if available; otherwise use a bounded subprocess adapter with
  captured output and a short timeout. Skip when no SDD tree exists.
- `-L|--list-checks`, `-C|--check`, `-j|--json`, `-v|--verbose`, `-D|--deep`, `-s|--strict`, and `-p|--project` should
  parse correctly even if some later checks are not implemented yet.

Acceptance:

- `sase doctor`, `sase doctor -j`, `sase doctor -v`, `sase doctor -L`, and `sase doctor -C runtime` work.
- Default command is read-only and does not call LLM providers.
- Exit codes match the product contract.
- Source-root drift produces an actionable warning in mismatched editable installs.
- `just install` and `just check` pass.

## Phase 3: Providers, Plugins, Project, Workspace, and Agent Index

Goal: make default doctor useful for actual SASE troubleshooting by adapting the high-value subsystem checks.

Files to add/change:

- `src/sase/doctor/checks_providers.py`
- `src/sase/doctor/checks_plugins.py`
- `src/sase/doctor/checks_project.py`
- `src/sase/doctor/checks_workspace.py`
- `src/sase/doctor/checks_agent_index.py`
- Existing plugin doctor files as needed for shared model reuse.
- Existing agent index module as needed to expose a public lightweight status function.
- Tests under `tests/doctor/` and regression tests for `sase plugin doctor`.

Checks in this phase:

- `llm.registry`
- `llm.default`
- `plugins.doctor`
- `project.current`
- `workspace.registry`
- `state.agent_index`

Implementation notes:

- Provider checks must never invoke a model. Use provider metadata, config, temporary override state, and `shutil.which`
  for configured/autodetected CLIs.
- Treat all agent runtimes uniformly; do not add runtime-specific assumptions beyond provider plugin metadata.
- Refactor `src/sase/plugins/doctor.py` to reuse `sase.diagnostics.models` or adapt its checks without changing
  `sase plugin doctor` behavior or JSON compatibility. Prefer a compatibility shim if a direct refactor would be risky.
- Expose a non-CLI helper for the existing lightweight agent index status payload instead of parsing
  `sase agents index status -j` text.
- For project checks, use `list_project_records()` and current-project inference. Report lifecycle state, launchability,
  active claims, parse warnings, and missing project context.
- For workspace checks, avoid `resolve_project_context()` because it may write sibling metadata. Build a pure read-only
  resolver for doctor that reads the ProjectSpec and constructs `WorkspaceStore` only when a primary workspace is known.
- If a workspace registry file is missing, do not create it. Report `SKIP` or `WARN` depending on root policy and
  whether missing state blocks normal use.

Acceptance:

- Default `sase doctor -j` contains all Phase 2 and Phase 3 check ids.
- A failing provider registry, missing default provider CLI, plugin load error, stale agent index, inactive project, or
  missing workspace path yields one actionable check without aborting the report.
- `sase plugin doctor` still passes existing tests and retains its documented behavior.
- `just install` and `just check` pass.

## Phase 4: Beads, Telemetry, Memory, Deep Mode, and Optional Tools

Goal: complete the ambitious MVP check catalog while keeping default mode fast and quiet for unused subsystems.

Files to add/change:

- `src/sase/doctor/checks_beads.py`
- `src/sase/doctor/checks_telemetry.py`
- `src/sase/doctor/checks_memory.py`
- `src/sase/doctor/checks_tools.py`
- `src/sase/doctor/checks_deep.py`
- Telemetry helper modules as needed to expose structured status.
- Tests under `tests/doctor/`.

Checks in this phase:

- `project.beads`
- `ops.telemetry_status`
- `state.agent_index_verify` behind deep mode
- `memory.episodes` behind deep mode
- `ops.telemetry_health` behind deep mode
- `ops.axe` behind deep mode if a lightweight source exists
- `providers.cli_version` behind deep mode
- `tools.optional` behind deep mode
- workspace repair/cleanup dry-run checks behind deep mode if and only if they are provably read-only

Implementation notes:

- Bead doctor currently returns strings such as `OK: ...` and `WARNING: ...`; adapt conservatively. If structured Rust
  bead doctor output is easy to expose through the existing facade, prefer that.
- Telemetry status currently has human output only. Extract a structured status helper that returns enabled state,
  metric count, endpoint URLs, and reachability booleans. Keep the existing `sase telemetry status` UI behavior.
- Memory episode doctor already returns JSON-shaped checks. Prefix adapted ids with `memory.episodes.*` or store the
  subsystem check data under one `memory.episodes` check; choose the less noisy shape for human output.
- Every deep subprocess or network check needs a short timeout and a clear timeout warning.
- Optional tools should warn only with affected feature names, not as generic install failures.

Acceptance:

- `sase doctor -D -j` includes deep checks and remains read-only.
- Telemetry disabled produces `SKIP`; telemetry enabled but unreachable produces `WARN`.
- Beads absent produces `SKIP`; bead state warnings are visible when a bead store exists.
- Deep checks can fail independently without suppressing other checks.
- `just install` and `just check` pass.

## Phase 5: Polish, Documentation, and Support Integration

Goal: make `sase doctor` feel finished and make it discoverable as the support front door.

Files to change:

- `docs/cli.md`
- `docs/configuration.md` if config-layer diagnostics need documentation.
- README or troubleshooting docs if present.
- Any agent-launch or validation error text that should mention `sase doctor -v`.
- Final parser/help tests and possibly snapshot-style renderer tests if local patterns support them.

Work:

- Tighten human output after seeing real reports in healthy and degraded local states.
- Ensure `--help` text is concise and useful.
- Add examples for `sase doctor`, `sase doctor -j`, `sase doctor -D`, and targeted checks.
- Document exit-code behavior and strict mode.
- Add a small troubleshooting section: "Attach `sase doctor -v` or `sase doctor -j` when asking for help."
- Audit all check summaries and next steps for clarity and actionability.
- Verify no secrets appear in JSON or human output.

Acceptance:

- `sase --help` lists `doctor` in sorted order.
- `sase doctor --help` documents every MVP flag with short and long forms.
- Healthy output is compact; degraded output puts the fix next to the issue.
- Docs describe JSON schema stability at a high level without overpromising future fields.
- `just install` and `just check` pass.

## Cross-Phase Guardrails

- Keep each check independent. One exception should become one `ERROR` check and the report should continue.
- Prefer direct Python APIs and Rust-backed facades over subprocesses. Use subprocesses only when no structured API
  exists yet.
- When a diagnostic is backend/domain semantics that another frontend would need, use or extend the Rust core boundary
  instead of duplicating logic in Python.
- Do not mutate state in default or deep doctor. Future repair mode is explicitly out of scope.
- Keep check ids stable once introduced. If an id must change before release, update tests and docs in the same phase.
- Avoid parsing human output where a structured helper can be extracted with reasonable effort.
- Redact environment-like values by default.
- Make all check selection deterministic so JSON reports are stable under tests.

## Verification Matrix

Each implementation phase should run:

```bash
just install
just check
```

Targeted checks to add across phases:

- Parser accepts every short and long doctor flag.
- `sase doctor -j` emits valid JSON and no Rich markup.
- `sase doctor` exits `0` for WARN by default.
- `sase doctor -s` exits `1` for WARN.
- `sase doctor -C <group>` runs only selected group checks.
- `sase doctor -C <id>` runs only selected check.
- `sase doctor -L` lists default/deep status for every registered check.
- Default doctor does not invoke LLMs, repairs, workspace materialization, or broad test commands.
- Broken check adapters are isolated into one `ERROR` check.
- Human renderer folds long paths and displays next steps.

Manual smoke after the final phase:

```bash
sase doctor
sase doctor -v
sase doctor -j | python -m json.tool
sase doctor -D -j | python -m json.tool
sase doctor -L
sase doctor -C runtime
sase doctor -C llm.default -s
```

## Recommended Implementation Order

Implement the phases in order. Phase 1 establishes the contract. Phase 2 makes the command real and immediately useful
for install/runtime drift. Phase 3 adds the SASE-specific support value. Phase 4 broadens the MVP without slowing the
default path. Phase 5 makes the command discoverable and polished.

Do not add `-R|--repair` or support-bundle generation in this MVP. Once the report contract has survived real use, those
can be separate features that delegate to already safe repair commands.
