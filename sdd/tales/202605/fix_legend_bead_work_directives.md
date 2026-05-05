---
create_time: 2026-05-05 08:38:45
status: done
prompt: sdd/prompts/202605/fix_legend_bead_work_directives.md
---
# Fix Legend Bead Work Directives

## Context

The Telegram screenshot shows agents launched by `sase bead work <legend_id>` for proposed legend epics with both
`%approve` and `%epic` directives. The desired behavior is for those epic-planning agents to include `%epic`, which
auto-approves the plan result as an epic, but not `%approve`, which makes the whole agent autonomous.

The relevant rendering is centralized in `src/sase/bead/work.py`:

- `render_multi_prompt()` handles ordinary epic phase work and should continue to use `%approve` for phase agents and
  land agents.
- `render_legend_multi_prompt()` handles legend work. It currently adds `%approve` and `%epic` to each epic-planning
  assignment, then adds `%approve` to the final land agent.

Existing directive tests already confirm that `%epic` is plan-specific and does not imply full auto-approval.

## Implementation Plan

1. Update `render_legend_multi_prompt()` so legend epic-planning assignment segments emit `%epic` without `%approve`.
   Keep the final legend land segment unchanged with `%approve`, because the request targets the agents created to plan
   proposed epics and the screenshot/root segment already reflects the intended land-agent autonomy.

2. Tighten unit coverage in `tests/test_bead/test_work.py`:
   - Update the legend rendering snapshot to remove `%approve` from assignment segments.
   - Keep `%approve` on the final `bd/land_legend` segment.
   - Add or adjust assertions so the VCS-prefixed legend rendering test proves assignment segments contain `%epic` and
     do not contain `%approve`.

3. Tighten CLI coverage in `tests/test_bead/test_cli_work_legend.py`:
   - In dry-run tests, assert epic-planning segments do not contain `%approve`.
   - In live-launch capture, assert the launched query contains `%epic` once per proposed epic and `%approve` only for
     the final land segment.

4. Run focused tests for legend work/rendering first:
   - `pytest tests/test_bead/test_work.py -k Legend`
   - `pytest tests/test_bead/test_cli_work_legend.py`

5. Because this repo requires it after changes, run `just install` if needed and then `just check`. Investigate and fix
   any failures caused by the change.

## Non-Goals

- Do not change ordinary epic phase work rendering; phase agents and ordinary land agents should remain autonomous.
- Do not change directive parsing semantics for `%epic` or `%approve`.
- Do not change xprompt content in `src/sase/default_config.yml`; the issue is in the launch directives emitted by the
  legend multi-prompt renderer.
