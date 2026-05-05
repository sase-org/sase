# SASE-23 Unified Artifacts Review

Date: 2026-05-05 (revised)

## Question

What user-facing behavior shipped with the closed legend bead `sase-23`, and how should people use it?

## Bead Status

`sase-23` is closed as the legend-tier **Unified Artifact Graph Plan**. It produced six closed epic beads:

- `sase-23.1` — Rust artifact core and persistence.
- `sase-23.2` — Source ingestion and link construction.
- `sase-23.3` — `sase artifact` CLI and `/sase_artifact` skill.
- `sase-23.4` — Artifacts TUI panel.
- `sase-23.5` — Migration, compatibility, and cleanup.
- `sase-23.6` — End-to-end quality gate (the perf smoke under
  `sdd/tales/202605/perf_artifacts/artifact_graph_perf_smoke.json` is the closing artifact).

## Summary

`sase-23` turns artifact discovery into a unified, typed graph instead of several separate views over ChangeSpecs,
beads, agents, files, thoughts, and workflow outputs. The graph is backed by a SQLite store owned by the Rust core
(`sase_core::artifact`) and exposed through the Python facade (`src/sase/core/artifact_facade.py`), the
`sase artifact` CLI, the ACE TUI artifact panel, and a generated agent skill.

The most important user-facing changes are:

- One artifact model, with stable IDs across kinds (`root`, `file`, `directory`, `project`, `changespec`, `commit`,
  `bead`, `agent`, `thought`, plus `unknown` for safety).
- Four typed link kinds: `parent` (child→parent ownership), `created` (agent→produced artifact),
  `worker` (bead→responsible agent), and `related` (everything else, including retries, follow-ups, and cross-links).
- Two provenance values per row: `manual` (operator/agent created via `add`) and `derived` (rebuilt from sources).
- A default SQLite index at `~/.sase/artifacts.sqlite`; every CLI subcommand and TUI entry point honours
  `-i/--index` for temporary/test indexes.
- A new top-level `sase artifact` CLI with seven subcommands (`add`, `remove`, `list`, `show`, `graph`, `rebuild`,
  `doctor`).
- The ACE TUI `A` keymap now opens the unified artifact panel keyed off the active tab (AXE → root, CLs → selected
  ChangeSpec, Agents → selected agent or its deterministic fallback ID).
- Agents can use the `/sase_artifact` skill to inspect the graph through stable JSON commands.
- Agent marker files (`agent_meta.json`) now carry provider-neutral artifact metadata so future rebuilds can attach
  beads, plans, questions, commits, retries, and follow-ups without prompt-text heuristics.

Rebuilds refresh derived rows but never delete source files, beads, transcripts, diffs, plans, responses, marker files,
images, PDFs, or ChangeSpec data. Tombstones suppress graph rows or links only — they do not affect source state.

## Important User-Facing Changes

### 1. Stable Artifact Identity

Artifact IDs are stable graph keys; agent display names are not the canonical identity for unnamed agents.

- `/` is the root artifact (kind `root`, ID `ARTIFACT_ROOT_ID`).
- File and directory artifacts use absolute normalized paths (kinds `file` and `directory`).
- Project artifacts use absolute `~/.sase/projects/*/*.gp` paths, including archive project files
  (`<project>-archive.gp`).
- ChangeSpec artifacts use the ChangeSpec `NAME` exactly (active and archived collapse to the same ID).
- Commit artifacts use `<changespec_name>:<commit_number>` where the number matches the COMMITS drawer ordinal.
- Beads use bead IDs such as `sase-23.5.6`.
- Agent artifacts prefer the stable agent name when present.
- Legacy unnamed agents use the deterministic fallback ID `agent:<project>:<workflow>:<timestamp>`. The fallback is a
  graph ID, not a renamed display name; the node metadata records the source artifact directory so an operator can
  later repair marker metadata.
- Thought artifacts use content-addressed `thought:<sha256-prefix>` IDs so identical thoughts collapse to one node.

