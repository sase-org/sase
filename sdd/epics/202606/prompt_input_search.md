---
create_time: 2026-06-17 18:21:33
status: done
prompt: sdd/prompts/202606/prompt_input_search.md
bead_id: sase-4v
tier: epic
---
# Plan: Vim-style Forward/Reverse Search in the Prompt Input Widget

## Summary

Add Vim-inspired incremental search to the `sase ace` prompt input widget (`PromptTextArea`). In **normal mode**, `/`
starts a forward search and `?` starts a reverse search over the text the user is composing. A Vim-style command line
collects the query, matches highlight live as the user types (incsearch), the cursor jumps to the nearest match, and `n`
/ `N` repeat the last search. The feature must feel intuitive (faithful to Vim muscle memory), be reliable (no stuck
modes, clean cancel, correct wrap-around), and look beautiful (theme-aware two-tier match highlighting and a polished
command line).

This is a buffer-local text-editing/navigation feature, scoped entirely to the prompt input widget. It is the natural
sibling of the existing Vim motions already implemented in this widget (`f`/`F`/`t`/`T`, `w`/`b`/`e`, `{`/`}`, `gg`,
text objects, etc.).

## Product Context

The prompt input is where users compose agent prompts, often long multi-line prompts and multi-agent prompts (with `---`
separators) and workflow prompts. The widget already has a rich Vim normal mode. The one glaring gap for Vim users is
search: there is currently no way to jump to an occurrence of a word within a long prompt without manual cursor motion.
Forward/reverse search closes that gap and rounds out the Vim experience. It also lays reusable foundations (a match
engine + a highlight overlay) that future features (e.g. search-and-replace) could build on.

## Goals

- `/<query><Enter>` performs a forward search; `?<query><Enter>` performs a reverse search, both from **normal mode**,
  matching Vim semantics.
- Incremental search ("incsearch"): as the query is typed, all matches highlight and the cursor previews the nearest
  match in the search direction.
- `n` repeats the last search in its original direction; `N` repeats in the opposite direction.
- Smartcase matching: case-insensitive unless the query contains an uppercase character (Vim-idiomatic).
- Wrap-around with clear, Vim-style feedback ("search hit BOTTOM, continuing at TOP"), and a non-intrusive "pattern not
  found" message when there are no matches.
- A two-tier, theme-aware highlight: every match gets a subtle highlight, the current match gets a strong one. Looks
  correct in every ACE theme.
- A match-count indicator (e.g. `[3/12]`) for orientation.
- Clean cancel (`Esc` / `Ctrl+C` restores the pre-search cursor and clears highlights) and clean confirm (`Enter` leaves
  the cursor on the match and records the search for `n`/`N`).
- Correct behavior in stacked multi-pane prompts (search operates within the active pane only) and on both single-line
  and multi-line prompts.

## Non-Goals (explicitly out of scope)

- Search-and-replace (`:s/.../.../`) — foundations are laid but the feature is not built here.
- Regex / pattern syntax — v1 is literal substring matching with smartcase. (Design leaves room to add regex later
  behind the same engine API.)
- Making the search keys (`/`, `?`, `n`, `N`) user-configurable. These are intrinsic Vim-mode keys handled inside the
  widget, exactly like the existing `f`/`F`/`t`/`T`/`;`/`,` motions, which are also hardcoded and **not** part of the
  configurable `AppKeymaps`. Therefore **no `default_config.yml` changes are required**. Configurability can be
  revisited later as a separate effort that would migrate all vim-mode keys together.
- Searching across panes, across prompt history, or in any widget other than `PromptTextArea`.

## Key Design Decisions

1. **Normal mode only.** `/`, `?`, `n`, `N` activate search only in normal mode. In insert mode these are literal
   characters being typed into the prompt, so search there would be wrong. This matches Vim and is the intuitive choice.
   Users press `Esc` (already implemented) to enter normal mode, then search.

2. **Intercept and stop `/` and `?` so they don't leak to the app.** At the app level, `/` is bound to `edit_query` and
   `?` to `show_help`. The prompt widget intercepts keys in `_on_key` before they bubble, but currently returns `False`
   for `/` and `?` in normal mode, which risks them bubbling to the app bindings. The implementation MUST handle these
   keys in the normal-mode dispatch and call `event.stop()` / `event.prevent_default()` so the app's `edit_query` /
   `show_help` never fire while the prompt input is focused in normal mode. This is a correctness/reliability
   requirement and a regression risk to guard with a test.

