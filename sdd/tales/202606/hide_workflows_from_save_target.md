---
create_time: 2026-06-25 09:40:47
status: done
prompt: sdd/prompts/202606/hide_workflows_from_save_target.md
---
# Plan: Hide YAML workflows from the "Save draft as xprompt" target list

## 1. Goal

When the user saves the current prompt draft as an xprompt (`gx` / `<ctrl+g>x`), the **"Save draft as xprompt"** picker
(`XPromptSaveTargetModal`) currently lists **every** known xprompt, including multi-step `.yml` **workflows**. Those
workflow rows are shown **disabled/dimmed** with the inline reason `(workflow - can't overwrite with a prompt draft)`.

The user wants these YAML workflows **removed from the list entirely** — not shown as disabled rows — because a prompt
draft written in the UI can never overwrite a multi-step workflow, so listing them only adds noise.

After this change, the save-target picker shows only `➕ Create new xprompt…` plus the **overwritable** xprompts
(single-step "simple" xprompts backed by a `.md` file or a config `xprompts:` entry). Multi-step workflows never appear.

## 2. Scope clarification (which list this is)

"YAML workflows" here means xprompt **workflows** in the project's glossary sense: a `.yml` file that expands to
multiple steps, i.e. `Workflow.is_simple_xprompt()` is `False`. The decisive signal in the request — "these can't be
overwritten by a prompt that was written in the UI so they shouldn't be shown at all" — matches exactly the disabled
rows produced today in `XPromptSaveTargetModal` (`load_xprompt_save_rows` →
`disabled_reason = "workflow - can't overwrite with a prompt draft"`).

This change is confined to that one picker:

- **In scope:** `XPromptSaveTargetModal` / `load_xprompt_save_rows`
  (`src/sase/ace/tui/modals/xprompt_save_target_modal.py`).
- **Out of scope (intentionally unchanged):**
  - `XPromptLocationModal` (the "where to create a new xprompt" picker) — it lists writable **directories and config
    files**, never individual workflow `.yml` files, so it has nothing to remove.
  - The XPrompt **Browser** (browse/run xprompts) — workflows are valid, runnable entries there.
  - **Read-only simple xprompts** (e.g. built-in/package `.md` xprompts) — these are simple xprompts that just happen to
    be unwritable; they are a different category from workflows and are left displayed-but-disabled exactly as today.
    (If the user also wants those hidden, that's a small follow-up; this plan does not assume it.)

## 3. Designed behavior

`load_xprompt_save_rows` builds one `_XPromptSaveRow` per known prompt. The change: **skip any prompt whose workflow is
not a simple xprompt** before a row is ever created. Concretely, prompts where `workflow.is_simple_xprompt()` is `False`
are filtered out and contribute no row, no group header, and no preview.

Consequences:

- The list contains `➕ Create new xprompt…` (pinned first, unchanged) followed only by simple xprompts grouped by
  source category. Any source category that contained **only** workflows simply no longer appears (group headers are
  built from the filtered rows, so no empty headers are produced).
- Filtering, navigation (skip headers + disabled), preview, and selection logic are otherwise unchanged. Disabled rows
  can still exist for read-only simple xprompts, and navigation continues to skip them.

## 4. Implementation

All paths repo-relative.

### 4.1 Core change — `src/sase/ace/tui/modals/xprompt_save_target_modal.py`

- In `load_xprompt_save_rows`, after merging `get_all_prompts` + `get_all_project_local_prompts`, **skip non-simple
  workflows** in the build loop:

  ```python
  for name, workflow in prompts.items():
      if not workflow.is_simple_xprompt():
          continue  # YAML multi-step workflows can't be overwritten by a UI draft
      ...
  ```

  This is the single behavioral change.

### 4.2 Dead-code cleanup (keep the code's intent honest)

With workflows filtered out at load time, every surviving row is a simple xprompt, so the "disabled workflow" concept no
longer exists. Remove the branch that produced its user-facing text:

- In `_disabled_reason(...)`, delete the leading branch:
  ```python
  if not workflow.is_simple_xprompt():
      return "workflow - can't overwrite with a prompt draft"
  ```
  The remaining reasons (`source path could not be resolved`, `unsupported source format`, `source file is read-only`,
  `source directory is not writable`) still apply to read-only/unresolvable simple xprompts and are kept.

Leave the cheap defensive guards that remain locally correct and harmless:

- `_target_for_workflow(...)` keeps its `if not workflow.is_simple_xprompt(): return None` guard (it makes the pure
  helper safe regardless of caller; it is simply never exercised now).
- `_overwrite_preview(...)` keeps its `if workflow.is_simple_xprompt(): … else …` split as a defensive fallback; in
  practice only the simple branch renders now. (Optional tidy-up: collapse to the simple branch — implementer's
  discretion; not required.)

No new public API, no signature changes, no styling changes (the `.tcss` blocks are untouched), and no change to the
keymap, the bar→app message, or the app-side save orchestration.

## 5. Rust core backend boundary

Per `memory/rust_core_backend_boundary.md`: this is a **presentation-only** decision about which rows a Textual modal
displays. The classification it keys on (`Workflow.is_simple_xprompt()`) already exists in the shared domain model; the
serialization/format contract and the loader/catalog are untouched. No `sase-core` change is required.

## 6. Testing

- `tests/ace/tui/modals/test_xprompt_save_target_modal.py`
  - `test_load_save_rows_marks_eligible_and_disabled_targets`: update so the multi-step `workflow` entry is **absent**
    from the produced rows instead of present-but-disabled. Replace the `by_name["workflow"].target is None` /
    `"workflow" in disabled_reason` assertions with `assert "workflow" not in by_name`, while keeping the `review`
    (markdown) and `cfg` (config) eligibility assertions. Rename to reflect the new contract (e.g.
    `test_load_save_rows_excludes_workflows_and_marks_eligible_targets`).
  - `test_disabled_rows_are_skipped_by_navigation`: this constructs synthetic rows directly and verifies navigation
    skips disabled rows. Re-point the disabled row at a realistic now-possible case — a **simple** xprompt with
    `disabled_reason="source file is read-only"` (and `target=None`) — instead of a workflow, so the test reflects the
    only kind of disabled row that can still occur. The skip-navigation assertion is unchanged.

- `tests/ace/tui/actions/test_prompt_save_xprompt.py`: uses simple-xprompt rows only → unaffected; no change expected.
  Run it to confirm.

- No PNG visual golden exists for this modal (verified), so no snapshot update is needed.

- Run `just install` first (ephemeral workspace), then `just check` (ruff + mypy + tests) before completion.

## 7. Reliability / edge cases

- **Empty categories:** a source group that held only workflows disappears cleanly (headers derive from filtered rows —
  no empty header rows).
- **Mixed groups:** a category with both workflows and simple xprompts keeps only its simple xprompts.
- **Create-new path:** `➕ Create new xprompt…` remains pinned first and fully functional; the downstream location
  picker and name modal are untouched.
- **Read-only simple xprompts:** still listed disabled with their real reason (unchanged), preserving an honest view of
  writable-but-blocked targets without reintroducing workflow noise.

## 8. Decisions made (so implementation is unambiguous)

- Workflows are **hidden**, not disabled, in the save-target picker (reversing the previous "listed-but-disabled"
  decision for this picker only).
- Filtering happens once, at row load (`load_xprompt_save_rows`), so the rest of the modal needs no awareness of
  workflows.
- Read-only **simple** xprompts remain shown-disabled (out of scope to hide); only multi-step workflows are removed.
- No Rust/core, styling, keymap, or help-text changes are required.
