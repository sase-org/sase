---
create_time: 2026-05-22 23:12:20
status: done
prompt: sdd/prompts/202605/plan_tag_relative_paths.md
---
# Plan: Keep Plan References Repo-Relative

## Problem

Approved tale plans are expected to be persisted into the project `sdd/` tree and referenced afterward with paths that
are relative to the project repository, for example `sdd/tales/202605/example.md`. Some recorded plan references are
absolute paths instead, which makes ChangeSpec/commit metadata less portable across workspaces and machines.

## Current Findings

- The VCS commit-message `PLAN=` tag is appended in `src/sase/workflows/commit/precommit_hooks.py::handle_sase_plan`.
  For in-repo files, it already attempts to convert the plan path to a repo-root-relative path before appending the tag.
- The ChangeSpec commit drawer `| PLAN:` is built in two places:
  - `src/sase/workflows/commit/commit_tracking.py::append_commits_entry`
  - `src/sase/workspace_provider/changespec.py::create_changespec_for_workflow`
- Both drawer paths currently read `SASE_PLAN` directly and only replace `$HOME` with `~`. If `SASE_PLAN` is an absolute
  in-repo SDD path, those functions can record an absolute `| PLAN:` line even though the durable plan lives under
  `sdd/`.
- Local history in this checkout shows current git commit bodies with repo-relative `PLAN=...` tags, while historical
  ChangeSpec drawers contain absolute `| PLAN:` paths. That points at the drawer formatting path as the reproducible
  current root cause. The fix should still harden the `PLAN=` path normalization so both metadata forms use one
  consistent rule.

## Approach

1. Add a small shared helper for plan reference display paths used by commit metadata.
   - Input: raw `SASE_PLAN`, workspace/repo root, and home directory.
   - Output priority:
     1. repo-relative path when the plan resolves under the current project root;
     2. `.sase/sdd/...` style path when appropriate for local SDD paths under a project-local `.sase/sdd`;
     3. `~`-shortened path for non-repo home paths;
     4. original/normalized path for truly external paths.
   - Use `Path.resolve()`/`os.path.realpath()` style comparison rather than string-prefix checks so symlinks and
     equivalent absolute spellings do not leak absolute paths.

2. Route every `SASE_PLAN` consumer through the helper.
   - Update `handle_sase_plan` so the `PLAN=` commit-message tag and `_plan_path` staging still point at the correct
     file, while the tag value is computed through the shared helper.
   - Update `append_commits_entry` so post-commit ChangeSpec `| PLAN:` drawers use the same repo-relative display value.
   - Update `create_changespec_for_workflow` so initial ChangeSpec commit drawers use the same value.

3. Add focused regression tests.
   - `handle_sase_plan`: in-repo absolute `SASE_PLAN` produces `PLAN=sdd/tales/...`, including when the path is already
     in `sdd/` and no copy is needed.
   - `append_commits_entry`: absolute in-repo `SASE_PLAN` records `| PLAN: sdd/tales/...`, not an absolute path.
   - `create_changespec_for_workflow`: absolute in-repo `SASE_PLAN` in a newly created ChangeSpec records a
     repo-relative plan path.
   - Preserve existing behavior for genuinely external plan paths, either `~`-shortened or unchanged.

4. Verify with targeted tests first, then run the repository check required after code changes.
   - Targeted pytest for commit workflow artifacts, commit tracking, and changespec workflow params.
   - Because this repo requires it after file changes, run `just install` if needed and then `just check`.

## Risks and Boundaries

- Do not rewrite existing ChangeSpec history in this change. The goal is to stop new absolute in-repo paths from being
  emitted.
- Keep local/non-version-controlled SDD behavior intact: only version-controlled tale approvals should add `PLAN=` to
  VCS commit messages.
- Avoid moving this into Rust core unless the investigation finds cross-frontend path normalization already belongs
  there. The current bug is in Python commit/ChangeSpec metadata formatting.
