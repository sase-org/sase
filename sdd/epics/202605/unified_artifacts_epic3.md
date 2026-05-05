---
create_time: 2026-05-05 12:05:34
bead_id: sase-23.3
tier: epic
legend_bead_id: sase-23
legend: sdd/legends/202605/unified_artifacts.md
epic: 3
status: done
prompt: sdd/prompts/202605/unified_artifacts_epic3.md
---

# Unified Artifacts Epic 3 Implementation Plan

## Scope

Implement Epic 3, "`sase artifact` CLI And `/sase_artifact` Skill", from `sdd/legends/202605/unified_artifacts.md`.

Epic 1 and Epic 2 appear to be present in this workspace already:

- Rust artifact graph modules exist under `../sase-core/crates/sase_core/src/artifact/`.
- PyO3 bindings are exported from `../sase-core/crates/sase_core_py`.
- Python wire and facade code exists in `src/sase/core/artifact_wire.py` and `src/sase/core/artifact_facade.py`.
- Source ingestion is implemented behind `artifact_rebuild` and `artifact_upsert_path`.

Epic 3 should therefore focus on making the graph usable from the command line and from agent skills. It should not move
graph semantics into Python. The CLI may format output in Python, but graph storage, rebuild, query, doctor, and export
semantics should continue to come from Rust through `sase_core_rs` and the existing facade.

## Product Contract

After this epic, users and agents should be able to:

- Add manual artifacts, links, and optional payloads through `sase artifact add`.
- Remove manual artifacts/links or tombstone derived artifacts/links through `sase artifact remove`.
- List artifacts with useful filters and stable JSON output through `sase artifact list`.
- Inspect an artifact with detail, direct children, typed inbound/outbound links, path to root, payload summaries, and
  diagnostics through `sase artifact show`.
- Export bounded or full graph views as JSON, compact text, Mermaid, or DOT through `sase artifact graph`.
- Rebuild derived graph rows through `sase artifact rebuild`.
- Run graph consistency checks through `sase artifact doctor`.
- Use `/sase_artifact` as a generated skill that documents the stable JSON shapes and recommended read-only discovery
  commands.

The default artifact index path should be `~/.sase/artifacts.sqlite`, while every subcommand should accept an explicit
index override for tests and debugging.

## Non-Goals

- Do not build the Artifacts TUI panel or change the `A` keybinding. That is Epic 4.
- Do not migrate or remove `~/.sase/agent_artifact_index.sqlite`. That is Epic 5.
- Do not duplicate Rust query, rebuild, tombstone, or doctor behavior in Python.
- Do not add runtime-specific skill behavior. Claude, Gemini, Codex, and plugin providers should all use the same
  command contract.
- Do not hand-edit generated `SKILL.md` files. Edit only `src/sase/xprompts/skills/sase_artifact.md`, then run
  `sase init-skills -f -C` or an equivalent no-deploy invocation.

## CLI Shape

Add a top-level `sase artifact` command. Follow the repo convention that every argument has a short option. Suggested
common options:

- `-i, --index PATH`: artifact index path, defaulting to `~/.sase/artifacts.sqlite`.
- `-j, --json`: emit stable JSON where a command has both human and machine output.
- `-f, --format FORMAT`: output format where a command naturally supports multiple non-JSON formats.

Suggested subcommands and important options:

- `add`: `-a/--artifact-id`, `-k/--kind`, `-t/--title`, `-s/--subtitle`, `-q/--search-text`, `-m/--metadata-json`,
  `-p/--payload-json`, `-P/--payload-type`, `-l/--link`, `-L/--link-json`.
- `remove`: `-a/--artifact-id`, `-l/--link-id`, `-T/--link-type`, `-S/--source-id`, `-D/--target-id`, `-p/--provenance`,
  `-r/--reason`.
- `list`: `-k/--kind`, `-L/--link-type`, `-P/--provenance`, `-s/--source-kind`, `-S/--source-id`, `-q/--text`,
  `-r/--root-id`, `-u/--include-tombstoned`, `-l/--limit`, `-o/--offset`, `-j/--json`.
