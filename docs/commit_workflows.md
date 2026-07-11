# Commit Workflows

Sase provides three unified workflows for landing code changes: **commit**, **propose**, and **pull request**. All three
share the same ChangeSpecI command (`sase commit`), the same `CommitWorkflow` orchestrator, and the same VCS provider
abstraction, but differ in what they produce and how they track the result.

## Overview

| Workflow    | XPrompt    | Method                | What it produces             | Tracking      |
| ----------- | ---------- | --------------------- | ---------------------------- | ------------- |
| **Commit**  | `#commit`  | `create_commit`       | Git commit on current branch | COMMITS entry |
| **Propose** | `#propose` | `create_proposal`     | Saved diff file              | COMMITS entry |
| **PR**      | `#pr`      | `create_pull_request` | New branch + PR              | ChangeSpec    |

```
#commit / #propose / #pr
        |
        v
Agent edits files
        |
        v
Provider-neutral commit finalizer
        |
        v
Commit skill wrapper (/sase_git_commit, /sase_hg_commit, ...)
        |
        v
sase commit -> CommitWorkflow -> VCS provider -> tracked output
```

## How It Works

### 1. Agent makes code changes

The agent receives an xprompt (`#commit`, `#propose`, or `#pr`) which sets the `SASE_COMMIT_METHOD` environment variable
and injects an instruction telling the agent **not** to create commits directly.

### 2. Commit finalizer checks for uncommitted work

When a provider invocation succeeds inside a SASE-launched agent session, the provider-neutral **commit finalizer** runs
in the shared LLM invocation layer before normal success postprocessing. In practice this means the process has
`SASE_AGENT_TIMESTAMP` set. The finalizer checks the main workspace for uncommitted changes through the active VCS
provider. It enforces configured linked repositories at their host-scoped workspace paths. The
`sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>` command also records manually opened linked
workspaces for ACE context. It does not scan arbitrary same-remote numbered workspaces just because their paths appear
in run artifacts. If everything is clean, the agent response is postprocessed normally.

There is one special case before the normal enforced-work follow-up path:

- If the only enforced dirty file is a tracked markdown file under `sdd/plans/`, and the only file diff is one
  leading-front-matter line changing from `status: wip` to `status: done`, SASE creates a direct closeout commit with
  the message `chore: Mark SDD plan done` and a `SASE_TYPE=sdd` runtime tag. If enforced changes remain, the finalizer
  starts bounded follow-up passes with the same provider. Each pass sends one follow-up prompt that lists dirty files
  and instructs the agent to use a commit skill such as `/sase_git_commit` or `/sase_hg_commit`. For the main workspace,
  the skill name is selected from the detected VCS provider; provider-specific generated skills can be scoped to the
  runtimes that support that provider. For configured linked repos, the current finalizer checks `git status` only in
  the resolved linked-repo `workspace_dir` assigned to the same workspace number after that linked-repo name appears in
  `opened_linked_workspaces.json`, and emits Git commit-skill instructions that first `cd` into that linked workspace.
  Dirty linked repos are enforced after they are opened.

Generated skills normally run an observable wrapper such as `sase_git_commit`, which records skill invocation evidence
and then delegates to `sase commit`. A typical Git skill invocation omits `--type` because the xprompt already set
`SASE_COMMIT_METHOD`:

```bash
sase_git_commit -M commit_message.md -f src/example.py
```

The low-level equivalent is `sase commit -M commit_message.md -f src/example.py -t <method>`. The method defaults to
`$SASE_COMMIT_METHOD` if the `-t` flag is omitted. If both the environment and `-t/--type` are set, they must resolve to
the same method unless `SASE_COMMIT_METHOD_ALLOW_OVERRIDE=1` is set.

If `SASE_BEAD_ID` is set, the finalizer first asks the agent to decide whether the uncommitted changes were made in the
current session. For changes the agent did make, it instructs the agent to close and verify the bead before invoking the
commit skill. This keeps bead lifecycle state ahead of the commit/proposal/PR dispatch while avoiding accidental closure
for unrelated dirty work.

The finalizer uses the shared instruction helpers in `sase.commit_instructions`, so the bead and method wording stays
consistent between main-workspace and linked-repository commit guidance. `commit.finalizer.max_passes` controls how many
follow-up invocations may run before SASE fails the invocation with a clear error and, when an artifacts directory is
available, a `commit_finalizer_result.json` artifact.

### CLI Arguments

