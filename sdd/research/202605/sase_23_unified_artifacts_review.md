# SASE-23 Unified Artifacts Review

Date: 2026-05-05

## Question

What user-facing behavior shipped with the closed legend bead `sase-23`, and how should people use it?

## Bead Status

`sase-23` is closed as the legend-tier **Unified Artifact Graph Plan**. It produced six closed epic beads:

- `sase-23.1` - Rust artifact core and persistence.
- `sase-23.2` - Source ingestion and link construction.
- `sase-23.3` - `sase artifact` CLI and `/sase_artifact` skill.
- `sase-23.4` - Artifacts TUI panel.
- `sase-23.5` - Migration, compatibility, and cleanup.
- `sase-23.6` - End-to-end quality gate.

## Summary

`sase-23` turns artifact discovery into a unified graph instead of several separate views over ChangeSpecs, beads,
agents, files, thoughts, and workflow outputs. The graph is backed by the Rust core and exposed through a Python CLI,
the ACE TUI, and a generated agent skill.

The most important user-facing change is that SASE now has one artifact model:

- Artifact nodes include root, file, directory, project, ChangeSpec, commit, bead, agent, and thought artifacts.
- Typed links describe relationships: `parent`, `created`, `worker`, and `related`.
- The default index is `~/.sase/artifacts.sqlite`.
- Rebuilds refresh graph rows from existing source state; they do not delete source files, beads, transcripts, diffs,
  plans, responses, marker files, images, PDFs, or ChangeSpec data.
- The ACE `A` key now opens the unified artifacts panel instead of the old agent run-log shortcut.
- Agents can use `/sase_artifact` as a read-first skill for stable JSON artifact inspection.

## Important User-Facing Changes

### 1. Unified Graph Index

The Rust core now owns graph storage, mutation semantics, queries, bounded graph materialization, export formats,
ingestion, and diagnostics. Python calls this through a strict facade rather than reimplementing graph behavior locally.

Artifact identity is stable and predictable:

- `/` is the graph root.
- Files and directories use absolute normalized paths.
- Project artifacts use absolute `~/.sase/projects/*/*.gp` paths.
- ChangeSpecs use their `NAME`.
- Commits use `<changespec_name>:<commit_number>`.
- Beads use bead IDs such as `sase-23.5.6`.
- Named agents use their stable agent name.
- Legacy unnamed agents use `agent:<project>:<workflow>:<timestamp>`.
- Thoughts use content-addressed `thought:<sha256-prefix>` IDs.

### 2. `sase artifact` CLI

The new top-level CLI surface is:

```bash
sase artifact {add,doctor,graph,list,rebuild,remove,show}
```

Read-only discovery is centered on `list`, `show`, `graph`, and `doctor`. Mutating operations are explicit:
`add`, `remove`, and `rebuild`.

Useful examples:

```bash
sase artifact list -j -l 50
sase artifact list -j -k file -l 50
sase artifact list -j -q "needle" -l 50
sase artifact show -j -a <artifact_id>
sase artifact graph -j -a <artifact_id> -d 2
sase artifact graph -f mermaid -a <artifact_id> -d 2
sase artifact doctor -j
```

All subcommands accept `-i/--index`, so testing and troubleshooting can point at a temporary SQLite index instead of the
default `~/.sase/artifacts.sqlite`.

### 3. Manual Rows And Tombstones

Manual graph edits are available for users and operators who need to add or suppress graph facts:

```bash
sase artifact add -j -a <id> -k <kind> -t "Title"
sase artifact add -j -l 'parent|<child_id>|<parent_id>'
sase artifact remove -j -a <artifact_id> -r "reason"
sase artifact remove -j -T <type> -S <source_id> -D <target_id> -r "reason"
```

Derived rows are refreshed from source data. Removing a derived row creates graph tombstone semantics rather than
deleting the source artifact. This distinction is important: the artifact graph is an index and overlay, not the owner of
the underlying work products.

### 4. Backfill, Incremental Refresh, And Doctor

`sase artifact rebuild` backfills existing state into the graph. With no source filters it can index the standard project
state, workspace context, current workspace bead store when supplied, and supported agent artifact directories.

Targeted rebuilds are available when a single context is stale:

