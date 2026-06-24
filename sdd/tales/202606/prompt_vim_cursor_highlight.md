---
create_time: 2026-06-24 06:49:11
status: done
prompt: sdd/prompts/202606/prompt_vim_cursor_highlight.md
---
# Plan: Readable, mode-distinct vim cursor in the Prompt Input Widget

## Problem & product context

In the `sase ace` Prompt Input Widget (the multi-pane `PromptTextArea`), vim **Normal Mode** highlights the character
under the cursor with **reverse video**. Reverse video layered over the widget's themed colors produces a low-contrast
cell where the glyph is hard to read. Two issues:

1. **Readability** — the selected character in Normal Mode is hard to see (the user's core complaint).
2. **Mode ambiguity at the cursor** — Normal and Insert mode both render the cursor as reverse video, so the cursor cell
   itself barely signals which mode you're in. Today the only at-cursor mode hint is a subtle read-only "warning" tint;
   the clearer signals live in the gutter (relative vs absolute line numbers, gold vs cyan).

### Goal

Redesign the cursor highlight so that:

- The character under the Normal Mode cursor is **crisply readable**.
- It is **immediately obvious** whether the user is in Normal Mode vs Insert Mode, from the cursor itself.
- It looks **beautiful** and coherent with the rest of the TUI.

## Root cause (why it's unreadable today)

Textual's `TextArea` renders the cursor cell by applying `TextAreaTheme.cursor_style` to one character. The prompt's
active theme (`sase-jinja-prompt`, derived from the builtin `css` theme) leaves `cursor_style = None`, so Textual falls
back to the `text-area--cursor` **component style**, whose default is `text-style: reverse` (plus, because Normal Mode
sets `read_only = True`, a `$warning-darken-1` background). Reverse video on top of explicit fg/bg colors swaps them
back in a theme-dependent way, giving the muddy, hard-to-read cell — and it is essentially the same in Insert Mode (also
reverse), so the cursor does not distinguish the modes.

Two facts make a clean fix possible:

- **Steady-vs-blinking is already free.** Normal/Visual modes set `read_only = True` and Insert sets
  `read_only = False`. Textual's `_draw_cursor` already renders a **steady block** when read-only and a **blinking
  caret** when editable. So the authentic vim "steady block in command mode, blinking caret in insert mode" behavior
  already exists — we only need to fix the _color/readability_, not blink.
- **The cursor style re-resolves every frame from CSS.** `TextArea.render_lines` calls `theme.apply_css(self)` on every
  render, which re-derives `cursor_style` from the `text-area--cursor` component style whenever the theme leaves it
  unset (ours does). Component styles react to the widget's CSS classes, and toggling a class invalidates the style
  cache. So a per-mode CSS class cleanly drives the cursor with no theme-object juggling.

## Design — the look

Replace reverse video with explicit, readable, **mode-colored solid blocks**, reusing the Flexoki accent language the
gutter already uses (`#D0A215` gold for the Normal-mode current line, `#3AA99F` cyan for Insert). The cursor color is
made to **match its mode's gutter accent**, so cursor + gutter form one coherent, redundant mode identity.

| Mode   | Cursor cell | Background        | Glyph color          | Weight | Cursor motion (already free) |
| ------ | ----------- | ----------------- | -------------------- | ------ | ---------------------------- |
| Normal | solid block | gold `#D0A215`    | near-black `#100F0F` | bold   | **steady** (read-only)       |
| Insert | solid block | cyan `#3AA99F`    | near-black `#100F0F` | bold   | **blinking** (editable)      |
| Visual | solid block | magenta `#CE5D97` | paper `#FFFCF0`      | bold   | steady (read-only)           |

Why this is readable, clear, and beautiful:

- A dark glyph on a bright, saturated block guarantees contrast against any terminal background — directly fixing the
  readability complaint, unlike reverse video.
- **Gold = command/Normal, cyan = typing/Insert** reads instantly and matches the gutter, so the two modes are
  unmistakable at a glance (cursor color + gutter color + relative/absolute numbers all agree).
- Steady gold block vs blinking cyan caret is the genuine terminal-vim metaphor — and it falls out of the existing
  `read_only` wiring, so we get it for free.
- Because each block supplies its own fg+bg, it looks correct on both light and dark terminals.
- Visual Mode gets its own magenta block for a complete, coherent three-mode palette (it also already shows a selection
  highlight); this keeps the language consistent without regressing Visual Mode.

## Design — the mechanism (presentation-only; no Rust)

Per the repo's `rust_core_backend_boundary` guidance, cursor highlight styling is **presentation-only Textual
rendering** and stays in this repo — no `sase-core` / binding changes.

Drive Textual's native cursor pipeline via a per-mode CSS class plus matching component-style rules:

1. **Stylesheet (`src/sase/ace/tui/styles.tcss`), near the existing `.prompt-input` rules.** Add one `text-area--cursor`
   rule per mode class, scoped to the prompt text area, e.g.
   `PromptTextArea.-vim-normal .text-area--cursor { color: …; background: …; text-style: bold; }` for `-vim-normal` /
   `-vim-insert` / `-vim-visual`. The selectors must out-specify Textual's built-in `:dark`/`:light .text-area--cursor`
   rules and explicitly set `text-style` so the inherited `reverse` is overridden (app stylesheet already beats widget
   `DEFAULT_CSS`, and the extra mode class adds specificity). Document the hex values with a comment cross-referencing
   the gutter colors.

2. **Per-mode class sync (Python glue).** Add a small helper on the widget (natural home: `LineRenderingMixin` in
   `_line_rendering.py`, which already owns per-mode visual indicators) that maps `self._vim_mode` to exactly one of
   `-vim-normal` / `-vim-insert` / `-vim-visual` (collapsing `visual_line` → visual) and applies it via
   `set_class`/`remove_class`. Call it from the existing methods that already set `_vim_mode`:
   - `_enter_normal_mode` / `_enter_insert_mode` (`_prompt_text_area_actions.py`)
   - `_enter_visual_mode` / `_switch_visual_kind` (`_vim_visual_state.py`)
   - Set the initial Insert-mode class on mount (extend the existing `on_mount` chain) so a freshly mounted prompt shows
     the Insert cursor before any transition occurs.

3. **No `cursor_blink` changes** — `read_only` already produces steady vs blinking; leave it untouched.

### Single source of truth for the colors

The gutter hexes are currently hardcoded in `_line_rendering.py`. To keep cursor and gutter colors in lockstep,
optionally lift the three mode accents into a tiny shared constants module referenced by both the gutter code and a
comment in `styles.tcss` (CSS cannot import Python). Minimum bar: matching hexes plus a cross-reference comment. Prefer
the lightweight comment unless the shared constant is trivially clean.

## Alternatives considered (and rejected)

- **Set `cursor_style` as a Python `Style` on the theme per mode.** Fights `_set_theme`'s `dataclasses.replace` and the
  Jinja/search overlay re-registration, and must be re-applied on every app-theme change. The CSS-class route is
  self-healing and simpler.
- **Post-process the rendered `Strip` to restyle the cursor cell in `render_line`.** Requires recomputing the cursor's
  cell column accounting for gutter width, horizontal scroll, and tab expansion — fragile and duplicates Textual
  internals.

## Testing & verification

- **Visual PNG snapshots** (`tests/ace/tui/visual/`, alongside the prompt-stack suite): add snapshots for (a) Normal
  Mode after `escape` showing the readable gold block and (b) Insert Mode showing the cyan caret (optionally a
  Visual-Mode magenta block). Generate goldens with the visual-update flag and eyeball them for readability and beauty.
- **Unit test** (deterministic, no pixels): assert the class-toggle contract — after `_enter_normal_mode` the widget
  carries `-vim-normal` (and not the others), `_enter_insert_mode` → `-vim-insert`, entering visual → `-vim-visual`.
  Place with the existing prompt vim-mode unit tests.
- Run `just install` then `just check` (and `just test-visual`) before finishing, per the build memory.

## Out of scope

- Cursor styling for non-prompt text areas / other widgets.
- Configurability of the cursor colors (could be a follow-up if desired).
- Any change to vim keybindings or mode semantics — this is purely the cursor's appearance.

## Acceptance criteria

- In Normal Mode, the character under the cursor is clearly legible.
- Normal vs Insert is obvious from the cursor alone (gold steady block vs cyan blinking caret), reinforced by the
  matching gutter color.
- Visual Mode remains visually coherent (distinct block, selection highlight intact).
- Light and dark terminals both render readable cursors.
- `just check` and the visual snapshot suite pass with refreshed goldens.
