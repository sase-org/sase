---
create_time: 2026-06-18 09:18:21
status: done
prompt: sdd/prompts/202606/frontmatter_add_property_picker.md
---
# Redesign the Add-Property Picker for the Frontmatter Panel

## Context

The prompt input bar mounts a **Frontmatter Panel** (`FrontmatterPanel`) directly above the prompt stack. This is the
"xprompt property panel": it structurally edits a prompt's YAML frontmatter (the `name`, `description`, `tags`, `input`,
`xprompts`, `skill`, `snippet` fields that define an xprompt).

While that panel is focused, pressing **`a`** adds a property. For an unset top-level field this posts
`FrontmatterPanel.AddRequested`, and the host bar (`_prompt_input_bar_frontmatter.py`) pushes the **`AddPropertyModal`**
— the small picker that lists the frontmatter fields the user has _not_ set yet, each with its one-line description
sourced from `sase-core` (the same schema that backs the xprompt LSP). Choosing one drops the panel into that field's
editor (inline for scalars/lists/bools, a sub-form modal for the structured `input` / `xprompts` fields).

### Problem

The picker that appears on `a` is underwhelming:

- **It's cramped.** `AddPropertyModal` is a bare `OptionList` in a 64-cell container (`styles.tcss` →
  `AddPropertyModal`). Each option is a single line (bold field name + dimmed description), with no room to convey a
  field's type, example, or accepted values.
- **Selection takes two steps.** It uses `OptionListNavigationMixin`: the user navigates with `j`/`k` and confirms with
  `enter`. There is no way to jump straight to a property with one key.

### Goals (from the request — I am leading the design)

1. The picker shown on `a` should be **larger**.
2. The user should be able to **select any available property with a single keypress**.
3. It should look **beautiful**.

## Boundary note (presentation-only)

This work is entirely TUI presentation: modal sizing, styling, row rendering, key handling, and Python glue in this
repo. The list of fields and all of their text (descriptions, examples, accepted-value hints) continues to come from
`sase-core` via `frontmatter_field_schema()`. **No Rust core, wire, or binding changes are required**, and no new field
semantics are introduced — we only display schema metadata that the panel already loads.

## Design

Rewrite `AddPropertyModal` from an `OptionList` picker into a **custom keyed picker** modeled on the existing
`ApproveOptionsModal` (custom selectable `Static` rows + a direct `on_key` handler + a footer hint line). This is the
established in-repo pattern for "press one letter to choose an action," so the new picker stays consistent with the rest
of the TUI.

### Layout (target look)

```
╭─ Add frontmatter property ─────────────────────────────────────────────╮
│                                                                         │
│  ▸  n   name         scalar      Overrides the reference name…          │
│     d   description  scalar      Single-line summary for completions…   │
│     t   tags         list        Tags for catalog filtering…           │
│     i   input        structured  Declares named inputs…                 │
│     x   xprompts     structured  Local xprompts referenced with #name…  │
│     s   skill        bool|list   Mark this xprompt as a slash skill…    │
│     p   snippet      bool|scalar Expose as a completion snippet…        │
│                                                                         │
│  ── name ────────────────────────────────────────────────────────────  │
│  Overrides the xprompt reference name used in catalogs and completions. │
│  Example   my_prompt                                                    │
│                                                                         │
│  n d t i x s p  pick   ·   j/k move   ·   enter select   ·   esc cancel  │
╰─────────────────────────────────────────────────────────────────────────╯
```

Each row carries:

- A **selection marker** (`▸`, accent) on the highlighted row; blank otherwise.
- A **key badge**: the single-char accelerator, styled as an accent chip (reverse-video on the highlighted row so the
  active choice pops).
- The **field name** in bold accent.
- A compact **kind tag** (`scalar` / `list` / `structured` / `bool|list` / `bool|scalar`) in a muted color, so the user
  sees what authoring the field will involve.
- The schema **description**, dimmed and truncated to fit one line.

Below the rows, a **detail strip** updates with the highlighted field and gives the picker depth (and justifies the
larger size): a header rule with the field name, the _full_ description, the schema **Example**, and — when present —
**Accepts** (the `allowed_values` hint, e.g. `true, false, or a provider list` for `skill`).

A **footer hint** line lists the accelerator keys and the navigation/confirm/ cancel keys, in the muted style used by
other modals.

### Interaction

- **Single keypress** — pressing a property's accelerator key immediately dismisses the modal with that field name (the
  existing `_on_pick` callback then calls `panel.begin_add(field)`, which opens the inline editor for scalars/lists or
  the sub-form modal for `input` / `xprompts`). This is the headline feature.
- `j` / `k` / `↑` / `↓` / `ctrl+n` / `ctrl+p` — move the highlight; the detail strip refreshes.
- `enter` — select the highlighted row (preserves current muscle memory and the existing "enter picks the first field"
  test behavior).