- `show`: `-a/--artifact-id`, `-j/--json`.
- `graph`: `-a/--artifact-id`, `-d/--depth`, `-L/--link-type`, `-I/--include-inbound`, `-O/--include-outbound`,
  `-F/--full`, `-l/--limit`, `-f/--format`.
- `rebuild`: `-p/--projects-root`, `-w/--workspace-root`, `-b/--beads-dir`, `-S/--include-source`,
  `-X/--exclude-source`, `-t/--target-path`, `-a/--artifact-dir`, `-c/--stale-cleanup`, `-j/--json`.
- `doctor`: `-j/--json`, plus short-option toggles only if the implementation exposes individual doctor checks.

Implementation agents may adjust exact short letters to avoid parser conflicts, but every option must keep a short form
and parser tests must pin the final contract.

## Phase Breakdown

Each phase below is intended for a distinct implementation agent. Later phases should treat earlier phases as committed
surface area and avoid broad rewrites outside their ownership.

### Phase 1: CLI Parser, Handler Skeleton, And Read-Only JSON Path

Dependencies: Epic 1 and Epic 2 bindings installed by `just install`.

Owner scope:

- `src/sase/main/parser.py`
- New `src/sase/main/parser_artifact.py`
- `src/sase/main/entry.py`
- New `src/sase/main/artifact_handler.py` or a small `src/sase/artifact/` CLI package
- Parser and handler tests under `tests/main/`

Implementation:

- Register `sase artifact` in the top-level parser and command dispatcher.
- Add the required subcommands: `add`, `remove`, `list`, `show`, `graph`, `rebuild`, `doctor`.
- Add a shared default-index helper that expands to `~/.sase/artifacts.sqlite`, while preserving explicit `-i/--index`.
- Implement read-only JSON behavior first:
  - `list -j` calls `artifact_facade.artifact_list`.
  - `show -j` calls `artifact_facade.artifact_show`.
  - `graph -f json` or `graph -j` calls `artifact_facade.artifact_graph`.
  - `rebuild -j` calls `artifact_facade.artifact_rebuild`.
  - `doctor -j` calls `artifact_facade.artifact_doctor`.
- Keep `add` and `remove` parsed and dispatched, but it is acceptable for this phase to return a clear "not implemented"
  handler error until Phase 2 lands.
- Convert facade dataclasses to JSON through `artifact_wire_to_json_dict`; do not rely on dataclass `repr`.
- Use deterministic `json.dumps(..., indent=2, sort_keys=True)` only if that is consistent with nearby CLI commands.

Tests:

- Parser registers `sase artifact` and all required subcommands.
- Every artifact option has a short option.
- `entry.py` dispatches `artifact` to the new handler.
- Read-only JSON commands call the expected facade functions with typed request objects.
- Missing subcommands print usage and exit non-zero.

Exit criteria:

- Targeted parser/handler tests pass.
- `sase artifact list -j -i <tmp.sqlite>` works against a temporary index when `sase_core_rs` is installed.

### Phase 2: Manual Mutation Commands

Dependencies: Phase 1.

Owner scope:

- Artifact CLI handler/parser files from Phase 1
- Focused mutation tests under `tests/main/` or `tests/test_artifact_cli.py`
- Python wire/facade helpers only if small constructor helpers are missing

Implementation:

- Implement `sase artifact add` for:
  - manual node upsert from CLI flags
  - optional payload upsert from JSON
  - one or more links from a compact repeated `--link` form and/or explicit `--link-json`
- Implement `sase artifact remove` for:
  - node removal by artifact ID
  - link removal by link ID
  - link removal by type/source/target tuple
  - optional provenance/source/reason fields needed to choose manual removal vs derived tombstone behavior
- Validate malformed JSON and incomplete link tuples in Python before calling Rust.
- Keep mutation result JSON stable and concise. Human mutation output can stay line-oriented in this phase.
- Preserve Rust semantics: Python should build `ArtifactNodeUpsertWire`, `ArtifactLinkUpsertWire`,
  `ArtifactPayloadWire`, `ArtifactNodeRemoveWire`, or `ArtifactLinkRemoveWire` and let the facade call Rust.

