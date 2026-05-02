---
create_time: 2026-05-01 13:22:31
status: done
prompt: sdd/prompts/202605/conditional_one_hour_headings.md
---
# Conditional one-hour heading visibility

## Goal

In `BY_DATE` grouping, suppress one-hour headings when their enclosing 4-hour window contains only one visible
ChangeSpec or agent entry. Keep 4-hour headings visible as they are today. When the 4-hour window contains two or more
entries, keep showing one-hour headings so dense windows remain scannable.

This applies to both grouped surfaces that currently emit one-hour headings:

- CLs tab `BY_DATE`: `Today` / `Yesterday` date buckets render `date bucket -> 4-hour window -> one-hour heading -> CL`.
- Agents tab `BY_DATE`: date buckets render `date bucket -> 4-hour window -> one-hour heading -> agent`.

## Current behavior and relevant code

- ChangeSpec grouping emits every `hour_subgroup` under `BY_DATE` Today / Yesterday:
  - `src/sase/ace/tui/models/changespec_groups/_tree.py`
  - `src/sase/ace/tui/models/changespec_groups/_keys.py`
  - `src/sase/ace/tui/models/changespec_groups/_buckets.py`
- Agent grouping emits every `one_hour` under every real 4-hour `BY_DATE` window:
  - `src/sase/ace/tui/models/agent_groups/_tree.py`
  - `src/sase/ace/tui/models/agent_groups/_keys.py`
  - `src/sase/ace/tui/models/agent_groups/_buckets.py`
- Banner rendering should not need a behavioral change. The visible rows are driven by the tree builders, and renderers
  already style the one-hour rows correctly when they exist.
- Fold/navigation/jump-hint behavior depends on the same group-key enumeration functions, so enumeration must match tree
  emission exactly.

## Design

Treat this as a model/tree-shape rule, not a display-only rendering rule.

For each `BY_DATE` 4-hour window, compute the number of entries that belong to that window. Emit one-hour group rows
only when that parent window count is `>= 2`.

This intentionally checks the parent 4-hour window size, not the size of each one-hour subgroup:

- One entry in a 4-hour window: show the 4-hour heading and the entry directly under it.
- Two entries in the same 4-hour window but same one-hour bucket: show the one-hour heading with both entries.
- Two entries in the same 4-hour window and different one-hour buckets: show both one-hour headings.
- Entries in separate singleton 4-hour windows: show each 4-hour heading, suppress each one-hour heading.

Existing collapsed one-hour fold state may become stale when a parent window shrinks from two entries to one. That is
acceptable if enumeration excludes the hidden key; existing focus-validity and tree rebuild code already treats missing
banner keys as no longer focusable.

## Implementation plan

1. Update ChangeSpec tree enumeration and build.
   - In `src/sase/ace/tui/models/changespec_groups/_tree.py`, add a small predicate such as
     `_should_emit_hour_subgroup(parent_count: int, hour: str) -> bool`.
   - Reuse the existing `date_subgroup_indices[(l0, date_subgroup)]` count as the parent 4-hour window count.
   - In `build_changespec_tree`, emit the level-2 hourly `ChangeSpecGroupRow` only when:
     - mode is `BY_DATE`,
     - `k.hour_subgroup` is non-empty,
     - `len(date_subgroup_indices[(k.l0, k.date_subgroup)]) >= 2`.
   - If the predicate is false, reset `cur_hour_subgroup` / `cur_hour_subgroup_collapsed` so the CL row renders directly
     under the 4-hour banner and stale collapsed hourly state cannot hide it.
   - In `enumerate_changespec_group_keys`, append hourly keys only under the same predicate, so fold registries, jump
     targets, and banner focus validation agree with the rendered tree.

2. Update Agent tree enumeration and build.
   - In `src/sase/ace/tui/models/agent_groups/_tree.py`, add the equivalent predicate near
     `_should_emit_time_window_banner`.
   - Reuse `hour_indices[(k.project, k.hour)]` as the parent 4-hour window count.
   - In `build_agent_tree`, emit the level-2 one-hour `GroupRow` only when:
     - mode is `BY_DATE`,
     - `k.one_hour` is non-empty,
     - the parent `hour_indices` count is `>= 2`.
   - If the predicate is false, reset `cur_one_hour` / `cur_one_hour_collapsed` before rendering the agent row.
   - In `enumerate_group_keys`, append one-hour keys only under the same predicate.

3. Preserve existing 4-hour behavior.
   - Do not change `_should_emit_time_window_banner` for Agents.
   - Do not suppress ChangeSpec L1 date subgroups.
   - Keep `(no time)` and `(no timestamp)` behavior as-is. Agents should still suppress singleton `(no time)` 4-hour
     headings per the existing predicate, and no one-hour heading is emitted for no-time entries.

4. Update tests.
   - Change existing expectations that singleton real 4-hour windows include a one-hour group.
   - Add explicit ChangeSpec tests:
     - singleton Today/Yesterday 4-hour window suppresses the one-hour key and renders the CL directly below L1;
     - two CLs in the same 4-hour window emit one-hour keys;
     - two CLs in different singleton 4-hour windows suppress one-hour keys for both;
     - collapsed hourly state is ignored when the parent 4-hour window has only one CL.
   - Add explicit Agent tests:
     - singleton real 4-hour window suppresses the one-hour key and renders the agent directly below L1;
     - two agents in the same 4-hour window emit one-hour keys, including the same-hour case;
     - `enumerate_group_keys` excludes singleton-window one-hour keys and includes them once the parent window has two
       agents;
     - collapsed hourly state is ignored when the parent 4-hour window has only one agent.
   - Update widget tests whose row indexes assume a singleton hourly banner, especially:
     - `tests/ace/tui/widgets/test_agent_list_grouping_gutter.py`
     - `tests/ace/tui/widgets/test_changespec_list_grouped.py`

5. Update docs.
   - In `docs/ace.md`, clarify that one-hour headings appear only for 4-hour windows with at least two entries.
   - Keep the visual-style docs intact, but make clear one-hour headings are conditional.

## Verification

Run the focused model/widget tests first:

```bash
just install
.venv/bin/pytest \
  tests/ace/tui/models/test_changespec_groups_layout.py \
  tests/ace/tui/models/test_agent_groups_grouping_mode_hour.py \
  tests/ace/tui/models/test_agent_groups_grouping_mode_tree.py \
  tests/ace/tui/widgets/test_agent_list_grouping_gutter.py \
  tests/ace/tui/widgets/test_changespec_list_grouped.py
```

Then run repo checks:

```bash
just fmt
just check
```

## Risks and mitigations

- Hidden hourly keys could leave stale collapsed state in registries. Mitigation: keep enumeration aligned with rendered
  rows; stale keys become inert and focus-validity checks drop them.
- Agents and CLs have separate grouping implementations. Mitigation: update both tree builders and both enumeration
  functions with the same parent-count rule, and cover both in tests.
- Widget tests may fail due changed row indexes rather than behavior. Mitigation: update fixtures to use two entries
  when the test is specifically asserting hourly heading styling/gutters; use singleton fixtures when asserting
  suppression.
