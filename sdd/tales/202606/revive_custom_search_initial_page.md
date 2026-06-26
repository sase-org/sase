---
create_time: 2026-06-26 10:28:20
status: done
prompt: sdd/prompts/202606/revive_custom_search_initial_page.md
---
# Plan: Show Custom Revival Search First Page Automatically

## Summary

Selecting **Custom revival search...** from the Agent Restore / Revive Agents flow opens `DismissedAgentSelectModal`
with a paged dismissed-archive loader. The modal does fetch the first page automatically, but the visible `OptionList`
can remain stuck on the disabled `Loading dismissed archive...` placeholder until the user types in the filter box.
Typing works around the issue because `on_input_changed` rebuilds the option list from the already loaded `self.agents`.

Fix the modal so the initial auto-loaded page is applied to widgets after the mount lifecycle is ready, without adding
any synchronous archive work to the Textual event loop.

## Diagnosis

Relevant flow:

1. `AgentReviveFlowMixin._revive_agent()` opens `SavedAgentGroupRevivalModal`.
2. Choosing `Custom revival search...` calls `_open_custom_revival_search()`, then
   `AgentReviveArchiveMixin._show_dismissed_agents_for_scope(selection)`.
3. `_show_dismissed_agents_for_scope()` pushes `DismissedAgentSelectModal` with:
   - `loading_archive=True`
   - `page_loader=_load_page_for_modal`
   - an initially empty or partial in-memory dismissed-agent list.
4. `DismissedAgentSelectModal.on_mount()` focuses the filter input and awaits
   `_load_more_async(preserve_highlight=False)`.
5. `_load_more_async()` runs `page_loader` through `asyncio.to_thread()`, then calls `set_agents(...)`.

I reproduced the bug with a small Textual harness:

- `page_loader` was called.
- `modal.agents` contained the first loaded agent.
- `modal._filtered` contained that agent.
- the `OptionList` still contained one disabled `Loading dismissed archive...` option.
- setting the filter input value rebuilt the list and displayed the agent immediately.

The likely root cause is the `set_agents()` mount guard:

```python
if not self.is_mounted:
    return
```

During the awaited initial load that runs inside `on_mount()`, `set_agents()` can update the modal's model state while
skipping `_rebuild_options()`, `_update_preview_for_current_highlight()`, and `_update_hints()`. No later render is
scheduled for that loaded state. The first `Input.Changed` event then rebuilds the list, which matches the reported
workaround.

## Goals

- Opening Custom revival search should automatically show the first 250 dismissed-agent rows once the first page
  finishes loading.
- Preserve the existing off-event-loop archive loading via `asyncio.to_thread()`.
- Preserve filtering, marking, preview updates, `Ctrl+K` paging, and highlight preservation.
- Add regression coverage that fails when the first page is loaded into modal state but not rendered.

## Non-Goals

- Changing page size, archive query semantics, scope filtering, or saved-group revival behavior.
- Reworking the dismissed-bundle paging implementation.
- Adding new help/footer entries; this fix does not change a keymap or user-facing command.

## Implementation Approach

1. Update `DismissedAgentSelectModal` so model updates that arrive before full mount are still rendered once widgets are
   available.
   - Prefer a small modal-local helper such as `_apply_agents_to_widgets(...)` or `_refresh_loaded_state(...)` that
     performs the current `_rebuild_options()`, preview, and hints update when mounted.
   - Replace the silent early return with a deferred refresh flag or a `call_after_refresh` / `call_later` callback so
     data loaded during `on_mount()` cannot be stranded in model state.
   - Keep all widget mutation on the UI thread; keep archive loading inside the existing thread handoff.

2. Make initial auto-load and later `Ctrl+K` load-more share the same apply path.
   - First-page load should render rows and clear the loading placeholder.
   - Load-more should still preserve the current highlight when requested.
   - Error and exhausted-page behavior should remain unchanged.

3. Add focused modal regression tests in `tests/ace/tui/modals/test_revive_agent_modal.py`.
   - A Textual `run_test` case with an initially empty modal and a fake `page_loader` returning one page should assert
     that, after mount/pause and without typing, the `OptionList` contains the loaded agent row, not the loading
     placeholder.
   - Keep the existing `Ctrl+K` paging test, and adjust only if the shared apply path changes timing.
   - Optionally assert preview/hints are refreshed after the initial page if the test remains stable.

4. Verify with focused tests first, then broader checks if time permits.
   - Run `./.venv/bin/python -m pytest tests/ace/tui/modals/test_revive_agent_modal.py`.
   - Run adjacent revival tests if the modal change touches shared revive behavior.
   - Run `just check` if the focused suite passes and runtime is reasonable.

## Risks and Mitigations

- **Textual lifecycle timing:** calling widget mutation too early can raise `NoMatches` or fail silently. Use an
  explicit deferred refresh path instead of assuming `is_mounted` is reliable during `on_mount()`.
- **Duplicate rebuilds:** an initial deferred refresh plus a later load-more could rebuild twice. Keep the helper
  idempotent and based on current modal state.
- **Highlight jumps:** preserve the existing `preserve_highlight` behavior by capturing identity before replacing the
  list and restoring it in the shared apply path.
- **Event loop blocking:** do not move page loading, bundle parsing, or archive repair onto the event loop.
