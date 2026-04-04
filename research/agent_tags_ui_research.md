# Agent Tags UI Research

## Goal

Design a UI for "agent tags" so users can assign custom named tags to one or more agents, then quickly view/filter/act
on those groups in ACE.

## Current UX Baseline (in-repo)

### Agents tab capabilities today

- Main/pinned agent lists with rich status icons and hierarchy (`src/sase/ace/tui/widgets/agent_list.py`).
- Agents-tab search filter via `/` using a simple substring query (`src/sase/ace/tui/actions/agents/_core.py`,
  `src/sase/ace/tui/actions/agents/_loading.py`).
- Existing grouping mechanisms:
  - pin/unpin (`P`) for a persistent focused subset.
  - wait chains (`w` / `W`) for dependency sequencing.
  - revive modal and run-log modal for historical agent sets.
- Top bar already has room for compact state labels (`src/sase/ace/tui/widgets/agent_info_panel.py`).

### Important keybinding constraint

`W` is already overloaded on Agents tab as "new agent waiting for this one" (implemented through `action_add_tag`
routing to wait behavior on Agents). Reusing `W` for tag assignment would conflict with an established workflow.

### Existing persistence patterns to copy

- Small user-owned JSON stores in `~/.sase/*.json` (e.g. pinned/dismissed agents, saved queries, saved tag names).
- Modal-based data entry patterns already exist for tags (`TagInputModal`) and list filtering (`QueryEditModal`).

## UX Jobs To Be Done

1. Add/remove tags on one agent quickly.
2. Apply a tag to many agents quickly.
3. See an agent's tags at a glance in the list.
4. Filter agents by tag without leaving normal navigation flow.
5. Reuse tag names and avoid typo drift.

## UI Options

## Option A: Inline Tag Badges + Filter DSL (lowest friction)

### Interaction

- Show up to 1-2 compact tag chips in each agent row, with `+N` overflow.
- Extend Agents filter (`/`) to support qualifiers like:
  - `tag:frontend`
  - `tag:frontend OR tag:release`
  - plain text still works as today.
- Add one action to tag current agent (open modal with existing tag-name suggestions).

### Why it fits the current app

- Reuses the existing single filter entry point (`QueryEditModal` on Agents tab).
- Minimal visual footprint and no new major panel/modal required.
- Can be implemented incrementally by expanding existing filter parsing in `_load_agents()`.

### Risks

- Harder to discover than a dedicated "Tag Manager".
- Bulk tagging needs an additional mechanism (see Option C or phased plan).

## Option B: Grouped Agent List by Tag (high visibility)

### Interaction

- Toggle list mode: `flat` vs `grouped-by-tag`.
- In grouped mode, list renders headers like:
  - `-- @frontend (4) --`
  - `-- @release (2) --`
  - `-- Untagged (9) --`
- Navigation stays j/k with header rows skipped (same pattern as run-log modal).

### Why it fits the current app

- Existing OptionList header/skip patterns are already implemented in `agent_run_log_modal.py`.
- Gives strong visual grouping for "workstreams".

### Risks

- Agents with multiple tags either need duplication across groups or primary-tag rules.
- More layout complexity with pinned panel + workflow child rows.

## Option C: Tag Palette Modal (best bulk-edit UX)

### Interaction

- New modal from Agents tab (example: `,g` in leader mode or another unclaimed binding).
- Left side: existing tags with counts.
- Right side: actions for selected tag:
  - apply to current agent
  - remove from current agent
  - apply to selected set (if multi-select is later added)
  - rename/delete tag

### Why it fits the current app

- Mirrors existing modal-heavy workflows (history, revive, run log, xprompt browser).
- Solves discoverability and administration of tags.

### Risks

- Highest implementation cost.
- More keybinding complexity.

## Recommended Direction

Adopt a phased hybrid:

1. Phase 1: Option A core (badges + `tag:` filter + add/remove tag on current agent).
2. Phase 2: Add lightweight bulk operations (apply/remove tag to all currently filtered agents).
3. Phase 3: If needed, add Option C (tag palette modal) for full tag management.

This keeps initial scope small while still supporting power-user workflows quickly.

## Concrete UI Proposal (Phase 1)

### Agent row rendering

- Append dim badges at the right side of each row label:
  - `… DONE  [frontend] [release]`
  - `… RUNNING [backend] +2`
- Badge style should be low-contrast enough to avoid overpowering status colors.

### Agent detail metadata panel

- Add a `Tags:` line near `Status` / `Workspace` / `Model` fields:
  - `Tags: frontend, release, flaky-test`

### Agents info panel

- When filter includes tags, show concise filter summary:
  - `filter: tag:frontend`
  - `filter: tag:frontend OR status:RUNNING`

### Tag assignment flow

- Action on Agents tab opens modal:
  - Input 1: tag name (autocomplete from history)
  - Optional toggle: add/remove mode
- Keep fast keyboard flow (Enter to apply, Esc to cancel).

## Suggested Keymap Shape

Because `W` is already used for wait semantics on Agents tab, avoid reclaiming it.

Possible mappings:

- `gt`: add/remove tag on current agent (vim-like mnemonic)
- `gT`: remove tag from current agent
- `,g`: open tag palette modal (future phase)

If avoiding new prefixes is preferred, define explicit actions in keymap config with currently unused uppercase keys,
but do not overload existing wait/pin/kill bindings.

## Data Model Notes

A practical persistence structure aligned with existing patterns:

- `~/.sase/agent_tags.json`
- Shape:
  - `tags_by_agent_identity`: maps stable agent identity tuple to `["tag1", "tag2"]`
  - `saved_tag_names`: optional last-used dictionary (or reuse existing saved tag name storage)

Identity should include existing `Agent.identity` components so tags stay attached across refreshes and tab switches.

## Edge Cases

- Workflow parent vs child steps:
  - Default tagging target should be top-level parent agent unless user explicitly tags a child.
- Dismissed agents:
  - Keep tags persisted so revived agents retain grouping.
- Unknown/temporary identities:
  - Delay tag write or normalize identity when `raw_suffix` is unavailable.
- Multi-tag ordering:
  - Store tags normalized/lowercased for filtering, preserve original case for display if desired.

## Testing Implications

High-value tests for UI confidence:

1. Tag add/remove survives `_load_agents()` refresh cycles.
2. `tag:` filter behavior composes with existing substring filter semantics.
3. Agent list renders badges without breaking pinned/folded/workflow-child formatting.
4. Dismiss/revive preserves tags.
5. Headless `sase ace --agent` snapshots include visible tag signals for e2e assertions.

## Summary

The most compatible UI is to treat agent tags as an extension of the existing Agents filter workflow, not a separate
navigation system. Start with inline badges + `tag:` filtering + a simple assign/remove action, then add bulk and modal
management only if usage proves the need.
