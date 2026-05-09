---
status: done
create_time: 2026-03-29 10:38:27
prompt: sdd/prompts/202603/fix_hg_newline_in_note.md
---

# Fix: hg amend newline failure in legacy-mercurial-plugin vcs_create_commit

## Problem

When `sase commit` runs with `create_commit` method on a Mercurial workspace, multi-line commit messages cause
`hg amend -n` to fail because it only accepts single-line notes.

### Root Cause Chain

1. Agent writes a multi-line commit message to a file (e.g. summary + details across multiple lines)
2. `cl_handler.py` reads it via `f.read().rstrip()` -- preserving internal newlines
3. `_handle_sase_plan()` may further append `\n\nPLAN=<path>` to the message
4. `CommitWorkflow.run()` dispatches to `vcs_create_commit(payload, cwd)`
5. **legacy-mercurial-plugin `vcs_create_commit`** (`plugin.py:355-365`) passes the entire multi-line message as a single note
   argument to `legacy_mercurial_plugin_amend`:
   ```python
   note = f"[run] {message}" if message else "[run] Agent changes"
   out = self._run(["legacy_mercurial_plugin_amend", note], cwd)
   ```
6. `legacy_mercurial_plugin_amend` script passes note to `hg amend -n "${NOTE}"` -- hg rejects the newline

### Evidence

From the logpack at `~/tmp/260329_103341/`:

- Agent reported: "`sase commit` failed with uncommitted changes and a newline issue in the note"
- Agent workaround: retried with a single-line message, which succeeded
- Runtime: Gemini on Mercurial (legacy-mercurial-plugin plugin)

### Contrast with working paths

- `vcs_create_pull_request` handles this correctly by writing message to a temp file and using `--logfile`
- `_append_commits_entry` in the commit workflow correctly extracts only the first line for the note
- `vcs_amend` (called from non-create_commit paths) also passes note as a CLI arg but is typically called with
  single-line notes from the COMMITS append flow

## Fix

### Change 1: `../legacy-mercurial-plugin/src/legacy_mercurial_plugin/plugin.py` -- `vcs_create_commit`

Extract only the first line of the message for the note argument, since `hg amend -n` only supports single-line notes:

```python
message = payload.get("message", "")
# hg amend -n only supports single-line notes -- use first line only
first_line = message.split("\n")[0] if message else ""
note = f"[run] {first_line}" if first_line else "[run] Agent changes"
```

### Change 2: `../legacy-mercurial-plugin/tests/test_hg_plugin.py` -- add test

Add a test that verifies multi-line messages only pass the first line to `legacy_mercurial_plugin_amend`.
