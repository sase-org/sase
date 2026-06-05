---
create_time: 2026-06-05 13:27:47
status: done
prompt: sdd/prompts/202606/prompt_ctrl_r_recursive_finder.md
---
# Plan: `<ctrl+r>` Recursive Fuzzy File Finder for the Prompt Input

## Goal

Add a new `<ctrl+r>` keymap to the prompt input widget (`sase ace` TUI) that opens a beautiful, large file-finder panel
for **recursive, as-you-type-fuzzy-filtered** file/directory path completion. It complements the existing `<ctrl+t>`
(single-level, inline, prefix) completion rather than replacing it.

### Behavior (from the request)

- `<ctrl+r>` searches **recursively** under the directory that was **to the left of the cursor** when pressed.
- The finder is **filtered as the user types** (the typed text is a transient fuzzy query that does **not** modify the
  prompt text).
- `<ctrl+r>` also works **while the `<ctrl+t>` completion window is open** — in that case the recursive root is derived
  from the currently-selected `<ctrl+t>` entry (treated as if that entry's path were the text to the left of the
  cursor).
- `<ctrl+n>` / `<ctrl+p>` (and `↓` / `↑`) navigate the result list.
- `<enter>` inserts the selected directory/file path back into the prompt **where the cursor was**.
- Decisions already locked by the user:
  - **Q1 — file scope:** Git-aware. Inside a git repo, list tracked + untracked-but-not-ignored files (respects
    `.gitignore`). Outside git, fall back to a filesystem walk that skips dotdirs and heavy dirs (`node_modules`,
    `__pycache__`, `target`, `.venv`).
  - **Q2 — match style:** Fuzzy subsequence (fzf/Telescope-style), ranked by match quality (consecutive runs,
    segment/word-boundary hits, filename hits, position, length tiebreak).

## Context: how the existing `<ctrl+t>` system works

(Grounding for the design — all in `src/sase/ace/tui/`.)

- **Key dispatch:** `widgets/prompt_text_area.py` → `PromptTextArea._on_key()`. `<ctrl+t>` is handled at the bottom of
  `_on_key` (calls `_try_file_completion_tab()`); navigation (`ctrl+n/ctrl+p/up/down`), accept (`ctrl+l`/`enter`), and
  dismiss (`esc`) are gated on `self._file_completion_active`.
- **Completion state** lives on the widget (`_file_completion_active`, `_file_completion_candidates`,
  `_file_completion_index`, `_completion_kind`).
- **Completion logic:** `widgets/_file_completion.py` (`FileCompletionMixin`) orchestrates; `widgets/file_completion.py`
  is the pure engine (`CompletionCandidate` dataclass, `extract_token_around_cursor`, `build_completion_candidates` — a
  single-level `os.scandir` prefix match — and `MAX_VISIBLE = 10`).
- **Panel rendering:** one shared `Static#prompt-completion` inside `widgets/prompt_input_bar.py`
  (`show_file_completions` / `hide_file_completions`), styled in `styles.tcss` (`#prompt-completion`, `max-height: 10`).
  It reuses 📁/📄/▸ glyphs and theme colors.
- **No fuzzy matcher exists today** — current matching is case-insensitive prefix only.
- **Precedent:** the entire `<ctrl+t>` completion stack is pure Python presentation/glue (no Rust core involvement),
  even though it does filesystem I/O.

## Design

### Interaction model: a dedicated modal finder (Telescope/fzf-style)

`<ctrl+t>` edits the prompt token _inline_; that model can't cleanly host a separate "type to filter" query without
polluting the prompt. So `<ctrl+r>` opens a **`ModalScreen` overlay** — the established pattern in this codebase
(history, project-select, query-edit modals are all modals and are already covered by the visual snapshot suite). The
modal:

1. Captures the recursive **root** and the **path-token range** around the cursor before opening.
2. Owns a transient **fuzzy query buffer** (typed text never touches the prompt).
3. Renders a large results panel + query line + counter + key hints.
4. On `<enter>`, dismisses with the selected candidate; the caller replaces the captured token range in the prompt with
   the chosen full path (re-focusing the text area). On `<esc>`, dismisses with no change.

Because a modal leaves the underlying prompt `TextArea` mounted, the captured `(row, col)` and widget reference stay
valid for insertion on return.

### Determining the recursive root + the token range to replace

A small helper computes `(root_display, root_abs, row, start, end)`:

