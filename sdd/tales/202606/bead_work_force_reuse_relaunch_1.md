---
create_time: 2026-06-16 09:40:53
status: done
prompt: sdd/prompts/202606/bead_work_force_reuse_relaunch_1.md
---
# Bead Work Force-Reuse Relaunch Plan

## Context

`sase bead work <epic-or-legend> -y` is intended to be retryable. If a previous phase agent, epic land agent, legend
epic-planning agent, or legend land agent already owns the deterministic bead-work name, the relaunch should
deliberately replace that old owner.

The current renderer already emits force-reuse name directives such as `%name:!sase-4q.1` and `%name:!sase-4q`. A dry
run for `sase-4q` confirms that all phase and land segments carry the `!` form. The failure Bryan saw means the
prompt-level contract is not enough: the live launch path still lets permanent agent-name validation see an ordinary
`%name:<name>` collision after the bead-work-specific wipe/rewrite handshake.

One concrete reproduction class is visible in the local registry: `sase-4q` is reserved by a completed `home` agent
family via `workflow_name=sase-4q`, while the actual artifact name is `sase-4q--code`. The fix must therefore handle any
registered owner of the planned bead-work name, not only artifacts whose `agent_meta.name` is exactly the planned phase
or land name.

## Goals

- Make live `sase bead work` relaunches honor the `%name:!<agent_name>` contract for every generated epic and legend
  segment.
- Overwrite old deterministic bead-work owners, including stale completed agents, dismissed owners, planned
  reservations, and still-live old agents.
- Keep `--dry-run` side-effect-free while making it clear which names would be force-reused.
- Preserve bead mutation ordering: do not mark ready or preclaim phase beads until name reuse preparation has succeeded.
- Keep ordinary non-bead launch surfaces protected from accidental `%name:!` reuse unless they already have their own
  confirmation path.

## Non-Goals

- Do not change the deterministic naming scheme for phase, land, or legend-planning agents.
- Do not add a new CLI flag. `-y/--yes` and the existing interactive confirmation are the confirmation path for this
  trusted bead-work launch.
- Do not relax normal `%name:<name>` collision behavior outside bead work.

## Design

1. Introduce a narrow bead-work launch preparation helper.

   The helper should accept the rendered multi-prompt and the exact expected names from the computed work plan. It will
   parse force-reuse directives from the prompt, verify they match the expected plan names, wipe those owners, verify
   the wipe did not report errors or leave the names reserved, then rewrite `%name:!<name>` to `%name:<name>` for the
   existing launcher.

   Keeping this helper in or near `src/sase/bead/cli_work.py` keeps the trust boundary explicit: bead work is the caller
   choosing to reuse these generated names. The general launcher should continue to reject raw `%name:!` from
   unconfirmed non-TUI surfaces.

2. Stop treating planned bead-work names as launch blockers.

   The current epic and legend live-collision checks should no longer abort live launches for names that are part of the
   computed plan. For live launches, force-reuse preparation should own replacement, including terminating old live
   owners through `wipe_agent_name_for_reuse`.

   For `--dry-run`, keep a warning path, but reword it from "would block live launch" to "would be force-reused" so the
   dry run reflects the new behavior.

3. Include legacy epic land owners in the cleanup set.

   Epic land agents now use `<epic_id>`, but older runs may have used `<epic_id>.land`. Preserve the existing
   compatibility awareness by adding that legacy name to the epic cleanup set when it differs from the current land
   name. It is not rendered in the new prompt, so it should be an additional cleanup target rather than an expected
   `%name:!` directive.

4. Make wipe failures fail early and clearly.

   Today the bead-work helper catches wipe exceptions and continues to launch after rewriting to ordinary `%name:`. That
   can surface later as `Agent name '<name>' is taken`, which hides the real failed reuse step.

   The new helper should fail before any bead mutation if a wipe raises, if an `AgentNameWipeResult` contains errors, or
   if the registry still reports an owner for a force-reused name after rebuild. The error should name the affected
   agent name and tell the user that forced reuse cleanup failed.

5. Keep launch rollback behavior scoped.

   If launch fails after successful force-reuse cleanup, the existing phase preclaim and `is_ready_to_work` rollback
   remains appropriate. The old agents were deliberately overwritten as part of confirmed relaunch and should not be
   restored.

## Test Plan

- Update epic collision tests in `tests/test_bead/test_cli_work_collisions.py`:
  - a live phase-name owner is force-reused and launch proceeds instead of refusing;
  - a live current land-name owner is force-reused and launch proceeds;
  - a live legacy `<epic_id>.land` owner is cleaned up and launch proceeds;
  - dry run warns that matching names would be force-reused and does not mutate beads or artifacts.
- Add/adjust epic launch tests in `tests/test_bead/test_cli_work_epic_launch.py` to assert the force-reuse preparation
  sees every expected phase and land name before the launcher receives rewritten ordinary `%name:` directives.
- Add a regression test for the `sase-4q` class of owner: a registry reservation where the target name appears as
  `workflow_name` while `name` is a plan/code family child such as `<epic_id>--code`. Relaunch should wipe that owner
  before validation.
- Update legend tests in `tests/test_bead/test_cli_work_legend.py` so legend epic-planning and land names are
  force-reused rather than refused.
- Run focused tests first:
  - `.venv/bin/python -m pytest tests/test_bead/test_cli_work_collisions.py`
  - `.venv/bin/python -m pytest tests/test_bead/test_cli_work_epic_launch.py`
  - `.venv/bin/python -m pytest tests/test_bead/test_cli_work_legend.py`
  - `.venv/bin/python -m pytest tests/test_bead/test_work_rendering.py`
- Run `just check` if the focused suite is green.

## Documentation

Update `docs/beads.md` so `sase bead work <id>` no longer claims live planned names block launch. The docs should say
live and stale deterministic bead-work owners are force-reused on confirmed launch, while dry run only reports what
would be replaced.

`docs/xprompt.md` already documents `%name:!` as the explicit confirmation form; only touch it if implementation details
change the general directive contract.
