---
create_time: 2026-05-05 21:36:24
status: done
prompt: sdd/prompts/202605/epic_legend_agent_tags.md
---
# Plan: Tag Epic and Legend Work Agents by Bead ID

## Goal

Ensure every agent created by the epic and legend `sase bead work` integrations carries a `%tag:<bead_id>` directive,
where `<bead_id>` is the controlling epic or legend bead ID.

For epic work, this means every phase agent and the final land-epic agent should be tagged with the epic bead ID. For
legend work, every epic-planning agent and the final land-legend agent should be tagged with the legend bead ID.

## Current Shape

The relevant orchestration lives in `src/sase/bead/cli_work.py`, while prompt rendering lives in
`src/sase/bead/work.py`.

`render_multi_prompt()` emits epic work segments with:

- optional VCS/ChangeSpec prefix
- `%name:<agent_name>`
- `%approve` for phase agents
- optional `%w:<agent_names>`
- the phase or land xprompt reference

`render_legend_multi_prompt()` emits legend work segments with:

- optional VCS prefix
- `%name:<agent_name>`
- `%epic` for epic-planning agents
- optional `%w:<agent_names>`
- the planning request or land xprompt reference

The `%tag` directive is already supported by directive extraction, validated through
`sase.ace.agent_tags.validate_tag_name`, written into `agent_meta.json`, and persisted for workflow agents when a
`cl_name` is present. Bead IDs used here are expected to be compatible with tag validation (`^[A-Za-z0-9_-]+$`), and
existing tests already use IDs such as `l1` and generated IDs with dashes.

## Implementation

1. Add a small rendering helper in `src/sase/bead/work.py`, for example `_tag_directive(bead_id: str) -> str`, returning
   `%tag:<bead_id>`.

2. Update `render_multi_prompt()` so each epic-created segment includes `%tag:<plan.epic_id>`:

- phase agent segments: after `%name:<assignment.agent_name>` and before `%approve`
- land agent segment: after `%name:<plan.land_agent_name>` and before any `%w`

This keeps identity directives grouped near the top of each segment and preserves the existing VCS prefix as the first
line when present.

3. Update `render_legend_multi_prompt()` so each legend-created segment includes `%tag:<plan.legend_id>`:

- epic-planning segments: after `%name:<assignment.agent_name>` and before `%epic`
- land agent segment: after `%name:<plan.land_agent_name>` and before any `%w`

4. Do not change `cli_work.py` launch orchestration unless tests reveal a gap. The existing directive pipeline is the
   correct single path for agent tags.

## Tests

Update focused rendering and integration tests:

- `tests/test_bead/test_work_epic_plan.py`
  - Update the diamond snapshot to include `%tag:e1` in every segment.
  - Assert all rendered segments contain `%tag:e1`.

- `tests/test_bead/test_work_legend_plan.py`
  - Update the legend snapshot to include `%tag:l1` in every segment.
  - Assert all rendered segments contain `%tag:l1`, including the land segment.
  - Ensure VCS-prefixed legend segments still start with `#git:sase\n` and include the tag after `%name`.

- `tests/test_bead/test_cli_work_epic.py`
  - Assert the captured live-launch query contains `%tag:<epic_id>` once per launched agent.
  - Assert dry-run VCS and ChangeSpec wrapper output includes `%tag:<epic_id>`.

- `tests/test_bead/test_cli_work_legend.py`
  - Assert dry-run and live-launch queries include `%tag:<legend_id>` once per created agent.

## Verification

Run targeted tests first:

```bash
pytest tests/test_bead/test_work_epic_plan.py tests/test_bead/test_work_legend_plan.py tests/test_bead/test_cli_work_epic.py tests/test_bead/test_cli_work_legend.py
```

Because this repo’s instructions require it after changes, run:

```bash
just install
just check
```

If `just check` is too broad or fails for unrelated environmental reasons, capture the exact failure and report it.
