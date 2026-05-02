---
create_time: 2026-03-23 16:00:01
status: done
prompt: sdd/prompts/202603/comments_command.md
---

# Plan: `sase comments` CLI Command

## Goal

Add a `sase comments` command that takes the same JSON schema used by the `comments` field in mentor output, validates
it, and renders a rich terminal preview that mirrors the mentor review panel in the TUI. Mentors can use this to verify
their JSON output before replying.

## Context

- **Mentor output schema**: `MENTOR_OUTPUT_JSON_SCHEMA` in `src/sase/ace/mentor_output.py` — an object with a `comments`
  array where each item has `focus_name`, `file_path`, `line_number`, `description`, `severity`.
- **TUI rendering**: `MentorReviewModal._update_main_panel()` renders each comment with header, focus/severity, file
  path, description, and a syntax-highlighted code snippet centered on the target line.
- **Code snippets**: `_build_code_snippet()` uses Rich `Syntax` with monokai theme, line numbers, highlight on the
  target line, and a window centered on `line_number`.
- **CLI pattern**: Parser definitions in `src/sase/main/parser.py`, handlers in `src/sase/main/entry.py`, each command
  gets its own handler module.

## Design Decisions

1. **Input**: Read JSON from **stdin** (the natural way for a mentor agent to pipe output). Also support a positional
   file path argument for manual testing.

2. **Validation**: Validate against `MENTOR_OUTPUT_JSON_SCHEMA` using `jsonschema` (already a dependency) or manual
   validation. Report clear errors with line/field context.

3. **Code snippets**: Read files directly from the **working directory filesystem**. This is correct because mentors
   review the current state of files. Show ~11 lines centered on the target line (matching TUI default), with the target
   line highlighted.

4. **Rendering**: Use Rich `Console` + `Syntax` to render to stdout. This produces the same visual output a mentor would
   see in the TUI review panel — colored severity, syntax-highlighted snippets, etc.

5. **Snippet window size**: Use a `--context` / `-c` flag (default 5 lines above/below = 11 total) to control how many
   lines of code context surround the target line, since we don't have a panel height to compute from.

6. **Exit code**: 0 if valid JSON with all files readable, 1 if validation fails, 2 if any referenced files are missing
   (but still render what we can).

## Implementation Steps

### Step 1: Add parser definition (`src/sase/main/parser.py`)

Add a `comments` subcommand (alphabetically between `commit` and `config`):

```python
# --- comments ---
comments_parser = top_level_subparsers.add_parser(
    "comments",
    help="Preview mentor comments from JSON (reads from stdin or file)",
)
comments_parser.add_argument(
    "file",
    nargs="?",
    help="Path to JSON file containing comments (default: read from stdin)",
)
comments_parser.add_argument(
    "-c",
    "--context",
    type=int,
    default=5,
    help="Lines of code context above/below the target line (default: 5)",
)
```

### Step 2: Create handler (`src/sase/main/comments_handler.py`)

New file with:

- `handle_comments_command(args)` — entry point
- `_load_comments_json(args)` — read from file or stdin, parse JSON, validate schema
- `_render_comments(comments, context_lines)` — iterate comments and render each one
- `_render_single_comment(console, comment, index, total, context_lines)` — render one comment mirroring TUI layout
- `_build_code_snippet(file_path, line_number, context_lines)` — read file, return Rich `Syntax` object

The rendering for each comment mirrors `MentorReviewModal._update_main_panel()`:

```
Comment 1/3
────────────────────────────────────────
  Focus: security_review    Severity: warning
  File: src/sase/foo/bar.py:42

  The function does not validate input before passing to subprocess.

  ┌─ src/sase/foo/bar.py ─────────────────
  │ 37 │   def run_command(self, cmd):
  │ 38 │     """Run a shell command."""
  │ ...│
  │ 42 │     subprocess.run(cmd, shell=True)  ← highlighted
  │ ...│
  │ 47 │     return result
  └────────────────────────────────────────
```

Reuse `lexer_for_path()` from `src/sase/ace/tui/modals/mentor_review_models.py` for syntax detection.

### Step 3: Wire up in entry.py (`src/sase/main/entry.py`)

Add handler between `commit` and `config`:

```python
# --- comments ---
if args.command == "comments":
    from .comments_handler import handle_comments_command
    handle_comments_command(args)
```

### Step 4: Validation logic

Validate the parsed JSON against the schema. On failure, print a clear error message showing:

- Which field is missing or has the wrong type
- The expected schema structure

Use `jsonschema.validate()` if available, otherwise do manual validation checking:

- Top-level must be an object with `comments` array
- Each comment must have all 5 required fields with correct types
- `severity` must be one of `error`, `warning`, `suggestion`

### Step 5: Handle edge cases

- **Missing files**: If a referenced file doesn't exist, print a warning but still render the comment without a snippet.
- **Line out of range**: Clamp to valid range (same as TUI).
- **Empty comments array**: Print "No comments." and exit 0.
- **Invalid JSON**: Print parse error with context and exit 1.
- **Stdin is a TTY with no file arg**: Print usage hint and exit 1.

## Files Changed

| File                                | Change                                             |
| ----------------------------------- | -------------------------------------------------- |
| `src/sase/main/parser.py`           | Add `comments` subcommand definition               |
| `src/sase/main/comments_handler.py` | **New** — handler with validation + Rich rendering |
| `src/sase/main/entry.py`            | Add `comments` command dispatch                    |

## Not In Scope

- Integration with actual mentor runs or file snapshots — this command works standalone with raw JSON.
- Acceptance/read state tracking — this is a preview tool, not a review workflow.
- TUI CSS styling — we use Rich Console directly for terminal output.
