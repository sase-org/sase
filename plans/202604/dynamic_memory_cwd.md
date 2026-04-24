---
create_time: 2026-04-24 18:30:28
status: done
---
# Plan: Make Dynamic Memory References Stable Across Workflow `chdir`

## Problem

The captured agent failure shows dynamic memory matching `memory/long/buganizer`, followed by prompt file-reference
validation failing on:

```text
@.sase/memory/long-buganizer.md
```

That looks contradictory because `generate_dynamic_memory()` is supposed to create the referenced file before the prompt
is handed to the agent. The contradiction is explained by CWD mutation:

1. `src/sase/axe/run_agent_runner.py` changes into the allocated agent workspace and calls `generate_dynamic_memory()`.
2. `generate_dynamic_memory()` writes each matched memory to `Path(".sase/memory")` and records a relative prompt path
   like `.sase/memory/long-buganizer.md`.
3. The anonymous xprompt workflow then expands embedded workflows such as `#hg` / `#commit`. Script steps may emit
   `_chdir`, and the workflow executor intentionally mutates the process CWD.
4. `preprocess_prompt_late()` then validates/processes `@` file references relative to the current CWD, which may no
   longer be the CWD where dynamic memory was generated.
5. The generated file can exist in the original workspace while validation looks for the same relative path under the
   new CWD and reports it missing.

I verified this behavior locally with a minimal reproduction: generate dynamic memory in temp dir A, append the
formatted `### DYNAMIC MEMORY` section, `chdir` to temp dir B, then run late prompt validation. Validation fails with
the same missing `@.sase/memory/long-buganizer.md` error even though the file exists in temp dir A.

## Fix Direction

Make dynamic-memory prompt references independent of later CWD changes.

The lowest-risk change is to have dynamic memory generation keep writing cache files under the generation CWD's
`.sase/memory/`, but return absolute file paths for injection into the prompt. Absolute `@` references validate against
the actual generated file regardless of any later `_chdir`. This preserves the existing cache location, stale cleanup
behavior, matching logic, and TUI artifact data while removing the fragile assumption that validation happens in the
same CWD as generation.

## Implementation Steps

1. Update `src/sase/memory/dynamic.py`:
   - Resolve `memory_dir` from the generation CWD, e.g. `Path.cwd() / ".sase/memory"`.
   - Keep writing files to that directory.
   - Return absolute paths in `DynamicMemoryResult.paths`.
   - Keep stale cleanup scoped to that same directory.
   - Update docstrings/comments to describe stable absolute prompt references.

2. Update tests in `tests/test_dynamic_memory_formatting.py` and `tests/test_dynamic_memory_matching.py`:
   - Adjust path assertions to accept/expect absolute generated paths.
   - Add a regression test that generates dynamic memory, changes CWD, and validates the formatted section successfully.
   - Keep `_memory_filename()` and section keyword annotation tests focused on formatting and filename behavior.

3. Run focused tests:
   - `just install` if needed for this workspace.
   - `just test tests/test_dynamic_memory_formatting.py tests/test_dynamic_memory_matching.py tests/test_file_references_parsing.py`

4. Run repo checks after source changes:
   - `just check`

## Risk and Tradeoffs

- Absolute paths in the generated prompt are less compact than `.sase/memory/...`, but they are correct across workflow
  `chdir`, subprocess/provider variation, and retry paths.
- In home-directory workspaces, the existing file-reference processor may copy absolute home paths into `.sase/home/`
  during late preprocessing. That still yields an existing reference and is preferable to a hard failure. If this
  becomes noisy, a follow-up can teach file-reference processing to preserve generated dynamic-memory absolute paths.
- Moving dynamic-memory generation later into prompt-step execution would also solve the CWD issue, but it would be a
  broader lifecycle change touching workflow execution, artifacts, and TUI timing. Absolute generated refs address the
  root cause with much smaller blast radius.
