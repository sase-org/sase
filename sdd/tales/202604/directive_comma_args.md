---
create_time: 2026-04-24 17:40:20
status: done
prompt: sdd/prompts/202604/directive_comma_args.md
---
# Plan: Comma-Separated Colon Args for Directives

## Goal

Let multi-value directives (today: `%wait`) accept multiple arguments in a single colon reference — e.g.
`%wait:agent_a,agent_b,5m` — matching how xprompts already split `#foo:a,b,c` into positional args. Writing three
`%wait:` lines stays supported; the new form is additive sugar.

## Motivation

The current `%wait` ergonomics require one directive per value:

```
%wait:agent_a
%wait:agent_b
%wait:5m
```

That's visually noisy, especially inside prompt files where `%wait` is often the only multi-value directive. XPrompts
already solved this with `#name:a,b,c` → `["a", "b", "c"]` (processor.py:305). Mirroring that here costs very little and
removes a gratuitous inconsistency between the two sibling syntaxes.

While we're in the area, the regex char class for directive colon args does not currently include `,`. That means
`%model:a,b` silently matches `%model:a` and leaves `,b` behind as stray text in the cleaned prompt — a latent bug worth
closing.

## Design Decisions

### D1. Which directives comma-split?

**Only `_MULTI_VALUE_DIRECTIVES` (today: `wait`) split on commas.**

Single-value directives (`model`, `name`, `repeat`, etc.) have no semantics for multiple values — splitting would either
silently drop data or require a new error path. Keeping their colon arg as a single literal string is the
least-surprising choice. (Commas inside the captured arg for a single-value directive are already unusual; if one
appears, we preserve it verbatim.)

`%model` is a soft exception — it's collected multi-value upstream by `split_prompt_for_models()`, not inside
`extract_prompt_directives()`. That upstream rewrite already converts `%model(a,b)` into `%alt(%model:a,%model:b,...)`,
so the inner `%model:` directives remain single-valued. No change needed there.

### D2. Backtick escaping

**Backtick-delimited colon args are treated as one literal value — no comma-splitting.** Exactly matches xprompt
behavior (processor.py:301-303).

Example: ``%wait:`a,b` `` → one arg `"a,b"` (probably never useful for wait, but preserves the invariant for any future
multi-value directive whose values can legitimately contain commas).

### D3. Paren syntax consistency

**Paren syntax for multi-value directives should consume all positional args, not just the first.** Today `%wait(a, b)`
only uses `a` (directives.py:494), which silently drops `b`. After this change, `%wait(a, b, 5m)` behaves the same as
`%wait:a,b,5m`.

This is a small bugfix tucked in for consistency; the current behavior is almost certainly not relied on and has no
tests.

### D4. Regex update

**Add `,` to the colon-arg char class.** Current pattern (directives.py:120):

```
:(`[^`]*`|[a-zA-Z0-9_#/.()-]*[a-zA-Z0-9_#/()-])
```

Extend both character classes to include `,`, mirroring the xprompt pattern (processor.py:58 — which has `,` in its
class). Applies uniformly to all directives; the _split-on-comma_ step happens later and is gated by D1, so single-value
directives keep the whole string.

### D5. Whitespace handling

**No whitespace around commas** — same as xprompts. `%wait:a, b` would fail to match the directive regex past `a` (space
breaks the capture), so users would see the stray `, b` in their prompt and notice. We do **not** try to be forgiving
here; consistency with xprompts is the whole point.

### D6. Empty segments

**Filter out empty strings after splitting.** `%wait:a,,b` and `%wait:a,b,` produce `["a", "b"]`. Rationale:
trailing/stray commas are a trivial user slip, not a meaningful signal — the bare-`%wait` semantics (resolve to most
recent agent) are only triggered by a _bare_ directive with no colon arg at all, not by an empty segment inside a comma
list. Preserving empty segments would accidentally trigger that lookup and surprise the user.

### D7. Error behavior

Existing error paths (duration + absolute-time combo, multiple absolute times, bare `%wait` with no prior agent) are
unchanged — they act on the final resolved list, not on how it was parsed.

## Files to Change

1. **`src/sase/xprompt/directives.py`**
   - Line 120: add `,` to both character classes in `_DIRECTIVE_PATTERN`.
   - Lines 488-497 (paren branch): for multi-value directives, keep all positional args; for single-value, keep today's
     first-arg-wins.
   - Lines 498-512 (colon branch + storage): when `name in _MULTI_VALUE_DIRECTIVES` and the arg is not backtick-wrapped,
     split on `,` and extend `seen_multi[name]` with the non-empty segments. Backtick-wrapped: treat as single arg (as
     today, no split).
   - No changes to the `_parse_duration` / `_parse_absolute_time` post-pass — it already iterates over the resolved list
     element-by-element and will handle the extra elements naturally.

2. **`tests/test_directives_types.py`**
   - New test: `%wait:a,b` → two agent names.
   - New test: `%wait:a,b,5m` → two agents + duration.
   - New test: `%wait:a,1430` → agent + absolute time.
   - New test: `%wait:`a,b`` (backticks) → one literal arg (not split).
   - New test: `%wait:a,,b` → `["a", "b"]` (empty segment filtered).
   - New test: paren form `%wait(a, b, 5m)` matches colon form.
   - New test: `%model:a,b` (single-value) — stays as one arg `"a,b"`; cleaned prompt should not leave stray text.
     (Locks in D1 + the latent-bug fix from D4.)
   - Existing tests at lines 91-211 should pass unchanged.

## Files to Leave Alone

- `src/sase/xprompt/processor.py` — reference only, no change.
- `src/sase/xprompt/_parsing.py` — `parse_args()` is already reused by the paren branch; no change needed. Deliberately
  **not** using `parse_args()` for the colon branch, because xprompts don't either — a plain `split(",")` keeps the two
  syntaxes symmetric.
- `src/sase/axe/run_agent_phases.py` — consumes the final resolved `directives.wait` list; unaffected by how the list
  was populated.

## Validation

- `just check` (lint + mypy + tests).
- Manually sanity-check: write a prompt with `%wait:agent_a,agent_b,5m` and confirm the resolved `PromptDirectives`
  matches `%wait:agent_a\n%wait:agent_b\n%wait:5m`.

## Out of Scope

- Named args (`key=value`) in directive colon syntax. XPrompts don't support them in colon form either — only in paren
  form via `parse_args()`. If a future multi-value directive needs named args, add them then.
- Whitespace-tolerant comma splits. Explicitly rejected in D5.
- Converting other directives to multi-value. The set `{wait}` is unchanged; new multi-value directives just add to
  `_MULTI_VALUE_DIRECTIVES` and inherit the new parsing for free.
