---
create_time: 2026-06-14 11:46:16
status: done
prompt: sdd/prompts/202606/bulk_agent_revert.md
---
# Bulk Agent Revert Plan

## Goal

Extend the Agents-tab leader keymap `,r` so that, when agent marks exist, it reverts the commits associated with every
marked agent instead of only the selected agent.

The bulk operation must:

- Use the existing marked-agent behavior on the Agents tab.
- Revert all commits associated with the marked agents.
- Apply reverts newest-first across the full combined commit set.
- Handle conflicts and other git failures robustly.
- Be atomic across the whole marked set: if any revert fails, leave the workspace with no partial revert changes or
  partial revert commit from the failed bulk operation.

## Current Shape

The existing single-agent flow lives in `src/sase/ace/tui/actions/agents/_revert.py` and already follows the right TUI
performance pattern:

- The key handler validates the selected agent cheaply.
- A tracked background preview task calls `preview_agent_revert`.
- A confirmation modal displays the commit set.
- A tracked background execute task calls `execute_agent_revert`.
- Successful completion schedules an Agents-tab async refresh.

The backend in `src/sase/ace/revert_agent.py` discovers commits by parsing `AGENT=<name>` commit tags from `git log`,
already returning commits newest-first for a single agent/family scope. It executes reverts using
`git revert --no-commit`, creates one revert commit, and best-effort pushes.

Marked agents are stored as `self._marked_agents` identities. Other bulk Agents-tab flows resolve them through
`self._agents_with_children`, prune stale marks, and keep long-running work out of the Textual event loop.

## Design

### 1. Add explicit bulk backend types

Extend `sase.ace.revert_agent` with batch-oriented dataclasses while preserving the current single-agent API:

- `RevertTarget`: resolved agent display/name/workspace/artifacts/scope metadata for one agent row.
- `BulkRevertPreview`: workspace, targets, deduplicated newest-first commits, skipped targets, and error details.
- `BulkRevertResult`: success/message/reverted SHAs/push status/error, plus enough detail for task output and tests.

Keep `RevertPreview` and `RevertResult` for the single-agent path, but allow the confirmation modal to render either a
single-agent preview or bulk preview.

### 2. Resolve marked agents in the TUI, then preview in one task

Change `_start_revert_selected_agent` so Agents-tab behavior is:

- If `self._marked_agents` is non-empty, route to a new `_start_revert_marked_agents`.
- Otherwise keep the current selected-agent behavior.

The bulk TUI method should:

- Resolve live marked rows from `self._agents_with_children`.
- Drop stale marks or warn if no marked rows remain.
- Filter to `is_revertable_agent_status`; warn and skip non-revertable marked rows.
- Resolve each target's agent name, workspace dir, family base, and artifacts dir using the same helpers as the
  single-agent path.
- Reject the bulk operation if no valid revertable targets remain.
- Reject mixed workspaces for the first implementation. A single `git revert --no-commit` transaction cannot be atomic
  across multiple repositories. The error should tell the user that marked agents span multiple workspaces and no
  changes were applied.
- Submit one tracked `revert_preview` task with a dedup key derived from the sorted target names and workspace.

### 3. Discover the combined commit set newest-first

Add `preview_agents_revert(targets)` in the backend.

It should:

- Validate the shared workspace is a git worktree.
- Validate the worktree is clean before discovery.
- Scan git history once and match commits against all target agent tags/family scopes.
- Deduplicate commits by full SHA so marking both a family parent and a child cannot revert the same commit twice.
- Preserve git-log newest-first order across the full combined commit set, not per-agent concatenation order.
- Track which targets matched at least one commit and which targets were skipped/no-match for user feedback.
- Return a non-ok preview if no commits are found.

This avoids cross-agent ordering bugs and scales better than running one full git log per marked agent.

### 4. Execute as one atomic git transaction

Add `execute_agents_revert(preview_or_shas, targets)` or a lower-level shared execute helper that both single and bulk
paths can use.

The bulk execute flow should:

- Revalidate the workspace is git and clean.
- Revalidate every previewed commit still exists.
- Capture `HEAD` before mutating anything.
- Run one `git revert --no-commit --no-edit <all-shas-newest-first>` command.
- Create one commit summarizing the bulk operation and listing affected agents and commits.
- Write per-agent `revert_result.json` artifacts only after the revert commit succeeds.
- Push using existing push semantics unless we decide to make push errors fatal later; local atomicity should not depend
  on remote availability.

