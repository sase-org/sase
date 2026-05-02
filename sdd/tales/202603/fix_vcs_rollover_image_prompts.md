---
create_time: 2026-03-27 18:38:09
status: done
prompt: sdd/prompts/202603/fix_vcs_rollover_image_prompts.md
---

# Fix VCS workflow rollover for image-based Telegram prompts

## Problem

When a Telegram message includes an image with a caption like `#gh_sase Fix the bug`, the `build_photo_prompt()`
function in `sase-telegram` wraps it as:

```
The user sent an image via Telegram with the following caption:

#gh_sase Fix the bug

The image has been saved to: /path/to/image.jpg
Please read the image file and respond to the user's request.
```

This pushes the `#gh_sase` VCS tag away from the start of the prompt. During agent startup, `extract_vcs_workflow_tag()`
only matches VCS tags at the **beginning** of the prompt (after `%directive` tokens), so `ctx.vcs_tag` is set to `None`.

The `#gh` embedded workflow IS correctly expanded during the **first** iteration (the workflow executor finds `#gh:sase`
anywhere in the prompt). But when the agent submits a plan and the followup coder agent is spawned, the followup prompt
is constructed as:

```python
state.current_prompt = (
    f"{vcs_prefix}"           # Empty because ctx.vcs_tag is None
    f"@{plan_file}\n\n"
    "The above plan has been reviewed and approved. "
    f"Implement it now.\n{embedded_refs}"  # gh excluded by "vcs" tag filter
)
```

The VCS workflow is lost because:

1. `vcs_prefix` is empty (`ctx.vcs_tag` is None)
2. `_get_embedded_workflow_refs()` unconditionally skips workflows tagged with `"vcs"`, even when `vcs_tag` is None and
   no VCS prefix is being used

Without the `#gh` embedded workflow, the followup agent has no diff step, so `diff_path` is never set and the completion
PDF sent via Telegram has no file changes attached.

## Evidence

- **Last working run** (`20260327172258`, ws=101): Original prompt started with `#gh:sase` directly.
  `ctx.vcs_tag = "#gh:sase "`. Followup (`20260327172650`) had `embedded_workflows.json` with `gh`, diff step ran,
  `diff_path = /tmp/sase-gh-2L9Gp7.diff`.

- **Broken run** (`20260327174839`, ws=100): Original prompt was image-based with `%n:c The user sent an image...`.
  `ctx.vcs_tag = None`. Followup (`20260327175633`) had NO `embedded_workflows.json`, no `prompt_step_gh__*` files,
  `diff_path = None`.

## Root Cause

`_get_embedded_workflow_refs()` in `src/sase/axe/run_agent_exec_plan.py:71-118`.

The filter condition at line 102:

```python
if name == vcs_name or "vcs" in wf_tags:
    continue
```

The `"vcs" in wf_tags` check unconditionally excludes VCS-tagged workflows from `embedded_refs`, even when `vcs_tag` is
None. This is correct when `vcs_tag` is set (the VCS workflow is already handled by `vcs_prefix`), but incorrect when
`vcs_tag` is None (the VCS workflow is not included anywhere).

## Fix

### Change 1: `src/sase/axe/run_agent_exec_plan.py` — conditional VCS exclusion

In `_get_embedded_workflow_refs()`, only exclude VCS-tagged workflows when `vcs_tag` is not None:

```python
# Before:
if name == vcs_name or "vcs" in wf_tags:
    continue

# After:
if name == vcs_name or (vcs_tag and "vcs" in wf_tags):
    continue
```

When `vcs_tag` is None, `vcs_name` is also None, so `name == vcs_name` is always False. The `"vcs" in wf_tags` check is
now gated on `vcs_tag` being truthy. This means VCS workflows are included in `embedded_refs` when no VCS prefix is
being used, ensuring the followup prompt gets the `#gh:sase` ref appended.

### Change 2: Test in `tests/axe/test_run_agent_exec_plan.py`

Add a test case for `_get_embedded_workflow_refs()` verifying that when `vcs_tag=None`, VCS-tagged workflows ARE
included in the returned refs.
