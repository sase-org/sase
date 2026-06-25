---
create_time: 2026-06-25 09:51:37
status: done
prompt: sdd/prompts/202606/fork_colon_trailing_text_completion.md
---
# Plan: Open the `#fork:` agent-name menu even when text follows the colon

## Problem / Product Context

The `#fork:` xprompt argument completion (an inline menu of resumable agent names) only opens when **nothing follows the
colon** on the line. As soon as there is any trailing content after `#fork:` — a space, more words, or another token —
the menu fails to open. In practice this reads as "it only works when `#fork:` is at the beginning of the line / the
only thing on the line."

The directive equivalent, `%wait:` (`%w:`), does **not** have this problem: its agent-name menu opens regardless of what
follows on the line. The two should behave the same — typing `:` after a fork/wait token that takes an agent argument
should pop the agent menu wherever the cursor is.

This is the same family of feature as the recently shipped optional-spacer `:` rewrite (`#fork ` + `:` → `#fork:`); that
change is correct, but it inherits this underlying limitation: the rewrite opens the menu only in the same positions the
menu would otherwise open, so mid-prompt forks still don't get a menu.

### Reproduction (confirmed empirically against the live detectors)

| Prompt (cursor right after the first `:`)                 | `#fork:` (xprompt) | `%wait:` (directive) |
| --------------------------------------------------------- | ------------------ | -------------------- |
| `#fork:` / `%wait:` (nothing after)                       | menu opens         | menu opens           |
| `#fork: ` / `%wait: ` (trailing space)                    | **no menu**        | menu opens           |
| `#fork: foo` / `%wait: foo` (trailing text)               | **no menu**        | menu opens           |
| `foo #fork: bar` / `foo %wait: bar` (mid-line + trailing) | **no menu**        | menu opens           |
| `#fork:c bar` (cursor before an existing value)           | **no menu**        | menu opens           |

So the asymmetry is precisely "is there content after the colon," not "where on the line is the token."

## Root Cause

Two different code paths detect the argument-completion context:

- **Directive (`%wait:`)** — `extract_directive_arg_token_around_cursor(line, col)` in
  `src/sase/ace/tui/widgets/directive_completion.py`. It scans the **current line around the cursor**: find the `%`, the
  directive name, the `:`, then read the argument value forward, bounded by whitespace/identifier characters. It is
  anchored to the cursor, so trailing content on the line is irrelevant.

- **Xprompt (`#fork:`)** — `detect_xprompt_arg_completion_at_cursor(...)` in
  `src/sase/ace/tui/widgets/xprompt_arg_assist.py`. It iterates **whole-text** lexical references via
  `iter_xprompt_references(text)` (`src/sase/xprompt/_parsing_references.py`) and then, for each reference, runs a
  guard:

  ```python
  if ref.end > cursor_offset and not _cursor_is_inside_reference_args(text, ref, base_end, cursor_offset):
      continue
  ```

  When `#fork:` is followed by `<space>text`, the lexer correctly parses `: text` as a **colon-shorthand free-form text
  argument** (`XPromptReferenceArgKind.COLON_SHORTHAND`). That gives the reference a semantic `end` that extends to the
  end of the shorthand text — well **past** the cursor that sits right after the colon. The guard then asks
  `_cursor_is_inside_reference_args(...)`, but that helper only recognizes the **open-paren** argument form (`(`); it
  has no branch for a **colon** argument. So the reference is skipped and no menu opens.

  When nothing follows the colon, the reference's `end` equals the cursor offset, the guard branch
  (`ref.end > cursor_offset`) is never entered, and detection proceeds normally — which is exactly why it works "at the
  beginning of the line."

The suffix-based resolver that runs _after_ the guard (`_colon_completion_context` / `_active_input_index_for_suffix`)
already does the right thing: for the cursor sitting immediately after the colon the suffix is just `":"`, which
resolves to the agent argument; and for a cursor that has moved _past_ a space (genuine free-form text) the suffix
contains whitespace and the resolver returns `None`. The only defect is that the guard discards the reference before
that resolver ever runs.

### Cross-frontend note (Rust core boundary)

There is a parallel implementation of this detection in the Rust core used by the Neovim xprompt LSP:
`detect_xprompt_arg_completion_at_position` in `sase-core` `crates/sase_core/src/editor/completion.rs`. That
implementation is structurally different — it matches only the **base `#name`** reference over the **prefix**
(`text[..cursor]`) via `xprompt_ref_re()`, then inspects `suffix = text[base_end..cursor]`. Because it never constructs
a "reference end past the cursor," **it does not have this bug** (verified by reading the Rust: for `#fork: bar` with
the cursor after the colon it sees prefix `#fork:`, base end after `#fork`, suffix `":"`, and returns the agent
context).

Therefore the Python TUI detector is the **diverged, buggy mirror**, and this fix **brings Python into parity with the
already-correct Rust core**. No `sase-core` change is required. (The two implementations are independent parallels here,
unlike the `#+` VCS-project completion which has a shared golden-vector parity table; introducing such a table for
xprompt-arg detection is out of scope for this fix.)