The constants live in `src/sase/core/artifact_wire/constants.py` (`ARTIFACT_KIND_*`, `ARTIFACT_LINK_*`,
`ARTIFACT_PROVENANCE_*`, `ARTIFACT_SOURCE_*`, `ARTIFACT_TOMBSTONE_*`, `ARTIFACT_STALE_CLEANUP_*`,
`ARTIFACT_WIRE_SCHEMA_VERSION = 1`).

### 2. Wire Schema (JSON Output)

All `-j/--json` outputs share `schema_version: 1` and a stable shape. The Python wire records are dataclasses in
`src/sase/core/artifact_wire/models.py`:

- `ArtifactNodeWire`: `id`, `kind`, `display_title`, `subtitle`, `provenance`, `source_kind`, `source_id`,
  `source_version`, `search_text`, `metadata`, `created_at`, `updated_at`.
- `ArtifactLinkWire`: `id`, `link_type`, `source_id`, `target_id`, `provenance`, source fields, `metadata`,
  `created_at`, `updated_at`.
- `ArtifactPayloadWire`: `artifact_id`, `payload_type`, `provenance`, source fields, `payload`, `updated_at`.
- `ArtifactDetailWire` (returned by `show`): `schema_version`, `node`, `payloads`, `outbound_links`, `inbound_links`,
  `children`, `path_to_root`, `diagnostics`. A missing artifact returns `node: null` with empty collections.
- `ArtifactGraphWire` (returned by `graph -j`): `schema_version`, `root_id`, `nodes`, `links`, `node_count`,
  `link_count`, `truncated`, `limit`. Treat `truncated: true` as "this is an excerpt".
- `ArtifactDoctorWire`: `schema_version`, `ok`, `issues` (each issue: `issue_type`, `severity`, `artifact_id`,
  `link_id`, `message`).
- `ArtifactMutationResultWire` (returned by `add`/`remove`/`rebuild`): `schema_version`, affected node IDs, affected
  link IDs, tombstone IDs, mutation counts (`nodes_added`/`updated`/`removed`, `links_added`/`updated`/`removed`,
  `tombstones_added`), and an `errors` list. Stop and surface the error rows when `errors` is non-empty.

### 3. `sase artifact` CLI Surface

Top-level: `sase artifact {add,doctor,graph,list,rebuild,remove,show}`. Every subcommand accepts `-i/--index`
(default `~/.sase/artifacts.sqlite`) and `-j/--json`. Short flags are mandatory per repo convention
(`memory/short/gotchas.md`).

Full flag table from `src/sase/main/parser_artifact.py`:

| Subcommand | Flag | Long             | Purpose                                                                 |
|------------|------|------------------|-------------------------------------------------------------------------|
| `add`      | `-a` | `--artifact-id`  | Manual artifact ID to upsert.                                           |
| `add`      | `-k` | `--kind`         | Artifact kind (use `ARTIFACT_KIND_*` values).                            |
| `add`      | `-t` | `--title`        | Display title.                                                          |
| `add`      | `-s` | `--subtitle`     | Display subtitle.                                                       |
| `add`      | `-q` | `--search-text`  | Pre-computed search text for the node.                                  |
| `add`      | `-m` | `--metadata-json`| Node metadata JSON object string.                                       |
| `add`      | `-p` | `--payload-json` | Payload JSON value string.                                              |
| `add`      | `-P` | `--payload-type` | Payload type label (e.g., `summary`).                                   |
| `add`      | `-l` | `--link`         | Compact link spec `TYPE\|SOURCE\|TARGET` or `ID\|TYPE\|SOURCE\|TARGET`; repeatable. |
| `add`      | `-L` | `--link-json`    | JSON link object; repeatable.                                           |
| `remove`   | `-a` | `--artifact-id`  | Artifact ID to remove or tombstone.                                     |
| `remove`   | `-l` | `--link-id`      | Link ID to remove.                                                      |
| `remove`   | `-T` | `--link-type`    | Link tuple — type.                                                      |
| `remove`   | `-S` | `--source-id`    | Link tuple — source.                                                    |
| `remove`   | `-D` | `--target-id`    | Link tuple — target.                                                    |
| `remove`   | `-p` | `--provenance`   | `manual` or `derived`; selects whether to delete or tombstone.          |
| `remove`   | `-r` | `--reason`       | Removal reason recorded in the tombstone.                               |
| `list`     | `-k` | `--kind`         | Repeatable kind filter.                                                 |
| `list`     | `-L` | `--link-type`    | Repeatable linked-edge type filter.                                     |
| `list`     | `-P` | `--provenance`   | Filter by provenance (`manual`/`derived`).                              |
| `list`     | `-s` | `--source-kind`  | Repeatable source-kind filter (`project_file`, `bead_store`, ...).      |
| `list`     | `-S` | `--source-id`    | Repeatable source-ID filter.                                            |
| `list`     | `-q` | `--text`         | Free-text search across indexed fields.                                 |
| `list`     | `-r` | `--root-id`      | Restrict to nodes reachable under the given root.                       |
| `list`     | `-u` | `--include-tombstoned` | Include tombstoned rows (debugging).                              |
| `list`     | `-l` | `--limit`        | Max nodes (default 200).                                                |
| `list`     | `-o` | `--offset`       | Result offset (default 0).                                              |
| `show`     | `-a` | `--artifact-id`  | Required. Artifact ID to inspect.                                       |
| `graph`    | `-a` | `--artifact-id`  | Root artifact ID.                                                       |
| `graph`    | `-d` | `--depth`        | Max traversal depth (default 2).                                        |
| `graph`    | `-L` | `--link-type`    | Repeatable edge-type filter.                                            |
| `graph`    | `-I` | `--include-inbound` | Walk inbound edges too.                                              |
| `graph`    | `-O` | `--include-outbound` | Walk outbound edges (default true).                                 |
| `graph`    | `-F` | `--full`         | Export the full bounded graph instead of a subgraph.                    |
| `graph`    | `-l` | `--limit`        | Max graph rows (default 500).                                           |
| `graph`    | `-f` | `--format`       | `json`, `text`, `dot`, `mermaid` (default `json`).                      |
| `graph`    | `-j` | `--json`         | Alias for `-f json`.                                                    |
| `rebuild`  | `-p` | `--projects-root`| Override projects root (default `~/.sase/projects`).                    |
| `rebuild`  | `-w` | `--workspace-root` | Workspace root for current ChangeSpec/agent context.                  |
| `rebuild`  | `-b` | `--beads-dir`    | Bead store directory (e.g., `<workspace>/sdd/beads`).                   |
| `rebuild`  | `-S` | `--include-source` | Repeatable allowlist of `ARTIFACT_SOURCE_*` source kinds.             |
| `rebuild`  | `-X` | `--exclude-source` | Repeatable denylist.                                                  |
| `rebuild`  | `-t` | `--target-path`  | Single target path to upsert (project file, directory, or any path).    |
| `rebuild`  | `-a` | `--artifact-dir` | One agent artifacts dir to refresh.                                     |
| `rebuild`  | `-c` | `--stale-cleanup`| `none` (default) or `mark` (mark stale derived rows when source is gone).|

Source-kind constants (the values for `-S/--include-source` and `-X/--exclude-source`): `project_file`, `changespec`,
`commit`, `directory`, `bead_store`, `agent_artifact`, `agent_created_file`, `agent_thought`.

### 4. Manual Rows And Tombstones

The graph supports human-asserted overlay data without giving up derived rebuild safety:

```bash
sase artifact add -j -a note:release-check -k unknown -t "Release check"
sase artifact add -j -a <id> -P summary -p '{"body": "text"}'
sase artifact add -j -l 'related|note:release-check|<artifact_id>'
sase artifact add -j -L '{"link_type":"parent","source_id":"<child>","target_id":"<parent>"}'
sase artifact remove -j -a <artifact_id> -p manual -r "reason"
sase artifact remove -j -T related -S note:release-check -D <artifact_id> -p manual -r "no longer relevant"
```

Manual rows are deleted directly when Rust can do so safely. Derived rows are *tombstoned* when the removal selects
`-p derived`, so the operator's suppression survives future rebuilds. Tombstones never delete underlying source files,
beads, marker files, responses, transcripts, or diffs. Use `list -u/--include-tombstoned` to inspect suppressed rows
when debugging.

### 5. Backfill, Targeted Refresh, And Doctor

