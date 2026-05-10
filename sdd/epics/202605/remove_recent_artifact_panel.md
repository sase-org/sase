---
create_time: 2026-05-06 02:52:22
status: done
bead_id: sase-25
tier: epic
prompt: sdd/prompts/202605/remove_recent_artifact_panel.md
---
# Remove Recent Artifact Panel And Unified Artifact Graph

## Goal

Remove all traces of the recent artifact panel work without reverting unrelated changes from the same time window.

Treat the following bead families as in scope:

- `sase-23` - `Unified Artifact Graph Plan`, legend file `sdd/legends/202605/unified_artifacts.md`
- `sase-24` - `Artifacts Panel Redesign`, legend file `sdd/legends/202605/artifacts_panel_redesign.md`

This includes the backend graph substrate in `../sase-core`, Python facade/CLI/docs/skills in this repo, Textual panel
and row indicators in this repo, generated skill deployment in `~/.local/share/chezmoi`, SDD prompt/plan/tale/perf
artifacts, and bead metadata for those two legends and their children.

Do not remove older or unrelated "agent artifact" functionality that predates these legends, including the agent
artifact index/startup cache work, file panel behavior, dismissed-agent artifact marker cleanup, and generic artifact
directory terminology used outside the unified graph.

## Discovery Summary

Reviewed project memory, `sase_beads` workflow notes, the two legend plans, and bead records.

The bead store shows:

- `sase-23`: closed legend, 6 epic children, designs under `sdd/epics/202605/unified_artifacts_*.md`,
  `artifacts_tui_panel.md`, and related prompts/tales.
- `sase-24`: closed legend, 6 epic children, designs under `sdd/epics/202605/artifacts_panel_*.md` and
  `artifact_epic*_*.md`.
- Phase notes contain many short commit IDs, but current repository history has follow-up and closure commits that are
  not always exactly the same IDs. Use commit notes as breadcrumbs, not as an automatic revert script.

Repository scan results:

- `sase_101`: contains most TUI, CLI, docs, SDD, tests, perf harness, and skill source changes.
- `../sase-core`: contains the Rust artifact module and PyO3 binding surface: `crates/sase_core/src/artifact/*` and
  artifact functions in `crates/sase_core_py/src/lib.rs`.
- `~/.local/share/chezmoi`: contains generated deployed skill files from commit `9971e259`:
  `home/dot_claude/skills/sase_artifact/SKILL.md`, `home/dot_codex/skills/sase_artifact/SKILL.md`,
  `home/dot_gemini/skills/sase_artifact/SKILL.md`.
- `../sase-nvim`, `../sase-github`, and `../sase-telegram`: no matching artifact-panel references found in focused
  searches.
- `../retired Mercurial plugin`: recent unrelated commit `98b8b4b feat: add Mercurial diff line stats`; no matching artifact-panel
  references found.

Known unrelated work in the same date window that must be preserved:

- `54e8402b feat: add leader agent run log keymap`
- `46bfca63 chore: Add SDD prompt and plan for cross_panel_agent_jump`
- `93e6becd fix: keep agent jump focus with cross-panel target`
- `d3295df5 chore: Add SDD prompt and plan for agent_untagged_panel`
- `47035433 fix: hide empty untagged agents panel`
- `98b8b4b feat: add Mercurial diff line stats` in `../retired Mercurial plugin`

## Safety Rules For Every Phase

- Start with `git status --short` in every repo the phase will touch. Preserve all unrelated dirty files.
- Do not use broad date-range reverts. Reconstruct changes from the bead/plan scope plus path-level inspection.
- Prefer path-scoped removal and targeted reverse patches over reverting whole commits when a commit mixes unrelated
  work.
- After each phase, run a focused negative search for `ArtifactPanel`, `open_artifacts_panel`, `sase artifact`,
  `sase_artifact`, `artifact_show_paged`, `artifact_summary`, `artifact search`, `sase-23`, and `sase-24` in the touched
  repo, then explain any intentionally retained hits.
