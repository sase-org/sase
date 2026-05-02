---
create_time: 2026-03-31 23:10:38
status: done
prompt: sdd/prompts/202603/approve_options_improvements.md
---

# Plan: Integrate PR #69 Improvements into PR #70

## Context

PR #70 adds an "approve-with-options" modal that replaces the rigid `c` (commit) keybinding with a new `A` (Options)
modal giving three controls: commit plan, run coder agent, and additional prompt. PR #69 implements the same feature
with a different approach. The previous review selected PR #70 as superior but identified 6 specific improvements from
PR #69 to integrate.

**Prerequisite**: Merge PR #70 first (`gh pr merge 70`), then apply these improvements on top.

## Changes

### 1. TextArea for coder prompt (`approve_options_modal.py`)

Replace the `Input` widget with `TextArea` for the additional coder prompt field. Multi-line input is the right choice
because coder instructions can span multiple lines and may include xprompt references with context.

- Change import from `Input` to `TextArea`
- In `compose()`: replace `yield Input(placeholder=..., id="coder-prompt-input")` with
  `yield TextArea("", id="coder-prompt-input")`
- In `on_switch_changed()`: query `TextArea` instead of `Input`
- In `action_approve()`: use `.text` instead of `.value` to read content

### 2. "Additional instructions:" header (`run_agent_exec_plan.py`)

Format the coder prompt injection with a labeled header instead of bare append. This helps the coder agent understand
the structure.

- Change `coder_extra = f"\n{plan_result.coder_prompt}"` to
  `coder_extra = f"\n\nAdditional instructions:\n{plan_result.coder_prompt}"`

### 3. 3-way status override logic (`_notification_modals.py`)

Fix misleading status when `commit_plan=False, run_coder=False`. Currently PR #70 shows "PLAN COMMITTED" for all
`run_coder=False` cases, but if nothing was committed that's wrong.

Current PR #70 2-way logic:

- `run_coder=True` -> "PLAN APPROVED"
- `run_coder=False` -> "PLAN COMMITTED"

Improved 3-way logic:

- `run_coder=True` -> "PLAN APPROVED" (agent will run)
- `run_coder=False, commit_plan=True` -> "PLAN COMMITTED" (committed but no agent)
- `run_coder=False, commit_plan=False` -> "PLAN APPROVED" (nothing happened beyond approval)

### 4. Unified SDD commit block (`run_agent_exec_plan.py`)

PR #70 leaves SDD commit logic in three separate locations: the no-coder path (line ~278), the epic path (line ~306),
and the coder path (line ~344). Consolidate into a single block that runs after SDD file generation, gated by
`plan_result.commit_plan`.

- After `write_sdd_files()`, compute `should_commit = plan_result.commit_plan if plan_result.action != "epic" else True`
  (epics always need committed SDD files since `#gh` pre-step wipes uncommitted files)
- Run the single commit block gated on `should_commit and sdd_plan_name`
- Remove the three scattered commit blocks
- For the no-coder early return: check `not plan_result.run_coder and plan_result.action != "epic"` instead of
  `plan_result.action == "commit"`

### 5. Type validation in `_plan_utils.py`

Replace bare `.get()` calls with `isinstance` checks for robust parsing of the response JSON.

- `commit_plan`: `isinstance(raw, bool)` with default `True`
- `run_coder`: `isinstance(raw, bool)` with default `True`
- `coder_prompt`: `isinstance(raw, str)` with `.strip()` and empty->None normalization
- Handle backward compat: `action == "commit"` maps to `action="approve", run_coder=False`

### 6. Comprehensive tests (3 files, ~6 new tests)

**`test_axe_run_agent_exec_plan.py`** (3 new tests in `TestModelInheritance` or new class):

- `test_approve_no_coder_commit_true_returns_plan_committed`: `run_coder=False, commit_plan=True` -> outcome
  "plan_committed", `_commit_sdd_files` called
- `test_approve_no_coder_commit_false_skips_commit`: `run_coder=False, commit_plan=False` -> outcome "plan_committed",
  `_commit_sdd_files` NOT called
- `test_approve_prompt_includes_custom_extra_text`: `coder_prompt="#foo\ncustom"` -> "Additional instructions:" appears
  in `state.current_prompt`

**`test_plan_rejection_response.py`** (2 new tests):

- `test_approve_commit_only_writes_options_and_sets_committed_status`: Verify response JSON includes
  `commit_plan`/`run_coder` fields and status override is "PLAN COMMITTED"
- `test_approve_with_prompt_writes_prompt_and_sets_approved_status`: Verify `coder_prompt` appears in response JSON and
  status is "PLAN APPROVED"

**`test_plan_utils.py`** (1 updated test + 1 new test):

- Update `test_handle_plan_approval_commit`: Assert `action="approve", run_coder=False` (backward compat mapping)
- New `test_handle_plan_approval_approve_with_options`: Parse full approve-with-options JSON including `isinstance`
  validation and whitespace trimming of `coder_prompt`
