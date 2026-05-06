---
create_time: 2026-05-05 20:04:51
status: done
prompt: sdd/prompts/202605/landing_agents_manual_approval.md
---
# Landing Agents Manual Plan Approval

## Context

Epic and legend bead automation launch multi-prompt agent batches from `sase bead work`. The phase workers are meant to
run autonomously, but the final landing agents are different: they verify that a larger body of work is actually
complete and, when it is not, create a follow-up plan for corrective work. Those corrective plans should require
explicit user approval.

The current render path sets `%approve` on the final landing segments:

- `render_multi_prompt()` adds `%approve` to the `#bd/land_epic:<epic_id>` segment.
- `render_legend_multi_prompt()` adds `%approve` to the `#bd/land_legend:<legend_id>` segment.

That directive becomes `agent_meta.json` field `approve: true`, so `sase ace` shows the agent as autonomous and plan
approval can be bypassed. The desired behavior is narrower: remove `%approve` only from the landing agents created by
these integrations.

## Proposed Change

Update the prompt rendering in `src/sase/bead/work.py`:

- Keep `%approve` on epic phase worker segments produced by `render_multi_prompt()`.
- Keep `%epic` on legend epic-planning segments produced by `render_legend_multi_prompt()`, since that is the existing
  mechanism for plan-to-epic handling.
- Remove `%approve` from the final `land_lines` for both `#bd/land_epic:<epic_id>` and `#bd/land_legend:<legend_id>`.
- Leave wait directives, VCS wrappers, ChangeSpec wrappers, agent names, and workflow-link metadata unchanged.

This is a Python rendering change only. The Rust core currently computes the work plan shape and agent names, while this
repo renders xprompt directives and launch wrappers; no Rust core API change is needed for this behavior.

## Test Plan

Update the existing expectations that currently assert `%approve` on landing segments:

- `tests/test_bead/test_work_epic_plan.py`
  - Snapshot should still show `%approve` for every phase worker.
  - Final `#bd/land_epic` segment should have `%name` and `%w`, but no `%approve`.
- `tests/test_bead/test_work_rendering.py`
  - ChangeSpec rendering snapshots should preserve VCS/PR routing and phase `%approve`, while omitting `%approve` from
    the final landing segment.
- `tests/test_bead/test_work_legend_plan.py`
  - Legend epic-planning segments should still use `%epic` and no `%approve`.
  - Final `#bd/land_legend` segment should have no `%epic` and no `%approve`.
- `tests/test_bead/test_cli_work_legend.py`
  - Dry-run/live assertions should expect zero `%approve` directives in legend launches, because the epic-planning
    agents use `%epic` and the land agent is now manual-approval.

Add or strengthen focused assertions so the behavior is explicit rather than only implied by large rendered-string
snapshots:

- The final epic landing segment does not contain `%approve`.
- The final legend landing segment does not contain `%approve`.
- Phase worker segments still contain `%approve`.

After implementation, run focused pytest coverage first:

```bash
pytest tests/test_bead/test_work_epic_plan.py \
  tests/test_bead/test_work_rendering.py \
  tests/test_bead/test_work_legend_plan.py \
  tests/test_bead/test_cli_work_legend.py
```

Because this repo requires it after changes, run:

```bash
just install
just check
```

## Risks And Compatibility

The main compatibility risk is any consumer that expected landing agents to auto-approve ordinary `#plan` output. That
is the behavior we are intentionally removing for epic/legend landing agents. The launcher, wait graph, VCS routing, and
artifact relationship metadata should be unaffected because those are encoded separately from `%approve`.

The change should not affect manual user prompts, generic `%approve`, `%epic`, or TUI toggling of auto-approval. It only
changes the multi-prompt text emitted for the automated landing agents.
