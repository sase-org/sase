---
create_time: 2026-04-13 13:07:37
status: done
prompt: sdd/prompts/202604/word_boundary_matching.md
---

# Plan: Word-boundary matching for dynamic memory keywords

## Problem

Dynamic memory keyword matching in `src/sase/memory/dynamic.py:80` uses plain substring containment:

```python
hits = [kw for kw in wf.keywords if kw.lower() in prompt_lower]
```

This causes false positives: keyword `"skill"` matches "unskilled"/"reskilling", `"plugin"` matches "unplugging", etc.
With only 2 memory files today the cost is negligible, but this needs fixing before the memory pool grows.

## Solution

Replace the substring check with `\b` word-boundary regex matching:

```python
re.search(rf'\b{re.escape(kw)}\b', prompt, re.IGNORECASE)
```

This eliminates mid-word substring matches while preserving all desired behavior:

- **Hyphenated keywords** (`cross-repo`, `sase-github`): `-` is a non-word character, so `\b` boundaries work correctly
  — `\bcross-repo\b` matches "cross-repo" but not "across-repository"
- **Underscored keywords** (`sase_commit`): `_` is a word character in regex, so `\bsase_commit\b` matches the whole
  token correctly
- **Dotted keywords** (`SKILL.md`): The dot is escaped by `re.escape`, and `\b` around the full pattern matches
  "SKILL.md" as expected
- **Multi-word keywords** (`commit workflow`): `\bcommit workflow\b` matches the phrase with boundaries on both ends
- **Case insensitivity**: Handled by `re.IGNORECASE` flag instead of pre-lowercasing

### Tradeoff: plurals

`\bplugin\b` does not match "plugins" (no word boundary between `n` and `s`). This is an acceptable tradeoff — keyword
authors can add explicit plural forms when needed, and the false-negative cost is far smaller than the false-positive
cost we're eliminating. No special `s?` suffix logic needed.

## Changes

### 1. `src/sase/memory/dynamic.py`

- Add `import re` to the import block
- Replace line 80 (`kw.lower() in prompt_lower`) with `re.search(rf'\b{re.escape(kw)}\b', prompt, re.IGNORECASE)`
- The `prompt_lower` variable becomes unused — remove it
- Update the docstring (line 59) to say "word-boundary regex" instead of "case-insensitive substring"

### 2. `tests/test_dynamic_memory.py`

Add tests that verify false positives are eliminated:

- **Substring no longer matches mid-word**: prompt containing "unskilled" should NOT match keyword `"skill"`
- **Whole-word still matches**: prompt containing "skill" still matches keyword `"skill"`
- **Hyphenated keyword**: `"cross-repo"` matches "cross-repo" but not "across-repository"
- **Special-char keyword**: `"SKILL.md"` matches "SKILL.md" in prompt

Existing tests all use whole-word occurrences in their prompts, so none should break.

### 3. `sdd/research/202604/dynamic_memory_critique.md`

Update the priority table to mark item #1 as **Resolved**, matching the pattern used for items #5, #6, #7. Add a brief
note in the Resolved Items section.
