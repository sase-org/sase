---
create_time: 2026-06-25
updated_time: 2026-06-25
status: research
---

# Epic `sase bead work` PR Migration

## Question

`sase bead work <epic>` currently launches one agent per phase bead plus a final land agent. For normal epics, recent
runs show each phase agent committing directly to `master`. The target state is one reviewable PR per epic, containing
one commit per phase bead and one final commit from the land agent.

This note consolidates two prior research passes, verifies their key claims against code and recent runs, and ends with
a recommended migration path.

## Sources Verified

- Prior research chats:
  - `~/.sase/chats/202606/sase-ace_run-260625_184007.md`
  - `~/.sase/chats/202606/sase-ace_run-260625_184020.md`
- Prior intermediate notes:
  - `sdd/research/202606/epic_bead_work_pr_migration.md`
  - `sdd/research/202606/one_pr_per_epic_bead_work.md`
- Current implementation:
  - `src/sase/bead/cli_work_handler.py`
  - `src/sase/bead/work.py`
  - `src/sase/bead/cli_work_context.py`
  - `src/sase/bead/cli_work_commit.py`
  - `src/sase/bead/sync.py`
  - `src/sase/vcs_provider/plugins/_git_commit_dispatch.py`
  - `src/sase/xprompts/commit.yml`
  - `src/sase/xprompts/pr.yml`
  - `src/sase/default_config.yml`
  - `sase-github/src/sase_github/xprompts/gh.yml`
  - `sase-github/src/sase_github/workspace_plugin.py`
- Existing docs and tests:
  - `docs/beads.md`
  - `docs/commit_workflows.md`
  - `tests/test_bead/test_work_rendering.py`
  - `tests/test_bead/test_cli_work_epic_launch.py`
- Prior design docs:
  - `sdd/epics/202604/epic_changespec_beads.md`
  - `sdd/tales/202605/epic_phase_vcs_prompts.md`
  - `sdd/epics/202602/git_change_specs_v3.md`
- Recent evidence:
  - `git log` for `sase-54`, `sase-55`, and `sase-56`
  - `sase chat list/show` for `sase-56`, `sase-55`, and `sase-54`
  - `sase bead search 'sase-56' --format json`
  - `sase changespec search 'sase-56' -f markdown`

## How Epic Work Runs Today

The epic path starts in `_handle_epic_bead_work()` in `src/sase/bead/cli_work_handler.py`.

1. It resolves the built-in or overridden `bd/work_phase_bead` and `bd/land_epic` xprompts.
2. It builds an `EpicWorkPlan` from the open phase beads under the epic. The plan is a Kahn-style wave schedule: phase
   dependencies become `%w:<agent>` waits, and the land agent waits on every launched phase.
3. It chooses launch context:
   - if the epic bead has `changespec_name`, it resolves a `ChangeSpecLaunchContext`;
   - otherwise it resolves a plain `VCSLaunchContext` for the current project.
4. It renders one `---`-separated multi-prompt segment per phase plus one land segment.
5. On live runs, it force-reuses deterministic agent names, marks the epic ready, preclaims all phase beads
   `in_progress` with `assignee=<phase-agent-name>`, launches the agents, then commits the launch-state bead mutation.

The launch-state commit is separate from the agent commits. `commit_successful_work_launch()` calls
`commit_bead_work_launch()`, which stages only bead-state files and commits:

```text
chore: mark bead work launched for <epic>
```

By default `bead.push_after_commit: true`, so this bookkeeping commit is pushed to the current branch, normally
`master`. It does not include phase implementation changes.

## Why Phase Agents Commit To `master`

The important decision is in `render_multi_prompt()` in `src/sase/bead/work.py`.

For a normal epic, every segment is prefixed with the project VCS ref:

```text
#gh:sase
%name:!sase-56.1
%group:sase-56
%model:worker
%auto
#bd/work_phase_bead:sase-56.1
```

The land segment is also `#gh:sase`. In the GitHub workflow, `#gh:sase` resolves as a project ref and checks out the
default branch, falling back through `master` / `main`.

The phase and land xprompts themselves do not say anything about commits, branches, or PRs. They tell the phase agent
to complete and close its own bead, and the land agent to verify the work, close the epic, update the plan frontmatter,
and run validation.

Commit behavior is injected by xprompt wrappers and the post-completion finalizer:

- `#commit` sets `SASE_COMMIT_METHOD=create_commit`.
- `#pr` sets `SASE_COMMIT_METHOD=create_pull_request`, `SASE_PR_NAME`, `SASE_PR_STATUS`, and `SASE_BUG_ID`.
- If no PR method is set, the commit path defaults to `create_commit`.
- `create_commit` stages the requested files plus bead state, commits on the current branch, and pushes that current
  branch.
- `create_pull_request` creates a branch, commits, pushes the branch, creates a PR in the GitHub plugin, and writes a
  ChangeSpec record.

