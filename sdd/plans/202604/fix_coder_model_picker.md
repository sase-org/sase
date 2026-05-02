---
create_time: 2026-04-08 20:17:41
status: done
prompt: sdd/prompts/202604/fix_coder_model_picker.md
---

# Fix: Model picker selection ignored for coder agents

## Problem

When a user selects a model (e.g., `gemini-3-flash-preview`) from the "Approve with Options" modal's model picker, the
coder agent runs with the planner's model (e.g., `gemini-3.1-pro-preview`) instead. Two root causes combine to produce
this behavior.

### Root Cause 1: `extract_prompt_directives` doesn't respect disabled regions

The coder prompt is assembled in `run_agent_exec_plan.py` as:

```
%model:gemini-3-flash-preview        ← from plan_result.coder_model (user's picker selection)
#resume:b.1 #git:bs_allow_plans      ← resumes planner's conversation
@plan_file

The above plan has been reviewed and approved. Implement it now.
```

When `#resume:b.1` expands (via `process_xprompt_references`), the planner's conversation is injected between
`%xprompts_enabled:false/true` disabled-region markers:

```
%model:gemini-3-flash-preview
%xprompts_enabled:false
# Previous Conversation

**User:**
...original prompt... %model:gemini-3.1-pro-preview   ← old directive from planner's prompt

**Assistant:**
...
%xprompts_enabled:true
# New Query
...
```

`extract_prompt_directives()` (in `directives.py`) protects fenced code blocks but does **not** protect disabled
regions. It sees **two** `%model` directives and raises `DirectiveError("Duplicate directive '%model' in prompt")`.

This crash prevents the coder from ever starting. The TUI still shows the agent as RUNNING briefly (before detecting the
crash), and the "Model:" field displays the planner's model inherited from `create_followup_artifacts`.

### Root Cause 2: Coder's `agent_meta.json` never reflects the picker selection

Even after fixing root cause 1, the coder's `agent_meta.json` would still show the planner's model.
`create_followup_artifacts()` copies the planner's `agent_meta` verbatim (including `model` and `llm_provider`). The
`%model` directive in the coder prompt is only consumed by `preprocess_prompt` → `invoke_agent` for LLM invocation — it
never updates `agent_meta.json`. So the TUI's "Model:" field (which reads from `agent_meta.json`) would be stale.

## Fix

### Phase 1: Add disabled-region protection to `extract_prompt_directives`

**File**: `src/sase/xprompt/directives.py`

Mirror the existing fenced-block protection pattern. Before scanning for directive matches, call
`protect_disabled_regions()` to replace disabled regions with null-byte placeholders. After processing, call
`unprotect_disabled_regions()` to restore them. Finally, call `strip_disabled_region_markers()` to remove the marker
lines (since directives are the last pipeline stage that needs to see them).

```python
from ._disabled_regions import (
    protect_disabled_regions,
    strip_disabled_region_markers,
    unprotect_disabled_regions,
)

def extract_prompt_directives(prompt: str) -> tuple[str, PromptDirectives]:
    ...
    fenced_blocks: list[str] = []
    prompt = protect_fenced_blocks(prompt, fenced_blocks)

    # NEW: Protect disabled regions so old directives inside #resume
    # expansions are not re-parsed.
    disabled_regions: list[str] = []
    prompt = protect_disabled_regions(prompt, disabled_regions)

    matches = list(re.finditer(_DIRECTIVE_PATTERN, prompt, re.MULTILINE))
    ...
    # After building cleaned prompt and directives:

    # Restore disabled regions, then strip markers
    cleaned = unprotect_disabled_regions(cleaned, disabled_regions)
    cleaned = strip_disabled_region_markers(cleaned)

    # Restore fenced code blocks
    cleaned = unprotect_fenced_blocks(cleaned, fenced_blocks)
    ...
```

This ensures `%model` (and any other directives) inside the "Previous Conversation" section from `#resume` are treated
as inert text.

### Phase 2: Update coder's `agent_meta.json` with the selected model

**File**: `src/sase/axe/run_agent_exec_plan.py`

After `create_followup_artifacts()` writes the initial `agent_meta.json`, update its `model` and `llm_provider` fields
if the coder model differs from the planner's model. This should happen for both the direct-coder and epic paths.

Compute the coder's resolved model/provider from `model_prefix` (which already holds the correct model string) and patch
`agent_meta.json` in the new artifacts directory:

```python
# After create_followup_artifacts(), update meta if coder model differs
if plan_result.coder_model and plan_result.coder_model != ctx.agent_model:
    from sase.llm_provider.registry import resolve_model_provider
    from sase.axe.run_agent_helpers import update_meta_field

    resolved_provider, resolved_model = resolve_model_provider(plan_result.coder_model)
    update_meta_field(state.current_artifacts_dir, "model", resolved_model)
    if resolved_provider:
        update_meta_field(state.current_artifacts_dir, "llm_provider", resolved_provider)
```

### Phase 3: Add test coverage

**File**: `tests/test_xprompt_directives.py`

Add a test that verifies `extract_prompt_directives` ignores `%model` inside disabled regions:

- Prompt with `%model:new_model` outside and `%model:old_model` inside `%xprompts_enabled:false/true` → should extract
  only `new_model`, no error.
- Prompt with only `%model:old_model` inside disabled region → should extract no model directive.

**File**: `tests/test_axe_run_agent_exec_plan.py`

Add a test that verifies the coder's `agent_meta.json` reflects `plan_result.coder_model` when it differs from the
planner's model.