3. **Reuse the existing highlight-overlay pattern, not a new rendering path.** Match highlighting is layered on the same
   mechanism that `JinjaHighlightMixin` uses: override `_build_highlight_map()`, emit spans via
   `_append_highlight_span(start, end, style_name)`, and register theme-aware named styles (`search.match`,
   `search.current`) on a `TextAreaTheme`. The new search mixin must cooperate with the Jinja overlay in the mixin chain
   (each override calls `super()._build_highlight_map()`); getting this chaining right is the main integration risk and
   is the reason the overlay is built and proven first (Phase 1). Honor the existing overlay perf guards
   (`_MAX_OVERLAY_BYTES`, `_MAX_OVERLAY_LINES`) and degrade gracefully on very large buffers.

4. **A small, pure match engine lives in Python alongside the existing vim motions.** Match finding (smartcase substring
   scan over the document, ordered results, next/prev selection relative to an origin with wrap-around) is a pure
   function placed next to `_vim_motions.py`. This mirrors how all current vim motions (`find_next_word_start`,
   `find_char_forward`, …) are pure Python helpers in this widget.

5. **Rust core boundary: this stays in Python.** Per `memory/short/rust_core_backend_boundary.md`, the litmus test is
   whether another frontend (web app, CLI, editor integration) would need this behavior to match the TUI. In-buffer
   incremental search of an ephemeral, being-composed prompt is presentation-layer text-editing behavior — the same
   category as the existing vim motions, which already live in Python in this repo. It is not shared domain logic.
   Putting per-keystroke match finding behind the `sase_core_rs` wire boundary would also fight the "highlight must
   paint immediately" performance rule. The plan therefore keeps the engine in Python. (If a future search-and-replace
   touched persisted ChangeSpec/agent data, that part would be re-evaluated against the boundary — but it is out of
   scope here.)

6. **Search is a transient sub-mode of normal mode, modeled like the existing pending-key states.** The widget already
   manages sub-modes via `_pending_keys` + `_update_count_display()` (e.g. the `g`-prefix state and its hints panel).
   The search command line is a new, dedicated sub-mode that captures a multi-character query terminated by
   `Enter`/`Esc`, distinct from the single-char pending states. It must be mutually exclusive with the other transient
   UIs (completion panel, frontmatter panel, `g`-prefix hints) and must tear down cleanly on mode change, pane switch,
   or edit.

## UX Design (intuitive + beautiful)

**Entering search.** In normal mode, `/` (forward) or `?` (reverse) opens a Vim-style command line anchored at the
bottom of the prompt input bar. It shows the leading `/` or `?` in the theme accent color, followed by the live query
and a cursor. The rest of normal-mode editing is suspended while the command line is open.

**Incremental search (incsearch).** On every keystroke:

- All occurrences of the current query highlight with the subtle `search.match` style.
- The match nearest the origin in the search direction is promoted to the strong `search.current` style and the cursor
  previews it.
- A right-aligned counter shows `[i/N]` (e.g. `[3/12]`); when there are no matches it shows a subtle, non-blocking
  `pattern not found`.
- Backspace shrinks the query and re-searches; emptying the query clears highlights and returns the preview cursor to
  the origin.

**Confirm / cancel.**

- `Enter` confirms: the cursor stays on the current match, the command line closes, the search (query + direction) is
  recorded for `n`/`N`. Match highlights remain briefly visible for orientation and clear on the next edit / mode change
  (final persistence behavior decided in Phase 3 to feel best).
- `Esc` or `Ctrl+C` cancels: the cursor returns to the pre-search origin, highlights clear, command line closes. No
  stuck state under any key sequence.

**Repeat navigation.**

