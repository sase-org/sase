---
create_time: 2026-06-02 20:18:46
status: done
prompt: sdd/prompts/202606/sase_var_output_variables.md
bead_id: sase-4a
tier: epic
---
# Plan: `sase var` Output Variables and `/sase_var`

## Goal

Add a new `/sase_var` xprompt slash command and a matching `sase var` CLI command. Agents will use it to attach small
named output values to their current SASE agent run. Those values must appear in ACE's Agents-tab metadata panel and be
available as Jinja2 namespaces to later agents in the same multi-agent markdown prompt when those later agents actually
run after the producer.

## Product Contract

Use a small, explicit CLI surface:

```bash
sase var set KEY=VALUE [KEY=VALUE ...]
```

Rules:

- The command is only valid inside a SASE agent, requiring `SASE_AGENT=1` and `SASE_ARTIFACTS_DIR`.
- Keys must be valid Jinja attribute identifiers: `[A-Za-z_][A-Za-z0-9_]*`.
- Values are strings. Split assignments on the first `=`, so values may contain additional `=` characters.
- Multiple calls merge into the same agent's output-variable map; later writes for the same key replace earlier values.
- The agent must have a usable name for cross-agent Jinja access. The TUI can still show variables for any agent whose
  metadata carries them.
- Do not treat output variables as secret storage: they are persisted in agent metadata and shown in ACE.

Persist variables under `agent_meta.json` as an `output_variables` object. This keeps the feature aligned with the
existing artifact watcher and persistent artifact index, because `agent_meta.json` is already an indexed marker.

## Phase 1: CLI, Storage Helper, and Slash Command Source

Implement the basic variable writer in the Python repo.

1. Add a focused helper module, for example `src/sase/agent/output_variables.py` or
   `src/sase/core/agent_output_variables.py`, with:
   - `parse_output_variable_assignments(assignments: list[str]) -> dict[str, str]`
   - `set_agent_output_variables(artifacts_dir, variables) -> dict[str, str]`
   - `read_agent_output_variables(artifacts_dir) -> dict[str, str]`
   - Atomic read-merge-write behavior for `agent_meta.json`, followed by
     `update_agent_artifact_index_for_marker_mutation(artifacts_dir)`.
2. Register `sase var` in the top-level parser and entry dispatch.
   - Add `parser_var.py` and `var_handler.py`, mirroring the simple structure of `sase artifact`.
   - Add the `set` subcommand with a positional `assignments` list.
   - Return a concise success output showing the stored keys, the current agent name when available, and the artifacts
     directory.
3. Add the xprompt skill source `src/sase/xprompts/skills/sase_var.md`.
   - Explain when to use it, the `sase var set KEY=VALUE ...` command, quoting rules, key restrictions, and the need to
     name producer agents with `%name`.
   - Include an indexed-name example such as `%name:build-@` producing `{{ build.result_path }}` for later agents.
4. Update generated-skill source tests and docs:
   - `tests/main/test_init_skills_sources.py`
   - `docs/xprompt.md` skill table
   - `docs/cli.md` and `docs/configuration.md`
5. Add parser/handler/storage tests in `tests/main/test_var_handler.py`.

Phase 1 is complete when an agent can run `sase var set plan_file=... status=ok`, the values are persisted into
`agent_meta.json["output_variables"]`, and the skill source is discoverable by `sase init-skills`.

## Phase 2: Scanner/Wire Support and ACE Metadata Panel Display

Make output variables first-class loader data so ACE can show them without ad hoc panel-side JSON reads.

1. Update `../sase-core` in the matching numbered workspace:
   - Add `output_variables: BTreeMap<String, String>` to Rust `AgentMetaWire` with serde defaulting.
   - Parse `agent_meta.json["output_variables"]` in the Rust scanner, coercing string values only.
   - Add Rust parity tests in `crates/sase_core/tests/agent_scan_parity.rs`.
2. Update the Python wire mirror:
   - Add `output_variables: dict[str, str]` to `src/sase/core/agent_scan_wire_markers.py`.
   - Ensure `agent_scan_wire_conversion.py` round-trips the new field.
   - Update Python scan/conversion tests.
3. Add `output_variables: dict[str, str]` to the ACE `Agent` model and populate it in both filesystem-backed and
   wire-backed metadata enrichment paths.
4. Render a new `OUTPUT VARIABLES` section in `build_header_text()`:
   - Place it after the top metadata fields, practically after the `Timestamps:` field, and before deltas, artifacts,
     `STEP METADATA`, memory reads, and errors.
   - Sort keys for deterministic display.
   - Render multi-line values in an indented, readable form.
