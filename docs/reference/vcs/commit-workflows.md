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
4. Merge with `origin/<default_branch>` to keep the branch current (a rebase conflict
   limited to generated state — bead events, artifact-link indexes, plan-header rows, or
   a linearly-ordered `revision_pin` — resolves mechanically first)
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
`AGENT`, `MODEL`, and `MACHINE` commit tags are also skipped because no VCS commit is
created.

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
read in either spelling — `TAG=` or `SASE_TAG=` — so inheritance works across the
migration. The merge order is: parent PR tags (lowest priority) -> config `pr_tags` ->
`BUG` tag (highest priority), followed by runtime-owned `AGENT` and `MODEL` tags.
Inherited or configured `AGENT`, `MODEL`, and `MACHINE` values are ignored so child PRs
do not retain stale parent runtime provenance.

**PR tags:** Any key-value pairs configured in `vcs_provider.pr_tags` are appended as
`SASE_TAG=VALUE` lines to the commit message before building the PR body. This supports
provider-specific metadata (e.g., Google PR tags) without manual entry. `AGENT`,
`MODEL`, and `MACHINE` are reserved for runtime provenance and are owned by the commit
workflow rather than static config. Note that the rendered keys carry the `SASE_` prefix
(e.g. a configured `MARKDOWN` tag is written as `SASE_MARKDOWN=`), so external tooling
that consumes these tags must accept the prefixed names. See
[Environment variables](../environment-variables.md#vcs-provider) for the config format.

Agent-backed commits and pull requests also carry `SASE_AGENT=` and, when the producing
turn's model is known, `SASE_MODEL=<provider>/<model>`. During a fallback retry, the
fallback model supplies the `SASE_MODEL` value. Manual commits omit both tags; proposals
omit them because they do not create commits.

**PR tag stripping:** When PR tags are present in the commit description (trailing lines
matching `^[A-Z][A-Z0-9_]*=`), they are automatically stripped before writing the
DESCRIPTION field of the created Patch. This prevents provider-specific metadata (e.g.,
`AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT`, `MARKDOWN=true`) from polluting the human-readable
description. The same stripping is applied when syncing descriptions after a reword
operation.

**Tracking:** Creates a Patch in the project file (not a STITCHES entry). The PR name is
automatically suffixed with `_<N>` if a Patch with the same base name already exists.

## Environment Variables

The shared `SASE_BEAD_ID`, `SASE_BUG_ID`, `SASE_VCS_PROVIDER`, and
`SASE_LINKED_REPOS_JSON` variables are listed in the
[environment-variable reference](../environment-variables.md#vcs-provider). This table
covers variables specific to commit workflows.

| Variable                            | Purpose                                                                                                                                                                                 |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SASE_COMMIT_METHOD`                | Dispatch method (set by macro `environment:` section)                                                                                                                                   |
| `SASE_COMMIT_METHOD_ALLOW_OVERRIDE` | Allow `-t/--type` to override a conflicting `SASE_COMMIT_METHOD`                                                                                                                        |
| `SASE_ARTIFACTS_DIR`                | Directory for `commit_result.json` and other artifacts                                                                                                                                  |
| `SASE_AGENT_NAME`                   | Agent name used for `SASE_AGENT=` runtime commit provenance                                                                                                                             |
| `SASE_MODEL_OVERRIDE`               | Active fallback model used for `SASE_MODEL=` provenance when present                                                                                                                    |
| `SASE_PLAN`                         | Plan source for storage/staging, status update, and the storage-relative `SASE_PLAN=` commit tag; ignored once the plan is done or archived, and not inherited by nested agent launches |
| `SASE_AGENT_PROJECT_FILE`           | Project file for Patch/STITCHES tracking                                                                                                                                                |
| `SASE_AGENT_CL_NAME`                | PR name used for proposal diff naming                                                                                                                                                   |
| `SASE_PR_NAME`                      | PR name (set by `#pr` macro input)                                                                                                                                                      |
| `SASE_PR_STATUS`                    | Initial PR Patch status (`draft`, `wip`, `ready`)                                                                                                                                       |
| `SASE_LINKED_REPO_<ENV_NAME>_DIR`   | Workspace-matched path for one configured linked repo                                                                                                                                   |

## Related

- [Version control](index.md) — the section hub.

## `sase stitch create`

Dispatches a commit, proposal, or PR via the VCS provider layer. See
[commit_workflows.md](index.md) for the full flow, payload, checkpoint, and resume
semantics.

<a id="cli-options-9"></a> Moved to [sase stitch](../cli/stitch.md).

## `sase stitch`

`sase stitch` defaults to `sase stitch list`, which shows a merged timeline for the
primary repo and configured linked repos. Add `-S/--sdd` to include sidecar repository
history. The legacy `sase vcs` spelling is still accepted as a deprecated alias.

<a id="cli-options-10"></a> Moved to [sase stitch](commit-workflows.md#sase-stitch).

<a id="command-behavior-5"></a> Moved to
[Commit workflows](commit-workflows.md#command-behavior-5).

## Command behavior {#command-behavior-5}

`sase stitch list` date filters accept relative offsets (`Nh`, `Nd`, `Nw`), `today`,
`yesterday`, `YYYY-MM-DD`, or `YYYY-MM-DDTHH:MM`. Day-granular `--until` / `--before`
values include the full named day; relative and minute-precise values remain instant
bounds. See [VCS Providers](providers.md#per-command-vcs-usage) for output examples and
provider notes. `--all` spans every registered enabled or disabled project and
deduplicates shared physical checkouts. Internal sibling backing checkouts remain
visible as linked repositories of their owning projects. Global scope can be combined
with repeatable `--repo` filters but not `--current-only`. Add `--sdd` to either scope
before selecting SDD history with `--repo sdd`; without the opt-in, that repo filter
does not expand the eligible set. `--all --sdd` includes materialized separate SDD
repositories across registered projects. The `--limit` is the cap on the final merged
timeline (default `40`; `0` means unlimited). `--origin` has no short form; repeat it to
OR `stitch`, `auto`, and `manual` origins.

## Review And Delivery

Flag and option details live in the generated [CLI command groups](../cli/index.md):

- [sase final](../cli/final.md), [sase stitch](../cli/stitch.md),
  [sase revert](../cli/revert.md), [sase restore](../cli/restore.md),
  [sase comments](../cli/comments.md)

Workflows: [Commit workflows](index.md), [VCS](index.md),
[Mentors](../automation/mentors.md).

Delivery commands delegate to the VCS and workspace provider layers, so the same command
surface can support plain git, GitHub pull requests, and other provider plugins.
