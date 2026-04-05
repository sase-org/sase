# CODEX

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

---

# CLAUDE

## Problem

When running many agents, it becomes hard to find and group them by purpose. The Agents tab currently offers filtering
by ChangeSpec (inherited from the CL query system) and visual separation via pinning, but there is no way to attach
arbitrary labels to agents and filter/group by those labels.

**Agent tags** would let you group one or more agents under a custom named tag, enabling fast filtering and visual
grouping in the TUI.

## Existing Patterns to Build On

| Pattern          | How it works                                           | What we can reuse                      |
| ---------------- | ------------------------------------------------------ | -------------------------------------- |
| CL tags ("W")    | Name/value pairs on ChangeSpecs, persisted in JSON     | Tag input modal UI, saved history      |
| Pinned agents    | Boolean flag per agent identity, separate panel        | Identity-keyed JSON persistence        |
| Saved queries    | 10 numbered slots for text filter strings              | Slot-based quick access pattern        |
| Agent names      | Single-letter names assigned via `%name` or TUI rename | Per-agent metadata in artifacts dir    |
| Workflow folding | Parent/child hierarchy with expand/collapse            | Visual grouping without separate panel |

## Design Options

### Option A: Tags as Agent Metadata (Recommended)

Tags are free-form string labels attached to individual agents. Multiple agents can share a tag, and one agent can have
multiple tags.

**Assigning tags:**

- **Keybinding "T"** on a selected agent opens a tag input modal (similar to the CL tag modal "W").
- The modal shows previously used tag names for quick selection (autocomplete from history).
- Tags are simple strings (no name/value pairs needed, unlike CL tags).
- Optionally support assigning tags at launch time via a `%tag` directive: `%tag deploy-fix`.

**Displaying tags:**

- Tags appear as colored badges after the agent name in the agent list: `[agent] my-cl  (RUNNING)  #deploy-fix #urgent`
- Tag color could be deterministic (hash-based) so the same tag always gets the same color.
- Tags could appear in the agent detail metadata panel as well.

**Filtering by tag:**

- Extend the agent list query/filter to support `tag:deploy-fix` or `#deploy-fix` syntax.
- If the query bar filters agents (not just ChangeSpecs), tags become first-class filter criteria.

**Persistence:**

- Store tag assignments in `~/.sase/agent_tags.json`, keyed by agent identity tuple `(agent_type, cl_name, raw_suffix)`.
- Store tag name history in `~/.sase/saved_agent_tag_names.json` (paralleling `saved_tag_names.json` for CLs).

**Pros:** Flexible, familiar pattern (mirrors CL tags), composable with existing query system. **Cons:** Per-agent
granularity means tagging many agents one-by-one could be tedious.

### Option B: Tag Groups as Virtual Panels

Instead of per-agent metadata, tags define named groups that appear as collapsible sections in the agent list (similar
to workflow fold groups but user-defined).

**Assigning:**

- Same "T" keybinding to tag individual agents.
- Additionally, a "bulk tag" mode: mark multiple agents (using existing mark system if available), then "T" to tag all
  marked agents at once.

**Displaying:**

- Agents with the same tag are grouped under a collapsible header row:
  ```
  ▼ #deploy-fix (3 agents)
    [agent] fix-auth  (DONE)
    [agent] fix-db    (RUNNING)
    [agent] fix-cache (DONE)
  ▼ #untagged (5 agents)
    ...
  ```
- Toggle between grouped view and flat view with a keybinding (e.g., "G" for group-by-tag).

**Pros:** Strong visual organization, easy to scan. **Cons:** More complex rendering, may conflict with workflow fold
hierarchy.

### Option C: Tags via Prompt Directive Only

Tags are assigned exclusively at launch time via a `%tag` directive in the agent prompt. No TUI modal for post-hoc
tagging.

**Assigning:**

- `%tag deploy-fix` in the prompt text before launching the agent.
- Multiple tags: `%tag deploy-fix %tag urgent`.
- Tag is stored in `agent_meta.json` alongside other directives.

**Displaying/Filtering:** Same as Option A.

**Pros:** Simple implementation, no new modal UI needed. **Cons:** Cannot tag agents after launch, cannot tag agents
launched by workflows/hooks.

## Recommended Approach: Option A + Elements of B

Combine per-agent tag metadata (Option A) with optional grouped display (Option B):

1. **Core: per-agent tags** -- "T" keybinding opens tag modal, tags persisted in JSON, displayed as badges.
2. **Bulk tagging** -- Support marking multiple agents and tagging them all at once.
3. **Filter support** -- `tag:name` or `#name` syntax in the agent filter bar.
4. **Optional grouped view** -- A toggle keybinding to switch between flat list and tag-grouped display.
5. **Launch-time directive** -- `%tag name` directive for pre-tagging agents at launch.

## UI Mockups

### Agent List (Flat View, Tags as Badges)

```
 [agent] fix-auth-middleware  (DONE)  #deploy-fix #urgent  @a
 [agent] update-cache-layer  (RUNNING)  #deploy-fix
 [workflow] refresh_cl_desc  (DONE)
 [agent] investigate-flake  (RUNNING)  #flaky-tests
```

### Agent List (Grouped View)

```
 ▼ #deploy-fix (2 agents)
   [agent] fix-auth-middleware  (DONE)  @a
   [agent] update-cache-layer  (RUNNING)
 ▼ #flaky-tests (1 agent)
   [agent] investigate-flake  (RUNNING)
 ▼ untagged (1 agent)
   [workflow] refresh_cl_desc  (DONE)
```

### Tag Input Modal

```
┌─ Tag Agent ─────────────────────────┐
│                                     │
│  Tag: deploy-fix                    │
│                                     │
│  Recent tags:                       │
│    deploy-fix                       │
│    flaky-tests                      │
│    urgent                           │
│    refactor                         │
│                                     │
│  [Enter] Apply  [Esc] Cancel        │
└─────────────────────────────────────┘
```

### Agent Detail Metadata Panel

```
Type:       agent
CL:         fix-auth-middleware
Status:     DONE
Tags:       #deploy-fix, #urgent
Timestamps: BEGIN | 2026-04-04 10:30:15
            END   | 2026-04-04 10:45:22
```

## Data Model Changes

```python
# In Agent dataclass (src/sase/ace/tui/models/agent.py)
tags: list[str] = field(default_factory=list)

# New persistence module (src/sase/ace/agent_tags.py)
# Mirrors pinned_agents.py pattern
_AGENT_TAGS_FILE = Path.home() / ".sase" / "agent_tags.json"

def load_agent_tags() -> dict[tuple[AgentType, str, str | None], list[str]]: ...
def save_agent_tag(identity, tag: str) -> None: ...
def remove_agent_tag(identity, tag: str) -> None: ...
```

## Keybinding Summary

| Key | Action                            | Context    |
| --- | --------------------------------- | ---------- |
| T   | Open tag modal for selected agent | Agents tab |
| G   | Toggle grouped/flat view          | Agents tab |

## Open Questions

1. **Tag scope**: Should tags be per-project or global across all projects? Per-project aligns with how agents are
   scoped, but global tags could be useful for cross-project workflows.
2. **Tag lifecycle**: Should tags on dismissed/archived agents be cleaned up automatically, or preserved for history?
3. **Tag colors**: Deterministic hash-based coloring, or let users pick colors? Hash-based is simpler.
4. **Interaction with saved queries**: Should saved query slots (0-9) work with agent tag filters, or only ChangeSpec
   queries?
5. **Bulk operations**: Beyond bulk tagging, should there be bulk actions on tagged agents (e.g., "dismiss all #done",
   "kill all #stale")?