- `n` jumps to the next match in the last search's direction; `N` jumps in the opposite direction.
- Both wrap around the buffer and surface Vim-style messages ("search hit BOTTOM, continuing at TOP" / "…hit TOP,
  continuing at BOTTOM").
- With no prior search, `n`/`N` are no-ops with a subtle "no previous search" hint.

**Smartcase.** Lowercase query → case-insensitive; any uppercase in the query → case-sensitive. Intuitive and matches
common Vim configs.

**Beauty.** Two-tier theme-aware highlighting (subtle vs. strong, derived from the active theme so it reads well
everywhere), an accent-colored command-line sigil, a tidy right-aligned counter, and gentle wrap/empty messaging. A PNG
visual snapshot locks the look (the repo's visual snapshot suite supports this).

## Technical Design Overview

- **Widget:** `src/sase/ace/tui/widgets/prompt_text_area.py` (`PromptTextArea`) and its mixin chain.
- **Normal-mode dispatch:** add `/`, `?`, `n`, `N` handling in the normal-mode key path (`_vim_normal.py` /
  `_vim_normal_motions.py`), guarding with `event.stop()` so they never bubble to the app's `edit_query` / `show_help`.
- **Search sub-mode state machine:** new mixin holding query/direction/origin/match-list/current-index, with
  enter/keystroke/confirm/cancel transitions, integrated with `_update_count_display()` and mutually exclusive with
  completion/frontmatter/`g`-prefix UIs.
- **Match engine:** new pure helper module beside `_vim_motions.py` (smartcase, ordered matches, next/prev with wrap,
  multi-line and unicode safe).
- **Highlight overlay:** new mixin paralleling `JinjaHighlightMixin` — `search.match` / `search.current` styles
  registered on a `TextAreaTheme`, spans emitted from `_build_highlight_map()` via `_append_highlight_span`, cooperating
  with the Jinja overlay in the chain and respecting the overlay perf guards.
- **Command-line UI:** a single-line region rendered by the prompt bar (sibling to the existing g-prefix hints /
  completion / frontmatter panels), shown only while the search sub-mode is active. Styling added to
  `src/sase/ace/tui/styles.tcss`. State recorded for `n`/`N` parallels the existing `_last_char_search` pattern used by
  `f`/`F`/`t`/`T` with `;`/`,`.
- **Last-search record:** add a `_last_search` field analogous to `_last_char_search`.

### Performance (per `memory/long/tui_perf.md`)

- The prompt buffer is small and bounded by the overlay guards, so smartcase substring scanning per keystroke is cheap;
  keep it synchronous so the highlight paints immediately (the perf rules say to debounce detail panels, never the
  highlight).
- Do not introduce a new refresh path; reuse `_refresh_jinja_overlay`-style refresh after recomputing spans.
- Above `_MAX_OVERLAY_BYTES` / `_MAX_OVERLAY_LINES`, skip highlight emission (as Jinja does) and still allow cursor-jump
  search, so large prompts degrade gracefully rather than lag.

### Documentation / conventions

- Update the `?` help modal (`src/sase/ace/tui/...` help content) to document the new prompt-input search keys, per the
  `ace/AGENTS.md` rule to keep the help popup in sync, respecting its fixed box-width formatting constraints.
- No `default_config.yml` / `AppKeymaps` / `_BINDING_META` changes (see Non-Goals / Decision 5). No footer keybinding
  changes (these are widget-internal vim keys, not conditional app keymaps).

## Phased Delivery

The work is split into **three sequential phases**, each completed by a distinct agent instance. Every phase must leave
the repo green (`just install` then `just check`, plus relevant tests) and is independently reviewable. Earlier phases
are foundational and intentionally land before the feature is user-visible to de-risk the trickiest integration (the
highlight overlay chaining) first.

### Phase 1 — Match engine + highlight overlay (foundation, not yet wired to keys)

**Scope.** Build the two reusable, independently testable foundations:

1. A pure match engine (new module beside `_vim_motions.py`): smartcase literal search returning ordered `(start, end)`
   spans over the document, plus a selector that, given an origin and direction, returns the target match index with
   wrap-around. Multi-line and unicode safe; handles empty query and no-match.
2. A `SearchHighlightMixin` paralleling `JinjaHighlightMixin`: registers theme-aware `search.match` / `search.current`
   styles, stores current match spans + current index on the widget, emits them in an overridden
   `_build_highlight_map()` that cooperates with the Jinja overlay via `super()`, and respects the overlay perf guards.
   Add a refresh helper.

**Deliverable.** Matches can be computed and rendered programmatically (driven by a test/dev hook); no user-facing
keybinding yet, so no behavior change for users.

**Acceptance.**

- Comprehensive unit tests for the engine: smartcase on/off, forward/reverse next selection, wrap-around, multi-line
  spans, unicode, overlapping/adjacent matches, empty query, no match.
- A focused test proving the overlay coexists with the Jinja overlay (both sets of spans present; mixin chaining
  correct) and that emission is skipped above the perf guards.
- `just check` green.

**Primary files.** new match-engine module + `_search_highlight.py` (new) under `src/sase/ace/tui/widgets/`; wire the
mixins into `PromptTextArea`'s base list; tests under `tests/`.

### Phase 2 — Interactive incremental search (`/` and `?`, command line, confirm/cancel)

**Scope.** Make search user-facing and interactive, on top of Phase 1.

- Add `/` and `?` handling to the normal-mode dispatch to enter the search sub-mode; `event.stop()` so they never reach
  the app's `edit_query` / `show_help`.
- Implement the search sub-mode state machine (query buffer, direction, origin cursor, current match index) and route
  subsequent keystrokes to it (printable → append, backspace → shrink, `Enter` → confirm, `Esc` / `Ctrl+C` → cancel),
  mutually exclusive with completion/frontmatter/`g`-prefix sub-modes.
- Incremental search: on each query change, recompute matches (Phase 1 engine), move the preview cursor to the nearest
  match in the search direction, and refresh highlights (Phase 1 overlay).
- Build the command-line UI region in the prompt bar + TCSS, with the accent sigil, live query, and right-aligned
  `[i/N]` counter / `pattern not found` state.
- Confirm records `_last_search`; cancel restores the origin cursor and clears highlights.

**Deliverable.** Fully working interactive `/` and `?` search with incsearch and clean confirm/cancel.

**Acceptance.**

- Integration tests via the existing prompt-page harness: forward and reverse search land on the correct match;
  incsearch updates as the query grows/shrinks; `Enter` keeps the cursor and records the search; `Esc` and `Ctrl+C`
  restore the origin and clear highlights; `/`/`?` do not trigger `edit_query`/`show_help`.
- Help modal updated to document the new keys.
- `just check` green.

**Primary files.** `_vim_normal.py` / `_vim_normal_motions.py`; new search sub-mode mixin under
`src/sase/ace/tui/widgets/`; `prompt_input_bar.py` + its mixins for the command-line region; `styles.tcss`; help modal
content; tests.

### Phase 3 — Repeat (`n`/`N`), wrap/feedback, edge-cases, multi-pane, and visual polish

**Scope.** Complete and harden the feature.

- `n` / `N` repeat using `_last_search` (respecting/inverting direction) with wrap-around and Vim-style "hit BOTTOM/TOP,
  continuing…" messages; no-op + hint when there is no previous search.
- "pattern not found" messaging and reliable teardown: clearing search highlights on mode change, edit, pane switch,
  blur, and cancel; guaranteeing no stuck sub-mode under any key sequence.
- Stacked multi-pane behavior: search and its state are scoped to the active pane; switching panes clears search
  highlights.
- Large-buffer graceful degradation verified (cursor-jump search still works with highlight emission skipped above the
  overlay guards).
- Final visual polish for beauty and a **PNG visual snapshot** of the highlighted search state added to the visual suite
  (goldens under `tests/ace/tui/visual/snapshots/png/`).
- Finalize the post-confirm highlight-persistence behavior chosen to feel best.

**Deliverable.** A polished, robust, beautiful feature with regression coverage.

**Acceptance.**

- Tests for `n`/`N` direction and wrap; not-found and wrap messaging; teardown on mode change / edit / pane switch /
  blur; multi-pane scoping; large-buffer degradation.
- Visual snapshot added and passing (`just test-visual`).
- Help/docs reflect `n`/`N` and search semantics.
- `just check` green.

**Primary files.** `_vim_normal_motions.py` (n/N); search sub-mode + overlay teardown hooks; `prompt_stack.py` /
multi-pane mixins for pane-switch clearing; visual test + golden; help/docs; tests.

## Testing Strategy

- **Unit:** the pure match engine (Phase 1) — exhaustive case coverage independent of Textual.
- **Integration:** the existing prompt-page TUI harness used by other normal-mode tests — drive `/`, `?`, typing,
  `Enter`, `Esc`, `Ctrl+C`, `n`, `N` and assert cursor position, highlight spans, command-line contents, counter, and
  that app bindings don't fire.
- **Visual:** one PNG snapshot of the highlighted incsearch state (Phase 3) to lock the look; uses the repo's
  deterministic visual fixtures.
- **Perf:** rely on existing overlay guards; if any doubt, sanity-check with `SASE_TUI_PERF=1` that per-keystroke search
  stays well under the 16 ms key-to-paint target on a large prompt.

## Risks & Mitigations

- **Mixin-chain `_build_highlight_map` interaction with Jinja** — highest risk. Mitigated by building and testing the
  overlay first (Phase 1) with an explicit coexistence test and disciplined `super()` chaining.
- **`/` `?` leaking to app `edit_query` / `show_help`** — mitigated by `event.stop()` in normal-mode dispatch plus a
  dedicated regression test.
- **Stuck sub-mode / mode confusion** with completion/frontmatter/`g`-prefix UIs — mitigated by explicit mutual
  exclusion and teardown-on-everything (mode change, edit, pane switch, blur) with tests.
- **Performance on large prompts** — mitigated by honoring the existing overlay byte/line guards and keeping the scan
  synchronous and cheap.
- **Read-only normal mode** — search only moves the cursor and renders overlays, so it is compatible with the
  normal-mode `read_only = True` state; verified by tests.

## Decisions Already Made (so phase agents don't re-litigate)

- Search activates in **normal mode only**.
- Keys are **hardcoded vim-mode keys** (no `default_config.yml` / `AppKeymaps` changes), consistent with the existing
  `f`/`F`/`t`/`T`/`;`/`,` motions.
- Matching is **literal substring with smartcase** (no regex in v1).
- Engine and overlay stay in **Python** (Rust core boundary explicitly evaluated — not shared domain logic).
- `n` = same direction as the last search, `N` = opposite; both wrap with Vim-style messaging.
