---
create_time: 2026-06-29 12:59:10
status: done
prompt: sdd/prompts/202606/neighbor_keymap_includes_ancestors.md
---
# Plan: Make the `~` (neighbors) keymap include ancestors of the selected agent

## Goal / product context

On the Agents tab of `sase ace`, the `~` keymap ("neighbor / descendant" navigation) lets the user jump between agents
related to the currently selected agent. Today it offers two kinds of related agents:

- **Neighbors** — visible agents in the same _hood_ (the immediate dotted namespace). For `0aa.cld.f1` the hood is
  `0aa.cld`, so neighbors are other `0aa.cld.*` rows.
- **Descendants** — visible agents nested under the selected name (`0aa.cld.f1.*`), plus a "revive" affordance for
  dismissed descendants.

What is missing is the ability to navigate **upward** to a parent/ancestor. From `0aa.cld.f1` there is currently no way
to reach its parent `0aa.cld` via `~`, even when `0aa.cld` is visible on screen. The parent is neither a neighbor (its
hood is `0aa`, not `0aa.cld`) nor a descendant.

**This change adds ancestors as a third class of `~` navigation target.** With it, selecting `0aa.cld.f1` and pressing
`~` will offer `0aa.cld` (the direct parent) and any other visible ancestor row (e.g. an agent literally named `0aa`),
so the user can jump up the dotted-name tree just as easily as they jump sideways (neighbors) or down (descendants).

### Motivating example

With `0aa.cld.f1` selected (running) while `0aa.cld` is visible in the "Done" group (see the screenshot the user
referenced), pressing `~` should let the user jump to `0aa.cld`. If `0aa.cld` is the only related agent, `~` jumps
straight to it; otherwise it appears in the chooser modal under a new "Ancestors" section.

## Definitions

- **Ancestor of agent `N`**: a visible agent row whose `agent_name` `A` is a strict dotted-name prefix of `N` — i.e.
  `N.casefold().startswith(A.casefold()
  - ".")`. This is the mirror image of the existing `is_agent_descendant` helper.
- Ancestors are independent of the _hood_ concept. Unlike hoods (which require the name to be dotted), a **dotless**
  name such as `0aa` is a perfectly valid ancestor of `0aa.cld.f1`. The ancestor computation must therefore rely only on
  dotted-prefix matching, never on `agent_hood()`.
- **Ordering**: nearest-first (direct parent, then grandparent, …). This puts the most-likely target (`0aa.cld`) at the
  top of the list and as the default-highlighted modal row.

## Scope decisions (please confirm at review)

1. **All visible ancestors, not just the direct parent.** The request says "parents" (plural) and this is symmetric with
   descendants (which already span all depths). The chooser modal makes picking among multiple ancestors trivial, and
   the single-ancestor case still jumps directly. _Alternative considered:_ direct-parent-only. If you prefer that, the
   index can simply return only the longest matching prefix.

2. **Visible ancestors only — no "revive dismissed ancestor" affordance.** Descendants support reviving a dismissed
   child because users routinely spawn and dismiss children. Reviving a dismissed _ancestor_ is a much rarer need, so V1
   keeps ancestors to currently-visible rows to limit scope. (Dismissed- ancestor revive could be a follow-up.)

3. **Modal section order: Ancestors → Descendants → Neighbors.** Prepend the new "Ancestors" section above the existing
   two (whose relative order is left unchanged). This surfaces the motivating parent-jump at the top and makes the
   nearest ancestor the default-highlighted row. _Note:_ for an agent that has both ancestors and descendants, this
   changes which row is auto-highlighted when the modal opens (previously the first descendant; now the nearest
   ancestor). This is intentional given the feature's purpose. _Alternative:_ tree-natural top-down order Ancestors →
   Neighbors → Descendants.

## Architecture / boundary note (Rust core)

Per the repo's "Rust Core Backend Boundary" rule, shared domain behavior belongs in `../sase-core`. However, the
existing neighbor/descendant logic (`AgentNeighborIndex`, `agent_hood`, `is_agent_descendant`) already lives entirely in
the Python TUI layer (`src/sase/ace/tui/models/agent_hoods.py`) because it operates on **currently-rendered,
render-ordered, fold/panel-aware visible rows** — presentation state, not portable domain state. No other frontend
consumes this navigation. Ancestor navigation is the exact same shape of logic, so it will live alongside the existing
code in the Python TUI layer to match the established pattern. Flagging this explicitly in case you want it pushed into
`sase-core` instead; if so, the dotted-name prefix predicate (not the visible-row indexing) would be the portable piece.

## Implementation outline

### 1. Core index — `src/sase/ace/tui/models/agent_hoods.py`

- Add an `_ancestors_by_global_idx: dict[int, tuple[int, ...]]` field to `AgentNeighborIndex`.
- In `AgentNeighborIndex.from_visible_rows`, after the descendant computation, build ancestors for each visible agent by
  enumerating its dotted prefixes (`".".join(parts[:k])` for `k` in `1 .. len(parts)-1`) and resolving each prefix that
  corresponds to a visible agent name to its global index, ordered nearest-first (longest prefix first). Build the
  lookup from the already- computed `name_by_global_idx` (a `name -> global_idx` map; defensively handle the unlikely
  case of duplicate visible names).
- Add query methods `ancestors_for(global_idx) -> tuple[int, ...]` and `ancestor_count(global_idx) -> int`, mirroring
  `descendants_for` / `descendant_count`.
