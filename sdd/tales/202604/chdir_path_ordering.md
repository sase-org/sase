---
create_time: 2026-04-10 20:58:52
status: done
prompt: sdd/prompts/202604/chdir_path_ordering.md
---

# Fix `_chdir` / path resolution ordering bug

## Problem

The `#split` xprompt workflow fails with:

```
ERROR: The following file(s) referenced in the prompt do not exist:
  - @/usr/local/google/home/bbugyi/projects/git/pat_plans/bb/sase/bs_allow_java_1.diff
```

**Root cause**: In `workflow_executor_steps_script.py`, both `_execute_bash_step` and `_execute_python_step` resolve
path-typed output fields to absolute paths **before** processing the `_chdir` special output. This means relative paths
get resolved against the pre-chdir CWD instead of the post-chdir workspace directory.

### Execution flow (current, buggy)

1. `sase_split_setup` runs in a subprocess:
   - Claims workspace, `chdir`s to workspace dir
   - Creates `bb/sase/<cl>.diff` (relative to workspace dir)
   - Prints `_chdir=<workspace_dir>` and `diff_path=bb/sase/<cl>.diff`
2. Executor parses output
3. Executor coerces types
4. **Executor resolves `diff_path` to absolute** using `os.path.abspath()` -- resolves against the **original CWD**, not
   workspace dir
5. HITL review (if any)
6. **Executor processes `_chdir`** -- changes CWD to workspace dir (too late!)
7. Stores output in context

The resolved path points to `<original_cwd>/bb/sase/<cl>.diff` which doesn't exist. The file is at
`<workspace_dir>/bb/sase/<cl>.diff`.

## Fix

Move `_chdir` processing to immediately after output parsing and type coercion, before path field resolution. This
ensures `os.path.abspath()` uses the correct CWD.

### Execution flow (fixed)

1. Parse output
2. Coerce types
3. **Process `_chdir`** (pop from output, chdir)
4. **Resolve path fields** (now uses correct CWD)
5. HITL review
6. Store output in context

## Files to change

- `src/sase/xprompt/workflow_executor_steps_script.py`
  - `_execute_bash_step`: Move the `_chdir` block (currently after HITL, ~line 216) to right after type coercion (~line
    141), before path resolution (~line 154)
  - `_execute_python_step`: Same reorder -- move `_chdir` block (~line 391) to before path resolution (~line 329)
