---
create_time: 2026-05-05 08:26:17
status: wip
prompt: sdd/prompts/202605/unified_artifacts.md
---
# Unified Artifact Graph Plan

## Goal

Unify SASE artifact discovery, relationship tracking, CLI management, and TUI navigation around one fast artifact graph.
The graph should make project specs, ChangeSpecs, commits, directories, beads, agents, agent-created files, questions,
plans, diffs, chat transcripts, and agent thoughts navigable from one place.

The performance-sensitive backend belongs in `../sase-core/crates/sase_core`. This repo should own Python CLI wiring,
Textual widgets/actions, generated xprompt skill source files, and thin adapters over `sase_core_rs`.

## Product Shape

Artifacts are graph nodes. Links are directed typed edges. For `parent`, direction is child -> parent, so walking
reverse `parent` edges gives tree children and walking forward reaches the root.

Artifact IDs:

- Root directory: `/`
- File artifacts: absolute normalized file path
- Directory artifacts: absolute normalized directory path, with `/` as the root sentinel
- Project artifacts: absolute `~/.sase/projects/*/*.gp` file path
- ChangeSpec artifacts: ChangeSpec `NAME`
- Commit artifacts: `<changespec_name>:<commit_number>`
- Bead artifacts: bead ID
- Agent artifacts: agent name when available, with a documented temporary fallback for legacy unnamed agents
- Agent thought artifacts: content-addressed thought IDs, `thought:<sha256-prefix>`, with the thought text stored in
  node detail payload and linked to the agent by `created`

Link types initially needed:

- `parent`: containment, hierarchy, or logical ownership
- `created`: agent-created transcripts, plans, diffs, questions, and thoughts
- `worker`: bead -> agent responsible for work
- `related`: planner/coder/follow-up transcript chains, retry chains, feedback/question rounds, and future
  non-hierarchical associations

The artifacts panel should open from `A` on every tab:

- AXE tab: root directory artifact
- CLs tab: current ChangeSpec artifact
- Agents tab: current agent artifact

The panel should combine tree navigation with link navigation. Each artifact view should show the current artifact,
metadata, direct tree children, typed inbound/outbound links, and a detail preview appropriate for the artifact type.

## Architecture

Create a Rust `artifact` module in `../sase-core/crates/sase_core` with a SQLite-backed graph index. Use Rust for:

- artifact and link wire records
- graph schema and migrations
- source scanners/builders for projects, ChangeSpecs, commits, directories, beads, and agent artifact directories
- incremental upserts and removals
- neighbor, path-to-root, children, detail, and search queries
- graph exports using `petgraph` for traversal and DOT/Mermaid export
- validation/doctor checks for root reachability, dangling links, duplicate IDs, and stale derived rows

Use Python in this repo for:

- `sase artifact` argparse registration and output formatting
- `sase.core.artifact_*` wire/adapters over `sase_core_rs`
- Textual modal/widget presentation and keybinding integration
- editor-opening behavior for file artifacts
- generated `/sase_artifact` skill source in `src/sase/xprompts/skills/`

The graph has two source classes:

- Derived rows from existing SASE state, rebuilt/upserted from scanners.
- Manual rows and links created by `sase artifact add/remove`. Removing a derived artifact/link should tombstone only
  the graph overlay, not delete the source file or source metadata.

Default graph index path: `~/.sase/artifacts.sqlite`. The existing `~/.sase/agent_artifact_index.sqlite` can remain
during migration; later phases can consolidate or delegate agent-specific queries through the broader artifact index.

## Epic 1: Rust Artifact Core And Persistence

Build the graph substrate in `../sase-core`.

Phase 1.1: Wire Types And Schema

- Add `artifact/wire.rs` with `ArtifactKindWire`, `ArtifactNodeWire`, `ArtifactLinkWire`, `ArtifactDetailWire`,
  `ArtifactQueryWire`, `ArtifactGraphWire`, and mutation result records.
- Define schema versioning and rectangular JSON shapes matching existing Rust/Python wire conventions.
- Add SQLite tables: `artifacts`, `artifact_links`, `artifact_payloads`, `source_watermarks`, `manual_tombstones`,
  `meta`.
- Add indexes for `id`, `kind`, `link_type`, `source_id`, `target_id`, `parent` children, and text search fields.

Phase 1.2: Core Mutations And Queries

- Implement add/upsert/remove node, add/remove link, show/detail, list/search, neighbors, tree children, path-to-root,
  and root reachability checks.
- Use transactions and WAL, following the existing agent artifact index style.
- Add unit tests for directionality, root invariants, duplicate upserts, tombstones, and query ordering.

Phase 1.3: Graph Export

