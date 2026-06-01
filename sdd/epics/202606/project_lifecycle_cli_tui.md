---
create_time: 2026-06-01 12:38:22
bead_id: sase-49
tier: epic
status: done
prompt: sdd/prompts/202606/project_lifecycle_cli_tui.md
---
# Project Lifecycle CLI and TUI Implementation Plan

## Goal

Implement first-class SASE project lifecycle state with `active`, `archived`, and `closed` projects. Users must be able
to inspect and mutate lifecycle state from the CLI and from the ace TUI. The ace TUI must expose a global project
management entry point, using `,P` by default, that lists active/archived/closed projects, supports state filtering, and
makes changing a project's state easy.

The design should follow `sdd/research/202606/project_lifecycle_state.md`: store lifecycle state in the active
ProjectSpec header as `PROJECT_STATE: ...`, treat missing state as `active`, keep `home` out of user lifecycle
management for the first implementation, and put shared lifecycle parsing/filtering behavior in `sase-core`.

## Key Decisions

- Storage: add `PROJECT_STATE:` to the ProjectSpec metadata header before `RUNNING:` or the first `NAME:` block.
- Default: a missing `PROJECT_STATE` is `active`; no migration is needed.
- Safety: state changes to `archived` or `closed` must reject projects with live work unless `--force` is passed.
- Launch behavior: archived/closed projects must not accept new work. The race-safe gate belongs inside the existing
  ProjectSpec lock used for `RUNNING` claims.
- Visibility: normal daily views default to active projects, while live agents/workflows from archived or closed
  projects remain visible until they finish.
- TUI keymap: use leader `,P` for the project management panel. This currently conflicts with `temporary_llm_override`;
  move that leader binding to `,o` and update default config, help, footer, and command catalog together.

## Phase 1: Core Lifecycle Contract

Owner scope: `../sase-core` plus the thin Python facade/wire layer in this repo.

Implement the shared lifecycle model in Rust:

- Add a `project_lifecycle` or expanded `project_spec` module in `crates/sase_core`.
- Define lifecycle enum values `active`, `archived`, and `closed`.
- Add parsing helpers for ProjectSpec header metadata:
  - missing `PROJECT_STATE` => `active`
  - invalid stored values => warning plus effective `active`
  - writers reject invalid target states
- Add content-update helper:
  - replace an existing `PROJECT_STATE:` line in the metadata header
  - insert before `RUNNING:` or the first `NAME:` when absent
  - preserve unrelated content and newline style as much as practical
- Add project-record listing over a projects root:
  - canonical `.sase` preferred over legacy `.gp`
  - include project name, active project file path, archive file path if present, workspace dir if present, effective
    state, whether the state was explicit, active claim count, launchability/workspace warnings, and parse warnings
  - sort by project name
  - exclude or mark `home` as system-managed for lifecycle mutation
- Expose PyO3 bindings for pure operations:
  - `read_project_lifecycle_from_content(content) -> dict`
  - `apply_project_lifecycle_update(content, state) -> str`
  - `list_project_records(projects_root, include_states, include_home=False) -> list[dict]`

Add Python facade code in this repo:

- Add typed dataclasses/converters under `src/sase/core/project_lifecycle_wire.py` and
  `src/sase/core/project_lifecycle_facade.py` or equivalent local naming.
- Keep Python host IO and locking outside Rust, matching the existing status and agent-scan facade patterns.
- Add tests that fake stale/missing Rust bindings where appropriate and parity tests that call the real binding when
  available.

Acceptance checks:

- Rust unit tests cover missing, valid, invalid, duplicate, and insertion-position cases.
- Python facade tests cover dict conversion and stale-binding failures.
- `cargo test --workspace` passes in `../sase-core`.
- Relevant Python facade tests pass in this repo after `just install`/`just rust-install`.

## Phase 2: CLI and Locked Mutation

Owner scope: CLI parser/handler, locked lifecycle mutation, CLI tests, ProjectSpec docs.

Add a `sase project` command group:

