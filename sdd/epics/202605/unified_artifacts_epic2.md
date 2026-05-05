---
create_time: 2026-05-05 10:30:33
status: wip
prompt: sdd/prompts/202605/unified_artifacts_epic2.md
---
# Unified Artifacts Epic 2 Implementation Plan

## Scope

Implement Epic 2, "Source Ingestion And Link Construction", from `sdd/legends/202605/unified_artifacts.md`.

Epic 1 has already landed the artifact graph substrate: Rust wire/store/query/export APIs in
`../sase-core/crates/sase_core/src/artifact/`, PyO3 bindings in `../sase-core/crates/sase_core_py`, and the thin Python
facade in `src/sase/core/artifact_facade.py`. Epic 2 should replace the current placeholder rebuild/upsert behavior with
real derived graph ingestion from existing SASE state.

The core boundary matters here: scanners, source-to-node/link construction, incremental rebuild logic, stale cleanup,
and validation belong in `../sase-core/crates/sase_core`. Python in this repo should stay thin: binding request/response
mirrors, facade helpers, and any unavoidable provider-specific path discovery that cannot live in Rust.

## Product Contract

After this epic, a rebuild of the default artifact index should derive graph rows for:

- Project `.gp` files under `~/.sase/projects/*/*.gp` and `*-archive.gp`
- ChangeSpecs and commits parsed from those project files
- Directory artifacts needed to navigate project files, workspaces, `sdd/beads`, agent artifact directories, and created
  file parents
- Beads from `sdd/beads`
- Agents from the existing Rust agent artifact scanner
- Agent-created file artifacts
- Agent thoughts where stable extraction is available

All derived rows must respect Epic 1's overlay semantics: manual tombstones suppress derived rows/links, and rebuilds do
not delete source files or user-managed metadata.

## Existing Architecture Context

Relevant Rust modules:

- `sase_core::artifact`: graph store, mutation/query/export functions, wire records, root `/` invariant
- `sase_core::parser::parse_project_bytes`: Rust ChangeSpec parser producing `ChangeSpecWire` with commits
- `sase_core::bead::read_store_issues`: JSONL-backed bead reader producing `IssueWire`
- `sase_core::agent_scan`: Rust scanner for `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>/`

Relevant Python surface:

- `src/sase/core/artifact_wire.py` and `artifact_facade.py`: strict binding mirror
- `src/sase/core/agent_scan_wire.py`: Python mirror of existing agent scan shape
- `src/sase/axe/*` and `src/sase/ace/tui/*`: producers and consumers of agent marker files
- `src/sase/ace/tui/widgets/thinking_panel.py` and `src/sase/ace/tui/thinking/`: current Python thinking extraction
- `src/sase/bead/work.py`: epic/legend work automation; phase agents are named after bead IDs, and phase beads are
  pre-claimed with `assignee=<phase_bead_id>`

## Non-Goals

- Do not build the `sase artifact` CLI. That is Epic 3.
- Do not build the artifacts TUI panel or replace the `A` keybinding. That is Epic 4.
- Do not remove the old agent artifact index. Migration and cleanup are Epic 5.
- Do not invent runtime-specific branches. Claude, Gemini, Codex, and plugin providers should feed the same artifact
  contract whenever their metadata is available.
- Do not add new graph link types unless a phase proves the existing initial set is insufficient. Use payload metadata
  for source-specific details such as bead dependencies unless a later epic explicitly expands the link taxonomy.

## Source And ID Conventions

Use the legend's artifact IDs:

- Root: `/`
- File artifacts: absolute normalized file paths
- Directory artifacts: absolute normalized directory paths, with `/` as the root sentinel
- Project artifacts: absolute normalized `.gp` file paths
- ChangeSpec artifacts: ChangeSpec `NAME`
- Commit artifacts: `<changespec_name>:<commit_number>`
- Bead artifacts: bead ID
- Agent artifacts: stable agent name when available, otherwise `agent:<project>:<workflow>:<timestamp>` as the temporary
  legacy fallback
- Thought artifacts: `thought:<sha256-prefix>`

Use the existing link direction:

- `parent`: child -> parent
- `created`: agent -> created file/thought
- `worker`: bead -> agent
- `related`: non-hierarchical relationships such as agent retry/follow-up chains and ChangeSpec associations

Derived row source metadata should be deterministic. Prefer explicit source kind constants, for example:

