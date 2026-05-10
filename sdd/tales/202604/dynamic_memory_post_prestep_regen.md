---
create_time: 2026-04-24 18:44:39
status: done
prompt: sdd/prompts/202604/dynamic_memory_post_prestep_regen.md
---
# Plan: Regenerate dynamic memory after embedded-workflow pre-steps

## Problem

Agents fail at file-reference validation with:

```
=== Dynamic Memory ===
  + memory/long/buganizer  (matched: b/)
======================

❌ ERROR: The following file(s) referenced in the prompt do not exist:
  - @.sase/memory/long-buganizer.md
```

The matched memory was clearly produced (so `generate_dynamic_memory` ran, picked the workflow, executed `$(cat …)`, and
wrote the file), yet validation later in the same process reports the file missing — and the workflow terminates before
the agent is ever invoked.

Captured run: `.sase/home/tmp/scratch/memory_file_not_exist.txt` (an `ace(run)` agent for `yserve_read_grow` in
workspace `/google/src/cloud/bbugyi/yserve_102/google3`).

## Root Cause

The dynamic-memory file is written too early — **before** an embedded workflow's pre-steps run, and those pre-steps (in
this case `#hg`'s `prepare`) wipe the workspace.

Sequence:

1. `src/sase/axe/run_agent_runner.py:204` — `os.chdir(workspace_dir)`.
2. `src/sase/axe/run_agent_runner.py:209` — `generate_dynamic_memory(prompt, project_name)` writes
   `<cwd>/.sase/memory/long-buganizer.md`.
3. `src/sase/axe/run_agent_runner.py:236` — appends `### DYNAMIC MEMORY` section referencing
   `@.sase/memory/long-buganizer.md` to the prompt.
4. `src/sase/axe/run_agent_runner.py:348` — `run_execution_loop` → `execute_workflow` → `_execute_prompt_step` (in
   `src/sase/xprompt/workflow_executor_steps_prompt.py`).
5. `workflow_executor_steps_prompt.py:184` — `preprocess_prompt_early` (xprompt expansion).
6. `workflow_executor_steps_prompt.py:200` — `_expand_embedded_workflows_in_prompt` runs the embedded workflow's
   pre-steps. For `#hg:yserve_read_grow` (defined in `retired Mercurial plugin_100/src/retired_mercurial_plugin/xprompts/hg.yml`):
   - `setup` (Python) emits `_chdir=<workspace_dir>` → executor calls `os.chdir` (see
     `workflow_executor_steps_script.py:142-149`).
   - `prepare` (bash) runs `retired_mercurial_plugin_clean`, which executes `hg update --clean .` and `hg clean` — **removing
     untracked files, including `.sase/memory/long-buganizer.md`**.
7. `workflow_executor_steps_prompt.py:217` — `preprocess_prompt_late` runs `validate_file_references`. The file is gone
   → `sys.exit(1)`.

Why the same problem doesn't always surface: workflows whose pre-steps don't clean the workspace (or whose clean ignores
`.sase/`) survive. The bug is structural — the early write is racy with any pre-step that mutates the workspace,
including future plugins that aren't `hg`.

## Approach

Move the dynamic-memory write into `preprocess_prompt_late` (or immediately before it), so it runs **after** all
embedded-workflow pre-steps have finished mutating the workspace and after any `_chdir`. The file appears in the prompt
as `@…` once and exists on disk when validation runs.

The keyword-matching pass and the file write currently live together in `generate_dynamic_memory`. We split them:
matching/section-formatting can stay early (so the printed `=== Dynamic Memory ===` snapshot and `dynamic_memory.json`
artifact still come out at the runner level), while the actual `write_text` to `.sase/memory/` happens late.

Two equivalent shapes; we'll go with the second:

- **A.** Run `generate_dynamic_memory` twice — once early (for the snapshot/artifact + section in the prompt), once late
  (just before validation, idempotent file write). Simple but does the keyword scan twice.
- **B (preferred).** Split the function: keep `generate_dynamic_memory` for matching, factor out
  `_write_memory_files(matched)` and call it at both the runner site (best-effort) and inside `preprocess_prompt_late`
  immediately before `validate_file_references`. The late call is the load-bearing one; the early call is a no-op if the
  late call rewrites the same content.

We keep the early call so we don't lose:

- The user-visible `=== Dynamic Memory === / + memory/long/foo (matched: …)` snapshot in the agent log.
- The `artifacts_dir/dynamic_memory.json` artifact.
- The section being part of the prompt that's printed and saved.

## Phases

### Phase 1 — Split write from match in `dynamic.py`

**File:** `src/sase/memory/dynamic.py`

Refactor so the `for m in matched: file_path.write_text(...)` loop is its own function:

```python
def write_memory_files(matched: list[MatchedMemory]) -> list[str]:
    """Resolve $(cat ...) substitution and write each matched memory to .sase/memory/.

    Idempotent — overwrites existing files. Uses the *current* CWD, so callers
    that want files written into a freshly-cleaned workspace must call this
    after any chdir/clean has already happened.
    """
```

