---
create_time: 2026-03-26 19:45:27
status: done
prompt: sdd/prompts/202603/fix_duplicate_status_frontmatter.md
---

# Fix Duplicate `status` Field in Plan File Frontmatter

## Problem

`add_create_time_frontmatter()` in `src/sase/llm_provider/_plan_utils.py` produces duplicate `status` fields when
existing frontmatter already contains `status` but no `create_time`.

## Root Cause

Line 45 bundles both fields together:

```python
fields = f"create_time: {ts}\nstatus: wip"
```

Line 62 (the else branch — no existing `create_time`) appends the entire `fields` string without checking whether
`status` already exists:

```python
return f"---\n{fm_body}{fields}\n---\n{content[end + 5 :]}"
```

Result when frontmatter already has `status: wip`:

```yaml
---
status: done
create_time: 2026-03-26 19:21:26
status: done
---
```

## Implementation Plan

### Phase 1: Fix the function logic

**File:** `src/sase/llm_provider/_plan_utils.py`

In the else branch at line 62, build the appended fields conditionally:

- Always append `create_time: {ts}`
- Only append `status: wip` if `status:` is not already present in `fm_body`

Concretely, replace the single `fields` variable (line 45) with conditional construction in the else branch, or check
for existing `status` before appending. The simplest fix:

```python
# Build fields to append — skip status if already present
extra = f"create_time: {ts}"
if not re.search(r"^status:", fm_body, re.MULTILINE):
    extra += "\nstatus: wip"
return f"---\n{fm_body}{extra}\n---\n{content[end + 5 :]}"
```

Also handle the `create_time`-exists branch (line 60) similarly: if that branch fires, `status` might also be missing,
so add it there too if needed.

### Phase 2: Add test coverage

**File:** `tests/test_plan_utils.py`

Add a test: existing frontmatter with `status: wip` but no `create_time`. Assert the result has exactly one `status`
field and the correct `create_time`.

### Phase 3: Fix existing plan files

Remove the second (duplicate) `status` line from these 5 files:

- `plans/commit_diff_drawer.md`
- `plans/commit_propose_pr_bug_bash.md`
- `plans/fix_embedded_env_injection.md`
- `plans/pr_agent_info_footer.md`
- `plans/remove_commit_fallbacks.md`
