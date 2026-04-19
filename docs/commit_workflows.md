# Commit Workflows

Sase provides three unified workflows for landing code changes: **commit**, **propose**, and **pull request**. All three
share the same CLI command (`sase commit`), the same `CommitWorkflow` orchestrator, and the same VCS provider
abstraction, but differ in what they produce and how they track the result.

## Overview

| Workflow    | XPrompt    | Method                | What it produces             | Tracking      |
| ----------- | ---------- | --------------------- | ---------------------------- | ------------- |
| **Commit**  | `#commit`  | `create_commit`       | Git commit on current branch | COMMITS entry |
| **Propose** | `#propose` | `create_proposal`     | Saved diff file              | COMMITS entry |
| **PR**      | `#pr`      | `create_pull_request` | New branch + PR              | ChangeSpec    |

## How It Works

### 1. Agent makes code changes

The agent receives an xprompt (`#commit`, `#propose`, or `#pr`) which sets the `SASE_COMMIT_METHOD` environment variable
and injects an instruction telling the agent **not** to create commits directly.

### 2. Stop hook triggers the commit

When the agent finishes, the **stop hook** (`sase_commit_stop_hook`) detects uncommitted changes and blocks the agent
with an instruction to use its `/sase_git_commit` or `/sase_hg_commit` skill. The skill calls:

```bash
sase commit '<json_payload>' -t <method>
```

The method defaults to `$SASE_COMMIT_METHOD` if the `-t` flag is omitted.

### CLI Arguments

| Short | Long                | Description                                                                                                                                                                                                                                                                 |
| ----- | ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-m`  | `--message`         | Commit message string (mutually exclusive with `-M`)                                                                                                                                                                                                                        |
| `-M`  | `--message-file`    | Path to file containing the commit message / PR description (mutually exclusive with `-m`)                                                                                                                                                                                  |
| `-f`  | `--file`            | File to stage (repeatable; omit to stage all)                                                                                                                                                                                                                               |
| `-n`  | `--name`            | Branch/CL name (required for `create_pull_request`)                                                                                                                                                                                                                         |
| `-b`  | `--bead-id`         | Bead ID to close and associate with the commit                                                                                                                                                                                                                              |
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
Precommit command  (e.g. `just fix`)
    |
Bead lifecycle     (close bead, sync beads, inject bead ID into message)  [skip for proposals]
    |
Plan handling      (append PLAN= to message, mark plan done)              [skip for proposals]
    |
PR tags            (append configured pr_tags as TAG=VALUE lines)         [PR only]
    |
Detect parent CL   (auto-set PARENT from current branch's ChangeSpec)     [PR only]
    |
PR name suffixing  (compute _<N> suffix for unique branch names)          [PR only]
    |
VCS dispatch       (call provider.create_commit / create_proposal / create_pull_request)
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

## Payload Format

All three methods accept the same JSON payload structure:

```json
{
  "message": "Commit message (required for commit/propose)",
  "name": "Branch or PR name (required for PR)",
  "files": ["optional", "list", "of", "specific", "files"],
  "bead_id": "optional-bead-id-to-close"
}
```

Internal fields added by `CommitWorkflow`:

| Field              | Set by              | Purpose                                 |
| ------------------ | ------------------- | --------------------------------------- |
| `_cl_name`         | Environment         | Fallback CL name for proposals          |
| `_plan_path`       | `_handle_sase_plan` | Plan file path for VCS staging          |
| `_pr_body`         | `_build_pr_body`    | Enriched PR description with agent info |
| `_skip_bead_amend` | Internal            | Skip post-commit bead amend             |

## Result Format

After a successful dispatch, `commit_result.json` contains:

```json
{
  "method": "create_commit",
  "result": "<commit_hash | diff_path | null>",
  "message": "The commit message",
  "name": "Branch/CL name",
  "bead_id": "Bead ID if provided",
  "changespec_name": "ChangeSpec name (PR only)",
  "entry_id": "COMMITS entry ID (commit/propose only)"
}
```

## Workflow Details

### Commit (`#commit`)

Creates an actual git commit on the current branch and pushes it.

**Git operations:**

1. Stage files (`git add -A` or specific files)
2. Stage `.sase_beads/` directory and plan file
3. Validate staged changes exist
4. Merge with `origin/master` to keep branch current
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
proposals don't represent landed changes.

### Pull Request (`#pr`)

Creates a new branch, commits changes, pushes, and creates a PR (via the GitHub plugin or equivalent).

**Input parameters:**

```yaml
input:
  - name: name # Branch/PR name (required)
    type: word
  - name: bug_id # Bug ID (optional, default: 0)
    type: int
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
the BUG field of the created ChangeSpec (as `http://b/<bug_id>`), and a `BUG=<bug_id>` line prepended to the PR tag
block (taking precedence over any static `BUG` key in `vcs_provider.pr_tags` config).

**Project prefix:** When `vcs_provider.use_project_pr_prefix` is `true`, a `[<project>] ` prefix is prepended to the PR
title (GitHub) or CL description (Mercurial). This prefix is only applied to the external representation — it does not
appear in the ChangeSpec DESCRIPTION or git commit message, and is automatically stripped when reading descriptions
back.

**PR tag inheritance:** When creating a child PR (one whose PARENT is an existing ChangeSpec), PR tags from the parent
PR's body are automatically inherited. The merge order is: parent PR tags (lowest priority) -> config `pr_tags` -> `BUG`
tag (highest priority). This ensures child PRs carry forward metadata like team tags without manual re-entry.