## High-Level Design

Make the Python detector accept a cursor that sits inside a **colon** argument region the same way it already accepts
one inside a **paren** argument region — so a reference whose semantic end was extended by a colon shorthand (or any
trailing content) is no longer discarded by the guard.

Concretely, extend the single shared helper `_cursor_is_inside_reference_args(text, ref, base_end, cursor_offset)` in
`src/sase/ace/tui/widgets/xprompt_arg_assist.py` to also return `True` when the character at `base_end` is a colon
(`text[base_end:base_end+1] == ":"`) and the cursor is within the reference span. Nothing else changes:

- The existing suffix resolver still decides whether to actually offer a menu, and still correctly returns nothing when
  the cursor has moved past a space into genuine free-form shorthand text (e.g. `#fork: ag` with the cursor after the
  space).
- The change is **purely additive**: it only lets the guard through in cases it currently rejects; it never blocks a
  case it currently allows.

### Why this layer / why this is the right fix

- `_cursor_is_inside_reference_args` is the exact and only place the colon case is missing, and it is **shared by both**
  `detect_xprompt_arg_completion_at_cursor` (the completion menu) and `detect_xprompt_arg_hint_at_cursor` (the inline
  argument hint). Fixing it once corrects both surfaces consistently — the inline hint for an xprompt with a required
  argument will now also appear when text follows the colon, matching the no-trailing-text case.
- It does **not** touch the lexer (`iter_xprompt_references`). The colon-shorthand parse is correct runtime semantics
  (`#fork: do a thing` really is a free-form text argument) and must not change; we only change _when the
  completion/hint surface offers help_, not how prompts are parsed.
- It mirrors the structure the Rust core already uses, closing the divergence rather than widening it.

### Considered alternative (not chosen)

Restructure the Python detector to mirror the Rust approach (match only the base `#name` over the prefix and read the
suffix up to the cursor). This is arguably the cleaner long-term shape and would make the bug impossible by
construction, but it is a broader rewrite of `detect_xprompt_arg_completion_at_cursor` /
`detect_xprompt_arg_hint_at_cursor` with more regression surface. The additive guard fix achieves identical observable
behavior with a far smaller blast radius, so it is preferred for this bug fix; the larger refactor can be a separate
follow-up if Python/Rust parity is later formalized with a shared golden-vector table.

## Testing

Pure-function tests are the core of this change (cheapest and most direct), added to
`tests/ace/tui/widgets/test_xprompt_arg_assist.py` alongside the existing
`test_detects_agent_arg_completion_contexts_for_fork_forms`:

- **New positive cases** — `detect_xprompt_arg_completion_at_cursor` with the cursor immediately after the colon and
  trailing content present resolves the agent context:
  - `#fork: bar` (trailing word) → `xprompt_arg_agent`, empty token.
  - `foo #fork: bar` (mid-line + trailing) → `xprompt_arg_agent`, empty token.
  - `#fork:` with no trailing content still works (guards the no-regression baseline).
- **New negative case (preserves free-form shorthand)** — `#fork: ag` with the cursor **after** the space returns `None`
  (the user is now typing free-form text, not an agent name).
- The existing negative test `test_detect_typed_argument_positions_rejects_broad_cases` (which includes
  `"#review: text"` evaluated with the cursor at end-of-string) must still pass — and does, because the cursor sits at
  the reference's end there, so the guard branch is never entered.

Optionally, one end-to-end widget regression in the `CompletionTestApp` style (mirroring
`tests/ace/tui/widgets/test_xprompt_optional_spacer.py`): seed visible agents, load a prompt where `#fork` is followed
by trailing text, type `:` at the colon position, and assert `_file_completion_active is True` with
`_completion_kind == "xprompt_arg_agent"`. This is belt-and-suspenders over the pure-function coverage.

## Verification

- `just install` then `just check` (lint + mypy + tests) in the workspace.
- Targeted: `tests/ace/tui/widgets/test_xprompt_arg_assist.py`,
  `tests/ace/tui/widgets/test_local_xprompt_completion.py`, `tests/ace/tui/widgets/test_xprompt_optional_spacer.py`,
  `tests/ace/tui/widgets/test_xprompt_arg_value_completion.py` (43 passing at baseline today; must stay green).
- Manual smoke in `sase ace`: in a non-empty prompt with text after the cursor position, type `#fork:` and confirm the
  agent menu opens immediately (matching `%wait:`), and that typing past a space after the colon returns the prompt to
  free-form text with no menu.

## Files Expected to Change

- `src/sase/ace/tui/widgets/xprompt_arg_assist.py` — extend `_cursor_is_inside_reference_args` with the colon argument
  branch (the one-function fix; benefits both the completion menu and the inline hint detectors).
- `tests/ace/tui/widgets/test_xprompt_arg_assist.py` — add the trailing-content positive/negative regression cases above
  (and optionally a `CompletionTestApp` end-to-end regression, here or in
  `tests/ace/tui/widgets/test_xprompt_optional_spacer.py`).

No `sase-core` / Rust changes required: the fix makes the Python TUI detector match the already-correct Rust core
implementation.
