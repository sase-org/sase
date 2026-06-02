---
create_time: 2026-06-02 13:39:53
status: done
prompt: sdd/prompts/202606/project_select_filter_popup.md
---
# Plan: Beautiful filterable pop-up for the `@` project picker

## Context & motivating discovery

Pressing `@` in the `sase ace` TUI runs `action_start_custom_agent`
(`src/sase/ace/tui/actions/agent_workflow/_entry_points.py:341`), which pushes `ProjectSelectModal`
(`src/sase/ace/tui/modals/project_select_modal.py`). The modal lists launchable projects (`[P]`), active ChangeSpecs
(`[C]`), and optionally an `[*] ALL` entry, then returns the chosen item to launch a custom agent.

While scoping this work I found that the premise is slightly off from reality, and it's worth stating up front:

- **A filter input already exists.** The modal already composes a `FilterInput` with a live, case-insensitive substring
  filter (`_get_filtered_items`, `on_input_changed`). Typing already narrows the list, and an unmatched query can be
  submitted as a custom CL name.
- **The real defect is styling/layout.** `ProjectSelectModal` has **no CSS whatsoever** — no `DEFAULT_CSS`, and no rule
  block in `src/sase/ace/tui/styles.tcss`. Its bare `Container()` therefore stretches to fill the entire `ModalScreen`,
  so the panel **takes over the whole screen**. The filter bar reads as an afterthought because it has no hint text, no
  result count, no empty-state, and no footer.

Every other filterable modal in this codebase (`CommandPaletteModal`, `XPromptSelectModal`, `PromptHistoryModal`, …) is
already a compact, centered, bordered pop-up with a styled title, a prominent filter, a hint line, an empty-state, and a
footer of key hints. `ProjectSelectModal` is the one picker that never received that treatment.

**So this task is: make the `@` panel a beautiful, compact, centered pop-up and promote its existing filter into a
first-class, obvious filter bar** — matching the `CommandPaletteModal` gold standard — rather than wiring up filtering
from scratch.

## Goals

1. The `@` panel is a **centered pop-up** that does not fill the screen: fixed sensible width, height that grows with
   content up to a cap, with a border and surface background consistent with the other modals.
2. The **filter bar is prominent and beautiful**: a clearly styled input with an icon'd title above it, helper hint text
   below it, and a live match count.
3. **Filtering feels polished**: live narrowing as you type (already works), plus a graceful empty-state that also hints
   you can press Enter to use the typed text as a custom name (the modal already supports this).
4. No regressions to existing behavior: project/CL/ALL/home selection, custom name fallback, `Ctrl+G` (select & edit),
   `Ctrl+D` (delete project), Enter on highlighted item, and arrow / `Ctrl+N`/`Ctrl+P` navigation while the filter has
   focus.

## Non-goals

- Changing what `@` does or its keymap (already bound; no `default_config.yml` change).
- Changing the project/CL data sources (`list_launchable_projects`, `find_all_changespecs`).
- Reworking the downstream agent-launch flow in `_entry_points.py`.
- Fuzzy/scored ranking. The current substring filter is adequate; I will keep it (optionally promoting prefix matches
  visually is a possible nice-to-have but is out of scope unless trivial).

## Backend boundary check (Rust core)

Per `memory/short/rust_core_backend_boundary.md`: filtering text in a UI filter bar and the modal's layout/styling are
**presentation-only** concerns. The project/CL list source already exists and is unchanged. No `sase-core` wire/API or
binding change is required; all changes stay in this repo's TUI layer.

## Design (I'm leading this)

Model the layout and styling on `CommandPaletteModal` (`src/sase/ace/tui/modals/command_palette_modal.py` + its
`styles.tcss` block at `CommandPaletteModal …`), which is the cleanest filterable-popup reference.

Composed structure (top to bottom) inside a single id'd `Container`:

1. **Title** (`Static`): icon + label, centered, e.g. `✦ Select Project or CL`, with a subtle live match count appended
   (e.g. `✦ Select Project or CL · 12 matches`). The count updates on every keystroke.
2. **Filter bar** (`FilterInput`, full width): placeholder `Type to filter projects & CLs…`. Reuses the existing
   `FilterInput` (readline `Ctrl+F`/`Ctrl+B` bindings).
3. **Hint line** (`Static`, muted): `Enter launch · ↑/↓ move · type a new name to create a custom CL`.
4. **Option list** (`OptionList`): the existing color-coded rows (`[*]` magenta, `[H]` gold, `[P]` cyan, `[C]` green).
   `height: auto` with a `max-height` cap so short lists stay compact and long lists scroll, with a solid `$secondary`
   border and stable scrollbar gutter.
