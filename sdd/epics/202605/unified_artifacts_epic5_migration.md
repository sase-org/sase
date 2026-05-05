---
legend: sdd/legends/202605/unified_artifacts.md
epic: 5
title: Unified Artifacts Epic 5 Migration Compatibility And Cleanup
create_time: 2026-05-05 14:06:06
status: wip
prompt: sdd/prompts/202605/unified_artifacts_epic5_migration.md
---

# Unified Artifacts Epic 5 Plan

## Scope

Implement Epic 5, "Migration, Compatibility, And Cleanup", from `sdd/legends/202605/unified_artifacts.md`.

Epic 1 through Epic 4 are already represented in this checkout:

- Rust graph storage, query, export, and ingestion live under `../sase-core/crates/sase_core/src/artifact/`.
- Python wire/facade and CLI surfaces live under `src/sase/core/artifact_wire/`, `src/sase/core/artifact_facade.py`,
  `src/sase/main/parser_artifact.py`, and `src/sase/main/artifact_handler.py`.
- `/sase_artifact` source exists at `src/sase/xprompts/skills/sase_artifact.md`.
- The `A` key opens `ArtifactPanelModal`, with the legacy run-log modal still available from inside the artifact panel.

This epic should make the unified artifact graph the operational default, fill compatibility gaps in historical state
and new runtime metadata, and then retire duplicated TUI surfaces only after parity is proven.

The work crosses the Rust/Python boundary. Shared graph derivation, identity, migration, and doctor behavior belong in
`../sase-core/crates/sase_core`; this repo should own CLI defaults, runtime marker writes, TUI removal/default behavior,
docs, and thin adapters over `sase_core_rs`.

## Product Contract

After Epic 5:

- `sase artifact rebuild` can backfill a user's existing `~/.sase` state without deleting source files or rewriting
  historical marker files unless an explicit repair command is used.
- Historical and archived state remains visible:
  - unnamed legacy agents use deterministic graph IDs
  - dismissed agents are still navigable
  - current and archive `*.gp` ChangeSpecs remain navigable
  - historical agent artifact directories remain linked to ChangeSpecs, plans, questions, retries, commits, files, and
    thoughts when metadata exists
- New runtime workflows write enough provider-neutral metadata for stable graph links.
- The artifact graph, not the old agent-specific artifact index or run-log modal, is the default discovery surface.
- Obsolete UI is removed or demoted only when tests prove the artifact panel has parity for the affected workflows.
- Operators have a short runbook for rebuild, tombstone, doctor, and repair behavior.

## Non-Goals

- Do not redesign the graph schema or add new link types unless an acceptance test cannot be satisfied with `parent`,
  `created`, `worker`, and `related`.
- Do not remove `~/.sase/agent_artifact_index.sqlite` in a destructive migration. It can remain as a compatibility index
  until all direct consumers are routed through the unified graph.
- Do not introduce runtime-specific branches for Claude, Gemini, Codex, or plugin providers. Provider-specific fields
  may be parsed when present, but all runtimes should emit the same SASE metadata contract.
- Do not rewrite historical marker files as part of default rebuild. If real-name assignment or marker repair is needed,
  make it explicit and documented.
- Do not remove old UI panels before parity tests land in the same phase or an earlier phase.

## Phase Breakdown

Each phase below is intended for a distinct implementation agent. Later agents should treat earlier phase outputs as
committed contracts and avoid broad refactors outside their ownership. Each implementation phase should run
`just install` first in this workspace and finish with `just check`; Rust-touching phases should also run focused
`cargo test` in `../sase-core`.

## Phase 5.1: Backfill Defaults And Legacy Visibility

Goal: make a default graph rebuild a reliable, non-destructive migration path for existing user state.

Dependencies: Epic 1, Epic 2, Epic 3.

Primary ownership:

- `../sase-core/crates/sase_core/src/artifact/ingest.rs`
- `../sase-core/crates/sase_core/src/artifact/query.rs`
- `../sase-core/crates/sase_core/tests/` artifact fixtures
- `src/sase/core/artifact_facade.py`
- `src/sase/main/artifact_handler.py`
- focused tests under `tests/test_core_facade/` and `tests/main/`

Implementation shape:

- Audit and harden `ArtifactRebuildRequestWire` defaults so an omitted request covers:
  - `~/.sase/projects`
  - current workspace root
  - current workspace `sdd/beads`
  - agent artifact directories under all supported project layouts