`sase artifact rebuild` is the migration and repair entry point. With no source filters it indexes the standard
projects root, the supplied workspace context, the supplied bead store, and supported agent artifact directories. It
backfills graph rows for current and archived ChangeSpecs, commits, beads, dismissed agents whose markers remain on
disk, named agents, legacy unnamed agents, agent-created files, and thoughts.

Targeted rebuilds (preferred when one source is stale):

```bash
sase artifact rebuild -j -S project_file -S changespec -S commit -t <project.gp>
sase artifact rebuild -j -S directory -t <path>
sase artifact rebuild -j -S bead_store -b <workspace>/sdd/beads
sase artifact rebuild -j -S agent_artifact -S agent_created_file -a <artifact_dir>
sase artifact rebuild -j -c mark    # mark stale derived rows whose source was intentionally removed
```

Doctor:

```bash
sase artifact doctor -j
```

Issue-type catalogue (from the migration path; see `docs/artifacts.md`):

- `fallback_agent_id`: legacy unnamed agent indexed with a deterministic fallback ID. Expected during migration.
- `unresolved_timestamp_link`: retry/question/follow-up metadata names a timestamp that did not resolve to an indexed
  agent.
- `unresolved_changespec_reference`: marker or bead references a ChangeSpec missing from the rebuilt project set.
- `unresolved_bead_reference`: metadata references a bead missing from the rebuilt bead store.
- `stale_derived`: `rebuild -c mark` flagged a previously-derived row whose source disappeared.

Doctor exits non-zero when issues are present, so it is safe to use in scripts.

### 6. ACE TUI Artifacts Panel

`A` opens `ArtifactPanelModal` (`src/sase/ace/tui/modals/artifact_panel_modal.py`) keyed off the active tab via
`ArtifactsMixin._artifact_panel_start_id` (`src/sase/ace/tui/actions/artifacts.py:49`):

- AXE tab → `/`.
- CLs tab → selected ChangeSpec name; refresh context = the ChangeSpec's `.gp` file path.
- Agents tab → selected agent name, or the deterministic fallback ID
  `agent:<project>:<workflow>:<timestamp>` derived from the agent's artifacts directory; refresh context = that
  artifacts directory.

Modal keybindings (from `ArtifactPanelModal.BINDINGS` and the visible hint footer):

- `j` / `k` — move through rows (via `OptionListNavigationMixin.NAVIGATION_BINDINGS`).
- `enter` — open the selected linked artifact.
- `b` / `f` — back / forward through this panel's navigation history.
- `p` — go to the parent artifact (uses `parent_id_from_detail`, walks `parent` outbound or `path_to_root`).
- `r` — jump to root (`/`).
- `/` — focus the row filter (`FilterInput`); filter applies to the rows shown for the current artifact only.
- `y` — copy the current artifact ID to the system clipboard.
- `e` — open file artifacts in `$EDITOR` (default `nvim`); other kinds notify "not a file".
- `g` — preview a bounded graph (root = current artifact, limit 100) inside the right detail pane.
- `G` — render a Mermaid graph export (root = current artifact, limit 100) inside the detail pane.
- `Ctrl-D` / `Ctrl-U` — scroll the right detail pane down / up.
- `q` / `Esc` — close the modal (inherited from the modal screen).

Loads run in workers so the UI stays responsive. If the starting artifact is missing on open, the modal makes one
bounded targeted refresh attempt via `refresh_artifact_graph_for_missing_artifact`
(`src/sase/ace/tui/artifact_graph_refresh.py:58`), which picks the smallest source it can identify (agent artifacts
dir → ChangeSpec `.gp` → directory → project sources). The retry is per-artifact-ID and recorded in
`_missing_refresh_attempted` so it never loops.

The right pane is rendered by kind-aware renderers in
`src/sase/ace/tui/modals/artifact_panel_renderers/` (`_detail.py`, `_files.py`, `_kinds.py`, `_summaries.py`,
`_common.py`) and shows display metadata, payloads, links, and diagnostics for files, directories, projects,
ChangeSpecs, commits, beads, agents, and thoughts.

### 7. Agent Marker Metadata Contract

