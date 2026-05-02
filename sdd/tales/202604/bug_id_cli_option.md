---
create_time: 2026-04-03 14:24:05
status: done
prompt: sdd/prompts/202604/bug_id_cli_option.md
---

# Plan: Add `-B|--bug-id` CLI Option to `sase commit`

## Context

Currently, the `sase commit` command reads the bug ID exclusively from the `$SASE_BUG_ID` environment variable. This is
used in two places within `CommitWorkflow` (in `src/sase/workflows/commit/workflow.py`):

1. **`_append_pr_tags()`** (line ~340): Reads `os.environ.get("SASE_BUG_ID", "")` to prepend a `BUG=<id>` tag to PR
   messages.
2. **`_create_changespec()`** (line ~433): Reads `os.environ.get("SASE_BUG_ID", "").strip()` to set the `bug` field on
   ChangeSpecs as `http://b/<id>`.

The goal is to add a `-B|--bug-id` CLI flag (taking an integer) so users can pass the bug ID explicitly without needing
the env var. The CLI flag should take precedence over the env var (standard CLI-over-env convention).

## Phase 1: Add CLI argument

**File: `src/sase/main/parser_commands.py`** (after `--bead-id`)

Add a new `-B/--bug-id` argument with `type=int` and `default=0`.

## Phase 2: Thread `bug_id` through the handler into the payload

**File: `src/sase/main/cl_handler.py`**

After constructing the payload dict, add `bug_id` as a string if the CLI flag was set (non-zero). This matches the
existing pattern for optional payload fields like `bead_id` and `name`.

## Phase 3: Use payload `bug_id` in CommitWorkflow, falling back to env var

**File: `src/sase/workflows/commit/workflow.py`**

In both `_append_pr_tags()` and `_create_changespec()`, prefer `self._payload.get("bug_id", "")` over the env var, using
`or` to fall back to `$SASE_BUG_ID` when the payload value is absent or empty.

## Phase 4: Add tests

- **`tests/test_commit_cli.py`**: CLI parsing tests for `-B` flag (flag present, default omitted)
- **`tests/test_pr_tags.py`**: PR tags from payload, payload-overrides-env
- **`tests/test_commit_workflow_changespec.py`**: ChangeSpec from payload, payload-overrides-env

## What we do NOT need to change

- **`/sase_git_commit` skill**: Per user requirement, no skill updates needed.
- **xprompt files** (`pr.yml`, `commit.yml`): These set `SASE_BUG_ID` as an env var which still works as the fallback.
