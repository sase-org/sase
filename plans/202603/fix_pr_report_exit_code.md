---
create_time: 2026-03-29 18:10:10
status: done
---

# Fix: pr.yml report bash step exits non-zero when optional metadata is empty

## Problem

Agent `@t` (and likely other agents using the `#pr` xprompt) failed with:

```
WorkflowExecutionError: Bash step 'report' failed: meta_pr_header=fix: enforce prettier formatting for committed plan files
```

The `report` step in `src/sase/xprompts/pr.yml` is a bash script that outputs optional `meta_*` key=value pairs. The
last two lines use `[ -n "$var" ] && echo ...` patterns:

```bash
[ -n "$result" ] && echo "meta_pr_url=$result"
[ -n "$changespec_name" ] && echo "meta_changespec=$changespec_name"
```

When both `$result` and `$changespec_name` are empty (common — e.g. when the commit hook created a commit but no PR/CL
was opened, or no changespec was associated), the last `[ -n ... ]` test evaluates to false, giving exit code 1. Since
it's the final command in the script, the entire script exits with code 1.

The bash step execution code in `workflow_executor_steps_script.py:118-125` treats any non-zero exit as a failure,
raising `WorkflowExecutionError` with stdout as the error message.

## Fix

Add `exit 0` at the end of the `report` bash step in `pr.yml` to ensure the script always exits successfully regardless
of whether optional metadata variables were populated.

### Files to change

- `src/sase/xprompts/pr.yml` — Add `exit 0` after line 70 (the last conditional echo)

This is a one-line fix. No other workflow files are affected — `commit.yml`, `propose.yml`, and `sync.yml` all use
Python for their `report` steps, which don't have this shell exit-code issue.
