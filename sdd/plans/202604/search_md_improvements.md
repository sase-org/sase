---
create_time: 2026-04-01 15:51:56
status: active
prompt: sdd/prompts/202604/search_md_improvements.md
---

# Plan: Integrate rejected PR improvements into `sase search --format markdown`

## Goal

Enhance the markdown output format (PR #75, now merged) by integrating the best ideas from rejected PRs #73 and #74, as
recommended in the comparative analysis. These improvements add useful context without compromising the clean,
agent-friendly design.

## Improvements

### 1. Add `project_basename` to metadata line (from PR #74)

Add `**Project:** myproject` to the metadata line after Status. Use `cs.project_basename` property (already exists on
ChangeSpec). This gives cross-project search results meaningful context.

**Before:** `**Status:** Ready · **Parent:** add_config_parser` **After:**
`**Status:** Ready · **Project:** myproject · **Parent:** add_config_parser`

### 2. Include query string in header (from PR #73)

Add
`**Query:** \`status:Ready\``below the summary count line. Requires passing`args.query`through to`\_display_markdown()`.
Valuable when output is piped or shared.

**Before:**

```
# Search Results

Found 3 change(s): 1 Draft, 1 Ready, 1 WIP
```

**After:**

```
# Search Results

**Query:** `status:Ready`

Found 3 change(s): 1 Draft, 1 Ready, 1 WIP
```

### 3. Include commit drawer file paths (CHAT/DIFF/PLAN) (from PR #74)

Add tilde-relative paths for CHAT, DIFF, and PLAN drawers under each commit row. These are actionable references (agent
can read them), not just internal bookkeeping. Render as a sub-row or indented lines after the commits table.

Since markdown tables can't have sub-rows, render drawers as a compact line below the commits table for each commit that
has them:

```
> **1:** `~/...chat.md` · `~/...diff` · `~/...plan.md`
```

### 4. Include Running Workspaces section (from PR #74)

Use `get_claimed_workspaces(cs.file_path)` to show which workspaces are actively claimed. Operationally useful for
understanding what's currently running. Render as a table after the metadata line.

```
### Running Workspaces

| Workspace | PID | Workflow | ChangeSpec |
| --- | --- | --- | --- |
| #1 | 12345 | crs | my_feature |
```

### 5. Include Kickstart section (from PR #74)

Show the kickstart field as a blockquote under a `### Kickstart` heading. This provides useful context about what a
ChangeSpec is trying to accomplish, especially when the description is terse. `cs.kickstart` is `str | None`.

### 6. Add PLAN drawer to commits (from PR #74)

`CommitEntry` has `chat`, `diff`, and `plan` fields. The current implementation renders none of them. Add all three as
part of improvement #3 above.

### 7. Summary anchor quick links (from PR #73)

Add `[name](#name)` links in the summary header for navigating long result sets. Markdown anchors are auto-generated
from `## name` headings, so `[my_feature](#my_feature)` links to the corresponding section.

**After:**

```
Found 3 change(s): 1 Draft, 1 Ready, 1 WIP

[feature_auth](#feature_auth) · [my_fix](#my_fix) · [new_api](#new_api)
```

## Files to Change

### 1. `src/sase/main/search_handler.py`

- **`handle_search_command()`**: Pass `args.query` to `_display_markdown()`.
- **`_display_markdown()`**: Accept `query` parameter. Add query line and anchor quick links to summary header.
- **`_md_changespec()`**: Add `project_basename` to metadata line. Add kickstart section. Add running workspaces
  section. Add drawer paths under commits table.
- New import: `get_claimed_workspaces` from `sase.running_field`.

### 2. `tests/test_search_markdown.py`

- Update `_capture_markdown()` helper to accept optional `query` parameter.
- Update existing snapshot tests for the new project_basename field in metadata.
- Add test for query string in header.
- Add test for commit drawer paths (CHAT/DIFF/PLAN).
- Add test for running workspaces section (will need to mock `get_claimed_workspaces`).
- Add test for kickstart section.
- Add test for summary anchor quick links with multiple ChangeSpecs.