- Use `just install` before `just check` in this workspace if phase changes this repo.
- Run the local check command for every modified repo:
  - this repo: `just install` then `just check`
  - `../sase-core`: `cargo test` or its repo `just check` if present
  - chezmoi: `just check`, and after committing/applying later, `chezmoi apply --force`
  - plugin repos only if modified: `just check`

## Phase 1: Authoritative Removal Map

Owner: one agent. Write only the final inventory artifact if needed; no product code changes.

Build a repo-by-repo removal manifest before deletion:

- Expand all `sase-23*` and `sase-24*` bead records from `sdd/beads/issues.jsonl`, including design paths and commit
  notes.
- For every short commit in bead notes, check whether it exists in `sase_101`, `../sase-core`, or chezmoi. Record the
  repo and touched paths.
- Diff the current tree against the nearest pre-`sase-23` baseline by path, not by time. Candidate baseline in this repo
  is immediately before `27484c1d chore: Add SDD prompt and plan for unified_artifacts`; candidate baseline in
  `../sase-core` is immediately before `3d270f5 feat: add artifact graph wire schema`.
- Produce a manifest with three buckets:
  - remove: unified artifact graph, artifact panel, artifact indicators, `sase artifact` CLI/docs/skill, SDD artifacts,
    bead entries.
  - preserve: pre-existing agent artifact index/cache/cleanup behavior and unrelated date-window changes.
  - inspect manually: files touched both by artifact work and unrelated changes.

Exit criteria:

- A clear path list for each repo.
- A list of mixed files requiring manual patching instead of deletion.
- No product code changes yet.

## Phase 2: Remove Rust Unified Artifact Graph From `../sase-core`

Owner: one agent. Write scope: `../sase-core`.

Remove the graph substrate introduced by `sase-23` and extended by `sase-24`:

- Delete `crates/sase_core/src/artifact/{wire,store,query,ingest,export,mod}.rs`.
- Remove artifact module exports from `crates/sase_core/src/lib.rs` and any internal module declarations.
- Remove PyO3 functions from `crates/sase_core_py/src/lib.rs`: `artifact_add`, `artifact_remove`, `artifact_list`,
  `artifact_search`, `artifact_show`, `artifact_show_paged`, `artifact_summary`, `artifact_graph`, `artifact_export_*`,
  `artifact_rebuild`, `artifact_upsert_path`, and `artifact_doctor`.
- Remove `petgraph` or other dependencies that were only needed for the unified graph.
- Remove Rust tests that only exercise unified artifact graph behavior.
- Preserve older agent artifact scanning/index APIs such as `scan_agent_artifacts`, `rebuild_agent_artifact_index`,
  `query_agent_artifact_index`, and agent cleanup marker behavior unless Phase 1 proves they were introduced solely for
  `sase-23`.

Validation:

- `cargo test` or repo-local check command.
- Negative search for unified graph symbols while allowing older `AgentArtifact*` symbols.

## Phase 3: Remove Python Artifact CLI, Facade, Docs, Skill Source, And Perf Harness From This Repo

Owner: one agent. Write scope: non-TUI Python/SDD/docs/test files in `sase_101`.

Remove the Python surfaces that wrap the Rust graph:

- Delete `src/sase/core/artifact_wire/` and `src/sase/core/artifact_facade.py`.
- Remove `sase artifact` parser/handler wiring: `src/sase/main/parser_artifact.py`, `src/sase/main/artifact_handler.py`,
  and `src/sase/main/artifact_cli/`.
- Remove `src/sase/xprompts/skills/sase_artifact.md` and update skill discovery/generation tests accordingly.
- Remove docs dedicated to this feature, especially `docs/artifacts.md` and the `sase_artifact` entry in
  `docs/xprompt.md`.
- Remove unified graph CLI/facade tests under `tests/main/test_artifact_cli_*` and
  `tests/test_core_facade/test_artifact*`.
- Remove perf harness files dedicated to the unified graph under `tests/perf/artifact_graph/` and
  `tests/perf/bench_artifact_graph.py`.
- Remove parser imports/dispatch entries from the main CLI without disturbing unrelated commands.

Preserve:

- `src/sase/artifacts.py`, `src/sase/agent/agent_artifacts_cache.py`, and older agent artifact tests unless Phase 1
  proves a specific hunk belongs only to the unified graph.
- Existing `sase file-history`, file panel, agent run log, prompt panel, and cleanup behavior.

Validation:

- Focused CLI parser tests that remain after deletion.
- `rg -n "sase artifact|sase_artifact|artifact_facade|artifact_wire" src tests docs`.

## Phase 4: Remove Textual Artifact Panel, Indicators, And Restore Legacy `A` Behavior

Owner: one agent. Write scope: TUI files in `sase_101`.

Remove the user-facing panel and row indicators:

- Delete `src/sase/ace/tui/modals/artifact_panel_*` modules and `src/sase/ace/tui/modals/artifact_panel_renderers/`.
- Remove `ArtifactPanelModal` exports from `src/sase/ace/tui/modals/__init__.py`.
- Remove `src/sase/ace/tui/actions/artifacts.py`, `artifact_summaries.py`, and
  `src/sase/ace/tui/artifact_graph_refresh.py`.
- Remove artifact indicator models/caches: `src/sase/ace/tui/models/artifact_indicator.py` and
  `artifact_summary_cache.py`.
- Remove indicator integration hunks from CL and Agent list rendering/loading paths while preserving unrelated row
  formatting, grouping, cross-panel jump, and untagged panel fixes.
- Restore the `A` key to the previous agent run log behavior in `src/sase/default_config.yml`, fallback bindings, keymap
  types, command catalog, help modal, and tests.
- Remove artifact panel CSS blocks from `src/sase/ace/tui/styles.tcss`.
- Delete panel/indicator tests: `tests/ace/tui/test_artifact_panel_launch.py`,
  `tests/ace/tui/modals/test_artifact_panel_*`, `tests/ace/tui/actions/test_artifact_summary_loading.py`,
  `tests/ace/tui/models/test_artifact_indicator.py`, `tests/ace/tui/test_agent_artifact_indicators.py`, and any
  panel-specific startup contract tests.

Validation:

- Keybinding tests prove `A` opens the legacy run log or equivalent pre-artifact behavior.
- Hot navigation tests still pass for CL and Agent rows without artifact summary calls.
- Negative search for `ArtifactPanelModal` and `open_artifacts_panel`.

## Phase 5: Remove Runtime Metadata And Watcher Hooks That Feed The Unified Graph

Owner: one agent. Write scope: runtime/workflow glue in `sase_101`.

Remove metadata writes and watchers whose only consumer was the unified artifact graph:

- Remove `src/sase/axe/run_agent_exec_plan_artifacts.py` if it exists solely for graph metadata.
- Remove graph-specific metadata additions from agent launch, plan approval, question handling, epic work, retry spawn,
  commit workflow, and event refresh code.
- Remove graph refresh invalidation and targeted rebuild hooks from file watchers.
- Preserve provider-neutral runtime metadata that is used elsewhere, including bead IDs, workspace paths, changespec
  links, retry chain metadata, prompt/history metadata, and existing agent artifact index markers.
- Update tests that expected graph metadata while keeping tests for non-graph metadata behavior.

Validation:

- Focused tests for agent launch, plan approval, question, epic work, retry, and commit workflows.
- Negative search for `artifact_rebuild`, `artifact_upsert_path`, `artifact_graph_refresh`, and graph-specific metadata
  keys introduced by `sase-23.5`.

## Phase 6: Remove Deployed Skill Files From Chezmoi

Owner: one agent. Write scope: `~/.local/share/chezmoi`.

Remove generated deployed skill files added by `9971e259`:

- `home/dot_claude/skills/sase_artifact/SKILL.md`
- `home/dot_codex/skills/sase_artifact/SKILL.md`
- `home/dot_gemini/skills/sase_artifact/SKILL.md`

If those directories become empty, remove the empty `sase_artifact` directories as well.

Validation:

- `rg -n "sase_artifact|sase artifact|unified artifact graph" home/dot_claude home/dot_codex home/dot_gemini home/dot_config/sase`
- `just check` in chezmoi.
- After the final commit/apply step, run `chezmoi apply --force`.

