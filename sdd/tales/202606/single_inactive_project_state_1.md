---
create_time: 2026-06-02 12:52:11
status: done
prompt: sdd/prompts/202606/single_inactive_project_state_1.md
---
# Plan: Single Inactive Project State

## Goal

Replace the project lifecycle model `active | archived | closed` with the canonical model `active | inactive`.
`inactive` should merge the current behavior of `archived` and `closed`: hidden from default launch/discovery surfaces,
not launchable, protected from new `RUNNING` claims, still visible in explicit management/history/all-state scans, and
reactivated through `sase project activate`.

This is a project-level lifecycle change only. It must not change ChangeSpec `STATUS: Archived`, artifact archive
directories, archived diffs, or other unrelated uses of the words "archive" and "closed".

## Current Shape

The current Python repo exposes `active`, `archived`, and `closed` through:

- Rust-backed lifecycle facade and wire constants in `src/sase/core/project_lifecycle_wire.py` and
  `src/sase/core/project_lifecycle_facade.py`.
- Rust core lifecycle logic in `../sase-core/crates/sase_core/src/project_spec.rs`, plus Python binding exports in
  `../sase-core/crates/sase_core_py/src/lib.rs`.
- Rust artifact-scan lifecycle filtering in `../sase-core/crates/sase_core/src/agent_scan/scanner.rs`.
- CLI parser/handler in `src/sase/main/parser_project.py` and `src/sase/main/project_handler.py`.
- Launch protection in `src/sase/running_field/_operations.py`.
- Lifecycle-aware ChangeSpec, project picker, xprompt, mobile/helper, and agent-scan surfaces.
- ACE Project Management modal filters, state colors, counts, keybindings, bulk actions, statuses, and visual snapshots.
- User docs in `README.md`, `docs/project_spec.md`, `docs/configuration.md`, `docs/cli.md`, `docs/ace.md`, and related
  launch/discovery docs.

The repository notes say shared domain behavior belongs in the sibling Rust core repo. The matching workspace is
available at `/home/bryan/.local/state/sase/workspaces/sase-org/sase-core/sase-core_10` via
`sase workspace open -p sase-core 10`, so implementation should update Rust core first, then update Python callers and
tests in this repo against the new Rust-backed contract.

## Product Contract

Use these rules across all surfaces:

- Canonical states are `active` and `inactive`; missing `PROJECT_STATE` still means `active`.
- `PROJECT_STATE: inactive` is the only inactive value written by new code.
- Legacy on-disk `PROJECT_STATE: archived` and `PROJECT_STATE: closed` remain readable and are normalized to `inactive`
  so existing ProjectSpecs do not break.
- Default discovery remains active-only.
- Explicit all-state scans include active and inactive projects, including legacy archived/closed records normalized to
  inactive.
- Launch/new-work attempts in inactive projects fail before writing `RUNNING`, with the same activation hint but using
  "inactive" wording.
- State changes to inactive continue to reject live `RUNNING` claims and live artifact markers unless `--force` is used.
- Agent-history, stale-claim cleanup, dismissed-agent recovery, and name-collision paths still scan all project states
  when they intentionally need historical/live inactive project data.

## Compatibility Strategy

Do not perform an eager filesystem migration. Lazy normalization is safer and avoids rewriting every user ProjectSpec.

Retain compatibility where it prevents surprising breakage:

- Existing ProjectSpecs with `archived` or `closed` load as explicit `inactive`.
- `sase project archive <project>` and `sase project close <project>` remain hidden/deprecated compatibility aliases
  that set `inactive`.
- `sase project set-state <project> archived|closed` can normalize to `inactive` for compatibility, even though help and
  docs show only `active|inactive`.
- `sase project list --state archived|closed` can remain a hidden compatibility filter that maps to `inactive`, while
  visible help and docs show `active|inactive|all`.

This gives users one status everywhere new, while avoiding immediate script and data breakage.

## Phase 1: Rust Core Lifecycle Contract

In the matching `sase-core` workspace, update the shared lifecycle domain logic first:

- Change the canonical lifecycle states to `active` and `inactive`.
- Add or centralize `is_active` / `is_inactive` style predicates in Rust so callers do not keep re-deriving
  `state == active` or inactive set membership.
- Parse missing `PROJECT_STATE` as defaulted `active`.
- Parse canonical `PROJECT_STATE: inactive` as explicit inactive.
- Parse legacy `PROJECT_STATE: archived` and `PROJECT_STATE: closed` as explicit inactive, preferably with a parse
  warning such as "legacy project state archived treated as inactive".
- Preserve the current behavior for unknown invalid states, but update tests so that behavior is intentional.
- Make lifecycle update/write helpers insert or replace `PROJECT_STATE:` with canonical `active` or `inactive` only.
- Make `list_project_records(..., include_states=["inactive"])` return canonical inactive records plus legacy
  archived/closed records normalized to inactive.
- Make `include_states="all"` / all-state callers expand to `active + inactive`, not `active + archived + closed`.
- Keep `launchable` true only for active projects with a valid workspace.
- Update Rust artifact-scan lifecycle filtering so `include_project_states=["inactive"]` includes canonical inactive and
  legacy archived/closed projects after normalization.
- Update Rust unit tests and Python binding tests for canonical inactive, legacy normalization, list filtering, and
  mutation output.

