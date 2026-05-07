---
create_time: 2026-05-07 19:39:58
status: done
prompt: sdd/prompts/202605/vcs_replayable_selection.md
---
# Plan: Prevent Non-Launchable VCS Refs From Becoming Replay State

## Problem

The `sase ace` warning shows `last_agent_selection.json` contained a replay selection whose `project_name` was
`"project"`. That file drives the `@/<space>` / space repeat flow, so the TUI later tried to replay a project-scoped
launch for `project` and correctly cleared it as stale because `project` was not launchable.

The plausible write path is the VCS launch path in `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py`: when a
submitted prompt resolves a VCS/workspace ref, it updates the saved `@/<space>` selection to the resolved ref.
Separately, the same path records the leading VCS tag into `vcs_xprompt_mru.json` before full VCS resolution has proven
the ref is launchable/replayable. That means a syntactically valid tag or a provider-resolved-but-not-replayable project
can leak into durable UI state.

## Goals

- Never persist a `last_agent_selection.json` entry for a project/CL unless the owning project is launchable by
  `ProjectSelectModal` rules.
- Never keep non-launchable known project refs in the VCS xprompt MRU.
- Preserve valid behavior for normal project refs, CL refs, known-project fallback refs, and non-workspace workflows
  like `#cd`.
- Add focused regression tests that reproduce the stale `"project"` class of failure.

## Implementation Approach

1. Add a small helper near the VCS selection save path that validates `ctx.project_name` with `is_launchable_project()`
   before writing `self._last_custom_agent_selection` and `save_last_agent_selection()`.
2. If validation fails, do not save or mutate the in-memory last selection. This avoids overwriting a good previous
   selection with a stale one.
3. Move or narrow VCS MRU recording so it records only resolved/canonical refs that are safe for future cycling. Keep
   non-workspace refs such as `#cd:~` if existing behavior expects them in MRU, but reject known project prefixes whose
   project file exists and is not launchable.
4. Strengthen `sase.history.vcs_xprompt_mru` so recording a stale known project prefix prunes it instead of moving it to
   the front.
5. Add tests:
   - `_run_agent_launch_body` does not save `SelectionItem(project_name="project")` when the resolved project is not
     launchable.
   - a valid resolved VCS ref still saves the expected replay selection.
   - `record_vcs_xprompt_usage("#gh:project")` does not preserve the entry when `project` is known but not launchable.
6. Run targeted tests for the changed modules, then `just install` if needed and `just check` before finishing because
   code files changed.

## Expected Outcome

The stale warning may still appear once for already-corrupt persisted files, but new launches and MRU cycling should not
create that state again. Valid project and CL replay remains intact.
