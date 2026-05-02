---
create_time: 2026-04-30 17:25:02
status: done
bead_id: sase-1l
prompt: sdd/prompts/202604/epic_changespec_beads.md
---
# Plan: ChangeSpec-Aware Epic Beads

## Goal

Add first-class support for attaching a ChangeSpec name to a SASE epic bead and use that attachment when
`sase bead work` launches the epic's phase agents.

When an epic has a ChangeSpec attachment:

- The first phase agent should be launched against the normal project VCS ref, e.g. `#git:<project>`, and should also
  include `#pr:<changespec_name>` so it creates/owns the ChangeSpec branch/PR.
- Every later phase agent, plus the final land agent, should be launched against the ChangeSpec ref, e.g.
  `#git:<changespec_name>`, so follow-up work happens on the ChangeSpec created by the first phase.
- `#bd/new_epic` should accept optional `changespec` and `bug_id` inputs. `bug_id` is valid only when `changespec` is
  provided and should be passed through to `#pr` when present.

The implementation should remain VCS-plugin-neutral. Do not hard-code a runtime or provider assumption; derive the
workflow tag (`git`, `gh`, `hg`, etc.) through the existing workspace provider/project-file mechanisms.

## Phase 1: Persist ChangeSpec Metadata on Epic Beads

Owner: one implementation agent.

Scope:

- Extend the bead `Issue` model with nullable ChangeSpec attachment fields on plan beads:
  - `changespec_name: str`
  - `changespec_bug_id: str` or `int | None`, depending on existing validation ergonomics
- Add validation rules:
  - phase beads cannot carry ChangeSpec metadata
  - `bug_id` cannot be set unless `changespec_name` is set
- Update SQLite schema and migrations:
  - new installs get the new columns
  - existing bead databases migrate without data loss
- Update JSONL import/export so attachments survive rebuilds and sync.
- Add public API support in `BeadProject.create()` and `BeadProject.update()` only where needed.
- Update `sase bead create` with short options for every new CLI option:
  - e.g. `-c/--changespec`
  - e.g. `-b/--bug-id`
- Enforce that these options are only accepted for `--type plan(...)`.
- Update `sase bead show` to display the ChangeSpec attachment for plan beads.

Tests:

- model validation tests for valid/invalid attachment combinations
- db create/get/update/migration tests
- JSONL round-trip tests
- CLI create/show tests covering `--changespec`, `--bug-id`, and invalid phase/bug-only cases

Deliverable:

- Epic beads can store and display a ChangeSpec attachment, and the metadata persists through database and JSONL paths.

## Phase 2: Render ChangeSpec-Aware Epic Work Prompts

Owner: one implementation agent.

Scope:

- Extend the epic work planning/rendering path so `render_multi_prompt()` can receive optional ChangeSpec launch
  context:
  - `changespec_name`
  - optional `bug_id`
  - `vcs_workflow` name, derived through existing workspace-provider helpers
  - `project_name`, derived from the current project file/workspace
- Keep the no-ChangeSpec rendering exactly backward compatible.
- When ChangeSpec metadata exists:
  - first non-closed phase segment starts with `#<vcs_workflow>:<project_name>`
  - first segment also includes `#pr:<changespec_name>` or `#pr(name=<changespec_name>, bug_id=<bug_id>)`, using syntax
    accepted by the current xprompt argument parser
  - every later phase segment starts with `#<vcs_workflow>:<changespec_name>`
  - the land segment starts with `#<vcs_workflow>:<changespec_name>`
  - existing `%name`, `%approve`, `%w`, and `#bd/work_phase_bead:<bead_id>` / `#bd/land_epic:<epic_id>` lines remain
    present
- Update `handle_bead_work` to:
  - read the attachment from the epic bead
  - derive VCS/project context only when the epic has a ChangeSpec attachment
  - fail with a clear error if a ChangeSpec-attached epic is launched from a context where VCS/project cannot be
    resolved
- Keep user xprompt override behavior intact: only the `bd/work_phase_bead` and `bd/land_epic` xprompt names should vary
  by tag resolution; the VCS and `#pr` references are launch wrappers around those xprompts.

Tests:

- unit snapshots for legacy rendering unchanged
- unit snapshots for ChangeSpec rendering with one phase, multiple phases, dependencies, and land
- bug ID rendering test
- CLI dry-run test that verifies the generated multi-prompt without mutating bead state
- error-path test for missing VCS/project context

Deliverable:

- `sase bead work <epic_id> --dry-run` shows the required `#<vcs>` and `#pr` wrappers for ChangeSpec-attached epics.

## Phase 3: Update `#bd/new_epic` and Creation Workflow Guidance

Owner: one implementation agent.

Scope:

- Update the builtin `bd/new_epic` xprompt in `src/sase/default_config.yml`.
- Add optional inputs:
  - `changespec: {type: word, default: null}`
  - `bug_id: {type: int, default: null}` or another nullable form supported by the xprompt parser
- Update prompt text so the bead-creation agent:
  - creates the epic plan bead with the ChangeSpec metadata when `changespec` is provided
  - passes `bug_id` only when `changespec` is provided
  - rejects/does not use `bug_id` by itself
  - continues to add `bead_id` to plan frontmatter
  - continues to commit bead-creation work before running `sase bead work <epic_id> --yes`
- Update xprompt tag/wiring tests to assert the new inputs and updated command guidance.
- If syntax clarity requires it, add an example to docs showing:
  - `#git:sase #bd/new_epic(plan_file_path=plans/..., changespec=sase_feature, bug_id=12345)`

Tests:

- builtin xprompt loading test for the new inputs/defaults
- lightweight content assertions for the new CLI flags and bug-only rule

Deliverable:

- The epic creation xprompt can be invoked with optional ChangeSpec metadata and instructs the agent to attach it to the
  created plan bead.

## Phase 4: Multi-Prompt VCS Metadata and End-to-End Hardening

Owner: one implementation agent.

Scope:

- Audit `launch_agent_from_cwd()` and `launch_multi_prompt_agents()` behavior when a multi-prompt contains different VCS
  refs in different segments.
- If current metadata/preallocation treats the first VCS ref as global, update multi-prompt launch so each segment
  derives its own VCS ref for:
  - running-field `cl_name`
  - preallocated workspace environment
  - history sort key
- Preserve existing wait/deferred-workspace behavior.
- Add regression tests for an epic multi-prompt where the first segment has `#<vcs>:<project> #pr:<changespec>` and
  later segments have `#<vcs>:<changespec>`.
- Run focused tests from earlier phases, then `just install` and `just check` before completion.

Deliverable:

- ChangeSpec-aware epic launches have correct prompt content and correct agent/workspace metadata across all phase and
  land agents.

## Implementation Notes

- Prefer storing the attachment on the plan/epic bead, not duplicating it across phase beads.
- Keep `bug_id` as metadata for the initial `#pr` creation path only; later phase and land agents should not receive
  `#pr`.
- Use existing VCS/provider abstractions:
  - `sase.workspace_provider.detect_workflow_type(project_file)` for the VCS xprompt name
  - existing project-name inference from the current project file/workspace
- Do not special-case Claude, Gemini, Codex, or any other runtime.
- Keep `bd/work_phase_bead` and `bd/land_epic` overrideable by semantic tag, as they are today.
