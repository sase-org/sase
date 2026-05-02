---
create_time: 2026-04-01 18:42:27
status: done
prompt: sdd/prompts/202604/vcs_xprompt_mru_cycling.md
---

# Plan: VCS Xprompt MRU Cycling in Prompt Input

## Problem

When a user presses `<space>` to start an agent from a ChangeSpec, the prompt input is pre-populated with the VCS
xprompt workflow reference for that specific CL (e.g., `#gh:sase `). But there's no way to quickly switch to a different
VCS xprompt workflow without dismissing and re-entering via a different ChangeSpec. Users who work across multiple
projects/CLs need a fast way to cycle through recently-used VCS xprompt workflows.

## Solution

Track the last 10 used embedded VCS xprompt workflows and let users cycle through them with `<ctrl+n>` / `<ctrl+p>` when
the prompt input widget is empty or only contains a VCS xprompt workflow reference.

## Design

### Phase 1: MRU Storage (`src/sase/history/vcs_xprompt_mru.py`)

New module for tracking the last 10 used VCS xprompt workflow prefixes.

**Data model**: A simple ordered list of VCS prefix strings (e.g., `["#gh:sase", "#gh:other_project", "#gh:my_lib"]`),
stored in `~/.sase/vcs_xprompt_mru.json`. Most recently used is at index 0.

**Functions**:

- `load_vcs_xprompt_mru() -> list[str]` — Load the MRU list from disk.
- `record_vcs_xprompt_usage(prefix: str) -> None` — Move/add `prefix` to the front of the list, cap at 10 entries, save
  to disk.

**Recording trigger**: In `_finish_agent_launch()` (`_agent_launch.py`), after a prompt containing a VCS workflow
reference is submitted, extract the VCS prefix (using `extract_vcs_workflow_tag()`) and call
`record_vcs_xprompt_usage()`.

### Phase 2: Prompt Input Cycling (`src/sase/ace/tui/widgets/prompt_text_area.py`)

Add VCS MRU cycling logic to `PromptTextArea._on_key()`.

**Activation condition**: `ctrl+n` or `ctrl+p` is pressed AND:

1. File completion is NOT active (existing ctrl+n/ctrl+p for file completion takes priority)
2. The prompt text is either empty OR consists solely of a VCS xprompt workflow tag (with optional trailing space)

**Detection**: Use `extract_vcs_workflow_tag()` on the stripped text. If the tag covers the entire text (after
stripping), the prompt is "VCS-only". An empty prompt also qualifies.

**Cycling behavior**:

- `ctrl+n` cycles forward through the MRU list (index 0 → 1 → 2 → ... → wraps to 0)
- `ctrl+p` cycles backward (index 2 → 1 → 0 → wraps to end)
- The current VCS prefix in the prompt (if any) determines the starting position in the MRU list
- If the prompt is empty, cycling starts from the most recent entry (index 0)
- After cycling, the prompt text is replaced with the new VCS prefix + trailing space, cursor at end

**State tracking**: A `_vcs_mru_index: int | None` field on `PromptTextArea` tracks the current position in the MRU list
during a cycling session. Reset to `None` when the user types any other character or when the prompt text changes in a
way that doesn't match a VCS-only pattern.

### Phase 3: Reset Logic

The `_vcs_mru_index` must be reset when:

- The user types any character (the prompt is no longer VCS-only)
- The prompt is cleared
- The prompt bar is unmounted/remounted
- File completion activates

This ensures cycling only happens in the narrow context where it makes sense.
