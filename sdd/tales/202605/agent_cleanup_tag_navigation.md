---
create_time: 2026-05-09 03:09:28
status: done
prompt: sdd/prompts/202605/agent_cleanup_tag_navigation.md
---
# Plan: Agent Cleanup Tag Navigation

## Problem

Pressing `X` opens the Agent Cleanup panel. From there, pressing `t` opens the tag-scoped cleanup selector, but that
selector does not respond to `j`/`k` navigation. This breaks the keyboard-first flow because the first cleanup panel can
be driven entirely from keys while the follow-up tag panel cannot.

## Current Findings

- `AgentCleanupModal` and `AgentCleanupTagModal` live in `src/sase/ace/tui/modals/agent_cleanup_modal.py`.
- `AgentCleanupTagModal.BINDINGS` currently includes only `escape`, `q`, and `enter`.
- Shared vim-style `OptionList` modal navigation already exists in `OptionListNavigationMixin` in
  `src/sase/ace/tui/modals/base.py`, including `j`, `k`, arrow keys, `ctrl+n`, and `ctrl+p`.
- Other selection modals use that mixin by inheriting from it, setting `_option_list_id`, and spreading
  `OptionListNavigationMixin.NAVIGATION_BINDINGS` into `BINDINGS`.

## Implementation Approach

1. Update `AgentCleanupTagModal` to use `OptionListNavigationMixin`.
2. Set `_option_list_id = "agent-cleanup-tag-list"` so the mixin targets the existing `OptionList`.
3. Replace the modal's duplicated cancel bindings with `OptionListNavigationMixin.NAVIGATION_BINDINGS`, keeping the
   existing `enter` binding for choosing the highlighted tag.
4. Update the footer hint text to advertise `j/k` navigation for this selector.
5. Add a focused regression test that mounts `AgentCleanupTagModal`, presses `j` and `k`, and asserts that the
   highlighted option moves as expected.

## Verification

- Run the targeted cleanup modal test file first: `pytest tests/ace/tui/test_agent_cleanup_modal.py`
- Because this repo requires it after source changes, run: `just install` `just check`
