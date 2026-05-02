---
create_time: 2026-04-26 00:46:31
status: done
prompt: sdd/prompts/202604/split_project_changespec_levels.md
---
# Split Project (L1) from ChangeSpec (L2) in agents-tab grouping

## Background

On the agents tab, agents within a single tag/panel are currently grouped into a two-level tree:

- **L0** — combined "project / ChangeSpec" banner. Group key: `(project_name, cl_name)`. Label:
  `"sase_100 / fix-bug-id"` or just `"sase_100"` when the agent has no ChangeSpec.
- **L1** — agent name-root banner (e.g. `coder`, `planner`). Only emitted when ≥2 agents share the same name-root.

All of this lives in `src/sase/ace/tui/models/agent_groups.py` plus the banner-label / rendering helpers in
`src/sase/ace/tui/widgets/_agent_list_rendering.py`. Fold state is keyed by arbitrary tuples in
`src/sase/ace/tui/models/agent_group_fold.py`, so the level count is not hard-coded there.

## Goal

Split the combined L0 into two distinct levels so the hierarchy becomes:

- **L0** — project (e.g. `sase_100`)
- **L1** — ChangeSpec (e.g. `fix-bug-id`)
- **L2** — agent name-root (current L1)

Each level should be independently foldable.

### Hard constraint: don't change the UI when no ChangeSpec is in play

> "If there are no agents that target a ChangeSpec, we shouldn't change the UI at all."

When **no** agent in a panel has a ChangeSpec, the user should see exactly today's two-level rendering: a project banner
directly above its name-root banner (or directly above agents). We must not introduce empty L1 banners or an extra
indent level in this case.

The check is **per-panel**: each panel decides independently whether to use the 3-level or 2-level layout based on
whether any of its agents has `cl_name != ""`.

## Mixed-case behaviour (some agents have ChangeSpec, some don't)

In a panel where at least one agent has a ChangeSpec, we use the 3-level layout. Agents in the same project that lack a
ChangeSpec need a place to live. Two reasonable options:

1. **Synthetic "(no ChangeSpec)" L1 bucket** — explicit empty-string ChangeSpec group, sorted last under its project.
   Symmetrical with how `NO_PROJECT` is handled today.
2. **Promote ChangeSpec-less agents to live directly under L0** — skip the L1 banner for them, similar to how a
   singleton name-root skips its L1 banner today.

**Recommendation: option 1 (synthetic bucket).** It keeps the tree shape regular, makes fold state meaningful, and
matches the existing precedent set by the `NO_PROJECT` sentinel. Label it `"(no ChangeSpec)"` and sort it last within
its project.

## Design

### Grouping keys

Replace the current `_GroupingKeys` dataclass:

```python
@dataclass(frozen=True)
class _GroupingKeys:
    project: tuple[str, str]   # (project_name, changespec)
    name_root: str
```

with:

```python
@dataclass(frozen=True)
class _GroupingKeys:
    project: str               # project_name (or NO_PROJECT)
    changespec: str            # cl_name (may be "")
    name_root: str
```

### `GroupRow` levels

`GroupRow.level` becomes 0/1/2:

| Level | group_key tuple                    | Banner label                        |
| ----- | ---------------------------------- | ----------------------------------- |
| 0     | `(project,)`                       | `project` or `"(no project)"`       |
| 1     | `(project, changespec)`            | `changespec` or `"(no ChangeSpec)"` |
| 2     | `(project, changespec, name_root)` | `name_root`                         |

This preserves the existing convention that a child group's key starts with its parent's key tuple, so
`AgentGroupFoldRegistry` (already `tuple[str, ...]`-keyed) needs no changes.

### Per-panel mode switch

In `agent_groups.py`, where the tree is built for a panel's agent list, first scan the panel's agents:

- `panel_uses_changespec_level = any(a.cl_name for a in panel_agents)`

If **false**: build the tree with today's two-level shape — a single L0 banner using the project name only (drop the
`/ cl_name` suffix), and the existing name-root level. Group keys remain 2-tuples (`(project,)` and
`(project, name_root)`). The user-visible UI is identical to today's, because today's L0 label already collapses to just
the project when `cl_name == ""`.

If **true**: build the new three-level tree as described above.

