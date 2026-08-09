---
title: "[05] Commit Workflows — The Pluggable Path From Diff to PR"
date: 2026-05-18
draft: true
description: >-
  Every agent eventually has to land code somewhere. SASE's commit workflows are the
  small, runtime-uniform layer that turns a diff into a commit, a proposal, or a pull
  request without the agent caring which VCS is underneath.
categories:
  - Agentic Software Engineering
  - Workflows
slug: commit-workflows-plugins
links:
  - Commit Workflows: commit_workflows.md
  - Plugins: plugins.md
  - VCS Providers: vcs.md
  - "[04] Beads and SDD — Planning Multi-Agent Work That Actually Lands": blog/posts/beads-and-sdd.md
  - View on GitHub: https://github.com/sase-org/sase
---

# [05] Commit Workflows — The Pluggable Path From Diff to PR

Every agent eventually has to land code somewhere. SASE's commit XPrompt workflows are
the small, runtime-uniform layer that turns an agent's diff into a commit, a proposal,
or a pull request — without the agent caring which VCS is underneath.

<!-- more -->

[\[04\]](beads-and-sdd.md) covered how a plan turns into a fleet of phase agents that
produce code. This post covers what happens at the end: how each of those agents lands
its diff somewhere durable, and how that path is uniform across runtimes and VCS
providers.

## One CLI, Three Outcomes

The `sase commit` command drives three XPrompt workflows. They share the same
orchestrator, the same pre-stages, and the same result format; they differ only in what
the dispatch step produces.

| Workflow    | XPrompt    | Dispatch hook         | What it produces             | Tracking       |
| ----------- | ---------- | --------------------- | ---------------------------- | -------------- |
| **Commit**  | `#commit`  | `create_commit`       | Git commit on current branch | STITCHES entry |
| **Propose** | `#propose` | `create_proposal`     | Saved diff file              | STITCHES entry |
| **PR**      | `#pr`      | `create_pull_request` | New branch + PR              | Patch          |

Every flow walks the same pre-dispatch pipeline: bead association → bead lifecycle close
(skipped for proposals) → plan handling → `commit_hooks.before` → parent PR detection
(PR only) → diff capture → checkpoint. Only then does it call the VCS-specific
`create_commit` / `create_proposal` / `create_pull_request` hook. A successful commit or
PR dispatch emits best-effort file-hook events and runs `commit_hooks.after` before
tracking; proposals skip both because they do not create commits. When
`SASE_ARTIFACTS_DIR` is set, tracking writes an initial `commit_result.json` marker
before publication. A commit or proposal that resolves an existing Patch then appends a
STITCHES entry and rewrites the marker with its ID.

## The Commit-Finalizer Contract

Agents do not run `git commit` directly. They make changes; after a successful provider
invocation inside a SASE-launched agent session, the shared commit finalizer checks the
main workspace and configured Git linked repos for uncommitted state at their resolved
workspace directories. The
`sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>` command records
manually opened linked workspaces for ACE context, and `-p/--project` names the
configured linked repo's backing project record. If enforced work is dirty, the
finalizer sends bounded follow-up prompts to the same provider with a structured
instruction to invoke the matching commit skill (for example `/sase_git_commit` for
git-based projects, `/sase_hg_commit` for Mercurial). Dirty linked repo clones are
enforced like the main workspace. The generated skill normally runs a wrapper such as
`sase_git_commit`, which records skill invocation evidence and then delegates to
`sase commit`. A narrow SDD closeout, where the only enforced diff is one tracked SDD
markdown file whose leading front matter changes from `status: wip` to `status: done`,
is committed directly by the finalizer with a `SASE_TYPE=sdd` tag.

That finalizer is runtime-uniform because it lives in the LLM provider orchestration
layer, not in a provider-native hook. Claude, Codex, Antigravity (`agy`), Qwen,
OpenCode, Muse Code, and plugin providers all follow the same control flow: changes
exist → follow-up with skill name → skill wrapper delegates to `sase commit` → finalizer
re-checks the workspaces. No runtime-specific branching in the agent prompt, no "if
Codex then X" anywhere in the workflow.

If `SASE_BEAD_ID` is set, the finalizer first asks the agent to decide whether the
uncommitted changes were made in the current session. For changes the agent did make, it
instructs the agent to close and verify the bead before invoking the commit skill. That
keeps bead lifecycle state ahead of the commit dispatch while avoiding accidental
closure of unrelated dirty work.

## Runtime-Uniform Commit Skills

Supported agent runtimes follow the same commit-finalizer control flow: the finalizer
asks for the VCS-specific commit skill, the skill delegates to `sase commit`, and the
finalizer re-checks for dirty work. The common Git skill surface is available across
Claude, Codex, Antigravity (`agy`), Qwen, OpenCode, and Muse Code; provider-specific
extras can be scoped to the runtimes that support that provider.

## The VCS Provider Boundary

The three dispatch methods are pluggy hooks defined in `VCSHookSpec`:

