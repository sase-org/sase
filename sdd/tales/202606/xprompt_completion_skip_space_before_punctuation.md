---
create_time: 2026-06-29 13:16:52
status: done
prompt: sdd/prompts/202606/xprompt_completion_skip_space_before_punctuation.md
---
# Plan: Skip the auto-inserted space after a no-arg xprompt when followed by punctuation

## Problem / Product context

When a user selects an xprompt (e.g. `#foo`) from the prompt input widget's completion menu, and that xprompt has **no
required arguments**, the completion machinery inserts a trailing space after the reference (`#foo `). This is
convenient at end-of-line, but it produces an unwanted space when the completion lands immediately before punctuation.
For example, completing `#fo` inside `(#fo)` yields `(#foo )` — a stray space wedged before the `)`.

Desired behavior: only insert the trailing space when the character immediately following the inserted xprompt is
**not** punctuation (e.g. `)`, `.`, `!`, `,`, `:`, `]`, etc.). At end-of-line (no following character) or before an
ordinary character, the trailing space is still inserted, exactly as today.

## Current behavior (how it works today)

The trailing space is produced by a single branch in the completion-skeleton builder:

- `src/sase/ace/tui/widgets/_xprompt_arg_assist_skeletons.py` →
  `xprompt_completion_skeleton(entry, *, append_text_arg_space=False)`. When the entry has no **required** inputs
  (`required_inputs(entry)` is empty), it returns `f"{entry.insertion} "` — the reference plus a hard-coded trailing
  space. This branch covers **both** xprompts with no inputs at all **and** xprompts whose inputs are all optional
  (`has_only_optional_inputs(...)` is true — those also have no _required_ inputs).

This skeleton is consumed by **three** insertion paths, each of which already computes an `append_text_arg_space` flag
from the document and replaces the completion token range with the skeleton:

1. **Completion-menu / Tab accept** — `_accept_xprompt_completion_candidate(...)` in
   `src/sase/ace/tui/widgets/_file_completion_accept.py` (line ~64). Reached from `_accept_file_completion` (Enter/Tab
   accept of the highlighted menu candidate) and from the single-candidate auto-accept in
   `src/sase/ace/tui/widgets/_file_completion_open.py` (line ~286). This is the path the user's request is primarily
   about.
2. **Soft (inline ghost) completion accept** — `src/sase/ace/tui/widgets/_prompt_soft_completion.py` (line ~284).
3. **Smart snippet insert** — `_insert_xprompt_smart_snippet(...)` in
   `src/sase/ace/tui/widgets/_prompt_input_bar_actions.py` (line ~307), via `xprompt_completion_suffix_skeleton(...)`.

All three already have the document and the token's end position in hand, so each can cheaply determine the character
that will follow the inserted reference.

Relevant interaction: after expansion, the accept paths call `_note_optional_xprompt_spacer(entry)`
(`src/sase/ace/tui/widgets/_xprompt_arg_hints.py`). That method only records a "pending spacer" when the character just
before the cursor is a literal space. So when we suppress the space, it naturally records nothing — **no change is
needed there**.

## Design

Keep the policy in one place and feed it the one new piece of context — the following character — from each call site.

### 1. Centralize the rule in the skeleton builder

In `src/sase/ace/tui/widgets/_xprompt_arg_assist_skeletons.py`:

- Add a module-level set of "space-suppressing" characters and a tiny predicate, e.g. `_NO_ARG_SPACE_SUPPRESSING_CHARS`
  and `_suppresses_no_arg_space(next_char)`.
- Extend `xprompt_completion_skeleton(...)` with a new keyword-only parameter `next_char: str | None = None`. Only the
  **no-required-input** branch consults it:
  - `next_char is None` (end-of-line / not provided) → keep `f"{entry.insertion} "` (unchanged).
  - `next_char` is a suppressing punctuation char → return `entry.insertion` (no trailing space).
  - otherwise → `f"{entry.insertion} "` (unchanged).
  - All other branches (`::`, `:`, `()` for required-input shapes) ignore `next_char`, so their behavior is untouched.
- Forward `next_char` through `xprompt_completion_suffix_skeleton(...)` (the smart-snippet wrapper) so path 3 gets the
  same treatment.

The default `next_char=None` makes the change backward-compatible: every existing caller and test that does not pass it
keeps today's behavior.

**Punctuation set — decision to confirm during review.** Recommended default: Python's `string.punctuation`
(`!"#$%&'()*+,-./:;<=>?@[\]^_\`{|}~`). It is the standard, predictable definition of "punctuation," matches the user's examples (`)`, `.`, `!`), and lives in a single constant that is trivial to narrow later (e.g. to exclude opening brackets like `(`/`[`/`{`).
If a curated subset is preferred, the natural narrower set is the closing/terminal marks `) ] } . , ; : ! ?` (plus
quotes). This is the one product decision in the plan; everything else follows mechanically.

### 2. Pass the following character from each call site

