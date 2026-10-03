---
keyword: Deck Panel
aliases:
  - deck layout
---

A deck panel is one Agents-tab detail region that shows one agent data deck. The Agents
tab shows one to three deck panels: one panel, two in a stacked split (`\`, one above
the other) or a side-by-side split (`|`, side by side), or four three-pane T shapes with
a full-span main panel, following vim's split naming. One split-key rule governs them
all: `\` draws a stacked divider and `|` a side-by-side divider; if that kind of divider
already spans the whole area, the key erases it and the side you are on grows to fill
the space; otherwise, with fewer than three panels, the key draws the divider through
the focused panel; with three panels, the key turns the layout. `Ctrl+F` / `Ctrl+B` move
the logical focus that deck, card, scroll, search, and fold keys act on, `Ctrl+Shift+F`
/ `Ctrl+Shift+B` (aliases `>` / `<`) swap the focused panel's session with the next /
previous panel, `Ctrl+Shift+D` (alias `Ctrl+X`) closes the focused panel, `Ctrl+T` turns
the layout, and `Z` zooms the focused deck panel in place. The identity header and the
jump panel span every deck panel and belong to none.
