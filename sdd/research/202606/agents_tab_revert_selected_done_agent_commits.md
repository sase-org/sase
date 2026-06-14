---
create_time: 2026-06-14
updated_time: 2026-06-14
status: research
---

# Agents Tab Revert Selected Done Agent Commits

## Question

Add a new `,r` leader key to the `sase ace` Agents tab that reverts commits associated with the currently selected done
agent, including committed `sdd/` prompt and plan files. The action should accept every status that means the agent has
finished its work.

## Short Answer

This is medium-sized work. The TUI wiring is straightforward, but the correctness boundary is the commit discovery and
revert backend.

The best first implementation is a git-focused `revert_agent_commits()` backend that discovers commits by exact
`AGENT=<name>` commit-message tag, reverts them newest-first with `git revert`, and is called from the Agents tab via a
tracked background task. That discovery path already finds normal work commits and version-controlled `sdd/` prompt/plan
commits created through `sase commit`.

Before shipping, close the known SDD tagging gaps: some raw SDD auto-commit paths currently add `TYPE=sdd` but not
`AGENT=<name>`. Without that fix, a tag-based revert is correct for the common `sase commit` SDD path but not for every
future SDD status/initialization auto-commit.

Estimated work:

- 2-3 focused days for a git-only version using `AGENT=` tags, including TUI wiring and tests.
- 3-5 days if the first version also fixes raw SDD auto-commit tagging, writes a `revert_result.json`, and handles
  selected-agent-family scope cleanly.
- 1-2 weeks for a provider/core-level API with non-git, PR/proposal, and normalized commit-record support.

## Verified Findings

### `,r` already means runners

`leader_mode.keys.runners` is currently `"r"` in both `src/sase/default_config.yml` and
`src/sase/ace/tui/keymaps/types.py`. The dispatcher handles it globally in
`src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`, and it is exposed through the command catalog, footer, and
help modal.

Adding `,r` for revert is therefore not just a new handler. It needs a key conflict decision:

- move "runners" to another leader key and reserve `,r` for agent revert;
- or make `,r` context-sensitive on the Agents tab, which is workable but makes help, command-palette labels, and
  repeat-last-leader behavior more subtle.

The cleanest implementation is to move runners and make `revert_agent` an explicit leader-mode key.

### Use a terminal-work predicate, not only `DONE`

The TUI already has `DISMISSABLE_STATUSES` in `src/sase/ace/tui/models/agent_status.py`:

`DONE`, `FAILED`, `PLAN COMMITTED`, `PLAN DONE`, `TALE DONE`, `PLAN REJECTED`, `EPIC CREATED`.

That is close, but it does not include displayed retry failures like `FAILED (RETRIED)`. The status bucket logic in
`src/sase/agent/status_buckets.py` treats every `FAILED*` status as terminal failure.

The new gate should be a shared helper, for example `is_revertable_agent_status(status)`, that returns true when:

- `status in DISMISSABLE_STATUSES`; or
- `status.startswith("FAILED")`.

It should reject `PLAN`, `QUESTION`, waiting, starting, and running states. Those are not "done with work"; they are
paused or active.

### The selected-agent model is sufficient, with robust identity resolution

The Agents tab can get the focused row with `_get_selected_agent()` in
`src/sase/ace/tui/actions/agents/_selection.py`. The `Agent` model already carries `status`, `workspace_dir`,
`artifacts_dir`, `cl_name`, `project_file`, and `agent_name`.

Done-agent loading enriches `agent.agent_name` from `agent_meta.json`, but the backend should still resolve the
canonical name defensively from the artifact directory (`Agent.get_artifacts_dir()` -> `agent_meta.json["name"]`) before
falling back to the dataclass field. That keeps the feature resilient for older or workflow-derived rows.

### Commit association: `AGENT=` is the practical source, not `COMMITS`

`src/sase/workflows/commit/runtime_tags.py` appends runtime commit tags to `sase commit` messages. For `create_commit`
and `create_pull_request`, `CommitWorkflow.run()` calls `apply_runtime_commit_tags()`, which writes `AGENT=<name>` and
`MACHINE=<host>` when the agent name can be resolved.

The ChangeSpec `COMMITS` drawer records notes, chat, diff, and plan paths, but it does not store commit SHAs. The
agent-local `commit_result.json` stores a single result, and later commit flows can overwrite it. It is useful for
display and legacy fallback, but it should not be the primary source for "all commits by this agent".

The practical discovery query is commit-message based:

```bash
git log --format=%H --extended-regexp --grep='^AGENT=<escaped-agent-name>$'
```

Implementation should escape the agent name or parse candidate commit messages and match exact tag lines. Do not rely
on `%(trailers)`: these tags look like trailers, but they are not guaranteed to satisfy git trailer parsing.

### SDD commits are partly covered today, but not universally

The common version-controlled SDD prompt/plan path is covered:

- `src/sase/axe/run_agent_exec_plan_sdd.py` builds a `TYPE=sdd` message and invokes `sase commit`.
- `sase commit` then applies runtime tags, so git history shows both `TYPE=sdd` and `AGENT=<name>` on those commits.
- Verified examples in this repo include `chore: Add SDD prompt and plan ...` commits with both tags.

There are also raw SDD commit paths that currently add `TYPE=sdd` but not `AGENT=<name>`:

