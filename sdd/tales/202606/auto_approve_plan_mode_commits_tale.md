---
create_time: 2026-06-29 08:55:55
status: done
prompt: sdd/prompts/202606/auto_approve_plan_mode_commits_tale.md
---
# Fix: `%a` (auto plan mode) wrongly approves a tale instead of a plain plan

## Problem statement

When an agent prompt uses the bare `%a` directive (alias for `%auto`, i.e. auto-approval in **plan** mode), the agent's
plan is auto-approved as a **tale** — it is committed to `sdd/tales/YYYYMM/<name>.md`, the agent status reads
**`TALE APPROVED`**, and an SDD git commit is created. The user expected a _normal plan approval_ (no SDD tale commit),
exactly like clicking **Approve** (not **Tale**) in the interactive approval modal.

Observed in agent `09p`: prompt `… #plan %a`, `Auto: ⚡ PLAN`, result `1/1—plan main (TALE APPROVED)` →
`1/1—code (WORKING TALE)`, artifact `sdd/tales/202606/rename_waiting_for_field.md`.

## Root cause

The auto-approval branch in the runner's plan-approval poll loop constructs its result **without** setting
`commit_plan`, so it silently inherits a dataclass default of `True`. For the `approve` action that default is wrong,
and downstream code treats `action == "approve" and commit_plan and run_coder` as a **tale**.

### The exact chain

1. **Directive parse** — bare `%a` → `auto_mode = "plan"` (`src/sase/xprompt/directives.py` ~line 608-618; valid modes
   `("plan", "tale", "epic")` in `src/sase/xprompt/_directive_types.py:38`).

2. **Meta wiring** — `src/sase/axe/run_agent_directives.py` (~lines 237-247): plan mode sets
   `agent_meta["approve"] = True` only (it does **not** set `auto_approve_plan_action`; that is reserved for
   `tale`/`epic`).

3. **Auto action resolution** — `get_auto_plan_approval_action()` (`src/sase/main/plan_approve_handler.py:59-77`) sees
   `meta["approve"]` truthy and returns the string `"approve"`.

4. **THE BUG** — `handle_plan_approval()` in `src/sase/llm_provider/_plan_utils.py` short-circuits on auto-approval at
   **two** return sites and builds the result as:

   ```python
   return PlanApprovalResult(action=auto_action, plan_file=plan_file)
   ```

   - first site ~line 175 (early check), second site ~line 302 (in-poll re-check).
   - `PlanApprovalResult` is defined at `_plan_utils.py:17-27` with **`commit_plan: bool = True`**. Neither auto site
     passes `commit_plan`, so for `auto_action == "approve"` the result carries `commit_plan=True`.

5. **Misclassification → tale** — the runner consumes that result in `src/sase/axe/run_agent_exec_plan_accept.py`:
   - `_accepted_plan_action_for_meta()` (lines 46-55) returns **`"tale"`** because
     `action == "approve" and commit_plan and run_coder` are all true → status shows `TALE APPROVED` (persisted as
     `meta["plan_action"] = "tale"`).
   - `should_commit = plan_result.commit_plan` (lines 265-269) is `True`, so the plan is committed to `sdd/tales/` via
     `plan_kind_for_action("approve")` which falls through to `"tales"`
     (`src/sase/axe/run_agent_exec_plan_sdd.py:247-252`).

### Why the interactive path is correct (the asymmetry that proves the fix)

The interactive modal does **not** rely on the `commit_plan` default. Its choice→protocol table
(`src/sase/ace/tui/modals/plan_approval_modal.py:28-51`) maps:

| choice    | action  | commit_plan | run_coder |
| --------- | ------- | ----------- | --------- |
| `approve` | approve | **False**   | True      |
| `tale`    | approve | True        | True      |
| `epic`    | epic    | True        | True      |
| `legend`  | legend  | True        | True      |

So clicking **Approve** yields `commit_plan=False` → no tale. The auto-approve path is the only one that loses this
distinction. The fix makes the auto path mirror this table: `approve → commit_plan=False`,
`tale`/`epic → commit_plan=True`.

### Scope note (what is NOT the bug)

