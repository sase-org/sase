---
create_time: 2026-03-31 21:40:26
status: done
---

# Plan: Plan Approval Options Modal (`A` key) replacing direct `c` commit path

## Goal

Replace the current `c` (commit) action from the plan approval panel with a new `A` (approve with options) flow that is
intuitive, reliable, and visually clear.

The new flow must let users configure, in one modal over the plan panel:

1. whether to commit the plan to the project repo (or `.sase/sdd/` when `sdd.version_controlled` is false),
2. whether to run the coder agent,
3. extra arbitrary prompt text (including xprompts) to inject into the coder prompt.

## Product / UX Design

### Existing behavior to preserve

- `PlanApprovalModal` remains the primary plan review screen.
- `q` still closes the top modal. If the user is inside options, `q` returns to plan review (because options is pushed
  on top of it).
- Existing actions (`a`, `r`, `f`, `e`, `E`, copy keys) continue to work.

### New interaction model

- Remove `c` action from plan review modal.
- Add `A` action: “Approve w/ options”.
- Pressing `A` opens a new `PlanApprovalOptionsModal` atop the plan review modal.

### Options modal layout

A compact, form-like modal with:

- Title and plan filename context.
- Boolean toggle: `Commit plan artifacts` (default ON).
- Boolean toggle: `Run coder agent` (default ON).
- Multi-line text area: `Additional coder prompt` (default empty).
- Footer hints:
  - `Enter` submit
  - `Space` toggle focused boolean
  - `Tab` cycle fields
  - `q` cancel/back

### Submission semantics

- Submit returns a result object with:
  - action = `approve`
  - options payload:
    - `commit_plan: bool`
    - `run_coder: bool`
    - `coder_prompt_extra: str` (trimmed; optional)

## Runtime / Data Contract Design

### Response file schema

`plan_response.json` for option-based approvals includes:

- `action: "approve"`
- `commit_plan: bool` (default true if absent)
- `run_coder: bool` (default true if absent)
- `coder_prompt_extra: string` (optional)

Backward compatibility:

- Keep accepting legacy `action: "commit"` responses.
- Keep accepting plain `action: "approve"` with no option keys (treated as all defaults).

### Plan approval result object

Extend `sase.llm_provider._plan_utils.PlanApprovalResult` with optional fields:

- `commit_plan: bool = True`
- `run_coder: bool = True`
- `coder_prompt_extra: str | None = None`

When reading `plan_response.json`, parse optional keys and populate this struct.

## Execution Semantics in `handle_plan_marker`

### SDD file handling

- SDD files are still generated before branching behavior.

### Commit decision

- Determine `should_commit_plan` from result:
  - legacy `action == "commit"` => true and run_coder=false behavior remains.
  - `action == "approve"` + `commit_plan` flag controls commit behavior.
- If `should_commit_plan` is true:
  - version-controlled path: `_commit_sdd_files(...)`
  - non-version-controlled path: `commit_sdd_files(...)`
- If false: skip commit steps.

### Coder launch decision

- If `run_coder` is false (or legacy `commit` action): return `"plan_committed"` after optional commit work.
- If true: continue to spawn `.code` follow-up agent.

### Prompt injection

When spawning coder for approve path:

- Keep current baseline:
  - optional model prefix
  - optional vcs prefix
  - `@<plan_file>`
  - “The above plan ... Implement it now.”
- If `coder_prompt_extra` is non-empty, append:
  - blank line
  - `Additional instructions:`
  - raw text block (unchanged so xprompts are preserved).
- Keep embedded workflow refs appended at end.

## TUI Notification handling updates

Update `handle_plan_approval` modal callback pipeline:

- Accept enriched modal result payload.
- Write response JSON keys for option-based approve.
- Status override logic:
  - If `approve` with `run_coder == false` and `commit_plan == true`: set `PLAN COMMITTED`.
  - If `approve` with `run_coder == true`: set `PLAN APPROVED`.
  - If `approve` with `run_coder == false` and `commit_plan == false`: set `PLAN APPROVED` (no follow-up run; still
    approved outcome).
- Persist action metadata with compatibility:
  - For “commit and don’t run coder”, persist plan action as `commit` (so existing status loaders continue to show
    `PLAN COMMITTED`).

## Styling / Visual quality

Add new styles in `styles.tcss` for options modal:

- Distinct bordered container matching plan modal palette.
- Clear label hierarchy and muted helper text.
- Inputs with high-contrast focus state.
- Balanced spacing to avoid cramped form UX.

## Tests

### Update tests for plan utils

- `tests/test_plan_utils.py`
  - add/adjust test for parsing approve + options from `plan_response.json`.
  - keep legacy commit parsing test.

### Add focused TUI behavior tests

- New tests for options result handling in notification callback:
  - approve with `{commit_plan: true, run_coder: false}` writes expected response and sets committed status path.
  - approve with prompt extra writes `coder_prompt_extra`.

### Update execution tests

- `tests/test_axe_run_agent_exec_plan.py`
  - add tests for `run_coder=False` path returning `plan_committed` while preserving commit toggle behavior.
  - add tests that coder prompt includes appended custom text when provided.

## Implementation order

1. Introduce new options modal + result dataclass.
2. Wire `A` key in plan modal and remove `c`.
3. Thread options through notification response writing.
4. Extend plan approval response parsing in `_plan_utils`.
5. Apply execution semantics in `run_agent_exec_plan`.
6. Add/update tests.
7. Run `just install` then `just check`.

## Risks and mitigations

- Risk: changing status labels unexpectedly.
  - Mitigation: preserve legacy `plan_action=commit` persistence where commit-only outcome is selected.
- Risk: external responders still sending old payloads.
  - Mitigation: keep legacy `commit` action accepted and defaults for missing option keys.
- Risk: prompt formatting regressions.
  - Mitigation: append section only when extra text is non-empty and cover with tests.