- `esc` / `q` — cancel (dismiss `None`); the bar returns focus to the panel.
- Any other printable key is swallowed (event barrier), exactly as `ApproveOptionsModal` does, so a stray keystroke
  can't leak through to an app command prefix while the modal is open.

### Accelerator-key assignment

Accelerators are computed deterministically from the displayed (unset) fields in canonical schema order, so they are
stable for muscle memory yet robust if `sase-core` adds fields later:

- For each field, pick the first character of its name that is not already taken and not a reserved key (`j`, `k`, `q`,
  and the nav keys); fall back to the field's remaining characters, then to digits `1`–`9`.
- The chosen character is the one highlighted in the badge.

For today's schema this yields clean mnemonics with no collisions:

| field       | key | field    | key |
| ----------- | --- | -------- | --- |
| name        | `n` | xprompts | `x` |
| description | `d` | skill    | `s` |
| tags        | `t` | snippet  | `p` |
| input       | `i` |          |     |

(`snippet` falls through `s`→`n`→`i`, all taken, to `p`.)

### Sizing & styling (`styles.tcss`)

- Widen the container (64 → ~76) and keep the established modal chrome (`align: center middle`,
  `border: thick $primary`, `background: $surface`, generous padding).
- Put the rows in a `VerticalScroll` with a sensible `max-height` so 10+ fields still scroll gracefully (today there are
  7, so no scrolling in practice).
- Highlighted row uses the accent left-border / background-tint treatment already used for highlighted option-list rows
  elsewhere in `styles.tcss`.
- Detail strip and footer use `$text-muted`; the detail header rule uses `$secondary`.
- Remove the now-unused `AddPropertyModal OptionList` rule; add rules for the new row / detail / footer widgets.

## Data plumbing

The picker needs each field's `kind`, `example`, and `allowed_values` to render the kind tag and detail strip. The panel
already holds the full descriptors (`FrontmatterPanel._schema` is `{name: _FrontmatterFieldSchema}` from
`frontmatter_field_schema()`), so it stays the single source:

- **Enrich `AddableProperty`** (`add_property_modal.py`) with `kind: str`, `example: str = ""`, and
  `allowed_values: str | None = None`, keeping `name` and `description`.
- **`FrontmatterPanel.addable_properties()`** returns the full schema descriptors for the unset fields (canonical order)
  instead of `(name, description)` tuples.
- **`_prompt_input_bar_frontmatter.py`** maps each descriptor to an `AddableProperty` when building the modal.
- The modal's public contract is otherwise unchanged: `AddPropertyModal( properties: list[AddableProperty])`, still a
  `ModalScreen[str | None]` that dismisses with the chosen field name or `None`. The bar's `_on_pick` callback is
  untouched.

## Files to change

- `src/sase/ace/tui/modals/add_property_modal.py` — rewrite as the keyed picker; enrich `AddableProperty`; add
  accelerator assignment + `on_key` + row/detail/ footer rendering. (Drop the `OptionListNavigationMixin` usage here.)
- `src/sase/ace/tui/styles.tcss` — resize/restyle `AddPropertyModal`; replace the `OptionList` rule with
  row/detail/footer rules.
- `src/sase/ace/tui/widgets/_frontmatter_panel_editing.py` — `addable_properties()` returns full descriptors.
- `src/sase/ace/tui/widgets/_prompt_input_bar_frontmatter.py` — build `AddableProperty` from the richer descriptors.

## Tests

- Update `tests/ace/tui/widgets/test_frontmatter_panel_subeditors.py` (`addable_properties()` is now descriptor objects,
  not `(name, _)` tuples).
- Keep `test_add_property_via_picker_and_edit` green: the first row is highlighted by default, so `enter` still selects
  `name`.
- Add picker tests:
  - pressing an accelerator (e.g. `t`) dismisses with that field and begins adding it (and that a structured accelerator
    like `x` opens the sub-form modal);
  - every unset field is offered with a unique accelerator, and set fields are excluded;
  - `esc` / `q` cancels and returns focus to the panel.
- Run `just check` (lint + mypy + tests). The ACE PNG snapshot suite pins TUI screens, not this modal; run
  `just test-visual` and only accept snapshot changes if a pinned screen genuinely shifts.

## Docs / config sync

- The frontmatter-panel `a` keymap and the app-level keymaps are unchanged, so `default_config.yml` and the keybinding
  footer need no edits (the new keys are modal-internal and self-documented in the footer hint).
- Re-check the `?` help popup / any panel docs for stale wording about the picker and keep them in sync if they describe
  it.

## Out of scope

- No changes to the frontmatter schema, its field set, or its text (owned by `sase-core`).
- No changes to the inline / sub-form editors the picker hands off to, nor to the `a`-on-a-sub-tree behavior (adding an
  item inside `input` / `xprompts`).
