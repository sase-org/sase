---
create_time: 2026-06-23
updated_time: 2026-06-23
status: research
---

# Why `sase bead work` Can Take So Long

## Question

Why does `sase bead work <id>` take a long time before returning control to the caller?

The short answer is that `sase bead work` is not only a launcher. On a real launch it plans the bead DAG, resolves
xprompts and VCS context, optionally kills/reuses prior deterministic agent names, mutates bead state, launches one
process per prompt segment, commits the bead-state change, and by default runs `git push`. The old known hot spots have
mostly been optimized, but the command still has a few synchronous costs that can make it feel slow.

## Current Behavior

The user-facing docs describe the successful epic path as:

- validate the epic plan bead;
- force-reuse deterministic names like `<epic_id>.<N>` and `<epic_id>`;
- mark the epic ready;
- build Kahn waves for the open phase beads;
- preclaim the phase beads;
- hand a `---`-separated multi-prompt to the agent launcher;
- commit the bead-state mutation;
- run `git push` when `bead.push_after_commit` is true, which is the default.

Relevant code:

- `docs/beads.md:295` documents `sase bead work`.
- `docs/beads.md:368` documents the post-launch bead-state commit.
- `docs/beads.md:375` documents the default synchronous `git push`.
- `src/sase/bead/cli_work_handler.py:102` orchestrates the epic path.
- `src/sase/bead/cli_work_commit.py:13` resolves sync/async/off push mode.
- `src/sase/bead/sync.py:49` commits bead-state changes.
- `src/sase/bead/sync.py:248` runs synchronous `git push`.
- `src/sase/bead/sync.py:292` implements async background push.

So for a real `--yes` launch, the command can remain busy even after the child agents have been spawned. A synchronous
push can block on network, remote hooks, or credentials. `--no-push` skips that for one invocation, and
`bead.push_after_commit: async` keeps auto-push but moves it off the critical path.

## Observed Case: `sase-55`

The live epic inspected here was `sase-55`, with six open phase beads:

```text
Epic sase-55: Reasoning-Effort Levels for XPrompt Model/Provider Selection
Wave 0: sase-55.1
Wave 1: sase-55.2, sase-55.5
Wave 2: sase-55.3
Wave 3: sase-55.4, sase-55.6
Land waits on: sase-55.1, sase-55.2, sase-55.5, sase-55.3, sase-55.4, sase-55.6
```

An initial dry run was slow:

```text
TIMEFMT='elapsed_real=%E user=%U sys=%S'
time sase bead work sase-55 --dry-run
elapsed_real=36.46s user=1.80s sys=0.36s
```

That dry run warned that all six phase names already had live owners. Later warm reruns of the same dry-run path were
much faster:

```text
time .venv/bin/python -m sase.main.entry bead work sase-55 --dry-run
elapsed_real=2.65s user=2.37s sys=0.27s

time sase bead work sase-55 --dry-run
elapsed_real=1.87s user=1.50s sys=0.24s
```

This matters: the 36s dry-run result does not appear to be the steady-state cost of current `--dry-run`. It looks more
like a cold-cache, transient I/O, or concurrent-contention event. The command has no durable per-stage dry-run log by
default, so that specific 36s run cannot be decomposed after the fact.

## Artifact and Name-Scan Cost

This machine has a large agent artifact history:

```text
ace-run artifact dirs: 20864
agent_meta.json files: 18453
done.json files: 2578
```

`sase bead work --dry-run` checks whether its expected deterministic names are already live. The optimized helper is
`get_live_agent_name_subset()` in `src/sase/agent/names/_auto.py:223`; it still walks artifact directories, but it only
does liveness checks after finding one of the expected names and stops once all expected names are found.

Measured against the seven `sase-55` names:

```text
elapsed=1.681s matches=7
```

That is a real cost on a mature machine, but it is too small to explain the original 36s dry run by itself. It can,
however, explain why even a dry run is not instant.

## Real Launch Evidence

The live `sase-55` agents show a real launch around 2026-06-23 11:50:30 to 11:51:19:

| Agent | PID | Artifact | Workspace | Waits |
| --- | ---: | --- | --- | --- |
| `sase-55.1` | 628052 | `20260623115030` | `sase_13` | none |
| `sase-55.2` | 628061 | `20260623115033` | primary checkout | `sase-55.1` |
| `sase-55.5` | 628207 | `20260623115034` | primary checkout | `sase-55.1` |
| `sase-55.3` | 628627 | `20260623115040` | primary checkout | `sase-55.1`, `sase-55.2` |
| `sase-55.4` | 629304 | `20260623115050` | primary checkout | `sase-55.1`, `sase-55.2`, `sase-55.3` |
| `sase-55.6` | 629521 | `20260623115057` | primary checkout | `sase-55.2`, `sase-55.3` |
| `sase-55` | 629767 | `20260623115103` | primary checkout | all phase agents |

