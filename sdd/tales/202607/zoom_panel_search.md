---
create_time: 2026-07-07 18:05:56
status: done
prompt: sdd/prompts/202607/zoom_panel_search.md
---
# Plan: Vim-style `/` and `?` Search in the Agents-tab Zoom Panel

## Product Context

The `sase ace` TUI has a near-fullscreen **zoom modal** (`ZoomPanelModal`) that blows up one Agents-tab detail panel at
a time — **METADATA** (agent prompt/details), **FILE** (diffs / file output / static files), or **TOOLS** (the tool-call
timeline). It is opened with `z` on the Agents tab and already supports Vim-flavored scrolling (`j/k/g/G/^D/^U`), panel
cycling (`]`/`[`), file paging (`^N`/`^P`), copy (`y`), edit (`E`), and refresh (`r`).

What it is missing is the single most-requested navigation primitive for a large scrollable buffer: **search**. When you
zoom a 2,000-line diff or a long tool timeline, there is no way to jump to a term — you scroll by hand. This plan adds a
genuine **Vim-style incremental search** to the zoom modal:

- `/` opens a **forward** search command line; `?` opens a **backward** search command line.
- You type a query and see the view **jump to and highlight** the first match live (incremental search, "incsearch").
- `Enter` commits; **all matches stay highlighted** (like Vim's `hlsearch`) with the **current match** shown distinctly.
- `n` / `N` jump to the next / previous match (with wrap-around, and Vim's "hit BOTTOM, continuing at TOP" feedback).
- `Esc` / `Ctrl+C` exits search and restores the normal panel view.

The design goal is that this feels _identical_ to the search users already know from the `sase ace` prompt editor (same
keys, same smartcase semantics, same `/query [3/12]` command-line look), so it is intuitive on first use, reliable
because it reuses the prompt's tested matching core, and beautiful because it mirrors an aesthetic that is already in
the product.

## What "the zoom panel's current contents" means (and why it drives the design)

The three zoomed panels are all Textual `Static` widgets that render **arbitrary Rich renderables** into a
`VerticalScroll`:

- FILE renders a Rich `Syntax` object (monokai theme, a line-number gutter, word-wrap) — and, crucially, is often
  **trimmed** to a page of lines by default (`_base_trim_size`), with `=`/`-` controlling how much is shown.
- METADATA / TOOLS render `Text` / `Group` / table renderables.

Two consequences shape the whole design:

1. **There is no cursor and no per-substring highlight API.** Unlike the prompt's `TextArea` (which has native
   selection/highlight spans), a `Static` gives us no reliable way to restyle a substring _inside_ an arbitrary
   renderable such as `Syntax`. Fighting each panel's bespoke rendering to inject highlights would be fragile and
   panel-specific.
2. **The rendered view is not the whole content.** The FILE panel may be trimmed, so "search what's on screen" would
   silently miss matches below the trim — a reliability trap.

Both point to the same clean solution: **search operates on the panel's full extracted text, rendered into a
search-owned overlay that we fully control.** The modal already exposes exactly the text we need via `zoom_text()`
(`zoom_panel_content.py`): FILE → `get_current_content()` (the _full_, untrimmed file/diff string), TOOLS →
`get_tools_text()`, METADATA/fallback → `renderable_to_text(active_panel.content)`. Because we render the overlay
ourselves from that text, highlighting is trivial and _uniform across all three targets_, and search always covers the
entire content regardless of the underlying panel's trim state.

This is the one genuinely new piece of machinery. Everything else is deliberately borrowed from the existing prompt
search so behavior and look stay consistent.

## Reuse: what already exists and will be shared, not reinvented

The `sase ace` prompt editor already implements Vim `/` `?` search. We reuse its core and mirror its UI:

- **Matching + selection core — reuse verbatim.** `src/sase/ace/tui/widgets/_vim_search.py` provides
  `find_search_matches(text, query, smartcase=True)` (literal, smartcase, overlapping spans) and
  `select_search_match(matches, origin, direction, include_origin=...)` (nearest match in a direction, with wrap-around
  reporting). These are pure, already unit-tested, and are exactly the semantics we want. The zoom search imports and
  calls them directly — **no new matching logic.** Smartcase (case-insensitive unless the query contains an uppercase
  letter) and literal (non-regex) matching come for free and match user expectations elsewhere in the app.
- **Interactive state machine — mirror.** `src/sase/ace/tui/widgets/_prompt_search.py` (`PromptSearchMixin`) is the
  template for the incremental command-line state machine: `_search_active` / `_search_query` / `_search_direction` /
  `_search_origin_*` / `_last_search`, a char-by-char key handler (`_handle_prompt_search_key`), a live preview
  (`_update_prompt_search_preview`), `_confirm` / `_cancel`, and `n`/`N` repeat (`_repeat_prompt_search`) with wrap
  feedback strings. The zoom search is a structurally parallel mixin whose only differences are "move a scroll + repaint
  an overlay" instead of "move a text cursor + set TextArea highlights."
- **Command-line look — share.** The prompt's search bar (`_prompt_input_bar_search.py`) renders `/query        [3/12]`
  with a `bold #00D7AF` sigil, white query, a reverse-video cursor cell, a `bold #FFD700` match count, and `dim #FF5F5F`
  "pattern not found", inside a bordered bar titled `search` with subtitle `[enter] accept  [esc/^c] cancel`. We extract
  that pure renderer into a shared helper and use it verbatim so the two search bars are pixel-identical.

## Design

### Key bindings and states (inside the zoom modal only)

The zoom modal gains a tiny three-state model. Keys are handled in the modal's `on_key` **before** its `BINDINGS` fire,
so a query can freely contain letters that are otherwise zoom shortcuts (`j`, `q`, `g`, `n`, `h`, `l`, …).

- **OFF** (normal zoom): `/` → start forward search (TYPING); `?` → start backward search (TYPING). All other keys
  behave exactly as today.
- **TYPING** (command line open, incsearch live): every keystroke edits the query and re-previews.
  - printable char → append; `Backspace`/`Ctrl+H` → delete last char;
  - `Enter` → commit (→ COMMITTED); `Esc`/`Ctrl+C` → cancel (→ OFF, restore pre-search scroll position);
  - all keys are consumed so nothing leaks to the scroll/bindings underneath.
- **COMMITTED** (matches highlighted, browsing): `n` → next match, `N` → previous match (opposite of the search
  direction, Vim semantics); `/` or `?` → start a fresh search; `Esc` → exit search back to the normal panel (**not**
  close the modal); `j/k/g/G/^D/^U` → scroll the highlighted overlay; `y` → copy; **any structural key** (`]` `[` `^N`
  `^P` `=` `-` `h` `l` `L` `H` `E` `r` `q` `z`) exits search first and then performs its normal action on the restored
  native panel. The rule is a one-liner users can internalize: _search-navigation keys stay in search; everything else
  drops you back out._

`?` currently falls through the modal to the **app-level** help binding (`bindings.py`), so opening the global help from
_inside_ the zoom modal will no longer happen — `?` now means "search backward," consistent with Vim. This is an
intentional, documented trade-off; the modal's in-context hint line still teaches every key.

### The search overlay (the one new widget)

Add to `ZoomPanelModal.compose()` a hidden overlay that mirrors the existing panel scrolls:

- `#zoom-search-scroll` — a scroll container carrying the same `.zoom-scroll` look, occupying the same `1fr` region as
  the panel scrolls (only one scroll is ever visible, others get `hidden`), so showing it is a seamless in-place swap.
- `#zoom-search-panel` — a `Static` inside it that we paint with the highlighted corpus.
- `#zoom-search-command` — a `Static` command-line bar (styled like `#prompt-search-command`: `round $accent` border,
  titled `search`), hidden by default, shown while TYPING and while COMMITTED (collapsed to just the `/query [n/total]`
  readout).

**Rendering model (exact and reliable):** at search start we snapshot the active panel's text via `zoom_text()`, split
it into logical lines, and build a Rich `Text` for the overlay rendered **without word-wrap** (`no_wrap=True`,
`overflow="crop"`) so that **one logical line is exactly one display row**. That makes the mapping
`match offset → (row, column)` exact, so scrolling to a match is deterministic (no wrapped-height estimation) — the key
reliability win. Long lines are horizontally scrollable (the overlay scroll enables `overflow-x`), which is precisely
Vim's `nowrap` search feel. Match highlighting is applied with `Text.stylize(start, end, style)` using the absolute
offsets returned by `find_search_matches` (both operate on the same snapshot string, so offsets align):

- **All matches (hlsearch):** a calm highlight, e.g. background `#585858` on default foreground.
- **Current match (incsearch):** a vivid, on-brand highlight, e.g. `black on #FFD787` (the app's PLAN amber) — it pops
  and stays readable, echoing the prompt bar's `#FFD700` count color.

(Exact style constants live in one place in the new module and can be tuned during review / visual-snapshot approval.)

**Jump-to-match:** the current match's row scrolls into view with a few lines of context above (and horizontally so the
matched column is visible); if the row is already comfortably visible we do not jerk the view. All scrolling is driven
explicitly through the modal against `#zoom-search-scroll`, so it does not depend on which widget holds focus.

**Search origin:** like Vim searching from the cursor, the zoom search's "origin" is the top of the current viewport
captured at search start (converted to a character offset). Incsearch uses `include_origin=True` (a match at the current
position counts); `n`/`N` use `include_origin=False` (always advance). Wrap-around reuses `select_search_match`'s
`wrapped` flag to surface Vim's _"search hit BOTTOM, continuing at TOP"_ / _"…hit TOP, continuing at BOTTOM"_ messages
(identical strings to the prompt).

### Freezing content during search (reliability)

The zoom modal auto-refreshes the active panel on a timer (`self._refresh_timer`). While the search overlay is shown
(TYPING or COMMITTED) we **pause that timer** so the corpus the user is searching cannot mutate under them — matches and
offsets stay valid, exactly like searching a Vim buffer. On exit (OFF) we resume the timer and force one refresh so the
live view is current again. This is a deliberate, documented trade-off in favor of correctness.

### Empty / non-text content

If the active panel yields no searchable text (`zoom_text()` is empty — e.g. an image in the FILE panel), `/` and `?` do
nothing except a gentle `notify("Nothing to search")`. No overlay, no state change.

### Focus and key capture

While search is active, focus is kept on a stable capture point in the modal (the modal / command-line widget) and all
keystrokes are routed through the modal's `on_key`, which `stop()`s them while TYPING so no child `VerticalScroll`
swallows arrows/page/backspace/enter. This mirrors the proven `RecursiveFileFinderModal` approach of owning input via
`on_key`. On exit, focus returns to the active panel scroll (today's `reset_active_scroll`).

## Files

New:

- `src/sase/ace/tui/modals/zoom_panel_search.py` — `ZoomSearchMixin`: the search state machine (start/typing/preview/
  confirm/cancel/repeat/exit), the overlay build + highlight + scroll-to-match, corpus extraction, and the pure
  offset→(row,col) helpers. Structurally parallel to `_prompt_search.py`; imports `_vim_search` for matching.
- `src/sase/ace/tui/widgets/search_command_line.py` — a shared pure
  `render_search_command_line(direction, query, current_index, total, width)` extracted from the prompt's
  `_render_search_command_line` so both search bars render identically. (The prompt bar can adopt it later; not required
  here.)

Changed:

- `src/sase/ace/tui/modals/zoom_panel_modal.py` — mix in `ZoomSearchMixin`; add the overlay + command-line widgets to
  `compose()`; add `on_key` dispatch for the three states; pause/resume `_refresh_timer` around search; make
  `active_scroll` return `#zoom-search-scroll` while the overlay is shown; update the bottom hint line to advertise
  `/ ? search  n/N next/prev`.
- `src/sase/ace/tui/modals/zoom_panel_navigation.py` — teach `active_scroll` (or its caller) about the overlay scroll so
  the existing scroll actions target it during search.
- `src/sase/ace/tui/styles.tcss` — styles for `#zoom-search-scroll` / `#zoom-search-panel` (mirror `.zoom-scroll`, with
  `overflow-x: auto` on the overlay) and `#zoom-search-command` (mirror `#prompt-search-command`).
- Docs / help: update `docs/ace.md`'s zoom section and the in-modal hint text; per `src/sase/ace/CLAUDE.md`, audit the
  `?` help popup / agents help content and add the new search keys if the zoom modal's keys are documented there.

### Architecture boundary

This is **presentation-only** Textual work — key handling, an overlay widget, scroll/highlight geometry, and CSS. It
does not cross the Rust core backend boundary: no `sase-core` wire/API/binding changes. (The matching primitive is the
existing pure-Python `_vim_search.py`, which is also presentation-layer TUI code.) This matches the boundary
determination the prior zoom-panel plans reached.

### Performance

All work is in-memory on the keypress path (`memory/tui_perf.md` applies): snapshot the corpus **once** at search start;
per keystroke, run one `find_search_matches` pass (literal regex `finditer`, microseconds–low-ms even for large diffs)
and re-apply spans to the pre-built overlay `Text` (O(matches)) rather than rebuilding the body. No disk or subprocess
work is added on the keypress path. Implementers should read `memory/tui_perf.md` first and sanity-check a large-diff
search with `SASE_TUI_PERF=1`.

## Testing

Follow the existing zoom test layout (`tests/ace/tui/test_agents_zoom_panel_*.py`, helpers in
`_agents_zoom_panel_helpers.py`) and the prompt-search tests. New file `tests/ace/tui/test_agents_zoom_panel_search.py`
covering:

- **Entry / capture:** `/` and `?` open the command line in the right direction; while TYPING, keys that are normally
  zoom shortcuts (`j`, `q`, `g`, `n`, `backspace`) edit the query / are captured rather than scrolling or closing.
- **Incsearch:** typing jumps to and highlights the first match from the origin in the chosen direction; a no-match
  query shows the `pattern not found` readout and does not move; `Esc` restores the pre-search scroll.
- **Commit + repeat:** `Enter` keeps highlights and records the query; `n`/`N` advance/retreat through matches, wrap
  around, and surface the "hit BOTTOM/TOP" feedback; `[k/total]` count is correct (multiple matches per line advance
  match-by-match, not line-by-line).
- **Full-content coverage:** searching a **trimmed** FILE panel finds a match that lives below the trim (proves search
  reads full content, not the rendered/trimmed view).
- **Exit semantics:** structural keys (`]`, `^N`, `r`, `q`) exit search and then perform their action; `Esc` in
  COMMITTED exits search without closing the modal; refresh timer is paused during search and resumed after.
- **Empty content:** `/` on an image/empty FILE panel notifies "Nothing to search" and changes no state.
- **Pure helpers:** unit-test corpus extraction and the offset→(row,col) mapping directly (fast, no TUI).

Add one PNG visual snapshot (mirroring `tests/ace/tui/visual/test_ace_png_snapshots_agents_zoom.py`) of the zoom modal
mid-search — command line with `/query [n/total]` plus the highlighted overlay (all-match + current-match styles) — to
lock the look. Reuse the existing color/font pinning so it stays deterministic; approve the golden with
`--sase-update-visual-snapshots` only after visual review.

## Verification

- `just install` then `just check` (ruff + mypy + fast test suite incl. PNG snapshots), and `just test-visual` for the
  new zoom-search snapshot.
- Manual smoke in `sase ace`: on the Agents tab, `z` a completed agent with a large diff; `/functionName` → jumps and
  highlights live; `Enter` then `n`/`N` cycle matches with wrap feedback; `?term` searches backward; `Esc` restores the
  syntax-colored native panel; confirm search covers content below the file-panel trim; confirm METADATA and TOOLS
  panels search too; confirm the live refresh resumes after exiting search.

## Deliberately out of scope (call-outs for review)

- **Regex search.** `/` is literal (smartcase) here, matching the prompt editor and avoiding surprising regex errors on
  metacharacters. Regex could be a later opt-in.
- **Preserving syntax/diff colors _under_ the highlight.** During search the overlay is clean highlighted text, not
  monokai-colored diff; `Esc` returns the fully colored native panel. A future enhancement could render a diff-aware
  colored overlay (line-prefix coloring is cheap) while keeping exact highlight control — noted, not built.
- **DRY-ing the prompt search onto the shared command-line renderer.** We add the shared renderer and use it in zoom;
  migrating the prompt bar to it is a safe follow-up left out to avoid touching the prompt's tested path.
- **`n`/`N` are included** even though the request named only `/` and `?`, because a Vim search without repeat is half a
  feature; they are free keys in the zoom modal. If undesired, they can be dropped without affecting the core.