5. Add focused TUI-rendering tests for:
   - Section is absent when no variables exist.
   - Section appears before `STEP METADATA` and artifact sections when variables exist.
   - Wire-loaded agents and direct filesystem-loaded agents render identically.

Phase 2 is complete when variables written in Phase 1 appear in the Agents-tab metadata panel under `OUTPUT VARIABLES`
and survive indexed visible-inbox loading.

## Phase 3: Multi-Agent Jinja Namespace Propagation

Expose prior agent variables to later agents at the point the later agent is actually about to execute.

1. Add a namespace sanitizer/helper:
   - If a producer used an indexed `%name:<base>-@` template, derive the namespace from `<base>`, not the concrete
     `<base>-N` name.
   - Convert `-` to `_`.
   - Preserve `.` as a nested namespace separator, so `research_swarm.final-@` can expose
     `{{ research_swarm.final.some_key }}`.
   - Validate each namespace component as a Jinja identifier. Invalid namespaces should not be silently exposed; tests
     should pin the behavior.
2. Preserve indexed-template metadata:
   - When `extract_directives_and_write_meta()` resolves `%name:foo-@` to `foo-1`, also persist the original template in
     `agent_meta.json`, for example as `agent_name_template`.
   - Include the template in any launch-time upstream context passed between multi-prompt segments.
3. Extend multi-prompt launch context:
   - In `launch_multi_prompt_agents()`, maintain an ordered list of prior named launched agents for the same multi-agent
     prompt/multi-prompt run.
   - Pass that list to later segments through an environment variable such as `SASE_AGENT_VAR_UPSTREAMS_JSON`.
   - Include enough data to resolve variables without a global ambiguous lookup: concrete name, namespace/template when
     known, project, workflow timestamp, and artifact directory or derivable artifact identity.
4. Materialize Jinja context in the runner:
   - After `wait_for_dependencies()` returns and before `run_execution_loop()`, load output variables from scoped
     upstreams and from explicit `%wait` names as a fallback for ordinary prompts.
   - Merge them into `_build_named_args(ctx)` as nested objects/dicts so Jinja can render `{{ build.result_path }}` or
     `{{ research_swarm.final.report_path }}`.
   - Later upstream entries should deterministically override earlier entries for the same namespace/key.
   - If a later prompt references a namespace before the upstream has written variables, leave it undefined so existing
     `StrictUndefined` behavior produces a clear template error. The `/sase_var` skill should tell agents to use
     `%wait:<producer>` when they need variables from another agent.
5. Add tests:
   - `build-@` concrete names expose `build`, not `build_1`.
   - `research_swarm.final-@` exposes `research_swarm.final`.
   - Waited-for agents' variables are available in the downstream prompt context.
   - Variables do not leak into earlier agents or unrelated launches.

Phase 3 is complete when a multi-agent markdown prompt can have one named agent run `sase var set report_path=...` and a
later `%wait`ed agent can render `{{ producer.report_path }}` from that value.

## Phase 4: End-to-End Polish, Documentation, and Checks

Close the feature with integration coverage and generated-skill deployment.

1. Add an end-to-end or near-end-to-end test fixture that simulates:
   - A producer agent with `agent_meta.json` and `output_variables`.
   - A later multi-agent segment waiting on the producer.
   - Jinja rendering of the producer namespace in the later segment.
2. Update user-facing docs:
   - `docs/ace.md`: describe `OUTPUT VARIABLES`.
   - `docs/xprompt.md`: document cross-agent variable handoff in multi-agent markdown prompts.
   - `docs/configuration.md` and `docs/cli.md`: document `sase var set`.
3. Run generated skill deployment steps after editing `src/sase/xprompts/skills/sase_var.md`:
   - `sase init-skills --force`
   - `chezmoi apply`
4. Validation:
   - In `../sase-core`: run the targeted Rust scanner tests first, then the appropriate crate test set.
   - In this repo: run `just install` if needed, then targeted tests for the changed areas, then `just check`.

Phase 4 is complete when docs, generated runtime skill files, and Python/Rust checks all agree on the same command and
metadata contract.

## Open Design Decisions for Implementers

- The first implementation should keep values string-only. Add `-j/--json` later only if typed/nested values become
  necessary.
- Prefer `agent_meta.json["output_variables"]` over a new marker file unless a later implementer finds a concrete
  concurrency or size issue. The existing watcher/index lifecycle is already built around `agent_meta.json`.
- Avoid global variable lookup when scoped launch context is available. Global lookup is useful as a fallback for
  explicit `%wait` names outside multi-agent xprompt files, but the same-file handoff should prefer launch-scoped
  upstream identity.
