---
create_time: 2026-07-07 15:52:14
status: done
prompt: sdd/prompts/202607/epic_work_auto_tale.md
---
# Epic Work `%auto:tale` Plan

## Goal

Change epic-tier `sase bead work` launches so phase worker agents and the final epic lander agent use `%auto:tale`
instead of bare `%auto`. The practical outcome is that when those agents submit implementation or landing plans, SASE
auto-approves them through the tale path, commits the approved plan into `sdd/tales/`, and still continues into the
normal coder/follow-up execution path.

## Current Behavior

The epic work renderer in `src/sase/bead/work.py` builds one multi-prompt segment per open phase bead plus one final
`bd/land_epic` segment. Both segment types currently append bare `%auto` after the model directive and before any `%w`
wait directive. Bare `%auto` is normal plan auto-approval: it runs the follow-up work but does not commit the proposed
plan as an SDD tale.

The directive and plan-approval layers already support `%auto:tale`; no new parser or approval semantics are needed.
Existing behavior maps tale auto-approval to a committed `sdd/tales` plan while preserving the follow-up execution path.

## Scope

Implement this for epic-tier phase and land prompts only:

- Phase worker segments rendered by `render_multi_prompt()`.
- Final epic lander segments rendered by `render_multi_prompt()`.

Keep these behaviors unchanged:

- Agent names, force-reuse `%name:!`, group directives, wait dependencies, VCS/ChangeSpec prefixes, and model routing.
- Legend epic-planning segments, which already use `%auto:epic`.
- Legend land segments, which are `land_legend` prompts rather than epic lander prompts and are outside this request.
- Directive parsing and plan-approval machinery, because `%auto:tale` already exists.

## Implementation Plan

1. Update `src/sase/bead/work.py` in `render_multi_prompt()`:
   - Replace the phase segment's appended `%auto` directive with `%auto:tale`.
   - Replace the final epic land segment's appended `%auto` directive with `%auto:tale`.
   - Preserve directive order exactly: `%name`, `%group`, `%model`, `%auto:tale`, optional `%w`, then the bead xprompt.
   - Consider a small local constant only if it improves readability; avoid broader refactors.

2. Update renderer and CLI tests:
   - Refresh exact expected multi-prompt strings in `tests/test_bead/test_work_rendering.py`.
   - Refresh the diamond snapshot in `tests/test_bead/test_work_epic_plan.py`.
   - Refresh dry-run assertions in `tests/test_bead/test_cli_work_epic_launch.py`.
   - Refresh the fast planned bead-work adapter fixture in `tests/test_launch_planned_bead_work.py`.
   - Strengthen assertions where useful so they check `%auto:tale` exactly; avoid weak `"%auto" in segment` checks that
     would pass for both bare `%auto` and `%auto:tale`.

3. Update documentation:
   - Update `docs/beads.md` so epic-tier work is documented as emitting `%auto:tale` for every phase and epic land
     segment, with the reason that submitted plans are committed to `sdd/tales/`.
   - Update `docs/blog/posts/beads-and-sdd.md` where it currently describes epic work segments as using bare `%auto`.
   - Leave general `%auto` directive docs alone unless they contain a specific stale claim about epic-tier bead work.

4. Verify behavior:
   - Run `just install` first, because these workspaces can be stale.
   - Run targeted tests for the affected surface:
     `pytest tests/test_bead/test_work_rendering.py tests/test_bead/test_work_epic_plan.py tests/test_bead/test_cli_work_epic_launch.py tests/test_launch_planned_bead_work.py`.
   - Run a focused grep/review for `%auto` in the touched epic-work files to ensure no epic-tier phase/land prompt still
     relies on bare `%auto`, while expected legend-only bare `%auto` remains.
   - Run `just check` before finishing, since this changes repo files.

## Acceptance Criteria

- `sase bead work <epic_id> --dry-run` shows `%auto:tale` in every phase worker segment and in the final `bd/land_epic`
  segment.
- Epic work phase/land tests fail if the renderer regresses to bare `%auto`.
- Legend epic creation still uses `%auto:epic`, and legend land behavior remains unchanged.
- Full repository checks pass.
