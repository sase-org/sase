---
create_time: 2026-04-08 17:36:34
status: done
---

# Plan: LLM Model Picker for Approve with Options Modal

## Goal

Add a model picker to the "Approve with Options" modal so users can specify a different LLM provider/model for the coder
agent instead of inheriting the planner's model. Include a "Custom" option that prompts for freeform `provider/model`
input.

## Design

### User Experience

The approve options modal gains a new **Coder model** row between "Run coder agent" and "Additional prompt":

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Approve with Options                         │
│                                                                    │
│  Commit plan                                              [ON]     │
│  Run coder agent                                          [ON]     │
│                                                                    │
│  Coder model:                                                      │
│  ▸ Same as planner                                                 │
│                                                                    │
│  Additional prompt:                                                │
│  none                                                              │
│                                                                    │
│  enter=Approve  space=Toggle  m=Model  p=Edit prompt  q/esc=Back   │
└──────────────────────────────────────────────────────────────────────┘
```

Pressing `m` opens a **ModelPickerModal** stacked on top:

```
┌──────────────────────────────────────┐
│          Select Coder Model          │
│                                      │
│  ▸ Same as planner                   │
│  ── Claude ──────────────────────    │
│    opus                              │
│    sonnet                            │
│    haiku                             │
│  ── Codex ───────────────────────    │
│    o3                                │
│    gpt-5.3-codex                     │
│    ...                               │
│  ── Gemini ──────────────────────    │
│    gemini-2.5-pro                    │
│    ...                               │
│  ─────────────────────────────────   │
│    Custom...                         │
│                                      │
│  enter=Select  q/esc=Cancel          │
└──────────────────────────────────────┘
```

If "Custom..." is selected, a **CustomModelInputModal** (small text input modal) opens:

```
┌──────────────────────────────────────┐
│        Enter Custom Model            │
│                                      │
│  Format: provider/model or model     │
│  ┌──────────────────────────────┐    │
│  │ codex/o3-preview             │    │
│  └──────────────────────────────┘    │
│                                      │
│  enter=Confirm  esc=Cancel           │
└──────────────────────────────────────┘
```

**Behavioral rules:**

- Model row is **disabled** when "Run coder agent" is OFF (same as prompt display)
- `m` key is a no-op when coder is OFF
- Default is "Same as planner" (sends `None` as `coder_model`)
- Model selection persists through the prompt-edit round-trip

### Data Flow

```
ApproveOptionsModal (coder_model field)
  → ApproveOptionsResult.coder_model
  → PlanApprovalResult.coder_model (TUI side)
  → plan_response.json {"coder_model": "codex/o3"}
  → _plan_utils.py reads coder_model from JSON
  → PlanApprovalResult.coder_model (backend side)
  → run_agent_exec_plan.py: overrides model_prefix with coder_model
```

## Implementation

### Phase 1: Model Picker Modal

**New file: `src/sase/ace/tui/modals/model_picker_modal.py`**

- `ModelPickerModal(ModalScreen[str | None])` — returns the selected model string or `None` for "Same as planner".
  Returns the sentinel `"__custom__"` when "Custom..." is selected.
- Uses `OptionList` with `Separator` items for provider groupings
- Model list sourced from `registry._MODEL_TO_PROVIDER` dict (grouped by provider)
- Vim-style navigation via `OptionListNavigationMixin` from `base.py`
- Styled similarly to other selector modals (centered, bordered, auto-height)

**New file: `src/sase/ace/tui/modals/custom_model_input_modal.py`**

- `CustomModelInputModal(ModalScreen[str | None])` — small text input for `provider/model`
- Reuses `_CommandInput` pattern from `command_input_modal.py` for readline bindings
- Validates non-empty input before accepting

### Phase 2: Approve Options Modal Changes

**File: `src/sase/ace/tui/modals/approve_options_modal.py`**

- Add `coder_model: str | None = None` constructor parameter
- Add `_coder_model` instance attribute to track current selection
- Add model display row (Static label + Static display value) between coder switch and prompt
- Add `m` key binding → `action_select_model()`
- `action_select_model()`: if coder is OFF, return early; otherwise push `ModelPickerModal`
- Callback from `ModelPickerModal`: if `"__custom__"`, push `CustomModelInputModal`; otherwise update `_coder_model` and
  refresh display
- Include `coder_model` in `ApproveOptionsResult` and `ApproveOptionsEditPrompt`
- Update `_sync_constraints()` to disable/enable the model row alongside the prompt row
- Update footer hint text to include `m`=Model
- Helper `_model_display_label()` to format the display: `"Same as planner"` for None, `"CLAUDE(opus)"` style for known
  models via `format_provider_model_label()`

### Phase 3: Data Threading (TUI side)

**File: `src/sase/ace/tui/modals/plan_approval_modal.py`**

- Add `coder_model: str | None = None` to `PlanApprovalResult`
- Add `coder_model: str | None = None` to `PendingApproveState`
- Thread `coder_model` through `_push_approve_options()` and `on_options_dismiss()`

**File: `src/sase/ace/tui/actions/agents/_types.py`**

- Add `coder_model: str | None = None` to `ApprovePromptContext`

**File: `src/sase/ace/tui/actions/agents/_notification_modals.py`**

- Include `coder_model` in `response_data` dict written to `plan_response.json`
- Thread `coder_model` through the `ApprovePromptContext` for the prompt-edit round-trip

**File: `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`**

- Thread `coder_model` through `PendingApproveState` in `_handle_approve_prompt_submitted()` and
  `_handle_approve_prompt_cancelled()`

### Phase 4: Data Threading (Backend side)

**File: `src/sase/llm_provider/_plan_utils.py`**

- Add `coder_model: str | None = None` to `PlanApprovalResult`
- Read `coder_model` from `plan_response.json` with type validation (same pattern as `coder_prompt`)

**File: `src/sase/axe/run_agent_exec_plan.py`**

- After line 300 where `model_prefix` is built: if `plan_result.coder_model` is set, override `model_prefix` with
  `f"%model:{plan_result.coder_model}\n"` instead of using `ctx.agent_model`
- The existing `has_model_directive()` check on `coder_prompt` still applies (user's custom prompt directive takes
  highest priority)

### Phase 5: Styling

**File: `src/sase/ace/tui/styles.tcss`**

- Style for model display row (consistent with prompt display row)
- Style for `ModelPickerModal` (centered, auto-height, bordered)
- Style for `CustomModelInputModal` (small centered input modal)

### Phase 6: Tests

**File: `tests/test_approve_options_modal.py`**

- `test_m_key_opens_model_picker` — pressing `m` pushes model picker
- `test_m_key_no_op_when_coder_off` — `m` does nothing when coder switch is OFF
- `test_model_selection_updates_display` — selecting a model updates the display label
- `test_model_persists_through_approve` — `coder_model` included in `ApproveOptionsResult`
- `test_model_persists_through_edit_prompt` — `coder_model` included in `ApproveOptionsEditPrompt`
- `test_initial_model_restoration` — constructor param restores model display
- `test_coder_off_disables_model_display` — model row disabled when coder is OFF

**New file: `tests/test_model_picker_modal.py`**

- `test_model_picker_returns_none_for_default` — "Same as planner" returns `None`
- `test_model_picker_returns_model_string` — selecting a model returns its name
- `test_model_picker_returns_custom_sentinel` — "Custom..." returns `"__custom__"`
- `test_model_picker_navigation` — vim keys work for navigation
- `test_model_picker_escape_cancels` — escape returns `None`
