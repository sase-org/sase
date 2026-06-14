---
create_time: 2026-06-14 10:46:22
status: done
prompt: sdd/prompts/202606/agents_tab_revert_agent_commits.md
---
# Implement Agents-Tab `,r` Revert For Done Agents

## Goal

Add a leader-mode `,r` action on the `sase ace` Agents tab that reverts commits associated with the currently selected
done agent. Use research Option C: discover associated commits by exact `AGENT=` commit-message tags and apply git
reverts. The action must include committed `sdd/` prompt/plan files when those commits carry the same agent provenance,
and it must accept all statuses that mean the agent has finished its work.

## Product Behavior

- `,r` is only meaningful on the Agents tab with a focused, rendered agent row whose status is terminal/done.
- The action first discovers candidate commits in a background task, then shows a confirmation modal with the agent
  identity, scope, commit count, short SHAs, subjects, and notable `sdd/` paths.
- On confirmation, a second tracked background task reverts the previewed commits and refreshes the Agents tab when
  complete.
- The UI should reject active/input states such as `RUNNING`, `STARTING`, `WAITING`, `PLAN`, and `QUESTION`.
- Revert work must be visible and cancellable through the existing task queue machinery.

## Key Decisions

1. Resolve the existing `,r` conflict by moving the leader-mode runners action to a new key and reserving `,r` for
   `revert_agent`.
   - Update `src/sase/default_config.yml`, `LeaderModeKeymaps`, help modal, command catalog, command availability, and
     footer leader-mode display together.
   - Keep the direct Agents-tab `r` retry behavior unchanged.

2. Keep this first backend in Python, isolated behind a reusable module.
   - The Rust core currently has pure git-output parsers, while subprocess/VCS side effects and commit-runtime tags live
     in this Python repo.
   - Add a focused Python backend such as `src/sase/ace/revert_agent.py`; avoid reusing ChangeSpec revert because that
     prunes/abandons whole CLs.

3. Use exact `AGENT=` tag matching as the primary association.
   - Parse candidate commit messages and match tag lines exactly rather than relying only on `git log --grep`.
   - For family-aware plan-chain rows, allow a family scope using `sase.plan_chain.agent_family_base` and
     `agent.agent_family`; otherwise default to exact selected-agent scope.

4. Avoid partial revert commits.
   - Discover commits newest-first.
   - Re-run clean-worktree and commit-existence checks in the final revert task.
   - Apply `git revert --no-commit <newest..oldest>` and then create one revert commit if all reverse patches apply.
   - On conflict or failure before commit, run `git revert --abort` and return a precise error.
   - Push the current branch when an `origin` remote and branch are available; no-op for local/no-remote/detached cases.

5. Close the raw SDD tagging gap for future commits.
   - Add a helper that composes `TYPE=<kind>` with runtime `AGENT=`/`MACHINE=` when runtime identity is available.
   - Use it in raw SDD auto-commit paths that currently only write `TYPE=sdd` or `TYPE=init`.
   - Existing behavior without an agent environment remains unchanged.

## Implementation Steps

1. Status predicate
   - Add `is_revertable_agent_status(status)` near existing TUI-facing status predicates.
   - Return true for `DISMISSABLE_STATUSES` and any displayed `FAILED*` status, including `FAILED (RETRIED)`.
   - Add focused tests for allowed and rejected statuses.

2. Backend
   - Add dataclasses for discovered commits, preview results, and revert results.
   - Resolve canonical agent name from `agent_meta.json` when possible, falling back to `Agent.agent_name`.
   - Resolve workspace from the selected agent and validate it is a git worktree.
   - Discover commits by parsing commit messages for exact `AGENT=<name>` tag lines.
   - Include changed paths per commit so the confirmation modal can show `sdd/` coverage.
   - Reject dirty/in-progress git states before preview and before final revert.
   - Revert the previewed commits newest-first using the no-commit batch flow, commit the revert, and push if
     applicable.
   - Write a small `revert_result.json` in the selected agent artifacts dir after a successful revert.

3. TUI action and task wiring
   - Add an `AgentRevertMixin` under `src/sase/ace/tui/actions/agents/` and include it in `AgentsMixinCore`.
   - Add `_start_revert_selected_agent()` or similar, called only from leader-mode dispatch.
   - Key handler responsibilities stay lightweight: selected-agent capture, status/name/workspace gate, and tracked task
     submission.
   - Preview task completion opens `ConfirmRevertAgentModal`.
   - Confirmation submits the final revert tracked task with a per-agent dedup key.
   - Completion notifies success/error and schedules the existing Agents-tab async refresh.

4. Modal
   - Add `ConfirmRevertAgentModal` with `y/n/escape/q` bindings.
   - Keep layout compact: title, scope, commit count, short SHA/subject rows, `sdd/` path summary, and clear warning
     that this creates a revert commit.
   - Export the modal from `src/sase/ace/tui/modals/__init__.py`.

5. Keymap, footer, help, and command palette
   - Add `revert_agent: "r"` to leader-mode config/defaults.
   - Move `runners` to an available non-conflicting leader key.
   - Update leader dispatch for `revert_agent`.
   - Update the leader footer to show revert only when the selected Agents-tab row is revertable.
   - Update command catalog labels/tab scope and command availability.
   - Update the Agents help modal and keymap tests.

6. SDD tagging hardening
   - Add runtime-tag composition helper in `workflows/commit/runtime_tags.py`.
   - Update `src/sase/sdd/_commit.py` and `src/sase/llm_provider/commit_finalizer_git.py` raw SDD commit sites.
   - Add tests showing `TYPE=sdd` remains alone without runtime identity and adds `AGENT=` when `SASE_AGENT_NAME` is
     set.

7. Tests and validation
   - Add backend git tests for exact tag matching, family matching, `sdd/` path discovery, dirty-worktree rejection,
     no-commit behavior, successful revert, and conflict abort.
   - Add TUI/unit tests for leader `,r` dispatch, preview task submission, modal confirmation, footer visibility, help,
     command palette availability, and keymap defaults.
   - Run `just install` before repo checks, then targeted tests while iterating, then `just check` before final
     response.

## Risks And Mitigations

- Historical raw SDD commits without `AGENT=` cannot be safely associated. The implementation will report that no tagged
  commits were found rather than guessing.
- Revert conflicts are expected in active branches. The no-commit batch flow and abort path should leave the repo clean
  if a conflict happens before the revert commit is created.
- Preview can become stale before confirmation. The final revert task will revalidate cleanliness and commit existence,
  and it will revert the previewed SHAs rather than silently expanding scope.
- This is git-only. Non-git providers should fail with an explicit unsupported message instead of using ChangeSpec prune
  semantics.
