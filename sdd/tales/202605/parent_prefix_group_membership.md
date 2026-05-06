---
create_time: 2026-05-05 22:51:00
status: done
prompt: sdd/prompts/202605/parent_prefix_group_membership.md
---
# Plan: Include Parent Marker Agents In Their Prefix Group

## Goal

Agents whose name is exactly `<foo>.<bar>` should participate in the same dotted-prefix subgroup as agents named
`<foo>.<bar>.<anything>`.

In the motivating `sase ace` snapshot, the `sase-42.3` agent currently renders directly under the `sase-42` root while
`sase-42.3.1` through `sase-42.3.6` render under the `sase-42.3` prefix subgroup. After this fix, `sase-42.3` should be
inside that `sase-42.3` subgroup too.

## Product Rules

1. Keep the existing name-root rule: the first segment before the first period is still the root group.
2. Treat the first two name segments as the prefix-group identity whenever the selected grouping name contains at least
   one period.
   - `sase-42.3` -> root `sase-42`, prefix `sase-42.3`
   - `sase-42.3.1` -> root `sase-42`, prefix `sase-42.3`
   - `sase-42` -> root `sase-42`, no prefix
3. Prefix subgroup emission should be based on the full prefix membership, including exact parent-marker rows. This
   means `foo.bar` plus `foo.bar.1` is enough to show a `foo.bar` subgroup.
4. Exact parent-marker rows should render before their dotted descendants inside the prefix subgroup when timestamps or
   other mode-specific ordering do not impose a stronger ordering.
5. Preserve existing mode boundaries:
   - `BY_STATUS` continues to render bucket -> name root -> name prefix.
   - `STANDARD` continues to render project -> optional ChangeSpec -> name root -> name prefix.
   - `BY_DATE` continues to suppress name-root and prefix grouping entirely.
6. Preserve workflow-child inheritance: a workflow child should keep inheriting its top-level parent agent's root and
   prefix identity.

## Technical Design

1. Update `src/sase/ace/tui/models/agent_groups/_keys.py`.
   - Change `_name_prefix()` so exact two-segment names return their full name instead of `""`.
   - Keep dotless names returning `""`.
   - Apply the same behavior to the `display_name` fallback so unnamed agents remain consistent with named agents.
   - Add a small per-agent sort discriminator for prefix members, so an exact prefix marker such as `sase-42.3` sorts
     before descendants such as `sase-42.3.1` inside the emitted prefix group. This can be a helper derived from the
     selected grouping name rather than a renderer concern.

2. Reuse existing tree emission in `src/sase/ace/tui/models/agent_groups/_tree.py`.
   - Because prefix counts are already built from `_GroupingKeys.name_prefix`, including exact two-segment names in
     `_name_prefix()` should make them part of `prefix_indices`, `GroupRow.agent_indices`, summaries, collapse behavior,
     and `enumerate_group_keys()`.
   - Review the tree builder after the key change to confirm no special case still assumes prefix groups require at
     least two periods.
   - Keep fold keys unchanged: the prefix subgroup key remains `(*parent_key, name_root, name_prefix)`, for example
     `("Done", "sase-42", "sase-42.3")`.

3. Update documentation and comments only where they now state the old rule.
   - The previous tale explicitly said one-period parent markers remain direct children; replace that understanding in
     current code comments/docstrings with the new parent-marker membership rule.
   - Keep historical plan files unchanged unless the implementation needs a local note elsewhere.

## Test Plan

1. Model tree shape:
   - Add or update a `BY_STATUS` test shaped like the snapshot: `sase-42.3`, `sase-42.3.1`, and `sase-42.3.2` should
     render under a `("Done", "sase-42", "sase-42.3")` group.
   - Update the existing shared-prefix test that currently asserts the one-period parent remains direct under the root.
   - Add a minimal direct-plus-one-child case (`foo.bar`, `foo.bar.1`) to lock in that parent membership contributes to
     subgroup emission.

2. Ordering:
   - Assert the parent marker appears before its descendants inside its prefix group when all other ordering inputs are
     equivalent.
   - Preserve existing singleton suppression for unrelated prefixes: `sase-42.1.1` and `sase-42.2.1` without matching
     parent markers should not emit prefix subgroup banners.

3. Fold and enumeration:
   - Update prefix-collapse coverage so collapsing `("proj", "demo", "sase-42", "sase-42.2")` hides the exact
     `sase-42.2` marker as well as `sase-42.2.*` descendants.
   - Add or adjust `enumerate_group_keys()` coverage for a direct-plus-child pair to ensure the prefix key is
     enumerable.

4. Widget regression:
   - Add a focused `AgentList` grouping test under `BY_STATUS` proving the rendered option order places the exact
     parent-marker row after the prefix banner, not between the name-root banner and prefix banner.
   - Existing gutter and banner-style tests should continue to pass because the group depth is unchanged.

5. Verification:
   - Run `just install` first if the workspace environment needs refresh.
   - Run focused tests:
     `just test -- tests/ace/tui/models/test_agent_groups_* tests/ace/tui/widgets/test_agent_list_grouping*`
   - Run the required full check before final handoff: `just check`

## Risks

1. Returning a prefix for all two-segment names changes subgroup emission from "two descendants share a prefix" to "two
   related rows share a prefix." This is intentional for parent-marker agents, but tests should verify it does not
   create noisy singleton groups.
2. If there are many exact two-segment names with no descendants, they remain singleton prefixes and should still render
   directly under their root, matching existing behavior.
3. The change is presentation-layer grouping only and stays in the Python TUI model; it should not cross the Rust core
   boundary.