`src/sase/axe/artifact_metadata.py` is the provider-neutral contract. It writes the following additive fields into
each agent's `agent_meta.json`:

- Identity fields: `artifact_schema_version` (currently `1`, exposed as `ARTIFACT_AGENT_METADATA_SCHEMA_VERSION`),
  `artifact_source_dir` (absolute artifacts dir), `artifact_agent_id` (stable agent name when present, else the
  fallback ID).
- ChangeSpec linkage: `changespec_name` (canonical) plus `cl_name` for backward compatibility.
- Bead linkage: `bead_id`, with phase/epic/legend variants (`phase_bead_id`, `epic_bead_id`, `legend_bead_id`).
- Workflow linkage (the full set is `WORKFLOW_RELATIONSHIP_FIELDS`):
  `plan_path`, `sdd_prompt_path`, `sdd_plan_path`, `plan_submitted_at`, `questions_submitted_at`,
  `feedback_submitted_at`, `question_request_path`, `question_response_path`, `question_session_id`,
  `commit_changespec_name`, `commit_entry_id`, `commit_result`, `commit_diff_path`, `parent_agent_timestamp`,
  `parent_agent_name`, `source_plan_agent_name`, `followup_agent_name`.
- Submission timestamp fields are list-typed and de-duplicated via `_append_unique` so repeated plan/question/feedback
  events do not overwrite earlier history.

Multi-agent launches can set `SASE_AGENT_WORKFLOW_LINKS` to a JSON object whose `*` key applies to every spawned agent
and whose per-agent keys override common fields. `workflow_relationships_from_env(agent_name)` is the loader.

User-facing effect: graph rebuilds connect agents to their plans, questions, retries, follow-ups, beads, ChangeSpecs,
and commits without needing prompt-text scraping.

### 8. `/sase_artifact` Skill

Generated from `src/sase/xprompts/skills/sase_artifact.md`. It teaches agents to:

- Prefer JSON for discovery and summarization.
- Inspect exact artifacts with `show -j -a <id>` before describing relationships or payloads.
- Treat any `graph` JSON with `truncated: true` as partial.
- Use `doctor -j` for consistency checks; cite affected IDs from issue rows.
- Never run `add`, `remove`, or `rebuild` unless the user explicitly asks.

The skill body documents the exact JSON field names per response shape, mirroring the wire schema above so agents can
parse output without inspecting Python source.

### 9. Compatibility Behavior

Two notable preservation decisions:

- The legacy `~/.sase/agent_artifact_index.sqlite` file is not deleted as part of artifact graph migration. It remains
  available for fast agent startup and legacy agent-list loading paths.
- `AgentRunLogModal` (`src/sase/ace/tui/modals/agent_run_log_modal.py`) is still wired into the CLs tab via
  `actions/changespec/_core.py:86-88`; the unified panel is the new historical discovery surface, but the older modal
  remains where it serves active monitoring of a single ChangeSpec's run log.

Translating to operator guidance: use the artifact panel and `sase artifact` for cross-cutting / historical discovery,
and keep using the older live-monitoring surfaces where they are wired in.

## High-Level Usage Guide

### First-Time Migration Or Broad Refresh

```bash
cp ~/.sase/artifacts.sqlite ~/.sase/artifacts.sqlite.bak   # optional rollback point
sase artifact rebuild -j
sase artifact doctor -j
```

If `doctor` reports issues, inspect affected IDs and rerun rebuild scoped to a more specific source root. Use
`rebuild -c mark` only when intentionally marking stale derived rows after source removal.

### Everyday Terminal Discovery

```bash
sase artifact list -j -l 50
sase artifact list -j -k bead -l 50
sase artifact list -j -q "sase-23" -l 50
sase artifact list -j -P manual -l 50
sase artifact list -j -L parent -r <root_id> -l 50
sase artifact list -j -s bead_store -l 50
sase artifact show -j -a <artifact_id>
```

### Relationship Exploration

