---
create_time: 2026-04-23 14:18:07
status: done
prompt: sdd/prompts/202604/ctrlt_file_history_completion.md
---

# Plan: Ctrl+T File-History Completion at Empty Cursor Context

## Problem / Goal

The `<ctrl+t>` keymap in the prompt input widget currently triggers completion in two modes based on the token around
the cursor:

- **xprompt** completion when the token starts with `#`
- **file path** completion when the token looks path-like (`@...`, `~/`, `/`, `./`, `../`, `.sase/`, or contains `/`)

When there is **no token at the cursor** (empty line, or cursor after whitespace), `<ctrl+t>` does nothing useful.

We want a third mode: **file-history completion**. When the user hits `<ctrl+t>` with nothing but whitespace before the
cursor, show a list of full file paths the user has previously referenced in prompts, sorted by recency (most recent
first, no duplicates). Selecting a candidate inserts the full path at the cursor.

This requires persisting a rolling history of file-path references extracted from every submitted prompt.

## Scope

### In scope

1. **New disk-backed history store** for file-path references (`~/.sase/file_reference_history.json`).
2. **Extraction logic** that pulls file-path tokens from a prompt string.
   - `@`-prefixed tokens (e.g. `@src/foo.py`, `@~/notes.md`, `@./x`)
   - Absolute path tokens (start with `/` or `~/`)
   - Only these two categories. Bare relative paths like `src/foo.py` without an `@` prefix are **not** recorded.
3. **Hook into prompt submission** so file references are persisted whenever a prompt is committed (both normal
   submission and the multi-prompt segment path; cancelled prompts handled explicitly — see open questions).
4. **Completion behavior change** for `<ctrl+t>`:
   - When cursor has no path- or xprompt-like token and nothing non-whitespace precedes it on the current line, open a
     new `"file_history"` completion kind showing the recency-ordered path history.
   - Navigation, acceptance, and dismissal use the existing completion UI (no new widget work).
5. **Tests** covering extraction, dedup/ordering, and the new cursor-context branch.

### Out of scope

- Fuzzy or substring matching on the history list. Initial version displays the raw recency-ordered list; any filtering
  is deferred.
- Changing the semantics of `<ctrl+t>` when a path-like or xprompt token is already at the cursor — existing behavior is
  untouched.
- Migrating or pre-populating the history from existing `prompt_history.json`. The history starts empty and grows as new
  prompts are submitted.
- Capping the history length. We'll start unbounded and revisit only if the file grows unwieldy.
- Distinguishing the two reference kinds (`@`-prefix vs absolute) in storage — both are normalized to the bare absolute
  path.

## High-Level Design

### 1. History storage module

**New file:** `src/sase/history/file_references.py`

Mirrors the shape of `src/sase/history/vcs_xprompt_mru.py` (the simplest existing MRU-style store). Data layout:

```json
{
  "paths": ["/home/bryan/projects/sase/src/sase/foo.py",
            "~/notes/ideas.md",
            ...]
}
```

Ordering: most-recent-first. Dedup by exact string match _after_ extraction normalization (see below).

Public API:

- `record_file_references(refs: Iterable[str]) -> None`
  - Loads, prepends new refs (preserving input order for entries added in the same call — so the _last_ one in `refs`
    ends up at index 0), removes later duplicates, saves.
- `load_file_references() -> list[str]`
  - Returns list in recency order (index 0 = most recent).

Storage path: `~/.sase/file_reference_history.json`. Use the same atomic-write and JSON-load patterns as the sibling
history modules (tmp file + rename, graceful handling of missing / corrupt files).

### 2. Extraction helper

**New function:** `extract_recordable_file_refs(text: str) -> list[str]`

Lives alongside the store (`history/file_references.py`). Responsibilities:

- Find every `@`-prefixed path token and every absolute path token (leading `/` or `~/`) in `text`.
- Reuse the existing `_FILE_PATH_RE` pattern from `src/sase/ace/tui/widgets/prompt_panel/_file_path_hints.py` as the
  starting point, but restrict the accepted set to the two kinds above (strip `@`, require result starts with `/` or
  `~/`). Bare relative paths that the existing regex also matches are filtered out.
- Preserve prompt order (left-to-right), so callers can feed the list straight into `record_file_references`.
- Return each path as the user typed it (with `~` still unexpanded) — no `os.path.expanduser` — so history matches how
  the user writes paths.