So normal epic phase agents land on `master` because their segments are `#gh:sase` and do not carry `#pr`. The finalizer
then commits on the checked-out `master` branch.

## Existing ChangeSpec Path

The desired PR shape is partially implemented already, gated behind epic bead metadata.

When the epic has `changespec_name`, `render_multi_prompt()` emits:

```text
#gh:sase #pr:<changespec_name>     # first phase
---
#gh:<changespec_name>              # later phases
---
#gh:<changespec_name>              # land agent
```

Tests pin this behavior, including the case where independent phases still produce exactly one `#pr` reference. The
original design in `sdd/epics/202604/epic_changespec_beads.md` explicitly called for this shape: first phase creates or
owns the ChangeSpec branch/PR; later phases and land run against the ChangeSpec ref.

This means the migration should not create a second PR concept. `changespec_name` / `changespec_bug_id` should remain
the durable epic PR identity.

However, this path is not safe enough to turn on unchanged:

- It is opt-in. `sase bead create -c/--changespec` can attach metadata, and `bd/new_epic` passes it only when asked.
  `sase bead update` does not currently expose a `--changespec` option, although `BeadProject.update()` can mutate the
  fields internally.
- It races when an epic has multiple independent root phases. Only the first phase gets `#pr`; other root phases have no
  `%w` dependency and can start before the first phase has created the branch, PR, and ChangeSpec record.
- Later `#gh:<changespec_name>` segments resolve through an existing ChangeSpec record. If that record does not exist
  yet, the GitHub resolver cannot resolve the ref.
- Even after the branch exists, multiple agents pushing to one PR branch concurrently will create branch-stack
  contention. The target history is one clean commit per phase plus one land commit, so v1 should not rely on
  concurrent pushes to the same branch.
- The current launch-state commit still pushes bead bookkeeping to `master`, which violates the desired final shape even
  if phase commits move to a PR branch.

## Recent Runs

Recent history matches the implementation.

For `sase-56` on June 23, 2026:

| Commit | Subject |
| --- | --- |
| `4c2f1d630` | `chore: mark bead work launched for sase-56` |
| `4b224219c` | `feat(directives)!: add %tale directive and repurpose %plan for plan auto-approval (sase-56.1)` |
| `b44dda18d` | `feat(ace): add Auto-Approve menu modal and rewire approve keymap (sase-56.2)` |
| `52cbe00d5` | `feat(ace): polish auto-approve presentation in agent list, footer, and help (sase-56.3)` |
| `f3144e633` | `chore: Add SDD prompt and plan for sase_56_completion (sase-56)` |
| `d605ae511` | `docs(ace): update auto-approve docs for the Auto-Approve menu (sase-56)` |

`sase chat list -j -q 'sase-56'` shows the actual phase prompts were `#gh:sase %name:sase-56.1`,
`#gh:sase %name:sase-56.2 %w:sase-56.1`, and `#gh:sase %name:sase-56.3 %w:sase-56.1,sase-56.2`. The land prompt was
also `#gh:sase`. No prompt snippet contained `#pr`. `sase changespec search 'sase-56' -f markdown` returned no matches.

`sase-55` and `sase-54` show the same pattern:

- a `chore: mark bead work launched for <epic>` commit;
- one direct phase commit per phase bead on `master`;
- a final land or follow-up closeout commit on `master`.

The `sase-56.1` transcript also shows the operational pain directly. Its first commit attempt failed because
`origin/master` advanced; the agent had to stash, fast-forward, pop, and re-run the commit. That race is expected when
independent agents push directly to the shared default branch, but it is exactly what the migration should remove from
`master`.

`sase bead search 'sase-56' --format json` confirms that the epic and phases ended closed, and that their stored
`changespec_name` fields are empty. The `COMMIT:` notes on those beads point at hashes that no longer exactly match the
visible log after later history rewriting, so land verification should continue to search by bead ID in commit messages
and ChangeSpec metadata rather than trusting bead note hashes alone.

## Design Constraints

The migration has to preserve several useful properties from the current flow:

- deterministic agent names (`<epic>.<N>` and `<epic>`) and retry behavior;
- phase-level bead IDs in commit messages;
- phase agents close only their own phase bead;
- land agent verifies phase outputs and creates the final closeout commit;
- xprompt tag override behavior for `bd/work_phase_bead` and `bd/land_epic`;
- runtime neutrality across Codex, Claude, Gemini, and other agents;
- VCS plugin neutrality where possible, with GitHub adding the external PR.

It also has to change several current assumptions:

- `master` should not receive a launch-state bookkeeping commit for PR-backed epic work.
- Phase bead closures should live on the epic PR branch until the PR merges.
- `sase bead list` on `master` will not see closed phase state until merge; this is normal PR behavior, but it is a
  user-visible change.
