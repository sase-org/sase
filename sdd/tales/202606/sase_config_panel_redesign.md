---
create_time: 2026-06-26 09:07:24
status: done
prompt: sdd/prompts/202606/sase_config_panel_redesign.md
---
# Plan: Beautify the "SASE Config" panel (Config Center modal)

## Goal

Polish the look of the `sase ace` Config Center modal (the full-screen modal opened with `#`). Satisfy the three
explicit requests and apply a small set of objective, cohesive design improvements so the panel reads as a deliberate,
branded "header band + content" layout instead of plain left-aligned text.

## Product context

The Config Center is a full-screen `ModalScreen` that hosts two internal tabs over a `ContentSwitcher`:

- **Config** (default) — the schema-driven read-only config browser (Sources / Fields / Detail panels).
- **XPrompts** — the migrated XPrompt Browser.

`[` / `]` cycle the tabs; `Esc`/`q` close. Today the modal chrome is:

- A bold, **left-aligned** title `Config Center`.
- A bold, **left-aligned** tab strip `Config │ XPrompts` (active tab colored, separators muted).
- A `92% × 85%` container with a `thick $primary` border.

The chrome looks unbalanced (left title over left tabs, no separation from content) and the naming is generic.

## Requirements (explicit)

1. **Title** → `SASE Config` (was `Config Center`), **centered** in the panel.
2. **Panel a little larger.**
3. **Rename the `Config` tab → `Settings`** (display label only; internal tab key stays `config`).

## Design improvements (lead/own these)

The unifying idea: turn the top of the modal into a clean, centered **header band** (title + tabs + divider) that
clearly frames the content below, and tie the colors to the existing `$primary` border so it looks branded.

A. **Centered, accented title.** Center `SASE Config`, keep it bold, and color it `$primary` so it harmonizes with the
modal's `thick $primary` border (reads as a real heading, not stray text). Color is tunable to `$accent`/teal at
snapshot-review time.

B. **Centered tab strip.** Center `Settings │ XPrompts` directly under the centered title so the two header rows share
one axis. Keep the existing active/inactive coloring (bold bright vs. muted) and the muted `│` separators — centering
plus the divider below is the visual win; no pills/extra noise.

- _Correctness detail:_ the tab strip is a `Static` whose click handler maps `event.x` to character ranges built from
  column 0. CSS-centering shifts the rendered text right, so the click handler must subtract the centering pad
  (`(content_width - text_width) // 2`) before comparing, or clicking a tab would hit the wrong/no tab. The built line's
  plain length is captured when the strip is (re)rendered so the handler can compute the pad. This keeps mouse
  tab-switching working after centering.

C. **Header/content divider.** Add one subtle full-width horizontal rule between the header band (title + tabs) and the
`ContentSwitcher`. This frames the chrome cleanly. Use a muted color (matching the `│` separators) with zero vertical
margin so it stays tight. Tunable/removable if it reads heavy during snapshot review.

D. **Larger panel.** Grow the container from `92% × 85%` to `95% × 90%` — noticeable but still a modal, and it gives the
three inner config panels more breathing room.

E. **Consistent naming.** Update the user-facing label of the open action from `Config Center` → `SASE Config` (keymap
label + binding description) and the panel name in `docs/configuration.md`, so help text and docs match the new title.
Internal identifiers (`ConfigCenterModal`, `CenterTab`, the `"config"` tab key, `open_config_center`,
`initial_tab="config"`, file names) are **left unchanged** to avoid churn and API/test breakage. Historical
`CHANGELOG.md` entries are left as-is.

Out of scope (kept deliberately tight): the inner pane titles/contents (e.g. the `Configuration [N fields · M modified]`
header, the Sources/Fields/Detail layout) and the XPrompt browser internals. The request targets the modal chrome.

## High-level technical design

**Modal chrome (Config Center modal source)**

- Title `Label` text `Config Center` → `SASE Config`.
- Tab label `Config` → `Settings` in the display-label table (the internal key stays `config`).
- Add a horizontal rule widget to the compose tree, between the tab strip and the `ContentSwitcher`.
- In the clickable tab-strip widget: capture the rendered line's plain length when (re)building it, and offset `event.x`
  by the centering pad in the click handler so centered tabs remain clickable.

**Styles (TUI stylesheet, Config Center section)**

- Container: `width 92% → 95%`, `height 85% → 90%` (keep `thick $primary` border, surface background, padding).
- Title: add `text-align: center` and `color: $primary` (keep bold; height 1).
- Tab strip: add `text-align: center` and `width: 100%` (keep `nowrap` / clip).
- New rule: zero margin, muted color, height 1.

**Naming sync**

- Keymap label table: `("open_config_center", "Config Center", False)` → `… "SASE Config" …`.
- Binding description string `Config Center` → `SASE Config`.
- `action_open_config_center` docstring/comment wording (cosmetic) updated to match.
- `docs/configuration.md`: panel name, the TOC anchor line, and section heading referencing "Config Center" updated to
  "SASE Config" (keep wording natural; the `#` keymap and behavior description are unchanged).

## Affected files

- `src/sase/ace/tui/modals/config_center_modal.py` — title text, tab label, add divider, click-offset fix.
- `src/sase/ace/tui/styles.tcss` — container size, centered/accent title, centered tabs, divider style.
- `src/sase/ace/tui/keymaps/types.py` — open-action label.
- `src/sase/ace/tui/bindings.py` — binding description.
- `src/sase/ace/tui/actions/base.py` — docstring wording (cosmetic).
- `docs/configuration.md` — panel name / heading / TOC anchor.
- `tests/ace/tui/visual/snapshots/png/config_center_*.png` — regenerated goldens (see Verification).

## Verification

1. `just install` (ephemeral workspace may have stale deps), then `just check` (ruff + mypy + tests).
2. Regenerate the Config Center visual goldens and **eyeball every one** to confirm the new chrome looks intentional and
   nothing is clipped/misaligned:
   - `config_center_config_tab`, `config_center_config_empty`, `config_center_config_loading`,
     `config_center_config_long_value`, `config_center_xprompts_tab` (these directly show the redesigned chrome).
   - `config_center_edit_modal`, `config_center_edit_preview` (the edit modal sits on top of the now-larger panel —
     confirm the dimmed panel peeking around the edges still looks clean).
   - Use `just test-visual` and accept intentional changes with `--sase-update-visual-snapshots` only after visual
     confirmation.
3. Confirm by manual reasoning (and the populated/xprompts snapshots) that **clicking** either tab still switches tabs
   after centering — verifying the click-offset fix.
4. Confirm no non-visual test asserted the old title/label strings (current grep shows only docstrings/snapshot report
   titles reference "Config Center"; those are non-functional).

## Risks & mitigations

- **Centered-tab click regression** — primary correctness risk; mitigated by the explicit `event.x` pad-offset fix and a
  manual click check during verification.
- **Snapshot churn** — every Config Center golden changes; mitigated by regenerating and individually eyeballing all
  seven, and updating only after visual confirmation.
- **Divider/title color taste** — `$primary` title and the rule color are tunable during snapshot review; the rule can
  be dropped if it reads heavy, without affecting the required changes.
