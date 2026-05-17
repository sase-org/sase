---
create_time: 2026-05-16 20:17:22
bead_id: sase-3r
tier: epic
status: done
prompt: sdd/prompts/202605/agent_families_2.md
---
# Agent Families Implementation Plan

## Summary

Introduce "agent families" as the durable model for plan, feedback, question, and coder handoff flows.

The target invariant is:

- The user-visible root agent name is stable and remains `<name>`.
- Phase/child agents use `<name>-<role>` or `<name>-<N>` names.
- The root row status mirrors the most recently launched child row status.
- `%wait:<name>` against a root/family waits for every member of that family to complete successfully.
- `#resume:<name>` against a root/family resolves to the most recent successfully completed family member.
- New user-specified names must not contain `-`.

This should be implemented with backwards compatibility for existing dot-suffixed artifacts. Historical names such as
`foo.plan`, `foo.code`, `foo.q`, and `foo.2` must continue to load, wait, and resume. The implementation should not
modify memory files unless explicitly approved.

## Current Implementation Map

Key current code paths:

- Naming constants and suffix inference: `src/sase/plan_chain.py`
- Plan, feedback, question, and coder follow-up artifacts: `src/sase/axe/run_agent_exec_plan.py`
- Root/follow-up artifact metadata helpers: `src/sase/axe/run_agent_helpers.py`
- Final done marker naming: `src/sase/axe/run_agent_exec.py`
- Wait marker lifecycle: `src/sase/axe/run_agent_wait.py`
- Wait dependency resolution chop: `src/sase/scripts/sase_chop_wait_checks.py`
- Wait chat and agent ref resolution: `src/sase/axe/run_agent_refs.py`
- Agent lookup and resume-derived naming: `src/sase/agent/names/*`
- Explicit name preflight validation: `src/sase/agent/launch_validation.py`
- TUI root status overlays: `src/sase/ace/tui/models/_agent_status_overrides.py`
- TUI wait/resume keymaps: `src/sase/ace/tui/actions/agents/_wait_resume.py`
- TUI metadata enrichment and agent loading: `src/sase/ace/tui/models/_loaders/*`
- Rust scan wire/parser if metadata fields are added: `../sase-core/crates/sase_core/src/agent_scan/*`

## Compatibility Model

Use the new `-` separator for new plan-chain artifacts:

- Planner phase: `-plan`
- Question phase: `-q`
- Coder phase: `-code`
- Feedback/question-answer continuation rounds: `-2`, `-3`, ...
- Existing non-coder plan actions should move to `-epic`, `-legend`, and `-commit` where those phase names are used.

Keep recognizing legacy dot suffixes in all readers:

- `.plan`, `.q`, `.code`, `.2`, `.3`, `.epic`, `.legend`, `.commit`

Do not classify arbitrary hyphenated historical names as families. Family parsing should only treat a suffix as a family
suffix when the suffix is one of the known phase suffixes or a numeric continuation. This avoids breaking older names
like bead-derived IDs that may contain hyphens.

## Phase 1: Naming Contract and Validation

Owner: one agent instance.

Goals:

- Add a single shared naming contract for agent-family suffixes.
- Make new code use hyphen suffixes without breaking old dot-suffixed reads.
- Forbid hyphens in new user-specified names.

Implementation shape:

- Update `src/sase/plan_chain.py` to define new canonical suffixes: `-plan`, `-q`, `-code`, `-2`, etc.
- Add helper functions for:
  - `agent_family_phase_name(base, suffix)`
  - `agent_family_base(name)`
  - `agent_family_suffix(name)`
  - `is_agent_family_member(name)`
  - `canonical_plan_chain_suffix(suffix)` accepting both new and legacy suffixes
  - `legacy_plan_chain_suffixes()` or equivalent for migration/compatibility tests
- Keep legacy suffix inference from `agent_meta.json` `role_suffix`, `name`, and `workflow_name`.
- Add validation for explicit user-specified names in all launch paths:
  - `%name` and `%n` parsing/preflight in `src/sase/agent/launch_validation.py`
  - runner-side claim path in `src/sase/axe/run_agent_directives.py`
  - TUI rename modal/action in `src/sase/ace/tui/actions/rename.py`
  - mobile launch helper in `src/sase/integrations/_mobile_agent_launch.py`
- Make forced reuse `%name:!foo` obey the same user-name validation after stripping `!`.
- Do not reject historical loaded names or internal generated phase names.

Tests:

- Add unit tests for new/legacy suffix canonicalization in `tests/test_plan_chain_roles.py` or a new focused file.
- Add explicit-name validation tests covering `%name:foo-bar`, `%name:!foo-bar`, modal rename, and mobile launch.
- Update tests that assert `.plan`, `.code`, `.q`, or `.<N>` for newly generated plan-chain names.

Exit criteria:

- New generated plan-chain names use `-`.
- Existing dot-suffixed metadata is still classified correctly.
- New user-entered names containing `-` fail before launch with a clear message.

## Phase 2: Runner Metadata and Handoff Semantics

Owner: one agent instance.

Goals:

- Stop renaming the root agent to a phase name.
- Make follow-up artifacts carry the new family/phase names.
- Preserve enough metadata for loaders and wait/resume to reason about the family.

Implementation shape:

- Change `promote_to_workflow()` in `src/sase/axe/run_agent_helpers.py` so root metadata keeps:
  - `name: <base>`
  - `workflow_name: <base>`
  - a dedicated root marker such as `plan_chain_root: true` or `agent_family: <base>`
- Do not set root `name` to `<base>-plan`.
- Decide whether to add explicit metadata fields:
  - `agent_family: <base>`
  - `agent_family_role: root | plan | code | q | feedback | epic | legend | commit`
  - If added, mirror them through Python wire dataclasses and Rust scan wire/parser.
- For the planner phase, because the root artifact is also the artifact that submitted the plan, expose the planner step
  as a logical child without changing the root name. The least disruptive design is a synthetic child row derived from
  the root artifact, with:
  - `name: <base>-plan`
  - `role_suffix: -plan`
  - `parent_timestamp: <root timestamp>`
  - plan path/chat metadata copied from the root artifact
- Update `handle_plan_marker()`:
  - Use `-plan` for planner chat and step metadata.
  - Feedback follow-ups use `-2`, `-3`, ...
  - Coder follow-ups use `-code`.
  - Epic/legend/commit follow-ups use hyphen phase names.
  - `source_plan_agent_name` uses `<base>-plan`.
- Update `handle_questions_marker()`:
  - Question phase suffix is `-q`.
  - Continuation follow-up uses the next numeric hyphen suffix.
- Update `_finalize_loop()` done marker naming to use the new helper and avoid dot fallback for plan-chain phases.
- Update optional `SASE_CODER_INHERIT_PLANNER_CHAT=1` behavior to resume `<base>-plan`, while keeping legacy reads.

Tests:

- Update `tests/test_axe_run_agent_exec_plan_followup_*`.
- Add tests proving root `agent_meta.json` keeps `name == <base>` after plan approval/feedback/question handling.
- Add tests proving planner/chat names are `<base>-plan` and coder names are `<base>-code`.
- Add compatibility tests for legacy dot metadata still finalizing and loading.

Exit criteria:

- A newly approved plan family has stable root `name=<base>` and child/follow-up phase names using hyphens.
- Existing dot-suffixed runs still behave as before when loaded or resumed.

## Phase 3: Loader, Tree, and Root Status Behavior

Owner: one agent instance.

Goals:

- Make the Agents tab display and status model reflect agent families.
- Root status must always equal the most recently launched child entry's status.
- Root wait/resume prompt generation uses the root family name, not a child phase name.

Implementation shape:

- Update agent loading to link family members by `agent_family`/`workflow_name` and parent timestamps.
- Add or adjust synthetic planner child creation if Phase 2 chose that design.
- Replace `is_root_plan_workflow()` assumptions that require root `role_suffix == ".plan"`.
- Update `apply_status_overrides()`:
  - Treat the root as a family container.
  - Compute the most recently launched child by `run_start_time` or `start_time`.
  - Assign root `status = newest_child.status`.
  - Continue propagating plan/feedback/question/code timestamps, diff path, and `meta_*` fields to the root.
  - Keep child statuses meaningful. For example, planner child can show `PLAN` while awaiting approval, coder child can
    show `RUNNING`, and completed coder child can show `DONE`.
- Remove or narrow root-only labels like `PLAN APPROVED`, `PLAN DONE`, and `TALE DONE` where they violate the new
  invariant. If those labels are still valuable, keep them on child/detail metadata rather than on the root status
  field.
- Update query child preservation and grouping keys that split on `"."` to use family helpers instead of hard-coded dot
  logic.
- Update copy/wait/resume UI helpers so when a root row is selected:
  - copied/name prompt value is `<base>`
  - `%w:<base>` is inserted
  - `#resume:<base>` is inserted Child rows may still use their phase name when directly selected.

Tests:

- Update `tests/test_agent_loader_status_override_*`.
- Add root invariant tests:
  - root + planner child awaiting approval => root status `PLAN`
  - root + active coder child => root status `RUNNING`
  - root + completed coder child => root status `DONE`
  - root + failed latest child => root status `FAILED`
  - root + feedback child as newest => root mirrors feedback child
- Add TUI action tests for wait/resume on root vs child rows.
- Update grouping tests that assume dot family splitting.

Exit criteria:

- The root row stays named `<base>`.
- The visible root status always matches the newest child row status.
- TUI keymaps insert root family names for root rows.

## Phase 4: Wait and Resume Backend Resolution

Owner: one agent instance.

Goals:

- `%wait:<base>` waits for successful completion of the entire `<base>` family.
- `#resume:<base>` resolves to the most recent successfully completed family member.
- Existing `%wait:<legacy-dot-name>` and `#resume:<legacy-dot-name>` remain supported.

Implementation shape:

