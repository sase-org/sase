---
create_time: 2026-04-25 21:10:01
status: done
prompt: sdd/prompts/202604/agents_tab_group_separators.md
---
# Agents Tab — Group Separator Redesign

## Goal

Redesign the group banners on the **Agents** tab of `sase ace` so that groups feel like distinct, visually-cohesive
sections instead of just rows that happen to contain a horizontal rule. The current banners do their job but are
visually flat: an L0 (project) banner is a single thin em-dash rule in sky blue, an L1 (name-root) banner is a
`· label ·` row in muted gray, and there is **zero whitespace** between groups. As soon as a project has more than a
handful of agents — or the screen has more than one project — it becomes hard to see at a glance where one group ends
and the next begins.

The redesign should:

1. Make it instantly obvious where a project group starts and ends.
2. Make it instantly obvious which name-root subgroup an agent belongs to (especially when subgroups are short — e.g.
   one agent per subgroup is common).
3. Establish a clear visual hierarchy: L0 banners feel "heavier" than L1 banners, and L1 banners feel like they nest
   inside L0.
4. Stay aesthetically restrained — the Agents tab is information-dense, so banners should anchor the eye, not dominate
   it.

## Current State (for reference)

- File: `src/sase/ace/tui/widgets/_agent_list_rendering.py` → `format_banner_option()` (lines 281–336).
- L0 row: `── <project> · <changespec> <chip> ─────────────` (bold sky blue, em-dash `─`).
- L1 row: `· <name-root> · <chip>                       ` (muted gray dots + spaces).
- Styling constants: `src/sase/ace/tui/widgets/_agent_list_styling.py`.
- Width contract: every row (agent, attempt, banner) is right-padded to the same `target_width` so the right-aligned
  runtime/timestamp suffix on agent rows lines up. Banners must keep honoring this width.
- Grouping model is in `src/sase/ace/tui/models/agent_groups.py` and is unchanged by this work.

## Design

The redesign has three pillars: **breathing room**, **a heavyweight L0 banner with a chip on the right**, and **a
nested-feel L1 banner with a tree-junction glyph**.

### 1. Breathing room (the single biggest win)

Insert a **blank spacer row** before each L0 banner _except the first_. This is the cheapest, most impactful change — it
gives every project group its own block of vertical space and immediately makes the transition between projects
unmistakable.

Spacer rows are rendered as a disabled, empty `Option` so they don't catch focus and don't break j/k navigation. They
count as a "row" in the list but are visually invisible.

No spacer between L1 banners (within the same project). The L0 spacer is load-bearing; sprinkling spacers inside a
project would dilute the hierarchy.

### 2. L0 (project) banner — heavyweight, chip on the right

**Format:**

```
▌ <project> · <changespec>  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5 agents · 2 done
```

Components, left to right:

- `▌` (U+258C, left half-block) in **bold sky blue**. This solid colored bar at the very left edge is the new visual
  anchor: it instantly reads as "new section" and harmonizes with the right-aligned agent suffixes that already use the
  rightmost column.
- A space, then the **project label** (bold sky blue) in the existing `<project> · <changespec>` form.
- Two spaces.
- Heavy rule `━` (U+2501, BOX DRAWINGS HEAVY HORIZONTAL) in **dim sky blue**, filling all remaining horizontal space up
  to the chip.
- Two spaces.
- The summary **chip** (e.g. `5 agents · 2 done`) right-aligned to the same column the runtime suffix uses on agent
  rows. Style: dim sky blue.

Why heavy rule (`━`) instead of the existing light rule (`─`)? It gives L0 a real weight difference vs L1, which still
uses `─`. Without that, L0 and L1 read at roughly the same density.

Why move the chip to the right? Two reasons. First, it mirrors the agent rows' right-aligned runtime suffix, so the eye
picks up a vertical "stats column" running down the right side of the screen — a strong visual through-line. Second, it
lets the rule run continuously between the label and the chip, which makes the banner feel like a single unit rather
than label + chip + filler.

### 3. L1 (name-root) banner — nested, tree-junction feel

**Format:**

```
  ╭─ <name-root> ─────────────────────────────────────  3 done
```

Components:

- **2-space indent**. This is the tell that L1 nests inside L0; it also visually links the L1 banners under the same
  project together.
- `╭─` (U+256D U+2500, BOX DRAWINGS LIGHT ARC DOWN AND RIGHT + LIGHT HORIZONTAL) — the rounded "branch" glyph reads as
  "a subgroup starts here," echoing tree views in modern TUIs.
- Space, then the **name-root label** in **bold teal** (existing `_NAME_ROOT_BANNER_LABEL_STYLE`).
- Space, then a light rule `─` (U+2500) in **muted gray**, filling remaining horizontal space.
- Two spaces.
- Subgroup chip, right-aligned, in muted gray.

If the project has only a single L1 subgroup (and no singletons), we still render the L1 banner — consistency wins. The
grouping logic already suppresses L1 banners when the name-root is empty (singletons), which is the right behavior.

### 4. Color & style refinements

- L0 marker glyph (`▌`) and label keep the existing sky blue (`#5FAFFF`), bold.
- L0 rule and chip become a **dimmer** sky blue (e.g. add `dim` to the same color) so the label is the brightest element
  of the banner.
