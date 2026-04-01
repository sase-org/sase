---
create_time: 2026-04-01 13:24:53
status: done
---

# Plan: File Path Completion for Prompt Input Widget

## Problem

The prompt input widget (`PromptInputBar` + `PromptTextArea`) has no file path completion. When a user types `~/`, `./`,
or any path prefix, nothing happens — they must type the full path from memory. This is a poor experience for a tool
that frequently takes file paths as part of prompts.

## Product Vision

File completion should feel as natural as shell tab-completion but look better. When the user types a path separator, a
compact dropdown appears directly above the input bar showing matching entries. Directories are visually distinct,
drill-down is automatic, and the whole interaction is snappy enough to feel instant.

## Design

### Trigger Behavior

Completion activates automatically when the cursor sits immediately after a path-like prefix:

| Typed        | Triggers? | Directory listed                                  |
| ------------ | --------- | ------------------------------------------------- |
| `~/`         | Yes       | Home directory                                    |
| `./`         | Yes       | Workspace directory                               |
| `../`        | Yes       | Parent of workspace                               |
| `/etc/`      | Yes       | `/etc/`                                           |
| `~/Dow`      | Yes       | Home dir, filtered to entries starting with "Dow" |
| `some text ` | No        | —                                                 |

The trigger word is extracted by scanning backwards from the cursor to the first whitespace (or start of line). If the
result starts with `~/`, `./`, `../`, or `/`, completion is active.

Completion updates live as the user types or deletes characters. It dismisses on: Escape, cursor movement away from the
path token, or typing a space.

### Completion Engine (Pure Logic)

- **Input**: a partial path string (e.g. `~/Dow`)
- **Split** into directory prefix (`~/`) and filter prefix (`Dow`)
- **Resolve** the directory: expand `~`, resolve `.`/`..` relative to the workspace directory from `PromptContext`
- **List** directory contents using `os.scandir()` (fast, returns type info)
- **Filter** entries whose names start with the filter prefix (case-insensitive)
- **Skip** hidden entries (names starting with `.`) unless the filter prefix itself starts with `.`
- **Sort**: directories first, then files; alphabetical within each group
- **Limit** to 15 visible entries (with scroll indicator if more exist)

### Dropdown Widget (`FileCompletionDropdown`)

A lightweight Textual widget rendered as a floating panel above the prompt input bar.

**Visual design:**

```
┌─ ~/Downloads/ ──────────────────────────┐
│  📁 Documents/                          │
│  📁 Downloads/                          │
│ ▸📁 Desktop/                            │
│  📄 .bashrc                             │
│  📄 .zshrc                              │
└─────────────────────────────────────────┘
```

- Current selection highlighted with a distinct background (e.g. Textual `$accent` or `$primary`)
- Directories shown with `📁` icon and trailing `/`, styled in a distinct color (e.g. `$primary`)
- Files shown with `📄` icon, styled in `$text`
- The border title shows the resolved directory being listed
- Max height: 15 entries + 2 for border = 17 rows; if fewer entries, shrinks to fit

**Implementation**: Subclass `Static` and render via Rich `Text` objects (matching the pattern used by
`ChangeSpecDetail` and other display widgets). This avoids the weight of `OptionList` and gives full control over
rendering.

### Keyboard Interaction

While the dropdown is visible, the `PromptTextArea._on_key()` method intercepts navigation keys:

| Key           | Action                                                                |
| ------------- | --------------------------------------------------------------------- |
| `↓` / `Tab`   | Move selection down (wrap to top at end)                              |
| `↑` / `S-Tab` | Move selection up (wrap to bottom at start)                           |
| `Enter`       | Accept selected completion                                            |
| `Escape`      | Dismiss dropdown, keep typed text                                     |
| Any printable | Continue typing — dropdown updates in real time                       |
| `Backspace`   | Continue deleting — dropdown updates or dismisses if path prefix gone |

**On acceptance:**

- **Directory**: replace the partial with `dirname/` and immediately re-trigger completion for the new directory
  (drill-down)
- **File**: replace the partial with `filename` and dismiss the dropdown

The replacement operates on the "path token" — the text from the token start to the cursor — using the same
`_replace_via_keyboard()` mechanism that snippet expansion uses.

### Widget Composition

The `FileCompletionDropdown` is mounted as a child of the `PromptInputBar`, positioned above the text area using Textual
CSS (`dock: top` won't work here since the bar docks bottom — instead, use `offset` with a negative Y to render above
the bar). Actually, a cleaner approach: mount the dropdown on the **app/screen level** (like how modals work) rather
than inside the bar, and position it absolutely just above the bar. This avoids layout conflicts with the bar's
auto-height system.

Flow:

1. `PromptTextArea` detects a path trigger → posts a `FileCompletionRequested` message
2. `PromptInputBar` catches it → mounts `FileCompletionDropdown` on the screen, positioned above itself
3. `PromptTextArea._on_key()` checks if dropdown is active and intercepts nav keys
4. On acceptance, `PromptTextArea` replaces text and either re-triggers or dismisses
5. On dismissal, the dropdown widget is unmounted

### Integration with Existing Features

- **Vim normal mode**: entering normal mode dismisses the dropdown
- **Snippet expansion**: Tab is overloaded — when dropdown is visible, Tab navigates the dropdown; when not visible, Tab
  does snippet expand/tabstop advance (existing behavior)
- **`#@` trigger**: unaffected — the path trigger only activates on path-like prefixes
- **Auto-wrap (prettier)**: wrapping should not interfere since path tokens are typically short
- **Feedback mode**: file completion works in feedback mode too (file paths are useful in plan feedback)

## Files to Create

1. `src/sase/ace/tui/widgets/file_completion.py` — `FileCompletionDropdown` widget + `list_completions()` engine

## Files to Modify

2. `src/sase/ace/tui/widgets/prompt_text_area.py` — trigger detection in `_on_key()`, nav key interception
3. `src/sase/ace/tui/widgets/prompt_input_bar.py` — mount/unmount dropdown, pass workspace context
4. `src/sase/ace/tui/styles.tcss` — styles for `FileCompletionDropdown`

## Phases

### Phase 1: Completion Engine + Widget

Build `file_completion.py` with:

- `list_completions(partial_path, workspace_dir) -> list[CompletionEntry]`
- `FileCompletionDropdown` widget with rendering and selection state

### Phase 2: Integration

Wire up trigger detection in `PromptTextArea`, mounting in `PromptInputBar`, key interception for navigation.

### Phase 3: Polish

Directory drill-down, edge case handling (permissions, symlinks, empty dirs), visual refinement.
