---
create_time: 2026-06-14
updated_time: 2026-06-14
status: research
---

# Agents Tab Revert Done Agent Commits

## Question

Add a new `,r` keymap to the `sase ace` Agents tab that reverts any commits associated with the currently selected
done agent, including plan/prompt files that were committed under `sdd/`. The research question is how much work this
entails, what implementation shapes are available, and which path is worth taking.

## Short Answer

The TUI surface is small. The correctness problem is not. A direct leader-key action can be wired in a day or two if it
only handles the currently persisted `commit_result.json` SHA from ordinary `sase commit` runs. That version would not
reliably satisfy the SDD requirement, because SDD prompt/plan commits and "mark plan done" commits are not currently
recorded as a durable list of commit records associated with the agent.

The right implementation is a metadata-first revert flow:

- persist an append-only list of commit records for each agent run;
- include ordinary work commits, SDD prompt/plan commits, and SDD plan-status commits;
- have the Agents tab action resolve those records, confirm them, and run the revert in a tracked background task;
- only then bind the action to a key.

This is probably a 4-6 day implementation if limited to git/current providers and existing agent artifact conventions.
A cross-provider, reusable core API with complete PR/branch semantics is closer to 1-2 weeks.

## Current Code Findings

### The `,r` Key Conflicts Today

The default leader key for "runners" is already `r`:

- `src/sase/default_config.yml:183` defines `leader_mode.keys.runners: "r"`.
- `src/sase/ace/tui/keymaps/types.py` defines the typed leader-mode config.
- `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py` dispatches leader keys.
- `src/sase/ace/tui/widgets/keybinding_footer.py`, `src/sase/ace/tui/modals/help_modal/agents_bindings.py`, and
  `src/sase/ace/tui/commands/catalog.py` expose the same keys in the footer, help modal, and command palette.

So `,r` is not just a new action. It requires either moving the existing runners key or making `,r` context-sensitive
on the Agents tab. Moving `runners` is simpler and easier to document. A context-sensitive reuse is possible, but it
would add ambiguity to command-palette labels, help text, and repeat-last-leader behavior.

### Selected Agent Access Already Exists

The Agents tab already has a focused-row helper:

- `src/sase/ace/tui/actions/agents/_selection.py:17` has `_get_selected_agent()`.
- `src/sase/ace/tui/models/agent.py` stores the displayed `Agent`, including `status`, `raw_suffix`, `workspace_dir`,
  `artifacts_dir`, `diff_path`, and a limited `commit_entry_id`.
- `src/sase/ace/tui/models/agent_artifacts.py` resolves artifact directories for rows.

The TUI action can use the selected `Agent` and artifact directory without a new selection model.

### "Done Agent" Needs A Shared Predicate

There are several overlapping status concepts:

- `src/sase/ace/tui/models/agent_status.py:8` defines `DISMISSABLE_STATUSES`:
  `DONE`, `FAILED`, `PLAN COMMITTED`, `PLAN DONE`, `TALE DONE`, `PLAN REJECTED`, and `EPIC CREATED`.
- `src/sase/core/agent_cleanup_wire.py:44` has a duplicate dismissable-status set for cleanup planning.
- `src/sase/agent/status_buckets.py:50` maps terminal done statuses to the "Done" bucket, while `FAILED*` maps to
  the "Failed" bucket.
- `FAILED (RETRIED)` is bucketed as failed because the bucket code checks `status.startswith("FAILED")`, but it is
  not in the TUI `DISMISSABLE_STATUSES` literal set.

For this feature, "done with its work" should not mean only `DONE`. It should be a new or reused shared predicate that
accepts all terminal/dismissable outcomes and failed terminal outcomes, including retried failures. A practical
predicate would accept:

- every status in the existing dismissable set;
- any `FAILED*` display status;
- no active, starting, stopped, waiting, question, or plan-input statuses.

This should be centralized instead of copied into the new key handler.

### Current Commit Markers Are Single-Result, Not Complete Association Records

The ordinary commit workflow writes a marker in the agent artifact directory:

- `src/sase/workflows/commit/commit_tracking.py:236` writes `commit_result.json`.
- The marker includes `method`, `cwd`, `result`, `commit_result`, `message`, `changespec_name`,
  `commit_changespec_name`, `entry_id`, `commit_entry_id`, `diff_path`, and `commit_diff_path`.
- `src/sase/workflows/commit/workflow.py:292` writes the marker before/after appending a `COMMITS` entry.

For `create_commit`, `result` is the created commit hash from the git provider. That is the best existing source for a
direct revert.

However, the marker is a single file, not a list. If one agent causes multiple commits, later commit flows can overwrite
earlier marker data. The TUI loader also does not currently expose the full marker onto `Agent`: `AgentMetaWire` has
`commit_result`, `commit_changespec_name`, and `commit_entry_id` fields, but the TUI model mostly carries only
`commit_diff_path`/`diff_path` through loader enrichment.

### SDD Commits Are The Hard Part