- `sase project list [-s|--state active|archived|closed|all] [-j|--json]`
- `sase project show <project> [-j|--json]`
- `sase project set-state <project> <active|archived|closed> [-f|--force]`
- `sase project activate <project> [-f|--force]`
- `sase project archive <project> [-f|--force]`
- `sase project close <project> [-f|--force]`

Implementation details:

- Add `src/sase/main/parser_project.py` and register it alphabetically in `src/sase/main/parser.py`.
- Add dispatch in `src/sase/main/entry.py` and a focused `src/sase/main/project_handler.py`.
- Use both short and long options for new flags, following repo convention.
- Implement a Python host-side mutation helper that:
  - resolves the preferred active ProjectSpec path
  - acquires `changespec_lock(project_file)`
  - reads current content
  - blocks archive/close when live work is present unless forced
  - applies the Rust content update helper
  - writes via `write_changespec_atomic()`
- At minimum, live-work blocking must include `RUNNING` claims in the ProjectSpec. If practical in this phase, also use
  the agent artifact scanner to block on live `running.json`, `waiting.json`, and pending-question markers for that
  project.
- CLI JSON should be stable and useful: project name, state, explicit/defaulted state, project file, archive file,
  workspace dir, active claim count, launchable boolean, warnings.
- CLI text output should be compact and tabular for list/show, with clear reactivation hints for inactive projects.
- Update `docs/project_spec.md` to document `PROJECT_STATE`, defaults, valid values, and manual-edit caveats.
- Update `docs/cli.md` with the new command group.

Acceptance checks:

- CLI parser tests verify default subcommand behavior, option shapes, and invalid states.
- Handler tests cover list/show JSON, missing project, missing state default, set-state insertion, set-state
  replacement, force behavior, and rejection with live claims.
- `sase project list` defaults to active projects.
- `sase project list --state all --json` includes archived/closed projects.

## Phase 3: Launch Enforcement and Active Defaults

Owner scope: workspace claim paths, project launch discovery, ChangeSpec discovery defaults, and related regression
tests.

Make inactive projects stop accepting new work:

- Add a lifecycle guard to `src/sase/running_field/_operations.py` inside the same locked read-modify-write cycle used
  by `claim_workspace()` and `allocate_and_claim_workspace()`.
- Return a clear `ClaimResult` error such as:
  `project 'foo' is archived; run 'sase project activate foo' before launching work`.
- Ensure deferred workspace (`workspace_num == 0`) claims still obey lifecycle.
- Audit direct launch paths that allocate/check workspaces before claiming, and add early user-facing checks where they
  improve errors, while keeping the locked claim guard as the authoritative gate.

Make normal project discovery active-only:

- Update `ProjectSelectModal` and `project_discovery.list_launchable_projects()` to use active lifecycle records by
  default.
- Update `find_all_changespecs()` and the cached snapshot equivalent to default to active project directories, while
  providing an explicit internal/all-states option for management and history views.
- Keep all RUNNING-field loaders scanning all project files so live agents from archived/closed projects remain visible.
- Ensure CWD/project inference can still resolve an archived/closed project so a user can reactivate it from inside its
  workspace.

Acceptance checks:

- Launch attempts for archived/closed projects fail before claiming a workspace and include an activation hint.
- Active projects continue launching exactly as before.
- ChangeSpec list/search defaults exclude archived/closed project ChangeSpecs.
- RUNNING agents from archived/closed projects still appear in the Agents tab/runners modal.

## Phase 4: Broader Project Filtering Integration

Owner scope: remaining known-project scans and non-TUI frontends that should default to active projects.

Wire lifecycle filtering into project-wide scans that currently walk every project:

- Rust artifact scanner/index options:
  - add lifecycle filtering directly or feed a prefiltered `only_projects` list from the Python facade
  - keep explicit all-history modes able to include inactive projects
- XPrompt known-project loading:
  - default project-local xprompt catalogs to active projects
  - explicit archived/closed references should produce a clear inactive-project message
- Bead/mobile helpers:
  - default broad project lists to active projects
  - explicit project operations can resolve inactive projects but must block work-launching mutations unless activated
- Any helper named `all_known` or equivalent should be reviewed so "all" means "all active" unless the caller explicitly
  requests inactive/all states.

Acceptance checks:

- XPrompt and project-local prompt discovery ignore archived/closed projects by default.
- Mobile/bead project discovery does not offer inactive projects as normal work targets.
- Explicit all-state/history paths still work for inspection.
- No active work disappears from agent/running views because of lifecycle filtering.

## Phase 5: TUI Project Management Panel

Owner scope: ace modal/panel UI, keymaps, help/footer/command catalog, and TUI tests.

Add a project management modal or panel:

- Open from global leader key `,P`.
- List all non-home projects by default, grouped or filterable by state.
- Show useful columns/details:
  - project name
  - state
  - workspace path/health
  - active claim count
  - launchable indicator
  - warnings from lifecycle parsing/discovery
- Support filters for active, archived, closed, and all. A simple cycle or segmented key set is fine; use the existing
  `OptionListNavigationMixin` and modal filtering patterns.
- Provide easy state changes for the highlighted project:
  - activate
  - archive
  - close
  - force archive/close when blocked, only after confirmation
- Mutations must call the same locked backend helper used by the CLI, not duplicate write logic.
- After mutation, reload project records and trigger enough app refresh to update ChangeSpecs, project pickers, agents,
  and footer status. Manual refresh is acceptable after external CLI changes.

Keymap updates:

- Add a leader-mode key entry such as `projects: "P"` in `default_config.yml`.
- Move `temporary_llm_override` from `P` to `o`.
- Update `LeaderModeKeymaps`, `KeybindingFooter.update_leader_bindings()`, help modal bindings, and command catalog.
- Add a direct command-palette command for opening the project management panel if that catalog supports app actions
  without leader-mode keys.

Suggested modal keybindings:

- `j/k` and arrows: navigate
- `/` or focused input: text filter
- `tab` or a small key set: state filter cycle
- `a`: activate
- `r`: archive
- `c`: close
- `F`: force current state change after confirmation when blocked
- `enter`: show project details or default to activate if inactive
- `q`/`escape`: close

Acceptance checks:

- `,P` opens the project panel from Changespecs, Agents, and AXE tabs.
- The panel can filter active/archived/closed/all without losing selection unexpectedly.
- State mutations update the ProjectSpec header and the modal row in-place.
- Attempting to archive/close a project with live work shows a clear blocked message and offers/handles forced action.
- Temporary model override remains available on its new key and in help/footer displays.

## Phase 6: Documentation, Migration Notes, and End-to-End Verification

Owner scope: docs, release note style context, cross-phase cleanup, and final checks.

Finish user-facing and maintainer-facing polish:

- Update relevant ace/TUI docs for the project management panel and keymap.
- Update configuration docs/schema if keymap schema documentation is generated or validated.
- Add a short note that existing projects are treated as active until `PROJECT_STATE` is written.
- Add examples for common workflows:
  - archive dormant project
  - list all closed projects
  - reactivate from CLI
  - reactivate from TUI
- Revisit any helper still doing an unfiltered `~/.sase/projects` scan and either route it through lifecycle records or
  document why it must include all projects.

Final verification:

- Run `just install` first in this ephemeral workspace.
- Run `just check`.
- In `../sase-core`, run `cargo fmt --check`, `cargo clippy --workspace --all-targets -- -D warnings`, and
  `cargo test --workspace`, or the local Justfile wrappers if those are the established commands.
- Run focused TUI tests for keymaps/modals and any visual/snapshot tests affected by footer/help text.
- Manually smoke-test:
  - `sase project list`
  - `sase project archive <project>`
  - failed launch on archived project
  - `sase project activate <project>`
  - ace `,P` panel open/filter/state-change path

## Cross-Phase Notes

- Do not modify memory files.
- Do not move project directories as part of this work.
- Do not make `home` user-configurable in the first implementation.
- Preserve legacy `.gp` read compatibility, but write canonical `.sase` where existing helpers already do.
- Keep lifecycle state out of `sase.yml`; TUI state changes must not rewrite user-managed config.
- Prefer Rust-owned pure domain logic and Python-owned host IO/locking, consistent with the existing Rust backend
  boundary.
- Every phase that changes code should include focused tests and run the narrowest meaningful checks before handoff.