The durable low-level spawn timing log has these rows:

| PID | Spawn row time | Workspace | Deferred | Total | Linked repo | Workspace claim | Subprocess spawn |
| ---: | --- | ---: | --- | ---: | ---: | ---: | ---: |
| 628052 | 11:50:32.116 | 13 | no | 1188.96 ms | 1159.69 ms | 1.84 ms | 26.39 ms |
| 628061 | 11:50:33.927 | 0 | yes | 51.68 ms | 0.01 ms | 29.01 ms | 50.98 ms |
| 628207 | 11:50:40.544 | 0 | yes | 103.35 ms | 0.01 ms | 41.80 ms | 68.10 ms |
| 628627 | 11:50:50.423 | 0 | yes | 192.94 ms | 0.01 ms | 166.21 ms | 192.19 ms |
| 629304 | 11:50:57.773 | 0 | yes | 28.40 ms | 0.01 ms | 1.70 ms | 27.76 ms |
| 629521 | 11:51:03.098 | 0 | yes | 68.85 ms | 0.01 ms | 42.74 ms | 68.18 ms |
| 629767 | 11:51:09.575 | 0 | yes | 33.78 ms | 0.01 ms | 1.75 ms | 33.10 ms |

The first low-level spawn was about 1.19s, mostly linked-repo resolution. Later deferred spawns were tens to hundreds of
milliseconds. But the spawn rows span 37.46s, with gaps of:

```text
1.81s, 6.62s, 9.88s, 7.35s, 5.32s, 6.48s
```

Those gaps are not explained by the low-level spawn records. They likely sit in parent-side multi-prompt work between
segments, or in contention around project/workspace state, and are not captured in the durable `agent_launch_spawn`
records.

The bead-state launch commit was:

```text
c40682a8621e7b1cdf4d0a1eb83b804546558cf3
AuthorDate: Tue Jun 23 11:51:09 2026 -0400
CommitDate: Tue Jun 23 11:51:09 2026 -0400
Subject: chore: mark bead work launched for sase-55
Files: sdd/beads/events/streams/sase-55.jsonl, sdd/beads/issues.jsonl
```

That timestamp lines up with the last spawn row. There was no durable push timing row, so this evidence does not prove
whether push added more latency in this specific run. It does show that a real launch had a long parent-side segment
launch span before the post-launch commit/push path even became relevant.

## What Is Probably Not the Main Issue Anymore

Several older bottlenecks already have fixes:

- Epic work-plan construction is Rust-backed (`src/sase/bead/work.py:124`) and prior SDD notes measured it around
  20-23 ms for a 500-issue synthetic store.
- Phase preclaim is now batched. Commit `e1b0a1bf6` replaced the old one-update-per-phase loop; prior research found
  250 phase preclaims dropped from about 5-6s to about 29 ms.
- Name validation was improved in commit `4be6f7352`, which loads the reserved-name set once per launch instead of
  repeatedly rechecking registry staleness for each explicit name.
- Bead work now has a planned launch adapter (`src/sase/agent/launch_cwd_bead_work.py:12`) that skips some generic
  rediscovery when VCS context is known.
- `--no-push` and `bead.push_after_commit: async` exist because push was identified as a user-visible post-launch
  delay.

These fixes narrow the remaining problem to launch orchestration, live/collision scans, workspace/project contention,
and sync push.

## Likely Contributors

### 1. Default synchronous push

For actual launches, sync push is the most obvious "why is the command still running?" explanation after agents are
spawned. The default path is:

- `commit_successful_work_launch()` calls `commit_bead_work_launch()`.
- `_resolve_push_mode()` returns `"sync"` unless `--no-push` is set or config says otherwise.
- `push_bead_work_launch()` runs `git push` and inherits stdin/stdout/stderr.

This is desirable for publishing bead-state launch records, but it couples command completion to remote latency.

### 2. Sequential segment launch

`sase bead work` renders a multi-prompt with one segment per phase plus a land segment. Even with the planned bead-work
adapter, the launcher still handles segments sequentially:

- `src/sase/agent/multi_prompt_launcher.py:244` loops over segments.
- `src/sase/agent/multi_prompt_launcher.py:328` resolves VCS context per slot.
- `src/sase/agent/multi_prompt_launcher.py:404` plans names.
- `src/sase/agent/multi_prompt_launcher.py:434` executes the segment launch plan.
- `src/sase/agent/launch_executor.py:92` loops over slots sequentially.

