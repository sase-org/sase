---
create_time: 2026-04-12 22:21:15
status: done
prompt: sdd/prompts/202604/dynamic_memory_section_headers.md
---

# Plan: Add Section Headers to Dynamic Memory Temp Files

## Problem

When multiple memory xprompts match a user prompt, `generate_dynamic_memory()` joins their resolved contents with just
`"\n\n"` — a bare double newline (`dynamic.py:75`). The resulting temp file is a continuous blob with no indication of
where one memory topic's content ends and another begins.

For example, if both `memory/external_repos` and `memory/generated_skills` match, the current output looks like:

```
# External Repos

## Chezmoi Repo
...content...

# Generated Skill Files

...content...
```

The two `#` headings happen to exist in the source files, but there's no structural separator that identifies _which
memory xprompt_ contributed each section. If a source file doesn't start with a heading, the boundary is invisible.

## Proposed Change

Prefix each matched memory's resolved content with a horizontal rule and a `##` heading derived from its xprompt name.
This gives clear visual and semantic separation regardless of the source file's own formatting.

After the change, the same two-match example would look like:

```
---
## memory/external_repos

# External Repos

## Chezmoi Repo
...content...

---
## memory/generated_skills

# Generated Skill Files

...content...
```

For a single match, the header is still included for consistency — the agent always knows which memory xprompt it's
reading.

## Implementation

### Phase 1: Add section headers in `dynamic.py`

**File:** `src/sase/memory/dynamic.py`

Change the content assembly (line 75) from:

```python
raw_content = "\n\n".join(m.content for m in matched) + "\n"
```

To:

```python
sections = []
for m in matched:
    sections.append(f"---\n## {m.name}\n\n{m.content}")
raw_content = "\n\n".join(sections) + "\n"
```

### Phase 2: Update tests in `test_dynamic_memory.py`

**File:** `tests/test_dynamic_memory.py`

1. Update `test_multiple_matches_concatenated` — verify the section headers (`---\n## memory/...`) appear in the output
   for each matched memory.
2. Update `test_matching_keywords_writes_temp_file` — verify the header appears even for a single match.
