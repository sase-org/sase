---
create_time: 2026-05-08 22:37:31
status: done
---
# Artifact Viewer j/k and n/p Navigation Plan

## Goal

Update the terminal artifact viewer navigation so page movement uses `j`/`k`, and artifact movement uses lowercase
`n`/`p` instead of uppercase `N`/`P`.

Current behavior:

- `n`: next page
- `p`: previous page
- `N`: next artifact
- `P`: previous artifact
- `r`: refresh
- `q`: quit

Target behavior:

- `j`: next page
- `k`: previous page
- `n`: next artifact
- `p`: previous artifact
- `r`: refresh
- `q`: quit

This applies to the artifact viewer key loop and footer prompt text. The existing sequence viewer header positioning
should remain unchanged: artifact/page position stays in the header, not duplicated in the sequence footer.

## Context

The relevant implementation is in `src/sase/ace/tui/graphics/_viewer_loop.py`.

- `page_index_after_key()` maps page movement keys to page index changes.
- `page_loop_available_keys()` builds the allowed key tuple for both page-only and sequence views.
- `run_artifact_sequence_loop()` branches on page keys versus artifact keys.
- `print_page_prompt()` renders footer labels from the available keys.

The public wrapper in `src/sase/ace/tui/graphics/viewer.py` re-exports these helpers but does not define the mapping.

The focused tests are in `tests/ace/tui/artifact_viewer/test_loops.py`.

## Design

Keep the change local to the artifact viewer loop module and tests.

1. Change `page_index_after_key()` so it treats `j` as next page and `k` as previous page.
   - Keep `key.lower()` normalization for quit/refresh and harmless uppercase input.
   - Stop treating `n`/`p` as page movement.

2. Change `page_loop_available_keys()` ordering and contents.
   - For multi-page artifacts, return `j`, then `k`.
   - For multi-artifact sequences, return lowercase `n` when a next artifact exists and lowercase `p` when a previous
     artifact exists.
   - Keep `r` and `q` unchanged.

3. Change `run_artifact_sequence_loop()` key handling.
   - Page keys become `j`, `k`, and `r`.
   - Artifact keys become `n` and `p`.
   - Preserve page reset to `0` when moving between artifacts.
   - Preserve clamping at sequence boundaries through `page_loop_available_keys()` plus the existing min/max protection.

4. Change `print_page_prompt()` labels.
   - `j: next page`
   - `k: previous page`
   - `n: next artifact`
   - `p: previous artifact`
   - `r: refresh`
   - `q: quit`

No default config update is expected because this viewer is a standalone terminal loop rather than the configurable ACE
Textual keymap. No help popup update is expected unless a search finds artifact viewer key documentation in a help modal
or docs page; if found during implementation, update that text too.

## Tests

Update focused tests in `tests/ace/tui/artifact_viewer/test_loops.py`.

- `test_artifact_page_index_state_machine`
  - Assert `j` advances pages and wraps forward.
  - Assert `k` moves backward and wraps backward.
  - Assert `n` and `p` no longer move pages in page-only state-machine context.

- `test_artifact_page_loop_available_keys_and_prompts`
  - Update expected available-key tuples for page-only and sequence contexts.
  - Update prompt assertions from `n/p` page labels to `j/k` page labels.
  - Update artifact prompt assertions from `N/P` to lowercase `n/p`.
  - Preserve the `show_position=False` footer assertion for sequence mode.

- `test_run_artifact_page_loop_redraws_and_tracks_keys`
  - Use `j`, then `k`, then `q`.

- `test_run_artifact_page_loop_wraps_boundary_keys`
  - Use `k`, then `j`, then `q`.

- `test_run_artifact_sequence_loop_navigates_pages_and_artifacts`
  - Use a sequence like `k`, `j`, `n`, `p`, `q`.
  - Update footer string assertions to expect `j: next page  k: previous page  n: next artifact`.

## Verification

After implementation, run:

```bash
just install
.venv/bin/python -m pytest tests/ace/tui/artifact_viewer/test_loops.py tests/ace/tui/artifact_viewer/test_rendering.py
just check
```

`just install` is included because this workspace may be stale and the repo memory warns that each `sase_<N>` workspace
has its own virtual environment.

## Risks

- The `n/p` keys are changing meaning in sequence mode. Tests should explicitly prevent an accidental mixed mapping
  where `n/p` still move pages.
- Single-artifact multi-page viewing will no longer accept `n/p` for page navigation. This matches the requested mapping
  but is a user-visible muscle-memory change.
- If any docs outside the focused tests mention artifact viewer keys, implementation should update them in the same
  change.
