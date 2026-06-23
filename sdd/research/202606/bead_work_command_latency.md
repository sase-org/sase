# Why `sase bead work` Is Slow — Latency Research (2026-06-23)

## Scope

This note answers "why does `sase bead work` take so long to complete?" by tracing the command's parent-side critical
path end to end and measuring it. It mines the built-in launch timing instrumentation (`SASE_BEAD_WORK_TIMING`,
`~/.sase/logs/tui_launch_timing.jsonl`), reads the source path, and runs fresh `--dry-run` and micro-benchmarks. No real
multi-agent launch was started for this study (that has side effects); the launch-side numbers come from **458 real
spawn records** already on disk plus targeted micro-benchmarks.

"Slow" has two distinct meanings, and they have different causes:

1. **Command wall time** — how long until `sase bead work` returns control to the shell. This is what most of this note
   is about.
2. **Time-to-useful-work** — how long until the launched agents actually start producing changes. The heavy part of
   this (per-agent repo materialization) runs in detached children, off the command's critical path, but it is the
   reason the *epic* feels slow even after the command returns. Covered in §6.

## Data Read

| Source | Evidence |
| --- | --- |
| `~/.sase/logs/tui_launch_timing.jsonl` | 594 records; **458 `agent_launch_spawn`** summaries from real launches |
| `SASE_BEAD_WORK_TIMING=1` dry-run on epic `sase-55` | Read-side stage breakdown (6 phases / 4 waves / 1 land) |
| `sase bead work sase-55 --dry-run` × 3 | End-to-end read-side wall time ~1.6 s |
| `git clone .` micro-bench | Cold full clone of this repo ~1.44 s (7,390 tracked files) |
| `src/sase/bead/cli_work_handler.py` and the launch path | The 12 instrumented stages + per-agent spawn path |
| `git log` (`4be6f7352`, `be748b627`) | Prior `sase bead work` perf work and its limits |

## The command's critical path

`handle_bead_work` (`src/sase/bead/cli_work_handler.py:58`) wraps the whole command in a `LaunchTimingRecorder` with
twelve stages. For an **epic** the ordered stages are:

```
project_open → initial_show → xprompt_lookup → work_plan_build → vcs_context →
prompt_render → [confirm] → force_reuse_cleanup → mark_ready → preclaim →
agent_launch → commit → push
```

`agent_launch` is the expensive one: it runs `launch_multi_prompt_agents`, which **iterates the rendered segments one at
a time in a plain `for` loop** (`src/sase/agent/multi_prompt_launcher.py:244`) and, for each segment,
`execute_launch_plan` spawns serially (`src/sase/agent/launch_executor.py:92`). There is no parallelism across agents in
the parent.

### How the work splits between parent and detached children

Each segment becomes a **detached** subprocess (`spawn_agent_subprocess`, `src/sase/agent/launch_spawn.py:97`), so the
agent's actual LLM runtime never blocks the command. But not all setup is detached. The split is governed by whether a
segment carries a `%w` (wait) directive:

- **Wave-0 phase agents** (no in-epic blockers, **no `%w`**) take the *eager* path. The parent synchronously
  materializes their workspace **and** their linked repos before spawning.
- **Later-wave phase agents and the land agent** (have `%w:...`) are *deferred*
  (`has_deferred_start_directive`, `src/sase/xprompt/directives.py:125`). The parent claims a placeholder
  (`workspace_num=0`), skips linked-repo resolution, and spawns cheaply. Their repo clone happens **child-side** when the
  wait resolves.

Verified on epic `sase-55` (6 phases, 4 waves, 1 land = 7 agents). The rendered multi-prompt has exactly **one** segment
with no `%w` (`sase-55.1`); the other six all carry `%w`:

```
%name:!sase-55.1            #bd/work_phase_bead:sase-55.1     ← eager (wave 0)
%name:!sase-55.2  %w:sase-55.1                                ← deferred
%name:!sase-55.5  %w:sase-55.1                                ← deferred
%name:!sase-55.3  %w:sase-55.1,sase-55.2                      ← deferred
%name:!sase-55.4  %w:sase-55.1,sase-55.2,sase-55.3            ← deferred
%name:!sase-55.6  %w:sase-55.2,sase-55.3                      ← deferred
%name:!sase-55    %w:...all six...   #bd/land_epic:sase-55    ← deferred (land)
```