If the wire record shape can stay the same (`state: str`, `parse_warnings: list[str]`), avoid a schema bump. If Rust
needs to expose a raw legacy value, add it deliberately and update the Python dataclass/schema tests together.

## Phase 2: Python Facade And Shared Helpers

After Rust is updated:

- Change `PROJECT_LIFECYCLE_STATES` in `src/sase/core/project_lifecycle_wire.py` to `("active", "inactive")`.
- Add a small shared normalization helper for legacy aliases so parser/handler/TUI code does not duplicate
  `archived|closed -> inactive`.
- Replace local `_INACTIVE_STATES = {"archived", "closed"}` style constants with a single inactive predicate/helper.
- Update facade tests in `tests/test_core_facade/test_project_lifecycle.py` to expect inactive as the canonical state
  and to cover legacy archived/closed inputs.

## Phase 3: CLI Behavior

Update `sase project` as the primary user-facing surface:

- Visible lifecycle filters become `active`, `inactive`, and `all`.
- Visible `set-state` choices become `active` and `inactive`.
- Add a visible `sase project deactivate <project> [-f|--force]` alias for `set-state <project> inactive`.
- Keep `activate` unchanged.
- Keep `archive` and `close` as hidden/deprecated compatibility aliases that call the inactive path.
- Update help text from "archiving or closing" to "setting inactive" / "deactivating".
- Update table/detail output so inactive rows show `inactive`, including legacy records normalized by Rust.
- Update JSON output expectations so `state` is `inactive` and `state_source` remains explicit/defaulted as before.
- Update CLI tests in `tests/main/test_project_handler.py` for inactive list/show/set/deactivate, legacy alias behavior,
  force behavior, and live-work blocking.

## Phase 4: ACE Project Management Modal

Collapse the modal to a single inactive state:

- Change `ProjectStateFilter` and tabs from `active / archived / closed / all` to `active / inactive / all`.
- Replace separate Archive and Close actions with one Deactivate action.
- Use a visible keybinding such as `d` for deactivate, while keeping `Ctrl+D` for delete.
- Keep `a` and Enter as activate/reactivate actions.
- Update footer, summary counts, detail hints, status strings, bulk-force wording, and color styling.
- Ensure marked-project bulk behavior still supports activate, deactivate, and delete.
- Update modal unit tests and visual snapshots for the new tabs, counts, keybindings, labels, and styles.

## Phase 5: Launch, Discovery, And Helper Surfaces

Update every lifecycle-aware caller to use canonical inactive:

- `src/sase/running_field/_operations.py`: reject inactive projects with "project '<name>' is inactive; run 'sase
  project activate <name>' before launching work"; add tests for canonical inactive and legacy archived/closed
  normalization.
- `src/sase/ace/changespec/discovery.py`: normalize state filters and ensure default active-only/all-state behavior
  still holds.
- `src/sase/ace/tui/modals/project_discovery.py`: launchable project lists remain active-only; all-state callers use
  active/inactive.
- `src/sase/xprompt/loader_sources.py`: explicit inactive project references produce inactive-project messages; broad
  catalogs stay active-only.
- Agent scan options and mobile/helper bridge surfaces should accept `inactive` where they currently mention archived or
  closed, while preserving all-state history behavior.
- Update tests for ChangeSpec filtering, CWD/VCS project resolution, project-local xprompts, running-field launch gates,
  agent scan options, and mobile/helper lifecycle warnings.

## Phase 6: Documentation

Update current product docs and avoid rewriting historical SDD plans unless they are active/generated references:

- `README.md`
- `docs/project_spec.md`
- `docs/configuration.md`
- `docs/cli.md`
- `docs/ace.md`
- `docs/xprompt.md`
- `docs/workspace.md`
- `docs/mobile_gateway.md`
- `docs/query_language.md`
- `docs/integrations.md`

Docs should emphasize:

- Valid `PROJECT_STATE` values are `active` and `inactive`.
- Missing state means active.
- Legacy `archived`/`closed` ProjectSpecs are read as inactive for compatibility.
- `inactive` is separate from ChangeSpec `STATUS: Archived`.
- Use `sase project deactivate` or `sase project set-state <project> inactive` to hide projects from normal work
  surfaces.

## Phase 7: Verification

Before finalizing implementation:

- Run `just install` if the workspace has not been installed.
- Run focused tests while iterating:
  - `pytest tests/test_core_facade/test_project_lifecycle.py`
  - `pytest tests/main/test_project_handler.py`
  - `pytest tests/test_running_field_operations.py`
  - `pytest tests/ace/changespec/test_lifecycle_filtering.py`
  - `pytest tests/test_project_local_xprompts.py`
  - `pytest tests/ace/tui/modals/test_project_management_modal_*.py`
  - affected mobile/helper and agent-scan tests
- Run visual snapshot tests for the Project Management modal and update PNG snapshots only if the rendered change is
  intentional.
- Run `just check` for the final repo verification after implementation file changes.
- Run the Rust core test suite in the matching `sase-core` workspace before depending on the updated binding here.

## Main Risks

- Hidden external scripts may depend on `--state archived` or `--state closed`; hidden compatibility aliases reduce this
  risk.
- A Python-only change would drift from the Rust-backed lifecycle contract; update Rust core first.
- Legacy values must be normalized consistently, otherwise all-state scans and launch gates could disagree.
- Visual snapshot churn is expected in the Project Management modal because the tabs, counts, and footer will change.