| Plugin          | `create_commit`    | `create_proposal` | `create_pull_request`     |
| --------------- | ------------------ | ----------------- | ------------------------- |
| `BareGitPlugin` | Commit + push      | Save diff + clean | Branch + commit + push    |
| `GitHubPlugin`  | Inherits from git  | Inherits from git | + creates PR via `gh` CLI |
| `HgPlugin`      | `hg commit` + mail | `sase_hg_clean`   | Not supported natively    |

All hooks return `tuple[bool, str | None]` — a success flag and an optional result
string (commit hash, diff path, or PR URL). The orchestrator stays VCS-agnostic; new VCS
providers slot in by implementing the three hooks. Provider selection is also pluggable:
an env var (`SASE_VCS_PROVIDER`), then `sase.yml` `vcs_provider` config, then
auto-detection. Documented in [`vcs.md`](../../vcs.md).

## Resume After Conflict

When a VCS dispatch hits a merge conflict mid-flight, the workflow leaves a checkpoint
on disk (`$SASE_ARTIFACTS_DIR/commit_state.json`, or
`~/.sase/commit_state/<session>.json` if no artifacts dir is set) and exits with
`RunResult.CONFLICT` (exit code 2). The CLI prints:

> `create_commit` hit a merge conflict: … Resolve the conflict, then run
> `sase commit --resume` to finish.

`sase commit --resume` loads the checkpoint, re-checks the working tree for conflict
markers, verifies the commit at `HEAD` matches the subject line from the checkpointed
message, calls the provider's `vcs_finalize_commit` hook to replay idempotent
post-commit work (bead amend, push with retry), runs `commit_hooks.after`, re-runs the
tracking steps (STITCHES entry append, Patch creation), and deletes the checkpoint on
success. Completed steps are skipped, so resuming an after-hook failure does not
duplicate dispatch or a successful hook. After hooks should still be repeatable for the
crash window between command success and checkpoint persistence. Resume is VCS-agnostic:
the same `--resume` flag works for commits, proposals, and PRs.

This is the recovery path that makes multi-agent execution survivable. Without it, a
conflict on phase 3 of a seven-phase epic would mean wiping the workspace and
restarting; with it, the human resolves the conflict, runs `sase commit --resume`, and
the rest of the epic carries on through AXE's `%wait` resolution.

## What's in `commit_result.json`

When `SASE_ARTIFACTS_DIR` is set, post-dispatch tracking writes the durable hand-off
after the applicable after hook succeeds. A representative final commit marker is:

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

`repo_name` is omitted for the primary checkout and identifies linked, external, or SDD
sidecar repositories when present. `committed_at` is an integer Unix timestamp and is
omitted when the revision time cannot be resolved. Patch fields are populated only for
PR creation; the initial marker has no stitch ID, and commit/proposal tracking rewrites
it after a STITCHES append succeeds.

The marker also dual-writes the legacy Patch aliases `changespec_name` and
`commit_changespec_name`, the stitch aliases `entry_id` and `commit_entry_id`, plus
`commit_result` and `commit_diff_path`. Built-in XPrompt post-steps still expose the
Patch as `meta_changespec`; completed agent-run projection adds canonical `meta_patch`
and retains `meta_changespec` for compatibility.

## The Public Plugin API

Two entry-point groups are the public extension surface:

- **`sase_vcs`** — provider classes that implement `create_commit`, `create_proposal`,
  `create_pull_request`, plus resume and classification hooks. `sase-github` is the
  canonical out-of-tree implementation.
- **`sase_xprompts`** — packages whose `xprompts/` directories contribute reusable
  XPrompts and workflows, including overrides for the built-in commit XPrompts.

Plugin resource loading can be disabled via environment variables for debugging:

| Variable                       | Effect                                                    |
| ------------------------------ | --------------------------------------------------------- |
| `SASE_DISABLE_PLUGINS`         | Disable resource plugin loading for config and xprompts   |
| `SASE_DISABLE_PLUGIN_XPROMPTS` | Disable xprompt/workflow resource plugins only            |
| `SASE_DISABLE_PLUGIN_CONFIG`   | Disable plugin `default_config.yml` resource loading only |

The VCS, workspace, and LLM provider registries load entry points directly and do not
consult these disable switches; those are about which configuration and prompt files
contribute to the resolver, not which providers exist.

## What To Read Next

- [Commit workflows](../../commit_workflows.md) — full pipeline, CLI flag table, result
  schema, resume protocol, environment variables, design principles.
- [Plugins](../../plugins.md) — entry-point groups, discovery, writing new VCS /
  workspace / LLM / xprompt / config plugins.
- [VCS providers](../../vcs.md) — provider selection tiers, per-command VCS usage,
  provider-specific details.
- [\[06\] Patches in Practice — Review State Outside the Chat](changespecs-in-practice.md)
  — what the commit/PR flow writes to, and how ACE reviews it.
