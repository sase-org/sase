# `sase bead work` latency - consolidated research 2026-06-23

## Scope

This consolidates the two independent notes created for the question:

- `sdd/research/202606/bead_work_command_latency.md`
- `sdd/research/202606/sase_bead_work_latency.md`

I rechecked the claims against current source, the local launch timing log, a fresh safe dry run, and the effective SASE
config. No live `sase bead work --yes` launch was started during consolidation.

The key correction is that there are two different slow paths:

1. For a real launch, the parent process does serial setup before returning. The strongest measured in-spawn cost is
   synchronous linked-repo materialization for eager agents, and the default post-launch `git push` can add network
   latency after spawning.
2. For `--dry-run`, no agents launch and no bead state is committed, but startup, xprompt/project lookup, and live-name
   collision checks over the local artifact history can still make the command non-instant. One-off slow dry runs need
   better durable timing; they should not be confused with normal agent-launch cost.

## Data read

| Source | Evidence |
| --- | --- |
| `src/sase/bead/cli_work_handler.py` | `handle_bead_work` stages; dry-run returns before mutation/launch/commit |
| `src/sase/agent/multi_prompt_launcher.py` | multi-prompt segments are processed in a serial `for` loop |
| `src/sase/agent/launch_executor.py` | fanout slots are spawned serially |
| `src/sase/agent/launch_spawn.py` | low-level spawn timing; linked repos skipped only for deferred `%w` agents |
| `src/sase/linked_repos.py`, `src/sase/workspace_provider/utils.py` | `materialize=True` resolves linked repos through `ensure_workspace_checkout`, which runs local `git clone` for cold workspaces |
| `src/sase/bead/cli_work_commit.py`, `src/sase/bead/sync.py` | successful launches commit bead state and default to synchronous `git push` |
| `~/.sase/logs/tui_launch_timing.jsonl` | 594 timing rows, including 458 `agent_launch_spawn` records |
| effective `linked_repos` config | `chezmoi`, `sase-core`, `sase-github`, `sase-telegram`, `sase-nvim` |
| `~/.sase/projects` artifact history | about 18.5k `agent_meta.json` files |
| fresh `sase bead work sase-55 --dry-run` | one run at 12.84s wall / 2.02s CPU, immediate rerun at 2.17s wall / 1.77s CPU |

## What the command does

`sase bead work` is not a simple bead update. For an epic, the parent process:

1. opens the bead project and reads the plan bead;
2. resolves the work-phase and land-agent xprompts;
3. builds the epic work DAG and renders a multi-prompt;
4. on dry run, checks live deterministic-name collisions and prints the prompt;
5. on live launch, force-reuses deterministic names, marks/preclaims bead state, launches all prompt segments, commits the
   bead-state mutation, and usually runs `git push`.

The dry-run branch returns before force-reuse cleanup, mark-ready, preclaim, agent launch, commit, and push. That makes
dry-run latency useful for diagnosing startup/collision-scan problems, but it does not measure launch/push latency.

## Findings

### 1. Low-level spawn cost is dominated by linked-repo materialization

`spawn_agent_subprocess` records durable `agent_launch_spawn` timings. Recomputing the current log gives:

| Population | Count | total p50 | total p90 | total p95 | total p99 | total max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all spawns | 458 | 157 ms | 1353 ms | 2097 ms | 3461 ms | 4119 ms |
| eager spawns | 383 | 202 ms | 1560 ms | 2331 ms | 3496 ms | 4119 ms |
| deferred spawns | 75 | 52 ms | 178 ms | 193 ms | 297 ms | 531 ms |

Within those same records:

| Stage | Median | p90 | Max | > 1000 ms |
| --- | ---: | ---: | ---: | ---: |
| `linked_repo_resolution` | 112 ms | 1289 ms | 4004 ms | 72 |
| `subprocess_spawn` | 29 ms | 103 ms | 394 ms | 0 |
| `workspace_claim` | 2 ms | 49 ms | 346 ms | 0 |
| `chop_registry_record` | 1 ms | 4 ms | 181 ms | 0 |

The code explains the split. If a segment has a deferred start directive (`%w` / wait), `spawn_agent_subprocess` uses an
empty linked-repo resolution. Otherwise it calls `resolve_linked_repos_for_project(... materialize=True)`. That resolves
each configured linked repo through `ensure_workspace_checkout`, which performs a full local `git clone` when the target
workspace checkout is missing or corrupt. On this machine that means up to five linked repos for an eager SASE launch.

So the strongest measured parent-side cost inside low-level spawn is not the detached child runtime; it is pre-fork repo
materialization for eager agents.

### 2. Eager cost scales with wave-0 width, not total epic size

Epic prompts are rendered as dependency waves. Wave-0 phases have no in-epic blockers, so they do not carry `%w` and are
eager. Later phases and the land agent carry `%w` and are deferred.

For the observed `sase-55` epic, the plan had six phase agents in four waves plus one land agent:

```text
Wave 0: sase-55.1
Wave 1: sase-55.2, sase-55.5
Wave 2: sase-55.3
Wave 3: sase-55.4, sase-55.6
Land: sase-55
```

Only `sase-55.1` was eager. The durable low-level spawn rows around the real launch show:

| Agent PID | Deferred | Workspace | Total | Linked repos | Claim | Spawn |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 628052 | no | 13 | 1189 ms | 1160 ms | 2 ms | 26 ms |
| 628061 | yes | 0 | 52 ms | 0 ms | 29 ms | 51 ms |
| 628207 | yes | 0 | 103 ms | 0 ms | 42 ms | 68 ms |
| 628627 | yes | 0 | 193 ms | 0 ms | 166 ms | 192 ms |
| 629304 | yes | 0 | 28 ms | 0 ms | 2 ms | 28 ms |
| 629521 | yes | 0 | 69 ms | 0 ms | 43 ms | 68 ms |
| 629767 | yes | 0 | 34 ms | 0 ms | 2 ms | 33 ms |

