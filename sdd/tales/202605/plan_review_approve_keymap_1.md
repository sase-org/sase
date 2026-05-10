---
create_time: 2026-05-10 11:43:43
status: done
prompt: sdd/prompts/202605/plan_review_approve_keymap_1.md
---
# Plan: Plan Review `a`/`t` Keymap Swap and New Approve Action

## Context

The Plan Review modal (`PlanApprovalModal` in `src/sase/ace/tui/modals/plan_approval_modal.py`) currently binds the `a`
key to an action labeled "Tale". The handler `action_approve()` actually returns the `tale` choice — committing the plan
into `sdd/tales/` and launching the coder. This makes the modal inconsistent with the sibling custom approval modal
(`ApproveOptionsModal`), which already exposes the intuitive direct mapping `a=Approve, t=Tale, e=Epic, l=Legend`.

The system supports four product-level approval choices, all with distinct behavior driven by
`approval_protocol_for_choice()`:

| Choice    | Commit plan?            | Follow-up              |
| --------- | ----------------------- | ---------------------- |
| `approve` | No SDD commit           | Run coder              |
| `tale`    | Commit to `sdd/tales`   | Run coder              |
| `epic`    | Commit to `sdd/epics`   | Launch `bd/new_epic`   |
| `legend`  | Commit to `sdd/legends` | Launch `bd/new_legend` |

The pure-`approve` path — approve and run the coder without persisting the plan as an SDD document — is currently only
reachable from the main Plan Review panel via the `c` (Custom) sub-modal. This plan exposes it as a top-level keymap and
corrects the misleading naming of the existing handler.

A WIP tale at `sdd/tales/202605/plan_review_approve_keymap.md` already documents the same intent; this plan is the
implementation-side breakdown.

## Goals

1. Make `a` mean "Approve" and `t` mean "Tale" on the Plan Review panel, matching the conventions of the custom approval
   sub-modal.
2. Stop overloading `action_approve()` to mean "tale". Add a dedicated `action_tale()` for the tale path so the action
   name matches the choice it produces.
3. Keep all downstream protocol and runner code unchanged. The user-visible difference is purely the key binding plus a
   new direct path to the existing `"approve"` choice.

## Non-Goals

- Do not change `PlanApprovalChoice`, `approval_protocol_for_choice`, or the `PlanApprovalResult` shape.
- Do not change the custom approval modal (`ApproveOptionsModal`) — it already maps `a → approve` and `t → tale`
  correctly.
- Do not change auto-approve behavior (`SASE_AGENT_AUTO_APPROVE_PLAN_ACTION`); its accepted values (`"approve"`,
  `"epic"`) already align with the new direct keymaps.
- Do not introduce a new approval choice or alter consequence text.

## Implementation Sketch

### 1. `src/sase/ace/tui/modals/plan_approval_modal.py`

- In the `BINDINGS` list:
  - Replace `("a", "approve", "Tale")` with two entries:
    - `("a", "approve", "Approve")`
    - `("t", "tale", "Tale")`
- Update the `hints` markup string in `compose()` so the footer renders
  `[green]a[/green]=Approve  [green]t[/green]=Tale  …` in place of the current `[green]a[/green]=Tale`. Other hints are
  unchanged.
- Repurpose `action_approve()`:
  - New body: `self.dismiss(plan_approval_result_for_choice("approve"))`.
  - Update its docstring to "Approve the plan without an SDD commit."
- Add a new `action_tale()` that does what `action_approve()` did before:
  - `self.dismiss(plan_approval_result_for_choice("tale"))`.
  - Docstring: "Approve the plan as an SDD tale."

The pure-`approve` path produces a `PlanApprovalResult` with `action="approve"`, `commit_plan=False`, `run_coder=True`,
and `choice="approve"` — derived through the existing `plan_approval_result_for_choice("approve")` helper, no new code
paths.

### 2. Tests

- `tests/test_plan_approval_modal_title.py` (or a new sibling file if cleaner) — add focused tests for the modal action
  layer:
  - `action_approve()` dismisses with a result whose `choice == "approve"`, `commit_plan is False`, `run_coder is True`,
    `action == "approve"`.
  - `action_tale()` dismisses with a result whose `choice == "tale"`, `commit_plan is True`, `run_coder is True`,
    `action == "approve"`.
  - Static assertion that `BINDINGS` contains both `("a", "approve", "Approve")` and `("t", "tale", "Tale")` and does
    NOT contain the old `("a", "approve", "Tale")` row.

  Use Textual's existing `App.run_test()` harness pattern already used elsewhere in the repo for modal tests, or, if
  simpler, instantiate the modal in isolation and patch `dismiss` to capture the result without spinning a full app.

- Audit `tests/` for any other place that asserts on the previous `("a", "approve", "Tale")` binding or that pushes the
  `a` key to the Plan Review modal expecting tale behavior, and update accordingly.

### 3. Documentation alignment

- The existing tale `sdd/tales/202605/plan_review_approve_keymap.md` is already the canonical SDD record for this
  change; no new SDD doc is needed.
- No `default_config.yml` changes — these bindings live in the modal class, not the app keymap config.
- No `keybinding_footer.py` changes — Plan Review modal bindings are not conditional and are surfaced via the modal's
  own footer string.
- No help-modal updates required because Plan Review modal bindings are not part of the global help popup.

## Risk and Edge Cases

- **Muscle memory.** Anyone hitting `a` expecting "tale" will now get "approve" (no SDD commit). The behavioral delta is
  `commit_plan` flipping from `True` to `False`. Acceptable: the new mapping matches the custom modal and the documented
  product intent.
- **Auto-approve semantics.** `SASE_AGENT_AUTO_APPROVE_PLAN_ACTION` and `agent_meta.auto_approve_plan_action` already
  use the value `"approve"` for the no-SDD-commit path and `"epic"` for the epic path. Adding the keymap does not affect
  them.
- **Other callers of `action_approve()`.** `Grep` shows the method is not invoked outside the modal itself, so the
  semantic change is local. `action_approve_options` (the back-compat alias for the old "Custom" binding) is independent
  and is left untouched.

## Validation

1. `just install` (workspace may be stale).
2. Run targeted tests:
   - `just test tests/test_plan_approval_modal_title.py`
   - Any added test module covering the new `action_tale()` and the new binding shape.
3. `just check` per the repo guideline whenever Python source changes.
4. Manual TUI smoke test: open a Plan Review modal, confirm:
   - `a` triggers Approve (no `sdd/tales/...` file is created; coder spawns).
   - `t` triggers Tale (a file is created under `sdd/tales/<YYYYMM>/`; coder spawns).
   - Footer hint reads `a=Approve  t=Tale  …`.