- Preserve non-destructive behavior:
  - default rebuild upserts derived rows and links
  - stale cleanup stays opt-in
  - tombstones suppress derived rows without deleting source files
- Verify unnamed legacy agents use the documented fallback ID `agent:<project>:<workflow>:<timestamp>`.
- Include fallback ID details in the agent node payload/metadata so users can trace a graph node back to its artifact
  directory and later assign a real agent name.
- Ensure dismissed agent artifact directories are included in ingestion when their marker files remain on disk.
- Ensure current and archive project files both ingest in default rebuilds.
- Ensure historical agent-created files referenced by `done.json`, `agent_meta.json`, prompt-step markers,
  `plan_path.json`, raw prompts, diffs, responses, question files, and thought files remain navigable.
- Add or strengthen `sase artifact doctor` diagnostics for migration-specific gaps:
  - fallback agent IDs in use
  - unresolved timestamp links
  - unresolved ChangeSpec/bead references
  - stale derived source rows when `--stale-cleanup mark` is used

Acceptance checks:

- A fixture with current and archive `*.gp` files, dismissed agents, unnamed agents, and historical created files
  rebuilds into one connected graph without source deletion.
- `artifact_show` on an unnamed historical agent returns a fallback ID, source artifact directory metadata, created file
  links, and any resolvable related ChangeSpec links.
- `sase artifact rebuild -j` with default-like paths reports mutation counts and no destructive cleanup.
- `sase artifact doctor -j` reports migration warnings deterministically.

Suggested verification:

- In `../sase-core`: focused `cargo test -p sase_core artifact::ingest artifact::query`.
- In this repo: targeted artifact facade/CLI tests, then `just check`.

## Phase 5.2: Provider-Neutral Agent Metadata Contract

Goal: define and write one stable metadata contract for new agents so future graph links do not depend on heuristics.

Dependencies: Phase 5.1.

Primary ownership:

- `src/sase/axe/run_agent_runner_setup.py`
- `src/sase/axe/run_agent_runner.py`
- `src/sase/axe/run_agent_phases.py`
- `src/sase/axe/run_agent_retry_spawn.py`
- `src/sase/agent/launcher.py`
- `src/sase/agent/multi_prompt_launcher.py`
- `src/sase/agent/multi_agent_xprompt.py`
- agent launch and retry tests under `tests/`

Implementation shape:

- Add a small Python helper for updating artifact graph metadata in marker JSON. Prefer a narrow module such as
  `src/sase/axe/artifact_metadata.py` or a similarly local helper rather than scattering ad hoc JSON writes.
- Write provider-neutral fields into `agent_meta.json` at launch/finalization time:
  - `artifact_schema_version`
  - stable `artifact_agent_id`
  - `artifact_source_dir`
  - `changespec_name` or existing `cl_name`
  - `bead_id` when known
  - `parent_agent_timestamp` / `parent_agent_name` when spawned from another agent
  - retry chain fields already used by the loader, normalized into the same contract
  - runtime/provider/model fields using existing shared names
- Preserve existing marker fields for compatibility. New fields should augment, not rename, current data.
- Ensure the helper is used uniformly by single-agent launches, multi-prompt launches, workflow launches, and retry
  spawn.
- Avoid runtime-specific branches. The runtime/provider may be a metadata value, but the write path should be common.
- Add tests that construct marker files for Claude/Gemini/Codex/plugin-like launches through the same helper contract
  rather than provider-specific fixtures.

Acceptance checks:

- New launched agents have `artifact_agent_id` equal to their stable agent name when named and the fallback ID when not
  named.
- Retry-spawn metadata links parent and child agents without relying solely on timestamp heuristics.
- Multi-agent xprompt children write the same metadata shape as single-agent launches.
- Existing loader tests still pass with older markers that lack the new fields.

Suggested verification:

- Targeted launch, retry, multi-prompt, and agent-name tests.
- `just check`.

## Phase 5.3: Plan, Question, Epic Work, And Commit Workflow Links

Goal: make higher-level workflows produce enough metadata for stable graph links to plans, questions, beads,
ChangeSpecs, commits, and follow-up agents.

Dependencies: Phase 5.2.

Primary ownership:

- `src/sase/axe/run_agent_exec_plan.py`
- `src/sase/axe/run_agent_exec_plan_artifacts.py`
- `src/sase/axe/run_agent_exec_plan_sdd.py`
- `src/sase/bead/work.py`
- `src/sase/bead/cli_work.py`
- `src/sase/workflows/commit/`
- `src/sase/workflows/commit_utils/`
- relevant tests under `tests/test_axe_run_agent_exec_plan_*`, `tests/test_bead/`, and `tests/test_commit_*`

