---
create_time: 2026-04-13 16:15:42
status: done
prompt: sdd/prompts/202604/dynamic_memory_keyword_annotations_1.md
---

# Plan: Keyword Annotations for DYNAMIC MEMORY Lines

## Context

The `### DYNAMIC MEMORY` section injected into agent prompts currently lists bare file paths with no indication of _why_
each memory was included:

```
### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md
- @.sase/memory/long-generated-skills.md
```

The matched keywords are already tracked internally (`MatchedMemory.keywords_matched`) but discarded during formatting.
This feature surfaces them inline so both humans reviewing `sase ace` output and agents reading their own prompt can see
the relevance signal.

An existing SDD spec lives at `plans/202604/dynamic_memory_keyword_annotations.md` — the API design (change
`format_dynamic_memory_section` to accept `DynamicMemoryResult`) is solid and I'm keeping it. The refinement here is the
visual design of the keyword annotation itself.

## Design: Visual Format

Use markdown backtick code spans inside parentheses with an italic "keywords:" label:

```
### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (_keywords:_ `chezmoi`, `plugin`)
- @.sase/memory/long-generated-skills.md (_keywords:_ `skill`, `commit workflow`)
```

**Why this works:**

- Backtick code spans give each keyword a monospace/highlighted appearance — they pop visually against the surrounding
  prose in any markdown renderer.
- The italic `_keywords:_` label is visually lighter than the keywords themselves, creating a natural hierarchy: your
  eye is drawn to the keywords first, then the label explains them.
- Parentheses keep the annotation clearly subordinate to the file path.
- In plain-text (no markdown rendering), backticks still serve as visual delimiters.

## Changes

### 1. `src/sase/memory/dynamic.py` — update `format_dynamic_memory_section`

Change signature from `(paths: list[str])` to `(result: DynamicMemoryResult)`. Zip `result.paths` with `result.matched`
and format each line as:

```
- @{path} (_keywords:_ `kw1`, `kw2`)
```

### 2. `src/sase/axe/run_agent_runner.py` ~line 252 — update call site

Change `format_dynamic_memory_section(dynamic_result.paths)` to `format_dynamic_memory_section(dynamic_result)`.

### 3. `AGENTS.md` — update the Tier 2 documentation example

Update the code block showing the `### DYNAMIC MEMORY` format to use the new annotated style so agents know what to
expect.

### 4. `tests/test_dynamic_memory.py` — update format tests

Update `test_format_dynamic_memory_section_single` and `test_format_dynamic_memory_section_multiple` to pass
`DynamicMemoryResult` objects and assert the `(_keywords:_ ...)` suffix appears.
