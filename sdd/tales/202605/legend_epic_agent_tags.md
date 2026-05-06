---
create_time: 2026-05-05 22:14:50
status: done
prompt: sdd/prompts/202605/legend_epic_agent_tags.md
---
# Plan: Legend-Aware Epic Work Agent Tags

## Problem

`sase bead work <epic_id>` renders all phase and land agents with `%tag:<epic_id>`. That is correct for standalone
epics, but wrong for epics that are children of a legend bead. In that case, agents launched from the epic work
automation should share the legend-level tag so the full legend workflow stays grouped under one agent tag.

Legend work already renders `%tag:<legend_id>` for epic-planning agents and the legend land agent. The gap is the later
epic work pass: once a linked epic exists under a legend, its phase agents and epic land agent still use
`%tag:<epic_id>`.

## Current Shape

- Epic work planning is built in Rust via `bead_build_epic_work_plan` and exposed through `src/sase/bead/work.py`.
- `EpicWorkPlan` currently carries `epic_id`, waves, land agent name, and land waits. It does not carry the parent
  legend ID or launch tag.
- `render_multi_prompt()` hardcodes `_tag_directive(plan.epic_id)` for every phase segment and the epic land segment.
- `render_legend_multi_prompt()` already hardcodes `_tag_directive(plan.legend_id)`.
- Linked epics are represented as plan beads with `tier=epic` and `parent_id` set to the legend bead ID, created through
  `plan(<plan_file>,<legend_id>)`.

## Target Behavior

- If the target epic bead has a parent bead whose tier is `legend`, every agent segment rendered by
  `sase bead work <epic_id>` uses `%tag:<legend_id>`.
- If the target epic has no legend parent, behavior remains unchanged: `%tag:<epic_id>`.
- The xprompt arguments remain bead-specific: `#bd/work_phase_bead:<phase_id>` and `#bd/land_epic:<epic_id>` do not
  change.
- Agent names and wait dependencies remain unchanged.
- Legend work rendering remains unchanged.

## Implementation Approach

1. Extend the epic work plan model with an explicit tag field.
   - Add `launch_tag_id` or similarly named field to Rust `EpicWorkPlanWire`.
   - Resolve it in `build_epic_work_plan_from_issues()`:
     - default to `epic_id`
     - if `epic.parent_id` points to an existing plan bead with `tier=legend`, set it to that parent ID
   - Mirror the field in Python `EpicWorkPlan` and `_plan_from_payload()`.

2. Use the explicit tag during rendering.
   - Replace `_tag_directive(plan.epic_id)` in `render_multi_prompt()` with `_tag_directive(plan.launch_tag_id)`.
   - Keep xprompt references and workflow wait names unchanged.

3. Preserve relationship metadata while adding legend context when available.
   - Keep `epic_bead_id` and phase `bead_id` fields unchanged.
   - When `plan.launch_tag_id != plan.epic_id`, add `legend_bead_id` to the common workflow links and per-agent links
     for epic work launches.
   - This keeps graph metadata consistent with the user-visible grouping tag without changing which bead each agent is
     actually working.

4. Add focused regression coverage.
   - Rust unit coverage in `../sase-core/crates/sase_core/src/bead/work.rs`: linked epic under a legend yields
     `launch_tag_id == legend_id`; standalone epic yields `launch_tag_id == epic_id`.
   - Python rendering coverage in `tests/test_bead/test_work_rendering.py`: linked epic phase and land segments contain
     `%tag:<legend_id>` while still referencing phase and epic xprompts by their original bead IDs.
   - CLI coverage in `tests/test_bead/test_cli_work_epic.py`: seed a legend, create an epic child under it,
     launch/dry-run work, and assert every rendered `%tag:` uses the legend ID and the workflow link env carries both
     `legend_bead_id` and `epic_bead_id`.
   - Existing standalone epic tests should continue asserting `%tag:<epic_id>`.

5. Verification.
   - Run the focused bead work tests first:
     `pytest tests/test_bead/test_work_rendering.py tests/test_bead/test_cli_work_epic.py tests/test_bead/test_work_epic_plan.py`
   - Because this repo requires it after changes, run `just install` if needed and then `just check` before finishing.

## Risks And Notes

- This crosses the Python/Rust boundary because work-plan construction is already shared backend behavior. Keeping the
  tag resolution in the Rust work plan avoids diverging frontend behavior later.
- The launch tag should only promote to the parent ID when the parent is actually a legend bead. A missing or non-legend
  parent should fall back to the epic ID rather than silently misgrouping agents.
- The plan intentionally does not rename agents or alter wait dependencies; `%tag:` is only grouping metadata.