Implementation shape:

- Extend the metadata helper from Phase 5.2 for workflow relationship fields:
  - `plan_path`
  - `sdd_prompt_path`
  - `sdd_plan_path`
  - `plan_submitted_at`
  - `questions_submitted_at`
  - `feedback_submitted_at`
  - `epic_bead_id`
  - `phase_bead_id`
  - `legend_bead_id`
  - `commit_changespec_name`
  - `commit_entry_id` or commit number when available
- Update plan approval and question handling to record explicit links between planner, question, feedback, and coder
  agents instead of relying only on timestamp fields.
- Update `sase bead work` launch metadata so each phase agent records the phase bead it is working and the final land
  agent records the epic bead it lands.
- Update commit workflow marker output so commits can link back to the agent, ChangeSpec, and created diff/chat
  artifacts through stable fields.
- Keep existing `plan_path.json`, `done.json`, and ChangeSpec COMMITS drawers compatible. Do not remove old fields in
  this phase.
- If the Rust ingester cannot yet consume one of the new fields, add a focused Rust ingestion follow-up in this phase so
  the field is immediately useful.

Acceptance checks:

- Plan approval creates graph-resolvable metadata from planner to coder, plan files, and ChangeSpec.
- Question handling creates graph-resolvable metadata for question files and follow-up chain agents.
- `sase bead work` phase agents produce `worker` links from phase bead to phase agent after rebuild.
- Commit workflow fixtures produce `related` links between ChangeSpec/commit artifacts and the responsible agent where
  metadata exists.
- Older markers that lack these fields continue to ingest with best-effort heuristic links.

Suggested verification:

- Targeted plan/question/bead/commit tests.
- Focused Rust artifact ingestion tests if Rust consumers are changed.
- `just check`.

## Phase 5.4: Default Graph Refresh And Compatibility Routing

Goal: route default user-facing artifact discovery through the unified graph and keep compatibility indexes as fallback
implementation details.

Dependencies: Phases 5.1 through 5.3.

Primary ownership:

- `src/sase/main/artifact_handler.py`
- `src/sase/ace/tui/actions/artifacts.py`
- `src/sase/ace/tui/actions/event_handlers.py`
- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/models/_loaders/`
- `src/sase/core/agent_scan_facade.py`
- `src/sase/agent/agent_artifacts_cache.py`
- TUI and loader tests under `tests/ace/tui/`

Implementation shape:

- Add explicit rebuild/upsert integration points for common state changes:
  - project file changes
  - bead JSONL changes
  - new or updated agent artifact marker files
  - plan/question/commit marker writes from Phase 5.3
- Prefer targeted `artifact_upsert_path` or targeted `artifact_rebuild(... target_path/artifact_dir ...)` over full
  rebuilds in TUI refresh paths.
- When `ArtifactPanelModal` opens a missing start artifact, trigger a bounded targeted rebuild for that context and
  retry once before showing a missing-artifact error.
- Keep the old `~/.sase/agent_artifact_index.sqlite` available for existing agent list loading paths until a focused
  replacement is proven faster or equivalent. Do not delete the file.
- Add tests that prove normal `j/k` movement and row highlight changes do not rebuild or scan the graph.
- Add tests that prove explicit source changes trigger targeted graph refresh without full rebuilds.

Acceptance checks:

- Opening the artifacts panel from AXE, CLs, and Agents works after fresh agent activity without requiring the user to
  manually run `sase artifact rebuild`.
- A missing but valid current ChangeSpec or selected agent can be recovered by a targeted rebuild.
- Existing agent list startup performance does not regress.
- Compatibility fallback paths are documented in comments/tests and are not user-visible defaults.

Suggested verification:

- Targeted TUI artifact modal and loader tests.
- Existing agent startup/perf smoke tests if touched.
- `just check`.

## Phase 5.5: Retire Obsoleted UI Surfaces After Parity

Goal: remove or demote duplicated TUI surfaces only after the artifact panel covers their workflows.

Dependencies: Phase 5.4.

Primary ownership:

- `src/sase/ace/tui/modals/agent_run_log_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_modal.py`
- `src/sase/ace/tui/modals/artifact_panel_renderers.py`
- `src/sase/ace/tui/widgets/agent_detail.py`
- `src/sase/ace/tui/widgets/file_panel/`
- `src/sase/ace/tui/widgets/thinking_panel.py`
- `src/sase/ace/tui/widgets/keybinding_footer.py`
- `src/sase/ace/tui/modals/help_modal/bindings.py`
- TUI tests under `tests/ace/tui/`

Implementation shape:

- Establish parity tests first:
  - ChangeSpec artifact views expose linked agents, commits, plans, questions, transcripts, diffs, and beads.
  - Agent artifact views expose created artifacts, related ChangeSpecs/beads, retry/follow-up chain links, and thoughts.
  - File artifacts support opening in editor and preview behavior comparable to the old file panel.
  - Thought artifacts render enough timeline detail to replace the old thinking panel for historical inspection.
- Remove `A`-specific legacy run-log paths that remain after Epic 4. If a separate compatibility command is still
  useful, keep it unadvertised or explicitly labeled legacy.
- Demote or remove old footer/help references that direct users to duplicated run-log/file/thinking surfaces for
  artifact discovery.
- Do not remove live agent detail panels that still serve active monitoring unless tests prove the artifact panel has an
  equivalent active-refresh experience. Historical inspection can move first; live monitoring can remain.
- Delete obsolete tests only after replacing them with artifact-panel parity tests.

Acceptance checks:

- No default keybinding or help surface presents the old Agent Run Log as the primary artifact discovery path.
- Artifact panel tests cover every workflow previously covered by the run-log modal for ChangeSpec history.
- Agents tab file/thinking surfaces are either still intentionally present for live monitoring or replaced with passing
  parity tests.
- Small terminal layout tests still pass without overlapping text or unusable controls.

Suggested verification:

- Focused TUI modal, renderer, footer, and help tests.
- `just check`.

## Phase 5.6: Docs, Runbook, And Migration Quality Gate

Goal: document the new default graph behavior and prove the full migration path is operable.

Dependencies: Phases 5.1 through 5.5.

Primary ownership:

- `docs/artifacts.md`
- `docs/` perf/debug runbook files if present
- `src/sase/xprompts/skills/sase_artifact.md`
- generated skills through `sase init-skills`
- `sdd/tales/202605/` handoff or completion note
- final integration tests and command smoke checks

Implementation shape:

- Document the artifact graph at a product level:
  - artifact kinds and IDs
  - link direction and meaning
  - manual vs derived rows
  - tombstone behavior
  - fallback legacy agent IDs
  - dismissed-agent/archive visibility
- Add operator guidance:
  - default rebuild
  - targeted rebuild by project path, bead store, or agent artifact directory
  - doctor interpretation
  - stale cleanup with `mark`
  - when to repair marker metadata manually or with future commands
- Update `/sase_artifact` source if CLI defaults or JSON fields changed, then regenerate skills using the repo's
  generated-skill workflow. Do not hand-edit generated output.
- Add or update smoke tests that exercise:
  - rebuild
  - doctor
  - CLI show/list/graph on a migrated fixture
  - TUI modal launch with migrated fixture data
- Record residual compatibility risks in a short SDD tale/handoff.

Acceptance checks:

- Docs explain rebuild/doctor/tombstone behavior without exposing raw SQL as the primary model.
- `/sase_artifact` examples match the final CLI contract.
- Final quality gate passes:
  - focused Rust tests for artifact migration behavior
  - targeted Python CLI/TUI tests
  - `just check`
- The completion note names any remaining legacy surfaces intentionally left in place.

## Cross-Phase Guardrails

- Keep source deletion out of rebuild paths. The artifact graph indexes existing state; it does not own the source
  files.
- Keep marker writes additive and backward-compatible.
- Treat fallback legacy IDs as stable graph IDs, not user-facing names to be silently rewritten.
- Prefer targeted rebuilds for runtime refresh paths. Full rebuilds are acceptable as explicit CLI/operator actions.
- Keep Rust as the source of truth for graph derivation and validation.
- Keep Python CLI/TUI code thin and presentation-oriented.
- Do not skip parity tests before removing legacy UI.

## Suggested Agent Order

1. Phase 5.1 first. It validates default migration/backfill and historical visibility.
2. Phase 5.2 second. It establishes the common metadata writer for new agents.
3. Phase 5.3 third. It applies that contract to plan/question/epic/commit workflows.
4. Phase 5.4 fourth. It turns the graph into the default refreshed discovery surface.
5. Phase 5.5 fifth. It retires duplicated UI only after parity is proven.
6. Phase 5.6 last. It documents behavior and runs the migration quality gate.
