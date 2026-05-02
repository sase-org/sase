---
create_time: 2026-03-27 14:33:09
status: done
prompt: sdd/prompts/202603/fix_just_workflow.md
---

# Plan: Fix broken `#sase/fix_just` workflow's `fix_fmt` step

## Root Cause Analysis

The `fix_fmt` step in `xprompts/fix_just.yml` has this bash command:

```bash
just fix && git commit -m "chore: run `just fmt`" && git pull && git push
```

There are **two bugs**:

### Bug 1: Backtick command substitution (primary failure cause)

The backticks around `` `just fmt` `` in the commit message are **interpreted by bash as command substitution**, not as
literal backticks. This means bash actually executes `just fmt` a second time and substitutes its stdout into the commit
message.

This perfectly explains the error output — we see 7 command echoes on stderr:

- 4 from `just fix` (fmt-py: 2 commands + fmt-md: 1 + fix-keep-sorted: 1)
- 3 from the backtick-expanded `just fmt` (fmt-py: 2 commands + fmt-md: 1)

The second `just fmt` execution can fail (e.g., if `ruff check --fix` returns non-zero for unfixable errors), and even
if it doesn't, the commit message becomes garbled with `just fmt`'s stdout instead of the literal text.

### Bug 2: Missing `git add` (secondary issue)

Even if the backtick issue were fixed, `git commit -m "..."` without `-a` flag only commits **staged** changes. The
files modified by `just fix` are **unstaged** working tree changes, so `git commit` would fail with "nothing to commit".

## Fix

In `xprompts/fix_just.yml`, change the `fix_fmt` step's bash command to:

1. Escape the backticks with backslashes: `` \`just fmt\` ``
2. Add `git add -A` before `git commit` to stage the formatting changes

Change line 35 from:

```yaml
just fix && git commit -m "chore: run `just fmt`" && git pull && git push
```

to:

```yaml
just fix && git add -A && git commit -m "chore: run \`just fmt\`" && git pull && git push
```
