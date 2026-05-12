---
create_time: 2026-05-12 14:34:26
status: done
prompt: sdd/prompts/202605/sase36_completion.md
---
# SASE-36 Completion Plan

## Context

Verification found that `sase-36` is not ready to close. The linked epic plan says every Athena-visible chop should
produce compact, useful no-op and action output, but the current workspace still has gaps:

- Main-repo built-in script chops that delegate to `HookJobRunner`, `CheckCycleRunner`, and `wait_checks` can still
  complete no-op runs with no output.
- Athena xprompt workflows print only sparse step outputs and do not consistently explain scan scope, threshold
  decisions, launched child names, marker paths, or no-op reasons.
- Chezmoi `gh_actions_fix` and `sase-telegram` changes exist in sibling worktrees and appear directionally correct, but
  they need focused checks as part of closeout.

## Plan

1. Add compact completion summaries to the main SASE built-in chop helper paths without changing behavior or exit codes.
   Cover hook/mentor/workflow/pending/comment-zombie/suffix/orphan/stale cleanup and full/comment check cycles with
   inspected counts, update/start/cleanup counts, and explicit no-op reasons.
2. Add a summary to `wait_checks` that reports projects/artifacts/waiting markers inspected, ready files written,
   skipped markers, and no-op reasons.
3. Improve the Athena xprompt workflows to emit bounded operational decisions for no-op and launch paths, including
   scanned limits, file counts, test outcomes, threshold decisions, launched agent names, marker paths, marker updates,
   and no-op reasons.
4. Add or extend focused tests for the new main-repo output contract where practical, especially no-op helper summaries
   and wait-check summaries.
5. Run focused SASE tests, then `just check` if non-bead source files changed. Run relevant checks in the touched
   sibling repos: chezmoi `just check` and `sase-telegram` focused/full checks as feasible.
6. Re-read `sase bead show` for all `sase-36` children, verify their notes are addressed, and then close the epic bead.
7. After closing the epic bead, run `just pyvision` if available.
8. Update `sdd/epics/202605/chop_output_coverage.md` frontmatter to `status: done`.