This resolves one conflict between the two drafts: linked-repo materialization is the top measured low-level spawn cost,
but it does not hit every agent in a waved epic. A wide epic with many independent wave-0 phases will pay more of this
cost in the parent than a mostly sequential epic.

### 3. The launch loop is serial, and some parent-loop time is still under-instrumented

`launch_multi_prompt_agents` iterates segments one at a time, and `execute_launch_plan` also loops over slots one at a
time. There is no parent-side overlap of per-segment setup or process spawning.

For `sase-55`, the seven low-level spawn summaries themselves add up to about 1.67s, but their summary timestamps span
about 37s. The gaps between rows were roughly 1.8s, 6.6s, 9.9s, 7.4s, 5.3s, and 6.5s. Those gaps are outside the durable
`agent_launch_spawn` records. They are probably in per-segment parent work before low-level spawn timing starts, such as
prompt normalization, VCS/project resolution, name planning, registry/artifact operations, or lock contention.

That means the current log proves linked-repo resolution is the largest measured in-spawn stage, but it does not fully
explain every observed launch delay. Durable timing should be added around the multi-prompt parent loop before ranking
the remaining gap with confidence.

### 4. Successful live launches default to a blocking `git push`

After agents are launched, `commit_successful_work_launch` commits bead-state files and resolves push mode from
`bead.push_after_commit`. The default is `true`, which runs synchronous `git push` before the command returns.

This is a separate tail-latency source from launch. It can block on network, remote-side work, or credentials. Existing
mitigations:

- pass `--no-push` / `-P` for one launch;
- set `bead.push_after_commit: false` to disable automatic push;
- set `bead.push_after_commit: async` to keep automatic push but detach it from the command's critical path.

The inspected `sase-55` timing rows do not prove push was slow in that run; they do prove push is on the default critical
path for live launches.

### 5. Dry-run latency is a different problem

Dry run does not launch, commit, or push, yet it can still take noticeable wall time. The relevant costs are:

- Python/import and command startup;
- `project_open` and xprompt lookup;
- Rust-backed work-plan build;
- live deterministic-name collision checks before printing force-reuse warnings.

The collision check uses `get_live_agent_name_subset(expected_names)`, which is better than building a full live-name
map, but it still walks ACE artifact directories until every expected name is found. With about 18.5k local
`agent_meta.json` files, a direct lookup of the seven expected `sase-55` names took 1.44s.

The slow dry-run measurements are not stable:

| Run | Wall | CPU | Notes |
| --- | ---: | ---: | --- |
| prior draft run | 36.46s | 2.16s | no durable stage breakdown |
| consolidation run | 12.84s | 2.02s | same live collision warnings |
| immediate consolidation rerun | 2.17s | 1.77s | same command, warm path |

Because the slow runs spend little CPU and dry-run has no launch/commit/push work, they look like transient filesystem
cache effects, artifact/index contention, or lock waits in a stage that is not durably captured. They are real user
experience, but they should be investigated separately from live-launch spawn cost.

### 6. Agents can still feel slow after the command returns

Detached child runtime is not on the parent command's critical path, but deferred agents still have to materialize their
workspaces and linked repos after their `%w` dependencies clear. For a multi-wave epic, time-to-useful-work includes
those child-side clones spread across dependency waves. Optimizing clone/materialization helps both parent return time
for eager agents and child startup time for deferred agents.

## What previous work already improved

The current code already avoids several older bottlenecks:

- epic work-plan construction is Rust-backed;
- phase preclaim is batched instead of one update per phase;
- deterministic name validation has a planned fast path;
- `launch_planned_bead_work_agents` avoids some generic multi-prompt rediscovery;
- `--no-push` and async push exist because push was already identified as user-visible latency.

Those fixes narrow the remaining problem to serial launch orchestration, cold repo materialization, live/collision scans,
lock/contention effects, and default sync push.

## Practical mitigations now

- Use `sase bead work <id> --yes --no-push` when the launch record does not need to be pushed immediately.
- Set `bead.push_after_commit: async` if automatic push is desired but shell return time matters.
- Treat slow `--dry-run` as evidence of startup/artifact-scan/contention latency, not agent launch latency.
- Expect wide wave-0 epics to return slower than mostly sequential epics because each eager phase can materialize
  workspaces and linked repos in the parent.

## Best follow-up measurements

For a safe live reproduction, run with push disabled first:

```bash
SASE_BEAD_WORK_TIMING=1 \
SASE_AGENT_LAUNCH_TIMING=1 \
sase bead work <epic-id> --yes --no-push
```

The missing piece is durable parent-loop timing around:

- per-segment prompt normalization and wait/resume rewrite;
- per-segment VCS/project resolution;
- per-segment name planning and reservation;
- `execute_launch_plan`;
- post-launch commit and push.

`agent_launch_spawn` already captures the low-level spawn stages well. The unresolved 37s `sase-55` span is outside
those rows, so adding durable timing above that layer is the next highest-value diagnostic change.

## Follow-up design opportunities

1. Defer or parallelize linked-repo materialization for eager agents.
2. Replace full local clones with `git worktree`, `clone --shared`, or `--reference` where safe.
3. Overlap independent parent-side spawns instead of serializing every segment.
4. Make async push the default, or surface `--no-push` more prominently.
5. Index live artifact names so deterministic force-reuse checks do not walk large historical artifact trees.
6. Move bead-work timing summaries to durable JSONL so one-off slow dry runs and launches can be decomposed after the
   fact.