- Optionally add an `is_agent_ancestor(candidate, name)` convenience predicate for symmetry/readability (or simply reuse
  `is_agent_descendant(name, candidate)`).
- An agent must never be its own ancestor (strict prefix only).

Caching: the existing `_agent_neighbor_index` cache key (agents identity, panel keys, grouping mode, fold version,
dismiss epoch) already captures every input that affects visible rows, so no cache-key change is needed — the ancestor
data is computed as part of the same index build and recomputes when folding/panels change.

### 2. Action handler — `src/sase/ace/tui/actions/agents/_neighbors.py`

- In `_start_agent_neighbor_navigation`: fetch `ancestors = index.ancestors_for(self.current_idx)`. Include ancestors in
  the "nothing-to-do" early return, in `related_count`, and in the single-target fast-path (when exactly one related
  agent exists, jump straight to it whether it is an ancestor, descendant, or neighbor).
- Pass `ancestors` into `_agent_neighbor_choices` and build ancestor choices there with `group="ancestor"`, prepended
  before descendants so quick-select letters (`a`, `b`, …) match the modal's top-to-bottom reading order. Reuse the
  existing `_agent_neighbor_panel_label` and `_agent_neighbor_time_hint` helpers.

### 3. Chooser modal — `src/sase/ace/tui/modals/agent_neighbor_modal.py`

- `AgentNeighborChoice.group` is already a free-form string; `"ancestor"` is a new value requiring no schema change.
- In `_create_options`, render an "Ancestors" section (via `_agent_neighbor_header_text("Ancestors")`) before the
  Descendants and Neighbors sections.
- In `_title_text`, include the ancestor count in the bracketed summary (e.g.
  `[1 ancestor - 2 descendants - 3 neighbors]`).

### 4. Footer label + info-panel badge count — `src/sase/ace/tui/actions/agents/_display_detail.py`

- `_selected_agent_neighbor_count` currently returns `neighbor_count + descendant_count`; add
  `+ index.ancestor_count(...)` so the `~` footer binding and the info-panel "neighbors: N" badge correctly appear/scale
  when ancestors are reachable (e.g. a leaf agent whose only related row is its parent). The generic footer/badge
  wording ("neighbors") is left unchanged since the count is already a combined related-agents total.

### 5. Help text — `src/sase/ace/tui/modals/help_modal/agents_bindings.py`

- Update the `start_sibling_mode` description from "Jump to neighbor / descendant agent" to also mention ancestors (e.g.
  "Jump to ancestor / neighbor / descendant"). Verify the wording fits the help-modal formatting constraints noted in
  `src/sase/ace/AGENTS.md` (help popup must stay in sync; box-width/description-length rules) and adjust phrasing if
  needed.
- Confirm no other `?`-help / popup prose describes the `~` key; update any that does.

### 6. Tests

- `tests/ace/tui/models/test_agent_neighbors.py`: add coverage for `ancestors_for` / `ancestor_count` — nearest-first
  ordering, dotless-ancestor inclusion (`0aa` is an ancestor of `0aa.cld.f1`), case-insensitivity, exclusion of
  non-rendered rows, the motivating chain (`0aa` / `0aa.cld` / `0aa.cld.f1`), and that an agent is not its own ancestor.
- `tests/ace/tui/test_agent_neighbor_navigation.py`: add behavior coverage — single visible ancestor triggers a direct
  jump; multiple related agents open the modal with an "Ancestors" section; cross-status-group jump works (the
  motivating case where the parent sits in "Done" while the child is "Running"); and `_selected_agent_neighbor_count`
  reflects ancestors so the footer/badge surface `~`.

## Edge cases & correctness

- **Strict ancestry**: an agent is never its own ancestor.
- **Dotless ancestors** (`0aa`) are valid targets; ancestor logic must not route through `agent_hood()` (which rejects
  dotless names).
- **Visibility**: only currently-rendered rows are ancestor targets, matching the descendant behavior. A parent folded
  away under a collapsed group simply is not offered until it becomes visible; the index rebuilds on fold/panel changes.
- **Cross-group jumps**: the motivating scenario crosses status groups (child in "Running", parent in "Done"). The
  existing `_focus_agent_neighbor_by_global_index` already handles cross-panel/cross-group jumps via `panel_idx` +
  global index, so ancestors get this for free.
- **Performance**: ancestor build is `O(visible_rows × dotted-depth)` with O(1) prefix lookups, done once per (cached)
  index build; depth is small. Keep the build allocation-light. Review `memory/tui_perf.md` before touching the index
  build path.

## Out of scope

- Reviving dismissed ancestors (see scope decision #2).
- Any change to ChangeSpec-tab ancestor/sibling navigation (`<` / `>` / `~` on the ChangeSpecs tab) — this plan only
  touches Agents-tab `~`.
- Pushing dotted-name ancestry into `sase-core` (see boundary note).

## Verification

- `just install` then `just check` (lint + mypy + tests) from the workspace.
- Targeted: the two neighbor test modules above, plus the visual snapshot suite if the modal/footer rendering changes
  goldens (`just test-visual`; accept intentional changes only via `--sase-update-visual-snapshots`).
- Manual smoke in `sase ace`: select a deep agent (`*.cld.f1`) and confirm `~` offers and jumps to its visible parent.
