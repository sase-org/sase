---
create_time: 2026-05-05 21:38:50
status: done
prompt: sdd/prompts/202605/agent_untagged_panel.md
---
# Plan: Hide Empty Untagged Agents Panel

## Goal

Make the Agents tab in `sase ace` stop rendering the `(untagged) · 0` panel when every visible agent belongs to a tag
panel. Preserve the current fallback behavior for an actually empty Agents tab and for mixed tagged/untagged agent sets.

## Current Behavior

- `src/sase/ace/tui/models/agent_panels.py` always returns `[None, *tags]` from `_panel_keys_for()`.
- `None` represents the untagged panel, so the TUI always renders an untagged panel, even when all loaded agents have
  effective tags.
- Workflow children inherit their parent's tag via `_panel_key_for_agent()`, so a child without its own tag should not
  force the untagged panel to remain visible when its parent is tagged.
- The panel widget id for index `0` is statically `agent-list-panel`. Several TUI paths rely on this id, so the stable
  id should remain, but its displayed panel key can be a tag when there is no untagged panel.

## Desired Behavior

- If there are untagged agents, keep `(untagged)` first, followed by sorted tag panels.
- If there are tagged agents and zero effective untagged agents, omit the `(untagged)` panel entirely and render the
  first tag panel in slot `0`.
- If there are no agents at all, keep the empty `(untagged)` panel as the fallback/empty-state focus target.
- If a focused panel disappears on refresh, fall back to the first available panel, not specifically to `None`.

## Implementation Steps

1. Update `src/sase/ace/tui/models/agent_panels.py`.
   - Change `_panel_keys_for()` to track both distinct tags and whether any agent maps to `None`.
   - Return `[None]` for an empty agent list.
   - Return `[None, *sorted_tags]` only when at least one effective untagged agent exists.
   - Return `sorted_tags` when all visible agents are tagged.
   - Update docstrings/comments that currently say the untagged panel always appears first.

2. Adjust focus fallback semantics in `AgentPanelGroup.from_agents()`.
   - Preserve focus by key when possible.
   - When the old focused key is missing, set `focused_idx = 0`, which now means “first available panel” rather than
     always “untagged”.
   - Keep `focused_key` unchanged in API shape (`PanelKey`) because `None` remains the real untagged key.

3. Update display/helper comments where index `0` is described as the untagged main pane.
   - `src/sase/ace/tui/actions/agents/_display_helpers.py`
   - `src/sase/ace/tui/actions/agents/_display_panels.py`
   - Any nearby docs that assert slot `0` is always untagged.
   - Avoid broad refactors; this is a panel-key policy change, not a widget-id rewrite.

4. Add focused regression coverage.
   - Add or update model tests for:
     - all tagged agents produce only tag keys, with no `None`;
     - mixed agents still produce `[None, sorted tags...]`;
     - empty agents still produce `[None]`;
     - workflow child of a tagged parent does not keep an empty untagged panel visible.
   - Update panel title/display tests that currently expect `(untagged) · 0` for all-tagged agents.
   - Add display coverage that when every agent is tagged, `agent-list-panel` can be titled with the first tag, proving
     the stable widget id is decoupled from the untagged key.

5. Verify behavior with targeted tests first, then the repo check.
   - Run the relevant pytest targets around `agent_panels`, panel titles/display, panel-scoped bulk, and jump/navigation
     if affected.
   - Because this repo’s memory says to install before checks in ephemeral workspaces, run `just install` if needed,
     then `just check` before final response after source changes.

## Risk Areas

- Code paths that infer panel meaning from widget id `agent-list-panel` may need to read `_panel_group.panel_keys[0]`
  instead. Initial inspection shows most runtime paths already map ids through panel index, so this should be a small
  change.
- `focused_key` uses `None` as a valid untagged key. Avoid using `None` to mean “no focused panel”; keep panel sets
  non-empty (`[None]` for no agents) so fallback remains deterministic.
- Existing tests may encode the old “empty untagged panel always present” behavior; update only tests that conflict with
  the new requested behavior.
