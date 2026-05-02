---
create_time: 2026-04-25 21:14:24
status: done
prompt: sdd/prompts/202604/agents_tab_vertical_panels.md
---
# Plan: Stack dynamic tag panels vertically on the Agents tab

## Problem & motivation

Phase 3 of the dynamic-tag-panels work mounted one `AgentList` per tag (plus the static "untagged" main panel) inside
`#agent-list-container`. The container was given `layout: horizontal`, so panels render **side-by-side**. Visually this
is wrong:

- The container grows wider with every tag (each panel is fixed `width: 60`), which carves a large empty gap between the
  agent-list column and the agent-detail column on the right.
- Even with zero tag panels mounted, the `width: auto` + `min-width: 60` shape interacts oddly with the surrounding
  `#agents-content` Horizontal, producing the gap visible in the user's snapshot.
- Side-by-side panels also makes per-panel identity (which tag is which?) hard to scan because there is no per-panel
  title — you only know which panel is which by horizontal position relative to the user's mental tag ordering.

The user wants the panels **stacked vertically** in a single fixed-width left column, with the **`(untagged)` panel
always at the top** and tag panels below it in alphabetical order. This matches how the user already conceptualises the
list (untagged is the "everything else" bucket; tags are pinned-style attention buckets above/below).

The data model already orders panel keys this way (`agent_panels._panel_keys_for` returns `[None, *sorted(tags)]`), so
this fix is purely a layout/styling problem plus a small affordance — adding visible per-panel titles so vertical stacks
are legible.

## Out of scope

- Changing the panel **set** semantics (which agents go in which panel) — already correct.
- Per-tag colour customisation in the title (could be a future polish).
- Re-introducing horizontal layout as a user toggle.
- Resizable panel splits (Textual doesn't ship a splitter; not worth a custom one for this).
- Reordering tag panels by anything other than alphabetical (matches existing banner sort).
- Per-panel agent counts in the title beyond a simple `· N` suffix.

## Design

### Container shape

`#agent-list-container` becomes a vertical stack with a fixed width matching one panel.

- In `src/sase/ace/tui/app.py:236`, change `Horizontal(id="agent-list-container")` →
  `Vertical(id="agent-list-container")`. Textual's actual layout is driven by CSS, but using the matching container
  class keeps the Python read-through consistent with the styling and prevents future readers from assuming the wrong
  axis. The `Vertical` import already exists at the top of the file (used by `#agents-view`, `#agent-detail-container`,
  etc.).
- In `src/sase/ace/tui/styles.tcss:650-655`, replace:
  ```
  #agent-list-container {
      width: auto;       /* grew with N panels */
      min-width: 60;
      height: 100%;
      layout: horizontal;
  }
  ```
  with:
  ```
  #agent-list-container {
      width: 60;         /* one fixed left column, regardless of panel count */
      height: 100%;
      layout: vertical;
  }
  ```

### Per-panel width and height

Each `AgentList` becomes full-width within its column and shares vertical space equally with siblings.

- In `src/sase/ace/tui/styles.tcss:664-669`, change:
  ```
  #agent-list-container AgentList {
      width: 60;
      height: 1fr;
      border: solid $primary;
      padding: 0 1;
  }
  ```
  to:
  ```
  #agent-list-container AgentList {
      width: 100%;
      height: 1fr;
      border: solid $primary;
      padding: 0 1;
  }
  ```
- `height: 1fr` (equal split among panels) is chosen for simplicity over `height: auto` (which would size to content but
  creates fragility when one panel has 50 agents and another has 1) and over weighted heights. `OptionList` already
  scrolls internally, so a small panel just shows whitespace and a large one scrolls — fine. Tradeoff: when a user has
  many tag panels (5+), the untagged main becomes cramped. Acceptable for now; revisit if users complain.
- The `.-focused-panel` accent border (line 671-672) keeps working as-is — purely a colour swap.

### Per-panel titles

Vertically stacked panels need a visible label so the user can tell `(untagged)` from `@review` from `@inbox` without
horizontal context. Use Textual's built-in `border_title` (rendered inline on the top border of any widget with a
border).

In `src/sase/ace/tui/actions/agents/_display.py` `_refresh_panel_widgets()` (around the per-panel loop at lines 257-…),
after each panel widget is queried, set its `border_title` from the panel key:

```python
if key is None:
    widget.border_title = "(untagged)"
else:
    widget.border_title = f"@{key}"
```

Set this on every refresh, not just at mount, because a panel widget id corresponds to an **index slot** in
`_panel_widget_id`, not a fixed tag — alphabetic shifts (e.g. dismissing the only `@apple`-tagged agent) cause panel `1`
to flip from `@apple` to `@banana` without remounting. Anchoring the title to the current `panel_keys[idx]` each refresh
guarantees correctness.

