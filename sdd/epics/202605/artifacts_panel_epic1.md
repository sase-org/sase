---
create_time: 2026-05-05 20:04:15
status: done
prompt: sdd/prompts/202605/artifacts_panel_epic1.md
bead_id: sase-24.1
tier: epic
legend_bead_id: sase-24
---
# Artifacts Panel Redesign Epic 1 Phase Plan

## Scope

Implement Epic 1, "Artifact Semantics And Migration Contract", from `sdd/legends/202605/artifacts_panel_redesign.md`.

This is intentionally backend-first work. The epic must make artifact graph semantics correct before later agents build
paged query contracts, the relationship navigator modal, or CL/Agent indicators on top. The primary implementation lives
in the sibling Rust core repo at `../sase-core/crates/sase_core`; this repo should only expose thin Python wire, CLI,
docs, and compatibility tests over `sase_core_rs`.

## Current Architecture Notes

The unified artifact graph already exists:

- Rust core stores artifacts, links, payloads, source watermarks, and tombstones in SQLite.
- Rust ingestion currently creates directory nodes too broadly through `artifact_upsert_path`, explicit
  `ARTIFACT_SOURCE_DIRECTORY` rebuild handling, `upsert_directory_path`, and `upsert_agent_directory`.
- File artifacts are currently `kind = "file"` with ad hoc metadata. Some renderer tests already look for
  `metadata.artifact_type`, but the wire/query layer has no canonical file type contract.
- Python mirrors Rust wire records in `src/sase/core/artifact_wire/*`, calls Rust through
  `src/sase/core/artifact_facade.py`, and exposes `sase artifact ...` in `src/sase/main/parser_artifact.py` and
  `src/sase/main/artifact_handler.py`.
- `sase artifact rebuild` is already the low-level historical rebuild command. There is no friendlier `sync` alias yet.

## Product Decisions For This Epic

Use the storage-compatible representation:

- Keep `kind = "file"` for all file artifacts.
- Store the semantic file type in `node.metadata["artifact_type"]`.
- Expose the type in query/CLI contracts as `file_type` / `file_types`, not as a new artifact `kind`.
- Treat missing or unknown file artifact metadata as `misc` for reads, filters, and compatibility.

Canonical file artifact types:

- `plan`
- `diff`
- `chat`
- `project`
- `prompt`
- `misc`

Directory invariant:

- `/` is always present.
- Any non-root directory exists only as the containing-directory closure of at least one non-directory artifact.
- Broad directory-only ingestion must not create standalone empty directory artifacts.
- Existing agent, project, bead, and workflow directories remain navigable because they contain agent, file, ChangeSpec,
  bead, project, commit, or thought artifacts.

Migration contract:

- Existing users run an explicit manual command for historical artifacts.
- Keep `sase artifact rebuild` as the low-level command.
- Add `sase artifact sync` as a friendlier alias unless a phase finds a hard parser/UX reason not to.
- `sase ace` startup must not run broad rebuild/sync.

## Phase 1: Rust File Type Taxonomy And Query Semantics

Owner scope:

- `../sase-core/crates/sase_core/src/artifact/wire.rs`
- `../sase-core/crates/sase_core/src/artifact/ingest.rs`
- `../sase-core/crates/sase_core/src/artifact/query.rs`
- Rust artifact tests in those modules

Implementation:

- Add Rust constants for the six canonical file artifact types and the metadata key `artifact_type`.
- Add helper functions that normalize file artifact metadata:
  - `file_artifact_type(node)` returns `misc` when metadata is missing or unknown.
  - `set_file_artifact_type(metadata, type)` writes `metadata["artifact_type"]`.
  - `validate_file_artifact_type(type)` accepts only the canonical set.
- Extend `ArtifactQueryWire` with `file_types: Vec<String>` while preserving schema version 1 unless the existing wire
  policy requires a version bump. Defaults must serialize as `[]`.
- Update `artifact_list`/`artifact_search` so `file_types` filters only `kind = "file"` nodes by semantic file type.
- Ensure text search includes useful type terms for file artifacts when nodes are rebuilt.
- Keep old rows compatible: `kind = "file"` with no `metadata.artifact_type` must behave as `misc`.

Tests:

- Wire JSON snapshot for `ArtifactQueryWire::default()` includes `file_types: []`.
- Rust list/search filters distinguish `file(project)`, `file(chat)`, and `file(misc)` even though all use
  `kind = "file"`.
- Missing and unknown `metadata.artifact_type` both read/filter as `misc`.
- Non-file nodes do not match file-type filters.

Exit criteria:

- `cargo test -p sase_core artifact::wire artifact::query`
- No Python changes in this phase unless the agent must adjust a compile-breaking binding test in `sase_core_py`.

