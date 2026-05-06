---
create_time: 2026-05-06 03:25:00
bead_id: sase-25.1
parent_bead_id: sase-25
---
# Remove Recent Artifact Panel Removal Map

This is the Phase 1 authoritative removal manifest for `sase-25.1`. It is based on:

- `sase bead show sase-25` and `sase bead show sase-25.1`
- all `sase-23*` and `sase-24*` rows in `sdd/beads/issues.jsonl`
- path diffs from `27484c1d^..HEAD` in this repo
- path diffs from `3d270f5^..HEAD` in `../sase-core`
- path diffs from `9971e259^..HEAD` in `~/.local/share/chezmoi`
- focused negative searches in plugin repos: `../sase-nvim`, `../sase-github`, `../sase-google`,
  `../sase-telegram`

No product code is removed by this phase.

## Bead Expansion

The bead store currently has 84 in-scope rows: `sase-23`, all `sase-23.*` descendants, `sase-24`, and all
`sase-24.*` descendants.

Linked design files:

| Bead | Design |
| --- | --- |
| `sase-23` | `sdd/legends/202605/unified_artifacts.md` |
| `sase-23.1` | `sdd/epics/202605/unified_artifacts_epic1.md` |
| `sase-23.2` | `sdd/epics/202605/unified_artifacts_epic2.md` |
| `sase-23.3` | `sdd/epics/202605/unified_artifacts_epic3.md` |
| `sase-23.4` | `sdd/epics/202605/artifacts_tui_panel.md` |
| `sase-23.5` | `sdd/epics/202605/unified_artifacts_epic5_migration.md` |
| `sase-23.6` | `sdd/epics/202605/unified_artifacts_epic6_quality_gate.md` |
| `sase-24` | `sdd/legends/202605/artifacts_panel_redesign.md` |
| `sase-24.1` | `sdd/epics/202605/artifacts_panel_epic1.md` |
| `sase-24.2` | `sdd/epics/202605/artifact_epic2_fast_indexing_query_contracts.md` |
| `sase-24.3` | `sdd/epics/202605/artifact_epic3_relationship_navigator.md` |
| `sase-24.4` | `sdd/epics/202605/artifacts_panel_epic4_indicators.md` |
| `sase-24.5` | `sdd/epics/202605/artifacts_panel_epic5.md` |
| `sase-24.6` | `sdd/epics/202605/artifacts_panel_epic6_rollout.md` |

## Commit Note Provenance

Every short commit hash recorded in `sase-23*` and `sase-24*` bead notes was checked in this repo, `../sase-core`, and
`~/.local/share/chezmoi`.

Found note hashes:

