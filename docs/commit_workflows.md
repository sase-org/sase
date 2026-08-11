# Commit Workflows

Sase provides three unified workflows for landing code changes: **commit**, **propose**,
and **pull request**. All three share the same commit CLI command
(`sase stitch create`), the same `CommitWorkflow` orchestrator, and the same VCS
provider abstraction, but differ in what they produce and how they track the result.

## Overview

| Workflow    | XPrompt    | Method                | What it produces             | Tracking       |
| ----------- | ---------- | --------------------- | ---------------------------- | -------------- |
| **Commit**  | `#commit`  | `create_commit`       | Git commit on current branch | STITCHES entry |
| **Propose** | `#propose` | `create_proposal`     | Saved diff file              | STITCHES entry |
| **PR**      | `#pr`      | `create_pull_request` | New branch + PR              | Patch          |

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
sase stitch create -> CommitWorkflow -> VCS provider -> tracked output
```

## How It Works

### 1. Agent makes code changes

The agent receives an xprompt (`#commit`, `#propose`, or `#pr`) which sets the
`SASE_COMMIT_METHOD` environment variable and injects an instruction telling the agent
**not** to create commits directly.

### 2. Commit finalizer checks for uncommitted work

When a provider invocation succeeds inside a SASE-launched agent session, the
provider-neutral **commit finalizer** runs in the shared LLM invocation layer before
normal success postprocessing. In practice this means the process has
`SASE_AGENT_TIMESTAMP` set. The finalizer checks the main workspace for uncommitted
changes through the active VCS provider. It enforces configured linked repositories at
their host-scoped workspace paths. Repositories opened through `/sase_repo`, including
external repos, are also recorded for ACE context and the durable repo-open audit log
and become finalizer candidates. It does not scan arbitrary same-remote numbered
workspaces just because their paths appear in run artifacts. If everything is clean, the
agent response is postprocessed normally.

There is one special case before the normal enforced-work follow-up path:

- If the only enforced dirty file is a tracked markdown file under `sdd/plans/`, and the
  only file diff is one leading-front-matter line changing from `status: wip` to
  `status: done`, SASE creates a direct closeout commit with the message
  `chore: Mark SDD plan done` and a `SASE_TYPE=sdd` runtime tag. If enforced changes
  remain, the finalizer starts bounded follow-up passes with the same provider. Each
  pass sends one follow-up prompt that lists dirty files and instructs the agent to use
  a commit skill such as `/sase_git_commit` or `/sase_hg_commit`. For the main
  workspace, the skill name is selected from the detected VCS provider;
  provider-specific generated skills can be scoped to the runtimes that support that
  provider. For configured linked repos, the current finalizer checks `git status` only
  in the resolved linked-repo `workspace_dir` assigned to the same workspace number
  after that linked-repo name appears in `opened_linked_workspaces.json`, and emits Git
  commit-skill instructions that first `cd` into that linked workspace. Dirty linked
  repos are enforced after they are opened.

Generated skills normally run an observable wrapper such as `sase_git_commit`, which
records skill invocation evidence and then delegates to `sase stitch create`. A typical
Git skill invocation omits `--type` because the xprompt already set
`SASE_COMMIT_METHOD`:

```bash
sase_git_commit -M .sase/commit_message.md -f src/example.py
```

The skill writes the message file under `.sase/` because that directory is git-ignored
in every SASE-managed checkout, so the temporary file can never trip the commit
finalizer's dirty check.

The low-level equivalent is
`sase stitch create -M .sase/commit_message.md -f src/example.py -t <method>`. The
method defaults to `$SASE_COMMIT_METHOD` if the `-t` flag is omitted. If both the
environment and `-t/--type` are set, they must resolve to the same method unless
`SASE_COMMIT_METHOD_ALLOW_OVERRIDE=1` is set.

If `SASE_BEAD_ID` is set, the finalizer first asks the agent to decide whether the
uncommitted changes were made in the current session. For changes the agent did make, it
instructs the agent to close and verify the bead before invoking the commit skill. This
keeps bead lifecycle state ahead of the commit/proposal/PR dispatch while avoiding
accidental closure for unrelated dirty work.

