---
create_time: 2026-04-12 21:09:07
status: done
prompt: sdd/prompts/202604/dynamic_memory_prompt_injection.md
---

# Plan: Dynamic Memory via Prompt Injection

## Goal

Change dynamic memory delivery from a workspace file (`memory/dynamic.md`) with TUI display to a temp file whose path is
injected directly into the agent prompt. This makes the dynamic memory visible in the prompt itself, eliminating the
need for special TUI support.

## Current State

The current implementation (from `dynamic_memory_3` plan):

1. `generate_dynamic_memory()` in `src/sase/memory/dynamic.py` writes matched `@` references to
   `{workspace_dir}/memory/dynamic.md`
2. AGENTS.md tier 2 section tells agents to look for `@memory/dynamic.md`
3. The TUI reads `dynamic_memory.json` artifact and displays a DYNAMIC MEMORY section
4. `.gitignore` excludes `memory/dynamic.md`

## Changes

### Phase 1: Modify `generate_dynamic_memory()` to write to temp file

**`src/sase/memory/dynamic.py`**

- Stop writing to `{workspace_dir}/memory/dynamic.md`. Instead, write matched content to a temp file under
  `get_sase_tmpdir()` (from `sase.core.paths`), falling back to system temp if `$SASE_TMPDIR` is unset.
- Use `tempfile.NamedTemporaryFile(delete=False, suffix=".md", prefix="sase_dynamic_memory_")` so the file persists for
  the agent session.
- Return the temp file path alongside the match data (add a `path` field or change return type to include it).
- Remove the cleanup logic that deletes `memory/dynamic.md` when no matches found (no longer relevant).

### Phase 2: Inject dynamic memory line into prompt

**`src/sase/axe/run_agent_runner.py`**

- After calling `generate_dynamic_memory()`, if there are matches, append a line to the prompt string:
  `\n\nDYNAMIC MEMORY: @<tmp_file_path>`
- This modified prompt flows through to the agent via `run_execution_loop(ctx, prompt)`. The agent runtime resolves the
  `@` reference and includes the tier 3 file content.
- Keep the artifact save (`dynamic_memory.json`) and console print for logging.

### Phase 3: Remove TUI dynamic memory display

Three removals:

1. **`src/sase/ace/tui/widgets/prompt_panel/_agent_display.py`** -- Remove the entire DYNAMIC MEMORY section (lines
   62-87). The dynamic memory is now visible in the AGENT PROMPT section since it's part of the prompt string.

2. **`src/sase/ace/tui/models/agent_artifacts.py`** -- Remove the `get_dynamic_memory_info()` function.

3. **`src/sase/ace/tui/models/agent.py`** -- Remove the `get_dynamic_memory_info()` method.

### Phase 4: Update AGENTS.md

**`AGENTS.md`**

Rewrite the tier 2 section to explain the new injection mechanism. Something like:

```
## Tier 2 (dynamic) Memory

When your prompt matches keywords from memory-tagged xprompts, sase injects a `DYNAMIC MEMORY: @<path>` line at the
bottom of your prompt. The `@` reference resolves to the matched tier 3 content automatically. You do not need to take
any action -- the content is included in your context.
```

### Phase 5: Clean up `.gitignore`

**`.gitignore`**

Remove the `memory/dynamic.md` entry and its comment. We no longer write to the workspace.

### Phase 6: Update tests

**`tests/test_dynamic_memory.py`**

- Update tests that assert on `memory/dynamic.md` existence to instead check for the temp file path.
- Update tests that check file cleanup behavior (no longer relevant since we use temp files).
- Add a test verifying the temp file is written to `get_sase_tmpdir()` when set.

### Phase 7: Validation

Run `just install && just check`.