| Note hash | Repo | Subject | Touched paths |
| --- | --- | --- | --- |
| `0d47cf05` | this repo | `feat: enable artifact graph export formats (sase-23.3.3)` | `src/sase/core/artifact_facade.py`, `src/sase/main/artifact_handler.py`, `tests/main/test_artifact_cli.py`, `tests/test_core_facade/test_artifact.py`, `public_api_methods.txt`, `sdd/beads/issues.jsonl` |
| `2339210` | `../sase-core` | `feat: add artifact mutation operations (sase-23.1.2)` | `crates/sase_core/src/artifact/mod.rs`, `crates/sase_core/src/artifact/store.rs`, `crates/sase_core/src/lib.rs` |
| `23630880` | this repo | `feat: render file artifacts by canonical type (sase-24.5.1)` | `src/sase/ace/tui/modals/artifact_panel_renderers/_common.py`, `src/sase/ace/tui/modals/artifact_panel_renderers/_files.py`, `tests/ace/tui/modals/test_artifact_panel_renderers.py`, `sdd/beads/issues.jsonl` |
| `2a14a411` | this repo | `chore: record bead worker artifact metadata note (sase-23.2.3)` | `sdd/beads/issues.jsonl`, `sdd/epics/202605/unified_artifacts_epic2.md` |
| `2bd0342c` | this repo | `fix: avoid duplicate artifact graph summaries (sase-24.5.5)` | `src/sase/ace/tui/modals/artifact_panel_renderers/_detail.py`, `src/sase/ace/tui/modals/artifact_panel_renderers/_summaries.py`, `tests/ace/tui/modals/test_artifact_panel_renderers.py`, `sdd/beads/issues.jsonl` |
| `2c0adfe3` | this repo | `feat: improve missing artifact recovery UX (sase-24.5.3)` | `src/sase/ace/tui/modals/artifact_panel_modal_rendering.py`, `tests/ace/tui/modals/test_artifact_panel_modal.py`, `sdd/beads/issues.jsonl` |
| `33472192` | this repo | `chore: close artifact file type taxonomy bead (sase-24.1.1)` | `sdd/beads/issues.jsonl` |
| `4781e236` | this repo | `chore: close agent artifact ingestion bead (sase-23.2.4)` | `sdd/beads/issues.jsonl` |
| `5d42f88d` | this repo | `chore: close artifact schema phase (sase-23.1.1)` | `sdd/beads/issues.jsonl` |
| `654ade35` | this repo | `feat: polish artifact CLI human output (sase-23.3.4)` | `src/sase/main/artifact_handler.py`, `tests/main/test_artifact_cli.py`, `sdd/beads/issues.jsonl` |
| `9f1cff09` | this repo | `feat: add sase artifact skill (sase-23.3.5)` | `src/sase/xprompts/skills/sase_artifact.md`, `tests/main/test_init_skills_handler.py`, `sdd/beads/issues.jsonl` |
| `a1255346` | this repo | `fix: harden artifact panel worker failures (sase-24.5.4)` | `src/sase/ace/tui/modals/artifact_panel_modal*.py`, `src/sase/ace/tui/modals/artifact_panel_state*.py`, `tests/ace/tui/modals/test_artifact_panel_*`, `sdd/beads/issues.jsonl` |
| `a38daee7` | this repo | `feat: add artifact detail relationship context strip (sase-24.5.2)` | `src/sase/ace/tui/modals/artifact_panel_modal_rendering.py`, `src/sase/ace/tui/modals/artifact_panel_renderers/_detail.py`, `src/sase/ace/tui/modals/artifact_panel_renderers/_summaries.py`, `src/sase/ace/tui/modals/artifact_panel_state*.py`, `tests/ace/tui/modals/test_artifact_panel_*`, `sdd/beads/issues.jsonl` |
| `cc56db63` | this repo | `test: harden artifact panel paged hot-path coverage (sase-24.6.4)` | `tests/ace/tui/modals/_artifact_panel_modal_helpers.py`, `tests/ace/tui/modals/test_artifact_panel_modal.py`, `tests/ace/tui/modals/test_artifact_panel_preview.py`, `sdd/beads/issues.jsonl` |
| `ccc8f2cf` | this repo | `feat: implement artifact mutation CLI commands (sase-23.3.2)` | `src/sase/main/artifact_handler.py`, `src/sase/main/parser_artifact.py`, `tests/main/test_artifact_cli.py`, `sdd/beads/issues.jsonl` |
| `ccfa6cbc` | this repo | `chore: close Rust graph primitive coverage bead (sase-23.6.1)` | `sdd/beads/issues.jsonl` |
| `e737c694` | this repo | `chore: document and verify artifact CLI (sase-23.3.6)` | `docs/artifacts.md`, `docs/xprompt.md`, `tests/main/test_artifact_cli.py`, `sdd/beads/issues.jsonl` |
| `f79b88cc` | this repo | `chore: close artifact ingestion classifier bead (sase-24.1.2)` | `sdd/beads/issues.jsonl` |
| `ff8e8d7` | `../sase-core` | `feat: ingest agent thoughts into artifact graph (sase-23.2.5)` | `Cargo.lock`, `Cargo.toml`, `crates/sase_core/Cargo.toml`, `crates/sase_core/src/artifact/ingest.rs` |
| `ffd742f4` | this repo | `feat: add artifact CLI JSON skeleton (sase-23.3.1)` | `src/sase/main/artifact_handler.py`, `src/sase/main/entry.py`, `src/sase/main/parser.py`, `src/sase/main/parser_artifact.py`, `tests/main/test_artifact_cli.py`, `sdd/beads/issues.jsonl` |

