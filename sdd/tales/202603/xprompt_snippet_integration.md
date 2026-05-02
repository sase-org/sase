---
create_time: 2026-03-29 14:01:41
status: done
---

# Plan: XPrompt Snippet Integration (Option D)

## Goal

Allow xprompt authors to opt in to snippet expansion by adding a `snippet` field to their frontmatter. Typing
`trigger<Tab>` in the ACE prompt expands the xprompt content inline with tabstop cycling, just like regular snippets.
The `#name(args)` expansion path remains available for full-semantics use.

## Design

### New field: `snippet` on XPrompt

Add `snippet: str | bool | None = None` to the `XPrompt` dataclass:

- `None` (default) — not a snippet
- `True` — register as snippet using the base name (sans namespace) as trigger
- `"rv"` — register as snippet using `"rv"` as the trigger word

### Conversion: xprompt content to snippet template

New module `src/sase/xprompt/snippet_bridge.py` with two public functions:

1. **`xprompt_to_snippet_template(xp: XPrompt) -> str | None`** — Convert one xprompt's content + inputs into a snippet
   template string. Returns `None` if the xprompt can't be converted (complex Jinja2).

   Rules:
   - **Bail out** if content has `{% %}` control structures or `{# #}` comments (complex Jinja2).
   - Collect input names into a set. Scan all `{{ expr }}` occurrences — if any `expr.strip()` is NOT an input name,
     bail out (it's a computed expression like `{{ count + 1 }}`).
   - For each input (in definition order), assign tabstop numbers starting at 1:
     - Required input (`default is UNSET`): replace `{{ name }}` with `$N`
     - Input with default: replace `{{ name }}` with the literal default value (pre-filled, no tabstop)
   - Handle legacy `{N}` placeholders: replace `{1}` with `$1`, `{2}` with `$2`, etc. Also handle `{N:default}` by
     pre-filling the default.
   - Append `$0` at the end.

2. **`get_xprompt_snippets(project: str | None = None) -> dict[str, str]`** — Load all xprompts, filter to those with
   `snippet` set, convert each, and return a `{trigger: template}` dict.

   Trigger resolution:
   - `snippet: "rv"` → trigger is `"rv"`
   - `snippet: true` → trigger is the xprompt's base name (part after last `/`, or full name if no `/`)
   - Validate trigger: must be `[a-zA-Z0-9_]+` (same chars the snippet expander recognizes). Skip invalid triggers.

### Parsing the `snippet` field

- **`loader.py:_load_xprompt_from_file()`** — Read `snippet` from parsed frontmatter dict, pass to
  `XPrompt(snippet=...)`.
- **`loader_parsing.py:parse_xprompt_entries()`** — Read `snippet` from structured dict format (sase.yml xprompts).
- Both .md files and config-defined xprompts support the field.

### TUI integration

In `app.py` where `_snippets` is populated (~line 300):

```python
self._snippets: dict[str, str] = ace_cfg.get("snippets", {}) ...

# Merge xprompt-derived snippets (user-defined snippets take precedence)
from sase.xprompt.snippet_bridge import get_xprompt_snippets
xp_snippets = get_xprompt_snippets()
xp_snippets.update(self._snippets)  # user wins on collision
self._snippets = xp_snippets
```

### Files to modify

| File                                   | Change                                                         |
| -------------------------------------- | -------------------------------------------------------------- |
| `src/sase/xprompt/models.py`           | Add `snippet: str \| bool \| None = None` field to `XPrompt`   |
| `src/sase/xprompt/loader.py`           | Pass `snippet` from frontmatter in `_load_xprompt_from_file()` |
| `src/sase/xprompt/loader_parsing.py`   | Read `snippet` in `parse_xprompt_entries()`                    |
| `src/sase/xprompt/snippet_bridge.py`   | **New** — conversion logic and `get_xprompt_snippets()`        |
| `src/sase/ace/tui/app.py`              | Merge xprompt snippets into `_snippets` at startup             |
| `tests/test_xprompt_snippet_bridge.py` | **New** — unit tests for conversion logic                      |

### Edge cases

- **Xprompt with no inputs and no Jinja2**: content becomes the snippet template verbatim + `$0`.
- **Xprompt with only defaulted inputs**: all placeholders pre-filled, just `$0` for cursor positioning.
- **Namespace collision**: two xprompts both set `snippet: true` with same base name — higher-priority source wins (same
  as xprompt name collisions).
- **Trigger collision with user snippet**: user snippet always wins; xprompt-derived snippet is silently dropped.