**Shared-regex decision:** lift `_FILE_PATH_RE` into a small shared module if both call sites want the same pattern.
Otherwise, duplicate the narrowed pattern here — pick whichever keeps the existing hints code unchanged. (Leaning toward
a new `sase.ace.tui.widgets.file_path_patterns` module with the regex, imported by both.)

### 3. Hook into prompt submission

**Target call site:** `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py` around line 175, immediately after
`add_or_update_prompt(prompt, ...)`.

Call:

```python
from sase.history.file_references import (
    extract_recordable_file_refs,
    record_file_references,
)

refs = extract_recordable_file_refs(prompt)
if refs:
    record_file_references(refs)
```

For multi-prompt segments, the current code saves each segment individually via `add_or_update_prompt` — we extract
per-segment as well, so every segment contributes its refs in order.

**Cancelled prompts:** `_save_bar_text_as_cancelled` (in `_prompt_bar.py`) already persists cancelled drafts. Open
question (see below) whether cancelled text should also update file-ref history. Default answer: **yes**, since the user
still referenced those files mentally. Cheap to include.

### 4. Completion-kind extension

**Files touched:**

- `src/sase/ace/tui/widgets/_file_completion.py`
- `src/sase/ace/tui/widgets/file_completion.py` (or a new sibling)
- `src/sase/ace/tui/widgets/prompt_input_bar.py` (only if the completion panel needs to distinguish the new kind
  visually — likely no change)

**New completion kind:** `"file_history"`.

**Trigger detection** (in `_try_file_completion_tab`):

The existing method starts by calling `_extract_token_around_cursor()`. Extend the "no token" early-exit branch:

```python
if token_info is None:
    if self._cursor_at_empty_prefix():
        return self._try_file_history_completion()
    self._clear_file_completion()
    return False
```

`_cursor_at_empty_prefix()` returns True when the substring of the current line from column 0 up to the cursor column
contains only whitespace (covers "beginning of line" and "cursor after trailing whitespace on a non-empty line").
End-of-line with text before it is **not** an empty prefix — the spec says "no text before the cursor", and that
phrasing rules out "after-a-word-at-EOL". Confirm with user.

**Candidate builder:** new function
`build_file_history_completion_candidates() -> tuple[list[CompletionCandidate], str]`

Returns one `CompletionCandidate` per history entry:

- `display = path` (the stored string, so `~/foo` stays as `~/foo`)
- `insertion = path`
- `is_dir = False`
- `name = path`

No shared-extension completion, no directory drill-down. Empty history → return `([], "")`, caller clears state
(identical to the "no candidates" branch already in `_try_file_completion_tab`).

**`_try_file_history_completion`** mirrors the last section of `_try_file_completion_tab`:

- Set `_completion_kind = "file_history"`
- Load candidates; if none, clear and return True (swallow the keypress so nothing else reacts — matches current
  behavior on empty candidate lists).