The finalizer uses the shared instruction helpers in `sase.commit_instructions`, so the
bead and method wording stays consistent between main-workspace and linked-repository
commit guidance. `commit.finalizer.max_passes` controls how many follow-up invocations
may run before SASE fails the invocation with a clear error and, when an artifacts
directory is available, a `commit_finalizer_result.json` artifact.

### CLI Arguments

| Short | Long                  | Description                                                                                                                                                                                                                                                           |
| ----- | --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-m`  | `--message`           | Commit message string (mutually exclusive with `-M`)                                                                                                                                                                                                                  |
| `-M`  | `--message-file`      | Path to file containing the commit message / PR description (mutually exclusive with `-m`)                                                                                                                                                                            |
| `-f`  | `--file`              | File to stage (repeatable; omit to stage all)                                                                                                                                                                                                                         |
| `-n`  | `--name`              | Branch/PR name (required for `create_pull_request`)                                                                                                                                                                                                                   |
| `-b`  | `--bug-id`            | Bug ID to associate with the commit (overrides `$SASE_BUG_ID`)                                                                                                                                                                                                        |
| `-B`  | `--do-not-close-bead` | Do not auto-close the assigned in-progress task bead after commit                                                                                                                                                                                                     |
| `-c`  | `--checkout-target`   | Branch point for PR (default: `HEAD~1`)                                                                                                                                                                                                                               |
| `-p`  | `--parent`            | Parent Patch **name** (overrides auto-detection from current branch). Must be an existing Patch in the current ProjectSpec or its archive — if it does not resolve, the PARENT field is omitted with a warning. Never pass a VCS ref (e.g., `origin/main`, `p4head`). |
| `-r`  | `--resume`            | Resume a previously-checkpointed commit after manual conflict resolution. When set, `-m` / `-M` / `-f` and other commit args are ignored (the payload is loaded from the checkpoint). See [Resume after Conflict](#resume-after-conflict) below.                      |
| `-s`  | `--status`            | Patch status for PRs (`wip`, `draft`, `ready`). Overrides `$SASE_PR_STATUS`; default is `draft`.                                                                                                                                                                      |
| `-t`  | `--type`              | Commit method — accepts full names or short aliases (see table below)                                                                                                                                                                                                 |

#### Type Aliases

The `-t/--type` flag accepts both full method names and short aliases:

| Alias     | Full Method           |
| --------- | --------------------- |
| `commit`  | `create_commit`       |
| `propose` | `create_proposal`     |
| `pr`      | `create_pull_request` |

The STITCHES entry note is always derived from the first line of the commit message —
there is no separate `--note` flag.

### 3. CommitWorkflow orchestrates

`CommitWorkflow` (`src/sase/workflows/commit/workflow.py`) is the central dispatcher. It
runs through these stages:

```
Subject gate       (reject a non-Conventional-Commit subject before any side effect)
    |
Bead association   (append linked SASE_BEAD= footer when SASE_BEAD_ID is set)
    |
Bead sync          (sync beads; warn if the assigned bead will not auto-close) [skip for proposals]
    |
Plan handling      (store/copy plan, append storage-relative SASE_PLAN=,  [skip for proposals]
                    mark plan done)
    |
Before hook        (`commit_hooks.before`, e.g. `just fix`)
    |
PR name suffixing  (compute _<N> suffix for unique branch names)          [PR only]
    |
