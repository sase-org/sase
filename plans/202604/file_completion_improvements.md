---
create_time: 2026-04-01 14:00:00
status: active
---

# Improve File Completion: Extract Module, Rich UI, Dotfile Filtering, Drill-down

## Problem

PR #71 delivered working file path completion with good tests and a solid Tab-triggered interaction model. However, all
completion logic is monolithically embedded in `prompt_text_area.py` (+264 lines), the panel uses plain text rendering,
dotfiles are unconditionally shown, directory acceptance doesn't drill down, and symlinks aren't followed. PR #72 had
better architecture on all these axes but shipped no tests. We want the best of both.

## Product Vision

After this work, file completion should feel as polished and discoverable as shell completion but look better. The panel
should use rich styling with directory/file icons, dotfiles should be hidden by default (matching shell conventions),
accepting a directory should immediately drill down into it, and the completion engine should be cleanly separated from
the widget code for testability and reuse.

## Design

### 1. Extract `file_completion.py` Module

Create `src/sase/ace/tui/widgets/file_completion.py` containing the pure-logic completion engine:

- `CompletionCandidate` dataclass — public version of the current `_FileCompletionCandidate` with the same fields:
  `display`, `insertion`, `is_dir`, `name`.
- `is_path_like_token(token: str) -> bool` — lifted from `PromptTextArea._is_path_like_token`.
- `extract_token_around_cursor(line: str, col: int) -> tuple[int, int, str] | None` — lifted from
  `PromptTextArea._extract_token_around_cursor`, taking `line` and `col` as arguments instead of reading from `self`.
- `build_completion_candidates(token: str) -> tuple[list[CompletionCandidate], str]` — lifted from
  `PromptTextArea._build_file_completion_candidates`, incorporating the dotfile filtering and symlink-following changes.

`prompt_text_area.py` imports from the new module and delegates. The state-management and UI-interaction methods
(`_clear_file_completion`, `_move_file_completion`, `_accept_file_completion`, `_try_file_completion_tab`,
`_refresh_file_completion_from_cursor`) stay in `PromptTextArea` since they depend on widget state.

### 2. Rich Panel Rendering

Replace the plain-text rendering in `PromptInputBar.show_file_completions` with Rich `Text` objects:

| Element          | Style                                  |
| ---------------- | -------------------------------------- |
| Selected marker  | `▸ ` (bold) vs `  `                    |
| Directory icon   | `📁 ` + cyan name                      |
| File icon        | `📄 ` + default text color             |
| Selected row     | Bold text                              |
| Border title     | Current directory path being completed |
| Scroll indicator | `  ↓ N more...` (dim) when capped      |
| Key hint line    | Removed (keys are in placeholder text) |

Cap the visible entries at `MAX_VISIBLE = 10`. When there are more candidates, show the first 10 centered around the
selection with a scroll indicator. The `show_file_completions` signature changes to accept a `scroll_offset` parameter
so `PromptTextArea` can manage the viewport.

### 3. Dotfile Filtering

In `build_completion_candidates`, skip entries whose name starts with `.` unless the partial filter prefix itself starts
with `.`. This matches standard shell behavior: `~/` lists visible files, `~/.` lists dotfiles.

### 4. Directory Drill-down

When `_accept_file_completion` inserts a directory (trailing `/`), instead of calling `_clear_file_completion`, call
`_try_file_completion_tab` on the new token. If the new directory has completions, the panel stays open showing its
contents. If not (empty dir or error), the panel clears normally.

### 5. Follow Symlinks

Change `entry.is_dir(follow_symlinks=False)` to `entry.is_dir(follow_symlinks=True)` so symlinked directories appear as
directories in the completion panel.

## Files to Create

1. `src/sase/ace/tui/widgets/file_completion.py` — completion engine module

## Files to Modify

1. `src/sase/ace/tui/widgets/prompt_text_area.py` — import from new module, remove extracted code, add drill-down
2. `src/sase/ace/tui/widgets/prompt_input_bar.py` — Rich rendering with scroll support
3. `tests/ace/tui/widgets/test_prompt_file_completion.py` — update imports, add tests for dotfile filtering, drill-down,
   symlink following

## Phases

### Phase 1: Extract Module

Create `file_completion.py` with the four public symbols. Update `prompt_text_area.py` to import and delegate. Run
existing tests to confirm no regressions.

### Phase 2: Rich Rendering + Scroll

Replace `show_file_completions` rendering with Rich `Text` objects. Add scroll offset tracking. Update CSS if needed.

### Phase 3: Behavioral Improvements

Add dotfile filtering to `build_completion_candidates`. Change `follow_symlinks` to `True`. Add directory drill-down to
`_accept_file_completion`.

### Phase 4: Tests

Add new test cases: dotfile filtering, directory drill-down, symlink following. Run `just check`.