**PR tags:** Any key-value pairs configured in `vcs_provider.pr_tags` are appended as `TAG=VALUE` lines to the commit
message before building the PR body. This supports provider-specific metadata (e.g., Google CL tags) without manual
entry. See [configuration.md](configuration.md#vcs_provider) for the config format.

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

| State      | Exit code | Meaning                                                                         |
| ---------- | --------- | ------------------------------------------------------------------------------- |
| `OK`       | `0`       | Commit succeeded end-to-end (or resume replayed tracking).                      |
| `FAILED`   | `1`       | Unrecoverable failure — bail out, no checkpoint is left behind on fatal errors. |
| `CONFLICT` | `2`       | VCS dispatch hit a merge conflict; a checkpoint is left on disk for resume.     |

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

1. `CommitWorkflow.run()` snapshots its resolved state (payload, CL name, project file, diff path, reserved name, parent
   CL) to the checkpoint **before** calling the VCS dispatch method.
2. If dispatch succeeds, the checkpoint is updated with the dispatch result, tracking steps run, and the file is deleted
   on success.
3. If dispatch fails because of a merge conflict (`RunResult.CONFLICT`), the checkpoint is retained and the CLI prints:

   > `create_commit` hit a merge conflict: ... Resolve the conflict, then run `sase commit --resume` to finish.

**Resume flow (`sase commit --resume`):**

1. Load the checkpoint from disk (if missing, the command errors out).
2. Re-check the working tree for conflict markers — if they're still present, refuse to continue with `CONFLICT`.
3. Verify the commit at `HEAD` matches the subject line from the checkpointed message. If it doesn't, abort with
   `FAILED`; the user is expected to re-run `sase commit` from scratch rather than resume into a foreign commit.
4. Call the provider's `vcs_finalize_commit` hook to replay idempotent post-commit work (bead amend, push with retry).
5. Re-run the tracking steps (COMMITS entry append, ChangeSpec creation) using the snapshotted payload.
6. Delete the checkpoint on success.

Resume is VCS-agnostic: the same `--resume` flag works for commits, proposals, and PRs. Skills emit the on-conflict
instructions automatically, so agents know to hand control back to the user rather than retry blindly.

## Environment Variables

| Variable                  | Purpose                                                 |
| ------------------------- | ------------------------------------------------------- |
| `SASE_COMMIT_METHOD`      | Dispatch method (set by xprompt `environment:` section) |
| `SASE_ARTIFACTS_DIR`      | Directory for `commit_result.json` and other artifacts  |
| `SASE_PLAN`               | Plan file path for staging and status update            |
| `SASE_AGENT_PROJECT_FILE` | Project file for COMMITS/ChangeSpec tracking            |
| `SASE_AGENT_CL_NAME`      | CL name used for proposal diff naming                   |
| `SASE_PR_NAME`            | PR name (set by `#pr` xprompt input)                    |
| `SASE_BUG_ID`             | Bug ID for PR metadata                                  |
| `SASE_VCS_PROVIDER`       | Override VCS provider detection (see [vcs.md](vcs.md))  |

## Stop Hook

The `sase_commit_stop_hook` (`src/sase/scripts/sase_commit_stop_hook.py`) is the bridge between the agent and the commit
workflow. It runs as a post-completion hook in Claude, Gemini, and Codex runtimes.

**Flow:**

1. Detect the project directory from runtime-specific env vars
2. Check for uncommitted changes via the VCS provider
3. If changes exist, emit a blocking instruction telling the agent to use its commit skill
4. The instruction message includes the commit method type (e.g., "The commit method type is `create_pull_request`") so
   the agent knows which method to use
5. For `create_pull_request`, the instruction also includes the PR name (from `SASE_PR_NAME` or a placeholder) and the
   project prefix if available
6. The commit skill resolves to `/sase_git_commit` or `/sase_hg_commit` based on the detected VCS provider (note:
   `/sase_hg_commit` is only installed for Gemini — see AGENTS.md "Commit Skills per Runtime")

The hook supports deduplication (Gemini), structured JSON output (Codex), and stderr messaging (Claude).

## Diff Storage

Diffs saved by proposals (and other operations) are stored in:

```
~/.sase/diffs/<name>-<timestamp>.diff     # Active diffs
~/.sase/reverted/<name>.diff              # Reverted CLs
~/.sase/archived/<name>.diff              # Archived CLs
```

Diffs can be re-applied to a workspace with `apply_diff_to_workspace()` from `sase.workflows.commit_utils.workspace`.

## Design Principles

- **Fail-fast:** If `commit_result.json` is missing when the xprompt post-steps run, the workflow fails explicitly
  rather than silently retrying. The stop hook is the only path to commit creation.
- **Single responsibility:** `CommitWorkflow` owns all orchestration (precommit, beads, plans, VCS dispatch, tracking).
  XPrompt steps only read and report results.
- **Proper proposal semantics:** Proposals save diffs and clean the workspace without creating commits. Bead lifecycle
  and plan handling are skipped because proposals don't represent landed changes.
- **VCS agnostic:** The same `CommitWorkflow` and xprompt definitions work across Git, GitHub, and Mercurial backends.
  Only the VCS plugin implementation differs.