```bash
sase artifact graph -j -a <artifact_id> -d 2
sase artifact graph -j -a <artifact_id> -d 2 -I             # include inbound edges
sase artifact graph -j -F -l 500                            # bounded full-graph JSON
sase artifact graph -f text -a <artifact_id> -d 2
sase artifact graph -f dot -a <artifact_id> -d 2
sase artifact graph -f mermaid -a <artifact_id> -d 2
```

Keep `-d/--depth` and `-l/--limit` bounded unless the graph is known to be small. `truncated: true` means the result
is an excerpt.

### TUI Navigation

Open ACE; press `A` from the current tab. Use `j/k` to move through linked rows, `enter` to open, `b/f` for history,
`p`/`r` to jump to parent or root, `/` to filter the current row set, `y` to copy the artifact ID, `e` to edit a file
artifact, and `g`/`G` for graph preview / Mermaid export.

### Manual Overlay Use

```bash
sase artifact add -j -a note:release-check -k unknown -t "Release check"
sase artifact add -j -l 'related|note:release-check|<artifact_id>'
sase artifact remove -j -T related -S note:release-check -D <artifact_id> -p manual -r "no longer relevant"
```

Always check the returned `errors`, affected node IDs, affected link IDs, and tombstone IDs.

### Performance And Quality Gate

For artifact graph changes that cross the Rust/Python boundary:

```bash
(cd ../sase-core && cargo test)
just install && just check
```

`just artifact-perf-smoke` runs `tests/perf/bench_artifact_graph.py` against synthetic fixtures and writes
`sdd/tales/202605/perf_artifacts/artifact_graph_perf_smoke.json`. Reference numbers from the latest committed run
(11 beads, 10 agents, 2 projects, 10 created files, 10 thoughts, 120 modal-linked rows):

| Operation                      | Latency (ms) | Bounded |
|--------------------------------|--------------|---------|
| `full_graph_rebuild`           | 104.8        | no      |
| `targeted_project_file_upsert` | 3.1          | yes     |
| `targeted_bead_store_upsert`   | 3.7          | yes     |
| `targeted_agent_artifact_upsert` | 11.3       | yes     |
| `artifact_show:*` (any kind)   | <1.3         | yes     |
| `artifact_doctor`              | <1           | yes     |
| `modal_open:/`                 | 154.0        | yes     |
| `modal_open:changespec:current`| 123.1        | yes     |
| `modal_open:agent:current`     | 134.6        | yes     |

The smoke uses temp SQLite indexes and synthetic fixtures, so it must not read or mutate
`~/.sase/artifacts.sqlite`.

## Review Notes

No blocking user-facing issues were found. The implemented surfaces match the closed legend shape:

- Rust core graph behavior (`../sase-core/crates/sase_core/src/artifact/{store,query,export,ingest,wire}.rs`) is the
  owner of mutation semantics, queries, exports, ingestion, and diagnostics.
- The Python facade (`src/sase/core/artifact_facade.py`, `artifact_wire/`) is a strict pass-through; the CLI handler
  (`src/sase/main/artifact_handler.py`) and parser (`parser_artifact.py`) implement the JSON contract described above.
- The TUI entry (`bindings.py:115` for `A`, `actions/artifacts.py`, `modals/artifact_panel_modal.py`,
  `modals/artifact_panel_renderers/`) honours the per-tab launch contract.
- Marker metadata (`src/sase/axe/artifact_metadata.py`) is provider-neutral and does not depend on prompt text.
- Docs (`docs/artifacts.md`), the skill (`xprompts/skills/sase_artifact.md`), and quality coverage
  (`tests/test_core_facade/test_artifact.py`, `tests/main/test_artifact_cli_*.py`, `tests/ace/tui/...`,
  `tests/perf/bench_artifact_graph.py`, `sdd/tales/202605/perf_artifacts/artifact_graph_perf_smoke.json`) all landed.

Residual review risks and follow-ups:

- **Not a line-by-line audit.** This review covers shape and behavior across Rust core, Python facade, CLI, TUI, skill,
  metadata, and docs. It does not exhaustively audit every Rust ingestion branch or every TUI renderer.
- **Marker metadata quality dictates derived edge quality.** Legacy unnamed agents land with fallback IDs (the
  `fallback_agent_id` doctor issue). Relationship fidelity improves only as newer agents write the richer fields under
  `WORKFLOW_RELATIONSHIP_FIELDS`. There is no automated repair pass for older marker files yet.