## Phase 2: Rust File Classifiers In Source Ingestion

Owner scope:

- `../sase-core/crates/sase_core/src/artifact/ingest.rs`
- Rust ingestion fixtures/tests in the same module

Implementation:

- Route every file artifact created by Rust ingestion through a single classifier helper. Classification should consider
  the marker key/reason, filename, extension, and payload context instead of scattering string checks across ingestion.
- Classify agent-created files as:
  - `plan`: `plan_path`, `sdd_plan_path`, `plan_path.json` target, plan feedback where appropriate.
  - `diff`: `diff_path`, `commit_diff_path`, prompt-step diffs, `.diff`, `.patch`.
  - `chat`: chat transcripts, response paths, live replies, and conversation-output transcripts.
  - `project`: `.gp` project files when represented as file artifacts.
  - `prompt`: `raw_xprompt.md`, `prompt.md`, `*_prompt.md`, prompt-step prompts, `sdd_prompt_path`.
  - `misc`: all other file artifacts.
- Do not change non-file artifact kinds such as `project`, `changespec`, `commit`, `agent`, `bead`, or `thought`. `.gp`
  files that are represented as `kind = "project"` may keep their existing project metadata; only `kind = "file"`
  project-file artifacts need `artifact_type = "project"`.
- Preserve existing payloads and created/related links.

Tests:

- Table-driven Rust classifier tests for every known marker key and representative filename.
- Agent artifact rebuild fixture proving created file nodes receive the expected `metadata.artifact_type`.
- Targeted rebuild fixture proving backfilled file types are present after re-ingesting an existing artifact directory.

Exit criteria:

- `cargo test -p sase_core artifact::ingest`
- No broad source scan or startup behavior changes.

## Phase 3: Rust Directory Invariant And Orphan Diagnostics

Owner scope:

- `../sase-core/crates/sase_core/src/artifact/ingest.rs`
- `../sase-core/crates/sase_core/src/artifact/query.rs`
- `../sase-core/crates/sase_core/src/artifact/store.rs` only if helper APIs are needed
- Rust artifact tests

Implementation:

- Change path materialization so `artifact_upsert_path` creates directory ancestors only when the target is a
  non-directory artifact, plus always ensuring `/`.
- Stop treating a directory target path as a standalone artifact upsert, except for `/`.
- Remove or neutralize broad `ARTIFACT_SOURCE_DIRECTORY` rebuild behavior that currently materializes `projects_root`,
  `workspace_root`, `beads_dir`, and `artifact_dir` just because they exist.
- Replace explicit directory-only calls with intent-specific parent-chain helpers:
  - project file ingestion creates parent directories because the project file exists.
  - agent ingestion creates the artifact/workflow/project directory chain because the agent node or created files exist.
  - bead ingestion creates the beads directory chain because bead nodes exist.
- Ensure parent links still make navigable paths from non-directory artifacts to `/`.
- Add doctor diagnostics for non-root directory artifacts that have no visible non-directory descendants. Prefer a
  warning such as `orphan_directory`; do not silently delete rows unless the implementation already has a safe tombstone
  pathway for this exact stale-derived case.

Tests:

- `/` exists in a fresh store.
- Upserting a standalone empty directory does not create a visible non-root directory artifact.
- Upserting a file creates the needed parent directory chain and parent links.
- Rebuilding agent, project, and bead fixtures keeps their directories navigable because they contain non-directory
  artifacts.
- Doctor reports old orphan directory rows.

Exit criteria:

- `cargo test -p sase_core artifact::ingest artifact::query`
- Existing graph/detail/export tests still pass with the stricter directory model.

## Phase 4: Python Wire, Constants, And CLI Surface

Owner scope:

- `src/sase/core/artifact_wire/constants.py`
- `src/sase/core/artifact_wire/models.py`
- `src/sase/core/artifact_wire/conversion.py`
- `src/sase/core/artifact_facade.py`
- `src/sase/main/parser_artifact.py`
- `src/sase/main/artifact_handler.py`
- `docs/artifacts.md`
- `src/sase/xprompts/skills/sase_artifact.md`
- Python unit tests under `tests/test_core_facade/` and `tests/main/`

Implementation:

- Mirror Rust file type constants in Python and export them from `sase.core.artifact_wire`.
- Add `file_types: tuple[str, ...] = ()` to Python `ArtifactQueryWire` and conversion helpers.
- Add `sase artifact list --file-type/-F` as a repeatable filter that populates `ArtifactQueryWire.file_types`.
- Update human list/detail formatting to surface file type for file artifacts without changing JSON shapes beyond the
  query input contract.
- Add `sase artifact sync` as a parser alias around rebuild:
  - same index/source/path options as rebuild where useful.
  - default to the same safe behavior as rebuild unless product wording requires a friendlier default.
  - help text must clearly say this is explicit historical sync/backfill and is not run on startup.
