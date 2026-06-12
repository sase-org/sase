---
create_time: 2026-06-12 12:45:29
status: done
prompt: sdd/prompts/202606/vcs_mru_cycling_anywhere.md
---
# Plan: Make `<ctrl+p>`/`<ctrl+n>` VCS MRU cycling work in (almost) any prompt

## Problem

In the `sase ace` prompt input widget (`PromptTextArea`), `<ctrl+p>`/`<ctrl+n>` cycle the prompt through the VCS xprompt
workflow MRU stack (`~/.sase/vcs_xprompt_mru.json`, loaded via `load_launchable_vcs_xprompt_mru()`), but **only** when
the prompt is empty or consists solely of a VCS workflow tag (`src/sase/ace/tui/widgets/prompt_text_area.py:341-379`).
As soon as the user has typed any prompt body (e.g. `#gh:sase fix the bug`), the keymaps silently stop working — even
though "swap which project/PR this prompt targets" is exactly as useful mid-composition as it is on an empty bar.

## Desired behavior

`<ctrl+p>`/`<ctrl+n>` should work essentially **always** in the prompt input widget:

1. **Replace case** — the prompt contains a current VCS xprompt workflow invocation (e.g. `#gh:sase`): replace _only
   that tag_ with the next/previous entry from the MRU stack, leaving every other character of the prompt untouched
   (directives, prompt body, later `---` segments, other VCS tags).
2. **Prepend case** — the prompt has text but no VCS workflow tag: prepend the next/previous MRU entry to the prompt (so
   `fix the bug` becomes `#gh:sase fix the bug`). Subsequent presses then hit the replace case and keep cycling that
   prepended tag.
3. **Empty prompt** — unchanged from today: the bar text becomes `"<mru[i]> "`.

"Current VCS xprompt workflow" = the **first** VCS workflow tag in the prompt text. This mirrors the launch flow, which
resolves the workspace from the first ref-pattern match in the submitted prompt (`_launch_body.py` ref search /
`_resolve_vcs_from_prompt`), so what the widget edits is exactly what launch will use.

## Design

### Trigger conditions (what stays gated)

- INSERT mode only (NORMAL-mode keys keep their vim dispatch), as today.
- File-completion popup takes precedence: while `_file_completion_active`, `<ctrl+p>`/`<ctrl+n>` keep navigating
  completion candidates, as today.
- **Feedback mode is excluded** (`bar._mode == "feedback"`): feedback text goes to a running agent, where a VCS tag is
  meaningless. This matches existing feedback-mode gating for the `#@` snippet trigger and `ctrl+y` workflow editor.
  (Today an empty feedback bar would happily cycle VCS prefixes in — this plan fixes that oddity rather than extending
  it.)
- Empty MRU stack → no-op (unchanged).

### Locating and replacing the current tag

- Add a span-aware helper to `src/sase/xprompt/_parsing_vcs_tags.py` (exported through `sase.xprompt._parsing` like its
  siblings), e.g. `find_vcs_workflow_tag_span(prompt) -> tuple[int, int] | None`, returning the character span of the
  **first** VCS workflow tag using the existing embedded tag pattern (`get_embedded_vcs_tag_pattern()`), with:
  - a sentinel space appended for matching (the tag patterns require trailing `\s`), so a tag at end-of-text still
    matches;
  - the returned span **excluding** the tag's trailing whitespace character, so replacing a tag followed by a newline
    preserves the newline.