- `src/sase/llm_provider/commit_finalizer_git.py::auto_commit_done_sdd_plan_status()`
- `src/sase/sdd/_commit.py::commit_sdd_files()`
- `src/sase/sdd/_commit.py::commit_bare_git_sdd_init_paths()`

Git history confirms `chore: Mark SDD plan done` commits with only `TYPE=sdd`. A tag-only revert cannot associate those
historical commits with an agent without heuristics. Future correctness requires tagging those raw auto-commits with the
same runtime tags, or recording normalized commit records when they are created.

### Existing ChangeSpec revert is the wrong operation

`src/sase/ace/revert.py::revert_changespec()` is a whole-ChangeSpec operation. It kills running processes, saves a diff,
abandons the remote change, prunes the branch, renames the ChangeSpec, and marks it `Reverted`.

That is not a per-agent `git revert`. A ChangeSpec can contain multiple agents' commits, and SDD commits can be on the
same branch but should still be selected by agent identity. Reusing `revert_changespec()` would over-revert and would
not preserve history.

### The TUI action must run as a tracked task

Git discovery, revert, push, conflict detection, and artifact writes must not run on the Textual event loop. The action
should capture the selected agent, show a confirmation modal, then submit a background task through
`_submit_tracked_task()` in `src/sase/ace/tui/actions/task_actions.py`.

On completion, refresh through the existing Agents-tab refresh path. Do not add synchronous JSON reads or subprocesses
inside the key handler beyond lightweight state capture.

## Implementation Options

### Option A: call `revert_changespec()`

This is the smallest code change, but it is semantically wrong. It reverts the whole CL/branch, not the selected
agent's commits. Reject as the implementation for `,r`.

### Option B: read `commit_result.json` and revert one SHA

This is a useful prototype: read the selected agent artifact's `commit_result.json`, require
`method == "create_commit"`, and run `git revert` on `result`.

It is incomplete. It misses multiple commits, overwritten markers, some SDD commits, PR/proposal methods, and any commit
not represented by the latest marker. Do not ship this as the final behavior.

### Option C: discover commits by exact `AGENT=` tag and `git revert` them

Resolve the selected agent name, find matching commits in the relevant git workspace, and revert them newest-first.

Pros:

- matches the request at commit granularity;
- naturally includes version-controlled `sdd/` prompt/plan commits made through `sase commit`;
- leaves sibling agents' commits alone when using exact scope;
- preserves history and is re-revertible.

Cons:

- needs conflict handling and `git revert --abort`;
- raw SDD auto-commit tagging gaps must be fixed for future completeness;
- exact selected-agent scope may leave half of a plan/coder workflow behind.

This is the right core mechanism.

### Option D: add normalized append-only commit records

Record every agent-associated commit as it is created, for example in `commit_records.json`, with repo, SHA, kind,
paths, method, ChangeSpec, and entry ID.

This is the strongest long-term data model and helps non-git or PR-aware flows, but it is not required to implement the
first git version because commit messages already carry the key association for ordinary and common SDD commits.

Use this when broadening beyond git, supporting historical artifact-only lookup, or replacing commit-message search with
a typed contract.

### Option E: reverse stored diffs or rewrite history

Reverse-applying captured diffs is brittle after later edits and does not reliably include SDD commits. Rewriting
history is too dangerous for pushed branches and open PRs. Reject both for this feature.

## Recommended Solution

Implement Option C as a reusable backend plus thin TUI caller, with two hardening steps from Option D.

1. Add `is_revertable_agent_status(status)` and gate on `DISMISSABLE_STATUSES` plus `FAILED*`. Exclude stopped/input
   statuses.
2. Decide the `,r` conflict by moving the existing runners key. Keep `revert_agent` explicit in config, typed keymaps,
   dispatch, footer, help, and command palette.
3. Add a backend such as `src/sase/ace/revert_agent.py::revert_agent_commits()`. It should resolve the canonical agent
   name from artifacts/meta, validate the workspace, require a clean worktree, discover commits by exact `AGENT=` tag,
   and revert newest-first through a new git/VCS-provider helper. On conflict, abort and return a precise error.
4. Make the backend support `scope="exact"` and `scope="family"`. Default the TUI to exact for ordinary agents, but use
   family scope for plan-chain rows or show an explicit confirm choice, because plan/prompt SDD commits and follow-up
   code commits can belong to different names in the same agent family.
5. Fix future SDD coverage by applying runtime tags to raw SDD auto-commit paths that currently only add `TYPE=sdd`.
   Historical untagged `TYPE=sdd` commits should be reported as not discoverable rather than guessed.
6. Add `ConfirmRevertAgentModal` showing the agent/family scope, commit count, short SHAs, subjects, and any `sdd/`
   paths. Submit the work with `_submit_tracked_task()`, write `revert_result.json`, refresh the Agents tab on success,
   and surface conflicts without leaving the repository in an in-progress revert.
7. Test status gating, exact tag matching, family matching, code plus SDD commit discovery, dirty worktree rejection,
   conflict abort/reporting, no-commit behavior, and the TUI leader/footer/help/palette wiring.

This satisfies the request without overusing the destructive ChangeSpec revert path, keeps slow git work off the TUI
event loop, handles the current version-controlled SDD prompt/plan flow, and makes the known SDD auto-commit gaps
explicit enough to fix before users depend on `,r`.
