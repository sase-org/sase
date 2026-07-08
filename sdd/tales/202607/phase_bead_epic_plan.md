---
create_time: 2026-07-08 00:09:37
status: done
prompt: sdd/prompts/202607/phase_bead_epic_plan.md
---
# Show Epic Plan Context for Phase Beads

## Context

`sase bead show <plan-bead>` currently renders the bead's own `design` path in a `PLAN` section. Phase beads do not
carry their own design path; they carry a `parent_id` pointing at the plan/epic bead that owns the larger body of work.
When a user targets a phase bead, the output already shows the parent bead but does not surface that parent's plan file.

The change is presentation-only CLI behavior. It should stay in the Python bead CLI rendering path rather than moving
backend/domain logic into the Rust core.

## Proposed Behavior

For `sase bead show <phase-id>`, resolve the phase's parent bead once while rendering the existing `PARENT` section. If
the parent resolves to a plan bead and has a non-empty `design` path, render an additional plan section for the parent
bead.

Use wording that makes the association explicit, for example:

```text
EPIC PLAN
  From parent epic bead beads-1 · Alpha Epic
  plans/alpha.md
```

If the parent plan bead is not actually tiered as an epic, fall back to similarly explicit generic wording such as
`PARENT PLAN` / `From parent plan bead ...` so the output remains accurate for older or non-epic plan beads.

The existing `PLAN` section for a targeted plan bead should remain unchanged, because in that case the plan file belongs
directly to the bead being shown.

## Implementation Plan

1. Refactor `src/sase/bead/cli_query.py` lightly so `handle_bead_show` keeps the resolved parent issue in a local
   variable instead of discarding it after the `PARENT` section.

2. Extract the existing design-path display logic into a small local helper so both the direct `PLAN` section and the
   new parent-plan section preserve the current relative-path behavior for in-tree SDD storage and absolute/external
   path behavior otherwise.

3. After rendering the target bead's description, notes, and ChangeSpec metadata, render plan information with these
   rules:
   - If the target issue has its own `design`, keep printing the existing `PLAN` section.
   - Else, if the target is a phase and its resolved parent is a plan bead with a `design`, print an explicit
     parent-context section (`EPIC PLAN` for epic parents, otherwise `PARENT PLAN`).
   - If the parent cannot be resolved or has no design path, omit the new section and keep the existing non-crashing
     behavior.

4. Add CLI coverage:
   - Add a golden `sase bead show beads-1.1` case that proves a phase bead shows the parent epic's plan path with
     explicit parent-epic wording.
   - Add focused handler coverage for a phase whose parent plan has no design path, proving the command does not print a
     misleading parent-plan section.
   - Keep the existing plan-bead golden output unchanged.

5. Verify with targeted tests while developing, then run the repository-required checks after implementation changes:
   - `just install`
   - targeted bead CLI tests such as
     `pytest tests/test_bead/test_cli_golden.py tests/test_bead/test_cli_changespec.py tests/test_bead/test_cli_search.py`
   - `just check`

## Acceptance Criteria

- Showing an epic bead still prints its direct `PLAN` section exactly as before.
- Showing a phase bead under an epic prints the epic's plan file and labels it as coming from the parent epic bead, not
  from the phase itself.
- Missing parent beads or parent beads without plan files do not introduce errors or misleading empty sections.
- Full-format bead search automatically inherits the new rendering because it already delegates to `handle_bead_show`.
