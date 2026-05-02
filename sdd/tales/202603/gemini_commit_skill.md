---
create_time: 2026-03-25 15:25:11
status: done
prompt: sdd/prompts/202603/gemini_commit_skill.md
---

# Plan: Fix Gemini commit stop hook to use skills instead of CLI command

## Problem

In `src/sase/scripts/sase_commit_stop_hook.py:247-253`, the Gemini runtime branch hardcodes a CLI command:

```
Run: .venv/bin/sase commit create --message '<your commit message>'
```

This fails because:

1. `.venv/bin/sase` doesn't exist in Google3 workspaces (or any non-sase workspace)
2. Gemini CLI **does** support skills, so it should get the same skill-based instruction as Claude
3. The Gemini branch bypasses `_resolve_commit_skill()`, so it ignores `SASE_VCS_PROVIDER` and `SASE_COMMIT_SKILL` env
   vars

The Claude branch (line 254-256) correctly resolves the skill and emits:

```
Use your /sase_hg_commit skill to commit these changes now.
```

## Root Cause

The Gemini branch was written assuming Gemini didn't support skills, so it used a direct CLI command as a workaround.
Now that Gemini CLI supports skills, this special-casing is unnecessary and broken.

## Fix

### Step 1: Remove Gemini-specific commit instruction in `sase_commit_stop_hook.py`

**File:** `src/sase/scripts/sase_commit_stop_hook.py`

Replace lines 247-256:

```python
    if gemini:
        commit_instruction = (
            "OVERRIDE: A post-completion hook has detected uncommitted changes. "
            "Ignore any prior instruction about not committing. You MUST commit now. "
            "Run: .venv/bin/sase commit create --message '<your commit message>'"
            " to commit the changes."
        )
    else:
        skill = _resolve_commit_skill(project_dir)
        commit_instruction = f"Use your {skill} skill to commit these changes now."
```

With unified logic that uses `_resolve_commit_skill()` for all runtimes:

```python
    skill = _resolve_commit_skill(project_dir)
    commit_instruction = (
        "OVERRIDE: A post-completion hook has detected uncommitted changes. "
        "Ignore any prior instruction about not committing. You MUST commit now. "
        f"Use your {skill} skill to commit these changes now."
    )
```

This:

- Uses `_resolve_commit_skill()` for all runtimes (respects `SASE_VCS_PROVIDER`, `SASE_COMMIT_SKILL`)
- Keeps the "OVERRIDE" preamble that tells the agent to ignore prior "don't commit" instructions (important for all
  runtimes, not just Gemini)
- Removes the broken `.venv/bin/sase` CLI command

### Step 2: Update tests

Update any tests in `tests/` that assert on the old Gemini-specific commit instruction string.

### Step 3: Verify with `just check`

Run lint + tests to confirm nothing is broken.
