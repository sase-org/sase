# Agent Tags: UI Research

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
