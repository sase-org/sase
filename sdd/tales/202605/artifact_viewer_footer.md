---
create_time: 2026-05-08 22:29:23
status: done
---
# Artifact Viewer Footer Plan

## Context

The artifact viewer opened from the TUI launches `python -m sase.ace.tui.graphics.viewer` in a tmux pane via
`view_artifact_files_in_tmux_pane()`. That entry point eventually calls `run_artifact_sequence_loop()` in
`src/sase/ace/tui/graphics/_viewer_loop.py`.

`run_artifact_sequence_loop()` currently renders two position indicators on every redraw:

- The header panel from `_print_artifact_header()`, which includes artifact position and page position when relevant.
- The footer prompt from `print_page_prompt()`, which prefixes the controls with strings like `Artifact 2/3  Page 2/3`.

The requested change is presentation-only TUI behavior, so it stays in this Python/Textual-side code rather than the
Rust core backend.

## Design

Keep the header as the single source of visible artifact/page position in the tmux artifact viewer.

Change the footer shown by `run_artifact_sequence_loop()` so it only lists available key actions, for example:

```text
n: next page  p: previous page  N: next artifact  P: previous artifact  r: refresh  q: quit
```

Do not remove the position prefix from the older `run_artifact_page_loop()` path, because that loop has no header and
would otherwise lose all page position context. The cleanest implementation is to add a small option to
`print_page_prompt()`, such as `show_position: bool = True`, and call it with `show_position=False` only from
`run_artifact_sequence_loop()`.

## Implementation Steps

1. Update `print_page_prompt()` in `src/sase/ace/tui/graphics/_viewer_loop.py` to support omitting the position prefix.
2. Pass the new option from `run_artifact_sequence_loop()` so tmux/multi-artifact viewer footers show only controls.
3. Leave `run_artifact_page_loop()` behavior unchanged by relying on the default `show_position=True`.
4. Update artifact viewer loop tests:
   - Keep direct `print_page_prompt()` expectations for the default position-bearing prompt.
   - Add or adjust an expectation for `show_position=False`.
   - Update sequence-loop assertions so they no longer expect `Artifact X/Y  Page X/Y` in the footer, while still
     asserting those values appear in the header.
5. Run focused tests:

```bash
pytest tests/ace/tui/artifact_viewer/test_loops.py tests/ace/tui/artifact_viewer/test_rendering.py
```

6. Because this repo requires it after code changes, run:

```bash
just install
just check
```

## Acceptance Criteria

- Opening artifacts in the tmux pane still shows artifact/page position in the header.
- The footer no longer repeats `Artifact X/Y` or `Page X/Y` in the sequence viewer.
- Single-page/standalone loop behavior remains unchanged where no header exists.
- Existing navigation keys still work exactly as before.
