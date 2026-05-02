---
create_time: 2026-05-01 12:56:06
status: done
prompt: sdd/prompts/202605/epic_phase_vcs_prompts.md
---
# Plan: Preserve VCS Workspace For Epic Phase Agents

## Problem

`sase bead work` renders a multi-prompt for all phase agents plus the final land agent. For normal epics, each segment
currently starts with directives like `%name` and `%approve`, followed by `#bd/work_phase_bead:<id>` or
`#bd/land_epic:<id>`, but no explicit workspace workflow. The multi-prompt launcher intentionally normalizes bare
segments to `#cd:~`, so those phase/land agents can start in home mode instead of the repository workspace.

ChangeSpec-attached epics already receive VCS prefixes through `ChangeSpecLaunchContext`, but non-ChangeSpec epics do
not. That matches the `sase ace` symptom: the agent metadata shows `cd(cd_ref=~)` rather than the intended VCS workflow.

## Scope

Fix the epic integration so phase and land agent prompts include the appropriate leading VCS workflow reference whenever
the current workspace can be resolved to a SASE VCS project. Keep non-VCS or unrecognized test projects working as they
do today.

## Implementation

1. Add a small VCS launch context for non-ChangeSpec epic work.
   - Store the workflow name (`git`, `gh`, `hg`, etc.) and project name.
   - Render it as `#<workflow>:<project>` at the beginning of every phase and land segment.

2. Refactor the existing ChangeSpec launch context path carefully.
   - Preserve the current ChangeSpec behavior: first phase uses `#<workflow>:<project> #pr...`; later phase and land
     segments use the ChangeSpec ref.
   - Avoid duplicating project/workflow detection logic between ChangeSpec and non-ChangeSpec epics.

3. Resolve VCS context in `handle_bead_work`.
   - For ChangeSpec-attached epics, keep the current required validation and error handling.
   - For regular epics, attempt to infer the current SASE project and workflow from the current workspace. If resolution
     fails, fall back to the existing bare rendering so local/non-VCS bead tests and workflows are not broken.

4. Add targeted tests.
   - Unit-test `render_multi_prompt` for a non-ChangeSpec VCS context so every segment starts with `#git:sase`.
   - CLI-test `sase bead work --dry-run` with mocked project/workflow resolution so the generated multi-prompt includes
     `#git:sase` before every phase and land prompt.
   - Keep existing ChangeSpec rendering assertions passing.

5. Verify.
   - Run the targeted bead work tests first.
   - Because this repo’s memory says file changes require it, run `just install` if needed, then `just check` before
     final response.