Not found in the three checked repos:

`092bfd0f`, `128a6ddb`, `17d0643e`, `18f8f3c0`, `21f306f7`, `2ef8a4d2`, `352d228b`, `43174564`,
`43810e60`, `4678d870`, `477b2a5f`, `497f8aef`, `4aa71ac4`, `4fa0f383`, `52922142`, `54957da1`,
`59de110a`, `5aedbab6`, `6063e84e`, `612e3514`, `62d5a598`, `680eaaf7`, `6aa89310`, `6ca8c27b`,
`71c83e7a`, `7afd801c`, `80d7c8f5`, `92156fed`, `927a4198`, `933a5568`, `9a1e2164`, `a7b377d0`,
`aa34a34d`, `ab5ab133`, `c4ea0599`, `c52b3a70`, `cbf734fc`, `d32c927e`, `d5ef9808`, `d83f0344`,
`e41da0bc`, `e51fb9fa`, `e660c16b`, `e96f274c`, `e9964998`, `ef539eb9`, `f0e77c95`, `f2181a0b`,
`fad1f532`.

Use the note hashes as breadcrumbs only. Several bead note hashes are absent from the final visible histories, while
the path diffs and current symbol search still expose the authoritative removal surface.

## Remove Bucket

### This Repo

Delete whole files or directories that are dedicated to the unified artifact graph, `sase artifact`, or the artifact
panel:

- `docs/artifacts.md`
- `src/sase/core/artifact_facade.py`
- `src/sase/core/artifact_wire/`
- `src/sase/main/artifact_cli/`
- `src/sase/main/artifact_handler.py`
- `src/sase/main/parser_artifact.py`
- `src/sase/xprompts/skills/sase_artifact.md`
- `src/sase/ace/tui/actions/artifact_summaries.py`
- `src/sase/ace/tui/actions/artifacts.py`
- `src/sase/ace/tui/artifact_graph_refresh.py`
- `src/sase/ace/tui/models/artifact_indicator.py`
- `src/sase/ace/tui/models/artifact_summary_cache.py`
- `src/sase/ace/tui/modals/artifact_panel_modal*.py`
- `src/sase/ace/tui/modals/artifact_panel_state*.py`
- `src/sase/ace/tui/modals/artifact_panel_renderers/`
- `src/sase/axe/artifact_metadata.py`
- `src/sase/axe/run_agent_exec_plan_artifacts.py`
- `tests/main/artifact_cli_helpers.py`
- `tests/main/test_artifact_cli_*`
- `tests/test_core_facade/test_artifact*.py`
- `tests/test_axe_artifact_metadata.py`
- `tests/perf/artifact_graph/`
- `tests/perf/bench_artifact_graph.py`
- `tests/ace/tui/test_artifact_panel_launch.py`
- `tests/ace/tui/test_artifact_graph_refresh.py`
- `tests/ace/tui/test_agent_artifact_indicators.py`
- `tests/ace/tui/actions/test_artifact_summary_loading.py`
- `tests/ace/tui/actions/test_agent_artifact_startup_contracts.py`
- `tests/ace/tui/models/test_artifact_indicator.py`
- `tests/ace/tui/modals/_artifact_panel_modal_helpers.py`
- `tests/ace/tui/modals/test_artifact_panel_*`

Remove SDD artifacts for `sase-23` and `sase-24` after product-code phases land:

- `sdd/legends/202605/unified_artifacts.md`
- `sdd/legends/202605/artifacts_panel_redesign.md`
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
- matching prompt files under `sdd/prompts/202605/` for those plans
- matching research, handoff, rollout, and perf files under `sdd/research/202605/` and `sdd/tales/202605/` whose
  titles are scoped to unified artifacts, artifact graph navigation, artifact panel rollout, or artifact graph perf
- `sase-23*` and `sase-24*` rows from `sdd/beads/issues.jsonl` and the corresponding SQLite records in
  `sdd/beads/beads.db`

### `../sase-core`

Delete the Rust graph substrate:

