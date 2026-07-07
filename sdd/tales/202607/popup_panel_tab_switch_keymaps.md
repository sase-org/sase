---
create_time: 2026-07-07 11:13:24
status: done
prompt: sdd/prompts/202607/popup_panel_tab_switch_keymaps.md
---
# Popup Panel Tab-Switch Keymaps

## Problem

The ACE TUI has app-level `next_tab` / `prev_tab` bindings, defaulting to `tab` and `shift+tab`. These bindings work in
the main app but are disabled while any `ModalScreen` is active so other modals can own tab-like keys. As a result, the
two help-style popup panels do not support tab switching while focused:

- `?` opens `HelpModal`.
- `,?` opens `TabGuideModal`.

When these panels are focused, `next_tab` / `prev_tab` should switch the underlying ACE tab exactly like they do outside
the panels, then update the panel content to match the newly active tab as though the user had opened that panel on that
tab.

## Current Findings

- `AceApp.check_action()` intentionally returns `False` for `next_tab` / `prev_tab` whenever `self.screen` is a
  `ModalScreen`; this should remain broadly true so unrelated modals keep their own tab behavior.
- Main tab switching lives in `BasicNavigationMixin.action_next_tab()` and `action_prev_tab()`.
- `action_next_tab()` has an Agents-tab special case: if a tracked artifact tmux pane can be focused, it records input
  and returns without changing tabs. Popup-panel tab handling should call the same action so this behavior is preserved.
- `HelpModal` already has dynamic `on_mount()` binding reconstruction for configured query-history keys, and its content
  is built from `_current_tab`.
- `TabGuideModal` currently has static modal bindings and builds one guide widget from `_current_tab`.
- `AceApp.watch_current_tab()` currently tries to refresh an open `HelpModal` by dismissing and re-pushing it, but this
  path does not help today because modal screens suppress the app-level tab actions before the tab changes.

## Plan

1. Keep global modal suppression in place.

   Do not loosen `AceApp.check_action()` for all modals. Instead, make only `HelpModal` and `TabGuideModal` explicitly
   opt into configured tab-switch keys. This avoids regressions in modals where `tab` is used for focus traversal,
   insertion, completion, or modal-local navigation.

2. Add modal-local tab-switch bindings for the two popup panels.

   In both `HelpModal` and `TabGuideModal`, build instance bindings from the active `KeymapRegistry` and add bindings
   for:
   - `registry.app.next_tab` -> modal action `next_tab`
   - `registry.app.prev_tab` -> modal action `prev_tab`

   These should use configured keys rather than hard-coded `tab` / `shift+tab`, matching existing keymap override
   behavior.

3. Route modal tab actions through the same app actions.

   Implement modal actions that call `self.app.action_next_tab()` and `self.app.action_prev_tab()` on the containing
   `AceApp`.

   This preserves the existing tab order, saved-position behavior, input-activity accounting, tab-specific refresh
   behavior, and the Agents artifact-pane special case.

4. Replace the brittle `HelpModal` dismiss/re-push behavior with explicit in-place refresh.

   Add a small refresh/update method on `HelpModal` that accepts the new tab and active query, updates `_current_tab` /
   `_active_query`, and refreshes the rendered title and columns in place.

   Give the existing left/right column statics stable IDs so the refresh method can update them without reconstructing
   the whole screen. Update the footer text to document the newly supported tab-switch keys using the configured display
   names.

5. Add an in-place tab-context refresh path for `TabGuideModal`.

   Add a refresh/update method that accepts the new tab, registry, and Agents-guide state, updates `_current_tab`,
   updates the modal border title/classes, and rebuilds the single guide widget for the newly active tab.

   Reuse the same Agents-guide state that `,?` uses today (`_agents_onboarding_launch_targets_available` and
   `_agents_onboarding_plugins_installed`). When switching into the Agents tab while the guide is open, make the app run
   the same scheduling/preparation logic it runs before opening the guide so the refreshed guide is as close as possible
   to a newly opened `,?` guide.

6. Centralize popup-panel refresh from `watch_current_tab()`.

   Update `AceApp.watch_current_tab()` so after the underlying tab view changes it checks the active screen:
   - If it is a `HelpModal`, call the modal's in-place refresh method with `new_tab` and `canonical_query_string`.
   - If it is a `TabGuideModal`, call the modal's in-place refresh method with `new_tab`, the active keymap registry,
     and current guide state.

   This keeps modal content correct whether tab changes originate from the modal-local bindings or another future
   tab-switch path while one of these screens is active.

7. Add focused regression tests.

   Add unit-level tests for the modal refresh methods:
   - `HelpModal` switches its internal tab and rebuilt help sections to the requested tab.
   - `TabGuideModal` switches its internal tab and builds the correct guide widget for the requested tab.

   Add app/pilot coverage for the actual key behavior:
   - With `HelpModal` open, pressing configured next/previous tab keys changes `app.current_tab` and updates visible
     help content to the new tab.
   - With `TabGuideModal` open, pressing configured next/previous tab keys changes `app.current_tab` and updates visible
     guide content to the new tab.
   - Use an override of `ace.keymaps.app.next_tab` / `prev_tab` in at least one test to ensure popup bindings honor
     configuration rather than only defaults.

8. Verify.

   After code changes, run:
   - `just install`
   - targeted pytest for the new/changed modal and tab-navigation tests
   - `just check`

   `just check` is required because this plan changes repo files outside the documented exceptions.

## Risks and Notes

- Avoid enabling tab switching for every modal. The existing global suppression is intentional and protects other modal
  interactions.
- Avoid hard-coding `tab` and `shift+tab`; the keymap registry is the source of truth.
- If `action_next_tab()` focuses a tracked artifact tmux pane and leaves `current_tab` unchanged, the modal should
  remain on the same content. That matches outside-panel behavior because the tab did not change.
- The help popup documentation must stay in sync with this new behavior per ACE help-popup maintenance rules.
