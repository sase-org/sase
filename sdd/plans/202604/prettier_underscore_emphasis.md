---
create_time: 2026-04-12 23:08:18
status: done
prompt: sdd/prompts/202604/prettier_underscore_emphasis.md
---

# Fix Prettier Converting Underscores to Asterisks in File Paths

## Problem

Prettier's markdown formatter interprets `_text_` as emphasis and normalizes it to `*text*`. When a
dynamically-generated temp file path contains matching underscore pairs (e.g., `sase_dynamic_memory_ghsbpnu_.md`),
Prettier converts it to `sase*dynamic_memory_ghsbpnu*.md`, corrupting the path.

This is **intermittent** — it only triggers when Python's `tempfile.NamedTemporaryFile` generates a random suffix ending
with `_`, creating a matching `_..._` pair with the prefix's trailing underscore. Roughly 1 in 37 runs are affected.

The existing fix in `format_with_prettier()` (lines 474-480 of `file_references.py`) only handles `_` backslash-escaped
underscores, not Prettier's `_emphasis_` → `*emphasis*` normalization.

## Affected Flow

1. `run_agent_runner.py:247` — injects `XPROMPT MEMORY: @<tmp_path>` into the prompt
2. `workflow_executor_steps_prompt.py:217` — calls `preprocess_prompt_late()` on the prompt
3. `preprocessing.py:161` — calls `format_with_prettier(prompt)` inside `preprocess_prompt_late()`
4. Prettier corrupts underscores in the file path
5. Corrupted prompt is saved to artifacts and displayed in `sase ace` TUI

## Fix

Protect the `XPROMPT MEMORY:` line from Prettier processing using the same protect/unprotect placeholder pattern already
established for fenced code blocks and disabled regions.

### Changes

**`src/sase/llm_provider/preprocessing.py`** — Add protect/unprotect steps around Prettier:

Between step 1 (protect fenced blocks) and step 5 (prettier), add a new protection step that extracts lines matching
`^XPROMPT MEMORY: .*$` and replaces them with null-byte placeholders. After Prettier runs (step 5), restore the original
lines before proceeding to step 6.

Use a simple inline approach (no new module needed) — the pattern is a single regex on the full prompt text, following
the same `\x00`-delimited placeholder convention:

```
# Between steps 1 and 2: protect XPROMPT MEMORY lines
memory_lines: list[str] = []
prompt = _protect_memory_lines(prompt, memory_lines)

# ... steps 2-5 unchanged ...

# After step 5, before step 6: restore XPROMPT MEMORY lines
prompt = _unprotect_memory_lines(prompt, memory_lines)
```

The helper functions can live at the top of `preprocessing.py` (private module-level functions). The regex pattern
should be `r'^XPROMPT MEMORY: .+$'` with `re.MULTILINE`.

**`tests/`** — Add a test that verifies a prompt containing `XPROMPT MEMORY: @path/sase_dynamic_memory_abc_.md` survives
`preprocess_prompt_late()` with underscores intact. The test should mock `format_with_prettier` to call the real
Prettier binary (or simulate its behavior) to confirm the protection works end-to-end.
