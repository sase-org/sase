---
create_time: 2026-04-25 18:00:00
status: draft
prompt: sdd/prompts/202604/name_root_banner_color.md
---

# Plan: Distinct Color for the Name-Root in Level-2 Group Banners

## Goal

In the Agents tab of `sase ace`, the level-2 (deepest) nested-group banner currently renders the name-root surrounded by
dim center-dot decorators, and the whole row is drawn in a single dim muted-gray style:

```
· coder ·                                                                  3 agents
```

We want the bare agent-name portion (the `coder` text — i.e. the value returned by `banner_label()` for an `L2`
`GroupRow`) to **visually stand out** with a distinct color, while the surrounding `·` decorators, the trailing summary
chip, and the padding all remain in their current dim gray. This makes it easier to scan for a specific agent name when
the user has many name-root groups visible inside a single project.

The change is purely cosmetic — no new behavior, no new keymap, no data model changes. It is a small follow-up to the
nested-groups feature documented in `plans/202604/agents_tab_nested_groups.md`.

## Non-goals

- Do **not** touch the L0 (tag) or L1 (project) banner styling — they already have distinct, prominent accent colors
  (`#FFAF00` warm yellow / `#5FAFFF` sky blue) and adding a third strong accent at L2 would flatten the visual
  hierarchy. The decorator/rule for L2 stays dim by design; only the name itself gets the accent.
- Do not change the banner shape (`· root ·`), padding, summary chip layout, or the `selectable` flag handling.
- Do not change which color L0/L1 banners use, including their bold modifier.
- Do not introduce a per-tag or per-project color for L2; the same accent applies to every name-root banner.

## Where the change lands

The render path is already small and well-isolated:

1. **`src/sase/ace/tui/widgets/_agent_list_styling.py`** — defines `_NAME_ROOT_BANNER_STYLE = "dim #AFAFAF"`. We add a
   new sibling constant for the name-root accent.
2. **`src/sase/ace/tui/widgets/_agent_list_rendering.py`** — `format_banner_option()` builds a single `Text` and
   currently appends `head_text = f"· {label} ·"` with one uniform style. We split the L2 branch into three appends (dim
   decorator, accent name, dim decorator) so the colorization only affects the label.

No other files in the rendering pipeline need to change. `banner_label()`, `compute_banner_summary()`,
`banner_summary_text()`, and the OptionList integration in `agent_list.py` all stay intact.

## Visual design

- **Constant name**: `_NAME_ROOT_BANNER_LABEL_STYLE` — naming follows the existing `_*_BANNER_STYLE` convention, with
  the `_LABEL_` qualifier signalling "applies to the text inside the banner, not the rule itself". Keeping
  `_NAME_ROOT_BANNER_STYLE` (dim gray) as the rule/chip style preserves the existing call sites.
- **Color choice**: `bold #87D7AF` (soft mint green).
  - Distinct from the L0 yellow and L1 blue accents already in use.
  - Distinct from the existing tag-badge sky blue (`#5FAFFF`), the agent-name-annotation gold (`#FFD700`), and the
    attempt-label orange (`#FF8700`) so we don't create a "two things in the same color" confusion when scanning a row.
  - Still readable against a default terminal background and clearly separates from the dim gray decorators on either
    side without competing with the heavier L0/L1 accents — this respects the "rule weight + color" hierarchy described
    in `agents_tab_nested_groups.md` (heavy double rule → single rule → dim center-dot rule).
  - `bold` makes the name pop further despite being a smaller character span than the L0/L1 labels.
  - If reviewers prefer a different hue (e.g. `#87D7D7` soft cyan or `#D7AFFF` soft lavender — the latter is already
    used for `parallel` step type, so cyan is the better fallback), the only edit is the constant value.

## Rendering change

In `format_banner_option()` the L2 branch becomes a multi-segment append. The L0/L1 branches stay single-segment as
today.

```python
elif group.level == 2:
    rule = " "
    chip_text = f"{chip} " if chip else ""
    decor_left = "· "
    decor_right = " ·"
    pad_len = max(
        0,
        width - len(decor_left) - len(label) - len(decor_right) - len(chip_text),
    )
    text = Text()
    text.append(decor_left, style=_NAME_ROOT_BANNER_STYLE)
    text.append(label, style=_NAME_ROOT_BANNER_LABEL_STYLE)
    text.append(decor_right, style=_NAME_ROOT_BANNER_STYLE)
    if chip_text:
        text.append(chip_text, style=_NAME_ROOT_BANNER_STYLE)
    text.append(rule * pad_len, style=_NAME_ROOT_BANNER_STYLE)
    return Option(
        text,
        id=f"group:{sequence}:{group.level}:{'/'.join(group.group_key)}",
        disabled=not selectable,
    )
```

The L0/L1 paths keep their current single-pass `text.append(head_text, style=...)` form; we factor just enough to keep
them readable but do not rework them. (If the resulting branching feels duplicative, fold the L0/L1 paths into a small
inline helper — explicitly out of scope is any broader refactor of `format_banner_option()`.)

## Tests

`tests/ace/tui/widgets/test_agent_list_grouping.py` and `tests/ace/tui/models/test_agent_groups.py` exercise the banner
rows. They currently assert on banner text content and `disabled` flags, not on styles, so they should keep passing.

Add one focused test in `test_agent_list_grouping.py` that:

1. Builds a tree with an L2 banner (a name-root with ≥ 2 agents so the L2 banner is emitted — the singleton-name-root
   suppression introduced in commit `4f10246b` still applies and we are not changing it).
2. Pulls the `Text` payload out of the rendered `Option` and walks its spans.
3. Asserts:
   - The span containing the bare label uses the new `_NAME_ROOT_BANNER_LABEL_STYLE`.
   - The flanking `· ` / ` ·` spans, the chip span, and the trailing padding span all still use
     `_NAME_ROOT_BANNER_STYLE`.
   - L0 and L1 banners are unchanged (single span at their existing styles) — guard against an accidental refactor that
     would have leaked the new style upward.

This is the only test addition; existing tests do not need updating because they don't pin styles.

## Manual verification

Run `sase ace` against a workspace with multi-model fanout (so name-root groups have ≥ 2 agents and L2 banners actually
render — e.g. the `coder.claude` / `coder.codex` shape from the original plan's UX sketch). Confirm:

- The name-root reads in mint green/bold while the surrounding `·` and the summary chip stay dim gray.
- L0 and L1 banners look identical to before the change.
- A collapsed / selectable L2 banner still inverts/highlights cleanly when focused (selection styling layered by
  OptionList over our spans).

## Definition of done

- `just check` green from a fresh `just install` in the workspace.
- New unit test passes; existing banner tests still pass.
- Manual TUI smoke test confirms the new color reads well at L2 without disturbing L0/L1.
- No changes to public APIs, JSON files, or keymaps.

## Risks / open questions

- **Color readability across terminals**. `#87D7AF` mint green is in the standard 256-color palette and renders
  consistently on the terminals supported by Textual; if a maintainer reports it washing out on their theme, swapping
  the hex in the one constant is a one-line fix.
- **Hierarchy creep**. Adding a third accent color at L2 risks visually competing with L0/L1. Mitigation: keep the
  rule/decorator dim and only color the bare label, so the _rule weight_ hierarchy (`══` → `──` → `· · `) remains the
  dominant cue and color is a secondary scan aid.
- **Singleton-name-root suppression** (commit `4f10246b`) means many simple workspaces won't show the new color at all —
  that is the correct behavior; the colorization only matters when a project actually has multiple name roots, which is
  the case the user is trying to optimize for.