- Add `petgraph` to `sase_core`.
- Implement graph subgraph materialization and DOT/Mermaid exports around a node, by depth, by link type, and for full
  graph snapshots with limits.
- Keep exports deterministic and bounded by default.

Phase 1.4: PyO3 Bindings

- Expose Rust bindings in `sase_core_rs`: `artifact_add`, `artifact_remove`, `artifact_list`, `artifact_show`,
  `artifact_graph`, `artifact_rebuild`, `artifact_upsert_path`, and `artifact_doctor`.
- Add parity tests proving Python wire conversion matches Rust JSON output.

## Epic 2: Source Ingestion And Link Construction

Teach the Rust core how to derive graph rows from existing SASE state.

Phase 2.1: Projects, ChangeSpecs, Commits, And Directories

- Scan `~/.sase/projects/*/*.gp` and `*-archive.gp`.
- Use the existing Rust ChangeSpec parser for project contents.
- Create Project file artifacts linked to `/` by `parent`.
- Create ChangeSpec artifacts linked to their project file by `parent`.
- Create Commit artifacts linked to their ChangeSpec by `parent`.
- Create Directory artifacts for discovered project, workspace, `sdd/beads`, artifact, and file-parent directories.
- For directory artifacts, link to the longest known containing directory by `parent`, else `/`.

Phase 2.2: Beads

- Reuse Rust bead storage/read modules to ingest `sdd/beads`.
- Create Bead artifacts, direct parent bead `parent` links, and `parent` links to the absolute `sdd/beads` directory
  artifact.
- Link beads to worker agents by `worker` using explicit epic/phase automation metadata when available.
- Add a follow-up phase to write worker-agent metadata at launch time if current bead/agent metadata is insufficient.

Phase 2.3: Agents And Created File Artifacts

- Reuse the existing Rust agent artifact scanner to create Agent artifacts and file artifacts for: chat transcripts,
  `live_reply.md`, response files, diffs, plan files, question files, generated Markdown PDFs, images, raw prompts, and
  output logs.
- Add `created` links from Agent -> each created file artifact.
- Link agent artifacts to related ChangeSpecs by `related` when `cl_name` or meta ChangeSpec fields are present.
- Link planner/coder/follow-up/retry chains by `related` using existing retry metadata, plan markers, question markers,
  feedback markers, parent timestamps, and role suffixes.

Phase 2.4: Agent Thoughts

- Move thought extraction into Rust where provider log/session parsing is stable enough; keep provider-specific path
  discovery in Python only if required.
- Represent each thought as `thought:<sha256-prefix>` with payload fields: text, source provider, source file/session,
  ordinal, timestamp if known, and a short generated display title.
- Link Agent -> Thought by `created`.
- In TUI detail, render thoughts as a timeline: source badge, timestamp/ordinal, compact title, expandable text. This
  replaces the old thinking panel only after the new panel has equivalent or better coverage.

Phase 2.5: Incremental Updates

- Add rebuild-all plus targeted upsert paths for project file changes, bead JSONL changes, and agent artifact directory
  marker changes.
- Integrate with existing file watcher refresh paths so the TUI can trigger cheap targeted upserts instead of full
  scans.
- Add stale-row cleanup and doctor diagnostics.

## Epic 3: `sase artifact` CLI And `/sase_artifact` Skill

Expose the graph outside the TUI.

Phase 3.1: Python Facade And CLI Skeleton

- Add `src/sase/core/artifact_wire.py` and `artifact_facade.py`.
- Add top-level parser/handler modules for `sase artifact`.
- Required subcommands: `add`, `remove`, `list`, `show`, `graph`, `rebuild`, `doctor`.
- Follow repo convention: every argument gets a short option.

Phase 3.2: CLI Behavior

- `sase artifact add`: add a manual artifact and optionally one or more links.
- `sase artifact remove`: remove a manual artifact/link or tombstone a derived artifact/link.
- `sase artifact list`: filter by kind, link type, project, text, source, or root reachability; JSON and table output.
- `sase artifact show`: full detail, typed inbound/outbound links, path to root, and source payload summary.
- `sase artifact graph`: output Mermaid, DOT, JSON, or compact text around a node or query.
- `sase artifact rebuild`: rebuild derived graph rows.
- `sase artifact doctor`: report dangling/unreachable/stale graph issues.

Phase 3.3: Generated Skill

- Add `src/sase/xprompts/skills/sase_artifact.md` with `skill: true`.
- Include command examples and JSON-stable fields, modeled after `sase_agents_status`.
- Run `sase init-skills --force` after the skill source lands, and ensure generated files are not hand-edited.

Phase 3.4: Tests And Docs

- Add CLI parser/handler tests, Rust binding tests, and documentation snippets in `docs/`.