```bash
sase artifact rebuild -j -t <project_or_file_path>
sase artifact rebuild -j -b <workspace>/sdd/beads -S bead_store
sase artifact rebuild -j -a <artifact_dir> -S agent_artifact -S agent_created_file -S agent_thought
```

`sase artifact doctor -j` reports graph health. Migration-specific diagnostics include fallback agent IDs, unresolved
timestamp links, unresolved ChangeSpec references, unresolved bead references, and stale derived rows.

### 5. ACE TUI Artifacts Panel

The ACE TUI now opens the artifact panel with `A`:

- AXE tab starts at `/`.
- CLs tab starts at the selected ChangeSpec artifact.
- Agents tab starts at the selected agent artifact, using the deterministic fallback ID for legacy unnamed agents.

The modal supports graph navigation instead of only a run log:

- `j` / `k` move through rows.
- `enter` opens the selected artifact.
- `b` / `f` move backward and forward through panel history.
- `p` goes to the parent artifact.
- `r` goes to root.
- `/` filters rows in the current artifact view.
- `y` copies the current artifact ID.
- `e` opens file artifacts in `$EDITOR` or `nvim`.
- `g` previews a bounded graph.
- `G` renders a Mermaid graph export in the detail pane.

The panel renders details for files, directories, projects, ChangeSpecs, commits, beads, agents, and thoughts. It also
attempts a targeted graph refresh if the starting artifact is missing, so current ChangeSpecs and agents can recover
without forcing a broad rebuild.

### 6. Workflow Metadata Links

Agent marker files now receive provider-neutral artifact metadata, including stable artifact agent IDs, source artifact
directories, ChangeSpec names, bead IDs, parent agent links, plan/question/feedback paths, and commit workflow fields.

User-facing effect: future graph rebuilds can connect agents to their created files, beads, plans, questions, commits,
ChangeSpecs, retry/follow-up chains, and thoughts without depending on provider-specific prompt text.

### 7. `/sase_artifact` Skill

The generated skill teaches agents to use the artifact CLI safely:

- Prefer JSON for discovery.
- Inspect exact artifacts with `show` before summarizing relationships.
- Treat `graph` output as bounded and partial when `truncated` is true.
- Use `doctor` for consistency checks.
- Avoid mutating commands unless the user explicitly asks.

This makes artifact graph inspection available inside agent workflows without needing each agent to relearn the CLI
contract.

## High-Level Usage Guide

### First-Time Migration Or Broad Refresh

```bash
sase artifact rebuild -j
sase artifact doctor -j
```

If `doctor` reports issues, inspect the affected IDs and rerun rebuild with a more specific source root when needed.
Use `rebuild -c mark` only when intentionally marking stale derived rows after source removal.

### Everyday Terminal Discovery

Start with a bounded list:

```bash
sase artifact list -j -l 50
```

Filter by kind, search text, provenance, source, link type, or root:

```bash
sase artifact list -j -k bead -l 50
sase artifact list -j -q "sase-23" -l 50
sase artifact list -j -P manual -l 50
sase artifact list -j -L parent -r <root_id> -l 50
```

Then inspect a concrete artifact:

```bash
sase artifact show -j -a <artifact_id>
```

### Relationship Exploration

Use a bounded graph when the relationship shape matters:

```bash
sase artifact graph -j -a <artifact_id> -d 2
sase artifact graph -f text -a <artifact_id> -d 2
sase artifact graph -f dot -a <artifact_id> -d 2
sase artifact graph -f mermaid -a <artifact_id> -d 2
```

Keep depth and limit bounded unless intentionally inspecting a small graph. If JSON says `truncated: true`, treat the
output as an excerpt.

### TUI Navigation

Open ACE and press `A` from the current tab. Use it as the default historical discovery surface:

- From AXE, browse from root.
- From CLs, inspect the selected ChangeSpec and linked agents, commits, beads, plans, questions, diffs, and files.
- From Agents, inspect the selected agent, created files, thoughts, related ChangeSpecs, retry/follow-up links, and bead
  relationships.

For active live monitoring, older live-detail surfaces may still exist where useful. For historical discovery, use the
artifact panel or `sase artifact`.

### Manual Overlay Use

