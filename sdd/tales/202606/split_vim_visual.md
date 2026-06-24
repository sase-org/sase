---
create_time: 2026-06-23 20:13:15
status: done
prompt: sdd/prompts/202606/split_vim_visual.md
---
# Split Vim Visual-Mode Widget Module

## Context

`src/sase/ace/tui/widgets/_vim_visual.py` is currently a 724-line private module containing all visual-mode state,
selection math, operator execution, pending-key handling, text-object selection, motion dispatch, and the public
`VimVisualModeMixin` entrypoint used by `_vim_normal_pending.py`.

The nearby vim normal-mode code is already split into small mixin modules with a compatibility facade. The visual-mode
split should follow that pattern so callers keep importing `VimVisualModeMixin` from `_vim_visual.py`, while the actual
implementation is divided by responsibility. This should be a behavior-preserving refactor.

## Goals

- Keep every touched Python module at or below 500 lines.
- Preserve the existing import surface:
  - `from sase.ace.tui.widgets._vim_visual import VimVisualModeMixin`
  - `VisualKind` remains available from `_vim_visual.py`.
- Avoid changing visual-mode behavior, keybindings, selection semantics, dot-repeat behavior, registers, or clipboard
  behavior.
- Avoid introducing any synchronous work or new refresh path in the TUI event loop.
- Keep the inheritance chain compatible with the existing vim normal-mode mixin stack.

## Proposed Structure

Create these new private modules under `src/sase/ace/tui/widgets/`:

- `_vim_visual_state.py`
  - Owns `VisualKind`.
  - Defines `VimVisualStateMixin(VimNormalOpsMixin)`.
  - Moves visual-mode entry/exit state, range math, TextArea selection mirroring, display subtitle updates, cursor
    movement, explicit range selection, end swapping, and pre-operator collapse helpers.
  - Expected source: current `_vim_visual.py` lines 44-281.

- `_vim_visual_ops.py`
  - Defines `VimVisualOperatorMixin(VimVisualStateMixin)`.
  - Moves register storage, selected-text extraction, visual mutation recording, linewise replacement payloads, visual
    delete/change/yank, visual paste replacement, visual case operators, and visual indent/dedent operators.
  - Expected source: current `_vim_visual.py` lines 283-426.

- `_vim_visual_pending.py`
  - Defines `VimVisualPendingMixin(VimVisualOperatorMixin)`.
  - Moves visual pending-prefix handling for `g`, `f/F/t/T`, `ae`, `iw`/`aw`/`iW`/`aW`, paragraph objects, quote/bracket
    text objects, and character search execution.
  - Expected source: current `_vim_visual.py` lines 436-537.

- `_vim_visual_keys.py`
  - Defines `VimVisualKeyHandlingMixin(VimVisualPendingMixin)`.
  - Moves count consumption and the top-level `_handle_visual_mode_key()` dispatcher for visual mode.
  - Expected source: current `_vim_visual.py` lines 428-434 and 539-724.

Then shrink `_vim_visual.py` to a facade:

```python
"""Vim visual-mode key handling for PromptTextArea."""

from __future__ import annotations

from sase.ace.tui.widgets._vim_visual_keys import VimVisualKeyHandlingMixin
from sase.ace.tui.widgets._vim_visual_state import VisualKind


class VimVisualModeMixin(VimVisualKeyHandlingMixin):
    """Compatibility facade for vim visual-mode key handling."""


__all__ = ["VisualKind", "VimVisualModeMixin"]
```

## Dependency Shape

The intended import chain is one-way:

`_vim_visual.py` -> `_vim_visual_keys.py` -> `_vim_visual_pending.py` -> `_vim_visual_ops.py` -> `_vim_visual_state.py`
-> `_vim_normal_ops.py`

This preserves the current normal-mode dependency where `_vim_normal_pending.py` imports only `_vim_visual.py`.

Each new module should import only the helper functions it uses. Keep `TYPE_CHECKING` blocks local and minimal instead
of centralizing a large protocol unless type checking exposes substantial duplication.

## Implementation Steps

1. Add `_vim_visual_state.py` and move the selection/state helpers first.
   - Move `VisualKind` here.
   - Keep `_vim_visual.py` temporarily importing and subclassing this new mixin if doing the split incrementally.

2. Add `_vim_visual_ops.py` and move visual operator helpers.
   - Import `Selection`, `copy_to_system_clipboard`, `first_non_blank_col`, and `apply_case_operator` here.
   - Confirm paste replacement still stores the replaced text before applying the register.

3. Add `_vim_visual_pending.py` and move pending-prefix/text-object helpers.
   - Import word/WORD/paragraph functions, quote/bracket text-object helpers, and character search helpers here.

4. Add `_vim_visual_keys.py` and move `_visual_count()` plus `_handle_visual_mode_key()`.
   - Import `Key`, word/WORD motion functions, paragraph boundary functions, and `find_matching_bracket` here.

5. Replace `_vim_visual.py` with the facade class and `__all__`.

6. Run formatting and verification.

## Verification

After implementing code changes, run:

```bash
just install
pytest tests/test_prompt_visual_mode.py \
  tests/test_prompt_normal_mode_paragraphs.py::test_visual_paragraph_motion_extends_selection \
  tests/test_prompt_normal_mode_paragraphs.py::test_vip_selects_whole_paragraph_lines \
  tests/test_prompt_normal_mode_paragraphs.py::test_vap_selects_paragraph_plus_trailing_blanks \
  tests/test_prompt_normal_mode_percent.py::test_visual_percent_extends_selection_to_match
just check
```

The targeted tests cover visual entry/exit, charwise and linewise ranges, text objects, paragraph selection, bracket
matching, operators, paste replacement, case conversion, indentation, and visual dot-repeat. `just check` is required by
repo instructions after code changes.

## Risks

- Import cycles are the main refactor risk. Keep `_vim_normal_pending.py` importing only the facade module, and keep the
  new visual modules flowing downward into `_vim_normal_ops.py`.
- The selected-text and mutation helpers depend on exact ordering around `_collapse_visual_before_operator()`,
  `_store_visual_register()`, and `_record_mutation()`. Move code without reordering those calls.
- The facade should re-export `VisualKind`; hidden callers or tests may import it from `_vim_visual.py` even though the
  symbol is private.