- The CLI/notification archive path (`src/sase/plan_approval_actions.py`, `_archive_plan_for_approval`) writes an
  `approve` plan copy into `sdd/tales/` by design (codified by `tests/test_plan_rejection_response.py:366-368`). The
  **auto-approve flow never calls that path** — it returns a `PlanApprovalResult` directly to the runner — so it is out
  of scope and must be left unchanged.
- The `#plan` xprompt and `/sase_plan` skill only inject instruction text; they do not cause the tale. The tale comes
  solely from the `commit_plan=True` default.

## Fix

Make the auto-approval result construction set `commit_plan` from the resolved auto action, in
`src/sase/llm_provider/_plan_utils.py`.

1. Add one small private helper that is the single source of truth for the auto-approve result shape:

   ```python
   def _auto_approval_result(auto_action: str, plan_file: str) -> PlanApprovalResult:
       """Build the runner result for an auto-approved plan.

       `%auto`/`%a` plan mode resolves to `auto_action == "approve"` — a plain plan
       approval that must NOT commit an SDD tale, matching the interactive "Approve"
       choice (commit_plan=False). The `tale`/`epic` auto modes do commit, so they keep
       commit_plan=True.
       """
       return PlanApprovalResult(
           action=auto_action,
           plan_file=plan_file,
           commit_plan=auto_action != "approve",
       )
   ```

2. Replace both auto-approve return sites (~line 175 and ~line 302) with
   `return _auto_approval_result(auto_action, plan_file)`.

This changes behavior for exactly one case — auto `approve` now carries `commit_plan=False` — and leaves `tale`/`epic`
(and `run_coder=True`) untouched. After the fix, `%a` produces a plain plan approval: `_accepted_plan_action_for_meta`
returns `"approve"`, `should_commit` is `False`, no `sdd/tales/` commit, status reflects a normal approval, and the
coder follow-up still runs (consistent with interactive **Approve**).

## Tests

Update expectations that currently encode the buggy default, and add a regression guard.

- `tests/test_plan_utils.py`
  - `test_handle_plan_approval_auto_approve` (~line 90-97): expected result must become
    `PlanApprovalResult(action="approve", plan_file=..., commit_plan=False)`.
  - `test_handle_plan_approval_rechecks_auto_approve_while_waiting` (parametrized over `["approve", "tale", "epic"]`,
    ~line 130-159): expected `commit_plan` must be `auto_action != "approve"` (False for `approve`, True for
    `tale`/`epic`).
  - `test_handle_plan_approval_auto_tale_skips_notification` (~line 115-126): unchanged — `tale` keeps
    `commit_plan=True` (default), confirming the fix does not regress tales.
- Add a regression test asserting the end-to-end classification: an auto `approve` result
  (`action="approve", commit_plan=False, run_coder=True`) makes `_accepted_plan_action_for_meta(...)` return `"approve"`
  (not `"tale"`) and yields `should_commit == False`; and that an auto `tale` still classifies as `"tale"`.

## Acceptance criteria

- A prompt with bare `%a` (or `%auto` / `%auto:plan`) auto-approves as a **plain plan**: no `sdd/tales/` file is written
  or committed, agent status is a normal approval (not `TALE APPROVED`), and the coder follow-up still runs.
- `%auto:tale` still commits to `sdd/tales/` and `%auto:epic` still routes to epics — unchanged.
- Interactive **Approve** / **Tale** / **Epic** / **Legend** behavior is unchanged.
- `just check` passes (lint + mypy + tests), including the updated and new tests above.

## Architecture / boundary note

Plan-approval semantics are cross-frontend (TUI modal, `sase plan approve` CLI, runner auto-approve), so per the
Rust-core boundary guidance they are arguably core backend logic. However, the entire current implementation lives in
Python, and this change is a localized correctness fix to a default value — not new domain behavior. A broader follow-up
worth flagging (out of scope here): collapse the three separate choice→(action, commit_plan, run_coder) mappings — the
TUI protocol table, the `_plan_response_json` mapping in `plan_approval_actions.py`, and this auto-approve helper — into
a single shared source of truth (eventually in `sase-core`) so this class of drift cannot recur.