- `crates/sase_core/src/artifact/export.rs`
- `crates/sase_core/src/artifact/ingest.rs`
- `crates/sase_core/src/artifact/mod.rs`
- `crates/sase_core/src/artifact/query.rs`
- `crates/sase_core/src/artifact/store.rs`
- `crates/sase_core/src/artifact/wire.rs`

Remove PyO3 graph bindings and tests from:

- `crates/sase_core_py/src/lib.rs`

Remove graph-only dependency additions from:

- `Cargo.toml`
- `Cargo.lock`
- `crates/sase_core/Cargo.toml`

### `~/.local/share/chezmoi`

Delete generated deployed skill files:

- `home/dot_claude/skills/sase_artifact/SKILL.md`
- `home/dot_codex/skills/sase_artifact/SKILL.md`
- `home/dot_gemini/skills/sase_artifact/SKILL.md`

Remove the empty `sase_artifact` directories if no files remain.

### Plugin Repos

Focused searches found no removal targets in:

- `../sase-nvim`
- `../sase-github`
- `../sase-google`
- `../sase-telegram`

## Preserve Bucket

Preserve older or unrelated agent artifact behavior:

- `src/sase/artifacts.py`
- `src/sase/agent/agent_artifacts_cache.py`
- `src/sase/ace/tui/models/agent_artifacts.py`
- `src/sase/ace/tui/actions/agents/_revive_artifacts.py`
- `tests/test_artifacts.py`
- `tests/test_workflow_artifact.py`
- `tests/agent/test_agent_artifacts_cache.py`
- `tests/ace/agent_artifact_startup_fixtures.py`
- `tests/test_agent_artifact_startup_fixtures.py`
- `tests/ace/tui/widgets/test_prompt_artifact_cache.py`
- `sdd/prompts/202605/agent_artifact_startup_perf.md`
- `sdd/epics/202605/agent_artifact_startup_perf.md`
- `sdd/research/202605/agent_artifact_loading_startup.md`
- `sdd/research/202605/agent_artifact_loading_startup_infographic.png`
- `sdd/prompts/202605/artifact_pyvision_cleanup.md`
- `sdd/tales/202605/artifact_pyvision_cleanup.md`
- `sdd/prompts/202604/unreadable_artifact_scan.md`
- `sdd/tales/202604/unreadable_artifact_scan.md`
- `sdd/research/202604/artifacts_panel.md`
- `sdd/research/202604/artifacts_panel_infographic.png`

Preserve unrelated same-window work, including:

- `54e8402b feat: add leader agent run log keymap`
- `46bfca63 chore: Add SDD prompt and plan for cross_panel_agent_jump`
- `93e6becd fix: keep agent jump focus with cross-panel target`
- `d3295df5 chore: Add SDD prompt and plan for agent_untagged_panel`
- `47035433 fix: hide empty untagged agents panel`
- `98b8b4b feat: add Mercurial diff line stats` in `../sase-google`
- `home/bin/executable_install_sase_github` and `home/bin/executable_install_sase_google` changes in chezmoi

Preserve generic terms such as "artifact directory" when they refer to existing agent run output directories rather
than the unified artifact graph.

## Inspect Manually Bucket

Patch these files manually instead of deleting them. They were touched in the baseline diff and contain either artifact
graph integration hunks or adjacent unrelated behavior:

### This Repo

- `docs/xprompt.md` - remove only the `sase_artifact` skill row.
- `src/sase/main/entry.py` - remove artifact handler dispatch only.
- `src/sase/main/parser.py` - remove artifact parser registration only.
- `src/sase/default_config.yml` - restore `show_agent_run_log: "A"` and remove `open_artifacts_panel`.
- `src/sase/ace/tui/bindings.py` - restore the legacy `A` binding.
- `src/sase/ace/tui/keymaps/types.py` - remove the artifact command field while preserving unrelated keymap work.
- `src/sase/ace/tui/commands/catalog.py` and `src/sase/ace/tui/commands/availability.py` - remove artifact command
  catalog entries only.