The plan-approval flow writes and commits SDD prompt/plan files before launching some agents:

- `src/sase/axe/run_agent_exec_plan_accept.py:58` wraps `commit_sdd_files_for_exec_plan()`.
- `src/sase/axe/run_agent_exec_plan_accept.py:224` and nearby code writes SDD files and records SDD paths in
  `agent_meta.json`.
- `src/sase/axe/run_agent_exec_plan_sdd.py:14` finds the generated prompt/plan files and shells out to `sase commit`.

There are also separate SDD commit paths:

- `src/sase/sdd/_commit.py:13` commits to the local `.sase/sdd/` repo when SDD is not version-controlled in the
  workspace.
- `src/sase/llm_provider/commit_finalizer_git.py:61` can auto-commit a tracked SDD plan status change from `wip` to
  `done` with a raw git commit.

These paths record useful file paths, but they do not reliably attach a normalized commit SHA list to the agent. That
means a revert feature that promises "including plan/prompt files committed to `sdd/`" cannot be correct by only reading
today's `commit_result.json`.

### Existing VCS Provider Has No Revert API

The provider surface supports commit, diff, patch apply, amend, archive, prune, stash/clean, and ChangeSpec abandon:

- `src/sase/vcs_provider/_base.py` defines the provider API.
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py:228` implements `vcs_create_commit()`.
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py:278` implements `vcs_create_proposal()`.
- `src/sase/vcs_provider/plugins/_git_commit_dispatch.py:291` implements `vcs_create_pull_request()`.
- `src/sase/ace/revert.py:160` is ChangeSpec-level abandon/revert behavior, not per-agent commit revert.

There is no provider-level `git revert` equivalent today. A first implementation can shell out to git, but that bakes
git semantics into the TUI action. If this becomes shared CLI/web/editor behavior, the rust-core/backend boundary argues
for moving the domain operation into a reusable backend API and keeping the TUI thin.

### The TUI Must Not Block

The TUI performance guidance applies here. Reverting can touch disk, invoke git, push, and conflict. It must run through
the existing tracked-task path:

- `src/sase/ace/tui/actions/task_actions.py:118` has `_submit_tracked_task()`.

The action should capture selected-agent state before submitting the task, do the git work off the Textual event loop,
then refresh or patch the Agents tab after completion.

## Implementation Options

### Option A: Minimal UI Hook Around Existing `commit_result.json`

Add the leader key, check the selected agent status, read `commit_result.json`, validate that
`method == "create_commit"` and `result` names a commit object, then run `git revert --no-edit <sha>` in the recorded
`cwd` via `_submit_tracked_task()`.

Estimated effort: 1-2 days.

Pros:

- Smallest implementation.
- Works for the simple happy path of an agent that made exactly one ordinary git commit through `sase commit`.
- Easy to test with a temporary git repo and fake artifact directory.

Cons:

- Does not reliably revert SDD prompt/plan commits.
- Does not handle multiple commits from one agent.
- Does not handle overwritten markers.
- Does not handle PR commits or proposal diffs.
- Bypasses provider abstractions unless a provider revert hook is added.
- May leave ChangeSpec `COMMITS` metadata pointing only at the original commit.

This is useful as an internal prototype, but it does not meet the stated requirement.

### Option B: Reverse The Captured Diff

Use `commit_diff.diff` or another captured diff, apply it in reverse, and commit the resulting revert.

Estimated effort: 2-3 days for a git-only version; more to make it robust.

Pros:

- Can work even when there is no commit SHA.
- Could theoretically reverse proposal diffs as well as committed diffs.

Cons:

- Patch application is brittle after subsequent edits.
- It is not semantically the same as `git revert`.
- It still needs a commit and push policy.
- It may not include SDD commits if those were created before or outside the captured diff.
- It is harder to explain and harder to recover from conflicts.

This should not be the primary design. It is a fallback for legacy agents only.

### Option C: Metadata-First Commit Association Records

Introduce an append-only agent artifact file, for example `commit_records.json`, that records every commit associated
with a run:

```json
{
  "version": 1,
  "run_id": "20260614_123456",
  "records": [
    {
      "kind": "work_commit",
      "method": "create_commit",
      "repo_dir": "/repo",
      "sha": "abc1234",
      "message": "feat: example",
      "paths": null,
      "changespec_name": "example",
      "entry_id": "..."
    },
    {
      "kind": "sdd_prompt_plan",
      "repo_dir": "/repo",
      "sha": "def5678",
      "message": "chore: Add SDD prompt and plan for example",
      "paths": ["sdd/prompts/...", "sdd/plans/..."]
    },
    {
      "kind": "sdd_plan_done",
      "repo_dir": "/repo",
      "sha": "987abcd",
      "message": "chore: Mark SDD plan done",
      "paths": ["sdd/plans/..."]
    }
  ]
}
```

Then implement the TUI action as a consumer of these records:

1. Get the selected agent.
2. Check the terminal/done predicate.
3. Resolve commit records from the artifact directory.
4. Show a confirmation modal with commit SHAs, messages, repos, and SDD paths.
5. Require clean worktrees for every affected repo.
6. Revert commits newest-first per repo.
7. Push when the original commit path pushed.
8. Write `revert_result.json` with the created revert commits and any conflicts/errors.
9. Refresh the Agents tab.

Estimated effort: 4-6 days for a git/current-provider implementation.

Pros:

- Meets the SDD prompt/plan requirement.
- Handles multiple commits from one agent.
- Gives a clean future contract for all commit-producing paths.
- Lets the TUI stay mostly orchestration and confirmation UI.
- Enables future CLI or web reuse.

Cons:

- Requires touching commit producers before the TUI action is fully correct.
- Needs migration/fallback behavior for historical agents with only `commit_result.json`.
- Needs careful testing around duplicate records and marker writes.

This is the first option that really satisfies the request.

### Option D: Provider/Core Revert Primitive

Add a provider-level operation such as `revert_commits(records, options)` and expose it through the shared backend/core
layer. The TUI would call the backend with selected-agent commit records and display the result.

Estimated effort: 1-2 weeks if done as a reusable API with git provider support, tests, and non-git unsupported paths.

Pros:

- Best long-term architecture.
- Keeps VCS semantics out of TUI code.
- Gives CLI/web/editor the same behavior.
- Can encode provider-specific push, branch, and PR behavior over time.

Cons:

- More upfront work.
- The current commit workflow is still mostly Python, so this may require a staged bridge rather than a pure Rust-core
  move.
- It does not remove the need for Option C's commit association records.

This is the architecture to aim at if the feature is expected to grow beyond the TUI.

### Option E: Close Or Revert PRs Instead Of Local Commits

Agents may use `create_pull_request`, where the meaningful artifact can be a branch or PR URL rather than a commit on
the current branch. The current marker is not enough to reliably close a PR or revert merged PR content.

Estimated effort: separate follow-up.

Pros:

- Matches how PR-based workflows should be undone.

Cons:

- Needs PR URL, branch, base branch, merge status, and provider-specific behavior.
- Not required for a first git commit revert if the action reports unsupported PR records.

The first version should explicitly report PR/proposal methods as unsupported unless normalized records provide enough
data.

## Work Estimate

| Scope | Estimate | Notes |
| --- | --- | --- |
| Keymap, footer, help, command palette, availability only | 0.5-1 day | Includes resolving the existing `,r` runners conflict. |
| Minimal `commit_result.json` SHA revert | 1-2 days | Fast but incomplete; misses reliable SDD handling. |
| Metadata-first git implementation | 4-6 days | Best practical target: records, resolver, TUI action, tests. |
| Shared provider/core revert API | 1-2 weeks | Worth it if CLI/web/editor should use the same feature. |
| PR/branch-aware revert/close behavior | follow-up | Needs stronger PR metadata and provider semantics. |

## Test Plan

Focused tests should cover:

- status predicate accepts `DONE`, `FAILED`, `FAILED (RETRIED)`, `PLAN COMMITTED`, `PLAN DONE`, `TALE DONE`,
  `PLAN REJECTED`, and `EPIC CREATED`, and rejects running/input/stopped statuses;
- commit-record append behavior for ordinary `create_commit`;
- SDD prompt/plan commit records from `commit_sdd_files_for_exec_plan()`;
- SDD plan-status commit records from `auto_commit_done_sdd_plan_status()`;
- resolver fallback for legacy `commit_result.json`;
- git integration test that reverts multiple commits newest-first in a temporary repository;
- dirty-worktree failure;
- conflict reporting;
- TUI leader dispatch, command availability, help/footer labels, and background-task submission.

Because this touches keymaps, `src/sase/default_config.yml` must be updated along with typed keymap definitions and UI
discovery surfaces.

## Recommended Solution

Implement this in two phases, with the metadata work first.

Phase 1 should add a normalized, append-only agent commit association record and update all relevant commit-producing
paths to write it: ordinary `sase commit`, SDD prompt/plan commits, and SDD plan-status auto-commits. Keep a legacy
resolver for existing `commit_result.json`, but treat legacy SDD revert as best-effort or unsupported when no SHA is
known. This phase is the core of making the feature honest.

Phase 2 should add the Agents-tab action. Use a shared terminal/done predicate, resolve records for the selected agent,
show a confirmation modal, run git/provider reverts in `_submit_tracked_task()`, write `revert_result.json`, push when
appropriate, and refresh the Agents tab. Bind the action only after deciding what happens to the existing `,r` runners
key; the cleanest default is to move runners to another leader key and reserve `,r` for "revert selected done agent" on
the Agents tab.

Do not ship the minimal `commit_result.json`-only version as the final feature. It is attractive because the UI part is
small, but it would create exactly the failure mode the request is trying to avoid: the code commit might revert while
the associated SDD plan/prompt commit remains in history.