- **Default index is mutable global state.** Always pass `-i <tmp.sqlite>` for tests, agent reproductions, or
  troubleshooting that should not perturb the user's live graph. The repo convention is enforced by the perf smoke and
  the skill, but ad-hoc operator commands can still hit the default.
- **Compatibility surfaces are intentional, not a regression.** The legacy
  `~/.sase/agent_artifact_index.sqlite` and `AgentRunLogModal` remain wired in for active monitoring; the unified
  panel is not a hard replacement. If a future change retires either, double-check call sites in
  `actions/changespec/_core.py` and the agent-list loaders.
- **Scope of `worker` edges.** The current contract names `worker` as bead→agent. Bead↔dependency edges are modelled
  via `related`, not a dedicated `dependency` link type, so consumers walking the graph for blocker chains should
  filter by `related` plus metadata rather than expecting a typed `dependency` edge.

## Reviewed Sources

- Beads:
  - `sase bead show sase-23`, `sase bead show sase-23.1` … `sase bead show sase-23.6`.
- Legend and epic plans:
  - `sdd/legends/202605/unified_artifacts.md`
  - `sdd/epics/202605/unified_artifacts_epic1.md` … `unified_artifacts_epic6_quality_gate.md`
  - `sdd/epics/202605/artifacts_tui_panel.md`
- Earlier research:
  - `sdd/research/202605/artifact_graph_unified.md` (identity model, edge model, Rust-core fit, open questions)
  - `sdd/research/202604/artifacts_panel.md` (TUI surface and obsolescence rationale)
- User docs and skill:
  - `docs/artifacts.md`
  - `docs/xprompt.md`
  - `src/sase/xprompts/skills/sase_artifact.md`
- Python implementation:
  - `src/sase/core/artifact_facade.py`
  - `src/sase/core/artifact_wire/{__init__.py,constants.py,models.py,conversion.py}`
  - `src/sase/main/parser_artifact.py`
  - `src/sase/main/artifact_handler.py`
  - `src/sase/ace/tui/bindings.py:115` (`A` keymap)
  - `src/sase/ace/tui/actions/artifacts.py`
  - `src/sase/ace/tui/artifact_graph_refresh.py`
  - `src/sase/ace/tui/modals/artifact_panel_modal.py`
  - `src/sase/ace/tui/modals/artifact_panel_state.py`
  - `src/sase/ace/tui/modals/artifact_panel_renderers/`
  - `src/sase/axe/artifact_metadata.py`
- Rust implementation in `../sase-core`:
  - `crates/sase_core/src/artifact/{store,query,export,ingest,wire}.rs`
  - `crates/sase_core_py/src/lib.rs`
- Quality evidence:
  - `tests/test_core_facade/test_artifact.py`
  - `tests/main/test_artifact_cli_*.py`
  - `tests/ace/tui/test_artifact_panel_launch.py`
  - `tests/ace/tui/modals/test_artifact_panel_modal.py`
  - `tests/ace/tui/modals/test_artifact_panel_renderers.py`
  - `tests/perf/bench_artifact_graph.py`
  - `sdd/tales/202605/perf_artifacts/artifact_graph_perf_smoke.json`
  - `Justfile:348` (`artifact-perf-smoke` target)
- Commit evidence:
  - `06d2b984`, `b5eb886e` — legend bead metadata and readiness.
  - `3d270f5` … `1ed9a0b` in `../sase-core` — Rust graph core, ingestion, exports, diagnostics, and bindings.
  - `649b0a78`, `ccfb0bac`, `22fa5b13`, `ffd742f4`, `ccc8f2cf`, `0d47cf05`, `654ade35`, `9f1cff09`,
    `199e06c4`, `1f58dd21`, `05ec6e1e`, `5a1f5228`, `8c462476`, `a63f8023`, `09ea23ba`, `aa9cbd85`,
    `2f3be66c`, `7539f662`, `0276d938`, `d95f8bfd`, and `ce5c1c27` in this repo — Python facade, CLI, TUI,
    metadata, docs, tests, and quality gates.