- Add family-aware lookup helpers in `src/sase/agent/names/_lookup.py` or a new `names/_family.py`:
  - `find_agent_family(base)`
  - `is_agent_family_complete(base)`
  - `most_recent_completed_family_member(base)`
  - `resolve_resume_agent_name(name)`
  - `resolve_wait_dependency(name)`
- For waiting:
  - Update `src/sase/scripts/sase_chop_wait_checks.py` to index both exact names and families.
  - A family dependency resolves only when every known member in the newest family generation completed with
    `outcome == "completed"`.
  - If the newest member failed or was killed, the family dependency does not resolve.
  - If there is an exact non-family agent named `<base>` with no family children, preserve existing exact-name behavior.
  - Prefer the newest generation when historical families with the same base exist.
- For wait chat injection:
  - Update `resolve_wait_chat_paths()` so a waited family name resolves to the most recent completed family member's
    `response_path`. This gives the launched agent the final handoff chat without duplicating every phase transcript.
- For resume:
  - Update bare and explicit resume resolution so `#resume:<base>` maps to the newest completed family member at
    runtime.
  - Keep direct `#resume:<base>-plan` and legacy `#resume:<base>.plan` exact references working.
- Update `resolve_agent_changespec()` and `@name` handling only if needed. If `@<base>` should mean the family's latest
  successful changespec, route through the same family resolver; otherwise document that this phase leaves `@name`
  unchanged.

Tests:

- Extend `tests/test_axe_chop_wait_checks.py`:
  - successful plan family resolves `%wait:<base>`
  - failed latest child blocks `%wait:<base>`
  - killed latest child blocks `%wait:<base>`
  - legacy dot family still resolves
  - exact agent with no children still resolves as before
- Extend `tests/test_axe_run_agent_phases_wait_chats.py` for family handoff chat resolution.
- Extend `tests/test_agent_names.py` for resume target resolution.

Exit criteria:

- A root-family wait is a true family barrier.
- A root-family resume opens the latest successful family member.
- Legacy exact names continue to work.

## Phase 5: Compatibility, Migration, and Full Verification

Owner: one agent instance.

Goals:

- Finish repo-wide cleanup of dot assumptions.
- Keep old artifacts useful without rewriting memory files.
- Verify the behavior across CLI, TUI, mobile, and Rust-backed scan paths.

Implementation shape:

- Audit for remaining hard-coded `.plan`, `.code`, `.q`, and `.\d+` assumptions.
- Update docs/comments/tests that describe current runtime behavior, excluding memory files unless the user approves.
- If new metadata fields were introduced, update:
  - Python wire dataclasses and conversions
  - Rust wire structs and scanner parsing
  - parity tests under `../sase-core/crates/sase_core/tests`
- Decide whether to include an explicit artifact migration. Preferred default:
  - no in-place migration
  - read legacy dot artifacts forever
  - only new artifacts use hyphen suffixes
- Update dismissal/revival, bundle summary, and archive code if it rewrites names or prompt references.
- Confirm generated workflows that emit `%name` directives either avoid hyphenated user bases or intentionally use an
  internal/system bypass with tests. This is especially important for bead-derived names that may currently contain `-`.

Verification:

- Run `just install` first in this workspace if implementation files changed.
- Run focused tests after each phase.
- Before final handoff for implementation phases, run `just check`.
- If Rust core files changed, also run the relevant Rust tests or the repo command that exercises the Rust parity suite.

High-risk test targets:

- `tests/test_plan_chain_roles.py`
- `tests/test_axe_run_agent_exec_plan_followup_approvals.py`
- `tests/test_axe_run_agent_exec_plan_followup_prompt_construction.py`
- `tests/test_agent_loader_status_override_feedback.py`
- `tests/test_agent_loader_status_override_followups.py`
- `tests/test_axe_chop_wait_checks.py`
- `tests/test_axe_run_agent_phases_wait_chats.py`
- `tests/test_agent_names.py`
- `tests/test_agent_names_auto_name.py`
- `tests/ace/tui/test_agent_marking.py`
- `tests/test_mobile_agent_resume_options.py`
- Rust agent scan parity tests if wire fields change

Exit criteria:

- No new code path generates dot plan-chain suffixes.
- New user-specified names containing `-` are rejected consistently.
- Root rows keep the base name and mirror newest child status.
- Wait and resume with the root name operate on the family.
- Existing dot-suffixed artifacts remain loadable and actionable.

## Open Decisions for Implementers

1. Whether to add explicit `agent_family` and `agent_family_role` metadata or derive family membership from existing
   `workflow_name`, `role_suffix`, and `parent_timestamp`. Recommendation: add explicit metadata if the first
   implementation agent finds that synthetic planner child creation or wait/resume resolution becomes ambiguous without
   it.

2. Whether root rows should retain old plan lifecycle labels anywhere. Recommendation: keep lifecycle details in
   metadata panels or child rows, but keep `Agent.status` on the root equal to the newest child status as required.

3. Whether generated bead/work planning names that contain `-` are considered user-specified. Recommendation: audit and
   either migrate generated base names away from `-` or add a narrow internal-only bypass that cannot be reached by
   `%name`, mobile launch names, or manual TUI rename.
