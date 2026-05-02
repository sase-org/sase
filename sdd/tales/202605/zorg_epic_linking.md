---
create_time: 2026-05-02 15:29:21
status: done
prompt: sdd/prompts/202605/zorg_epic_linking.md
---
# Fix Epic Bead Legend Linking

## Problem

The `zorg` snapshot shows an epic bead created as `zorg-2`, with phase beads `zorg-2.1` through `zorg-2.5`. It should
have been created as a child of the existing legend bead `zorg-1`, which would have allocated the epic ID as `zorg-1.1`.

The artifact trail shows the root cause clearly:

- The original planning prompt asked for epic #1 from `sdd/legends/202605/zorg_v1_mvp.md`.
- That legend file already had `legend_bead_id: zorg-1` in frontmatter.
- The generated epic plan copied into `sdd/epics/202605/zorg_epic1_foundations.md` did not include `legend_bead_id`.
- The `.epic` follow-up prompt was generated as: `#gh:zorg #bd/new_epic:sdd/epics/202605/zorg_epic1_foundations.md`
- `bd/new_epic` only links an epic when either a second xprompt argument is provided or the epic plan frontmatter
  contains `legend_bead_id`.
- With neither signal present, the epic-creation agent intentionally ran
  `sase bead create --type plan(sdd/epics/202605/zorg_epic1_foundations.md) --tier epic`, so the Rust bead allocator
  correctly created the next top-level ID, `zorg-2`.

This was not an ID allocator bug. The relationship was known at the legend source, but the plan-approval-to-epic handoff
dropped it.

## Goal

Make future "Epic" approvals preserve the source legend parent automatically when the approved plan came from a legend
that already has a `legend_bead_id`.

Specifically, when launching the `.epic` follow-up, SASE should generate:

```text
#bd/new_epic:sdd/epics/202605/zorg_epic1_foundations.md,zorg-1
```

instead of:

```text
#bd/new_epic:sdd/epics/202605/zorg_epic1_foundations.md
```

The existing `bd/new_epic` prompt will then tell the agent to create the linked epic with:

```bash
sase bead create --type plan(<plan_file>,zorg-1) --tier epic
```

which allocates `zorg-1.1`.

## Non-Goals

- Do not retroactively rename the existing `zorg-2` bead graph in this change. It already has launched phase agents and
  commits tied to those IDs.
- Do not change the core bead ID allocation semantics. They are correct: parentless plans get top-level IDs, linked
  plans get hierarchical child IDs.
- Do not require every planning agent to remember to copy `legend_bead_id` into the epic plan. The fix should make the
  automation robust even when the plan only references the source legend in prose.

## Implementation Plan

1. Add a small inference helper near the epic follow-up construction in `src/sase/axe/run_agent_exec_plan.py`.

   The helper should find a `legend_bead_id` in this order:
   - Parse the generated SDD epic plan frontmatter. If it already contains `legend_bead_id`, use it.
   - Parse the SDD prompt snapshot linked by the epic plan frontmatter (`prompt: ...`) and the epic plan body for
     references to `sdd/legends/.../*.md` or `.sase/sdd/legends/.../*.md`.
   - Resolve those legend paths relative to the workspace or SDD root.
   - Parse candidate legend frontmatter and collect `legend_bead_id` values.
   - If exactly one unique legend bead ID is found, use it. If none or more than one is found, do not guess.

2. Thread the inferred ID into the `.epic` follow-up prompt.

   In the `plan_result.action == "epic"` branch, after computing `plan_ref`, append the second positional xprompt
   argument only when inference returns an ID:

   ```text
   #bd/new_epic:{plan_ref},{legend_bead_id}
   ```

   Keep the no-parent prompt unchanged when no safe ID is found.

3. Keep `bd/new_epic` as the enforcement point for bead creation.

   The existing xprompt already accepts `legend_bead_id` as its second input and tells the agent to use
   `--type plan(<plan_file>,<legend_bead_id>)`. No CLI behavior needs to change for the primary fix.

   Optionally tighten the wording in `src/sase/default_config.yml` to make the second argument path explicit, but avoid
   broad prompt churn.

4. Add regression tests.
   - A test where the original/linked prompt references `sdd/legends/202605/zorg_v1_mvp.md`, that legend has
     `legend_bead_id: zorg-1`, and the resulting `.epic` prompt includes
     `#bd/new_epic:sdd/epics/202605/zorg_epic1_foundations.md,zorg-1`.
   - A test where the generated epic plan itself already has `legend_bead_id`; that direct metadata should be used.
   - A test where no legend metadata exists; the prompt should remain unchanged.
   - A test where multiple distinct legend IDs are discoverable; the prompt should remain unchanged rather than making a
     bad parent choice.
   - A focused xprompt expansion test confirming `#bd/new_epic:<plan>,zorg-1` renders linked-epic instructions.

5. Verify with focused tests first, then repo checks.
   - Run the new/changed tests around epic approval and xprompt tags.
   - Because this repo requires it after changes, run `just install` if needed and then `just check`.

## Expected Outcome

Next time a user approves an epic plan that came from a legend with `legend_bead_id: zorg-1`, the `.epic` follow-up
agent receives the parent ID explicitly. The agent no longer has to rediscover the relationship, and the bead CLI will
create `zorg-1.1` instead of `zorg-2`.
