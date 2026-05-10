---
create_time: 2026-04-10 22:45:59
status: draft
prompt: sdd/prompts/202604/commit_parent_flag.md
---

# Plan: Fix PARENT ChangeSpec field for `sase commit -t create_pull_request`

## Problem

When `sase commit -t create_pull_request` is run from a branch other than master/main, the PARENT ChangeSpec field
should be set to the ChangeSpec associated with the current branch. This auto-detection exists in
`_detect_parent_changespec()` (workflow.py:386-417) but is not working reliably, at least for child CLs created by the
`#split` xprompt workflow in retired Mercurial plugin.

## Root Cause Analysis

The auto-detection code in `_detect_parent_changespec()` has two issues:

1. **Silent failure**: The entire method is wrapped in `except Exception: return None`, which silently swallows any
   errors. If `get_cl_name_from_branch()`, `get_project_from_workspace()`, or `get_changespec_from_file()` fails for any
   reason, the parent is silently not set with no indication of what went wrong.

2. **No explicit override**: There is no `--parent` flag on `sase commit`, so callers like the split workflow's
   `split_executor.md` cannot pass the known parent directly. The split workflow already computes `default_parent` in
   its setup step and knows which parent each child CL should have, but this information is lost because `sase commit`
   only supports auto-detection.

In the retired Mercurial plugin split workflow specifically, the executor navigates to the parent CL via
`retired_mercurial_plugin_update <parent>` (which calls `hg update` + `clear_branch_name`) before running `sase commit`. The
auto-detection then calls `branch_name` to determine the current CL, but after `clear_branch_name` this may not return
the expected value, causing `_detect_parent_changespec()` to silently return None.

## Solution

### Phase 1: Add `--parent` / `-p` flag to `sase commit` (sase repo)

Add an explicit `--parent` / `-p` CLI argument that allows callers to specify the parent ChangeSpec name directly. When
provided, this takes precedence over auto-detection.

**Files to change:**

- `src/sase/main/parser_commands.py` — Add `-p` / `--parent` argument to `register_commit_parser()`
- `src/sase/main/cl_handler.py` — Pass `args.parent` into the payload (key: `"parent"`)
- `src/sase/workflows/commit/workflow.py` — In `run()`, check `self._payload.get("parent")` before falling back to
  `_detect_parent_changespec()`; in `_detect_parent_changespec()`, replace the blanket `except Exception: return None`
  with targeted exception handling that logs warnings

### Phase 2: Update split executor to pass parent (retired Mercurial plugin repo)

Update `split_executor.md` to include the parent flag in the `sase commit` invocation so each child CL gets the correct
PARENT set explicitly.

**Files to change:**

- `src/retired_mercurial_plugin/xprompts/split_executor.md` — Change the `sase commit` invocation in step 4 to include `-p <parent>`,
  where `<parent>` is the CL that was navigated to in step 1 (either the entry's explicit `parent` or
  `{{ default_parent }}`)

### Phase 3: Tests

- Add a test for the new `--parent` flag in the commit workflow tests
- Verify existing `_detect_parent_changespec` tests still pass

## Scope

- **In scope**: Adding the `-p`/`--parent` flag, improving error handling in auto-detection, updating the retired Mercurial plugin
  split executor
- **Out of scope**: Fixing the `branch_name` / `clear_branch_name` behavior in retired Mercurial plugin (the explicit flag makes this
  unnecessary)
