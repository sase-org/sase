---
create_time: 2026-03-27 09:58:37
status: done
prompt: sdd/prompts/202603/telegram_resume_branch_name.md
---

# Plan: Fix Telegram Resume Button to Use Branch Name Instead of Project Name

## Problem

When clicking the "Resume" button in Telegram for an agent completion message (especially one that created a PR), the
VCS xprompt tag in the resume text uses the **project name** (e.g., `#gh:sase`) extracted from the original prompt
instead of the **branch name** / cl_name (e.g., `#gh:sase_foobar_1`).

This means resuming would create a _new_ branch under the project instead of resuming work on the _existing_ branch
where the PR was created.

## Current Behavior

In `sase-telegram/src/sase_telegram/formatting.py:539-558`:

1. Extracts VCS tag from original prompt: `extract_vcs_workflow_tag(raw_prompt)` → `#gh:sase `
2. Builds resume text: `#gh:sase #resume:agent_name `

The `action_data` already contains `cl_name` (the branch name, e.g., `sase_foobar_1`) from `run_agent_runner.py:421`,
but it's not being used.

## Desired Behavior

Resume text should be: `#gh:sase_foobar_1 #resume:agent_name ` (using cl_name as the VCS ref).

## Implementation Steps

### Step 1: Add `replace_ref_in_vcs_tag()` helper to `sase.xprompt._parsing`

Add a small utility function that takes a VCS tag (e.g., `#gh:sase `) and a new ref (e.g., `sase_foobar_1`) and returns
the tag with the ref replaced (e.g., `#gh:sase_foobar_1 `). This handles all VCS tag formats (colon, parenthesized) and
strips HITL suffixes (`!!`, `??`) for resume scenarios.

This helper is needed because:

- The TUI code in `_interaction.py:345-349` and `_interaction.py:371-375` has the exact same pattern and will benefit
  from this function
- It properly handles all VCS tag formats (colon, parenthesized, HITL suffixes)

**Files to modify:**

- `src/sase/xprompt/_parsing.py` — add `replace_ref_in_vcs_tag(tag: str, new_ref: str) -> str`
- `src/sase/xprompt/__init__.py` — export the new function

### Step 2: Fix `_format_workflow_complete()` in sase-telegram

In `sase-telegram/src/sase_telegram/formatting.py:539-558`, when building the resume text:

1. Extract VCS tag from prompt (as before)
2. If VCS tag exists AND `cl_name` is in `action_data`, call `replace_ref_in_vcs_tag(vcs_tag, cl_name)` to swap the
   project ref for the branch name
3. Use the updated tag in the resume text

**Files to modify:**

- `sase-telegram/src/sase_telegram/formatting.py` — update resume text construction in `_format_workflow_complete()`

### Step 3: Update/add tests

- `tests/test_xprompt_parsing.py` or similar — test `replace_ref_in_vcs_tag` for colon format (`#gh:sase ` →
  `#gh:new `), parenthesized format (`#git(repo) ` → `#git(new) `), and HITL format (`#gh!!:sase ` → `#gh:new `)
- `sase-telegram/tests/test_formatting.py` — add test for `TestFormatWorkflowComplete` where `action_data` includes both
  `prompt` with VCS tag and `cl_name`, verifying the resume button uses the cl_name

### Step 4: (Note for future) TUI has the same pattern

The TUI resume code in `src/sase/ace/tui/actions/agents/_interaction.py:345-349` and `:371-375` extracts the VCS tag
from `agent.get_raw_xprompt_content()` and uses it as-is. This has the same issue — when resuming a completed agent, it
should use the agent's `cl_name` instead of the original project ref. The new `replace_ref_in_vcs_tag` function can be
used here too, but this is out of scope for this change (user only asked about Telegram).