Optional polish (cheap): also append `· {len(panel_agents)}` to the title, matching the existing banner-row style
(`· N agents`). Implementation: count is already computed via `agents_for_panel(...)` in the same loop. Recommended; the
extra signal helps users decide which panel to focus.

### Verification of "(untagged) on top"

`agent_panels._panel_keys_for` (`src/sase/ace/tui/models/agent_panels.py:39-53`) already returns
`[None, *sorted(distinct_tags, key=str.lower)]`. Panels mount in `panel_keys` order via the loop at
`_display.py:235-238`, which uses `_panel_widget_id(idx)` keyed by index. Vertical layout will stack children in mount
order — top to bottom — so untagged ends up on top automatically. **No code change required for ordering**; the plan
just calls this out as the load-bearing property to leave undisturbed.

### Stylesheet sweep

Quick `rg` for any other rules that target `#agent-list-container` or assume horizontal layout to make sure nothing else
references the old shape:

- `src/sase/ace/tui/styles.tcss` — confirmed only the two blocks above (650-655 and 664-673) plus the focused-panel rule
  (671-672, no axis assumption).
- No other `*.tcss` files reference these IDs.

### Plan doc update

`sase_plan_dynamic_tag_panels.md` describes side-by-side panels as the original Phase 3 design. Append a short addendum
section (e.g. `## Followup — vertical panel stack`) noting that the panels were re-stacked vertically with per-panel
border titles, and link to this plan file. Don't rewrite the historical phase descriptions.

## Files touched

| File                                                                                        | Change                                                                                                                                                                   |
| ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/sase/ace/tui/app.py` (line 236)                                                        | `Horizontal(id="agent-list-container")` → `Vertical(id="agent-list-container")`                                                                                          |
| `src/sase/ace/tui/styles.tcss` (lines 650-655, 664-669)                                     | container `layout: vertical`, `width: 60`; child panel `width: 100%`                                                                                                     |
| `src/sase/ace/tui/actions/agents/_display.py` (`_refresh_panel_widgets`, around line 257-…) | set `widget.border_title` from `key` (and optionally append agent count) on every refresh                                                                                |
| `sase_plan_dynamic_tag_panels.md` (append)                                                  | Followup section pointing to this plan                                                                                                                                   |
| `tests/ace/tui/` (new file `test_agent_panel_titles.py` OR extend an existing test)         | one Textual `pilot`-driven test that mounts the agents view with both untagged and tagged agents and asserts each panel's `border_title` matches `(untagged)` / `@<tag>` |

## Tests

- **Unit test (lightweight)**: existing `tests/ace/tui/test_agent_jk_navigation.py` already mounts the app with mixed
  tagged/untagged agents and walks `J`/`K`. Add a parallel small test (or a new assertion in the existing test) that,
  after the initial refresh, queries each mounted `AgentList` widget and asserts:
  - The first widget is `agent-list-panel` (untagged main) with `border_title == "(untagged)"`.
  - Subsequent widgets are `agent-list-panel-1`, `-2`, … with `border_title == f"@{tag}"` in alphabetical order.
  - If we add the `· N` suffix, assert it too.
- **No layout snapshot test**: there is no Textual snapshot infrastructure in this repo. Don't introduce one for this
  fix.
- **Manual verification**: run `sase ace`, tag at least two agents with distinct tags via
  `sase agents tag set -n <name> -t <tag>` (or launch with `%tag:foo`), confirm:
  1. Left column is one fixed-width vertical stack — no big gap between left and right columns.
  2. `(untagged)` panel is on top.
  3. Tag panels are alphabetically ordered below it.
  4. Border titles read correctly.
  5. `J`/`K` cycles focus down/up the stack with the focused panel highlighted by accent border.
  6. `j`/`k` still moves the cursor inside the focused panel.
  7. Killing the last agent of a tag removes that panel; focus falls back to untagged.
- **`just check`**: run before terminating, per `memory/short/build_and_run.md`. If running from an ephemeral `sase_<N>`
  workspace, run `just install` first.

## Risks

- **Vertical fairness with many tags**: 5+ tag panels makes each panel ~6-8 rows tall on a typical 50-row terminal,
  which is cramped for the untagged main panel. Mitigation: accept for now; if it becomes a problem, switch to
  `height: auto` + `max-height: 50%` for tag panels and `height: 1fr` for untagged. Document the followup but don't
  pre-build it.
- **`border_title` overflow on long tag names**: long tags get clipped by Textual automatically. Acceptable; sase tag
  names are validated by `validate_tag_name` to a reasonable shape.
- **Test fragility**: Textual `pilot` tests can be flaky around mount timing. Use `await pilot.pause()` between mount
  and assertion, mirroring the pattern in `test_agent_jk_navigation.py`.