| Short | Long                | Description                                                                                                                                                                                                                                                                 |
| ----- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-m`  | `--message`         | Commit message string (mutually exclusive with `-M`)                                                                                                                                                                                                                        |
| `-M`  | `--message-file`    | Path to file containing the commit message / PR description (mutually exclusive with `-m`)                                                                                                                                                                                  |
| `-f`  | `--file`            | File to stage (repeatable; omit to stage all)                                                                                                                                                                                                                               |
| `-n`  | `--name`            | Branch/PR name (required for `create_pull_request`)                                                                                                                                                                                                                         |
| `-B`  | `--bug-id`          | Bug ID to associate with the commit (overrides `$SASE_BUG_ID`)                                                                                                                                                                                                              |
| `-c`  | `--checkout-target` | Branch point for PR (default: `HEAD~1`)                                                                                                                                                                                                                                     |
| `-p`  | `--parent`          | Parent ChangeSpec **name** (overrides auto-detection from current branch). Must be an existing ChangeSpec in the active project file or archive — if it does not resolve, the PARENT field is omitted with a warning. Never pass a VCS ref (e.g., `origin/main`, `p4head`). |
| `-r`  | `--resume`          | Resume a previously-checkpointed commit after manual conflict resolution. When set, `-m` / `-M` / `-f` and other commit args are ignored (the payload is loaded from the checkpoint). See [Resume after Conflict](#resume-after-conflict) below.                            |
| `-s`  | `--status`          | ChangeSpec status for PRs (`wip`, `draft`, `ready`). Overrides `$SASE_PR_STATUS`; default is `draft`.                                                                                                                                                                       |
| `-t`  | `--type`            | Commit method — accepts full names or short aliases (see table below)                                                                                                                                                                                                       |

#### Type Aliases

The `-t/--type` flag accepts both full method names and short aliases:

| Alias     | Full Method           |
| --------- | --------------------- |
| `commit`  | `create_commit`       |
| `propose` | `create_proposal`     |
| `pr`      | `create_pull_request` |

The COMMITS entry note is always derived from the first line of the commit message — there is no separate `--note` flag.

### 3. CommitWorkflow orchestrates

`CommitWorkflow` (`src/sase/workflows/commit/workflow.py`) is the central dispatcher. It runs through these stages:

```
Bead association   (inject SASE_BEAD_ID into message when set)
    |
Bead lifecycle     (close bead, sync beads)                               [skip for proposals]
    |
Plan handling      (store/copy plan, append storage-relative SASE_PLAN=,  [skip for proposals]
                    mark plan done)
    |
Before hook        (`commit_hooks.before`, e.g. `just fix`)
    |
PR name suffixing  (compute _<N> suffix for unique branch names)          [PR only]
    |
