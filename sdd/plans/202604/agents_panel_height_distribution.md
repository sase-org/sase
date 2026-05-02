---
create_time: 2026-04-27 11:27:39
status: done
prompt: sdd/prompts/202604/agents_panel_height_distribution.md
---
# Fix Agents-tab panel height distribution

## Problem

In the `sase ace` Agents tab, the `(untagged)` panel can render much smaller than a tag panel such as `@mute`, even when
`(untagged)` contains far more agents. The snapshot shows `(untagged) · 11` getting only its natural content height
while `@mute · 1` consumes nearly the rest of the left column.

## Root Cause

The panel stack is built by `AgentDisplayMixin._refresh_panel_widgets` in `src/sase/ace/tui/actions/agents/_display.py`.
Panel keys are ordered by `AgentPanelGroup` as `[None, tag1, tag2, ...]`, so `(untagged)` is always first and tag panels
follow alphabetically.

`_apply_panel_heights` currently has two regimes:

- If all natural panel heights fit inside the container, every panel except the last gets an exact fixed cell height
  (`option_count + 2` border rows), while the last panel gets `1fr` and absorbs all leftover space.
- If natural heights overflow, all panels get proportional fractional weights based on `option_count + 1`.

That first regime was introduced to fix the single-panel case where the untagged panel left blank space beneath it. It
solved that case but made the multi-panel case wrong: with `(untagged)` first and `@mute` last, the one-agent `@mute`
panel receives every spare row simply because it is last.

The visual mismatch in the snapshot is therefore expected from the current algorithm, not a Textual rendering glitch.

## Design

Keep the original goals:

- no dead zone beneath the panel stack when the panels' natural heights fit;
- no tiny panel collapsing to zero;
- overflow still shares height proportionally;
- a single untagged panel still fills the column.

Change the "fits" regime so leftover height is assigned to the primary untagged panel, not blindly to the last panel.
Since `(untagged)` is always index 0 and is the main panel, this makes the common display match user expectation: the
untagged work area receives the flexible space, while tag panels keep compact natural heights.

Concretely:

- In `_apply_panel_heights`, when `total_natural <= container_height`:
  - if there is exactly one panel, set it to `1fr`;
  - otherwise set the first panel to `1fr`;
  - set all later tag panels to their natural fixed cell heights.
- Leave the overflow branch unchanged.
- Update comments/docstring so they describe the new policy.

This deliberately does not make every panel fractional in the fits regime. Equal or proportional fractions would make
low-count tag panels visually large again whenever there is spare room. The fixed-tag/elastic-main split preserves
compact tag panels while still consuming the full column.

## Tests

Update `tests/ace/tui/test_agent_panels_display.py`:

- Replace the existing "last panel absorbs leftover" expectation with "first untagged panel absorbs leftover; tag panels
  keep natural cell heights".
- Keep the single-panel test asserting the lone untagged panel uses `1fr`.
- Keep the overflow test asserting all panels use proportional fractional weights, unchanged.
- Keep the resize/reapply test checking height recomputation does not rebuild option lists.

## Verification

Run targeted tests first:

```bash
uv run pytest tests/ace/tui/test_agent_panels_display.py
```

Then run the repo check required by project memory:

```bash
just install
just check
```

Manual verification after that: open `sase ace` with one or more tag panels and confirm `(untagged)` is the flexible
panel while small tag panels stay compact; then verify the no-tag case still gives `(untagged)` the full column height.