## Phase 7: Remove SDD Plans, Prompts, Research, Tales, Perf Artifacts, And Bead Records

Owner: one agent. Write scope: planning artifacts and bead metadata in `sase_101`.

Remove the historical SDD surface for `sase-23` and `sase-24` only after implementation phases are complete:

- Delete legend files:
  - `sdd/legends/202605/unified_artifacts.md`
  - `sdd/legends/202605/artifacts_panel_redesign.md`
- Delete linked epic plans:
  - `sdd/epics/202605/unified_artifact_epic1.md`
  - `sdd/epics/202605/unified_artifacts_epic1.md`
  - `sdd/epics/202605/unified_artifacts_epic2.md`
  - `sdd/epics/202605/unified_artifacts_epic3.md`
  - `sdd/epics/202605/artifacts_tui_panel.md`
  - `sdd/epics/202605/unified_artifacts_epic5_migration.md`
  - `sdd/epics/202605/unified_artifacts_epic6_quality_gate.md`
  - `sdd/epics/202605/artifacts_panel_epic1.md`
  - `sdd/epics/202605/artifact_epic2_fast_indexing_query_contracts.md`
  - `sdd/epics/202605/artifact_epic3_relationship_navigator.md`
  - `sdd/epics/202605/artifacts_panel_epic4_indicators.md`
  - `sdd/epics/202605/artifacts_panel_epic5.md`
  - `sdd/epics/202605/artifacts_panel_epic6_rollout.md`
- Delete corresponding prompt files under `sdd/prompts/202605/`.
- Delete corresponding tales, rollout notes, handoffs, benchmark outputs, and research/infographic files whose titles
  are scoped to unified artifacts or artifact panel navigation.
- Remove all `sase-23*` and `sase-24*` records from `sdd/beads/issues.jsonl` and the corresponding rows from
  `sdd/beads/beads.db`. If the current bead CLI has no delete command, perform a careful direct store migration with a
  backup and validate with `sase bead show sase-23` / `sase bead show sase-24` returning not found.

Preserve:

- Older SDD entries for `agent_artifact_startup_perf`, `artifact_pyvision_cleanup`, generic file-panel artifact fixes,
  and any unrelated May 5-6 plans listed in the discovery summary.

Validation:

- `rg -n "sase-23|sase-24|unified_artifacts|artifacts_panel_redesign|artifacts_tui_panel|ArtifactPanel|open_artifacts_panel|sase_artifact|sase artifact" sdd src tests docs`
- `sase bead show sase-23` and `sase bead show sase-24` fail cleanly or report no issue.
- `just install` then `just check`.

## Phase 8: Cross-Repo Final Sweep And Integration Gate

Owner: one agent. Write scope: only small cleanup found by validation.

Run the final cross-repo verification:

- `git status --short` in all candidate repos: `sase_101`, `../sase-core`, `~/.local/share/chezmoi`, `../sase-nvim`,
  `../sase-github`, `../retired Mercurial plugin`, `../sase-telegram`.
- Cross-repo negative search for: `ArtifactPanel`, `open_artifacts_panel`, `sase_artifact`, `sase artifact`,
  `artifact_show_paged`, `artifact_summary`, `artifact_graph`, `artifacts_panel_redesign`, `unified_artifacts`,
  `sase-23`, `sase-24`.
- Explain any retained hits as either older generic agent-artifact behavior or unrelated text.
- Run final checks in every modified repo.
- In chezmoi, run `chezmoi apply --force` after the checked-in removal is ready.

Final acceptance:

- No user-facing `A` artifact panel remains; `A` uses the pre-artifact-panel behavior.
- No `sase artifact` CLI, docs, or generated skill remains.
- No unified artifact graph backend remains in `../sase-core`.
- No artifact panel row indicators remain in CLs or Agents tabs.
- No `sase-23` or `sase-24` SDD/bead records remain.
- Unrelated same-window changes remain intact.
- All modified repositories pass their local checks.
