---
create_time: 2026-05-09 19:34:27
status: done
prompt: sdd/prompts/202605/plan_approval_custom_model_picker.md
bead_id: sase-2l
tier: epic
---
# Plan: Plan Approval Custom Actions And Model Picker Upgrade

## Goal

Replace the plan approval modal's `A` Options flow with a `c` Custom flow that lets the user choose the approval outcome
directly: Approve, Tale, Epic, or Legend. While doing that, substantially improve the coder-model picker by adding a
filter input, apostrophe jump behavior matching other TUI panels, and visually distinct provider/model styling.

This plan is split into phases intended for separate agent instances. Phases should run sequentially because later UI
work depends on the action semantics and modal contracts stabilized earlier.

## Product Semantics

Use the existing protocol where possible, but make the user-facing choices explicit:

- Approve: approve the plan and run the coder without committing a generated SDD tale. This is today's no-commit run
  path: `action="approve"`, `commit_plan=false`, `run_coder=true`.
- Tale: approve the plan as a normal SDD tale, commit/archive it through the existing `sdd/tales` path, then run the
  coder. This is `action="approve"`, `commit_plan=true`, `run_coder=true`.
- Epic: keep the existing `action="epic"` behavior, forcing the SDD epic plan to be committed and launching
  `bd/new_epic`.
- Legend: keep the existing `action="legend"` behavior, forcing the SDD legend plan to be committed and launching
  `bd/new_legend`.

The old "commit plan" toggle should disappear from the custom modal because the selected action now determines commit
behavior. The existing "run coder agent" toggle should also be removed from this modal unless a product requirement
reintroduces a separate "Commit only" action; the four requested choices do not include commit-only.

Keep response-file backward compatibility:

- Continue writing `action="approve"` for both Approve and Tale.
- Distinguish Approve vs Tale through `commit_plan=false/true`.
- Continue accepting existing `commit` responses in `_plan_utils.py` for older pending notifications or external
  transports.

## Current Code Map

- `src/sase/ace/tui/modals/plan_approval_modal.py`
  - Top-level modal currently binds `a` to Tale, `A` to Options, `E` to Epic, and `L` to Legend.
  - `PlanApprovalResult` still carries `commit_plan`, `run_coder`, `coder_prompt`, and `coder_model`.
  - `PendingApproveState` reopens `ApproveOptionsModal` after prompt editing.
- `src/sase/ace/tui/modals/approve_options_modal.py`
  - Current options modal owns the commit/run switches, model picker launch, and prompt edit round-trip sentinel.
- `src/sase/ace/tui/modals/model_picker_modal.py`
  - Current model picker is an unfiltered `OptionList` grouped by provider.
- `src/sase/ace/tui/actions/agents/_notification_modals.py`
  - Converts `PlanApprovalResult` into `plan_response.json`, visible status overrides, persisted approval markers, and
    best-effort SDD archive updates.
- `src/sase/axe/run_agent_exec_plan.py`
  - Runner consumes `commit_plan`, `run_coder`, `coder_prompt`, and `coder_model`.
- `src/sase/llm_provider/_plan_utils.py`
  - Polls and validates `plan_response.json`; must preserve old response compatibility.
- `src/sase/ace/tui/actions/navigation/jump_hints.py` and `NotificationOptionMixin`
  - Existing apostrophe semantics: enter jump mode, show hint markers, `'` jumps to the last selection when possible or
    the first row otherwise.
- `src/sase/ace/tui/styles.tcss`
  - Contains existing styles for plan approval, approve options, model picker, and modal filter inputs.

## Phase 1: Stabilize The Approval Action Contract

Owner: one agent. Write scope: plan approval dataclasses, response construction, runner-facing tests, and narrow docs
near the touched code.

Purpose: make the four requested actions explicit in Python without doing the larger modal redesign yet.

Concrete work:

1. Introduce a small internal action-choice model near the approval modal code, for example:
   - `PlanApprovalChoice` literals or constants for `approve`, `tale`, `epic`, `legend`.
   - A helper that maps a choice to the existing response protocol:
     - `approve` -> `action="approve"`, `commit_plan=false`, `run_coder=true`;
     - `tale` -> `action="approve"`, `commit_plan=true`, `run_coder=true`;
     - `epic` -> `action="epic"`, `commit_plan=true`, `run_coder=true`;
     - `legend` -> `action="legend"`, `commit_plan=true`, `run_coder=true`.
2. Keep `PlanApprovalResult.action` compatible with current runner actions. If a separate `choice` field is added, make
   it optional and do not require `_plan_utils.py` to understand it.
3. Update `_build_plan_approval_response()` and status/persist helpers in `_notification_modals.py` so they can display
   and persist the chosen semantics clearly:
   - Approve/no-commit should show a distinct status such as `PLAN APPROVED`.
   - Tale/commit should show a distinct status such as `TALE APPROVED`.
   - Existing commit-only status behavior can stay as backward compatibility only.