Tests:

- `add` builds the expected node upsert request.
- `add` can also upsert payloads and links.
- `remove` builds node and link remove requests correctly.
- Malformed metadata/payload/link JSON exits non-zero with a useful error on stderr.
- Mutation result output includes affected node/link IDs and tombstone IDs.

Exit criteria:

- Mutation handler tests pass with a fake facade.
- Real-extension smoke test can add, list, show, remove, and doctor a temp index.

### Phase 3: Graph Export Formats And Rust Binding Exposure

Dependencies: Phase 1. Can run after Phase 2 or in parallel if it avoids shared Python formatter files.

Owner scope:

- `../sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/artifact_facade.py`
- `src/sase/core/artifact_wire.py` only if an export request/result wire is needed
- Artifact graph CLI handler
- Rust/Python binding tests and CLI graph tests

Implementation:

- Prefer exposing existing Rust export functions instead of recreating DOT/Mermaid generation in Python. Add a binding
  such as `artifact_export(index_path: str, options: dict, format: str) -> str`, or an equivalent small set of bindings
  for `json`, `dot`, and `mermaid`.
- Keep `artifact_graph` returning the existing `ArtifactGraphWire` for JSON and TUI consumers.
- Implement `sase artifact graph` formats:
  - `json`: stable graph wire JSON
  - `dot`: Rust DOT export
  - `mermaid`: Rust Mermaid export
  - `text`: compact Python line-oriented summary from `ArtifactGraphWire`
- Support bounded graph options: root artifact, depth, link type filters, inbound/outbound direction, full graph, and
  limit.
- Surface truncation metadata in JSON and compact text.

Tests:

- PyO3 export binding rejects unknown formats and returns deterministic strings for DOT/Mermaid fixtures.
- CLI graph passes the expected `ArtifactGraphOptionsWire`.
- `graph -f text` shows node/link counts, truncation state, and a compact edge list.
- `graph -f dot` and `graph -f mermaid` print raw export text without Rich styling.

Exit criteria:

- In `../sase-core`: targeted PyO3 tests pass.
- In this repo: facade and CLI graph tests pass.

### Phase 4: Human Output, Error Semantics, And CLI Polish

Dependencies: Phases 1 through 3.

Owner scope:

- Artifact CLI formatter/helper modules
- Handler tests for human output
- Existing command help/parser tests

Implementation:

- Add readable default output for:
  - `list`: table with kind, ID, title, provenance, source, and updated time.
  - `show`: detail block with node summary, path to root, children, inbound/outbound link groups, payload summaries, and
    diagnostics.
  - `doctor`: concise OK/failure summary plus issue rows.
  - `rebuild`: mutation summary including counts and errors.
  - `add/remove`: mutation summary including affected IDs and tombstones.
- Keep JSON output as the stable automation surface. Human output may be Rich-based like other SASE CLIs, but graph
  DOT/Mermaid formats must remain plain text.
- Standardize exit codes:
  - `0` for successful commands, including `doctor` when `ok` is true.
  - non-zero for invalid CLI input, facade errors, and `doctor` when issues are found.
  - non-zero for `show` when the artifact is missing, unless the Rust detail contract explicitly treats missing as an
    empty successful record.
- Ensure stderr contains errors and stdout contains only requested command output.
- Add help text examples where useful without making parser help noisy.

Tests:

- Human output snapshots are compact and deterministic.
- JSON output remains unchanged after adding human formatters.
- Facade exceptions are converted to non-zero exits with actionable messages.
- `doctor` exits non-zero when issues are returned.
- Existing global parser help sorting tests still pass.

Exit criteria:

- CLI output is usable for humans while `/sase_artifact` can rely on JSON.
- Targeted command tests pass.

### Phase 5: Generated `/sase_artifact` Skill

Dependencies: Phases 1 through 4, because the skill should document the final CLI contract.

Owner scope:

- `src/sase/xprompts/skills/sase_artifact.md`
- `tests/main/test_init_skills_handler.py` or a neighboring skill-generation test
- Generated live skill output only through `sase init-skills`; do not hand-edit generated `SKILL.md`

Implementation:

- Add `src/sase/xprompts/skills/sase_artifact.md` with frontmatter:
  - `name: sase_artifact`
  - a concise description
  - `skill: true`
- Model the content after `sase_agents_status` and `sase_notify`:
  - Make read-only discovery commands primary.
  - Prefer JSON examples for `list`, `show`, `graph`, and `doctor`.
  - Document stable JSON fields at a practical level.
  - Clearly mark `add`, `remove`, and `rebuild` as mutating commands that require explicit user intent.
  - Include troubleshooting guidance for stale indexes: run `sase artifact rebuild -j`, then `sase artifact doctor -j`.
- Run `sase init-skills -f -C` after the source lands. If local config disables chezmoi, the command still verifies
  generation; if config enables chezmoi, `-C` avoids committing/pushing/deploying generated files during this phase.
- Add a provider-discovery test like the existing `sase_chats` and `sase_notify` tests.

Tests:

- Skill source has valid frontmatter, `skill: true`, non-empty body, and command examples matching the implemented CLI.
- `sase init-skills` renders `sase_artifact` for all registered providers in a temp home.
- Rendered skill includes `sase artifact list -j`, `sase artifact show`, `sase artifact graph`, and
  `sase artifact doctor -j`.

Exit criteria:

- Skill source is committed as source.
- Generated skill rendering is verified by tests.

### Phase 6: Docs, Integration Tests, And Final Verification

Dependencies: Phases 1 through 5.

Owner scope:

- `docs/` snippets, likely `docs/ace.md`, `docs/xprompt.md`, or a new `docs/artifacts.md`
- `docs/perf_runbook.md` if adding doctor/rebuild troubleshooting notes now is appropriate
- End-to-end CLI tests using a temporary artifact index
- Final verification fallout across the files touched by earlier phases

Implementation:

- Add concise docs for `sase artifact`:
  - default index path
  - read-only discovery workflow
  - mutation/tombstone behavior
  - rebuild behavior
  - graph output formats
  - doctor troubleshooting
- Add documentation pointers from `docs/xprompt.md` skill list if that table is maintained manually.
- Add an end-to-end temp-index test that exercises:
  - add node
  - add parent link
  - list JSON
  - show JSON
  - graph text or JSON
  - doctor
  - remove/tombstone path as applicable
- Run final checks:
  - `just install`
  - `just check`
  - If Phase 3 touched `../sase-core`, also run targeted `cargo test` there, and run broader `cargo test` if feasible.
- Fix any integration breakage from earlier phase boundaries without broad unrelated refactors.

Tests:

- Documentation snippets do not drift from parser command names.
- End-to-end CLI test uses only temp paths and does not touch the real `~/.sase/artifacts.sqlite`.
- Full repo check passes.

Exit criteria:

- Epic 3 is complete enough for Epic 4 to build the TUI panel against stable CLI/facade behavior.
- `/sase_artifact` is available as generated skill source and verified by tests.
- `sase artifact doctor` and `sase artifact graph` are reliable operator/debug surfaces.

## Suggested Sequencing

Run phases in order unless two agents coordinate carefully:

1. Phase 1 must land first because every later phase depends on parser/handler dispatch and default-index behavior.
2. Phase 2 and Phase 3 can proceed in parallel after Phase 1 if they avoid editing the same handler functions.
3. Phase 4 should land after Phase 2 and Phase 3 so it can polish the final command set.
4. Phase 5 should wait for Phase 4 so the generated skill documents the final UX.
5. Phase 6 should be a final integration agent.

## Verification Summary

All implementation phases that change this repo should run `just install` before tests if the workspace may be stale.
Any phase making file changes in this repo should run at least targeted tests before handing off. The final phase must
run `just check` as required by repo memory.

Any phase touching `../sase-core` should run the narrow Rust tests it affects, and should document whether full
`cargo test` was run or intentionally deferred.
