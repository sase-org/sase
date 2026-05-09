---
create_time: 2026-05-09 13:02:47
status: done
---
# Plan: Unread Agent Count White

## Goal

Make the Agents tab header count number before `unread` render white so it stands out in snapshots like:

`Agents(<total>): <running> running · <waiting> waiting · 24 unread · <read> read`

The concrete example says the `24` in `24 unread` should be white, so this plan treats `unread` as the target count. The
word `unread` should remain dim, and the count computation should not change.

## Current State

The Agents tab metric strip is rendered by `AgentInfoPanel._update_display()` in
`src/sase/ace/tui/widgets/agent_info_panel.py`.

Count styles are centralized in `AgentInfoPanel._COUNT_STYLES`:

- `total`: `bold #5FAFFF`
- `running`: `bold #00D7AF`
- `waiting`: `bold #AF87FF`
- `unread`: `bold #FFAF5F`
- `read`: `bold #BCBCBC`

The existing semantics are already separated in `AgentDisplayMixin._update_agents_info_panel()`:

- visible top-level rows only
- running excludes waiting
- unread is driven by `_unread_completed_agent_ids`
- read is the remainder after running, waiting, and unread

Those semantics should be left alone.

## Design

Make a minimal presentation-only update:

1. Change the `unread` count style in `AgentInfoPanel._COUNT_STYLES` from amber to white.
2. Keep the `unread` label dim so only the number is emphasized.
3. Keep the `read` count style unchanged unless product feedback confirms the literal `read` count should also be white.
4. Keep the loading state `Agents: …` unchanged.
5. Preserve the exact plain text of the header.

Using `bold white` is preferable to `#FFFFFF` because the surrounding code already uses Rich named styles in several
places, and the user specifically asked for white rather than a particular truecolor hex.

## Implementation Steps

1. Update `AgentInfoPanel._COUNT_STYLES["unread"]` to `bold white`.
2. Update the focused Rich style assertion in `tests/ace/tui/widgets/test_agent_info_panel.py` so the unread count span
   expects `bold white`.
3. Keep the uniqueness assertion if it still holds, which it should because no other count currently uses white.
4. Do not modify `AgentDisplayMixin._update_agents_info_panel()` or count formulas.

## Verification

Run the focused widget test:

```bash
pytest tests/ace/tui/widgets/test_agent_info_panel.py
```

Because repo memory requires a full check after code changes, run:

```bash
just check
```

If this workspace needs dependency refresh first, run `just install` before `just check`.
