---
create_time: 2026-03-28 16:55:18
status: done
prompt: sdd/prompts/202603/multi_agent_prompt_history.md
---

# Plan: Save Multi-Agent Prompts to History Separately

## Context

Currently, when a multi-agent prompt (segments separated by `---`) is saved to prompt history, the **entire combined
prompt** is stored as a single entry. This means individual agent segments can't be reused from history independently.

**Example** — today, this multi-agent prompt:

```
Fix the auth bug
---
%wait Review the fix and add tests
```

...is saved as one history entry containing both segments joined with `---`. If the user later wants to reuse just "Fix
the auth bug", they have to manually extract it.

## Goal

When a multi-agent prompt is saved, also save each segment as its own history entry. This way:

- The **combined prompt** is still in history (for replaying the full multi-agent workflow).
- Each **individual segment** is also in history (for standalone reuse).

## Design

### Where to add the splitting logic

Centralize it inside `add_or_update_prompt()` in `src/sase/history/prompt.py`. This way all callers (CLI launcher, TUI
agent launch, cancelled prompt saves) automatically get the behavior without per-callsite changes.

After saving the full text as-is (existing behavior), detect whether it's a multi-prompt and, if so, save each segment
as an additional entry (subject to the same dedup rules).

### What to save per segment

Each segment's text, stripped of frontmatter but otherwise unmodified (including any `%wait`, `%name`, etc. directives).
Directives are part of the user's intent and should be preserved so they're available if the segment is reused in a new
multi-agent prompt.

### Frontmatter handling

Frontmatter defines shared local xprompts (`_style`, `_context`, etc.). It is NOT included in individual segment entries
— it's only meaningful in the combined prompt context. If a segment references `#_style`, the user can add their own
frontmatter when reusing it.

### Deduplication

The existing dedup (exact text match) handles this naturally. If "Fix the auth bug" was already in history from a
previous standalone use, saving it again from a multi-agent prompt just bumps `last_used`.

### Cancelled prompts

For cancelled multi-agent prompts, each segment should also be saved as cancelled. This preserves the draft-recovery
behavior at the segment level.

## Changes

### Phase 1: Core logic (`src/sase/history/prompt.py`)

In `add_or_update_prompt()`, after the existing save logic, add:

```python
# Also save individual segments for multi-agent prompts
from sase.agent.multi_prompt import is_multi_prompt, parse_multi_prompt

if is_multi_prompt(text):
    multi = parse_multi_prompt(text)
    for segment in multi.segments:
        # Recursive call for each segment (won't re-trigger since
        # individual segments aren't multi-prompts)
        add_or_update_prompt(
            segment,
            project_name=project_name,
            branch_or_workspace=branch_or_workspace,
            cancelled=cancelled,
        )
```

Note: The recursive `add_or_update_prompt` call for each segment will go through the same dedup/save path. Since
individual segments are not themselves multi-prompts, there's no infinite recursion risk.

### Phase 2: Tests (`tests/history/test_prompt.py`)

Add tests for:

1. Multi-agent prompt saves both combined and individual segments
2. Dedup: segment already in history just gets `last_used` bumped
3. Cancelled multi-agent prompt saves cancelled segments
4. Single-segment prompt with frontmatter does NOT split (not a multi-prompt)
5. Segments with directives (`%wait`, `%name`) are preserved as-is
