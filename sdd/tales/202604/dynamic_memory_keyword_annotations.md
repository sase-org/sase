---
create_time: 2026-04-13 16:10:49
status: wip
prompt: sdd/prompts/202604/dynamic_memory_keyword_annotations.md
---

# Plan: Add Matched-Keyword Annotations to DYNAMIC MEMORY Section

## Problem

When the `### DYNAMIC MEMORY` section is injected into an agent's prompt, there's no indication of _why_ each memory
file was included. The agent sees:

```
### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md
- @.sase/memory/long-generated-skills.md
```

This makes it hard for both humans (reviewing `sase ace` output) and agents to understand the relevance of each injected
memory. The matched keywords are already tracked internally (`MatchedMemory.keywords_matched`) but discarded during
formatting.

## Design

Append a `(matched: kw1, kw2)` annotation to each line in the formatted section:

```
### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md (matched: chezmoi, plugin)
- @.sase/memory/long-generated-skills.md (matched: skill, commit workflow)
```

This is the same format already used in the console debug output at `run_agent_runner.py:242`, so we're making the
in-prompt format match what operators already see in the terminal.

### API change

`format_dynamic_memory_section` currently takes `paths: list[str]` — a flat list with no keyword info. The cleanest fix:
change the signature to accept `DynamicMemoryResult` directly, since it already bundles `paths` and `matched` in
parallel order, and the function lives in the same module as that dataclass. This avoids inventing a new data structure
or passing parallel lists.

```python
# Before
def format_dynamic_memory_section(paths: list[str]) -> str:

# After
def format_dynamic_memory_section(result: DynamicMemoryResult) -> str:
```

## Changes

### 1. `src/sase/memory/dynamic.py` — update `format_dynamic_memory_section`

- Change signature from `(paths: list[str])` to `(result: DynamicMemoryResult)`.
- Zip `result.paths` with `result.matched` and format each line as `- @{path} (matched: {kw1}, {kw2})`.

### 2. `src/sase/axe/run_agent_runner.py` — update call site

- Change `format_dynamic_memory_section(dynamic_result.paths)` to `format_dynamic_memory_section(dynamic_result)`.

### 3. `AGENTS.md` — update documentation example

- Update the Tier 2 example block to show the new annotated format so agents know what to expect.

### 4. `tests/test_dynamic_memory.py` — update format tests

- Update `test_format_dynamic_memory_section_single` and `test_format_dynamic_memory_section_multiple` to pass
  `DynamicMemoryResult` objects and assert the `(matched: ...)` suffix appears.