4. Add or update focused tests covering the mapping and serialization:
   - Approve writes `commit_plan=false` and `run_coder=true`.
   - Tale writes `commit_plan=true` and `run_coder=true`.
   - Epic/Legend still write their existing actions and force committed SDD paths in the runner.
   - Old `commit` response compatibility in `_plan_utils.py` still maps to approve with `run_coder=false`.

Validation:

- `pytest tests/test_plan_utils.py tests/test_axe_run_agent_exec_plan_followups.py tests/test_axe_run_agent_exec_plan_epic_refs.py`

## Phase 2: Replace `A` Options With `c` Custom In The Plan Approval Modal

Owner: one agent. Write scope: `PlanApprovalModal`, approve/custom modal code, prompt-edit round-trip contexts, related
tests, and `src/sase/default_config.yml` only if a configurable keymap entry exists or is introduced.

Purpose: deliver the requested approval UX while preserving the existing prompt and model customizations.

Concrete work:

1. Change the top-level plan approval binding and footer:
   - Remove `("A", "approve_options", "Options")`.
   - Add `("c", "custom", "Custom")`.
   - Keep direct shortcuts for fast paths if desired: `a` can remain Tale, `E` Epic, `L` Legend, and `r/f/e/y/Y` keep
     existing behavior.
2. Rename or repurpose `ApproveOptionsModal` into a custom approval modal. A full class rename is optional; if renamed,
   leave import aliases if tests or external code rely on the old class name.
3. Replace the commit/run switches with a compact, keyboard-friendly choice control:
   - Four fixed actions: Approve, Tale, Epic, Legend.
   - Stable keymaps inside the modal, for example `a`, `t`, `e`, `l`, plus `enter` for the highlighted/default action.
   - Highlight the current choice and show one-line consequences: no SDD commit for Approve, `sdd/tales` for Tale,
     `sdd/epics` for Epic, `sdd/legends` for Legend.
4. Preserve useful customizations:
   - Additional coder prompt editing via existing PromptInputBar round-trip.
   - Coder model selection via the improved `ModelPickerModal`.
   - Prompt/model controls should be disabled or hidden only if a selected action truly will not run a coder. Under the
     four-action model above, all four follow up with some agent, so model selection stays relevant.
5. Update `PendingApproveState`, `ApprovePromptContext`, and prompt submit/cancel handling so the selected action
   survives prompt editing, not just commit/run booleans.
6. Add focused Textual tests:
   - `c` opens the custom modal from `PlanApprovalModal`.
   - Choosing Approve/Tale/Epic/Legend returns the expected `PlanApprovalResult`.
   - Prompt edit cancellation restores the selected action, prompt, and model.
   - Printable keys inside the modal remain event barriers and do not leak into app custom modes.

Validation:

- `pytest tests/test_plan_approval_modal_title.py tests/test_approve_options_modal_model.py tests/ace/tui -k 'plan or approve'`

## Phase 3: Refactor Model Picker Data And Filtering

Owner: one agent. Write scope: `model_picker_modal.py`, modal base/filter helpers if needed, styles for the filter
input, and `tests/test_model_picker_modal.py`.

Purpose: add provider/model filtering on top of a cleaner option model before jump hints and final styling are layered
on.

Concrete work:

1. Replace the raw `list[Option | None]` builder with an internal list of typed rows:
   - default row (`Same as planner`) when enabled;
   - provider header rows;
   - model rows with provider, display label, and model id;
   - custom row.
2. Add a `FilterInput` at the top of `ModelPickerModal`:
   - Filtering should match provider names, model ids, provider/model labels, and short aliases from
     `model_short_alias_map()`.
   - Provider headers remain visible when any of their models match.
   - Matching a provider name with no specific model term should show all models for that provider.
   - `Same as planner` and `Custom...` remain available unless the filter clearly excludes them; if in doubt, keep them
     visible for low-friction escape hatches.
3. Keep keyboard ergonomics:
   - On mount, focus the filter input, while `j/k`, arrows, `ctrl+n/ctrl+p`, and enter operate on the option list.
   - Typing printable characters edits the filter input.
   - Escape first clears the filter if non-empty; otherwise it cancels.
4. Preserve return values exactly:
   - default returns `None`;
   - custom returns `CUSTOM_SENTINEL`;
   - known models return the model id string.
5. Add tests for:
   - filtering by provider;
   - filtering by model substring;
   - filtering by alias;
   - no-results rendering;
   - selection remains valid after filter changes;
   - `include_default_option=False` behavior remains correct for temporary override callers.

Validation:

- `pytest tests/test_model_picker_modal.py tests/llm_provider/test_temporary_override.py`

## Phase 4: Add Apostrophe Jump Mode To The Model Picker

Owner: one agent. Write scope: `model_picker_modal.py`, possible shared jump helper extraction, and model picker tests.

Purpose: make the model picker behave like other panels when the user presses `'`.

Concrete work:

1. Add an apostrophe binding to `ModelPickerModal`, using the same `JUMP_HINT_CHARS`, `build_jump_hint_maps()`, and
   `normalize_jump_key()` helper as the app and notification modal.
2. Behavior should match existing panels:
   - Pressing `'` enters jump mode and overlays hint markers on currently visible selectable rows.
   - Pressing a hint selects/highlights that row and exits jump mode.
   - Pressing `'` while in jump mode jumps back to the last selected row when there is one; otherwise it targets the
     first visible selectable row.
   - Escape exits jump mode without changing the filter or selected row.
   - Invalid keys exit jump mode without selection.
3. Rebuild visible options with hint markers without changing option ids.
4. Ensure filtering and jump mode cooperate:
   - Refiltering clears jump mode and hint maps.
   - Hidden rows never receive stale hints.
   - The highlighted row remains on a visible selectable option after filtering.
5. Add tests for:
   - hint assignment order over filtered rows;
   - apostrophe-to-first behavior;
   - apostrophe-back behavior;
   - uppercase hint normalization;
   - clearing hints after filter changes.

Validation:

- `pytest tests/test_model_picker_modal.py tests/ace/tui/test_jump_to_entry_hints.py`

## Phase 5: Provider And Model Styling Polish

Owner: one agent. Write scope: model picker rendering, provider style helpers, `styles.tcss`, and visual/snapshot-like
unit tests that inspect Rich text styles where practical.

Purpose: make each provider and its models visually distinct without compromising scan density.

Concrete work:

1. Centralize provider styling in one helper shared by the model picker and the plan approval title badge where
   practical:
   - Start from `provider_cli_status_color_map()` for plugin-driven colors.
   - Provide distinctive fallback palettes for built-ins: Claude, Codex/OpenAI, Gemini, Qwen, OpenCode.
   - Keep unknown providers readable with a neutral fallback.
2. Render provider headers with strong provider color, a subtle rule/glyph, and model count.
3. Render model rows with:
   - hint marker, if active;
   - model id;
   - optional provider/model alias in a dim secondary style;
   - selected/highlighted row still readable under Textual's option highlight.
4. Avoid an over-decorated UI:
   - No large cards inside the modal.
   - Dense rows, stable heights, no layout shifting as hints/filter text appear.
   - Colors should be distinctive across providers, not a one-hue palette.
5. Add tests for deterministic style selection and provider grouping. Manual verification should include opening the
   modal with enough providers to confirm the visual hierarchy is clear.

Validation:

- `pytest tests/test_model_picker_modal.py tests/test_plan_approval_modal_title.py`

## Phase 6: Integration, Compatibility Sweep, And Final Checks

Owner: one final integration agent. Write scope: bug fixes only, stale docs/tests, and final verification notes.

Purpose: catch seams between phases, protocol compatibility issues, and stale user-facing references.

Concrete work:

1. Search for stale key labels and modal copy:
   - `A=Options`
   - `Approve Options`
   - `Commit plan`
   - `Run coder agent`
   - `m=Model` and old model picker footer text that omits filtering or apostrophe behavior.
2. Search for protocol-sensitive code before changing it:
   - `commit_plan`
   - `run_coder`
   - `action == "commit"`
   - `action == "approve"` Keep compatibility paths unless a test proves they are dead.
3. Verify default config/keymap docs:
   - If plan approval modal bindings are hard-coded only, no config change is needed.
   - If a keymap registry entry is added for this modal, update `src/sase/default_config.yml` in the same phase.
4. Run focused tests from all phases, then the repo-required check:
   - `just install`
   - `pytest tests/test_model_picker_modal.py tests/test_approve_options_modal_model.py tests/test_plan_approval_modal_title.py tests/test_plan_utils.py tests/test_axe_run_agent_exec_plan_followups.py tests/test_axe_run_agent_exec_plan_epic_refs.py`
   - `just check`
5. Manually smoke-test in `sase ace` if possible:
   - Plan review modal shows `c=Custom`, not `A=Options`.
   - Custom modal can produce Approve, Tale, Epic, Legend.
   - Model picker filters by provider/model/alias.
   - `'` jump mode works in the filtered and unfiltered model list.

## Risks And Guardrails

- Do not rename the wire action `approve`; it is consumed by runner code and external transports.
- Do not remove `commit_plan` or `run_coder` from the response parser. They remain part of the compatibility protocol
  even if the TUI no longer exposes them as switches.
- Be careful with `None` from `ModelPickerModal`: it currently means both cancel and "Same as planner" in callers with
  default semantics. Existing behavior should remain unless a phase intentionally introduces a richer result type and
  updates all callers.
- Textual `OptionList` disabled headers and separators can make index arithmetic fragile. Tests should select by option
  id rather than raw index whenever possible.
- The model picker touches shared provider metadata. Treat all runtimes uniformly; do not hard-code assumptions that one
  runtime lacks hooks, skills, or model support.
- If phases rename `ApproveOptionsModal`, preserve aliases until downstream tests and imports are updated.