The `sase-55` spawn rows show multi-second gaps between segments even though each low-level spawn was quick. That points
to parent-side work outside `agent_launch_spawn`, not child process runtime.

### 3. VCS/project/workspace state resolution

The first real `sase-55` spawn spent 1159.69 ms in linked-repo resolution. That is captured. The larger unexplained
gaps may involve related per-segment project/VCS/context work before low-level spawn timing begins. The planned adapter
already removes some generic work, but it still canonicalizes aliases, activates known project refs, scans ref
patterns, validates names, and dispatches through the shared multi-prompt loop.

### 4. Live-name collision lookup over artifact history

Dry run and force-reuse safety need to know whether deterministic names are live. The current subset lookup is much
better than building a full active-name map, but it still walks historical artifact directories. On this machine it was
about 1.681s for the `sase-55` expected-name set.

### 5. File locks and workspace contention

Workspace claims use `changespec_lock()` around ProjectSpec read/modify/write. `changespec_lock()` has a 30s timeout
with 0.1s polling (`src/sase/ace/changespec/locking.py:129`), and `claim_workspace()` has retry sleeps for transient
I/O (`src/sase/running_field/_operations.py:76`). Most `sase-55` workspace-claim timings were small, but one was
166.21 ms and others were 29-43 ms. Contention with other live agents could occasionally create larger pauses.

### 6. Child startup can be confused with parent latency

Artifact mtimes show child-side initialization after the parent spawns a process. For example, `sase-55.1` had an
artifact directory timestamp around 11:50:30 and `agent_meta.json` at 11:50:51. Waiting agents wrote `waiting.json`
after their own `agent_meta.json`. These are useful for understanding when agents become visible, but they do not
necessarily mean the parent `sase bead work` command was still blocked at that point.

## Recommended Next Measurements

The biggest gap in the evidence is parent-side timing between multi-prompt segments. Reproduce with a real launch where
it is safe to create or reuse agents:

```bash
SASE_BEAD_WORK_TIMING=1 \
SASE_AGENT_LAUNCH_TIMING=1 \
sase bead work <epic-id> --yes --no-push
```

Use `--no-push` first so the launch path can be separated from remote git latency. Then repeat without `--no-push` if
the push path itself needs measurement.

Add durable timing, or temporarily promote existing `LaunchTimingRecorder` output, around these parent stages:

- `launch_planned_bead_work_agents()` setup;
- per-segment `prompt_normalize`;
- per-segment `wait_resume_rewrite`;
- per-segment `prompt_parse`;
- per-segment `fanout_plan`;
- per-segment `vcs_resolution`;
- per-segment `name_plan`;
- per-segment `execute_launch_plan`;
- post-launch `commit`;
- post-launch `push`.

The existing low-level `agent_launch_spawn` records are not enough: they showed a 37.46s span for `sase-55`, but only
about 1.67s of summed low-level spawn time.

## Operational Mitigations

For day-to-day use:

- Use `sase bead work <id> --yes --no-push` when the launch record does not need to be pushed immediately.
- Set `bead.push_after_commit: async` in config if automatic push is desired but the CLI should return as soon as the
  local launch commit is done.
- Treat slow `--dry-run` results as a signal to inspect artifact-scan or lock contention, because dry run does not
  launch agents, commit, or push.

For implementation follow-up:

- Make `SASE_BEAD_WORK_TIMING=1` durable enough to diagnose one-off slow launches after the fact.
- Add parent-loop timing to `agent_launch_multi_prompt`; the code already creates a recorder, but the observed durable
  log only captured low-level spawn records.
- Consider a more direct bead-work batch launch path if timing confirms that shared multi-prompt per-segment work is
  still responsible for the gaps.
- Consider indexing live artifact names so force-reuse collision checks do not walk tens of thousands of historical
  artifact directories.

## Bottom Line

There are two different latency classes:

1. Real `sase bead work --yes` launches can legitimately take time because they synchronously launch every segment,
   commit bead state, and usually run `git push`.
2. The observed 36s `--dry-run` does not look normal for the current code. Warm dry runs were under 2s, and direct
   live-name lookup was about 1.7s, so the 36s case was probably transient contention, cold filesystem/cache behavior,
   or another parent-side stage that needs durable timing to catch.

For the specific `sase-55` launch, the most suspicious evidence is the multi-second gaps between sequential spawn rows.
Those gaps are outside the low-level spawn timings, so the next useful work is instrumentation in the parent
multi-prompt loop, with push disabled during the first measurement pass.