- `project_file`
- `changespec`
- `commit`
- `directory`
- `bead_store`
- `agent_artifact`
- `agent_created_file`
- `agent_thought`

The exact names may vary if the implementation finds an existing local pattern, but all phases must use one shared set
of constants rather than ad hoc strings.

## Phase Breakdown

Each phase below is intended for one distinct implementation agent. Later agents should treat prior phases as committed
contracts and avoid broad refactors outside their ownership.

### Phase 1: Ingestion Framework, Rebuild Requests, And Path Helpers

Dependencies: Epic 1 only.

Owner scope:

- `../sase-core/crates/sase_core/src/artifact/`
- `../sase-core/crates/sase_core/src/lib.rs`
- `../sase-core/crates/sase_core_py/src/lib.rs`
- `src/sase/core/artifact_wire.py`
- `src/sase/core/artifact_facade.py`
- Focused Rust/Python binding tests

Implementation:

- Add a small ingestion module, for example `artifact/ingest.rs`, that owns source constants, source-selection options,
  mutation aggregation, and shared helpers.
- Define rebuild/upsert request wire records instead of accepting an untyped dict forever. The request should support:
  - index path remains a binding argument
  - optional `projects_root`
  - optional `workspace_root`
  - optional `beads_dir`
  - optional include/exclude source list
  - optional targeted path or artifact directory
  - stale cleanup mode
  - default behavior matching user state under `~/.sase` plus the current workspace
- Implement reusable helpers for:
  - absolute path normalization
  - file node construction
  - directory node construction
  - directory parent selection: longest known containing directory, else `/`
  - deterministic parent link construction
  - derived payload upsert
  - mutation result merging
- Wire `artifact_rebuild` through the typed request and have it call the ingestion dispatcher. It can still ingest zero
  sources in this phase, but it should no longer return the Epic 1 "no ingesters registered" placeholder once later
  phases register sources.
- Wire `artifact_upsert_path` through the same path helpers and make it create file/directory nodes plus directory
  parent links, not just a lone node.
- Preserve tombstone behavior by calling Epic 1 mutation APIs rather than writing SQL directly from scanners.

Tests:

- Path upsert creates a file node, parent directory nodes, and `parent` links to `/`.
- Directory parent selection is deterministic and longest-known-parent wins.
- Rebuild request parsing defaults are stable through PyO3 and Python facade conversion.
- Tombstoned derived path nodes are not resurrected by path upsert.

Exit criteria:

- `cargo test -p sase_core artifact`
- `cargo test -p sase_core_py artifact`
- Targeted Python facade tests for the new request wire shape

### Phase 2: Projects, ChangeSpecs, Commits, And Core Directories

Dependencies: Phase 1.

Owner scope:

- Rust ingestion code for project files, ChangeSpecs, commits, and directory artifacts
- Rust fixtures/tests for `.gp` and `*-archive.gp` scans
- Minimal Python binding/facade test updates only if request fields need adjustment

Implementation:

- Scan `~/.sase/projects/*/*.gp` and `~/.sase/projects/*/*-archive.gp`, using a caller-supplied `projects_root` in
  tests.
- Parse each project file with `parse_project_bytes`; unreadable or invalid files should be reported in mutation result
  errors without aborting the whole rebuild.
- Create project file artifacts:
  - kind `project`
  - ID absolute normalized `.gp` path
  - `parent` link to `/` or to a known directory artifact if Phase 1 helpers make that natural
  - payload summarizing project name, archive/current file type, source path, mtime/size when available
- Create ChangeSpec artifacts:
  - kind `changespec`
  - ID `ChangeSpecWire.name`
  - `parent` link to the project artifact
  - payload containing the parsed `ChangeSpecWire` or a compact equivalent suitable for TUI detail rendering
  - searchable text including name, status, project, parent, bug, description, CL/PR, and commit notes
- Create commit artifacts:
  - kind `commit`
  - ID `<changespec_name>:<commit_number>`
  - `parent` link to the ChangeSpec
  - payload from `CommitWire`
- Create directory artifacts for:
  - `projects_root`
  - project directories under it
  - the current workspace root when provided
  - `sdd/beads` when present
  - parent directories of project files
- Make source cleanup for project-derived rows work at the project-file granularity, so removing a `.gp` source marks
  only rows derived from that source as stale.

Tests:

- Current and archive project files both produce project, ChangeSpec, and commit nodes.
- `parent` traversal from commit -> ChangeSpec -> project -> root is correct.
- ChangeSpec duplicate names across current/archive files are deterministic and diagnosed. Prefer not to silently
  overwrite distinct source payloads without a doctor issue.
- A malformed `.gp` file records an error but other project files still ingest.
- Re-ingesting after a commit entry changes updates payload/search text without duplicating rows.

Exit criteria:

- `cargo test -p sase_core artifact::ingest` or equivalent focused tests
- `artifact_show` on a commit fixture includes useful path-to-root and payload detail

### Phase 3: Bead Ingestion And Worker Link Inputs

Dependencies: Phase 1. Can run in parallel with Phase 2 if the shared source constants are already landed.

Owner scope:

- Rust ingestion code for `sdd/beads`
- Rust bead fixture tests
- Small agent-launch metadata follow-up design note if existing metadata is insufficient

Implementation:

- Reuse `read_store_issues(beads_dir)` and existing `IssueWire` data; do not reimplement bead JSONL parsing.
- Create a directory artifact for the absolute `sdd/beads` directory and link it into the directory tree.
- Create one bead artifact per issue:
  - kind `bead`
  - ID `IssueWire.id`
  - payload containing status, issue type, tier, title, owner, assignee, parent ID, changespec metadata, dependencies,
    and design path
  - searchable text including ID, title, status, tier, owner, assignee, and ChangeSpec metadata
- Create `parent` links:
  - child bead -> parent bead when `parent_id` is present
  - top-level bead -> absolute `sdd/beads` directory artifact when no parent bead is present
- Prepare worker link inputs:
  - When `assignee` names an existing or inferable agent ID, create `worker` link bead -> agent.
  - For epic/phase automation, treat `assignee=<phase_bead_id>` as an intended agent ID because `sase bead work` names
    phase agents after bead IDs.
  - If the target agent node does not exist yet, store a deterministic payload field such as `pending_worker_agent_id`
    and let the final reconciliation phase materialize the link after agent ingestion.
- Link bead plan metadata to ChangeSpecs with `related` only when `IssueWire.changespec_name` is non-empty and the
  ChangeSpec artifact exists in the same rebuild context; otherwise leave the name in payload for later reconciliation.
- Write a short follow-up note in the plan or test comments identifying any launch-time metadata that would make worker
  links more reliable. Do not modify launch workflows in this phase unless the missing metadata blocks the ingestion
  contract.

Tests:

- Bead parent hierarchy produces child -> parent links.
- Top-level beads are visible under the `sdd/beads` directory.
- Phase bead with `assignee` equal to its bead ID records a worker target and creates the link if an agent node with
  that ID is present.
- Bead dependencies remain in payload and do not require a new link type.
- Missing or corrupt bead store produces a scoped error without aborting other ingestion sources.

Exit criteria:

- `cargo test -p sase_core bead artifact`
- No Python bead parser changes

### Phase 4: Agent Artifacts And Created File Links

Dependencies: Phase 1. Can run in parallel with Phases 2 and 3 after shared helpers land.

Owner scope:

- Rust ingestion code using `sase_core::agent_scan`
- Rust fixtures/tests for agent records and created file nodes
- PyO3 request plumbing only if agent source options need binding support

Implementation:

- Reuse `scan_agent_artifacts(projects_root, options)` and `scan_agent_artifact_dir` for targeted updates.
- Create one agent artifact per `AgentArtifactRecordWire`:
  - kind `agent`
  - ID from `agent_meta.name`, `done.name`, or deterministic fallback `agent:<project>:<workflow>:<timestamp>`
  - payload including project, workflow, timestamp, artifacts dir, status markers, model/provider/VCS, workspace, retry
    fields, role suffix, wait fields, and source marker paths
  - searchable text including agent ID/name, project, workflow, ChangeSpec, provider, model, and marker status
- Create directory artifacts for artifact roots and each artifact timestamp directory.
- Create file artifacts and `created` links for all stable paths found in marker data and well-known artifact files:
  - chat transcripts and response files
  - `live_reply.md` and `live_reply_timestamps.jsonl`
  - `raw_xprompt.md`
  - selected `*_prompt.md` files
  - diff files
  - plan files from `plan_path.json` and done markers
  - question/plan approval request and response files
  - generated Markdown/PDF/image outputs listed in marker data
  - output logs
  - prompt-step response/diff artifacts