## Epic 4: Artifacts TUI Panel

Build the new fast `A` panel.

Phase 4.1: Modal Skeleton And Keymap

- Replace `show_agent_run_log: "A"` with `open_artifacts_panel: "A"` in `default_config.yml` and fallback bindings.
- Add `ArtifactPanelModal` with async initial load, loading/error states, and keyboard navigation.
- Launch contexts:
  - AXE -> `/`
  - CLs -> current ChangeSpec `NAME`
  - Agents -> current agent name/fallback ID

Phase 4.2: Navigation Model

- Maintain a stack/history for artifact navigation.
- Show tree children from reverse `parent` links and typed link groups for all inbound/outbound links.
- Add actions for open selected link, back, forward, parent, root, search/filter, copy artifact ID, open file in editor,
  and graph preview/export.
- Keep Rust queries narrow: selected node detail, children page, links page, and optional detail preview only.

Phase 4.3: Detail Renderers

- File artifacts: path, size/mtime if available, preview with syntax/image handling reused from existing file panel
  where appropriate, and editor action.
- Directory artifacts: child artifact list and filesystem summary.
- Project/ChangeSpec/Commit artifacts: parsed metadata, direct linked agents/files/beads, and source location.
- Bead artifacts: bead status, parent/children/dependencies, worker agent link.
- Agent artifacts: status, model/provider/workspace, transcripts, diffs, plans, questions, thoughts, retry/follow-up
  links, and related ChangeSpec/bead.
- Thought artifacts: the timeline card design from Epic 2.4.

Phase 4.4: Obsolete Panel Coverage

- Ensure ChangeSpec views clearly show linked agents, commits, plans, questions, transcripts, diffs, and beads.
- Ensure Agent views clearly show all created artifacts and related ChangeSpecs/beads.
- Keep old Agent Run Log, file panel, and thinking panel behind current behavior until the artifacts panel has parity.

Phase 4.5: Performance Verification

- Add modal tests with fake Rust facade responses.
- Add a smoke benchmark for opening from each tab on a large fixture graph.
- Verify j/k navigation does not perform broad scans and detail preview work is cancellable/debounced.

## Epic 5: Migration, Compatibility, And Cleanup

Make the new graph the default and retire duplicated surfaces.

Phase 5.1: Backfill And Legacy Handling

- Rebuild graph from existing user state without destructive changes.
- Handle unnamed legacy agents with deterministic fallback IDs and a path toward assigning real names.
- Preserve dismissed-agent archive visibility.
- Ensure archive `*.gp` ChangeSpecs and historical agent artifacts remain navigable.

Phase 5.2: Runtime Integration

- Update agent launch, plan approval, question handling, epic work, retry spawn, and commit workflows to write any
  missing metadata needed for stable artifact links.
- Avoid runtime-specific branches; Claude, Gemini, Codex, and plugin providers should all feed the same graph contract.

Phase 5.3: Remove Obsoleted UI

- After parity tests pass, remove or demote the old Agent Run Log modal from `A`.
- Fold Agents file/thinking panel functionality into artifact detail renderers.
- Update footer/help text and keybinding docs.

Phase 5.4: Docs And Operator Runbook

- Document graph schema at a product level, not as raw SQL.
- Add `sase artifact doctor` guidance to the perf/debug runbook.
- Document rebuild, tombstone, and repair behavior.

## Epic 6: End-To-End Quality Gate

Phase 6.1: Rust Tests

- Unit tests for all graph primitives.
- Fixture tests for project/ChangeSpec/commit/bead/agent ingestion.
- Binding parity tests for all exposed artifact commands.

Phase 6.2: Python Tests

- CLI parser/handler tests for all subcommands.
- Facade conversion tests.
- TUI modal behavior tests with mocked artifact graph responses.
- Keybinding/footer tests for `A`.

Phase 6.3: Integrated Checks

- In `../sase-core`: run `cargo test`.
- In this repo after implementation changes: run `just install` then `just check`.
- Add targeted performance measurements for graph rebuild, targeted upsert, and modal open latency.

## Implementation Order Recommendation

Start with Epic 1 and only a tiny manual CLI proof path, then land Epic 2 ingestion in slices. Do not build the full TUI
first; the modal should depend on stable Rust query contracts. Once `artifact show` and `artifact graph` can answer the
same questions the TUI needs, Epic 4 becomes mostly presentation work.

The first implementation agent should take Epic 1 Phase 1.1 and 1.2 only, with ownership of `../sase-core` artifact
wire/schema/query primitives and matching Python wire stubs if needed. Later agents can work in parallel across
ingestion sources because Projects/ChangeSpecs, Beads, Agents, and Thoughts have mostly disjoint scanners.