- `src/sase/ace/tui/modals/__init__.py` - remove `ArtifactPanelModal` exports only.
- `src/sase/ace/tui/modals/help_modal/bindings.py` - replace artifact help labels with legacy run-log labels.
- `src/sase/ace/tui/styles.tcss` - remove only `ArtifactPanelModal` CSS blocks.
- `src/sase/ace/tui/actions/__init__.py`, `_state_init.py`, `event_handlers.py`, `startup.py`, `app.py` - remove graph
  refresh/cache state and action wiring only.
- `src/sase/ace/tui/actions/changespec/_display.py` and `_loading.py` - remove artifact indicator load/render hunks
  while preserving grouped rows, jump hints, and detail-only refresh behavior.
- `src/sase/ace/tui/actions/agents/_display_helpers.py`, `_display_panels.py`, `_loading.py`,
  `_loading_finalize.py`, `_panels.py` - remove artifact indicator and summary load hunks while preserving panel
  grouping, untagged panels, workflow rows, and cross-panel navigation.
- `src/sase/ace/tui/util/fs_watcher.py` - remove graph refresh trigger paths only.
- `src/sase/ace/tui/widgets/_agent_list_build.py`, `_agent_list_render_agent.py`, `_agent_list_render_banner.py`,
  `_agent_list_render_cache.py`, `_agent_list_styling.py`, `agent_list.py` - remove indicator render/cache dimensions
  only.
- `src/sase/ace/tui/widgets/_changespec_list_helpers.py`, `_changespec_list_render.py`, `changespec_list.py`,
  `changespec_detail.py`, `deltas_builder.py`, `keybinding_footer.py` - remove artifact indicator display plumbing only.
- `src/sase/axe/run_agent_exec_plan_artifacts.py` callers and adjacent workflow metadata writers - remove only graph
  metadata writes; keep bead IDs, workspace paths, changespec links, prompt/history metadata, and retry-chain metadata.
- `tests/test_commit_workflow_artifacts.py` - preserve any non-graph commit workflow coverage; remove graph metadata
  assertions.
- Existing TUI tests changed in the same window, such as `tests/ace/tui/test_show_agent_run_log_keymap.py`,
  `tests/ace/tui/widgets/test_agent_list_*`, `tests/ace/tui/widgets/test_changespec_list_*`, and
  `tests/ace/tui/test_*fold*`, should be patched only where they assert artifact indicators or `open_artifacts_panel`.

### `../sase-core`

- `crates/sase_core/src/lib.rs` - remove only `artifact` module exports and re-exports.
- `crates/sase_core_py/src/lib.rs` - remove only `artifact_*` functions, registrations, and tests. Keep older
  `scan_agent_artifacts`, `rebuild_agent_artifact_index`, `query_agent_artifact_index`, and cleanup marker bindings.
- `Cargo.toml`, `Cargo.lock`, `crates/sase_core/Cargo.toml` - remove only dependencies introduced for the unified graph,
  such as graph/export/search support that becomes unused after artifact module deletion.

### `~/.local/share/chezmoi`

- Do not alter `home/bin/executable_install_sase_github` or `home/bin/executable_install_sase_google`; they are present
  in the baseline diff but are unrelated to `sase_artifact`.

## Validation Commands For Later Phases

Run the relevant repo-local checks after each deleting phase:

- this repo: `just install` then `just check`
- `../sase-core`: `cargo test` or repo-local `just check` if available
- `~/.local/share/chezmoi`: `just check`; after final apply, `chezmoi apply --force`

Focused negative searches after removal:

```bash
rg -n "ArtifactPanel|open_artifacts_panel|sase_artifact|sase artifact|artifact_show_paged|artifact_summary|artifact_graph|artifacts_panel_redesign|unified_artifacts|sase-23|sase-24" src tests docs sdd
rg -n "ArtifactPanel|open_artifacts_panel|sase_artifact|sase artifact|artifact_show_paged|artifact_summary|artifact_graph" crates Cargo.toml Cargo.lock
rg -n "sase_artifact|sase artifact|unified artifact graph" home/dot_claude home/dot_codex home/dot_gemini home/dot_config/sase
```