Use manual graph edits only when you need an explicit human assertion or override:

```bash
sase artifact add -j -a note:release-check -k note -t "Release check"
sase artifact add -j -l 'related|note:release-check|<artifact_id>'
sase artifact remove -j -T related -S note:release-check -D <artifact_id> -r "no longer relevant"
```

Prefer `-j` and check the returned `errors`, affected node IDs, affected link IDs, and tombstone IDs.

## Review Notes

No blocking user-facing issues were found in this review pass. The implemented surfaces match the closed legend shape:
Rust core graph behavior, Python facade and CLI, TUI entrypoint, generated skill source, migration docs, and quality
coverage all landed.

Residual review risks:

- This was a high-level review of the completed legend, not a line-by-line audit of every Rust ingestion path and every
  TUI renderer.
- The graph depends on marker metadata quality. Legacy unnamed agents are handled with fallback IDs, but user-facing
  relationship quality improves only as newer agents write the richer metadata fields.
- The default index is mutable state under `~/.sase`; troubleshooting and tests should continue using `-i` with a
  temporary index unless intentionally exercising the live graph.

## Reviewed Sources

- Beads:
  - `sase bead show sase-23`
  - `sase bead show sase-23.1` through `sase bead show sase-23.6`
- Legend and epic plans:
  - `sdd/legends/202605/unified_artifacts.md`
  - `sdd/epics/202605/unified_artifacts_epic1.md`
  - `sdd/epics/202605/unified_artifacts_epic2.md`
  - `sdd/epics/202605/unified_artifacts_epic3.md`
  - `sdd/epics/202605/artifacts_tui_panel.md`
  - `sdd/epics/202605/unified_artifacts_epic5_migration.md`
  - `sdd/epics/202605/unified_artifacts_epic6_quality_gate.md`
- User docs and skill:
  - `docs/artifacts.md`
  - `docs/xprompt.md`
  - `src/sase/xprompts/skills/sase_artifact.md`
- Python implementation:
  - `src/sase/core/artifact_facade.py`
  - `src/sase/core/artifact_wire/`
  - `src/sase/main/parser_artifact.py`
  - `src/sase/main/artifact_handler.py`
  - `src/sase/ace/tui/actions/artifacts.py`
  - `src/sase/ace/tui/artifact_graph_refresh.py`
  - `src/sase/ace/tui/modals/artifact_panel_modal.py`
  - `src/sase/ace/tui/modals/artifact_panel_renderers/`
  - `src/sase/axe/artifact_metadata.py`
- Rust implementation in `../sase-core`:
  - `crates/sase_core/src/artifact/store.rs`
  - `crates/sase_core/src/artifact/query.rs`
  - `crates/sase_core/src/artifact/export.rs`
  - `crates/sase_core/src/artifact/ingest.rs`
  - `crates/sase_core/src/artifact/wire.rs`
  - `crates/sase_core_py/src/lib.rs`
- Quality evidence:
  - `tests/test_core_facade/test_artifact.py`
  - `tests/main/test_artifact_cli_*.py`
  - `tests/ace/tui/test_artifact_panel_launch.py`
  - `tests/ace/tui/modals/test_artifact_panel_modal.py`
  - `tests/ace/tui/modals/test_artifact_panel_renderers.py`
  - `tests/perf/bench_artifact_graph.py`
  - `sdd/tales/202605/perf_artifacts/artifact_graph_perf_smoke.json`
- Commit evidence:
  - `06d2b984` / `b5eb886e` - legend bead metadata and readiness.
  - `3d270f5` through `1ed9a0b` in `../sase-core` - Rust graph core, ingestion, exports, diagnostics, and bindings.
  - `649b0a78`, `ccfb0bac`, `22fa5b13`, `ffd742f4`, `ccc8f2cf`, `0d47cf05`, `654ade35`, `9f1cff09`,
    `199e06c4`, `1f58dd21`, `05ec6e1e`, `5a1f5228`, `8c462476`, `a63f8023`, `09ea23ba`, `aa9cbd85`,
    `2f3be66c`, `7539f662`, `0276d938`, `d95f8bfd`, and `ce5c1c27` in this repo - Python facade, CLI, TUI,
    metadata, docs, tests, and quality gates.
