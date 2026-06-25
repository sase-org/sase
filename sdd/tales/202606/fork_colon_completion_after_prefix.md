---
create_time: 2026-06-25 10:11:18
status: done
prompt: sdd/prompts/202606/fork_colon_completion_after_prefix.md
---
# Fix `#fork:` Agent Completion After Earlier XPrompt References

## Problem

`#fork:` agent-name completion now works at the beginning of the prompt, and it also works after ordinary free text, but
it fails in the common prompt shape where `#fork:` follows another xprompt reference such as:

```text
#gh:sase #fork:
```

In the actual widget path, `Ctrl+T` falls through to file-history completion instead of opening the `fork agent` menu.
The pure `#fork:` trailing-text tests missed this because their fixture only included the `fork` entry, so there was no
earlier catalog xprompt to interfere with detection.

## Root Cause

`detect_xprompt_arg_completion_at_cursor()` scans parsed xprompt references in source order. For `#gh:sase #fork:`, the
parser yields:

1. `#gh:sase`
2. `#fork`

The detector reaches the earlier `#gh` reference first. Because `#gh` is a known catalog xprompt and the text from the
`#gh` base to the cursor begins with `:`, the detector calls `_colon_completion_context(...)` and immediately returns
its result.

That result is `None` because the suffix is effectively:

```text
:sase #fork:
```

and colon completion intentionally rejects whitespace in a positional colon argument. Returning that `None` stops the
scan before the detector ever reaches the real reference under the cursor, `#fork`.

This is not a parser or absolute-offset bug. The parser and widget cursor offset are correct; the detector is treating
an invalid earlier colon-looking reference as a terminal answer.

## Design

Update xprompt argument completion detection so a rejected earlier reference does not block a later reference that is
actually at the cursor.

The important boundary is double-colon free-text shorthand. `#ask:: ...` consumes free text through the rest of the
parsed shorthand span, and nested `#...` text inside that body must not become active xprompt completion. The fix should
therefore:

1. Continue scanning when a colon or paren completion context for an earlier normal reference returns `None`.
2. Preserve a hard stop when the cursor is inside or at the end of a `DOUBLE_COLON_SHORTHAND` reference span, so
   `#ask:: after #fork:` does not open a fork-agent menu inside the free-text body.
3. Keep the existing trailing-text behavior for `#fork: bar`, including the case where the cursor is immediately after
   the colon and parsed trailing text is to the right.

This is a pure hot-path change only: no disk I/O, catalog rebuilds, subprocesses, or event-loop work should be added.

## Implementation Steps

1. Add a targeted pure regression test in `tests/ace/tui/widgets/test_xprompt_arg_assist.py` for a real preceding
   xprompt-like entry:
   - entries include both `gh` and `fork`
   - prompt is `#gh:sase #fork:`
   - cursor is after `#fork:`
   - detected completion kind is `xprompt_arg_agent`

2. Add a widget-level regression in `tests/ace/tui/widgets/test_xprompt_arg_value_completion.py`:
   - use the real or fixture-equivalent `#gh:sase #fork:` shape
   - seed both `gh` and `fork` assist entries
   - seed visible agent candidates
   - assert `Ctrl+T` / `_try_file_completion_tab()` opens `xprompt_arg_agent` completion instead of file history

3. Add an explicit negative regression for double-colon text:
   - `#ask:: after #fork:` with cursor after the inner `#fork:`
   - assert xprompt arg completion is `None`, or at widget level assert no fork-agent menu opens

4. Change `detect_xprompt_arg_completion_at_cursor()` so it stores the result of `_colon_completion_context(...)` or
   `_paren_completion_context(...)` in a local variable and only returns it when non-`None`; otherwise it continues to
   the next parsed reference.

5. Add an explicit double-colon-span guard before attempting suffix completion: when
   `ref.arg_kind is XPromptReferenceArgKind.DOUBLE_COLON_SHORTHAND` and `ref.start < cursor_offset <= ref.end`, return
   `None` to prevent nested completion inside free-form text.

6. Keep the rest of the detector unchanged. In particular, do not change catalog loading, widget event ordering, or
   file-history fallback behavior.

## Verification

Run:

```bash
just install
pytest tests/ace/tui/widgets/test_xprompt_arg_assist.py tests/ace/tui/widgets/test_xprompt_arg_value_completion.py
just check
```

`just install` has already been run in this workspace during diagnosis, but it should remain in the verification
sequence because this repo requires it before full checks in ephemeral workspaces.
