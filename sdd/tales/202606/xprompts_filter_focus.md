---
create_time: 2026-06-27 09:25:32
status: wip
prompt: sdd/prompts/202606/xprompts_filter_focus.md
---
# Plan: XPrompts Filter Focus Behavior

## Problem

In the SASE Admin Center, pressing `5` from another Admin Center tab switches to the XPrompts tab. The XPrompts pane
currently focuses the filter input automatically via `XPromptBrowserPane.focus_default()`. Because the filter owns
keyboard input, a subsequent digit such as `1` is inserted into the filter instead of reaching the Admin Center's
numbered tab keymaps.

The intended behavior is browse-first: opening or switching to XPrompts should leave the pane ready for navigation and
tab hotkeys, and the user should press `/` explicitly when they want to edit the filter.

## Current Shape

- `ConfigCenterModal._focus_active_pane()` calls `focus_default()` on whichever pane is active after mount or tab
  switch.
- `XPromptBrowserPane.focus_default()` currently focuses `#browser-filter-input`.
- `XPromptBrowserPane` already builds and highlights the first real row on mount, so list selection/preview can remain
  available without focusing the filter.
- Neighboring Admin Center panes already use the desired convention:
  - Projects focuses its option list by default and binds `/` to the filter.
  - Updates focuses its option list by default and binds `slash` to the filter.

## Implementation Approach

1. Make the XPrompts pane browse-first.
   - Change `XPromptBrowserPane.focus_default()` to focus `#browser-list` instead of `#browser-filter-input`.
   - Keep `on_mount()` row highlighting and preview initialization unchanged.

2. Add explicit filter activation.
   - Add a `/` / `slash` binding to `XPromptBrowserPane.BINDINGS` for a new `action_focus_filter()`.
   - Implement `action_focus_filter()` by focusing `#browser-filter-input`, matching the style used by Projects and
     Updates.

3. Update comments/docstrings that assume the filter is always focused.
   - In `BrowserFilterInput`, revise the class docstring so it describes the input behavior only while the filter has
     focus.
   - Leave its existing forwarding of `[` / `]` and loadable `tab` behavior in place, because those are still needed
     once the user explicitly focuses the filter.

4. Add focused regression coverage.
   - Extend the Admin Center tab tests to cover the exact failure mode: open Config Center, press `5`, then press `1`;
     assert the modal switches to Config and the XPrompts filter value did not receive `1`.
   - Add a complementary assertion that pressing `/` on XPrompts focuses the filter and typing then changes the filter
     value.
   - Keep the fixture stubbing deterministic, as existing Config Center tests do, so the test does not depend on real
     xprompt files.

5. Validate.
   - Run the targeted Admin Center/XPrompts tests first.
   - Because implementation files will change in this repo, run `just install` if needed and then `just check` before
     reporting completion.

## Risks and Notes

- This should not add any synchronous work to TUI key handlers. It only changes focus targets and bindings.
- The PNG snapshot for the XPrompts tab may change slightly if the focused widget border/cursor differs. If targeted
  tests indicate a visual snapshot update is needed, inspect the diff before accepting it.
- `Ctrl+I`/terminal `tab` inline-load behavior from the filter remains scoped to the filter. If browse-mode `Ctrl+I`
  behavior is expected separately, that can be handled by the pane binding path, but it is not required for the reported
  numbered-tab regression.
