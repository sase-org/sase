---
create_time: 2026-05-05 22:32:22
status: done
prompt: sdd/prompts/202605/agent_name_prefix_grouping.md
---
# Plan: Agent Name Prefix Subgroups

## Goal

Add an optional deeper Agents-tab grouping level for dotted agent-name prefixes. When multiple agents under the same
existing name-root share the text before the second period, render a subgroup heading for that prefix.

For the snapshot case in `group: by status`, agents named `sase-42.2.1`, `sase-42.2.2`, ... should render under:

```text
Done
  sase-42
    sase-42.2
      sase-42.2.1
      sase-42.2.2
```

The direct one-period agent `sase-42.2` does not itself have a "before second period" prefix; it should remain directly
under `sase-42` unless we decide separately to include parent/phase marker rows in their child prefix group.

## Product Rules

1. Keep the existing first-period `name_root` grouping rule.
2. Add a `name_prefix` grouping key only when the chosen name has at least two periods.
   - `sase-42.2.6` -> `sase-42.2`
   - `sase-42.2` -> no prefix subgroup key
   - `coder.claude` -> no prefix subgroup key
3. Emit a prefix subgroup heading only when at least two agents share that prefix within the same parent grouping scope.
4. Preserve workflow-child inheritance: workflow children should use their top-level parent agent's root/prefix
   grouping.
5. Leave `BY_DATE` unchanged, since it intentionally suppresses name-root grouping in favor of time subgroups.
6. Apply the new prefix grouping wherever name-root grouping is active:
   - `BY_STATUS`: status bucket -> name root -> name prefix.
   - `STANDARD` without a ChangeSpec level: project -> name root -> name prefix.
   - `STANDARD` with a ChangeSpec level can use the same model and produce project -> ChangeSpec -> name root -> name
     prefix. This is a fourth structural level, so the renderer must handle deeper rows generically rather than assuming
     a hard max of three.

## Technical Design

1. Extend `src/sase/ace/tui/models/agent_groups/_keys.py`.
   - Add `name_prefix` to `_GroupingKeys`.
   - Add a helper parallel to `_name_root()` that returns text before the second period from `agent.agent_name`, falling
     back to `display_name` exactly as `_name_root()` does.
   - Suppress `name_prefix` under `BY_DATE`, matching `name_root`.
   - Update `walk_order()` so grouped prefixes sort after direct/root-only agents and before stable per-agent tiebreaks.

2. Extend `src/sase/ace/tui/models/agent_groups/_tree.py`.
   - Count prefix groups by `(parent_key, name_root, name_prefix)`.
   - Emit existing `name_root` banners exactly as today when `name_root` has 2+ members.
   - Inside an expanded `name_root`, emit a child prefix banner when `name_prefix` has 2+ members.
   - Prefix banner `group_key` should be `(*parent_key, name_root, name_prefix)`, which keeps fold keys unique and
     intuitive.
   - Agents without an emitted prefix group should render directly under their current parent/root, preserving singleton
     suppression behavior.
   - Update `enumerate_group_keys()` so collapse-all/jump-hint/fold navigation sees prefix subgroup keys.
   - Update docstrings for the expanded hierarchy.

3. Make banner rendering depth-aware.
   - Current styling treats only `STANDARD` ChangeSpec and `BY_DATE` time subgroups as the middle-tier `▎` heading;
     name-root banners use `▸`.
   - For trees that now have a child under a name-root, the name-root should use the middle-tier heading and the prefix
     subgroup should use the deepest branch heading. This matches the existing three-level visual language.
   - Update `format_banner_option()` and `compute_tier_styles()` to derive "middle" vs "deepest" treatment from
     structural context, while preserving current `STANDARD` and `BY_DATE` output where no prefix subgroup exists.
   - Ensure gutters are not capped at two ancestors; deeper structural rows should receive a stable tuple of ancestor
     guide styles.

4. Update fold/navigation documentation.
   - Refresh comments in `agent_group_fold.py` and `agent_groups/__init__.py` so arbitrary-length group keys and prefix
     subgroup keys are documented.
   - Existing fold/navigation code already stores tuple keys and computes deepest visible groups, so it should need
     little or no behavioral change beyond key enumeration/tree output.

## Test Plan

1. Model tests:
   - `BY_STATUS` snapshot-shaped case: `sase-42.1.*` and `sase-42.2.*` produce L2 prefix groups under L1 `sase-42`.
   - Prefix groups are suppressed for singletons.
   - Direct one-period agents like `sase-42.2` remain direct children of `sase-42`.
   - Workflow children inherit the parent's prefix.
   - `enumerate_group_keys()` includes emitted prefix subgroup keys.
   - Collapsing a prefix subgroup hides only that prefix's agents.

2. Widget/render tests:
   - `BY_STATUS` with three name levels renders `Running/Done` L0, `sase-42` as the middle-tier `▎` heading, and
     `sase-42.2` as the deepest `▸` heading.
   - Agent rows under prefix groups carry the expected ancestor gutters.
   - Existing `STANDARD` and `BY_DATE` rendering tests continue to pass or are updated only where the intentional new
     prefix grouping changes row shape.

3. Verification:
   - Run focused tests first:
     `uv run pytest tests/ace/tui/models/test_agent_groups_* tests/ace/tui/widgets/test_agent_list_grouping*`
   - Because this repo requires it after changes, run `just install` if needed, then `just check` before finalizing
     implementation.

## Risks and Decisions

1. The main product decision is whether one-period parent rows such as `sase-42.2` should be pulled into the `sase-42.2`
   prefix subgroup. The literal "before the second period" rule says no, so this plan keeps them direct under `sase-42`.
2. Supporting `STANDARD` with ChangeSpec plus prefix creates a fourth structural level. The fold registry already
   accepts arbitrary tuple keys, but renderer gutter logic needs to become depth-aware to avoid cramped or misleading
   output.
3. This is TUI presentation behavior only, so it should stay in the Python `agent_groups` and `AgentList` layers rather
   than moving to `sase-core`.
