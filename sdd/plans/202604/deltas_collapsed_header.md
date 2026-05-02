---
create_time: 2026-04-30 12:32:25
status: done
prompt: sdd/prompts/202604/deltas_collapsed_header.md
---
# Plan: Preserve the DELTAS Header When Collapsed

## Problem

When a ChangeSpec has DELTAS entries and the DELTAS fold state is `COLLAPSED`, the TUI detail panel currently omits the
entire DELTAS section. This makes it look like the ChangeSpec has no DELTAS field at all, even though entries exist and
are merely folded.

The desired behavior is that a ChangeSpec with non-empty DELTAS always shows at least the `DELTAS:` field line.
Collapsed DELTAS should hide the individual file entries, but not hide the existence of the field.

## Current Shape

The relevant rendering path is:

- `src/sase/ace/tui/widgets/changespec_detail.py`
  - calls `build_deltas_section(...)` between COMMITS and HOOKS.
- `src/sase/ace/tui/widgets/deltas_builder.py`
  - returns immediately for `FoldLevel.COLLAPSED`, producing no text.
- `tests/ace/tui/test_deltas_builder.py`
  - currently asserts collapsed DELTAS renders nothing.

The ChangeSpec app default is `deltas_collapsed = FoldLevel.EXPANDED`, but fold-mode commands can collapse all sections
or collapse DELTAS directly, triggering the hidden-field behavior.

## Intended Behavior

For ChangeSpecs with `changespec.deltas` set to a non-empty list:

- `COLLAPSED`: render `DELTAS:\n` only.
- `EXPANDED`: keep the current header plus summary behavior.
- `FULLY_EXPANDED`: keep the current header plus full path list behavior.

For ChangeSpecs with `changespec.deltas is None` or `[]`, continue rendering nothing. This preserves the current
distinction between absent/no-op DELTAS and present-but-folded DELTAS.

## Implementation

1. Update `build_deltas_section` in `src/sase/ace/tui/widgets/deltas_builder.py`.
   - Keep the early return for `not deltas`.
   - Move the `DELTAS:` header append before the collapsed branch.
   - For `FoldLevel.COLLAPSED`, append a newline and return without summary or entries.
   - Update the docstring to describe the new collapsed behavior.

2. Update focused tests in `tests/ace/tui/test_deltas_builder.py`.
   - Replace the collapsed test that expects empty output with an assertion that collapsed output is exactly
     `DELTAS:\n`.
   - Assert the collapsed output does not include summary counts or file paths.
   - Keep existing `None` and empty-list tests unchanged.

3. Run targeted validation.
   - `pytest tests/ace/tui/test_deltas_builder.py`

4. Run repository validation required by local instructions after changes.
   - Run `just install` if needed for this workspace.
   - Run `just check`.

## Risk

This is a small rendering-only change. It should not alter parsing, DELTAS persistence, fold key handling, or ChangeSpec
data models. The main visual impact is that fully collapsed ChangeSpec detail panels can gain one visible `DELTAS:` line
when DELTAS entries exist, which is the requested behavior.
