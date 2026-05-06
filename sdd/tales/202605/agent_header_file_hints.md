---
create_time: 2026-05-06 19:46:02
status: done
prompt: sdd/prompts/202605/agent_header_file_hints.md
---
# Plan: Agent Header File Hints

## Problem

In the Agents tab, pressing `v` calls `AgentDetail.update_display_with_hints()`, which delegates to
`AgentPromptPanel.update_display_with_hints()`. That hint renderer builds the agent details header with
`build_header_text(agent)`, then scans only selected later text blocks: error traceback, raw xprompt, prompt content,
and reply/chat content. The already-rendered header is not scanned for file paths.

The snapshot shows the consequence: the `FBACK` timestamp detail contains
`~/.sase/plans/202605/wait_requires_success.md`, but it lives inside `agent.timestamps_display`, which is appended
inside `build_header_text()`. Since that header text is constructed before hint scanning starts, the path remains
visible but has no `[N]` marker and cannot be selected from the `View:` prompt.

## Scope

- Fix agent detail hint mode for file paths that appear in the agent header, especially `Timestamps:` details such as
  feedback plan paths.
- Keep the current normal, non-hint rendering behavior unchanged.
- Keep the change in the Python/Textual presentation layer; this is not shared backend logic.
- Avoid broad changes to ChangeSpec timestamp rendering unless a direct regression is found there.

## Technical Approach

1. Add a small hint-aware header rendering path rather than trying to parse the final `Text.plain` output after the
   fact.
   - The most targeted option is to extend `build_header_text()` with optional hint state for fields that may contain
     paths.
   - Start with `agent.timestamps_display`, because it is the source of the bug in the snapshot.
   - If implementation is cleaner, create a sibling helper used only by hint mode, but avoid duplicating the full
     header.

2. Preserve styling and mapping semantics.
   - Keep the `Timestamps:` label style as-is.
   - Render detected paths with the same marker/file styling used by prompt and reply hints.
   - Resolve `~` paths with `os.path.expanduser()` and relative paths against the agent workspace, matching existing
     `append_text_with_file_hints()` behavior.
   - Continue numbering sequentially so a header hint consumes `[1]` before later xprompt/prompt/reply hints.

3. Update `AgentHintsDisplayMixin.update_display_with_hints()`.
   - Resolve `workspace_dir` before building the header, as it already does.
   - Pass the current `hint_counter` and `hint_mappings` into the header hint path.
   - Continue scanning error traceback, raw xprompt, prompt, and reply sections after the header with the updated
     counter.

4. Add regression tests.
   - Add a unit test around the fake prompt panel showing that a terminal or running agent with `timestamps_display`
     containing `FBACK | ... ~/.sase/plans/202605/wait_requires_success.md` renders a `[1]` marker next to that path
     after `update_display_with_hints()`.
   - Assert the mapping expands `~` to the home directory.
   - Assert subsequent hint numbering still advances for existing xprompt/prompt paths, so the fix does not overwrite or
     reset mappings.

5. Verify.
   - Run the targeted test file first.
   - Because this repo requires it after code changes, run `just install` if needed and then `just check`.

## Risks

- Rebuilding the header in hint mode can accidentally alter spacing/styling if we duplicate logic. Prefer modifying the
  existing builder at the exact timestamp append point.
- Header paths beyond timestamps may still be unhinted. If tests or inspection show another common header path-bearing
  field, include it only if it can be handled without widening the change substantially.
