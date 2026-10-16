---
title: Commit workflows
description: Look up commit, proposal, and pull request workflow behavior.
---

# Commit workflows

This page describes the outcomes and user-facing behavior of commit workflows.

Sase provides three unified workflows for landing code changes: **commit**, **propose**,
and **pull request**. All three share the same commit CLI command
(`sase stitch create`), the same `CommitWorkflow` orchestrator, and the same VCS
provider abstraction, but differ in what they produce and how they track the result.

For steps to inspect an agent's work and complete a review, see
[Review and land a change](../../guides/review-and-land-change.md).

## Overview

| Workflow    | Macro      | Method                | What it produces             | Tracking       |
| ----------- | ---------- | --------------------- | ---------------------------- | -------------- |
| **Commit**  | `#commit`  | `create_commit`       | Git commit on current branch | STITCHES entry |
| **Propose** | `#propose` | `create_proposal`     | Saved diff file              | STITCHES entry |
| **PR**      | `#pr`      | `create_pull_request` | New branch + PR              | Patch          |

```
#commit / #propose / #pr
        |
        v
Agent edits files, then declares each dirty repo through /sase_final
        |
        v
Host-owned builtin@commit finalizer
        |
        v
sase stitch create -> CommitWorkflow -> VCS provider -> tracked output
```

Outside a SASE-launched agent turn, a human (or an agent explicitly told to commit) runs
the same `sase stitch create` command directly or through the `/sase_git_commit` skill.

## Workflow Details

### Commit (`#commit`)

Creates an actual git commit on the current branch and pushes it.

**Git operations:**

1. Stage files (`git add -A`, honoring `-x/--exclude`, or the internal allowlist)
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
[change_spec.md](../work-units/patches.md#stitches) for the full entry format including
drawers.

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
2. Stage files (honoring `-x/--exclude`, or the internal allowlist) and bead/plan paths
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
[Environment variables](../environment-variables.md#vcs-provider) for the config format.

**PR tag stripping:** When PR tags are present in the commit description (trailing lines
matching `^[A-Z][A-Z0-9_]*=`), they are automatically stripped before writing the
DESCRIPTION field of the created Patch. This prevents provider-specific metadata (e.g.,
`AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT`, `MARKDOWN=true`) from polluting the human-readable
description. The same stripping is applied when syncing descriptions after a reword
operation.

**Tracking:** Creates a Patch in the project file (not a STITCHES entry). The PR name is
automatically suffixed with `_<N>` if a Patch with the same base name already exists.

## Environment Variables

| Variable                            | Purpose                                                                                                                                                                                 |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_COMMIT_METHOD`                | Dispatch method (set by macro `environment:` section)                                                                                                                                   |
| `SASE_COMMIT_METHOD_ALLOW_OVERRIDE` | Allow `-t/--type` to override a conflicting `SASE_COMMIT_METHOD`                                                                                                                        |
| `SASE_ARTIFACTS_DIR`                | Directory for `commit_result.json` and other artifacts                                                                                                                                  |
| `SASE_AGENT_NAME`                   | Agent name used for `SASE_AGENT=` runtime commit provenance                                                                                                                             |
| `SASE_BEAD_ID`                      | Bead ID written as a linked `SASE_BEAD=` footer tag without changing the subject                                                                                                        |
| `SASE_PLAN`                         | Plan source for storage/staging, status update, and the storage-relative `SASE_PLAN=` commit tag; ignored once the plan is done or archived, and not inherited by nested agent launches |
| `SASE_AGENT_PROJECT_FILE`           | Project file for Patch/STITCHES tracking                                                                                                                                                |
| `SASE_AGENT_CL_NAME`                | PR name used for proposal diff naming                                                                                                                                                   |
| `SASE_PR_NAME`                      | PR name (set by `#pr` macro input)                                                                                                                                                      |
| `SASE_PR_STATUS`                    | Initial PR Patch status (`draft`, `wip`, `ready`)                                                                                                                                       |
| `SASE_BUG_ID`                       | Bug ID for PR metadata                                                                                                                                                                  |
| `SASE_VCS_PROVIDER`                 | Override VCS provider detection (see [VCS providers](providers.md))                                                                                                                     |
| `SASE_LINKED_REPOS_JSON`            | JSON metadata for configured linked repos passed to agents                                                                                                                              |
| `SASE_LINKED_REPO_<ENV_NAME>_DIR`   | Workspace-matched path for one configured linked repo                                                                                                                                   |

## Related

- [Version control](index.md) — the section hub.
