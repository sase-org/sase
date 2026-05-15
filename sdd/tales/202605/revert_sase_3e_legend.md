---
create_time: 2026-05-14 19:20:01
status: done
prompt: sdd/prompts/202605/revert_sase_3e_legend.md
---
# Revert sase-3e Legend Work

## Goal

Revert the work associated with legend bead `sase-3e` ("Rust Daemon and Indexed Projections Performance Rebuild") across
the main SASE repository and maintained sibling repositories. Preserve unrelated later work where possible, and do not
modify memory files.

## Scope Discovered

- Main repo: `/home/bryan/projects/github/sase-org/sase_102`
  - `sase bead show sase-3e` reports the legend as closed with 11 closed child epic beads.
  - The linked legend plan is `sdd/legends/202605/rust_daemon_indexed_projections_1.md`.
  - The current branch is clean.
  - Active current-history commits include the `sase-3e` series from the legend prompt/plan through epic 11, plus later
    no-daemon research commits that explicitly reference `sase-3e`.
  - Earlier first-attempt `sase-3e` commits were already reverted in history; those revert commits should not be
    inverted or the old work would come back.
- Sibling/plugin repos:
  - `../sase-core` is clean and contains current `sase-3e` commits for the Rust backend contracts, local daemon,
    projections, scheduler, provider host, and diagnostics.
  - `../sase-github`, `../sase-telegram`, and `../sase-nvim` are clean and do not show exact `sase-3e` references in
    current history or current files from the inspection pass. They still need final status checks, but no revert is
    currently expected there.

## Revert Strategy

1. Confirm all involved worktrees are still clean immediately before reverting.
2. In the main repo, revert the currently active `sase-3e` commits in reverse chronological order using
   `git revert --no-commit`, excluding already-existing "Revert ..." commits and excluding unrelated `sase-3ec` commits.
   - Include the legend SDD/bead commits, child epic/phase commits, implementation commits, verification metadata, and
     explicit `sase-3e` no-daemon research commits.
   - Resolve conflicts by preserving non-`sase-3e` behavior and removing daemon/projection/provider-host/scheduler
     surfaces introduced by the legend.
3. In `../sase-core`, revert the current non-revert commits whose subjects reference `sase-3e`, also in reverse
   chronological order with `git revert --no-commit`.
   - Resolve conflicts by restoring the pre-legend backend contract surface while preserving unrelated fixes such as
     later hidden-workflow-state and `sase-3i` revert work.
4. Re-check `../sase-github`, `../sase-telegram`, and `../sase-nvim` with `git status`, exact reference search, and
   recent-history search. If a related commit is found after the second pass, revert it with the same no-commit
   approach; otherwise leave those repos untouched.
5. Audit remaining references:
   - `rg 'sase-3e|rust_daemon_indexed_projections|rust_daemon_epic|local daemon|provider host|daemon scheduler'` in the
     main repo and `../sase-core`.
   - Triage expected historical references in git logs versus live files. Live files should not contain the reverted
     legend artifacts unless they predate `sase-3e` or are unrelated general documentation.
6. Verification:
   - Main repo: run the repo's normal check target from memory, starting with `just check`.
   - Modified sibling repos: run `just check` in each modified plugin/sibling repo. This is required for `../sase-core`
     if it is modified.
   - If `just check` is too broad or fails for environmental reasons, capture the failure and run focused tests around
     touched areas where possible.
7. Final state:
   - Leave the reverts as uncommitted working-tree/index changes unless explicitly asked to commit.
   - Report changed repositories, verification results, and any unresolved residual references or conflicts.

## Risk Controls

- Do not use destructive history operations such as `git reset --hard` or `git checkout --`.
- Do not revert user/unrelated dirty changes; stop and report if a worktree becomes dirty for reasons unrelated to this
  task.
- Avoid reverting earlier "Revert ..." commits, because doing so would reapply older abandoned `sase-3e` attempts.
- Keep sibling/plugin repo changes limited to repositories with confirmed related `sase-3e` work.