5. **Empty-state** (`Static`, hidden unless no matches): e.g.
   `No matching projects — press Enter to use “<query>” as a custom name`. Toggle its visibility against the option list
   exactly like `CommandPaletteModal._refresh_empty_visibility`.
6. **Footer** (`Static`, muted, centered): key hints `Enter launch · ^G edit · ^D delete · Esc close`.

Pop-up sizing (in `styles.tcss`, new `ProjectSelectModal` block):

- `ProjectSelectModal { align: center middle; }`
- Container: `width: 64` (≈ wide enough for project + status labels) with a `max-width` guard, `height: auto`,
  `max-height: 80%`, `border: double $primary`, `background: $surface`, `padding: 1 2`. (Final numbers tuned against the
  visual snapshot for balance.)
- Per-child rules for title (centered, `margin-bottom`), filter input (`width: 100%`), hint (muted, height 1), list
  (`height: auto; max-height: N`, solid `$secondary` border), empty-state (centered, muted, mirrors list box), footer
  (centered, muted, `margin-top: 1`).

Behavioral polish:

- On `on_input_changed`: rebuild filtered options (existing), then update the title match count and toggle the
  empty-state — reusing the `_refresh_empty_visibility` pattern.
- Highlight the first option after each filter change so Enter targets the top match (matches command-palette feel).
- Keep navigation working while the filter is focused: arrows and `Ctrl+N`/`Ctrl+P` already route through
  `OptionListNavigationMixin`. If needed, add a small `on_key` forwarder for arrows like `CommandPaletteModal` so list
  movement is reliable while typing. (Note: `j`/`k`/`q` nav bindings from the mixin are inert while the text input is
  focused — they are typed as filter text, which is the desired behavior for a filter-first modal; no change needed, but
  I'll verify and document this.)

## Files to change

1. `src/sase/ace/tui/modals/project_select_modal.py`
   - Restructure `compose()` to add the id'd container, icon'd title `Static`, hint `Static`, empty-state `Static`, and
     footer `Static` around the existing `FilterInput` + `OptionList`.
   - Add helpers: `_build_title(count)`, `_build_empty_state(query)`, `_refresh_empty_visibility()`, and a small
     `_apply_filter` consolidation so `on_input_changed`, delete-refresh, and mount share one code path.
   - Set `highlighted = 0` after each filter rebuild.
   - Optional `on_key` arrow forwarder if verification shows it's needed.
2. `src/sase/ace/tui/styles.tcss`
   - New `ProjectSelectModal` rule block (center alignment + compact container + per-child styling) placed alongside the
     other modal blocks.
3. `tests/ace/tui/modals/test_project_select_modal.py`
   - Extend with assertions for the new behavior that don't need rendering: empty-state visibility toggles with no
     matches, match-count text updates, first-option highlight after filtering. Keep existing data-loading tests green.
4. `tests/ace/tui/visual/test_ace_png_snapshots_project_select.py` (new)
   - PNG snapshot test mirroring `test_ace_png_snapshots_projects.py`: patch the startup loaders +
     `list_launchable_projects`/`find_all_changespecs` with deterministic fixtures, push `ProjectSelectModal`,
     `wait_for_visual_idle`, and snapshot (a) the default unfiltered pop-up and (b) a filtered state (after typing a
     query) to lock in the compact layout and filter bar. Generate goldens with `--sase-update-visual-snapshots`.

## Help / docs sync

The `@` action, its keymap, and its behavior are unchanged, so the `?` help modal should not need edits. I will grep
`help_modal.py` for any description of the custom-agent picker and update wording only if it describes the panel's
appearance; otherwise no change.

## Testing & verification

- `just install` first (ephemeral workspace), then implement.
- `just check` (lint + mypy + fast tests) — required by repo rules after file changes.
- `just test-visual` for the new PNG snapshot(s); inspect `.pytest_cache/sase-visual/` artifacts on any diff and only
  accept intentional changes via `--sase-update-visual-snapshots`.
- Manual smoke (optional, via the `run`/`verify` flow): launch the TUI, press `@`, confirm the panel is a centered
  compact pop-up, typing narrows the list live, the count updates, the empty-state shows for no matches, and
  Enter/`^G`/`^D`/Esc all still behave.

## Risks & mitigations

- **Visual snapshot determinism**: follow the existing projects-snapshot harness (patched loaders, fixed fixtures,
  fontconfig/Fira pinning) so renders are deterministic; CI's small ratio tolerance covers renderer drift.
- **Sizing across terminal widths**: use `%`-based `max-width`/`max-height` caps with a fixed base width, matching
  sibling modals, so it stays a pop-up on small and large terminals alike.
- **Navigation-while-typing edge cases**: verify arrow/`Ctrl+N`/`Ctrl+P` behavior with the filter focused; add the
  `on_key` forwarder only if a gap is found.
