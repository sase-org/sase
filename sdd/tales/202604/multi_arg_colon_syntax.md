---
create_time: 2026-04-13 16:02:09
status: done
prompt: sdd/prompts/202604/multi_arg_colon_syntax.md
---

# Plan: Multi-arg colon syntax for xprompts

## Problem

The colon syntax `#foo:arg` currently supports only a single argument. Users want to pass multiple arguments without
switching to the heavier parenthesis syntax `#foo(a, b, c)`. The desired syntax is `#foo:arg1,arg2,arg3` —
comma-separated with no spaces.

## Design

### Syntax rules

- `#foo:a,b,c` → positional_args = `["a", "b", "c"]`
- Commas act as separators only in the **word-char** variant of colon args (the third alternative in the regex).
  Backtick-delimited (`` `...` ``) and command-substitution (`$(...)`) variants remain single-arg — commas inside those
  are literal content, not separators.
- A trailing comma (e.g. `#foo:a,`) produces one arg `["a"]`, not two — same as how `parse_args` handles trailing commas
  in the paren syntax.

### Changes

**1. Regex update** (`src/sase/xprompt/processor.py` line 58)

The word-char alternative in Group 3 currently is:

```
[a-zA-Z0-9_.~/-]*[a-zA-Z0-9_~/-]
```

Add comma to the interior character class so the regex captures the full `a,b,c` string:

```
[a-zA-Z0-9_.~,/-]*[a-zA-Z0-9_~/-]
```

Note: comma is only added to the _repeating_ class, not the _trailing_ class, so a trailing comma (like `#foo:a,`) is
naturally excluded from the match — the comma won't be the last captured char.

**2. Split on commas** (`src/sase/xprompt/processor.py` ~line 303)

After extracting `colon_arg` and stripping backticks, split the word-char variant on commas:

```python
elif colon_arg is not None:
    if colon_arg.startswith("`") and colon_arg.endswith("`"):
        colon_arg = colon_arg[1:-1]
        positional_args, named_args = [colon_arg], {}
    else:
        positional_args, named_args = colon_arg.split(","), {}
```

The backtick and `$(...)` variants remain single-arg (backticks already stripped; `$(...)` doesn't contain commas in the
captured group since the regex is `\$\([^)]*\)`).

**3. Update comment** (`processor.py` line 51)

Change the comment from "colon syntax for single arg" to reflect multi-arg support.

**4. Tests** (`tests/test_xprompt_processor_pattern.py` and `tests/test_expand_for_spec.py`)

- Pattern tests: `#foo:a,b,c` captures `"a,b,c"` in Group 3; `#foo:a,` captures only `"a"`.
- Expansion test: an xprompt with two inputs expands both when invoked as `#wf:val1,val2`.
- Existing single-arg colon tests remain passing (no behavioral change for single arg).

### What doesn't change

- Backtick syntax: commas inside backticks are literal content, not split.
- Command substitution: `#foo:$(cmd)` stays single-arg.
- Paren syntax: already supports multiple args via `parse_args`.
- The Jinja2 rendering and `validate_and_convert_args` already handle lists of positional args — no changes needed
  downstream.