- Each created file artifact should also have directory parent links from Phase 1 helpers.
- Create `related` links:
  - agent -> ChangeSpec when `cl_name` or project metadata names a known ChangeSpec
  - retry parent <-> child using `retry_of_timestamp`, `retried_as_timestamp`, and `retry_chain_root_timestamp`
  - planner/coder/follow-up chains using `parent_timestamp`, role suffixes, plan/question/feedback marker arrays, and
    timestamp references when they resolve to agent artifacts
- Keep unresolved related targets in payload diagnostics rather than creating dangling links.

Tests:

- Running, waiting, and done agent fixtures create agent nodes with stable IDs.
- Created file paths from done markers, plan markers, prompt steps, and well-known files create file nodes and `created`
  links.
- Legacy unnamed agent uses the fallback ID deterministically.
- Agent with `cl_name` links to an existing ChangeSpec and leaves metadata-only detail when no ChangeSpec node exists.
- Retry chain fixtures produce deterministic `related` links without duplicates.

Exit criteria:

- `cargo test -p sase_core agent_scan artifact`
- Existing agent scan parity tests still pass

### Phase 5: Agent Thoughts

Dependencies: Phase 4.

Owner scope:

- Rust thought extraction module under `../sase-core/crates/sase_core/src/artifact/` or a dedicated reusable module
- Optional thin Python discovery hook only if provider session paths cannot be resolved in Rust
- Tests with small provider-specific fixtures

Implementation:

- Define a Rust internal `ThoughtRecord` shape with:
  - text
  - source provider
  - source file/session
  - ordinal
  - timestamp when known
  - following action when available
  - generated display title
- Implement stable extraction for sources already local to an agent artifact:
  - Codex `codex_thinking.jsonl`
  - Claude JSONL transcripts when their paths are discoverable from existing metadata or a caller-supplied discovery
    result
  - Gemini proxy logs only if source path discovery can be made deterministic and testable; otherwise leave Gemini
    discovery as a documented Python-provided input for a later integration slice
- Create thought artifacts:
  - kind `thought`
  - ID `thought:<sha256-prefix>` from text plus source identity to avoid cross-agent collisions
  - payload with the full thought record
  - `created` link agent -> thought
- Store source file paths as file artifacts when available and relate them through the agent-created file machinery.
- Keep ordering deterministic: chronological ordinals in payload, stable list ordering from graph queries.
- Do not remove the existing TUI thinking panel in this phase; Epic 4 will switch presentation after parity.

Tests:

- Codex fixture produces thought nodes and agent -> thought `created` links.
- Claude fixture parser matches the current Python parser for representative thinking/tool-action cases.
- Duplicate thought text from different sessions does not collide incorrectly.
- Malformed provider log lines are skipped and counted/diagnosed without aborting rebuild.

Exit criteria:

- `cargo test -p sase_core artifact`
- If Python discovery is added, targeted Python tests cover the request shape and no runtime-specific graph semantics
  leak into Python

### Phase 6: Incremental Updates, Stale Cleanup, And Binding Surfacing

Dependencies: Phases 2, 3, 4, and 5.

Owner scope:

- Rust rebuild dispatcher and source watermark/stale cleanup logic
- PyO3 `artifact_rebuild` and `artifact_upsert_path`
- Python facade request/response helpers
- Existing file watcher integration points only where non-invasive and testable

Implementation:

- Implement full rebuild:
  - open one store transaction or a bounded series of source transactions
  - ingest selected sources
  - update `source_watermarks`
  - remove or tombstone stale derived rows/links according to the request mode
  - return aggregated mutation counts, affected IDs, and scoped errors
- Implement targeted upserts for:
  - project file changes
  - bead `issues.jsonl` changes
  - agent artifact directory marker changes
  - direct file/directory path changes
- Define stale cleanup rules:
  - cleanup applies only to derived rows for selected source scopes
  - manual rows and manual links are never deleted by rebuild
  - manual tombstones continue to suppress matching derived rows
  - deleted source files remove or mark stale only rows whose `source_kind/source_id` belongs to that source
- Expose Python facade helpers around typed rebuild/upsert requests; keep argparse/CLI out of this phase.
- Integrate with existing watcher refresh paths only to the extent needed to call the new targeted upsert helper from a
  background-safe place. If that would require TUI presentation changes, leave a tested facade and defer the UI call
  site to Epic 4.