- Activate the panel with no token/prefix (since there's nothing to replace).

**Accept path:** `_accept_file_completion` needs to handle the new kind. Because there's no existing token to replace,
it should _insert_ the candidate at the cursor rather than calling `_replace_token_text`. Add a branch: when
`_completion_kind == "file_history"`, `self.insert(insertion)` and clear. (Sanity-check the exact Textual insertion
method used elsewhere in the codebase.)

**Refresh / typing behavior:** once the user starts typing, the token at cursor is no longer empty, so
`_refresh_file_completion_from_cursor` should bail out of file-history mode. Simplest rule: in `_refresh_...`, if
`_completion_kind == "file_history"` and the current token is non-empty, clear completion. User can retrigger with
`<ctrl+t>` if they want file-or-xprompt completion on what they just typed.

Navigation (`ctrl+n`/`ctrl+p`, up/down) and Enter acceptance reuse the existing mixin methods as-is.

### 5. Visual treatment

The completion panel already receives a `completion_kind` argument
(`prompt_input_bar.show_file_completions(..., completion_kind=...)`). Check whether the existing renderer needs a new
header/label for `"file_history"`. If the panel displays a kind-specific title, add one (e.g. "recent files"). If not,
no change needed — the entries are full paths and self-describing.

## Files Touched (summary)

| Kind         | Path                                                                 | Reason                                                                                                           |
| ------------ | -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| New          | `src/sase/history/file_references.py`                                | Store + extractor                                                                                                |
| New (maybe)  | `src/sase/ace/tui/widgets/file_path_patterns.py`                     | Shared regex                                                                                                     |
| Edit         | `src/sase/ace/tui/widgets/_file_completion.py`                       | New kind branch in `_try_file_completion_tab`, `_accept_file_completion`, `_refresh_file_completion_from_cursor` |
| Edit         | `src/sase/ace/tui/widgets/file_completion.py`                        | Add `build_file_history_completion_candidates` (or put it alongside the store)                                   |
| Edit         | `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`           | Record refs after `add_or_update_prompt`                                                                         |
| Edit (maybe) | `src/sase/ace/tui/actions/agent_workflow/_prompt_bar.py`             | Record refs on cancel                                                                                            |
| Edit (maybe) | `src/sase/ace/tui/widgets/prompt_panel/_file_path_hints.py`          | Import shared regex instead of local copy                                                                        |
| Edit (maybe) | `src/sase/ace/tui/widgets/prompt_input_bar.py`                       | Panel header for `"file_history"`                                                                                |
| New tests    | `tests/history/test_file_references.py`                              | Store + extraction                                                                                               |
| New tests    | `tests/ace/tui/widgets/test_file_completion.py` (or extend existing) | Empty-prefix branch                                                                                              |

## Testing Strategy

- **Unit** (`extract_recordable_file_refs`):
  - `@src/foo.py` → `["src/foo.py"]`? No — we only keep `@`-prefixed and absolute. Decide: does a bare-relative
    `@`-prefixed path (e.g. `@src/foo.py`) count as a file reference? Spec says yes ("file references in prompts that
    had an `@` prefix"). Keep it, strip `@`.
  - `/etc/hosts` and `~/notes.md` included; bare `src/foo.py` excluded.
  - Mixed prompt: order preserved.
  - No false positives on `email@domain.com`, `key@abc`, etc. — the existing `_FILE_PATH_RE` negative lookbehind
    `(?<![/\w@.])` already guards this.
- **Unit** (`record_file_references` / `load_file_references`):
  - Dedup keeps most-recent instance.
  - Ordering preserves recency across multiple calls.
  - Corrupt JSON → empty list, no crash.
- **Integration** (completion mixin):
  - Empty prompt + `<ctrl+t>` with non-empty history → panel shows history.
  - Empty prompt + `<ctrl+t>` with empty history → nothing happens.
  - Non-empty path token still routes to existing file completion.
  - Non-empty `#` token still routes to xprompt.
  - Accepting a history candidate inserts the path at the cursor.

## Open Questions

1. **"No text before the cursor" — exact definition.** Proposal: the portion of the _current line_ from column 0 up to
   the cursor column is whitespace only. That covers "beginning of line" (trivially) and "end of a blank line", but a
   cursor at the end of `foo bar ` (trailing space, non-empty line) _would_ trigger file-history mode under this rule.
   Is that desired, or should we require the entire buffer to have no text before the cursor? The user's example —
   "beginning or end of a line" — is ambiguous here.
2. **Include cancelled prompts in history?** Recording them means even a typed-then-cancelled file reference sticks
   around. Omitting them keeps the history tighter. Default: include.
3. **History cap?** Start unbounded; add a cap (e.g. 500) only if the file grows large. Worth deciding up front?
4. **Pre-populate from `prompt_history.json`?** One-time migration would give the feature immediate value. Default: no,
   keep the change minimal.
5. **Bare-relative `@` paths** (e.g. `@src/foo.py`): store as `src/foo.py` or as `@src/foo.py`? Proposal: strip the `@`
   so the completion inserts the literal path and the user can decide to re-add `@` if needed. Alternative: keep the `@`
   and insert as-is.

## Risks / Non-Risks

- **Low risk:** The change is additive. No existing code path changes behavior when a token is present at the cursor.
- **Privacy:** The new file stores absolute paths of files the user has referenced. Consistent with existing sase state
  under `~/.sase/` — no new category of data.
- **Concurrency:** Multiple sase TUIs writing simultaneously could race on the file. The existing history modules don't
  lock; we'll follow the same pattern (last-writer-wins is acceptable). Call out if the user wants stronger guarantees.