Detect parent PR   (auto-set PARENT from current branch's ChangeSpec)     [PR only]
    |
PR metadata        (append PR tags and project prefix)                    [PR only]
    |
Runtime tags       (append/update SASE_AGENT=, SASE_MACHINE= provenance)  [commit/PR only]
    |
PR body            (build body with final tags and agent footer)          [PR only]
    |
Diff capture       (save the pre-dispatch diff for tracking)
    |
Checkpoint         (save resolved payload and tracking state for resume)
    |
VCS dispatch       (call provider.create_commit / create_proposal / create_pull_request)
    |
After hook         (`commit_hooks.after`, after commit/push)              [commit/PR only]
    |
ChangeSpec         (create ChangeSpec entry in project file)              [PR only]
    |
Result marker      (write commit_result.json for xprompt post-steps)
    |
COMMITS entry      (append entry to project file)                         [commit/propose only]
```

### 4. XPrompt reads the result

The xprompt post-steps read `commit_result.json` from `$SASE_ARTIFACTS_DIR` and emit metadata outputs
(`meta_new_commit`, `meta_commit_message`, `meta_changespec`, etc.) for downstream consumption.

## CLI Inputs and Internal Payload

The `sase commit` CLI builds an internal `CommitWorkflow` payload from flags. It does **not** accept a positional JSON
payload.

Typical commit or proposal:

```bash
sase commit -M commit_message.md -f src/auth.py -f src/login.py -t commit
```

Typical PR:

```bash
sase commit -M pr_description.md -n feature_branch -B 12345 -s ready -t pr
```

The internal payload has this shape:

```json
{
  "message": "Commit message (required for commit/propose)",
  "name": "Branch or PR name (required for PR)",
  "files": ["optional", "list", "of", "specific", "files"]
}
```

The CLI maps `-m` / `-M` to `message`, repeated `-f` flags to `files`, `-n` to `name`, `-B` to `bug_id`, `-c` to
`checkout_target`, `-p` to `parent`, and `-s` to `status`. Omitted `-f` means "stage all changes" and is represented as
an empty `files` list.

Bead association is not a user-supplied CLI flag. For new commit attempts, `sase commit` reads `SASE_BEAD_ID`; when it
is set, the CLI adds that bead to the workflow payload, and `CommitWorkflow` enforces that the bead ID appears in the
first line of the dispatched commit or PR message. Conflict resumes reuse the bead value captured in the original
checkpoint.

Runtime provenance tags are also not user-supplied CLI flags. For `create_commit` and `create_pull_request`,
`CommitWorkflow` appends or updates trailing `SASE_AGENT=<sase agent name>` and `SASE_MACHINE=<host name>` lines in the
commit message. `AGENT` comes from `SASE_AGENT_NAME`, falling back to `SASE_ARTIFACTS_DIR/agent_meta.json` when
available; it is omitted for manual non-agent commits with no agent name. `MACHINE` comes from the local hostname.
Runtime-owned `AGENT` and `MACHINE` values replace inherited or configured PR tags with the same keys. `create_proposal`
does not get runtime commit tags because it saves a diff instead of creating a VCS commit.

**Footer tag prefix:** All SASE-authored commit footer tags (`TYPE`, `AGENT`, `MACHINE`, `PLAN`, `BUG`, and any
configured or inherited PR tag keys) are written with a `SASE_` prefix — for example `SASE_TYPE=sdd` and
`SASE_AGENT=<name>`. Readers (agent-commit/revert discovery, parent-PR tag inheritance, ChangeSpec description
stripping) still accept the historical unprefixed spelling, so commit history is not rewritten and old commits remain
readable. Because this changes the exact footer keys visible to external PR tooling, any external consumer that reads
these tag names must be updated to accept the `SASE_`-prefixed keys (or both spellings).

Internal fields added by `CommitWorkflow`:

| Field              | Set by              | Purpose                                 |
| ------------------ | ------------------- | --------------------------------------- |
| `_cl_name`         | Environment         | Fallback PR name for proposals          |
| `_plan_path`       | `_handle_sase_plan` | Plan file path for VCS staging          |
| `_pr_body`         | `_build_pr_body`    | Enriched PR description with agent info |
| `_skip_bead_amend` | Internal            | Skip post-commit bead amend             |
| `bead_id`          | Environment         | Bead ID resolved from `SASE_BEAD_ID`    |

## Result Format

After a successful dispatch, `commit_result.json` contains:

```json
{
  "method": "create_commit",
  "result": "<commit_hash | diff_path | null>",
  "message": "The commit message",
  "name": "Branch/PR name",
  "bead_id": "Bead ID if SASE_BEAD_ID was set",
  "changespec_name": "ChangeSpec name (PR only)",
  "entry_id": "COMMITS entry ID (commit/propose only)",
  "diff_path": "Saved pre-dispatch diff path, when available"
}
```

For compatibility with older xprompt post-steps, the marker also includes alias keys: `commit_result`,
`commit_changespec_name`, `commit_entry_id`, and `commit_diff_path`.

## Workflow Details

### Commit (`#commit`)

Creates an actual git commit on the current branch and pushes it.

**Git operations:**

1. Stage files (`git add -A` or specific files)
2. Stage in-repo SDD bead and plan files when present
3. Validate staged changes exist
4. Merge with `origin/<default_branch>` to keep the branch current
5. `git commit -m <message>`
6. Post-commit bead amend (append bead note)
7. Push to remote with retry on failure

**Returns:** `(True, commit_hash)`

**Tracking:** Appends a COMMITS entry to the project file with the commit note, diff path, chat path, and plan path
(when `SASE_PLAN` is set). Multi-line commit messages are supported: the first paragraph becomes the note, and
subsequent paragraphs (separated by a blank line) become an indented body below the note. Empty body lines are stored as
a dot (`.`) placeholder to preserve structure. See [change_spec.md](change_spec.md#commits) for the full entry format
including drawers.

### Propose (`#propose`)

Saves the current diff without committing and cleans the workspace. This is useful for parking work-in-progress changes
that aren't ready to land.

**Git operations:**

1. Save diff to `~/.sase/diffs/<cl_name>-<timestamp>.diff`
2. Clean workspace (`git reset --hard HEAD` + `git clean -fd`)

**Returns:** `(True, diff_path)`

**Tracking:** Appends a proposal COMMITS entry to the project file. Bead lifecycle and plan handling are skipped because
proposals don't represent landed changes. Runtime `AGENT` and `MACHINE` commit tags are also skipped because no VCS
commit is created.

### Pull Request (`#pr`)

Creates a new branch, commits changes, pushes, and creates a PR (via the GitHub plugin or equivalent).

**Input parameters:**

```yaml
input:
  - name: name # Branch/PR name (required)
    type: word
  - name: bug_id # Bug ID (optional, default: 0)
    type: int
  - name: status # Initial ChangeSpec status: draft, wip, or ready (optional, default: draft)
    type: word
```

**Git operations:**

1. `git checkout -b <name>` (create new branch)
2. Stage files and bead/plan paths
3. `git commit -m <message>`
4. `git push -u origin <name>`
5. (GitHub plugin creates the actual PR via `gh`)

**Returns:** `(True, pr_url)` after GitHub plugin processing

**Parent detection:** If the current branch corresponds to an existing ChangeSpec, that ChangeSpec is automatically set
as the PARENT of the new PR ChangeSpec. This creates a chain of related changes without manual bookkeeping.

**BUG propagation:** When `SASE_BUG_ID` is set in the environment and non-zero, the value is propagated to two places:
the BUG field of the created ChangeSpec (as `http://b/<bug_id>`), and a `SASE_BUG=<bug_id>` line prepended to the PR tag
block (taking precedence over any static `BUG` key in `vcs_provider.pr_tags` config).

**Project prefix:** When `vcs_provider.use_project_pr_prefix` is `true`, a `[<project>] ` prefix is prepended to the PR
title (GitHub) or PR description (Mercurial). This prefix is only applied to the external representation — it does not
appear in the ChangeSpec DESCRIPTION or git commit message, and is automatically stripped when reading descriptions
back.

**PR tag inheritance:** When creating a child PR (one whose PARENT is an existing ChangeSpec), PR tags from the parent
PR's body are automatically inherited. Parent tags are read in either spelling — legacy `TAG=` or new `SASE_TAG=` — so
inheritance works across the migration. The merge order is: parent PR tags (lowest priority) -> config `pr_tags` ->
`BUG` tag (highest priority), followed by runtime-owned `AGENT` and `MACHINE` tags. Inherited or configured `AGENT` and
`MACHINE` values are ignored so child PRs do not retain stale parent runtime provenance.

**PR tags:** Any key-value pairs configured in `vcs_provider.pr_tags` are appended as `SASE_TAG=VALUE` lines to the
commit message before building the PR body. This supports provider-specific metadata (e.g., Google PR tags) without
manual entry. `AGENT` and `MACHINE` are reserved for runtime provenance and are owned by the commit workflow rather than
static config. Note that the rendered keys carry the `SASE_` prefix (e.g. a configured `MARKDOWN` tag is written as
`SASE_MARKDOWN=`), so external tooling that consumes these tags must accept the prefixed names. See
[configuration.md](configuration.md#vcs_provider) for the config format.

**PR tag stripping:** When PR tags are present in the commit description (trailing lines matching `^[A-Z][A-Z0-9_]*=`),
they are automatically stripped before writing the DESCRIPTION field of the created ChangeSpec. This prevents
provider-specific metadata (e.g., `AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT`, `MARKDOWN=true`) from polluting the human-readable
description. The same stripping is applied when syncing descriptions after a reword operation.

**Tracking:** Creates a ChangeSpec in the project file (not a COMMITS entry). The PR name is automatically suffixed with
`_<N>` if a ChangeSpec with the same base name already exists.

## VCS Provider Abstraction

The three dispatch methods are defined in `VCSHookSpec` and implemented by each VCS plugin:

| Plugin          | `create_commit`    | `create_proposal` | `create_pull_request`     |
| --------------- | ------------------ | ----------------- | ------------------------- |
| `BareGitPlugin` | Commit + push      | Save diff + clean | Branch + commit + push    |
| `GitHubPlugin`  | Inherits from git  | Inherits from git | + creates PR via `gh` CLI |
| `HgPlugin`      | `hg commit` + mail | `sase_hg_clean`   | Not supported natively    |

All methods return `tuple[bool, str | None]` (success flag and optional result string).

Plugins that support resume also implement `vcs_finalize_commit(payload, cwd)`, which re-runs the idempotent portion of
a commit (bead amend, push with retry) after a previously-checkpointed workflow has had its merge conflicts resolved by
hand. See [Resume after Conflict](#resume-after-conflict) below for how this fits into the overall flow. Providers that
cannot safely replay finalization (e.g., Mercurial today) can leave it unimplemented — `CommitWorkflow.resume` catches
the `NotImplementedError` and only replays the tracking steps.

## Run Result

`CommitWorkflow.run()` and `CommitWorkflow.resume()` return a `RunResult` with three states:

| State      | Exit code | Meaning                                                                       |
| ---------- | --------- | ----------------------------------------------------------------------------- |
| `OK`       | `0`       | Commit succeeded end-to-end (or resume replayed tracking).                    |
| `FAILED`   | `1`       | Failure; an after-hook failure keeps its post-dispatch checkpoint for resume. |
| `CONFLICT` | `2`       | VCS dispatch hit a merge conflict; a checkpoint is left on disk for resume.   |

The `sase commit` CLI propagates these states to its process exit code, so wrapper skills (`/sase_git_commit`) can
branch on `$?` to distinguish a real failure from a conflict that the user needs to resolve.

## Resume after Conflict

`CommitWorkflow` persists its progress to a checkpoint file so that a dispatch interrupted by a merge conflict can be
finished by hand without re-running the whole flow:

```
SASE_ARTIFACTS_DIR/commit_state.json              # preferred, when running under a workflow
~/.sase/commit_state/<session>.json               # fallback when no artifacts dir is set
```

**Normal flow:**

1. `CommitWorkflow.run()` snapshots its resolved state (payload, PR name, project file, diff path, reserved name, parent
   PR) to the checkpoint **before** calling the VCS dispatch method.
2. If dispatch succeeds for a commit or PR, the checkpoint is updated with the dispatch result and `commit_hooks.after`
   runs before tracking. Proposals skip the after hook.
3. If the after hook and tracking succeed, their completed steps are checkpointed and the file is deleted.
4. If dispatch fails because of a merge conflict (`RunResult.CONFLICT`), the checkpoint is retained and the CLI prints:

   > `create_commit` hit a merge conflict: ... Resolve the conflict, then run `sase commit --resume` to finish.

**Resume flow (`sase commit --resume`):**

1. Load the checkpoint from disk (if missing, the command errors out).
2. Re-check the working tree for conflict markers — if they're still present, refuse to continue with `CONFLICT`.
3. Verify the commit at `HEAD` matches the subject line from the checkpointed message. If it doesn't, abort with
   `FAILED`; the user is expected to re-run `sase commit` from scratch rather than resume into a foreign commit.
4. If dispatch was not already completed, call the provider's `vcs_finalize_commit` hook to replay idempotent
   post-commit work (bead amend, push with retry), then checkpoint dispatch completion.
5. Run `commit_hooks.after` for commit/PR workflows unless its completion is already checkpointed.
6. Re-run the tracking steps (COMMITS entry append, ChangeSpec creation) using the snapshotted payload.
7. Delete the checkpoint on success.

Resume is VCS-agnostic: the same `--resume` flag works for commits, proposals, and PRs. Skills emit the on-conflict
instructions automatically, so agents know to hand control back to the user rather than retry blindly.

An after-hook failure also uses this resume path: the commit may already be pushed, so creating a new commit would risk
duplication. Fix the hook and run `sase commit --resume`; dispatch/finalization is skipped because its completed step is
already recorded. After hooks should be repeatable because a crash between command success and checkpoint persistence
has at-least-once execution semantics.

## Environment Variables

| Variable                            | Purpose                                                                                          |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ |
| `SASE_COMMIT_METHOD`                | Dispatch method (set by xprompt `environment:` section)                                          |
| `SASE_COMMIT_METHOD_ALLOW_OVERRIDE` | Allow `-t/--type` to override a conflicting `SASE_COMMIT_METHOD`                                 |
| `SASE_ARTIFACTS_DIR`                | Directory for `commit_result.json` and other artifacts                                           |
| `SASE_AGENT_NAME`                   | Agent name used for `SASE_AGENT=` runtime commit provenance                                      |
| `SASE_BEAD_ID`                      | Bead ID to automatically associate with the commit                                               |
| `SASE_PLAN`                         | Plan source for storage/staging, status update, and the storage-relative `SASE_PLAN=` commit tag |
| `SASE_AGENT_PROJECT_FILE`           | Project file for COMMITS/ChangeSpec tracking                                                     |
| `SASE_AGENT_CL_NAME`                | PR name used for proposal diff naming                                                            |
| `SASE_PR_NAME`                      | PR name (set by `#pr` xprompt input)                                                             |
| `SASE_PR_STATUS`                    | Initial PR ChangeSpec status (`draft`, `wip`, `ready`)                                           |
| `SASE_BUG_ID`                       | Bug ID for PR metadata                                                                           |
| `SASE_VCS_PROVIDER`                 | Override VCS provider detection (see [vcs.md](vcs.md))                                           |
| `SASE_LINKED_REPOS_JSON`            | JSON metadata for configured linked repos passed to agents                                       |
| `SASE_LINKED_REPO_<ENV_NAME>_DIR`   | Workspace-matched path for one configured linked repo                                            |
| `SASE_DISABLE_COMMIT_STOP_HOOK`     | Skip the commit finalizer when set                                                               |

## Commit Finalizer

For SASE-launched agent sessions, the normal path is the provider-neutral finalizer in
`src/sase/llm_provider/commit_finalizer.py`. It runs after a successful provider invocation and before success
postprocessing. The finalizer is deliberately outside any one runtime's native hook system, so Claude, Codex,
Antigravity (`agy`), Qwen, OpenCode, and provider plugins share the same behavior.

**Flow:**

1. Skip when `commit.finalizer.enabled` is false, `SASE_DISABLE_COMMIT_STOP_HOOK=1` is set, or the process is outside a
   SASE agent session (`SASE_AGENT_TIMESTAMP` is unset).
2. Resolve the project directory from provider/workspace environment variables.
3. Check the main workspace through the VCS provider's diff helpers.
4. Check configured linked repos from `SASE_LINKED_REPOS_JSON`, or from project config when available, with
   `git status --porcelain`; opened-workspace markers provide paths for linked repos opened during the run.
5. Auto-commit an exact tracked SDD markdown `status: wip` to `status: done` closeout when that is the only enforced
   change and the file is under `sdd/plans/`.
6. If dirty enforced repos exist, run follow-up provider invocations up to `commit.finalizer.max_passes`. When an
   artifacts directory is available, also write `commit_finalizer_pass_<N>_prompt.md` and
   `commit_finalizer_pass_<N>_response.md`.
7. Re-check every dirty target. If all enforced repos are clean, write `commit_finalizer_result.json` with status
   `finalized` when artifacts are enabled, and append the follow-up response to the agent's final response.
8. If enforced changes remain after `commit.finalizer.max_passes`, write status `failed` when artifacts are enabled and
   fail the invocation instead of silently accepting dirty work.

Configured linked repos are resolved to host-scoped directories before agent launch. For example, an agent in `sase_10`
sees a `../sase-core` linked repo at `sase_10/.sase/workspaces/sase-core`. The linked-repo dirty-check path is
Git-specific: non-Git linked-repo paths can still be exposed through environment variables and metadata, but the
finalizer does not enforce them as dirty targets.

When the only enforced dirty state is the exact SDD status closeout described above, the finalizer creates the commit
itself instead of running a follow-up provider invocation. The result artifact records
`reason: "auto_committed_done_plan_status"`.

The obsolete provider-native commit hook scripts are no longer shipped. Active SASE-launched runs rely on the
provider-neutral finalizer instead of runtime-specific commit hook configuration.

## Diff Storage

Diffs saved by proposals (and other operations) are stored in:

```
~/.sase/diffs/<name>-<timestamp>.diff     # Active diffs
~/.sase/reverted/<name>.diff              # Reverted PRs
~/.sase/archived/<name>.diff              # Archived PRs
```

Diffs can be re-applied to a workspace with `apply_diff_to_workspace()` from `sase.workflows.commit_utils.workspace`.

## Design Principles

- **Fail-fast:** If `commit_result.json` is missing when the xprompt post-steps run, the workflow fails explicitly
  rather than silently retrying. The finalizer and commit skills are the sanctioned path to commit creation.
- **Single responsibility:** `CommitWorkflow` owns all orchestration (commit hooks, beads, plans, VCS dispatch,
  tracking). XPrompt steps only read and report results.
- **Proper proposal semantics:** Proposals save diffs and clean the workspace without creating commits. Bead lifecycle
  and plan handling are skipped because proposals don't represent landed changes.
- **VCS agnostic:** The same `CommitWorkflow` and xprompt definitions work across Git, GitHub, and Mercurial backends.
  Only the VCS plugin implementation differs.
