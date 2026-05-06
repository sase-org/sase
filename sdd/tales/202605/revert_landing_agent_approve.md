---
create_time: 2026-05-06 00:51:48
status: done
---
# Revert Landing Agent Approve Directive

## Goal

Restore the `%approve` directive on landing agents created by `sase bead work` for both epic and legend workflows.

The target change is the behavioral inverse of commit `5074543f`
(`fix: require manual approval for landing agent plans`), but it should not blindly revert intervening work. Current
behavior and newer changes should be preserved unless they directly conflict with restoring landing-agent autonomy.

## Current Understanding

- `render_multi_prompt()` in `src/sase/bead/work.py` renders ordinary epic work:
  - phase worker segments still include `%approve`;
  - the final `#bd/land_epic:<epic_id>` segment currently does not.
- `render_legend_multi_prompt()` renders legend work:
  - legend epic-planning segments include `%epic` and intentionally do not include `%approve`;
  - the final `#bd/land_legend:<legend_id>` segment currently does not include `%approve`.
- Later changes added `%tag:<controlling_bead>` directives to generated segments. Those tags should stay.
- The requested revert is scoped to landing agents. It should not restore `%approve` to legend epic-planning agents.

## Implementation Plan

1. Update epic landing prompt rendering.
   - In `render_multi_prompt()`, add `%approve` to `land_lines` after the `%name` / `%tag` directives and before
     wait/xprompt content.
   - Preserve VCS and ChangeSpec prefix behavior.
   - Preserve `%tag:<plan.launch_tag_id>` on the landing segment.

2. Update legend landing prompt rendering.
   - In `render_legend_multi_prompt()`, add `%approve` to `land_lines` after `%name` / `%tag`.
   - Preserve `%epic` only on legend epic-planning segments.
   - Preserve the invariant that legend epic-planning segments do not include `%approve`.

3. Update focused tests.
   - `tests/test_bead/test_work_epic_plan.py`: restore the epic render snapshot so the final land segment includes
     `%approve`, and assert every segment includes `%approve`.
   - `tests/test_bead/test_work_rendering.py`: update ChangeSpec render snapshots so final land segments include
     `%approve`; keep phase assertions intact.
   - `tests/test_bead/test_work_legend_plan.py`: update legend render snapshots and VCS assertions so only the final
     land segment includes `%approve`.
   - `tests/test_bead/test_cli_work_legend.py`: update dry-run/live assertions to expect one `%approve` directive for
     the legend land agent, while keeping zero `%approve` on epic-planning segments.

4. Verify behavior.
   - Run targeted tests first:
     - `pytest tests/test_bead/test_work_epic_plan.py tests/test_bead/test_work_rendering.py tests/test_bead/test_work_legend_plan.py tests/test_bead/test_cli_work_legend.py`
   - Because this repo’s instructions require it after file changes, run `just install` if needed and then `just check`.

## Non-Goals

- Do not change directive parsing semantics for `%approve` or `%epic`.
- Do not change `sase bead work` scheduling, pre-claiming, ready flags, workflow metadata, or launch context behavior.
- Do not modify historical SDD/tale files except for this planning artifact.
