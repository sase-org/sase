---
create_time: 2026-04-12 23:42:21
status: done
prompt: sdd/prompts/202604/dynamic_memory_section.md
---

# Plan: Replace DYNAMIC MEMORY Line with Section of Individual File Paths

## Context

Today, dynamic (tier 2) memory works by:

1. Matching keyword-tagged memory xprompts against the user's prompt
2. Concatenating all matched content into a single temp file (`sase_dynamic_memory_<random>.md` in `$SASE_TMPDIR`)
3. Appending `DYNAMIC MEMORY: @<temp_file_path>` to the prompt
4. Protecting that line from Prettier underscore mangling via null-byte placeholders

This has several drawbacks:

- The agent sees one opaque blob; it can't tell which memory files were loaded or how many
- The temp file name (`sase_dynamic_memory_jeyhbzqb`) carries no semantic information
- The `DYNAMIC MEMORY: ` prefix requires special Prettier protection because it isn't valid markdown
- Tier 2 and tier 3 reference the same underlying `memory/long/` files but the agent has no way to know this

## Goal

Replace the single-line injection with a `### DYNAMIC MEMORY` markdown section containing a list of individual
`.sase/memory/` file paths, one per matched xprompt. File names encode the source tier so agents can identify long-term
memory files. Update AGENTS.md to explain that tier 2 entries may duplicate tier 3 files (so the agent doesn't re-read
them).

## Output Format

Before (current):

```
DYNAMIC MEMORY: @.sase/home/tmp/sase/sase_dynamic_memory_jeyhbzqb.md
```

After (new):

```
### DYNAMIC MEMORY
- @.sase/memory/long-external-repos.md
- @.sase/memory/long-generated-skills.md
```

## File Naming Convention

Each matched memory xprompt gets its own file in `.sase/memory/`. The name is derived from the xprompt name
(`memory/long/<stem>`) by replacing `memory/long/` with `long-` and converting underscores to hyphens:

| Xprompt name                   | File name                  |
| ------------------------------ | -------------------------- |
| `memory/long/external_repos`   | `long-external-repos.md`   |
| `memory/long/generated_skills` | `long-generated-skills.md` |

The `long-` prefix tells the agent this is a long-term (tier 3) memory file. Future non-long-term memory xprompts would
use a different prefix (e.g., `dyn-<stem>.md`).

Hyphens instead of underscores avoid Prettier's emphasis mangling without needing placeholder protection.

## Changes

### 1. `src/sase/memory/dynamic.py` - Write individual files to `.sase/memory/`

- Add a helper to derive the `.sase/memory/` filename from an xprompt name (e.g., `memory/long/external_repos` ->
  `long-external-repos.md`)
- Change `generate_dynamic_memory()` to:
  - Create `.sase/memory/` directory (in CWD) if it doesn't exist
  - Write each matched memory xprompt's resolved content to its own file in `.sase/memory/`
  - Remove the temp file creation entirely
- Change `DynamicMemoryResult`:
  - Replace `path: str | None` with `paths: list[str]` (one path per matched xprompt)
- Add a helper to format the `### DYNAMIC MEMORY` section string from the list of paths

### 2. `src/sase/axe/run_agent_runner.py` (~line 247) - Use new section format

- Replace `prompt + f"\n\nDYNAMIC MEMORY: @{dynamic_result.path}"` with the formatted `### DYNAMIC MEMORY` section using
  the new helper
- Update the condition check from `dynamic_result.path` to `dynamic_result.paths`

### 3. `src/sase/llm_provider/preprocessing.py` - Remove Prettier protection

- Delete `_MEMORY_LINE_RE`, `_MEMORY_PLACEHOLDER_PREFIX`, `_MEMORY_PLACEHOLDER_SUFFIX`
- Delete `_protect_memory_lines()` and `_unprotect_memory_lines()`
- Remove steps 1b and 5b from `preprocess_prompt_late()`

The `### DYNAMIC MEMORY` heading is valid markdown. The `@` file paths use hyphens (no underscores to mangle). Prettier
protection is no longer needed.

### 4. `AGENTS.md` - Update tier 2 description and cross-reference tier 3

Update the "Tier 2 (dynamic) Memory" section to:

- Describe the new `### DYNAMIC MEMORY` section format with a list of `@.sase/memory/` file paths
- Explain the naming convention (`long-` prefix = long-term/tier 3 source)
- Note that tier 2 entries with `long-` prefix are the same content as the corresponding tier 3 files -- if a `long-`
  prefixed file appears in your dynamic memory section, you do NOT need to separately read the tier 3 file

### 5. `tests/test_dynamic_memory.py` - Update for new API

- Update all tests that check `result.path` to check `result.paths` (list)
- Update content assertions: instead of checking a concatenated temp file, check individual files in `.sase/memory/`
- Add test for the filename derivation helper
- Add test for the section formatting helper

### 6. `tests/test_preprocessing_memory_lines.py` - Remove

This entire test file tests the Prettier protection for `DYNAMIC MEMORY:` lines, which is being removed. Delete the
file.

### 7. `sdd/research/202604/dynamic_memory_critique.md` - Update or note resolved items

Items #5 (temp file accumulation), #6 (injection placement), and #7 (preprocessing fragility) are addressed by this
change. Add a brief note.
