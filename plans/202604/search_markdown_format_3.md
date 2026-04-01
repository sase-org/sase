---
create_time: 2026-04-01 15:40:59
status: done
---

# Plan: Add `markdown` format to `sase search -f|--format`

## Goal

Add a `markdown` output format to `sase search` that renders ChangeSpecs as clean, self-documenting markdown. The target
audience is AI agents that know nothing about ChangeSpec internals - every piece of domain jargon should be translated
into plain language with standard markdown conventions.

## Design

### Output Structure

```markdown
# Search Results

Found 3 changes: 1 Draft, 1 Ready, 1 WIP

---

## feature_auth

**Status:** Ready · **Parent:** add_config_parser · **Bug:** b/12345 **PR:** https://github.com/org/repo/pull/42

> Add new feature for user authentication
>
> This change implements a complete authentication system with JWT token support and role-based access control.

### Commits

| #   | Description                          | Status             |
| --- | ------------------------------------ | ------------------ |
| 1   | Initial JWT validator implementation |                    |
| 2   | Integrate validator into middleware  |                    |
| 2a  | Alternative approach                 | :warning: Proposal |

### Test Hooks

| Hook      | Commit | Result                    | Duration |
| --------- | ------ | ------------------------- | -------- |
| run_tests | #1     | :white_check_mark: Passed | 1m23s    |
| run_tests | #2     | :x: Failed                | 2m15s    |

### Review Comments

| Reviewer | Status                                 |
| -------- | -------------------------------------- |
| critique | :warning: Unresolved Critique Comments |
| review   | :white_check_mark:                     |

### Mentors

| Commit | Mentor                | Result                            | Duration |
| ------ | --------------------- | --------------------------------- | -------- |
| #1     | perf_reviewer / alice | :arrows_counterclockwise: Running |          |
| #1     | code_reviewer / bob   | :white_check_mark: Passed         | 3h5m12s  |

---

## next_changespec_name

...
```

### Key Design Decisions

1. **Summary header** - `# Search Results` with a human-readable count and status breakdown, so the reader immediately
   knows scope.

2. **Metadata line** - Status, parent, bug, and PR on one or two compact lines using bold labels and `·` separators.
   Only non-null fields appear. This avoids a wall of key-value pairs.

3. **Description as blockquote** - Visually distinct from metadata. Multi-line descriptions preserve paragraph breaks
   inside the blockquote.

4. **Kickstart omitted** - The kickstart field is an internal prompt/instruction, not useful for an external reader.
   Omit it.

5. **Tables for structured data** - Commits, hooks, comments, and mentors each get a markdown table. Tables are
   universally parseable and scannable.

6. **Suffix translation** - All suffix types (`!:`, `@:`, `~@:`, `$:`, `?$:`, `~$:`, `~!:`, `%:`) are translated to
   human-readable text with GitHub-compatible emoji shortcodes:
   - `:white_check_mark:` for Passed/Submitted/Commented
   - `:x:` for Failed/Error conditions
   - `:arrows_counterclockwise:` for Running (agent or process)
   - `:warning:` for warnings (proposals, unresolved comments, zombie)
   - `:skull:` for Dead/Killed

7. **No file paths** - Chat, diff, plan paths, and `.gp` file locations are internal artifacts. Omit them since they
   mean nothing to an external agent.

8. **No RUNNING field** - Workspace claims are infrastructure state, not useful for understanding the change itself.

9. **No TIMESTAMPS** - The audit log is operational noise for an external reader.

10. **Horizontal rules** between ChangeSpecs for clear visual separation.

11. **Emoji shortcodes over unicode** - Using `:white_check_mark:` instead of raw unicode ensures consistent rendering
    across markdown renderers (GitHub, GitLab, most agent UIs). The shortcodes are more readable in raw form too.

### Hooks Table: Flattened Rows

Each hook status line becomes its own row. The hook command column uses the display command (prefixes stripped). This
makes it easy to see per-commit results at a glance without understanding the nested structure.

### Comments Table: Suffix as Status

If a comment has no suffix, it shows as just the reviewer type with a checkmark. If it has an error suffix (like
"Unresolved Critique Comments"), that becomes the status cell with a warning indicator.

## Files to Change

### 1. `src/sase/main/parser_commands.py`

- Add `"markdown"` to the `choices` list for `-f|--format`
- Update help text to mention the new option

### 2. `src/sase/main/search_handler.py`

- Add `elif args.format == "markdown":` routing in `handle_search_command()`
- Implement `_display_markdown(matching)` - top-level renderer that prints the summary header, then iterates over
  ChangeSpecs calling per-section helpers
- Implement private helpers (all within this file, no new modules):
  - `_md_status_indicator(status, suffix, suffix_type)` - maps status + suffix info to emoji shortcode
  - `_md_changespec(cs)` - renders a single ChangeSpec as markdown lines
  - Inline table construction for commits, hooks, comments, mentors (no separate helper functions needed for simple
    table building)

### 3. `tests/test_search_markdown.py` (new file)

- Unit tests for `_display_markdown()` covering:
  - Minimal ChangeSpec (just name, description, status)
  - Full ChangeSpec with all sections populated
  - Multiple ChangeSpecs (verify separator)
  - Suffix type translation (error, running, killed, etc.)
  - Summary header accuracy
  - Null/empty field handling (no parent, no CL, no commits, etc.)
