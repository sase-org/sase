---
create_time: 2026-06-15 19:03:13
status: done
prompt: sdd/prompts/202606/view_selected_images.md
---
# Display `v`-Selected Images With The Artifact Viewer

## Goal

When a user selects an image file through the ACE TUI `v` view-file hint flow, SASE should not pipe the image through
`bat` or `cat`. Image selections should use the same terminal image rendering stack used for image artifacts, and the
rendered image must remain visible until the user explicitly dismisses the viewer.

## Current Behavior

- `v` enters hint mode through `FileViewingMixin.action_view_files()`.
- Submitted hints are parsed in `InputProcessingMixin._process_view_input()`.
- Normal view selections call `FileViewingMixin._view_files_with_pager()`.
- `_view_files_with_pager()` shells out to `bat --color=always ... | less -R` or `cat ... | less`, which is correct for
  text but wrong for image binaries.
- SASE already has reusable image/artifact viewer code in `src/sase/ace/tui/graphics/`:
  - `view_image_file()` and `view_artifact_files()` render images through `kitten icat`.
  - The artifact page loop prints a prompt and blocks until explicit input (`q`, plus navigation keys for sequences).
  - Notification image attachments already use `with app.suspend(): view_image_file(path)`.

## Design

1. Keep editor and clipboard suffix behavior unchanged.
   - Inputs ending in `@` still open selected files in `$EDITOR`.
   - Inputs ending in `%` still copy selected paths.

2. Add image-aware routing to the normal view path.
   - After `parse_view_input()` returns selected files, classify expanded paths with the existing
     `is_supported_image_path()` helper.
   - If the selection contains no supported image paths, preserve the existing text pager behavior.
   - If the selection contains at least one supported image path, route the entire selected sequence through the
     artifact viewer rather than sending any selected image to `bat`/`cat`.

3. Reuse the artifact viewer instead of adding a second image renderer.
   - Build `ArtifactViewSpec` entries for the selected paths.
   - Use `kind="image"` for supported image paths.
   - Use `kind="file"` or no explicit kind for non-images in the same mixed selection so markdown, PDF, and text files
     continue to be handled by the artifact viewer's existing mode detection.
   - Call `view_artifact_files()` under `with self.suspend():`, matching the current pager flow and the notification
     image attachment flow.

4. Preserve the "review as long as needed" contract.
   - The artifact viewer's image/page loop already keeps the terminal occupied until explicit user input.
   - For image selections this gives the user a stable prompt and prevents a fire-and-forget image render from appearing
     and immediately disappearing.
   - If implementation review shows the existing `q` prompt is too different from the requested "press enter to
     continue" wording, add Enter as a non-breaking alias for quitting the single-image viewer while keeping `q` and the
     existing artifact navigation keys.

5. Keep tmux behavior conservative for the `v` flow.
   - The current `v` file viewer opens in the same terminal via `suspend()`, even inside tmux.
   - The artifact split-pane tracking in `AgentPanelArtifactMixin` is Agents-tab-specific and also changes layout/focus
     behavior.
   - For this change, use the same-pane suspended artifact viewer for `v` selections. That reuses the artifact rendering
     stack without coupling ChangeSpecs-tab file viewing to the Agents-tab artifact-pane state machine.

6. Surface viewer failures through existing TUI notifications.
   - If `view_artifact_files()` returns a warning, call `notify(..., severity="warning")`.
   - Missing `kitten`, missing files, and unsupported artifact types should report through the existing structured
     viewer warning path.

## Performance And Responsiveness

- Do not add synchronous file reads, artifact scans, image probing, or subprocess calls to normal navigation/refresh
  paths.
- The only synchronous subprocess work remains inside `suspend()`, where the user has explicitly invoked an external
  viewer/pager.
- Image detection is extension-based through `is_supported_image_path()` and does not touch disk.
- No agent artifact cache, detail-panel refresh, or navigation code needs to change.

## Test Plan

1. Add focused unit tests around the hint view path:
   - Text-only selections still use the existing pager route.
   - Image-only selections call `view_artifact_files()` inside `suspend()` and do not invoke the text pager.
   - Mixed image/text selections call `view_artifact_files()` with the selected files in order.
   - Viewer warnings are surfaced with `notify(..., severity="warning")`.
   - `@` editor and `%` clipboard suffixes bypass the image viewer exactly as before.

2. Add artifact viewer loop tests only if Enter is added as an alias.
   - Verify Enter exits/continues without removing existing `q`, `j`, `k`, `n`, `p`, and `r` behavior.

3. Run targeted tests first, then repo validation after implementation:
   - `pytest tests/test_hints.py tests/ace/tui/actions/test_view_files_image.py`
   - `pytest tests/ace/tui/artifact_viewer`
   - `just check`
