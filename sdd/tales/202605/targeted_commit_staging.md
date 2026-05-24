---
create_time: 2026-05-24 17:04:07
status: done
prompt: sdd/prompts/202605/targeted_commit_staging.md
---
# Plan: Targeted Staging for Automatic Commits

## Context

The codebase has several automatic or semi-automatic commit paths. Most already stage targeted paths:

- `sase init memory` stages the generated memory paths it wrote.
- `sase init skills` / chezmoi deploy stages the rendered skill files it wrote.
- `sase bead work` stages changed bead-state files explicitly.
- The xprompt browser commit action stages the edited xprompt file.
- Version-controlled SDD plan commits call `sase commit` with one `-f` per discovered prompt/plan file.

The risky areas are:

- `src/sase/sdd/files.py::commit_sdd_files`, which uses `git add -A` in the local `.sase/sdd` repository even when
  callers just wrote one prompt/plan pair or initialized bead files.
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py::_stage_bead_dirs`, which stages the whole `sdd/beads/`
  pathspec during normal `sase commit` dispatch and post-commit amend.
- Commit-finalizer/skill instructions still document that omitting `-f` stages all changes; this is useful as an
  intentional manual escape hatch, but finalizer-triggered commits should steer agents to pass the listed files
  explicitly.

I will preserve the documented low-level `sase commit` behavior where a user intentionally omits `-f` to stage
everything. The implementation focus is on automatic callers and generated agent instructions so SASE-owned commit paths
do not accidentally sweep unrelated files into commits.

## Implementation Plan

1. Add targeted git path discovery for SDD commits.
   - Extend `commit_sdd_files` with an optional `paths` argument.
   - Resolve supplied files/directories relative to the SDD git root.
   - Use `git ls-files --modified --others --deleted --exclude-standard -z -- <paths...>` to compute concrete changed
     files.
   - Run `git add -- <changed-files...>` instead of `git add -A`.
   - When no `paths` are provided, keep the local-SDD repository behavior by enumerating changed files under `.` and
     staging that explicit changed-file list.

2. Pass known SDD paths from automatic callers.
   - In plan approval handling, pass the prompt and plan paths returned by `write_sdd_files` into `commit_sdd_files` for
     non-version-controlled SDD mode.
   - In local bead initialization, pass `.gitignore` and the local bead directory to `commit_sdd_files` so
     initialization commits only the generated bead store artifacts.

3. Make provider bead staging targeted.
   - Replace `git status --porcelain sdd/beads/` plus `git add sdd/beads/` with changed-file enumeration under
     `sdd/beads/`.
   - Use `git add -- <changed bead files>` for both pre-commit bead staging and post-commit bead amend.
   - Keep the existing best-effort semantics: bead staging should not derail the main commit unless the explicit
     `git add` fails in the same way the old add could have failed.

4. Tighten finalizer-triggered commit guidance.
   - Update `build_commit_instruction_message` so finalizer prompts tell agents to include `-f` for each listed file
     they intend to commit and to omit `-f` only when intentionally staging every change in that repository.
   - Update the generated `sase_git_commit` skill source to keep the manual escape hatch but strongly prefer repeatable
     `-f` flags for finalizer-triggered commits.
   - Because skill files are generated, run `sase init-skills --force` after changing the skill source if that command
     is available in this workspace.

5. Add regression tests.
   - Add a local SDD commit test showing an unrelated dirty file is not staged/committed when `paths` names only the
     prompt/plan files.
   - Add a git provider dispatch test showing bead staging enumerates and stages concrete bead-state files rather than
     `sdd/beads/` or `git add -A`.
   - Update finalizer instruction tests for the new `-f` guidance.
   - Adjust existing tests that assert `git add -A` only where the behavior remains explicitly manual.

6. Verify.
   - Run targeted pytest for the changed surfaces.
   - Run `just install` and `just check` as required by the repo instructions after code changes.
