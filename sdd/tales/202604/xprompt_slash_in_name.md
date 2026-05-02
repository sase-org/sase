---
create_time: 2026-04-01 13:21:49
status: done
prompt: sdd/prompts/202604/xprompt_slash_in_name.md
---

# Fix: FileNotFoundError when xprompt name contains slashes

## Problem

Creating a config xprompt with a hierarchical name like `prs/compare` crashes with `FileNotFoundError`. The `/` in the
name is passed directly into the `tempfile.mkstemp` prefix, which interprets it as a directory separator — resulting in
a path like `/tmp/xprompt_prs/compare_xxx.md` where the intermediate directory doesn't exist.

## Root Cause

`xprompt_browser_actions.py:144` — `entry.name` is used unsanitized in the temp file prefix:

```python
tmp_fd, tmp_path = tempfile.mkstemp(
    suffix=".md", prefix=f"xprompt_{entry.name}_"
)
```

## Fix

Sanitize the name for use as a temp file prefix by replacing `/` with `_`:

```python
safe_name = entry.name.replace("/", "_")
tmp_fd, tmp_path = tempfile.mkstemp(
    suffix=".md", prefix=f"xprompt_{safe_name}_"
)
```

The sanitization only applies to the temp file prefix — the actual xprompt name (`entry.name`) is preserved everywhere
else (config insertion, notifications, commit messages).

## Secondary Fix

`task_queue_modal.py:291-293` has the same pattern with `task.cl_name`, which could also contain `/`:

```python
fd, path = tempfile.mkstemp(
    suffix=".log", prefix=f"task_{task.task_type}_{task.cl_name}_"
)
```

Apply the same sanitization there for robustness.

## Files to Modify

1. `src/sase/ace/tui/modals/xprompt_browser_actions.py` — sanitize `entry.name` in mkstemp prefix
2. `src/sase/ace/tui/modals/task_queue_modal.py` — sanitize `task.cl_name` in mkstemp prefix
