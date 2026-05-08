---
create_time: 2026-05-08 17:38:32
status: done
prompt: sdd/prompts/202605/artifact_viewer_page_wrap.md
---
# Artifact Viewer Page Wrap Plan

## Context

The tmux artifact viewer is implemented in `src/sase/ace/tui/graphics/`.

The relevant page-navigation behavior currently lives in:

- `src/sase/ace/tui/graphics/_viewer_loop.py`
  - `page_index_after_key()` clamps `n` at the last page and `p` at the first page.
  - `page_loop_available_keys()` hides `n` on the last page and hides `p` on the first page.
  - `run_artifact_page_loop()` uses `page_index_after_key()`.
  - `run_artifact_sequence_loop()` currently reimplements `n`/`p` movement inline with `min()`/`max()`.
- `tests/ace/tui/test_artifact_viewer.py`
  - Covers the page state machine, prompt key visibility, direct page loop behavior, and multi-artifact sequence loop
    behavior.

The requested behavior is specifically for page navigation keys:

- When an artifact has more than one rendered page, `n` and `p` should always be available.
- Pressing `n` on the last page should cycle to the first page.
- Pressing `p` on the first page should cycle to the last page.
- Single-page artifacts should continue to omit `n` and `p`.
- Artifact navigation keys `N` and `P` are separate document navigation and are not part of this change.

## Implementation Plan

1. Update the page state machine in `_viewer_loop.py`.
   - Keep `q`, `r`, unknown keys, and single-page behavior unchanged.
   - Change `n` for `page_count > 1` to `(current_index + 1) % page_count`.
   - Change `p` for `page_count > 1` to `(current_index - 1) % page_count`.

2. Update key visibility in `_viewer_loop.py`.
   - In `page_loop_available_keys()`, add both `n` and `p` whenever `page_count > 1`.
   - Preserve the existing action ordering: page navigation, artifact navigation, refresh, quit.
   - Leave `N`/`P` visibility unchanged so artifact sequence navigation still only appears when there is a next or
     previous artifact.

3. Remove divergent page movement in `run_artifact_sequence_loop()`.
   - Route `n`, `p`, and `r` through `page_index_after_key()` instead of duplicating clamp logic inline.
   - Keep `q`, `N`, and `P` handling explicit.
   - Reset `page_index` to `0` when moving between artifacts, as it does today.

4. Update focused tests in `tests/ace/tui/test_artifact_viewer.py`.
   - Adjust `test_artifact_page_index_state_machine()` expectations so boundary `n`/`p` wrap.
   - Adjust `test_artifact_page_loop_available_keys_and_prompts()` so multi-page prompts always include both `n` and
     `p`.
   - Replace or rename the boundary-key test so it verifies wrapping instead of ignored unavailable keys.
   - Add or adjust sequence-loop coverage so page wrapping works inside the multi-artifact viewer path as well.

5. Verify.
   - Run the focused test file: `pytest tests/ace/tui/test_artifact_viewer.py`.
   - Because this repo asks for `just check` after code changes, run `just install` if needed, then `just check`.

## Risks and Notes

- The public helper `page_index_after_key()` is exported from both `graphics.viewer` and `graphics.__init__`, so
  changing it affects callers that rely on the helper. The tests already treat it as the canonical navigation state
  machine, and the new behavior matches the requested product behavior.
- The prompt output is part of tests, so expected text changes should be intentional and narrow.
- Multi-artifact navigation uses uppercase `N`/`P`; the lowercase page wrapping should not cause movement between
  artifacts.
