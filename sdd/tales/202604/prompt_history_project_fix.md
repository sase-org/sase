---
create_time: 2026-04-02 12:02:56
status: done
prompt: sdd/prompts/202604/prompt_history_project_fix.md
---

# Fix: Prompt history saves wrong project for VCS-tagged home-mode prompts

## Problem

When a prompt containing a VCS tag like `#hg:pat` is submitted from home mode, the prompt history entry is saved with
the wrong project association. In the reported case, a prompt with `#hg:pat` was saved with `Branch: yserve` and
`Workspace: home` instead of `Branch: pat` and `Workspace: pat`.

## Root Cause

In `_finish_agent_launch()` (`src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`), `add_or_update_prompt()` is
called at **line 56** — before VCS resolution happens at **line 126**. The call order is:

1. **Line 56**: `add_or_update_prompt(prompt, project_name=ctx.project_name, branch_or_workspace=ctx.history_sort_key)`
   - At this point `ctx.project_name` is still `"home"` and `ctx.history_sort_key` is the stale value from the entry
     point (e.g., `"yserve"` from a previous `,<space>` selection).
2. **Line 126**: VCS resolution updates `ctx.project_name` to `"pat"` and `ctx.display_name` to `"pat"`.

The prompt history is written with pre-resolution values that don't reflect the actual prompt content.

A secondary issue: `ctx.history_sort_key` is **never updated** after VCS resolution, so even moving the save call
wouldn't fully fix the problem without also updating `history_sort_key`.

## Fix

Two changes, both in `_agent_launch.py`:

### 1. Update `history_sort_key` after VCS resolution

In the home-mode VCS resolution block (around line 142), after `ctx.display_name = ref_value`, add:

```python
ctx.history_sort_key = ref_value
```

Similarly, in the multi-prompt early-return path (around line 120), after `ctx.display_name = ref_value`, add:

```python
ctx.history_sort_key = ref_value
```

### 2. Move `add_or_update_prompt()` to after VCS resolution

Remove the early `add_or_update_prompt()` call (lines 53-60). Add it back in two places:

- **After the home-mode VCS resolution block** (~line 146) — covers the single-prompt path. By this point
  `ctx.project_name` and `ctx.history_sort_key` are correct.
- **Inside the multi-prompt early-return path** — before the `return` at line 124, so multi-prompts also get correct
  history entries.

## Scope

- Only `_agent_launch.py` needs changes.
- The cancelled-prompt save in `_save_bar_text_as_cancelled()` uses pre-resolution context by design (the user hasn't
  submitted, so full VCS resolution hasn't run). That's a separate concern and out of scope.
- Tests in `tests/history/test_prompt.py` don't need changes since they test `add_or_update_prompt()` in isolation, not
  the TUI launch flow.
