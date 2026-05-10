---
create_time: 2026-05-10 01:37:47
status: wip
prompt: sdd/prompts/202605/png_only_visual_snapshots_completion.md
---
# Complete PNG-only ACE visual snapshots

## Context

Verification of bead `sase-2p` found that earlier agent transcripts claimed completion, but this checkout still exposes
the SVG visual snapshot API and contains the SVG helper, SVG tests, and SVG goldens. The parent epic and children remain
open/in-progress. The implementation should complete the original epic in the current workspace.

## Plan

1. Replace the public visual snapshot API with PNG-only assertions.
   - Remove the `ace_visual` SVG fixture.
   - Rename the page capture convenience method to `assert_page_png`.
   - Keep Textual SVG export and `source_svg` failure artifacts only as PNG rasterization/debug internals.

2. Convert the full-screen ACE visual suite to PNG.
   - Rename the SVG test module to `test_ace_png_snapshots.py`.
   - Use `ace_png_visual.assert_page_png(...)` for the four deterministic ACE states.
   - Generate and commit PNG goldens in `tests/ace/tui/visual/snapshots/png/`.

3. Remove SVG snapshot support.
   - Delete the SVG helper, SVG helper tests, old SVG full-screen tests, and `snapshots/svg/`.
   - Sweep live test/docs/CI/config wording for stale SVG snapshot API references.

4. Verify and update completion metadata.
   - Run focused visual helper tests, full visual tests, and the repo check.
   - Update `sdd/epics/202605/png_only_visual_snapshots.md` frontmatter `status` to `done`.
   - Close all `sase-2p.*` child beads if the implementation is verified.

5. Close the bead.
   - Close parent epic bead `sase-2p`.
   - After the epic is closed, run `just pyvision` if available to catch unused code left hidden while the epic was
     open.