`generate_dynamic_memory` continues to call `write_memory_files` so its existing return shape and call sites don't
change.

### Phase 2 — Late regeneration inside `preprocess_prompt_late`

**File:** `src/sase/llm_provider/preprocessing.py`

Just before step 3 (file references), parse the `### DYNAMIC MEMORY` section out of the prompt, re-resolve the matched
memories from the loader, and call `write_memory_files` so the on-disk files exist relative to the _current_ CWD.

Sketch:

```python
# 2.5 Re-write dynamic memory files after pre-steps may have wiped them
from sase.memory.dynamic import (
    rewrite_dynamic_memory_for_prompt,  # new helper, see below
)
rewrite_dynamic_memory_for_prompt(prompt)
```

`rewrite_dynamic_memory_for_prompt` (new, in `dynamic.py`):

1. Find the `### DYNAMIC MEMORY` section in `prompt`. If absent, return.
2. Extract the listed memory names (parse `- @.sase/memory/<filename>` back to xprompt name via the inverse of
   `_memory_filename`, or — cleaner — store the xprompt name explicitly in the section format, e.g.
   `- @.sase/memory/long-foo.md (memory/long/foo, matched: …)` so we don't need a fragile inverse).
3. Look those memories up via `get_all_prompts(project=None)` (project detection is fine; the loader walks the standard
   search paths).
4. Call `write_memory_files` with the resolved list.

Section-format change: extend `format_dynamic_memory_section` to embed the xprompt name in each line so the late-phase
parser doesn't need to invert `_memory_filename` (the existing `_` ↔ `-` collapse is lossy). The agent doesn't care
about the extra annotation; humans see it as helpful context.

### Phase 3 — Keep early call as best-effort + snapshot

**File:** `src/sase/axe/run_agent_runner.py`

No structural change: the existing call at line 209 stays. It still:

- Prints `=== Dynamic Memory ===` for the agent log.
- Writes `dynamic_memory.json` artifact.
- Appends the section to the prompt that's saved as `raw_xprompt.md` and forwarded into the workflow.

Its on-disk write may be wiped later by pre-steps; the late phase regenerates it. No code change here, but add a comment
explaining the early/late split so the next reader doesn't "fix" it.

### Phase 4 — Tests

**File:** `tests/test_dynamic_memory.py` (or wherever existing dynamic-memory tests live).

Add:

1. **Pre-step wipe test.** Set up a fake workspace with a `memory/long/foo.md` source. Run the full prompt pipeline with
   a fake embedded workflow whose pre-step deletes `.sase/memory/long-foo.md`. Assert that `preprocess_prompt_late`
   succeeds (file exists at validation time).
2. **`_chdir` test.** Same setup, but the fake pre-step `os.chdir`s into a sibling directory. Assert the late phase
   writes the file into the new CWD's `.sase/memory/` and validation passes.
3. **No-op when no DYNAMIC MEMORY section.** Prompts without the section must not trigger keyword scanning in the late
   phase.
4. **Existing tests.** All current dynamic-memory tests must continue to pass.

### Phase 5 — Verify with the original repro

Reproduce the failing scenario locally (or via the user's google3 workspace) and confirm an `ace(run)` with a
`b/`-keyword-matching prompt + embedded `#hg` succeeds end-to-end.

## Files to Touch

- `src/sase/memory/dynamic.py` — split out `write_memory_files`, add `rewrite_dynamic_memory_for_prompt`, extend
  `format_dynamic_memory_section` to embed xprompt names.
- `src/sase/llm_provider/preprocessing.py` — call `rewrite_dynamic_memory_for_prompt` in `preprocess_prompt_late` just
  before `validate_file_references`.
- `src/sase/axe/run_agent_runner.py` — comment-only change explaining the early/late split.
- `tests/test_dynamic_memory.py` (or equivalent) — new tests per Phase 4.

## Out of Scope

- Teaching `retired_mercurial_plugin_clean` (in the `retired Mercurial plugin` plugin) to preserve `.sase/`. That would be defense in depth, but
  the same class of bug would still surface for any other plugin/workflow that mutates the workspace between early and
  late phases. Fixing this in sase core makes plugins not need to know about `.sase/memory/`.
- Reordering `generate_dynamic_memory` to run only late. Possible but loses the early log snapshot / artifact, which the
  user (and TUI consumers) rely on.

## Open Questions

1. **Section format change OK?** Extending `format_dynamic_memory_section` to include the xprompt name
   (`- @.sase/memory/long-foo.md (memory/long/foo, matched: ...)`) is the cleanest way to avoid inverting
   `_memory_filename`. The line is human-readable text the agent sees; should be fine, but worth confirming.
2. **Project detection in late phase.** The early call uses `project_name` derived from `project_file`. The late phase
   doesn't have that handy — defaulting to `project=None` triggers `detect_project()` from CWD, which after `_chdir` is
   the right workspace. Acceptable, or do we need to thread `project` through?
3. **Other plugins (`#gh`, etc.).** Likely affected the same way. Fix lands in core, so they're covered; no plugin
   changes required.
