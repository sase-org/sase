---
create_time: 2026-04-08 10:56:00
status: done
---

# Plan: Add Coder Provider/Model Picker to Approve With Options

## Goal

Add a new provider/model picker to the **Approve with Options** modal so users can run the coder with a different model
than the planner by default, with an explicit **Custom** path that delegates entry to `PromptInputBar` using
`<provider>/<model>` syntax.

## Product Design

### Default behavior

- Keep existing behavior as default: coder inherits planner model.
- Picker default option is **Same as planner** (include current planner provider/model in label when available).
- No behavior change if user ignores the picker.

### Picker behavior

- Add a dropdown row in `ApproveOptionsModal` named `Coder model`.
- Options are:
  - `Same as planner (...)` (default)
  - A curated set of known provider/model pairs derived from LLM registry metadata
  - `Custom...`
- If coder switch is OFF, disable/gray out the model row (like prompt row).

### Custom behavior

- Selecting `Custom...` immediately exits modal with sentinel action.
- Caller mounts `PromptInputBar(mode="approve_model")`.
- User enters `<provider>/<model>`.
- Validation:
  - must contain exactly one provider segment and one model segment split by `/`
  - no whitespace
  - provider must be a registered provider name
- On valid submit, reopen plan approval -> options modal with preserved toggles/prompt and selected custom model.
- On cancel, reopen with previous model selection untouched.

## Architecture

### End-to-end data flow

1. `ApproveOptionsModal` emits result with `coder_model` (or sentinel for custom edit)
2. `PlanApprovalModal` forwards `coder_model` in `PlanApprovalResult`
3. Notification handler writes `coder_model` into `plan_response.json`
4. `_plan_utils.handle_plan_approval` parses and validates `coder_model`
5. `run_agent_exec_plan.handle_plan_marker` uses `coder_model` to compute `%model:` prefix for coder agent

### Precedence rules

1. If picker is `Same as planner` -> inherit planner model (existing behavior)
2. If picker has explicit value -> prepend `%model:<provider/model>` for coder
3. If additional coder prompt includes `%model`/`%m`, it still wins (existing override behavior): drop inherited/picked
   model prefix to avoid duplicate model directives

## Implementation Scope

### 1) Modal models and UI

Files:

- `src/sase/ace/tui/modals/approve_options_modal.py`
- `src/sase/ace/tui/styles.tcss`

Changes:

- Extend dataclasses with `coder_model`.
- Add `ApproveOptionsEditModel` sentinel dataclass.
- Add constructor args for planner model label + initial coder model.
- Add `Select` dropdown row for coder model.
- Implement disabled styling/behavior tied to `run_coder` switch.
- Wire `Select.Changed` to trigger custom sentinel when `Custom...` is selected.

### 2) Plan approval state plumbing

Files:

- `src/sase/ace/tui/modals/plan_approval_modal.py`
- `src/sase/ace/tui/actions/agents/_types.py`
- `src/sase/ace/tui/actions/agents/_notification_modals.py`
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`
- `src/sase/ace/tui/widgets/prompt_input_bar.py`

Changes:

- Extend `PlanApprovalResult` and `PendingApproveState` with `coder_model`.
- Add action `approve_model_edit` for custom model round-trip.
- Add `ApproveModelContext` parallel to `ApprovePromptContext`.
- Add prompt-bar mode `approve_model` (title/placeholder/subtitle).
- Add submit/cancel handlers that validate model string and reopen modal with restored state.

### 3) Registry helper for picker options

File:

- `src/sase/llm_provider/registry.py`

Changes:

- Add small public helpers for:
  - registered provider names
  - known provider/model choices for UI (deduped, sorted, stable)
- Reuse existing mapping as source of truth to avoid drift.

### 4) Response + runtime handling

Files:

- `src/sase/llm_provider/_plan_utils.py`
- `src/sase/axe/run_agent_exec_plan.py`

Changes:

- Parse/trim `coder_model` from plan response with validation fallback.
- Build model prefix from `plan_result.coder_model` first, else planner model.
- Preserve existing `%model` directive collision handling with custom prompt.

## Test Plan

### Modal tests

File: `tests/test_approve_options_modal.py`

- verify result includes `coder_model`
- verify constructor restores model selection
- verify coder-off disables model row
- verify selecting `Custom...` dismisses with `ApproveOptionsEditModel`

### Plan response tests

Files:

- `tests/test_plan_utils.py`
- `tests/test_plan_rejection_response.py`

Add coverage for:

- `coder_model` round-trip in `plan_response.json`
- parsing/trim/validation behavior in `_plan_utils`

### Prompt construction tests

File: `tests/test_axe_run_agent_exec_plan.py`

- when `coder_model` set, coder prompt starts with `%model:<provider/model>`
- custom prompt model directive still suppresses inherited/picked prefix

### Registry helper tests

File: new or existing llm provider tests

- known picker options include expected provider/model entries
- provider list aligns with registry

## Validation & Quality Gates

- Run `just install` first in this ephemeral workspace
- Run targeted pytest for touched behavior during iteration
- Run full required check at the end: `just check`

## Non-goals

- No changes to planner agent model selection
- No runtime-specific branching per provider
- No CLI flag changes