**Consequence:** the parent's eager-clone cost scales with the **width of wave 0** (count of phases with no in-epic
dependency), *not* with the total agent count. A sequential/diamond epic like `sase-55` pays one eager clone; a wide
fan-out epic with many independent phases pays one per wave-0 phase, serially.

## Findings (ranked by contribution to command wall time)

### 1. Per-agent `linked_repo_resolution` is the dominant per-spawn cost — and it is a synchronous `git clone`

Aggregating the 458 real `agent_launch_spawn` records, the per-spawn stage costs are:

| stage | median | max |
| --- | ---: | ---: |
| **`linked_repo_resolution`** | **111.7 ms** | **4,003.8 ms** |
| `subprocess_spawn` | 28.5 ms | 394.4 ms |
| `workspace_claim` | 1.6 ms | 346.2 ms |
| `chop_registry_record` | 0.7 ms | 180.8 ms |
| `launch_prepare` | 0.4 ms | 168.5 ms |
| `env_shape` / `output_path_derive` / `runner_script_resolution` | <0.3 ms | <16 ms |

`linked_repo_resolution` (`src/sase/agent/launch_spawn.py:173`) calls
`resolve_linked_repos_for_project(... materialize=True)`. For each configured linked repo,
`_resolve_workspace_dir` with `materialize=True` calls `ensure_workspace_checkout` →
`_ensure_git_clone_at`, which does a **full `git clone`** of that repo into the agent's workspace number when the target
is cold (`src/sase/workspace_provider/utils.py:242`). This project's launch context lists four linked repos
(`sase-core`, `sase-github`, `sase-telegram`, `sase-nvim`) plus a global `chezmoi` entry — so an eager spawn can
synchronously clone up to **five** extra repos before the agent process even forks.

This is why the stage is so heavy and so spiky:

- **median 111.7 ms**, but
- **25% of spawns exceed 500 ms**, and
- **72 of 458 (16%) exceed 1,000 ms**; the worst single resolution was **4.0 s**.

It only runs for *eager* (non-deferred) agents — it is explicitly skipped when `deferred_workspace` is true — which is
consistent with it being the wave-0 materialization cost.

### 2. The spawn loop is serial, so tail latencies compound

Whole-spawn `total_ms` across the 458 records: **p50=158 ms, p90=1,354 ms, p95=2,215 ms, p99=3,495 ms**. Because
segments are launched one after another with no overlap, a 7-agent epic pays the *sum* of seven draws from this
distribution. Hitting the p90 even once or twice (likely with 7 draws) adds multiple seconds. Deferred agents are
cheaper per spawn (no linked-repo clone) but still serial.

### 3. Eager workspace materialization is a full clone of the main repo (~1.4 s cold)

Separately from linked repos, the wave-0 agent's own workspace is materialized in the parent by
`_preclaim_axe_workspace` → `get_workspace_directory_for_num` (`src/sase/agent/launch_executor_workspace.py:149`), which
calls `clean_workspace` (a `git clean`/reset subprocess) and `ensure_workspace_checkout` (the same full-clone path as
linked repos). Micro-bench: a cold `git clone` of this repo is **~1.44 s** (7,390 files). Once a `sase_<N>` directory
exists and `git status` succeeds, the clone is skipped and the cost drops to a `git status` + clean + `git fetch` (the
fetch was ~0.01 s locally). So this is mainly a **cold / first-use-of-a-workspace-number** cost.

### 4. Default config pushes to the remote synchronously on the critical path

`commit_successful_work_launch` ends the command with a local bead-state commit (5 sequential `git` subprocess calls:
`rev-parse`, `ls-files`, `add`, `diff --cached`, `commit`) followed by a push. The push mode default is
`push_after_commit: true` (`src/sase/default_config.yml:346`), i.e. **synchronous** — the command blocks on a network
round-trip to the GitHub remote before returning. On a slow or contended network this is seconds of tail latency that
has nothing to do with launching agents. Mitigations exist but are off by default: `-P/--no-push`, or
`bead.push_after_commit: async` (detached background push).

### 5. Python import + read-side startup is a fixed ~1.5–1.6 s floor

End-to-end `sase bead work <epic> --dry-run` (which stops before `agent_launch`/`commit`) is **~1.6 s** warm. The
in-process `SASE_BEAD_WORK_TIMING` breakdown for that path:

| stage | ms |
| --- | ---: |
| `xprompt_lookup` | 463 |
| `project_open` | 350 |
| `initial_show` | 20 |
| `work_plan_build` | 13 |
| `vcs_context` | 5 |
| `prompt_render` | 0.03 |
| **named stages subtotal** | **~851** |
| **recorder total** | **~2,500 (cold) / ~1,600 (warm CLI)** |

The large gap between the named stages and the total is **lazy imports** charged inside the handler — the
`from sase.bead.work import …` / `from sase.bead.xprompts import …` blocks (`cli_work_handler.py:111` and `:267`) run
*before* their corresponding `timer.stage(...)` and pull in the launcher, workspace-provider, and vcs-provider trees.
`xprompt_lookup` (463 ms) is itself import-and-registry-scan heavy. For comparison, bare `sase bead --help` startup is
~0.22 s, so the bead-work path adds well over a second of import/registry work on top of interpreter start.

### What is *not* on the command's critical path

- The agents' actual runtime (LLM work) — fully detached.
- Repo materialization for **deferred** (waved) agents — deferred to the child when the wait resolves.

## What prior work already addressed (and what it didn't)

Commit `4be6f7352` ("perf(bead): speed up `sase bead work` launch path") added: the planned fast-path adapter
(`launch_planned_bead_work_agents`) that skips generic fan-out re-discovery and CWD re-parse; one-load name validation;
`-P/--no-push` and async-push config; and the `SASE_BEAD_WORK_TIMING` instrumentation used above. That work targeted
**parent-side bookkeeping** ("one batch plan plus one batch validation"). It did **not** change the three biggest
remaining costs: serial spawning, synchronous linked-repo cloning, and synchronous workspace cloning. Those are the open
items.

## Opportunities (for follow-up design, not yet decided)

Ordered roughly by expected payoff vs. effort:

1. **Defer or parallelize linked-repo materialization (Finding 1).** It is the dominant, spikiest per-spawn cost and
   currently runs synchronously in the parent for every eager agent. Options: defer it to the child like the main
   workspace already is for waved agents; resolve the paths without `materialize=True` at spawn time; or materialize the
   N linked repos concurrently instead of serially.
2. **Replace full `git clone` with `git worktree add` or `clone --shared`/`--reference` (Findings 1 & 3).** Both the
   main-repo and linked-repo materialization do full clones (~1.4 s each cold). A shared object store / worktree avoids
   re-copying history and would cut cold materialization to near-instant.
3. **Overlap the serial spawn loop (Finding 2).** Spawns are independent detached forks; launching them concurrently (or
   at least overlapping each spawn's I/O) turns a sum into a max.
4. **Make async push the default, or surface `-P` prominently (Finding 4).** Removes a network round-trip from the
   default critical path; the local bead-state commit stays synchronous.
5. **Trim import/registry startup (Finding 5).** Cache or lazy-load the xprompt registry (`xprompt_lookup` 463 ms) and
   `project_open` (350 ms); audit the lazy-import blocks in `cli_work_handler` that fall outside the timed stages.

## §6. Time-to-useful-work (the other "slow")

Even with a fast-returning command, an epic *feels* slow because the deferred agents each do their own full
materialization child-side as their waves unblock — the same per-repo `git clone` cost (main workspace + up to five
linked repos), now multiplied across every phase agent and serialized behind wave dependencies. For `sase-55` that is up
to ~6 repos × 7 agents of clone work spread over four dependency waves. The worktree/shared-store change in Opportunity 2
would help here too, since it attacks the per-clone cost that both the parent and the children pay.

## Reproduce

```bash
# Read-side stage breakdown (safe; no agents launched):
SASE_BEAD_WORK_TIMING=1 sase bead work <epic-id> --dry-run    # promote stage logs to info

# Mine real spawn timings already on disk:
python -c "import json,statistics as s; \
rows=[json.loads(l) for l in open('$HOME/.sase/logs/tui_launch_timing.jsonl')]; \
sp=[r for r in rows if r.get('operation')=='agent_launch_spawn']; \
print('spawn total_ms p50/p90/p95:', *[round(s.quantiles([r['total_ms'] for r in sp],n=20)[i]) for i in (9,17,18)])"
```