- L1 label keeps its bold teal (`#87D7AF`).
- L1 branch glyph (`╭─`), rule, and chip use the existing dim gray (`#AFAFAF`).
- All new style strings live in `_agent_list_styling.py` next to the current banner styles, so a future theme/palette
  change touches one file.

### 5. Visual mockup (full screen excerpt)

```
▌ sase_102 · master  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6 agents · 3 done
  ╭─ planner ─────────────────────────────────────────────────────  1 done
    planner.1                                              12s · 03:14
  ╭─ coder ───────────────────────────────────────────────────────  2 done
    coder.1                                                33s · 03:18
    coder.2                                                 5m · 03:22
    coder.3 ⚡                                                running
                                                                          ← spacer
▌ retired Mercurial plugin · feature/provider-skills  ━━━━━━━━━━━━━━━━  3 agents · 0 done
  ╭─ planner ─────────────────────────────────────────────────────  0 done
    planner.1                                                running
  ╭─ coder ───────────────────────────────────────────────────────  0 done
    coder.1                                                  3s · 03:25
    coder.2                                                  1s · 03:25
                                                                          ← spacer
▌ (no project)  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2 agents · 1 done
    quick_check.1                                          22s · 03:10
    quick_check.2 ✘                                        18s · 03:09
```

The colored half-block bars on the left form a strong vertical anchor list of "where projects begin," the rounded
branches step inward to show nesting, and the right-aligned chips line up with the agent runtime column.

## Implementation Outline

All changes are confined to the agent list widget; the data model, the grouping logic, and the surrounding tab plumbing
are untouched.

1. **`_agent_list_styling.py`** — add a small handful of new style constants:
   - `_PROJECT_BANNER_BAR_STYLE` (bold sky blue, used for the `▌` glyph and the label).
   - `_PROJECT_BANNER_RULE_STYLE` (dim sky blue, used for the `━` rule and the chip).
   - `_NAME_ROOT_BANNER_BRANCH_STYLE` (dim gray, used for `╭─` and the trailing rule).
   - Constants for the new glyphs themselves (`_PROJECT_BAR_GLYPH`, `_NAME_ROOT_BRANCH_GLYPH`, `_PROJECT_RULE`,
     `_NAME_ROOT_RULE`, `_NAME_ROOT_INDENT`).

2. **`_agent_list_rendering.py` → `format_banner_option()`** — rewrite the body to emit the new layouts. Both levels now
   share the same shape: `<prefix><label><space><rule…><space><chip>`. The chip-on-the-right pattern means the function
   should compute `pad_len = max(2, width − prefix_len − label_len − chip_len − 4)` (the `4` accounts for the two
   single-space gaps around the rule) and emit: `prefix + " " + label + " " + rule * pad_len + "  " + chip`. When the
   chip is empty, fall back to filling the trailing space with rule. Both L0 and L1 follow this contract; only the
   glyphs and styles differ.

3. **`agent_list.py`** (or whichever helper composes the row stream) — when assembling the `_row_entries` list, inject a
   disabled spacer `Option` before each L0 banner index that isn't 0. The spacer row needs a unique non-selectable id
   (e.g. `spacer:<sequence>`) and an empty `Text`. Verify j/k navigation skips it because it's disabled.

4. **Width calculation** — banners already participate in `target_width` computation. Confirm that the new
   chip-on-the-right banners contribute to `max_left` / `max_suffix` correctly: a banner now has a "left side" ending at
   the rule and a "right side" of the chip. The cleanest way is to render banners through `assemble_padded_option()`
   like agent rows already do, treating the chip as the suffix; this keeps right-alignment logic in exactly one place.

5. **Tests** — there's existing coverage of `format_banner_option` (search `format_banner_option` under `tests/`).
   Update assertions for the new prefix glyphs, chip-on-the-right layout, and verify the spacer row injection at the
   row-stream level. Add a snapshot-style test that renders a small fixture (two projects, three subgroups each) and
   asserts the expected sequence of banner / spacer / agent rows.

## Edge Cases

- **First L0 banner**: no spacer row above it (top of list shouldn't have a leading blank).
- **`(no project)` group**: same heavyweight L0 treatment; the literal label `(no project)` reads cleanly with the new
  format.
- **Empty name-root (singletons)**: no L1 banner, as today. Singletons appear directly under the L0 banner with their
  existing indentation.
- **Workflow children**: unchanged; they continue to indent under their parent agent row (`_CHILD_INDENT = "  └─ "`).
  They do not interact with banner styling.
- **Narrow terminals**: `_MIN_BANNER_WIDTH = 40` still applies. The new format degrades gracefully because the rule
  shrinks first; if the terminal is too narrow for label + chip + at least 2 rule chars, the rule disappears but the
  label and chip still render.
- **Selection / focus**: banners remain non-selectable disabled options (this is already the case). Spacer rows are also
  disabled.

## Out of Scope

- Changing the grouping logic itself (what defines a project group or a name-root subgroup). The redesign is pure
  presentation.
- Restyling the agent rows themselves (icons, runtime suffix, child indent prefix). They keep their current look.
- Restyling other tabs (ChangeSpecs, etc.) or other in-app dividers (prompt panel attempt dividers, dashboard
  separators). Those use their own conventions and aren't part of this change.
- Theming / user-configurable colors. The new constants live in the same single file as the existing ones, ready for a
  future theme pass.