Rollback behavior:

- On any revert conflict or git failure, first run `git revert --abort`.
- Then verify `HEAD` and `git status --porcelain`.
- If the operation dirtied the worktree or advanced `HEAD`, force the workspace back to the captured pre-operation
  `HEAD` with `git reset --hard <head-before>`.
- Return an error message that includes the failing git output and states that the bulk revert was rolled back.

Because the precondition is a clean worktree, the hard reset fallback only discards changes made by the attempted bulk
revert. This is the explicit atomicity guard missing from relying on `git revert --abort` alone.

The existing single-agent `execute_agent_revert` should be updated to use the same rollback helper so it benefits from
the stronger failure handling without duplicating git plumbing.

### 5. Confirmation modal updates

Update `ConfirmRevertAgentModal` so it can present bulk previews:

- Title can remain "Revert Agent Commits" or become "Revert Agent Commits" for both modes.
- Show target count and workspace for bulk previews.
- Show total commit count, newest-first commit list, and SDD summary.
- Include skipped/non-matching target summary without requiring a second modal.
- Warning text should say bulk mode creates a single revert commit for all marked agents and rolls back the whole
  operation on failure.

Keep the existing `y/n/q/escape` bindings and keep the modal display compact with truncation.

### 6. Footer, leader-mode, and command palette availability

Make `,r` discoverable/runnable when either:

- The selected agent is revertable, or
- There is at least one marked agent.

Specific updates:

- In leader-mode handling, `,r` should call the marked-agent path when marks exist.
- In footer leader bindings, show `revert marked (N)` or similar when marks exist; otherwise retain `revert agent`.
- In command palette availability, `leader.revert_agent` should be available on Agents tab when `ctx.mark_count > 0`,
  even if the focused row is a group banner or non-revertable agent.
- Keep the keymap itself unchanged: `revert_agent` remains bound to leader subkey `r`, so `default_config.yml` should
  not need a key change.

### 7. Tests

Backend tests in `tests/ace/test_revert_agent.py`:

- Bulk preview scans once and returns combined commits newest-first across multiple agents.
- Bulk preview deduplicates overlapping family/agent matches.
- Bulk preview rejects dirty worktree, non-git workspace, no matching commits, and mixed workspaces.
- Bulk execute creates one revert commit for all marked-agent commits.
- Bulk execute conflict rolls back to the original `HEAD`, leaves status clean, and preserves file contents.
- Bulk execute commit failure or injected git failure also rolls back cleanly.
- Existing single-agent tests continue to pass and should cover the shared rollback helper where practical.

TUI action tests in `tests/ace/tui/test_revert_agent_action.py`:

- No marks keeps current selected-agent preview behavior.
- Marks route to one bulk preview task.
- Stale/invalid marks warn and do not submit.
- Non-revertable marked agents are skipped with feedback; all-invalid marks do not submit.
- Mixed-workspace previews surface an error and do not open execute flow.
- Confirming a bulk preview submits one bulk execute task and successful completion schedules one Agents-tab refresh.

Footer/command tests:

- Leader footer advertises `revert marked (N)` when marks exist.
- Command palette availability allows `leader.revert_agent` with marks even when no focused revertable agent exists.
- Existing keymap default tests remain unchanged for `,r`.

## Verification

After implementation, run:

```bash
just install
pytest tests/ace/test_revert_agent.py tests/ace/tui/test_revert_agent_action.py tests/ace/tui/test_confirm_revert_agent_modal.py tests/test_keybinding_footer_agent.py tests/test_command_catalog.py tests/test_command_catalog_guards.py tests/test_keymaps_defaults.py
just check
```

If `just check` is too slow or blocked by unrelated environment issues, run the targeted pytest set above and report the
blocker clearly.

## Open Decisions

- Push failures: the current single-agent flow treats "no push" as a successful local revert. I plan to preserve that
  behavior for bulk unless we explicitly want remote push failure to make the operation fail and rollback the local
  revert commit.
- Mixed workspaces: I plan to reject them rather than attempt cross-repository atomicity. True cross-workspace atomicity
  would require a coordinated transaction across repositories and push state, which is outside the existing single-agent
  revert model.
