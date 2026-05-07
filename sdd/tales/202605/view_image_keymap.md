---
create_time: 2026-05-07 17:57:11
status: done
prompt: sdd/prompts/202605/view_image_keymap.md
---
# Add `V` View Image Keymap

## Goal

Add a `V` keymap that, when an image preview is currently visible in the TUI, suspends Textual, runs `kitten icat` for
the underlying image file, and waits for the user to press any key before returning to the TUI.

The first supported surfaces are:

- Agents tab file panel, when the current file panel entry is an image attachment.
- Notification modal right-hand file preview, when the highlighted notification's current attachment is an image.

## Existing Shape

Image detection already exists in `sase.ace.tui.graphics.images.is_supported_image_path()` and is used by:

- `AgentFilePanel.display_static_file()` / `_display_static_image()`
- `NotificationAttachmentMixin._display_file()` / `_display_image_file()`

Both surfaces already track the currently selected file:

- Agents file panel: `AgentFilePanel.get_current_file_path()` returns the expanded file path for non-live-diff entries.
- Notification modal: `NotificationAttachmentMixin` uses `_get_highlighted_notification()` plus `_current_file_index`.

The keymap layer is config-driven:

- App defaults live in `src/sase/default_config.yml`.
- App keymap fields live in `src/sase/ace/tui/keymaps/types.py`.
- Command palette metadata must cover every `AppKeymaps` field.
- Help and footer labels are manually maintained.

Important constraint: `V` is currently bound to `toggle_attempt_view` on the Agents tab. The keymap loader rejects
duplicate app bindings, so the implementation cannot add a second app-level `V` binding without resolving that conflict.

## Design

### 1. Add a shared image viewer helper

Create a small TUI-facing helper, for example `src/sase/ace/tui/graphics/viewer.py`, with two responsibilities:

- Validate that a path is a supported image path and exists.
- Run an interactive shell command while the TUI is suspended:

```bash
kitten icat "$path"; printf "\nPress any key to return to SASE..."; read -r -n 1
```

Use `subprocess.run(..., shell=False)` where practical. If waiting for any key is easier portably through the shell,
keep the shell script tiny and quote the path with `shlex.quote`.

Behavior:

- Missing/unsupported image returns a clear status result rather than raising.
- Missing `kitten` reports a warning toast.
- Non-zero `kitten icat` exits report a warning toast after returning.
- The helper does not know about Textual widgets; callers provide the suspend context.

### 2. Expose "current visible image" on both surfaces

Agents tab:

- Add `AgentFilePanel.get_current_image_path() -> str | None`.
- It should return the expanded current file path only when:
  - the file panel is currently displaying a real file, not the live-diff sentinel;
  - the expanded path has a supported image extension;
  - the file exists.
- Add `AgentDetail.get_current_image_path() -> str | None` that delegates only when the file panel is visible.

Notification modal:

- Add a private helper such as `_get_current_image_path()` to `NotificationAttachmentMixin`.
- It should inspect the highlighted notification, `_current_file_index`, expand `~`, and return the path only when the
  current attachment is a supported existing image.

These helpers should use `is_supported_image_path()` so the keymap behavior stays in sync with existing preview support.

### 3. Add a contextual app action for `V`

Add an app-level action named `view_image`:

- `AppKeymaps.view_image`
- `_BINDING_META` entry: `("view_image", "View Image", False)`
- `src/sase/default_config.yml`: `view_image: "V"`
- `src/sase/ace/tui/commands/catalog.py` metadata: label `View image`, category `Display`, tabs `("agents",)`.
- `src/sase/ace/tui/commands/availability.py`: available on the Agents tab only when context extraction can know an
  image is visible. If current command context does not expose this yet, keep the command conservatively visible on
  Agents and let the action validate at runtime.

Resolve the existing `V` conflict by changing the `toggle_attempt_view` default to a non-conflicting key, or by making
`view_image` the single `V` binding and providing attempt-view fallback inside the action.

Recommended resolution:

- Bind `view_image` to `V`.
- Move `toggle_attempt_view` to a new default key only if the product owner wants a dedicated attempt-history shortcut.
- Preserve muscle memory pragmatically by making `action_view_image()` fall back to `action_toggle_attempt_view()` on
  the Agents tab when no image is visible and the selected agent has attempt history.

This gives `V` the requested behavior whenever an image is visible while avoiding a hard regression for existing `V`
attempt-view users on non-image rows.

### 4. Implement the Agents tab action

Add `action_view_image()` in `AgentPanelsMixin`:

1. No-op outside the Agents tab.
2. Query `#agent-detail-panel`.
3. Ask `agent_detail.get_current_image_path()`.
4. If present, suspend the app and run the shared viewer helper.
5. Show warning toasts for missing image, unsupported image, missing `kitten`, or failed command.
6. If no image is visible, fall back to the existing attempt-view behavior when applicable; otherwise warn
   `No image visible`.

This action should not modify panel state or refresh file content unless it falls back to attempt view.

### 5. Implement notification modal `V`

Add `("V", "view_image", "View Image")` to `NotificationModal.BINDINGS`.

Add `NotificationAttachmentMixin.action_view_image()`:

1. Resolve `_get_current_image_path()`.
2. If absent, notify `No image visible`.
3. If present, use `self.app.suspend()` and run the shared viewer helper.
4. Re-display the current file afterward only if needed; suspending and returning should normally leave state intact.

Update `DEFAULT_HINT_TEXT` to include `V: view image` without making the footer too long.

### 6. Footer and help updates

Agents footer:

- When the file panel is currently showing an image, show `V view image`.
- Otherwise continue showing `V attempt view` only when the fallback is available, or show the new key assigned to
  `toggle_attempt_view` if that action is moved.

The current footer inputs do not include file-panel state, so this may require passing a `has_visible_image` boolean
from the Agents tab refresh path into `KeybindingFooter.update_agent_bindings()`.

Help modal:

- Agents tab help should document `V View image` and the attempt-view fallback or new attempt-view key.

Image fallback text:

- Update `ImageFallbackRenderable` from `Open with e in notifications or %E in agent panels` to mention `V` as the
  direct image viewer.

### 7. Tests

Add focused unit tests rather than broad TUI integration:

- `AgentFilePanel.get_current_image_path()` returns an expanded image path only for the selected image file, not for
  live diff or text files.
- `NotificationAttachmentMixin._get_current_image_path()` returns the highlighted current image attachment and tracks
  `_current_file_index`.
- Agents `action_view_image()` calls the shared viewer with suspend when an image is visible.
- Notification `action_view_image()` calls the shared viewer with `self.app.suspend()` when an image is visible.
- Missing/non-image cases notify and do not run `kitten`.
- Keymap consistency tests updated for the new `view_image` field and the `V` conflict resolution.
- Footer/help tests updated so visible image state advertises `V view image`.

Run at minimum:

```bash
just install
pytest tests/ace/tui/test_image_file_panels.py tests/test_notification_modal_actions.py tests/test_keymaps.py tests/test_keybinding_footer_agent.py tests/test_command_availability.py
just check
```

Per repository memory, run `just check` before finishing after implementation changes.

## Open Decision

The only product decision is what to do with the existing `V` attempt-view binding. My recommended implementation is a
contextual `V`: view the image when one is visible, otherwise preserve existing attempt-view behavior when available.
This matches the requested mnemonic without making attempt history disappear.
