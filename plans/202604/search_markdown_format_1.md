---
create_time: 2026-04-01 15:40:44
status: done
---

# Plan: Add `markdown` format to `sase search -f|--format`

## Goal

Add a third format option (`markdown`) to the `sase search` command that renders ChangeSpec results as clean, beautiful,
portable markdown — suitable for reading raw, rendering in GitHub/editors, or piping to files.

## Design Decisions

### Output Structure

Each ChangeSpec renders as a self-contained markdown section:

```markdown
## sase_banana_1

**Status:** Draft · **Project:** myproject

> feat: Add banana-flavored output to the sase CLI
>
> This adds a new --banana flag that makes all output yellow.

| Field     | Value                                    |
| --------- | ---------------------------------------- |
| Parent    | `sase_apple_1`                           |
| CL/PR     | https://github.com/sase-org/sase/pull/42 |
| Bug       | BUG-123                                  |
| Kickstart | Set up the banana module...              |

### Commits

1. **(1)** Initial Commit
   - Chat: `~/.sase/chats/sase-org-pr-260314_222754.md`
   - Diff: `~/.sase/diffs/sase_banana-260314_222754.diff`
2. **(2)** Address review feedback
3. **(2a)** Proposed fix — ⚠️ NEW PROPOSAL

### Hooks

| Hook        | Entry | Timestamp       | Status    | Duration | Note                |
| ----------- | ----- | --------------- | --------- | -------- | ------------------- |
| `just lint` | (1)   | `260315_092521` | ✅ PASSED | 3s       |                     |
| `just test` | (1)   | `260315_092522` | ❌ FAILED | 29s      | Hook Command Failed |
| `just test` | (2)   | `260316_101531` | ✅ PASSED | 31s      |                     |

### Comments

- **[critique]** `~/.sase/comments/banana-critique-260315_093000.json`
- **[critique]** `~/.sase/comments/banana-critique-260316_102000.json` — ⚠️ Unresolved Critique Comments

### Mentors

- **(1)** profile1
  - `profile1:mentor1` — ✅ PASSED (0h2m15s)
  - `profile1:mentor2` — 💬 COMMENTED (0h1m30s)

---
```

After all ChangeSpecs, a summary section:

```markdown
## Summary

**Found 3 ChangeSpec(s):** 1 Draft, 1 Ready, 1 WIP

| Name            | Status | Project      |
| --------------- | ------ | ------------ |
| `sase_banana_1` | Draft  | myproject    |
| `sase_apple_1`  | Ready  | myproject    |
| `sase_cherry_1` | WIP    | otherproject |
```

### Key Design Choices

1. **Status emoji mapping for hook/mentor statuses:**
   - ✅ PASSED — clean success signal
   - ❌ FAILED — clear failure
   - 🔄 RUNNING — active process
   - 💀 KILLED / DEAD — terminated
   - 💬 COMMENTED — mentor produced comments (distinct from pass/fail)

2. **Suffix type rendering** (annotations on commits, hooks, comments):
   - Error (`suffix_type="error"`): ⚠️ prefix
   - Running agent (`suffix_type="running_agent"`): 🤖 prefix
   - Killed agent (`suffix_type="killed_agent"`): 💀 prefix
   - Running/killed process: ⚙️ / 🛑 prefix
   - Summarize complete: 📋 prefix
   - Rejected proposal: 🚫 prefix
   - Plain/None: no prefix, just the message

3. **Metadata table** — only rendered when at least one optional field (Parent, CL, Bug, Kickstart) is present. Omit
   rows for None fields.

4. **File paths** — use `~` for home directory (consistent with plain format), wrapped in backticks for code formatting.

5. **Section headers** — subsections (Commits, Hooks, Comments, Mentors) only appear if the ChangeSpec has data for
   them. No empty sections.

6. **ChangeSpec separator** — horizontal rule (`---`) between each ChangeSpec for visual separation.

7. **Hooks table** — flat table with all status lines. Hook command repeated on each row (markdown tables don't support
   rowspan). Note column only populated when there's a suffix.

8. **Description** — rendered as a blockquote (`>`) to visually distinguish it from metadata.

9. **Multi-line kickstart** — if present, rendered in the metadata table; if very long (multi-line), use a separate
   blockquote sub-section instead of the table row for readability.

10. **TIMESTAMPS** — omitted (consistent with plain format; timestamps are internal bookkeeping, not useful for a
    shareable markdown report).

## Implementation

### Phase 1: Wire up the new format option

**Files:** `parser_commands.py`, `search_handler.py`

- Add `"markdown"` to the `-f|--format` choices list in `register_search_parser`
- Add `elif args.format == "markdown"` dispatch in `handle_search_command`
- Add `_display_markdown(matching)` function

### Phase 2: Implement `_display_markdown`

**File:** `search_handler.py`

Build the `_display_markdown(matching)` function that:

1. Iterates through matching ChangeSpecs
2. For each, builds markdown text covering all fields:
   - Header (H2 with name)
   - Status/project metadata line (bold labels, middle-dot separator)
   - Description as blockquote
   - Optional metadata table for Parent/CL/Bug/Kickstart
   - Commits as ordered list with drawer items (Chat/Diff/Plan)
   - Hooks as table with all status lines
   - Comments as bullet list
   - Mentors as nested bullet list
3. Joins with `---` separators
4. Appends summary section at end
5. Prints all text to stdout

Helper functions within `_display_markdown`:

- `_md_status_emoji(status)` — maps PASSED/FAILED/RUNNING/KILLED/DEAD/COMMENTED to emoji
- `_md_suffix(suffix, suffix_type)` — renders a suffix with appropriate emoji prefix
- `_md_path(path)` — converts path to tilde-relative backtick-wrapped form
- `_md_changespec(cs)` — renders a single ChangeSpec to markdown string
- `_md_summary(matching)` — renders the summary section

### Phase 3: Update help text

- Update the `-f|--format` help string to mention the new `markdown` option