- In v1, phase commits on the epic PR branch should be serialized. Parallel phase execution can be reintroduced later
  with a coordinator that captures isolated phase results and applies them sequentially to the PR branch.

Multi-repo epics are the biggest unresolved edge. Recent phase work can touch both `sase` and linked repos such as
`sase-core`. In practice, "one PR per epic" likely means one PR per affected repo, sharing a ChangeSpec name. The
ChangeSpec model can track per-repo commits, but this needs an explicit end-to-end test before being treated as solved.

## Options

### Option A: Document the current opt-in ChangeSpec path

This is too small. It leaves normal epics direct-to-master and does not address launch-state commits or wave-0 races.

### Option B: Pre-create the PR branch and render every segment against it

This is robust for branch resolution, but the straightforward implementation adds a seed commit such as
`chore: open epic PR for <epic>` to create a PR before any phase runs. That restores a clean review gate, but it no
longer satisfies the strict target of exactly one commit per phase plus one land commit.

This can be a good later version if a seed commit is acceptable, or if provider support is added for creating a
reviewable PR/ChangeSpec identity without an extra commit. It is not the best first migration if the N+1 commit shape is
part of the requirement.

### Option C: Existing first-`#pr` path plus deterministic serialization

This reuses the implemented ChangeSpec funnel and preserves the exact commit count:

- the first phase segment runs as `#gh:sase #pr:<epic-pr-name>`;
- every later phase and the land agent runs as `#gh:<epic-pr-name>`;
- every non-first phase waits on the preceding phase in deterministic topological order;
- the land agent waits on the final phase.

The cost is less parallelism. The benefit is a clean PR branch stack without inventing new VCS plumbing.

### Option D: Coordinator applies isolated phase results

This is the long-term parallel version. Phase agents work in isolated branches or proposals, then a coordinator applies
one commit per phase to the epic PR branch in deterministic order. It preserves parallel work and clean history, but it
is much larger: patch capture, conflict handling, validation, retry semantics, and commit attribution all become new
system behavior.

## Recommended Solution

Implement Option C first: make PR-backed epic work the default behind a config flag, reuse the existing ChangeSpec path,
serialize commits, and suppress the parent launch-state commit on `master`.

Concrete steps:

1. Add a staged rollout config, for example `bead.epic_pr: false | true`, defaulting to `false` for the first merge and
   flipping after one or two real epic runs. Keep a per-command escape hatch such as `--direct` or
   `--epic-work-mode=direct`.
2. In `_handle_epic_bead_work()`, when the flag is enabled and the epic has no `changespec_name`, synthesize a stable
   ChangeSpec/branch name from the epic ID plus plan slug or title. Prefer a name that should not need suffixing, such
   as `sase_56_auto_approve_menu`, so retries can rederive it.
3. Build a `ChangeSpecLaunchContext` from either the stored metadata or the synthesized name. Do not fall through to
   the plain project `VCSLaunchContext` for PR-mode epics.
4. In PR mode, render a deterministic commit-order chain across all non-closed phase assignments. The first phase keeps
   `#pr:<name>` and no synthetic wait; every later phase waits on the immediately previous phase agent, in topological
   order, in addition to any semantic bead dependencies. The land agent waits on the last phase. This eliminates the
   wave-0 branch/ChangeSpec race and avoids concurrent pushes to the same PR branch.
5. Do not push the parent launch-state commit to `master` in PR mode. Either skip preclaim persistence entirely for
   PR-backed epics, or apply preclaim/ready state in a temporary local overlay and roll it back after launch. Durable
   bead closures should be produced by the phase and land commits on the PR branch.
6. Keep each phase agent's responsibility unchanged: complete exactly its phase, close that phase bead, and let the
   finalizer create one commit with the phase bead ID in the message.
7. Extend `bd/land_epic` for PR-backed work so the land agent verifies the ChangeSpec/PR branch, closes the epic bead,
   marks the epic plan `status: done`, runs validation, and marks the ChangeSpec/PR `Ready`. Do not auto-merge by
   default; the point of the migration is to restore a review gate. Add a later opt-in such as
   `bead.epic_pr.auto_merge`.
8. Add tests for:
   - default PR-mode rendering;
   - legacy direct-mode rendering;
   - generated ChangeSpec name reuse;
   - independent root phases proving later roots wait on the first PR-creating phase;
   - no `commit_successful_work_launch()` / no master launch-state commit in PR mode;
   - land prompt PR finalization behavior;
   - one multi-repo fixture or integration test before claiming multi-repo support.

This satisfies the requested shape with the smallest reliable change: one PR per epic, one commit per phase bead, one
land-agent commit, and no phase-agent commits directly to `master`.

After that works, revisit Option B or D. Option B can improve branch/PR observability before the first phase completes
if a seed commit is acceptable. Option D is the right long-term route if parallel phase execution is important enough to
justify a coordinator.

