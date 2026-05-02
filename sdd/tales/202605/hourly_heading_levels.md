---
create_time: 2026-05-01 13:02:08
status: done
prompt: sdd/prompts/202605/hourly_heading_levels.md
---
# Plan: Promote 4-hour BY_DATE windows to level-2 visual headings

## Context

The recent hourly subgroup work added this BY_DATE hierarchy in both CLs and Agents:

- date bucket (`Today`, `Yesterday`, etc.)
- 4-hour window (`8AM-12PM`, `12PM-4PM`, etc.)
- 1-hour window (`09:00`, `14:00`, etc.)
- leaf row

The model layer already represents the hierarchy distinctly:

- CLs: `ChangeSpecGroupRow.level == 1` for the 4-hour/date subgroup and `level == 2` for the hourly subgroup.
- Agents: `GroupRow.level == 1` for the 4-hour window and `level == 2` for the hourly subgroup.

The issue is in rendering, not grouping: both time-window levels currently use the same "name-root" visual treatment,
which reads like the same heading level.

## Goal

Make 4-hour BY_DATE window headings render as level-2 headings, while keeping 1-hour window headings as level-3
headings.

Concretely:

- Date bucket remains the strongest L0 heading.
- 4-hour window uses the existing L1/ChangeSpec-style visual language (`▎`, cooler accent, light rule).
- 1-hour window keeps the existing L2/name-root-style visual language (`▸`, teal label, dim gray rule).
- Group keys, collapse behavior, ordering, and row hierarchy remain unchanged.

## Implementation Outline

1. Update Agents banner rendering in `src/sase/ace/tui/widgets/_agent_list_render_banner.py`.
   - Add a BY_DATE-specific branch for `group.level == 1` before the generic name-root fallback.
   - Use the existing ChangeSpec L1 style constants for these 4-hour window headings.
   - Keep `group.level == 2` BY_DATE hourly headings on the name-root fallback.
   - Update the function docstring so it no longer says 4-hour and 1-hour windows intentionally share the same visual
     treatment.

2. Update Agents tier gutter styling in `src/sase/ace/tui/widgets/_agent_list_build.py`.
   - `compute_tier_styles()` currently makes BY_DATE L1 4-hour banners contribute `_NAME_ROOT_BANNER_BRANCH_STYLE` to
     descendants.
   - Change real 4-hour windows to contribute `_CHANGESPEC_BANNER_RULE_STYLE`, matching their promoted L1/level-2 visual
     treatment.
   - Preserve the existing special handling for `(no time)` so it does not add an extra descendant tier.

3. Update CL banner rendering in `src/sase/ace/tui/widgets/_changespec_list_banner.py`.
   - CL grouped rendering does not currently receive the grouping mode, but BY_DATE L1 4-hour/day/week subgroups and
     BY_PROJECT/BY_STATUS sibling-root banners all share `level == 1`.
   - Prefer the consistent interpretation that all CL `level == 1` subgroup headings should use the level-2 visual
     style, and only `level >= 2` should use the level-3/name-root visual style.
   - This promotes BY_DATE 4-hour headings without needing to thread grouping mode through the CL renderer.
   - The tradeoff is that CL BY_PROJECT/BY_STATUS sibling-root headings also become level-2 visual headings. That is
     consistent with their model level and with the user's request for level-based heading semantics.

4. Update tests to assert visual hierarchy, not just row counts.
   - Agents:
     - Add/update a BY*DATE widget test proving the 4-hour banner starts with one bucket gutter plus the L1 glyph
       (`│  ▎ 8AM-12PM ...`) and includes `_CHANGESPEC_BANNER*\*` styles.
     - Update the hourly gutter test to expect the second gutter segment to use `_CHANGESPEC_BANNER_RULE_STYLE` instead
       of `_NAME_ROOT_BANNER_BRANCH_STYLE`.
     - Keep an assertion that hourly headings still start with `│  │  ▸ HH:00`.
   - CLs:
     - Add/update a grouped BY_DATE widget test that inspects the 4-hour banner prompt and the hourly banner prompt.
     - Assert 4-hour uses `▎` / ChangeSpec-style colors and hourly uses `▸` / name-root-style colors.
     - Check that `banner_natural_width()` still accounts for the correct prefix length if the prefix calculation
       changes.

5. Documentation cleanup.
   - Update nearby comments/docstrings in `_agent_list_styling.py`, `_agent_list_render_banner.py`,
     `_changespec_list_banner.py`, and any affected tests to describe the three visual heading levels accurately.
   - If `docs/ace.md` has explicit visual-treatment text for BY_DATE headings, update it to say 4-hour windows render as
     L1/level-2 headings and hourly windows render as L2/level-3 headings.

## Verification

Run focused tests first:

```bash
just install
uv run pytest \
  tests/ace/tui/widgets/test_agent_list_grouping_gutter.py \
  tests/ace/tui/widgets/test_agent_list_grouping_buckets.py \
  tests/ace/tui/widgets/test_changespec_list_grouped.py \
  tests/ace/tui/models/test_agent_groups_grouping_mode_hour.py \
  tests/ace/tui/models/test_changespec_groups_layout.py
```

Then run the repo gate after source changes:

```bash
just fmt
just check
```

## Non-goals

- Do not change group key shapes.
- Do not move 4-hour or 1-hour rows between model levels.
- Do not alter sorting, collapse semantics, row selection, or jump target enumeration.
- Do not introduce a new color palette unless the existing L1 style proves unusable.
