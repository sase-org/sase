---
create_time: 2026-05-21 15:49:41
status: done
prompt: sdd/prompts/202605/fork_keymap_and_suffix.md
---
# Plan: Move Agent Forking to `f` and `.f<N>` Names

## Goal

Finish the user-facing rename from resume to fork for the Agents-tab continuation workflow:

- Pressing `f` on the Agents tab should open the fork prompt (`#fork:<name> ...`).
- Pressing `r` on the Agents tab should no longer fork/resume an agent.
- Newly generated fork-derived agent names should use `<target>.f<N>` instead of `<target>.r<N>`.

Keep unrelated resume concepts intact: `sase run --resume`, `sase commit --resume`, chat `--format resume`, hook/session
resume semantics, and legacy `#resume` transcript parsing.

## Findings

The current `r` Agents-tab behavior is not a dedicated resume keymap. It is the global `run_workflow` binding:

- CLs tab: `r` runs a ChangeSpec workflow.
- AXE tab: `r` runs a chop or re-runs a completed bgcmd.
- Agents tab: `action_run_workflow()` dispatches to `action_resume_agent()`.

The `f` key is already the global `edit_hooks` binding and is meaningful on the CLs tab. Changing `run_workflow` from
`r` to `f` globally would unnecessarily move CL/AXE workflow behavior and collide with CL hook editing. The safer change
is tab-specific: keep CL/AXE `r` behavior, move only the Agents-tab fork action onto the existing `f` key path.

Name allocation is centralized in `src/sase/agent/names/_resume.py`, with callers in single-agent launch, repeat launch,
and model/alt fan-out. Updating that allocator reaches all current fork-derived naming paths.

## Design

1. Add a fork-oriented action path for Agents-tab continuation.
   - Keep the existing prompt construction behavior: running named agents get `#fork:<name> %w:<name>`, completed agents
     get `#fork:<name>`, and VCS tags continue to be prepended when available.
   - Prefer adding `action_fork_agent()` and leaving `action_resume_agent()` as a compatibility alias, rather than
     forcing every internal symbol to be renamed in one pass.

2. Move the Agents-tab key trigger from `r` to `f` without disturbing other tabs.
   - Remove the Agents-tab dispatch from `BaseActionsMixin.action_run_workflow()` so `r` remains CL/AXE-only.
   - Teach `HookEditingMixin.action_edit_hooks()` to dispatch to `action_fork_agent()` when `current_tab == "agents"`.
   - Guard hook editing so `f` is a no-op outside CLs/Agents instead of accidentally editing hooks from another tab.

3. Update user-facing key labels and docs.
   - Agents footer should show `f fork` instead of `r resume`.
   - Agents help modal should describe `f` as forking chat as an agent.
   - `docs/ace.md` should list `f` for the Agents-tab fork action.
   - Leave CL help/docs showing `f` for edit hooks and `r` for run workflow.

4. Switch fork-derived name allocation to `.f<N>`.
   - Change `allocate_resume_name()` / `allocate_resume_names()` to return `<target>.f<N>`.
   - Keep legacy function names for now because they are internal API already used across launch paths and still parse
     legacy `#resume` references.
   - Treat existing legacy `.r<N>` descendants as reserving the same numeric slot as `.f<N>`. For example, if `foo.r1`
     exists, the next generated fork name should be `foo.f2`, avoiding two visually different "first fork" descendants
     of the same target.

5. Update focused tests.
   - Key/footer/help tests should assert the Agents-tab fork action is on `f`, and that `r` no longer appears for it.
   - Agent action tests should verify `action_run_workflow()` does not fork on Agents and `action_edit_hooks()` does.
   - Naming tests should assert `.f<N>` output, including legacy `.r<N>` slot reservation.
   - Repeat and fan-out tests should expect `.f<N>` names and `%wait` dependencies.
   - Existing legacy `#resume` parsing tests should remain so old transcripts keep working.

## Verification

Run targeted tests first:

- `pytest tests/test_agent_names.py tests/test_agent_names_extract.py tests/test_repeat_launcher.py tests/test_directives_split_models.py`
- `pytest tests/test_keymaps.py tests/test_keybinding_footer_agent.py tests/ace/tui/test_agent_wait_resume.py`

Then run repo-required validation:

- `just install` if the workspace environment is stale.
- `just check` before final response because this repo requires it after file changes.

Finally, run targeted `rg` checks so any remaining `.r<N>` or Agents-tab `r resume` references are either historical
fixtures/docs or intentionally preserved legacy compatibility coverage.
