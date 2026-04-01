---
create_time: 2026-04-01 13:12:47
status: done
---

# Prompt Input File Completion (Rich, Intuitive, Reliable)

## Objective

Add high-quality file path completion to the prompt input widget so typing path fragments (especially `~/`) provides
fast, discoverable, and visually rich completion in-place, without disrupting existing prompt, snippet, or vim/readline
editing behavior.

## Product Experience

1. Completion should feel immediate and shell-like.
2. Completion should be discoverable from first use.
3. Completion should preserve prompt writing flow (no modal required).
4. Completion UI should be readable and attractive in the existing ace visual language.
5. Existing snippet expansion and prompt submission behavior must remain reliable.

## UX Design

### Triggering

1. File completion activates when cursor is on a path-like token (examples: `~/`, `/tmp/`, `./src/`, `../`, `.sase/`,
   `docs/re` with slash context).
2. Pressing `Tab` on a path token requests completion.
3. Typing while completion is visible continuously refines suggestions.

### Behavior

1. If there is one match, `Tab` completes it immediately.
2. If there are multiple matches:
   1. Insert shared prefix extension (when available).
   2. Show a completion panel with the best matches.
3. Keyboard interaction while panel is open:
   1. `Ctrl+N` / `Down`: move selection forward.
   2. `Ctrl+P` / `Up`: move selection backward.
   3. `Ctrl+L`: accept highlighted suggestion.
   4. `Esc`: dismiss completion panel.
4. Directory completions insert trailing `/` so nested completion is natural.
5. Home paths stay user-friendly (`~`) in inserted text.

### Visual Design

1. Add an inline completion panel directly in `PromptInputBar` above the text area.
2. Style cues:
   1. Distinct border/tonal block within the prompt bar.
   2. Folder/file glyph labels (ASCII-safe fallbacks if needed).
   3. Highlighted row with strong contrast.
   4. Compact hint line for key usage.
3. Auto-grow prompt bar height to accommodate panel + input content.

## Technical Design

### New Internal Completion Model

In `PromptTextArea`, introduce lightweight state for active file completion:

1. Current candidates list (display label, insertion text, type).
2. Highlight index.
3. Active/inactive flag.
4. Utility to clear/reset state on cancellation or non-path context.

### Path Parsing and Resolution

Implement robust helpers in `PromptTextArea`:

1. Extract path token around cursor (bounded by whitespace/quotes).
2. Expand `~` for filesystem lookup but preserve `~` for insertion text.
3. Resolve base directory + partial basename.
4. Enumerate candidates via `os.scandir` with defensive exception handling.
5. Sort directories first, then files, case-insensitive.
6. Limit panel size to a reasonable cap (e.g. 8 entries).

### Completion Application

1. Replace only the active token range (not whole line).
2. Preserve cursor position at end of inserted completion.
3. Ensure completion actions are undo-friendly through existing keyboard replacement path.

### PromptInputBar Integration

1. Add a dedicated completion display widget in `PromptInputBar` composition.
2. Expose methods on `PromptInputBar` to:
   1. Show/update completion content.
   2. Hide completion content.
   3. Recompute bar height when completion visibility changes.
3. Keep `PromptTextArea` as key-event owner while delegating presentation to `PromptInputBar`.

### Key Handling Integration

Adjust `PromptTextArea._on_key` with careful precedence:

1. Preserve current submit/cancel/vim-mode behavior.
2. In INSERT mode, route file-completion navigation keys first when completion is active.
3. Handle `Tab` as:
   1. File completion when path context exists.
   2. Existing snippet/tabstop behavior otherwise.

## Reliability & Edge Cases

1. Gracefully handle unreadable/missing directories (no crash, no panel spam).
2. Ignore hidden/system files only if explicitly filtered (default: show all).
3. Handle path tokens with spaces only when quoted support is clear (initial pass: whitespace-delimited tokens).
4. Ensure completion panel closes when:
   1. Cursor leaves token context.
   2. Prompt submits/cancels.
   3. Mode switches to NORMAL.
5. Keep behavior deterministic when there are thousands of entries (capped display list).

## Testing Strategy

### Unit/Widget tests

Add a new test module for file completion behavior in `tests/ace/tui/widgets/`:

1. Detect token from `~/` and show candidates.
2. Single match completion inserts trailing `/` for directories.
3. Multi-match path applies shared prefix and shows panel.
4. Navigation (`Ctrl+N`, `Ctrl+P`, arrows) updates highlight.
5. Accept (`Ctrl+L`) inserts selected candidate.
6. `Esc` dismisses completion panel.
7. Non-path `Tab` still performs snippet expansion/tabstop behavior.
8. Completion state resets on submit/cancel.

### Regression checks

1. Re-run snippet expansion tests to ensure no priority regressions.
2. Validate prompt bar height behavior when panel toggles.

## Implementation Sequence

1. Add completion UI surface + styling in `PromptInputBar` and `styles.tcss`.
2. Implement file-completion engine/helpers in `PromptTextArea`.
3. Integrate key handling and completion panel updates.
4. Add focused widget tests for completion flow.
5. Run formatting/lint/tests and fix issues.
6. Run full required repo checks before handoff.

## Acceptance Criteria

1. Typing `~/` then `Tab` surfaces rich completions for home directory.
2. Completion can be navigated and accepted fully from keyboard.
3. Prompt editing, submission, snippets, and vim mode remain stable.
4. UI looks integrated and polished in the prompt bar.
5. Tests cover primary flows and regressions.