- Make `artifact_doctor` report stale/unresolved rows introduced by ingestion, including unresolved worker and related
  targets where those are stored as diagnostics.

Tests:

- Full rebuild over a fixture tree creates project, ChangeSpec, commit, bead, agent, file, and thought nodes.
- Targeted project-file upsert updates only rows derived from that file.
- Targeted bead upsert updates bead payloads and worker-link inputs without touching agent-created files.
- Targeted agent artifact dir upsert updates one agent and its created files without rescanning all projects.
- Removing a source file cleans only that source's derived rows.
- Manual tombstones survive full and targeted rebuilds.

Exit criteria:

- `cargo test -p sase_core artifact`
- `cargo test -p sase_core_py artifact`
- Targeted Python facade tests pass

### Phase 7: Cross-Source Reconciliation, Quality Gate, And Handoff

Dependencies: Phase 6.

Owner scope:

- Rust reconciliation pass inside artifact ingestion
- End-to-end fixture tests
- Minimal documentation or SDD handoff notes

Implementation:

- Add a final reconciliation pass after selected source ingestion to materialize links that depend on multiple sources:
  - bead `worker` links to agent nodes that appeared later in the rebuild
  - bead `related` links to ChangeSpecs
  - agent `related` links to ChangeSpecs
  - retry/follow-up links where one side was ingested by a different targeted source
- Ensure reconciliation never creates dangling links. If a target is unresolved, keep a payload diagnostic or doctor
  issue instead.
- Verify query usefulness for Epic 3 and Epic 4:
  - `artifact_show` on a ChangeSpec reveals commits, related agents, and related beads through inbound/outbound links
  - `artifact_show` on an agent reveals created files and thoughts
  - `artifact_show` on a bead reveals parent/children and worker agent when available
  - path-to-root works for created files under artifact directories
- Add a concise handoff note under `sdd/tales/202605/` or `sdd/epics/202605/` describing:
  - implemented source kinds
  - unresolved metadata gaps
  - performance characteristics from fixture rebuilds
  - any work intentionally deferred to Epic 3, 4, or 5

Tests:

- End-to-end fixture graph passes `artifact_doctor`.
- Show/detail queries for ChangeSpec, bead, agent, file, and thought artifacts include expected links and payloads.
- Rebuild is deterministic across two fresh indexes from the same fixture tree.
- Bounded graph export around a ChangeSpec includes expected commits/agents/beads without broad scans.

Exit criteria:

- In `../sase-core`: `cargo test`
- In this repo after any Python changes: `just install` then `just check`
- Handoff note checked in with any known gaps documented

## Recommended Work Waves

Wave 1:

- Phase 1 only. It creates the shared ingestion framework and typed request surface.

Wave 2:

- Phase 2, Phase 3, and Phase 4 can proceed in parallel after Phase 1 if they keep ownership to their source scanners.

Wave 3:

- Phase 5 after Phase 4, because thoughts hang off agent artifacts.

Wave 4:

- Phase 6 after source scanners land, because incremental cleanup needs all source contracts.

Wave 5:

- Phase 7 as the integration/land phase.

## Risk Notes

- Agent identity is the highest-risk contract. Use real names when present and document the fallback ID because Epic 5
  may migrate legacy unnamed agents later.
- Cross-source links should be reconciled after source-specific ingestion. Trying to make each scanner own all links
  will create ordering bugs and duplicated logic.
- Thought extraction is intentionally narrower than full UI replacement. Epic 2 should create graph data; Epic 4 owns
  presentation parity with the old thinking panel.
- Directory artifacts can explode if every filesystem ancestor is inserted eagerly. Insert only useful discovered
  directories and parent chains needed for graph reachability.
- Keep broad scans out of single-node detail queries. Rebuild can scan; `artifact_show` and TUI-facing calls should
  query the index only.

## Final Acceptance Criteria

- `artifact_rebuild` no longer returns the Epic 1 no-op placeholder.
- A full rebuild over fixture SASE state derives project, ChangeSpec, commit, directory, bead, agent, created file, and
  thought artifacts.
- Derived links use the legend's direction and types.
- Manual tombstones suppress derived rows across full and targeted rebuilds.
- `artifact_doctor` is clean on the happy-path fixture and useful on unresolved/stale fixtures.
- Rust tests cover each source scanner and the end-to-end rebuilt graph.
- Python facade and PyO3 tests cover the typed rebuild/upsert path.