This keeps the no-ChangeSpec case byte-identical and confines the new behaviour to panels that actually need it.

### Singleton suppression

Today, an L1 (name-root) banner is suppressed when only one agent shares that name-root. Apply the analogous rule to the
new L1 (ChangeSpec) banner? **Recommendation: no.** ChangeSpec banners convey meaningful identity (the CL/PR), not just
a name prefix, and the user explicitly asked for ChangeSpec to be its own level. Always render the L1 ChangeSpec banner
when the panel is in 3-level mode.

The L2 (name-root) singleton suppression carries over unchanged from today's L1 behaviour.

### Workflow children

Workflow children inherit their parent's grouping keys (project, ChangeSpec, name-root). This continues to work because
the inheritance is already keyed off the parent agent's identity, not the level count. We just need to make sure the new
`_grouping_keys_for()` returns the parent's project/changespec/name_root triple.

### Sorting

- L0 (project): unchanged — named projects alphabetically, `NO_PROJECT` last.
- L1 (changespec): named ChangeSpecs alphabetically (case-insensitive), synthetic `"(no ChangeSpec)"` bucket last within
  its project.
- L2 (name-root): unchanged — singletons first in input order, grouped name-roots after, alphabetically.

### Banner labels

Update `banner_label()` in `agent_groups.py` to dispatch on the new levels:

- level 0 → project name (or `"(no project)"`)
- level 1 → ChangeSpec name (or `"(no ChangeSpec)"`)
- level 2 → name-root

Drop the `"project / changespec"` composite label entirely from the 3-level path; the two pieces of information now live
on separate banners. Keep the composite label only as the fallback rendering used by the 2-level
(no-ChangeSpec-anywhere) path, where it degenerates to just the project name.

## Files to touch

- `src/sase/ace/tui/models/agent_groups.py` — primary rewrite. New `_GroupingKeys` shape, per-panel mode switch,
  three-level walk/sort, updated `banner_label()`, updated `enumerate_group_keys()`.
- `src/sase/ace/tui/widgets/_agent_list_rendering.py` — accept level=2 in banner formatting; pick an indent/style for
  the new ChangeSpec banner (likely the same accent the current L0 uses, with the name-root banner taking on the
  slightly-deeper accent currently used at L1).
- `src/sase/ace/tui/widgets/agent_list.py` — verify resolve-row / selection / fold-toggle paths handle 3-level keys
  (mostly mechanical since fold registry is generic).
- `src/sase/ace/tui/models/agent_group_fold.py` — no logic changes; just confirm `clear_unknown()` still does the right
  thing with longer tuples.
- Tests:
  - `tests/ace/tui/models/test_agent_groups.py` — update existing expectations for the 3-level case, keep/add coverage
    for the 2-level fallback when no agent has a ChangeSpec, add coverage for the mixed-case `(no ChangeSpec)` bucket,
    add fold-state coverage at each level, add workflow-child inheritance coverage at the new level.
  - `tests/ace/tui/widgets/test_agent_list_grouping.py` — update banner rendering expectations and add a test asserting
    **no UI change** when no agent in a panel has a ChangeSpec (a regression guard for the constraint).

## Risks / open questions

- **Visual density**: adding a third banner level will eat vertical space in panels that have ChangeSpecs. Indent and
  styling choices matter — worth a visual check against a panel with several projects × several CLs.
- **Fold-state migration**: existing collapsed-set entries are 2-tuples `(project, cl)` or 3-tuples
  `(project, cl, name_root)`. After the change these tuples no longer match any group key (the new L0 is a 1-tuple). Old
  entries will be cleared by `clear_unknown()` on the first refresh, which is acceptable — fold state is in-process
  only.
- **Mixed-case bucket label**: `"(no ChangeSpec)"` is a suggestion; an alternative is `"(no CL)"` or `"(unassigned)"`.
  Pick whichever matches the rest of the TUI's voice — the current code uses `"(no project)"`, so `"(no ChangeSpec)"` is
  the closest match.
- **Per-panel switch granularity**: if a user has one panel with ChangeSpecs and another without, the two panels will
  have different level counts. That seems fine and is what the constraint implies, but worth confirming with the user
  that per-panel (rather than per-tab) is the right granularity.