Detect parent PR   (auto-set PARENT from current branch's Patch)          [PR only]
    |
PR metadata        (append PR tags and project prefix)                    [PR only]
    |
Runtime tags       (append/update linked global SASE_AGENT= provenance)   [commit/PR only]
    |
PR body            (build body with final tags and agent footer)          [PR only]
    |
Diff capture       (save the pre-dispatch diff for tracking)
    |
Checkpoint         (save resolved payload and tracking state for resume)
    |
VCS dispatch       (call provider.create_commit / create_proposal / create_pull_request)
    |
File-hook events   (capture the committed revision; best effort)          [commit/PR only]
    |
After hook         (`commit_hooks.after`, after commit/push)              [commit/PR only]
    |
Patch creation     (create Patch entry in project file)                    [PR only]
    |
Initial marker     (write commit_result.json)                 [when SASE_ARTIFACTS_DIR is set]
    |
Publication        (bead pages and plan header; agent artifacts when applicable)
                                                                          [commit/PR only]
    |
STITCHES entry      (append entry to project file)                         [commit/propose only]
    |
Final marker       (rewrite with the new stitch ID)           [commit/propose, if appended]
    |
DELTAS refresh     (recompute the tracked diff summary)       [commit/propose, if Patch found]
    |
Task bead autoclose (close the eligible in-progress task bead)      [commit/PR only, last]
```

The marker is deliberately written before publication and STITCHES tracking so a
successful dispatch has a durable hand-off before retryable post-dispatch work begins.
When a commit or proposal is appended to a Patch, SASE rewrites the marker so the final
copy includes `stitch_id`. A normal CLI invocation outside an agent or xprompt run may
not set `SASE_ARTIFACTS_DIR`; in that case no result-marker files are written.

The **subject gate** runs first, immediately after payload-shape validation and before
bead lifecycle handling, plan staging, and the before hook. If the first line of the
message is not a Conventional Commit (`<type>[(<scope>)][!]: <description>`), the
workflow fails with an actionable error and nothing else has run — no bead is closed for
a commit that never happened. Merge, revert, and fixup subjects are exempt; empty
messages are rejected. The failure is recorded on the `commit_failed` run-log event with
`reason="invalid_message"`, and `sase stitch create` preserves the `-M` message file so
the same command can be re-run after the subject is rewritten. Configure the gate
through `commit.message` (see [Configuration](configuration.md#commitmessage)).

For PRs, the subject is validated exactly as the agent authored it.
`vcs_provider.use_project_pr_prefix: true` prepends a `[project] ` prefix to the PR
title _after_ validation, so the final title on the pull request can differ from the
validated subject.

#### Task Bead Autoclose

As the last stage of `CommitWorkflow`, `create_commit` and `create_pull_request` (never
`create_proposal`) auto-close the bead assigned to the commit, provided all of the
following hold:

- The bead's `issue_type` is `task` — phase, epic, and plan beads are skipped.
- The bead's `status` is `in_progress`.
- The commit's repository root is the project's primary repo — commits made in a
  configured linked repository or an SDD sidecar are skipped, since those never carry
  the project's own task lifecycle.

When all conditions hold, SASE runs the equivalent of
`sase bead close <id> --resolution done --note "<note>"`, where the note reads:

> Auto-closed by `sase stitch create` after `<method>` landed `<short-sha>`
> ("`<subject>`"). No verification is implied by this note. Reopen with
> `sase bead open <id>`, or pass `-B`/`--do-not-close-bead` on mid-flight commits.

and the CLI prints
`Auto-closed task bead <id>. Reopen with sase bead open <id> if more work remains.` Pass
`-B/--do-not-close-bead` (see [CLI Arguments](#cli-arguments) above) on any commit that
is not the task's final commit, since an intermediate commit would otherwise close the
bead before the work is done. See
[Standalone Task Workflow](beads.md#standalone-task-workflow) for how this fits into the
broader task-bead lifecycle.

### 4. XPrompt reads the result

The built-in xprompt post-steps read `commit_result.json` from `$SASE_ARTIFACTS_DIR` and
emit metadata outputs such as `meta_new_commit` and `meta_commit_message`. Their Patch
output is still named `meta_changespec` for workflow compatibility. When SASE projects
the completed agent run into agent metadata, it adds canonical `meta_patch` and retains
`meta_changespec` as an alias.

## CLI Inputs and Internal Payload

The `sase stitch create` CLI builds an internal `CommitWorkflow` payload from flags. It
does **not** accept a positional JSON payload.

Typical commit or proposal:

```bash
sase stitch create -M .sase/commit_message.md -f src/auth.py -f src/login.py -t commit
```

Typical PR:

```bash
sase stitch create -M .sase/pr_description.md -n feature_branch -b 12345 -s ready -t pr
```

The internal payload has this shape:

```json
{
  "message": "Commit message (required for commit/propose)",
  "name": "Branch or PR name (required for PR)",
  "files": ["optional", "list", "of", "specific", "files"]
}
```

The CLI maps `-m` / `-M` to `message`, repeated `-f` flags to `files`, `-n` to `name`,
`-b` to `bug_id`, `-B` to `do_not_close_bead`, `-c` to `checkout_target`, `-p` to
`parent`, and `-s` to `status`. Omitted `-f` means "stage all changes" and is
represented as an empty `files` list.

Bead association is not a user-supplied CLI flag. For new commit attempts,
`sase stitch create` reads `SASE_BEAD_ID`; when it is set, the CLI adds that bead to the
workflow payload, and `CommitWorkflow` leaves the subject unchanged while adding
`SASE_BEAD=<id>` as the first structured footer tag. When the project's beads sidecar is
hosted on GitHub, the tag is a Markdown reference link to the bead's generated page in
the `--beads` repository; otherwise it remains the bare ID. Resolution is local-only and
best-effort. Conflict resumes reuse the already-tagged message captured in the original
checkpoint.

Runtime provenance tags are also not user-supplied CLI flags. For `create_commit` and
`create_pull_request`, `CommitWorkflow` appends or updates a trailing
`SASE_AGENT=<username>.<machine>.<lane>` line. The value is the committing agent's
**lane**, not the concrete agent that ran: a family member commits as its family
(`pc--code` is tagged `<username>.<machine>.pc`), and a solo agent is tagged with its
own name exactly as before. When the configured agents sidecar is hosted on GitHub, the
value is a Markdown reference link to the lane's page — the family page for a family
lane and the agent README for a solo lane — with no `#member-<role>` fragment. Every
fallback path (no owner, no project, unresolvable or non-hosted sidecar) still emits the
lane label unlinked. `AGENT` comes from `SASE_AGENT_NAME`, falling back to
`SASE_ARTIFACTS_DIR/agent_meta.json` — the concrete member name is resolved first only
so its lane can be derived — and it is omitted for manual non-agent commits. New commits
never produce `SASE_MACHINE`, while cleanup still removes inherited `AGENT` and
historical `MACHINE` values. `create_proposal` does not get runtime commit tags because
it saves a diff instead of creating a VCS commit.

After an agent-backed primary operation and its first durable result marker, the
workflow first refreshes the committed bead's generated page lineage when the message
carries `SASE_BEAD=`. It then resolves the immutable primary revision through the VCS
provider and resolves the project's agents target. When that target is available, SASE
records a project-scoped outbox request for only that agent's top-level hood before
attempting publication. The attempt also drains older requests for the project. A
failure after enqueueing does not invalidate the primary commit; the request remains for
a later agent commit or full `sase agent sync`. Target-resolution and outbox-persistence
failures occur before that durability guarantee, so they can instead skip publication or
require `sase stitch create --resume`.

**Footer tag prefix:** All SASE-authored commit footer tags (`TYPE`, `BEAD`, `AGENT`,
`PLAN`, `BUG`, and any configured or inherited PR tag keys) are written with a `SASE_`
prefix — for example `SASE_TYPE=sdd` and `SASE_AGENT=<name>`. Readers
(agent-commit/revert discovery, parent-PR tag inheritance, Patch description stripping)
still accept historical `MACHINE` tags and the unprefixed spelling, so commit history is
not rewritten and old commits remain readable. External consumers should accept both
historical and `SASE_`-prefixed spellings.

**Legacy `SASE_AGENT` values:** commits written before provenance moved to the lane
carry a concrete member name and a `#member-<role>` anchor — for example
`SASE_AGENT=[bbugyi200.athena.pc--code][2]` pointing at
`families/bbugyi200.athena.pc.md#member-code`. History is never rewritten, so every
reader (inventory history, import evidence, revert discovery, image-attachment scanning,
plan and bead associations, the PR body footer) accepts both spellings permanently: a
member-named tag keeps its exact per-run attribution, while a lane-named tag is
attributed to the lane. Readers that need a link for a tag prefer the destination
recorded in the footer itself, because that URL already distinguishes a family page from
a solo agent page for commits from either era.

Internal fields added by `CommitWorkflow`:

| Field              | Set by              | Purpose                                                     |
| ------------------ | ------------------- | ----------------------------------------------------------- |
| `_cl_name`         | Environment         | Fallback PR name for proposals                              |
| `_plan_path`       | `_handle_sase_plan` | Plan file path for VCS staging                              |
| `_pr_body`         | `_build_pr_body`    | Enriched PR description with agent info                     |
| `_skip_bead_amend` | Internal            | Skip folding post-commit bead-store changes into the commit |
| `bead_id`          | Environment         | Source ID for the linked `SASE_BEAD=` footer tag            |

## Result Format

When `SASE_ARTIFACTS_DIR` is set, post-dispatch tracking writes `commit_result.json`
after the applicable after hook succeeds. A representative final marker for a commit is:

```json
{
  "method": "create_commit",
  "run_id": "260809_123456",
  "cwd": "/path/to/repository",
  "result": "abc123",
  "message": "fix: handle empty input",
  "name": "",
  "bead_id": "sase-abcd",
  "patch_name": null,
  "commit_patch_name": null,
  "stitch_id": "2",
  "diff_path": "/path/to/pre-dispatch.diff"
}
```

`repo_name` appears only when the dispatch directory is a linked, external, or SDD
sidecar repository rather than the agent's primary checkout. `committed_at` appears only
when SASE can resolve the revision's author timestamp; its value is an integer Unix
timestamp. `result` and `diff_path` may be `null`; `name` and `bead_id` may be empty
strings. The Patch fields are populated by PR creation and otherwise are `null`.
`stitch_id` starts as `null` in the initial marker and is populated only when a commit
or proposal is successfully appended to an existing Patch's STITCHES section.

For compatibility with older consumers, the same marker dual-writes `changespec_name` /
`commit_changespec_name` for the Patch, `entry_id` / `commit_entry_id` for the stitch,
`commit_result` for `result`, and `commit_diff_path` for `diff_path`. New consumers
should read `patch_name` (or `commit_patch_name`) and `stitch_id` first.

## Workflow Details

### Commit (`#commit`)

Creates an actual git commit on the current branch and pushes it.

**Git operations:**

1. Stage files (`git add -A` or specific files)
2. Stage in-repo SDD bead and plan files when present
3. Validate staged changes exist
4. Merge with `origin/<default_branch>` to keep the branch current
5. `git commit -m <message>`
6. Fold any straggler bead-store changes into the commit via amend
7. Push to remote with retry on failure

**Returns:** `(True, commit_hash)`

**Tracking:** Appends a STITCHES entry to the project file with the commit note, diff
path, chat path, and plan path (when `SASE_PLAN` is set). Multi-line commit messages are
supported: the first paragraph becomes the note, and subsequent paragraphs (separated by
a blank line) become an indented body below the note. Empty body lines are stored as a
dot (`.`) placeholder to preserve structure. See
[change_spec.md](change_spec.md#stitches) for the full entry format including drawers.

### Propose (`#propose`)

Saves the current diff without committing and cleans the workspace. This is useful for
parking work-in-progress changes that aren't ready to land.

**Git operations:**

1. Save diff to `~/.sase/diffs/<cl_name>-<timestamp>.diff`
2. Clean workspace (`git reset --hard HEAD` + `git clean -fd`)

**Returns:** `(True, diff_path)`

**Tracking:** Appends a proposal STITCHES entry to the project file. Bead lifecycle and
plan handling are skipped because proposals don't represent landed changes. Runtime
`AGENT` and `MACHINE` commit tags are also skipped because no VCS commit is created.

### Pull Request (`#pr`)

Creates a new branch, commits changes, pushes, and creates a PR (via the GitHub plugin
or equivalent).

**Input parameters:**

```yaml
input:
  - name: name # Branch/PR name (required)
    type: word
  - name: bug_id # Bug ID (optional, default: 0)
    type: int
  - name: status # Initial Patch status: draft, wip, or ready (optional, default: draft)
    type: word
```

**Git operations:**

1. `git checkout -b <name>` (create new branch)
2. Stage files and bead/plan paths
3. `git commit -m <message>`
4. `git push -u origin <name>`
5. (GitHub plugin creates the actual PR via `gh`)

**Returns:** `(True, pr_url)` after GitHub plugin processing

**Parent detection:** If the current branch corresponds to an existing Patch, that Patch
is automatically set as the PARENT of the new PR Patch. This creates a chain of related
changes without manual bookkeeping.

**BUG propagation:** When `SASE_BUG_ID` is set in the environment and non-zero, the
value is propagated to two places: the BUG field of the created Patch (as
`http://b/<bug_id>`), and a `SASE_BUG=<bug_id>` line prepended to the PR tag block
(taking precedence over any static `BUG` key in `vcs_provider.pr_tags` config).

**Project prefix:** When `vcs_provider.use_project_pr_prefix` is `true`, a
`[<project>] ` prefix is prepended to the PR title (GitHub) or PR description
(Mercurial). This prefix is only applied to the external representation — it does not
appear in the Patch DESCRIPTION or git commit message, and is automatically stripped
when reading descriptions back.

**PR tag inheritance:** When creating a child PR (one whose PARENT is an existing
Patch), PR tags from the parent PR's body are automatically inherited. Parent tags are
read in either spelling — legacy `TAG=` or new `SASE_TAG=` — so inheritance works across
the migration. The merge order is: parent PR tags (lowest priority) -> config `pr_tags`
-> `BUG` tag (highest priority), followed by runtime-owned `AGENT` and `MACHINE` tags.
Inherited or configured `AGENT` and `MACHINE` values are ignored so child PRs do not
retain stale parent runtime provenance.

**PR tags:** Any key-value pairs configured in `vcs_provider.pr_tags` are appended as
`SASE_TAG=VALUE` lines to the commit message before building the PR body. This supports
provider-specific metadata (e.g., Google PR tags) without manual entry. `AGENT` and
`MACHINE` are reserved for runtime provenance and are owned by the commit workflow
rather than static config. Note that the rendered keys carry the `SASE_` prefix (e.g. a
configured `MARKDOWN` tag is written as `SASE_MARKDOWN=`), so external tooling that
consumes these tags must accept the prefixed names. See
[configuration.md](configuration.md#vcs_provider) for the config format.

**PR tag stripping:** When PR tags are present in the commit description (trailing lines
matching `^[A-Z][A-Z0-9_]*=`), they are automatically stripped before writing the
DESCRIPTION field of the created Patch. This prevents provider-specific metadata (e.g.,
`AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT`, `MARKDOWN=true`) from polluting the human-readable
description. The same stripping is applied when syncing descriptions after a reword
operation.

**Tracking:** Creates a Patch in the project file (not a STITCHES entry). The PR name is
automatically suffixed with `_<N>` if a Patch with the same base name already exists.

## VCS Provider Abstraction

The three dispatch methods are defined in `VCSHookSpec` and implemented by each VCS
plugin:

| Plugin          | `create_commit`    | `create_proposal` | `create_pull_request`     |
| --------------- | ------------------ | ----------------- | ------------------------- |
| `BareGitPlugin` | Commit + push      | Save diff + clean | Branch + commit + push    |
| `GitHubPlugin`  | Inherits from git  | Inherits from git | + creates PR via `gh` CLI |
| `HgPlugin`      | `hg commit` + mail | `sase_hg_clean`   | Not supported natively    |

All methods return `tuple[bool, str | None]` (success flag and optional result string).

Plugins that support resume also implement `vcs_finalize_commit(payload, cwd)`, which
re-runs the idempotent portion of a commit (bead amend, push with retry) after a
previously-checkpointed workflow has had its merge conflicts resolved by hand. See
[Resume after Conflict](#resume-after-conflict) below for how this fits into the overall
flow. Providers that cannot safely replay finalization (e.g., Mercurial today) can leave
it unimplemented — `CommitWorkflow.resume` catches the `NotImplementedError` and only
replays the tracking steps.

## Run Result

`CommitWorkflow.run()` and `CommitWorkflow.resume()` return a `RunResult` with three
states:

| State      | Exit code | Meaning                                                                       |
| ---------- | --------- | ----------------------------------------------------------------------------- |
| `OK`       | `0`       | Commit succeeded end-to-end (or resume replayed tracking).                    |
| `FAILED`   | `1`       | Failure; an after-hook failure keeps its post-dispatch checkpoint for resume. |
| `CONFLICT` | `2`       | VCS dispatch hit a merge conflict; a checkpoint is left on disk for resume.   |

The `sase stitch create` CLI propagates these states to its process exit code, so
wrapper skills (`/sase_git_commit`) can branch on `$?` to distinguish a real failure
from a conflict that the user needs to resolve.

## Resume after Conflict

`CommitWorkflow` persists its progress to a checkpoint file so that a dispatch
interrupted by a merge conflict can be finished by hand without re-running the whole
flow:

```
SASE_ARTIFACTS_DIR/commit_state.json              # preferred, when running under a workflow
~/.sase/commit_state/<session>.json               # fallback when no artifacts dir is set
```

**Normal flow:**

1. `CommitWorkflow.run()` snapshots its resolved state (payload, PR name, project file,
   diff path, reserved name, parent PR) to the checkpoint **before** calling the VCS
   dispatch method.
2. If dispatch succeeds for a commit or PR, the checkpoint is updated with the dispatch
   result and `commit_hooks.after` runs before tracking. Proposals skip the after hook.
3. If the after hook and tracking succeed, their completed steps are checkpointed and
   the file is deleted.
4. If dispatch fails because of a merge conflict (`RunResult.CONFLICT`), the checkpoint
   is retained and the CLI prints:

   > `create_commit` hit a merge conflict: ... Resolve the conflict, then run
   > `sase stitch create --resume` to finish.

**Resume flow (`sase stitch create --resume`):**

1. Load the checkpoint from disk (if missing, the command errors out).
2. Re-check the working tree for conflict markers — if they're still present, refuse to
   continue with `CONFLICT`.
3. Verify the commit at `HEAD` matches the subject line from the checkpointed message.
   If it doesn't, abort with `FAILED`; the user is expected to re-run
   `sase stitch create` from scratch rather than resume into a foreign commit.
4. If dispatch was not already completed, call the provider's `vcs_finalize_commit` hook
   to replay idempotent post-commit work (bead amend, push with retry), then checkpoint
   dispatch completion.
5. Run `commit_hooks.after` for commit/PR workflows unless its completion is already
   checkpointed.
6. Re-run the tracking steps (STITCHES entry append, Patch creation) using the
   snapshotted payload.
7. Delete the checkpoint on success.

Resume is VCS-agnostic: the same `--resume` flag works for commits, proposals, and PRs.
Skills emit the on-conflict instructions automatically, so agents know to hand control
back to the user rather than retry blindly.

An after-hook failure also uses this resume path: the commit may already be pushed, so
creating a new commit would risk duplication. Fix the hook and run
`sase stitch create --resume`; dispatch/finalization is skipped because its completed
step is already recorded. After hooks should be repeatable because a crash between
command success and checkpoint persistence has at-least-once execution semantics.

## Environment Variables

| Variable                            | Purpose                                                                                          |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ |
| `SASE_COMMIT_METHOD`                | Dispatch method (set by xprompt `environment:` section)                                          |
| `SASE_COMMIT_METHOD_ALLOW_OVERRIDE` | Allow `-t/--type` to override a conflicting `SASE_COMMIT_METHOD`                                 |
| `SASE_ARTIFACTS_DIR`                | Directory for `commit_result.json` and other artifacts                                           |
| `SASE_AGENT_NAME`                   | Agent name used for `SASE_AGENT=` runtime commit provenance                                      |
| `SASE_BEAD_ID`                      | Bead ID written as a linked `SASE_BEAD=` footer tag without changing the subject                 |
| `SASE_PLAN`                         | Plan source for storage/staging, status update, and the storage-relative `SASE_PLAN=` commit tag |
| `SASE_AGENT_PROJECT_FILE`           | Project file for Patch/STITCHES tracking                                                         |
| `SASE_AGENT_CL_NAME`                | PR name used for proposal diff naming                                                            |
| `SASE_PR_NAME`                      | PR name (set by `#pr` xprompt input)                                                             |
| `SASE_PR_STATUS`                    | Initial PR Patch status (`draft`, `wip`, `ready`)                                                |
| `SASE_BUG_ID`                       | Bug ID for PR metadata                                                                           |
| `SASE_VCS_PROVIDER`                 | Override VCS provider detection (see [vcs.md](vcs.md))                                           |
| `SASE_LINKED_REPOS_JSON`            | JSON metadata for configured linked repos passed to agents                                       |
| `SASE_LINKED_REPO_<ENV_NAME>_DIR`   | Workspace-matched path for one configured linked repo                                            |
| `SASE_DISABLE_COMMIT_STOP_HOOK`     | Skip the commit finalizer when set                                                               |

## Commit Finalizer

For SASE-launched agent sessions, the normal path is the provider-neutral finalizer in
`src/sase/llm_provider/commit_finalizer.py`. It runs after a successful provider
invocation and before success postprocessing. The finalizer is deliberately outside any
one runtime's native hook system, so Claude, Codex, Antigravity (`agy`), Qwen, OpenCode,
Muse Code, and provider plugins share the same behavior.

**Flow:**

1. Skip when `commit.finalizer.enabled` is false, `SASE_DISABLE_COMMIT_STOP_HOOK=1` is
   set, or the process is outside a SASE agent session (`SASE_AGENT_TIMESTAMP` is
   unset).
2. Resolve the project directory from provider/workspace environment variables.
3. Check the main workspace through the VCS provider's diff helpers.
4. Check configured linked repos from `SASE_LINKED_REPOS_JSON`, or from project config
   when available, with `git status --porcelain`; opened-workspace markers provide paths
   for linked repos opened during the run.
5. Auto-commit an exact tracked SDD markdown `status: wip` to `status: done` closeout
   when that is the only enforced change and the file is under `sdd/plans/`.
6. If dirty enforced repos exist, run follow-up provider invocations up to
   `commit.finalizer.max_passes`. When an artifacts directory is available, also write
   `commit_finalizer_pass_<N>_prompt.md` and `commit_finalizer_pass_<N>_response.md`.
7. Re-check every dirty target. If all enforced repos are clean, write
   `commit_finalizer_result.json` with status `finalized` when artifacts are enabled,
   and append the follow-up response to the agent's final response.
8. If enforced changes remain after `commit.finalizer.max_passes`, write status `failed`
   when artifacts are enabled and fail the invocation instead of silently accepting
   dirty work.

For projects whose SDD store lives in a separate or sidecar repository, the finalizer
also commits leftover bead state as a safety net (`chore(beads): sync bead state`) ahead
of each dirty-state check, then verifies that commit actually reached the remote — a
bead mutation that exists only in a workspace clone is destroyed when that workspace is
evicted. If it stayed local, `commit_finalizer_result.json` records `status: "failed"`
with `reason: "bead_state_unpublished"` and the full publication diagnostic instead of
`finalized`, and the invocation fails. The finalizer holds that failure until its return
points rather than raising it at the commit site, so the agent's own commit passes still
run first — otherwise a bead problem would strand uncommitted code in the workspace. On
the dirty-after-max-passes path (step 8) the publication diagnostic is appended to the
existing error so neither failure is swallowed. See
[Publication Verification](beads.md#publication-verification).

Configured linked repos are resolved to host-scoped directories before agent launch. For
example, an agent in `sase_10` sees a `../sase-core` linked repo at
`sase_10/sase/repos/linked/sase-core`. The linked-repo dirty-check path is Git-specific:
non-Git linked-repo paths can still be exposed through environment variables and
metadata, but the finalizer does not enforce them as dirty targets.

When the only enforced dirty state is the exact SDD status closeout described above, the
finalizer creates the commit itself instead of running a follow-up provider invocation.
The result artifact records `reason: "auto_committed_done_plan_status"`.

The obsolete provider-native commit hook scripts are no longer shipped. Active
SASE-launched runs rely on the provider-neutral finalizer instead of runtime-specific
commit hook configuration.

## Diff Storage

Diffs saved by proposals (and other operations) are stored in:

```
~/.sase/diffs/<name>-<timestamp>.diff     # Active diffs
~/.sase/reverted/<name>.diff              # Reverted PRs
~/.sase/archived/<name>.diff              # Archived PRs
```

Diffs can be re-applied to a workspace with `apply_diff_to_workspace()` from
`sase.workflows.commit_utils.workspace`.

## Design Principles

- **Fail-fast:** If `commit_result.json` is missing when the xprompt post-steps run, the
  workflow fails explicitly rather than silently retrying. The finalizer and commit
  skills are the sanctioned path to commit creation.
- **Single responsibility:** `CommitWorkflow` owns all orchestration (commit hooks,
  beads, plans, VCS dispatch, tracking). XPrompt steps only read and report results.
- **Proper proposal semantics:** Proposals save diffs and clean the workspace without
  creating commits. Bead lifecycle and plan handling are skipped because proposals don't
  represent landed changes.
- **VCS agnostic:** The same `CommitWorkflow` and xprompt definitions work across Git,
  GitHub, and Mercurial backends. Only the VCS plugin implementation differs.
