---
create_time: 2026-06-08 17:34:28
status: done
prompt: sdd/prompts/202606/fix_generated_skill_staleness_1.md
---
# Fix Generated Skill Staleness For sase-4g

## Goal

Finish the remaining validation work discovered after verifying and closing the `sase-4g` epic: generated provider skill
files are stale relative to the in-repo `sase_var` skill source.

## Plan

1. Regenerate provider skill files from the canonical skill source with the repository's generated-skills workflow.
2. Inspect the generated diffs to confirm they only reflect the intended `sase_var` skill wording/behavior update.
3. Re-run repository validation with `just check`; if it fails, address only issues directly caused by this work.
4. Confirm the epic plan frontmatter remains `status: done` and the associated verification commands still pass.
5. Close `sase-4g` as the final bead step, or confirm it remains closed if the bead was already closed earlier in this
   verification pass.