- **Case A — `<ctrl+t>` panel open on a path/file kind:** take the selected candidate's `insertion` path and apply
  "directory-to-the-left" extraction to it: a directory entry (`src/foo/`) → root is that dir; a file entry
  (`src/foo.py`) → root is its parent (`src/`). The token range to replace is the current path token under the cursor
  (or the cursor point if none).
- **Case B — otherwise:** read the path token around the cursor (reusing the existing token-extraction logic). If it has
  a `/`, root = everything up to and including the last `/` (e.g. `src/foo` → `src/`); if no `/`, root = current working
  directory (`.`). The full token is the range to replace.
- **Query pre-seed (recommended):** when the token has a partial filename portion (`src/foo` → `foo`), pre-seed the
  fuzzy query with it so the user continues what they were typing. Flagged as a deliberate UX choice (easy to disable to
  "always start empty").

On accept, the inserted text = `root_display_prefix + relative_path_under_root` so it reads exactly as a user would type
it (e.g. root `src/` + chosen `sase/ace/foo.py` → `src/sase/ace/foo.py`). Directories insert with a trailing `/`. The
token range is replaced via the existing `_replace_token_text` / `_replace_via_keyboard` path so undo history stays
consistent.

### Candidate enumeration (Q1: git-aware)

New pure helper `enumerate_recursive_candidates(root_abs, root_display)`:

- **Git-aware:** `git ls-files --cached --others --exclude-standard -z` run with `cwd=root` → tracked +
  untracked-not-ignored files relative to root (honors `.gitignore`). Detect non-git (command failure / not a work tree)
  and fall back.
- **Fallback walk:** `os.walk` skipping dotdirs and a heavy-dir denylist (`node_modules`, `__pycache__`, `target`,
  `.venv`, …).
- **Directories are selectable too:** derive the set of intermediate directories from the file paths (every unique
  parent prefix) and emit them as `is_dir=True` candidates. In git mode this automatically respects ignores (a dir
  appears only if it contains a non-ignored file).
- **Safety cap:** bound enumeration (e.g. ~20k entries); if exceeded, surface a visible "showing first N — narrow the
  root" note (no silent truncation).
- Reuse the existing `CompletionCandidate` dataclass (`display`, `insertion`, `is_dir`, `name`).

### Fuzzy matching + ranking (Q2: subsequence)

New pure module function `fuzzy_match(query, text) -> (score, matched_positions) | None`:

- Case-insensitive in-order subsequence; `None` when not all query chars match.
- Score bonuses: consecutive matched runs; matches at segment/word boundaries (`/ _ - .` and camelCase); matches within
  the **basename** weighted higher than directory hits; earlier first match; shorter path as tiebreak.
- Returns matched character indices for **highlighting**.
- Empty query → all candidates shown in a sensible default order (e.g. shortest/most-shallow first).
- A `rank_candidates(query, candidates)` wrapper sorts by score; ties broken by path length then lexicographic. A thin
  `FinderModel` (candidates + query + filtered view + selection index) holds finder state so the modal stays a thin view
  and the logic is unit-testable.

Performance: enumerate once on open; re-rank the in-memory list per keystroke (fast for typical repos within the cap).
Note an optional debounce/cap path for very large roots.

### The "large, beautiful" panel — visual design

A centered modal (~80% width, ~70% height, sensibly clamped), consistent with existing theme variables (`$accent`,
`$secondary`, `$panel`, `$surface`, `$text`, dim) and the app's 📁/📄/▸ glyph vocabulary:

```
┌─ 🔍 Recursive Finder ───────────────────── src/   (42/318) ─┐
│ ▸ 📄 src/sase/ace/tui/widgets/file_completion.py            │
│   📄 src/sase/ace/tui/widgets/_file_completion.py           │
│   📁 src/sase/ace/tui/widgets/file_panel/                   │
│   📄 src/sase/ace/tui/widgets/prompt_input_bar.py           │
│   …                                                          │
│   ↓ 276 more…                                                │
├─────────────────────────────────────────────────────────────┤
│ 🔎 fil comp▌                                                 │
└─ [^N/^P ↑↓] move    [Enter] insert    [Esc] cancel ─────────┘
```

- **Header / border title:** finder label + the active **root** and a live **`matched/total`** counter.
- **Results rows:** selection marker `▸` + icon (📁 dir / 📄 file) + path with the directory portion dimmed and the
  basename emphasized; **fuzzy-matched characters highlighted** (bold accent); the selected row gets a highlighted
  background.
- **Windowing:** show a large fixed window of rows with a centered scroll offset (generalizing the existing panel's
  offset math) plus `↑ N more…` / `↓ N more…` indicators.