Each path already reads the token's `end` and the line. Compute the next char as
`line[end] if end < len(line) else None` (using the path's existing row/col conventions) and pass it to the skeleton
builder alongside the existing `append_text_arg_space`:

- `_file_completion_accept.py` `_accept_xprompt_completion_candidate` — uses `self.document.get_line(row)` and the int
  `end`. (Covers the menu/Tab accept and the single-candidate auto-accept, since both call this method.)
- `_prompt_soft_completion.py` — uses `self.document.get_line(end[0])` and `end[1]`.
- `_prompt_input_bar_actions.py` `_insert_xprompt_smart_snippet` — uses `text_area.document.get_line(end[0])` and
  `end[1]`, passing `next_char` through `xprompt_completion_suffix_skeleton`.

Because the skeleton replaces the half-open token range `[start, end)`, the character at index `end` is exactly the
character that will immediately follow the inserted reference, so it is the correct thing to inspect.

**Scope note (all three paths):** the user's request names the completion menu (path 1), but the same surprise occurs in
the soft-completion and smart-snippet paths. Since the policy is centralized, wiring all three is cheap and avoids
inconsistent behavior between equivalent ways of accepting the same completion. Recommendation: apply to all three. (If
the user prefers a strictly minimal change, path 1 alone satisfies the literal request; flagged for confirmation.)

### Resulting behavior examples

- `(#fo)` accept `#foo` → `(#foo)` (was `(#foo )`); cursor parked between `#foo` and `)`.
- `#fo` at end of line → `#foo ` (unchanged).
- `#fo bar` → trailing space still added before the existing space (unchanged; see Non-goals).
- Optional-only xprompt completed before `)` → `#foo)` with no spacer recorded; typing `:` afterward inserts a normal
  colon (`#foo:)`), since there is no space to rewrite.
- Required-input xprompts (`#name::`, `#name:`, `#name()`) → entirely unchanged.

## Boundary / architecture notes

This is presentation-only text-editing behavior of the Textual prompt widget (shaping the snippet string inserted into
the input box). The skeleton functions are pure Python in `src/sase/ace/tui/widgets/` with no `sase_core_rs`
involvement, so per the Rust-core boundary litmus test this stays in the Python/TUI layer — no Rust wire/API/binding
changes are required.

## Tests

### Unit tests — `tests/ace/tui/widgets/test_xprompt_arg_assist.py`

Add coverage for the new `next_char` parameter of `xprompt_completion_skeleton` (and the suffix variant), modeled on the
existing skeleton-shape tests:

- No-input entry, `next_char=")"` / `"."` / `"!"` → `"#none"` (no trailing space).
- No-input entry, `next_char="a"` → `"#none "` (ordinary char keeps the space).
- No-input entry, `next_char=None` and the no-arg default → `"#none "` (unchanged).
- Optional-only entry (all inputs optional) before punctuation → no trailing space; before an ordinary char / at
  end-of-line → trailing space.
- `xprompt_completion_suffix_skeleton(..., next_char=")")` → `"none"` (no space, `#` stripped).
- Sanity: required-input shapes are unaffected by any `next_char` value.

### Integration tests — `tests/ace/tui/widgets/test_xprompt_completion.py`

Mirror `test_single_candidate_xprompt_without_inputs_adds_trailing_space` for the before-punctuation case, e.g.:

- Seed `[_entry("none")]`, `load_text("(#n)")`, cursor at `(0, 3)` (right after `#n`, before `)`), then
  `_try_file_completion_tab()`; assert `ta.text == "(#none)"`, `ta.cursor_location == (0, len("(#none"))`, and
  `ta._active_xprompt_arg_hint is None`.
- Keep/confirm the existing end-of-line test still asserts `#none ` (regression guard).

If paths 2 and 3 are included, add an analogous before-punctuation assertion for the soft- completion accept and the
smart-snippet insert (following their existing tests in `test_prompt_live_completion.py` / `test_xprompt_arg_hints.py`).

### Optional-spacer interaction — `tests/ace/tui/widgets/test_xprompt_optional_spacer.py`

Add a test that an optional-only xprompt completed immediately before punctuation inserts no trailing space, records no
pending spacer, and that a subsequently typed `:` is inserted normally rather than rewriting a (non-existent) spacer.

### Existing tests

All current trailing-space assertions exercise end-of-line / no-following-char scenarios (`next_char` defaults to
`None`), so they should pass unchanged. No existing assertions are expected to need updating; if any do, that indicates
an unintended behavior change to investigate.

## Non-goals / explicitly out of scope

- **Whitespace after the reference:** when the following character is already a space, today's code can produce a double
  space (`#foo  bar`). This plan does not change that — the request is specifically about punctuation. (Could be a cheap
  follow-up if desired; flagged but not included.)
- No change to required-argument skeletons (`::`, `:`, `()`) or to the optional-spacer rewrite mechanism itself.
- No new public API surface beyond the backward-compatible `next_char` keyword.

## Validation

Per repo conventions for code changes in the sase repo:

1. `just install` (workspace venvs are ephemeral; install first).
2. `just check` (ruff + mypy + fast tests).
3. `just test-visual` to confirm no PNG-snapshot regressions (this change is text-editing logic and is not expected to
   alter renders; only accept snapshot changes if intentional).

## Decisions to confirm during plan review

1. **Punctuation set:** full `string.punctuation` (recommended) vs. a curated closing/terminal subset. One-line constant
   either way.
2. **Scope:** all three accept paths (recommended, for consistency) vs. only the completion-menu path named in the
   request.