- Replacement text is the raw MRU entry (e.g. `#gh:other`). When the tag sits at end-of-text, a single trailing space is
  ensured after it (preserving today's `"#git:bar "` result for VCS-only prompts). HITL suffixes (`!!`/`??`) and
  underscore/paren forms on the _old_ tag are replaced wholesale, matching today's VCS-only behavior.

### Prepend position

When no tag exists, the MRU entry + `" "` is inserted at the start of the prompt **body**: after a leading YAML
frontmatter block, leading whitespace, and any leading `%directive` tokens — reusing the same placement rules as
`normalize_default_vcs_workflow_segment()` / `_inherit_vcs_workflow_tag_segment()` so directives keep parsing.

### MRU index stepping (unchanged semantics)

- `<ctrl+p>` steps forward through the stack (toward older entries), `<ctrl+n>` steps backward, both wrapping —
  identical to today's direction/wrap logic.
- Continuity via the existing `_vcs_mru_index` field: a cycling streak continues from the last index; the index resets
  on any non-cycling keypress, submit, and NORMAL-mode entry (all existing reset points stay).
- When starting a streak with a current tag present, look the tag up in the MRU (after `.strip()` plus underscore→colon
  normalization via `normalize_vcs_underscore_refs()`) and step from its position; otherwise start at index 0
  (`<ctrl+p>`) / last (`<ctrl+n>`), as today.

### Cursor and selection

The current code jumps the cursor to end-of-text, which is fine for a VCS-only bar but hostile mid-composition. New
rules, applied via the widget's existing `_absolute_offset()` / `_location_from_absolute()` helpers:

- Cursor before the edited span → unchanged.
- Cursor inside the replaced tag → snaps to just after the new tag.
- Cursor at/after the span end (or after the prepend point) → shifted by the length delta, so it stays at the same
  logical spot in the prompt body.
- Any selection collapses to the cursor.
- Perform the edit through the TextArea document-replacement API (not whole-text reassignment) so undo history stays
  sane; clear/refresh soft completion, xprompt arg hints, and the prompt-completion timer after the edit so no stale
  hints survive the text change.

### Structure

Extract the whole `<ctrl+p>`/`<ctrl+n>` handling out of `_on_key` into a small widget mixin module (e.g.
`src/sase/ace/tui/widgets/_vcs_mru_cycling.py`), following the established `_file_completion.py` /
`_prompt_soft_completion.py` mixin pattern, with the text transformation itself as **pure functions** (text in → new
text + new cursor offset + new index out) so it is unit-testable without Textual. Parsing/span logic lives with the
other tag parsers in `sase/xprompt/_parsing_vcs_tags.py`.

Rust core boundary: this is presentation-layer prompt-editing glue around MRU state that already lives Python-side
(`sase/history/vcs_xprompt_mru.py`); no `sase-core` change is needed.

### Performance

Per `memory/long/tui_perf.md`: no new work is added to the typing hot path — the MRU load
(`load_launchable_vcs_xprompt_mru()`, file read + cached resolvability index) continues to run only on an explicit
`<ctrl+p>`/`<ctrl+n>` press, exactly as today. Ordinary keystrokes see the same single
`event.key in ("ctrl+n", "ctrl+p")` check that exists now.

## Edge cases covered

- `%n:a #gh:sase fix` → directives preserved, only the tag swapped.
- Tag on a later line / mid-line (embedded form) → that occurrence is replaced in place.
- Multi-segment prompts (`--- ` separators) with several tags → only the **first** tag changes.
- Tag followed by newline → newline preserved (span excludes trailing whitespace).
- Tag at end of text with no trailing space → still matched (sentinel), trailing space ensured.
- `#gh_sase` underscore and `#gh(ref)` paren forms → recognized and replaced wholesale.
- `#cd:<path>` prefixes → cycle like any other registered workflow tag (the `cd` plugin registers normal workflow
  metadata).
- Current tag not in the MRU → streak starts at the stack's most-recent end, as today.
- `#gh@ref` mobile shorthand is not a recognized tag form in the widget (same as today) → treated as "no tag", so the
  prepend case applies.
- Launch-side guards are untouched: cycled refs are pre-pruned by `load_launchable_vcs_xprompt_mru` and the
  unresolved-leading-tag abort in `_launch_body.py` stays the backstop.

## Files to touch

| File                                                             | Change                                                                                              |
| ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `src/sase/xprompt/_parsing_vcs_tags.py` (+ `_parsing` re-export) | `find_vcs_workflow_tag_span()`; prepend-offset helper reusing directive/frontmatter placement rules |
| `src/sase/ace/tui/widgets/_vcs_mru_cycling.py` (new)             | Mixin + pure cycle-text functions (replace/prepend, cursor math, index stepping)                    |
| `src/sase/ace/tui/widgets/prompt_text_area.py`                   | Replace inline cycling block with mixin call; feedback-mode gate; post-edit hint refresh            |
| `tests/ace/tui/widgets/test_prompt_vcs_mru_cycling.py`           | Extend pilot tests (see below)                                                                      |
| `tests/` (new module for pure functions)                         | Unit tests for the text transformation                                                              |
| `docs/ace.md` (~line 1780)                                       | Re-document: cycling now works with prompt text present (replace current tag / prepend)             |

## Test plan

Pilot-driven widget tests (extending the existing regression suite, which pins that the bar text is exactly what launch
will see):

- existing VCS-only and empty-prompt cases stay green (text and trailing-space expectations unchanged);
- `#git:foo fix the bug` + `<ctrl+p>` → `#git:bar fix the bug`, cursor stays at its logical spot;
- prepend: `fix the bug` → `#git:foo fix the bug`, then a second press replaces (streak continuity);
- directives, later-line tags, multi-segment multi-tag prompts (only first tag edited), newline preservation;
- feedback mode: no cycling/prepending;
- file-completion-active precedence unchanged.

Pure-function unit tests for span finding, cursor math, and index stepping (fast, no Textual).

## Verification

`just install` (fresh ephemeral workspace), then `just check`, plus targeted
`pytest tests/ace/tui/widgets/test_prompt_vcs_mru_cycling.py tests/test_vcs_xprompt_mru.py`.
