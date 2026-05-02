---
create_time: 2026-04-23 14:59:06
status: done
prompt: sdd/prompts/202604/skip_short_prompts_in_history.md
---

# Skip Short Prompts in Prompt History

## Problem

Prompts with fewer than 2 words are getting saved to prompt history. This clutters `~/.sase/prompt_history.json` (and
the fzf picker) with useless entries like bare xprompt triggers. Canonical example: the user launches an agent (or
cancels the prompt input bar) with just `#gh:sase` — a single-token xprompt trigger with no actual instruction — and
that token ends up in history even though it is never a meaningful prompt to re-run.

Today there are a couple of ad-hoc filters (`.`, `.x`, `"#... ."`, `"#... .x"`) in `_save_bar_text_as_cancelled`, but
they only apply to the TUI cancel path and they only catch literal dot-trigger patterns. The broader "it's a single
word, not a real prompt" case is not handled, and it is not handled at all for the _launch_ path (an accepted
single-word prompt gets saved too).

## Goal

No prompt with fewer than 2 words ever lands in `~/.sase/prompt_history.json`, regardless of entrypoint (TUI launch, TUI
cancel, TUI editor cancel, CLI launcher, query handler, multi-prompt segments).

## Design

### Where to filter

Centralize the check inside `add_or_update_prompt()` in `src/sase/history/prompt.py`.

Every write to prompt history — accepted launches, cancelled TUI text, CLI launcher, query handler, recursive
multi-prompt segments — flows through this one function. Putting the filter here means:

- Single source of truth; no risk of one entrypoint forgetting.
- Multi-prompt segments are automatically filtered (the recursive `add_or_update_prompt` call on each segment hits the
  same gate).
- The TUI-specific dot-trigger filter in `_save_bar_text_as_cancelled` becomes partially redundant but is cheap to keep
  as a belt-and-suspenders for the `#foo .` 2-token case (which the word-count filter alone would let through).

An alternative would be to filter at each call site, but that is exactly the duplication we want to avoid — and the
current tree has six call sites.

### What counts as a "word"

Keep it simple: `len(text.strip().split()) < 2` → skip.

- `split()` with no args splits on any whitespace run and discards empties — matches the intuitive notion of "word."
- `#gh:sase` → 1 token → skipped.
- `#gh:sase fix login` → 3 tokens → saved.
- `fix` → 1 token → skipped.
- `fix bug` → 2 tokens → saved.
- `""` / whitespace-only → 0 tokens → skipped (already a no-op in practice, but the new check makes it explicit).
- Multi-line prompts still count words across lines via whitespace splitting.

We are _not_ trying to be clever about punctuation, URLs, or CJK. The user said "2 words"; naive whitespace tokenization
is the right fit.

### Behavior on existing entries

The filter applies to **new** inserts and to **updates of `last_used`** on existing entries. The net effect: even if
`#gh:sase` is already in history from before this change, we stop bumping its `last_used` on subsequent invocations, and
we never re-add it if it gets purged. We do not proactively prune existing sub-2-word entries — that is a separate
concern (and could be left for a manual cleanup or a later task).

### Interaction with the existing `cancelled=True` flow

The word-count gate fires _before_ the cancelled/non-cancelled bookkeeping. A single-word prompt cancelled in the TUI is
dropped on the floor — which is what we want. This is consistent with the existing "trivial pattern" filters.

### Interaction with `_save_bar_text_as_cancelled`

Leave the existing `_TRIVIAL_PROMPT_PATTERNS` and `" ."`/`" .x"` checks in place. They catch the 2-token case
`#gh:sase .` that our word-count filter would let through. We do not remove them.

## Implementation Sketch

1. **`src/sase/history/prompt.py`** — `add_or_update_prompt()`:
   - Add `_MIN_PROMPT_WORDS = 2` module-level constant.
   - At the top of the function (after the `text` parameter is in scope, before `_load_prompt_history()`), add an early
     return:
     ```python
     if len(text.split()) < _MIN_PROMPT_WORDS:
         return
     ```
   - That's it. No other call-site changes.

2. **`tests/history/test_prompt.py`** — new tests:
   - Single-word prompt (`"#gh:sase"`) is not written to history.
   - Whitespace-only prompt is not written to history.
   - Two-word prompt is written normally.
   - Single-word cancelled prompt is not written.
   - Multi-prompt where the whole string has ≥2 words but an individual segment is 1 word: the whole string is saved,
     the short segment is skipped, the long segment is saved. (E.g. `"#gh:sase\n---\nfix auth bug"` → whole and
     `"fix auth bug"` saved, `"#gh:sase"` skipped.)
   - Existing single-word entry in history is not updated when `add_or_update_prompt` is called again with that same
     single-word text.

3. **No changes** to `_prompt_bar.py`, `_agent_launch.py`, `launcher.py`, or `_query.py`. Centralizing in
   `add_or_update_prompt` is the whole point.

## Non-Goals

- Pruning existing sub-2-word entries from `~/.sase/prompt_history.json`.
- Changing the file-reference history (`file_reference_history.json`) — it records file refs, not prompts, and is out of
  scope.
- Making the threshold configurable. `2` is hardcoded; if someone later wants a user setting we can promote the
  constant.
- Smarter tokenization (punctuation, CJK, etc.).

## Verification

- `just check` (covers lint + mypy + pytest + coverage).
- Manual smoke in the TUI: type `#gh:sase`, cancel the bar, inspect `~/.sase/prompt_history.json` — no new entry. Type
  `#gh:sase fix login`, cancel → entry present with `cancelled: true`.