- **Query line:** `🔎 <query>` with a block cursor.
- **Footer (border subtitle):** key hints.
- **Empty state:** a clear "No matches" / "No files found under `<root>`" message.

### Key handling inside the modal

The modal's `on_key` owns its input (no embedded `Input` widget, for full control + consistency with the app's custom
key handling): printable chars append to the query; `backspace` deletes; `ctrl+u` clears; `ctrl+n`/`down` and
`ctrl+p`/`up` move selection (wrapping); `enter` accepts; `esc` cancels. Each query change re-ranks and
resets/repositions the selection.

## Files to create / change (high-level)

**New**

- `src/sase/ace/tui/widgets/recursive_file_finder.py` — pure logic: `fuzzy_match`, `rank_candidates`,
  `enumerate_recursive_candidates`, `FinderModel`, ignore-dir/cap constants.
- `src/sase/ace/tui/modals/recursive_finder_modal.py` — `RecursiveFileFinderModal(ModalScreen)`: compose, render,
  `on_key`, dismiss-with-result.

**Modify**

- `widgets/prompt_text_area.py` — add the `<ctrl+r>` branch in `_on_key`; add `_open_recursive_file_finder()` that
  computes root+token-range, pushes the modal, and inserts on return.
- `widgets/_file_completion.py` — add the root/token-range helper, including the "derive root from the active `<ctrl+t>`
  selection" case.
- `widgets/prompt_input_bar.py` — extend the placeholder hint to advertise `[^R] find`.
- `styles.tcss` — CSS for the new modal (`#finder-dialog`, results region, query line, sizing, colors).
- `src/sase/default_config.yml` — **only if** prompt-level keys are config-driven. They are not today (`<ctrl+t>` is
  hardcoded), so the default is to hardcode `<ctrl+r>` to match precedent; will confirm during implementation and update
  config if a prompt-keymap section is added.

## Testing

- **Pure logic** (`tests/ace/tui/widgets/test_recursive_file_finder.py`): fuzzy subsequence correctness, ranking order
  (consecutive/boundary/basename bonuses), matched-position output, empty query; `enumerate_recursive_candidates` with
  `tmp_path` + `git init` (gitignore respected, dirs derived, heavy-dir exclusion in non-git mode), and the
  cap/truncation note.
- **Modal/functional** (`tests/ace/tui/widgets/test_recursive_finder_modal.py`): via the existing pilot harness — open,
  type to filter, `ctrl+n/p` navigate, `enter` inserts at the captured cursor, `esc` cancels with no change, and the
  `<ctrl+r>`-while-`<ctrl+t>`-open path uses the selected entry's directory as root.
- **Visual PNG snapshot** (add a scenario to `tests/ace/tui/visual/test_ace_png_snapshots.py`, new golden under
  `tests/ace/tui/visual/snapshots/png/`): the populated finder (root, matches, highlighted query, selection) — the
  reviewable "looks beautiful" artifact. Accept the golden with `just test-visual --sase-update-visual-snapshots`.
- Run `just check` before completion (per repo policy).

## Design decisions / risks to confirm

1. **Rust core boundary.** `memory/short/rust_core_backend_boundary.md` says cross-frontend domain behavior belongs in
   `../sase-core`. Recursive enumeration + fuzzy ranking _could_ be argued as reusable backend logic.
   **Recommendation:** implement in Python, mirroring the existing `<ctrl+t>` engine (which lives entirely in Python
   presentation/glue and also does filesystem I/O). If you later want web/editor parity, the pure `fuzzy_match` +
   enumeration functions are self-contained and can move to `sase_core` behind a binding with minimal churn. **Flagging
   for your call before implementation.**
2. **Modal vs. inline panel.** Going modal (vs. expanding the inline `#prompt-completion` panel) to keep the fuzzy query
   out of the prompt and to get a genuinely large, focused finder. This is the biggest UX fork — confirm you're happy
   with a full overlay.
3. **Query pre-seed** from the partial filename (recommended on) vs. always-empty query.
4. **Directories selectable** and inserted with a trailing `/` (enter = insert + close; no directory drill-down inside
   the finder for v1 — possible later enhancement).
5. **Discoverability:** prompt-level keys (`<ctrl+t>`, `<ctrl+j>`, …) are _not_ in the `?` help modal today — only the
   placeholder hint and each panel's own footer document them. Plan follows that precedent (placeholder hint + the
   finder's footer); will add to help if you want it there.