- Keep all CLI options with short forms.

Tests:

- Python wire shape/conversion tests for `file_types`.
- Facade binding-call tests include `file_types` in the query dict.
- CLI parser/handler tests for `list -F plan -F diff`.
- CLI parser/handler tests for `artifact sync` dispatching to the rebuild facade with the expected request.
- Docs and `/sase_artifact` skill examples parse.

Exit criteria:

- `just install` if the workspace venv is stale.
- `pytest tests/test_core_facade/test_artifact.py tests/main/test_artifact_cli_parser.py tests/main/test_artifact_cli_read_commands.py tests/main/test_artifact_cli_maintenance_commands.py`

## Phase 5: Cross-Language Migration Compatibility And E2E Coverage

Owner scope:

- `../sase-core/crates/sase_core_py/src/lib.rs` only if binding tests need adjustment for the new query field.
- `tests/main/test_artifact_cli_real_extension.py`
- `tests/test_core_facade/test_artifact.py`
- Any small Rust/Python parity fixture needed to prove compatibility

Implementation:

- Verify PyO3 conversion accepts and returns the extended `ArtifactQueryWire` shape.
- Add real-extension tests that build a historical fixture with agent artifacts, project files, prompt files, diffs,
  chats, and miscellaneous files, then run explicit sync/rebuild and assert:
  - file artifacts have exactly one canonical `metadata.artifact_type`.
  - `sase artifact list --file-type ...` returns the right buckets.
  - old `kind = "file"` rows without metadata still appear as `misc`.
  - directory-only paths are absent unless they contain non-directory artifacts.
- Add or update tests proving `sase ace` startup paths do not call `artifact_rebuild`/`sync`. This should be a targeted
  regression around existing TUI startup/action code, not a broad perf benchmark.
- Ensure `artifact_doctor` diagnostics for orphan directories are visible through Python.

Tests:

- `cargo test -p sase_core_py artifact`
- `pytest tests/main/test_artifact_cli_real_extension.py tests/test_core_facade/test_artifact.py`
- Targeted TUI startup regression test if a suitable existing test file is present.

Exit criteria:

- Cross-language wire and real extension tests pass.
- The implementation has not introduced automatic broad sync/rebuild on startup.

## Phase 6: Final Integration, Documentation, And Validation

Owner scope:

- Small integration fixes across touched Rust/Python files.
- `docs/artifacts.md`
- `src/sase/xprompts/skills/sase_artifact.md`
- Optional SDD tale documenting the landed model.

Implementation:

- Review the final behavior against Epic 1 acceptance criteria.
- Ensure help text and docs say:
  - historical artifacts may require `sase artifact sync` or `sase artifact rebuild`.
  - newly-created artifacts are indexed automatically by existing targeted refresh paths.
  - `sase ace` startup does not run broad sync.
  - file artifact types are `plan`, `diff`, `chat`, `project`, `prompt`, `misc`.
  - directory artifacts are only `/` or containers for non-directory artifacts.
- Add a short SDD tale if the project convention expects one for this epic.
- Run the full repo validation expected after file changes in this workspace.

Tests:

- In `../sase-core`: `cargo test -p sase_core artifact` and `cargo test -p sase_core_py artifact`.
- In this repo: `just install` if needed, then `just check`.

Exit criteria:

- `just check` passes.
- Epic 1 is ready for Epic 2 agents to depend on stable file type and directory semantics.

## Phase Dependencies

- Phase 1 must land before Phases 2, 4, or 5 because it defines the canonical Rust query/type contract.
- Phase 2 depends on Phase 1 classifier constants and helpers.
- Phase 3 can run after Phase 1, but should coordinate with Phase 2 if both touch `ingest.rs`; safest execution is Phase
  1, then Phase 2, then Phase 3.
- Phase 4 depends on Phase 1's query field and constants.
- Phase 5 depends on Phases 2, 3, and 4.
- Phase 6 is the final land/validation pass.

## Risks And Guardrails

- Avoid changing file artifact `kind` to `file:plan` etc. That would cause larger DB and UI churn than Epic 1 needs.
- Do not use `metadata.file_type` for the semantic type; existing project-node code already uses `file_type` for a
  different project-file concept. Use `metadata.artifact_type`.
- Do not run historical sync from `sase ace` startup or from the artifact modal.
- Do not delete old orphan directory rows as a first move unless the stale-derived cleanup path is clearly scoped and
  tested. Doctor diagnostics are safer and satisfy the epic's cleanup/diagnostic requirement.
- Keep all runtime behavior uniform across Claude, Gemini, Codex, and other providers. Classify artifacts by marker
  fields and files, not by assumptions about one runtime lacking capabilities.
