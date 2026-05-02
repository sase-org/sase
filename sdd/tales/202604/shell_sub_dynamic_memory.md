---
create_time: 2026-04-12 22:06:02
status: done
prompt: sdd/prompts/202604/shell_sub_dynamic_memory.md
---

# Plan: Use Shell Substitution for Dynamic Memory Content

## Goal

Change memory xprompt content fields from `@` file references to `$(cat ...)` shell substitution. This makes the dynamic
memory temp file self-contained with actual file content, rather than containing `@` references that require the agent
runtime to resolve a second level of indirection.

## Current State

Memory xprompts in `default_config.yml` have content like `@memory/long/generated_skills.md`. When matched,
`generate_dynamic_memory()` writes this string verbatim to a temp file. The prompt then gets
`DYNAMIC MEMORY: @<temp_file>` appended. The agent runtime must resolve `@<temp_file>`, read it, find
`@memory/long/generated_skills.md` inside, and resolve _that_ too -- two levels of `@` resolution.

## Desired State

Content fields use `$(cat memory/long/generated_skills.md)`. `generate_dynamic_memory()` resolves the `$(...)` before
writing to the temp file, so the temp file contains the actual markdown content. The agent runtime only needs to resolve
one `@` reference (the temp file itself).

## Changes

### Phase 1: Update `default_config.yml` content fields

**`src/sase/default_config.yml`**

Change the two memory xprompt content fields:

- `"@memory/long/external_repos.md"` → `"$(cat memory/long/external_repos.md)"`
- `"@memory/long/generated_skills.md"` → `"$(cat memory/long/generated_skills.md)"`

### Phase 2: Resolve shell substitution in `generate_dynamic_memory()`

**`src/sase/memory/dynamic.py`**

After joining matched content and before writing to the temp file, call `process_command_substitution()` from
`sase.gemini_wrapper.file_references` to resolve `$(cat ...)` into actual file content.

This works because `run_agent_runner.py` calls `os.chdir(workspace_dir)` before invoking `generate_dynamic_memory()`, so
`cat memory/long/foo.md` resolves correctly against the workspace (which is a full repo clone).

Update the module docstring to reflect that content is resolved via shell substitution rather than passed through as `@`
references.

### Phase 3: Update AGENTS.md tier 2 section

**`AGENTS.md`**

Update the tier 2 description to mention that matched xprompt content is resolved (via shell substitution) and inlined
into the dynamic memory file, rather than being written as `@` references.

### Phase 4: Update tests

**`tests/test_dynamic_memory.py`**

- Test content fields now use `$(cat ...)` instead of `@memory/long/...`
- Tests that assert temp file content contains `@memory/long/...` need updating:
  - `test_matching_keywords_writes_temp_file`: mock the subprocess call or provide actual files
  - `test_multiple_matches_concatenated`: same
  - `test_returns_structured_result`: check `m.content` has `$(cat ...)` not `@...`
- The `_make_memory_workflows()` helper needs updated content strings
- Since `process_command_substitution` uses `subprocess.run`, tests should either:
  - Create actual `memory/long/` files in `tmp_path` and `chdir` there, or
  - Mock `process_command_substitution` to return known content

### Phase 5: Validation

Run `just install && just check`.
