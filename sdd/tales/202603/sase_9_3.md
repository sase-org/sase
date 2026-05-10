---
create_time: 2026-03-24 02:17:41
status: done
prompt: sdd/prompts/202603/sase_9_3.md
---

# Plan: sase-9.3 — `sase commit` rewrite + new hookspecs + remove `sase amend`

## Bead: sase-9.3

## Overview

Rewrite `sase commit` to be VCS-agnostic by accepting a JSON payload and dispatching to new plugin hooks. Add three new
hookspecs (`vcs_create_commit`, `vcs_create_proposal`, `vcs_create_pull_request`). Remove `sase amend` (but keep
`AcceptWorkflow` which is used by TUI/scheduler).

## Key Findings from Exploration

- `AmendWorkflow` is only imported by `cl_handler.py` — safe to delete
- `AcceptWorkflow` is used by TUI (`change_actions.py`, `proposal_rebase.py`, `hooks_builder.py`, `scheduler`) — must
  keep. Only the CLI entry point (`sase amend --accept`) goes away.
- Current `sase commit` takes `cl_name` + `file_path` positional args with various flags
- New `sase commit` takes JSON payload as positional arg, reads `$SASE_COMMIT_METHOD` env var
- All VCS hooks follow `tuple[bool, str | None]` return convention
- Plugins use `@hookimpl` from `sase.vcs_provider._hookspec`
- `BareGitPlugin` extends `GitCommon` which extends `CommandRunner`

## Implementation Steps

### Step 1: Add new hookspecs (Part A)

**Files to modify:**

1. `src/sase/vcs_provider/_hookspec.py` — Add three new hookspecs under a new "Commit dispatch" section:
   - `vcs_create_commit(payload: dict, cwd: str) -> tuple[bool, str | None]`
   - `vcs_create_proposal(payload: dict, cwd: str) -> tuple[bool, str | None]`
   - `vcs_create_pull_request(payload: dict, cwd: str) -> tuple[bool, str | None]`

2. `src/sase/vcs_provider/_base.py` — Add three optional methods (raise `NotImplementedError` by default) under a new
   "Commit dispatch" section:
   - `create_commit(payload: dict, cwd: str)`
   - `create_proposal(payload: dict, cwd: str)`
   - `create_pull_request(payload: dict, cwd: str)`

3. `src/sase/vcs_provider/_plugin_manager.py` — Add three dispatch methods using `_call_or_raise`:
   - `create_commit(payload: dict, cwd: str)`
   - `create_proposal(payload: dict, cwd: str)`
   - `create_pull_request(payload: dict, cwd: str)`

### Step 2: Add bare_git hook implementations (Part C - bare_git)

**File to modify:** `src/sase/vcs_provider/plugins/bare_git.py`

Implement the three hooks for bare git:

- `vcs_create_commit` — `git add -A` + `git commit` + `git push`
- `vcs_create_proposal` — same as create_commit for bare git
- `vcs_create_pull_request` — `git checkout -b` + `git add -A` + `git commit` + `git push` (no actual PR)

The payload fields used: `message` (commit message), `files` (list of files, or empty for all), `name` (branch name for
PR).

### Step 3: Rewrite `sase commit` CLI (Part B)

**Files to modify:**

1. `src/sase/main/parser_commands.py` — Replace `register_commit_parser`:
   - `payload` positional arg (JSON string)
   - `--method` option to override `$SASE_COMMIT_METHOD`
   - Remove old `cl_name`, `file_path`, bug, project, chat, timestamp, note, message args

2. `src/sase/workflows/commit/workflow.py` — Major rewrite of `CommitWorkflow`:
   - Constructor takes `payload: dict` and `method: str`
   - `run()` method:
     1. Reads `$SASE_COMMIT_METHOD` (or uses `--method` override)
     2. Gets VCS provider
     3. Dispatches to `provider.create_commit()`, `provider.create_proposal()`, or `provider.create_pull_request()`
     4. Handles ChangeSpec creation/update (VCS-agnostic parts) — only for `create_commit` and `create_pull_request`
     5. Handles COMMITS entry tracking

3. `src/sase/main/cl_handler.py` — Rewrite `handle_commit_command`:
   - Parse JSON from `args.payload`
   - Read `$SASE_COMMIT_METHOD` or `args.method`
   - Create and run new `CommitWorkflow`

### Step 4: Add plugin hook implementations (Part C - plugins)

**sase-github** (`../sase-github/src/sase_github/plugin.py`):

- `vcs_create_commit` — `git add` specified files + `git commit -m message` + `git push`
- `vcs_create_proposal` — same as create_commit for GitHub
- `vcs_create_pull_request` — `git checkout -b name` + `git add` + `git commit` + `git push -u` + `gh pr create`

**retired Mercurial plugin** (`../retired Mercurial plugin/src/retired_mercurial_plugin/plugin.py`):

- `vcs_create_commit` — `hg addremove` + `hg amend` (with COMMITS entry note)
- `vcs_create_proposal` — creates proposal on CL
- `vcs_create_pull_request` — creates new CL

### Step 5: Remove `sase amend` (Part D)

**Files to modify:**

1. `src/sase/main/entry.py` — Remove `handle_amend_command` import and `amend` command handler block
2. `src/sase/main/cl_handler.py` — Remove `handle_amend_command` function and `AmendWorkflow` import
3. `src/sase/main/parser_commands.py` — Remove `register_amend_parser` function
4. `src/sase/main/parser.py` — Remove `register_amend_parser` call (need to check)
5. `src/sase/workflows/amend.py` — Delete the file
6. `README.md` — Remove `sase amend` from command table

**Files to keep:**

- `src/sase/workflows/accept/` — AcceptWorkflow is used by TUI, scheduler, and other components

### Step 6: Update tests

- Remove/update any commit workflow tests that test old args
- Add new tests for JSON payload parsing and method dispatch
- Verify no tests reference amend workflow

### Step 7: Run checks

- `just install && just check` in sase core
- Verify no lint/type/test failures

## JSON Payload Schema

```json
{
  "message": "commit message (required for create_commit/create_proposal)",
  "files": ["file1.py", "file2.py"],
  "name": "branch_name (required for create_pull_request)",
  "description": "CL/PR description (for create_pull_request)",
  "note": "optional COMMITS note",
  "wip": false
}
```

## Verification

- `just check` passes
- `sase commit '{"message": "test", "files": []}' --method=create_commit` dispatches correctly
- `sase amend` no longer exists as a command
- Plugin hooks are called correctly for each VCS provider
