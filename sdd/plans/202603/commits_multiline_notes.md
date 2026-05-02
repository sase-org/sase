---
create_time: 2026-03-27 17:06:30
status: done
prompt: sdd/prompts/202603/commits_multiline_notes.md
---

# Plan: Multi-line COMMITS Notes with Truncation and Folding

## Problem

COMMITS entries are currently single-line only. The note is extracted via `message.split("\n")[0]`, discarding the
commit message body. Long notes overflow the terminal width with no truncation, and there's no way to include
multi-paragraph notes with blank line separators.

## Design

### File Format

Adopt a continuation-line format using 6-space indentation (aligning with the note text start position after `(N) `).
Body lines are distinguished from drawer lines (`| CHAT:`, `| DIFF:`) by the absence of the `| ` prefix.

**Blank lines within the body** are represented as a line containing only 6 spaces followed by a single dot (`      .`).
This avoids ambiguity with true blank lines that act as section separators in the ChangeSpec parser.

```
COMMITS:
  (1) Short note with no body
  (2) Header line for a multi-paragraph note
      Body paragraph one, first line.
      Body paragraph one, second line.
      .
      Body paragraph two.
      | CHAT: ~/.sase/chats/foo.md
      | DIFF: ~/.sase/diffs/foo.diff
  (3) Another single-line note
```

**Why this format?**

- 6-space indent is already established for CHAT/DIFF continuation lines
- Body lines are unambiguously not drawers (no `| ` prefix, and not `| CHAT:`/`| DIFF:`)
- The `.` blank-line marker is minimal, visually quiet, and cannot collide with real note content (a lone `.` on a
  continuation line would never appear naturally)
- No lookahead needed in the parser: body lines are detected by indent + absence of drawer prefix

### Data Model (`CommitEntry`)

Add a `body: list[str] | None` field to the `CommitEntry` dataclass. Each element is one line of the body. Empty strings
represent paragraph breaks (the `.` markers). The `note` field remains the header line only.

### Parsing

Update `parse_commits_line()` in `section_parsers.py` to accumulate body lines into the current entry. A 6-space
indented line that doesn't start with `| CHAT:` or `| DIFF:` is a body continuation line. A line that is exactly `.`
(after stripping the 6-space indent) represents a blank body line and is stored as `""` in the body list.

Also update the second parser in `renumber_utils.py:parse_commit_entries()` to handle the same continuation format.

### Writing

Update all entry-writing paths to emit body lines when present:

1. `entries.py:add_commit_entry_with_id()` — after the header line, emit body lines at 6-space indent
2. `renumber_utils.py:build_commits_section()` — same treatment when reconstructing
3. `changespec_operations.py:add_changespec_to_project_file()` — same treatment for initial entries

Update `workflow.py:_append_commits_entry()` and `post_commit.py:append_post_commit_entry()` to preserve the full commit
message (header + body), not just the first line. The header is the first line; everything after the first blank line is
the body.

### Truncation (TUI Display)

For entries whose header line exceeds the available display width, truncate the note text with a `…` (unicode ellipsis)
suffix. The truncation calculation accounts for the fixed-width prefix ` (N)` and any suffix ` - (!: MSG)`.

Pass `max_width: int | None` into `build_commits_section()`. The caller (`changespec_detail.py`) will supply
`self.size.width` (available from the Textual widget). When `max_width` is provided:

- Compute `available = max_width - len("  (N) ") - suffix_width - folded_indicator_width`
- If `len(note) > available`, display `note[:available-1] + "…"`

### Folding (TUI Display)

When a note has a body, the body is **folded by default** (hidden). A subtle indicator is appended to the header line
showing the body is present: `  [+N lines]` in dim italic grey (same style as the existing `[folded: ...]` indicators).

Body visibility follows the existing COMMITS fold levels:

- **COLLAPSED**: Body hidden for all entries. Show `[+N lines]` indicator.
- **EXPANDED**: Body shown for all entries. Body lines rendered at 6-space indent in a slightly dimmer shade of the note
  color to visually distinguish header from body. Blank body lines rendered as actual blank lines.
- **FULLY_EXPANDED**: Same as EXPANDED (body visibility doesn't differentiate further).

This reuses the existing fold cycling mechanism (`z`/`Z` keys) — no new keybindings needed.

Body rendering uses a slightly dimmer style (`#B8B890`) compared to the header note style (`#D7D7AF`), with 6-space
indent to visually nest under the header.

## Implementation Phases

### Phase 1: Data Model & Parsing

**Files:**

- `src/sase/ace/changespec/models.py` — Add `body: list[str] | None = None` to `CommitEntry`
- `src/sase/ace/changespec/section_parsers.py` — Update `CommitEntryDict` to include `body` key; update
  `parse_commits_line()` to detect body continuation lines (6-space indent, no `| ` prefix) and `.` blank markers;
  update `build_commit_entry()` to pass body through
- `src/sase/workflows/renumber_utils.py` — Update `parse_commit_entries()` to handle body lines; update
  `build_commits_section()` to emit body lines

**Tests:**

- Add parsing tests for multi-line notes with body, blank line markers, and mixed body+drawer lines
- Add round-trip tests: parse → build → parse produces identical result

### Phase 2: Writing Multi-line Notes

**Files:**

- `src/sase/workflows/commit_utils/entries.py` — Update `add_commit_entry_with_id()` and `add_proposed_commit_entry()`
  to accept and write body lines
- `src/sase/workflows/commit/workflow.py` — Update `_append_commits_entry()` to preserve full message body (split on
  first blank line: header = first line, body = lines after first blank line)
- `src/sase/workflows/commit_utils/post_commit.py` — Update `append_post_commit_entry()` to preserve body from
  commit_result message
- `src/sase/workflows/commit/changespec_operations.py` — Update initial entry creation to support body

**Tests:**

- Test that multi-line commit messages are preserved as header + body
- Test that single-line messages produce no body (backward compatible)
- Test file format output matches expected indentation

### Phase 3: TUI Truncation

**Files:**

- `src/sase/ace/tui/widgets/commits_builder.py` — Add `max_width` parameter to `build_commits_section()`; implement
  header truncation with `…` when note exceeds available width
- `src/sase/ace/tui/widgets/changespec_detail.py` — Pass `self.size.width` to `build_commits_section()`

**Tests:**

- Test truncation at various widths
- Test that suffix is preserved (truncation applies to note text, not suffix)
- Test edge cases: very short width, width exactly matching note length

### Phase 4: TUI Body Folding

**Files:**

- `src/sase/ace/tui/widgets/commits_builder.py` — Render `[+N lines]` indicator when body exists and fold level is
  COLLAPSED; render body lines when fold level is EXPANDED or FULLY_EXPANDED; use dimmer style for body text

**Tests:**

- Test folded indicator shows correct line count
- Test body renders at EXPANDED fold level
- Test body hidden at COLLAPSED fold level
- Test blank body lines render as actual empty lines when expanded
