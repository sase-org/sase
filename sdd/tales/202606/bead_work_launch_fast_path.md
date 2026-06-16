---
create_time: 2026-06-16 14:00:03
status: done
prompt: sdd/prompts/202606/bead_work_launch_fast_path.md
---
# Plan: Make `sase bead work` Return Much Faster

## Context

`sase bead work <id>` has already received the first round of performance fixes from
`sdd/tales/202605/bead_work_speed.md`: the epic phase preclaim loop is now a Rust-backed batch mutation, and live-name
collision lookup uses `get_live_agent_name_subset()`.

Current local evidence shows those fixes worked:

- `tests/perf/bench_bead.py --runs 3 --issues 500 --dependencies 250`
- `build_epic_work_plan`: median about 21 ms
- batch preclaim for 250 phases: median about 29 ms
- old per-phase preclaim loop for 250 phases: median about 6.1 s

So the remaining slowness is no longer bead-store mutation. The remaining parent-side costs are mostly launch
orchestration and post-launch git work:

- `bead work` renders a generic multi-prompt, then calls `launch_agent_from_cwd()`.
- `launch_agent_from_cwd()` re-parses and re-discovers context that `bead work` already knows: segment split,
  deterministic names, dependency waits, per-segment env, VCS/project wrapper, and absence of fan-out directives.
- The generic multi-prompt launcher validates every explicit `%name` through the durable agent-name registry. A mocked
  local benchmark, with real subprocess spawning and workspace claiming patched out, still spent about 5.7-5.9 s for 5
  bead-like segments and about 22 s for 20 segments before I stopped the 50-segment probe. The stack was in
  `validate_launch_name_requests() -> is_name_reserved() -> load_name_registry()`, whose cache path still checks
  registry staleness by walking registered owner paths.
- Each regular segment also claims a workspace and resolves/materializes/cleans that workspace before spawning.
- After agents launch, `bead work` commits bead state and, by default, runs `git push`. The push can block on network or
  credentials even though the agents are already launched.

## Goal

Make the perceived `sase bead work --yes` latency scale close to "one batch plan + one batch validation + required
workspace preparation" rather than "generic launch overhead times segment count".

Target outcome for a typical 5-20 phase epic: return in seconds less, with the biggest win on machines with large
agent-name registries or slow artifact storage. Large epics should keep the previous batch-preclaim improvement and
avoid reintroducing O(phase_count \* registry/artifact history) behavior.

## Non-Goals

- Do not change phase/land prompt text, wait semantics, model routing, bead env, or rollback semantics.
- Do not weaken name collision safety for normal user launches.
- Do not make spawned agents share workspaces.
- Do not move shared backend behavior into Python if it belongs in `../sase-core`.

## Plan

### 1. Add bead-work timing around the actual parent path

Add structured timing to `src/sase/bead/cli_work.py`, using the existing `LaunchTimingRecorder` style or a small
bead-specific wrapper enabled by an env var such as `SASE_BEAD_WORK_TIMING=1`.

Measure these stages separately:

- project open and initial `show`
- xprompt lookup
- work-plan build
- VCS/ChangeSpec context resolution
- prompt rendering
- force-reuse cleanup
- `mark_ready_to_work`
- batch `preclaim_epic_work`
- agent launch call
- commit
- push

Extend `tests/perf/bench_bead.py` or add a sibling perf harness that builds synthetic epic/legend stores and invokes
`handle_bead_work()` with the launcher, commit, and push patched. Include registry-size scenarios so the name-registry
cost has a regression floor.

### 2. Fix explicit-name validation to load the registry once per launch

`validate_launch_name_requests()` currently calls `is_name_reserved()` for each explicit name. Even with the registry
cache, each call can re-run stale-owner checks over the registry entries. Change the validator to compute the
reserved-name set once under the existing `agent_name_allocation_lock()` and then check every request against that set.

Keep behavior unchanged:

- syntax validation still applies unless the trusted internal separator bypass is set
- duplicate names inside one launch still fail
- existing reserved names still fail
- forced-reuse names still require explicit confirmation and rewrite before launch

This is the lowest-risk high-payoff change because it improves all multi-prompt launches, not only bead work, while
preserving the same safety contract.

### 3. Add a structured bead-work launch adapter

Introduce a narrow agent-launch API for callers that already have a fully planned multi-prompt, for example
`launch_planned_bead_work_agents(...)`.

The adapter should accept:

- pre-split prompt segments, rather than a joined string that must be parsed again
- per-segment env from `epic_work_segment_env()` / `legend_work_segment_env()`
- expected deterministic names
- the already resolved project/VCS context when available
- an assertion that bead work does not use parent-side fan-out directives

Initially, implement this adapter as a thin wrapper around `launch_multi_prompt_agents()`, but pass preplanned one-slot
fanout plans so the generic launcher does not parent-expand `#bd/work_phase_bead`, `#bd/land_epic`, or `#bd/land_legend`
merely to discover there is no fan-out.

Update `cli_work.py` to call this adapter after force-reuse cleanup and before commit. Keep the current generic
`launch_agent_from_cwd()` path as a fallback for unusual contexts until tests cover the direct path.

### 4. Preserve name safety with batch reservation, not blind bypass

After the one-load validator fix, evaluate whether explicit bead-work names still dominate. If they do, add a trusted
batch reservation path for prevalidated explicit names:

- reserve all deterministic bead-work names for their future artifact directories in one registry mutation
- mark reservations committed as each child successfully spawns
- release uncommitted reservations on partial launch failure

This should reuse the existing planned-name reservation model rather than skipping the registry. The important change is
to reserve explicit deterministic names in bulk instead of repeatedly loading/staleness-checking the registry.

### 5. Batch or parallelize workspace preparation only after timing proves it matters

If timing shows workspace work is the next bottleneck, add a second-stage launch executor improvement:

- reserve all timestamps for the bead-work slots in one batch
- allocate workspace numbers for the slot batch under one ProjectSpec lock where safe
- pre-resolve/materialize/clean the claimed workspace directories before spawning, with bounded concurrency
- keep parent preclaims and child transfer semantics intact so other launchers cannot race into the same slots

This should be treated as a follow-up because workspace claims are correctness-critical. Implement it in shared
launch/running-field code, and move any core planning logic into `../sase-core` per the project boundary rule.

### 6. Remove push latency from the critical path

Keep the local bead-state commit synchronous, because failed mutation commits need to be reported clearly. Make remote
push nonblocking or opt-in for `sase bead work`:

- add a config-compatible mode such as `bead.push_after_commit: async` or a CLI flag like `--no-push`
- default conservatively unless Bryan confirms a behavior change is desired
- when asynchronous, launch a small detached push helper and print where failures are logged

This makes "agents launched" return without waiting on remote network latency while preserving the existing local
durability point.

## Validation

Run targeted tests:

```bash
just install
pytest tests/test_agent_launch_validation.py
pytest tests/test_multi_prompt_launcher_launch.py tests/test_multi_prompt_launcher_launch_env.py
pytest tests/test_bead/test_cli_work_epic_launch.py tests/test_bead/test_cli_work_epic_lifecycle.py
pytest tests/test_bead/test_cli_work_legend.py tests/test_bead/test_cli_work_collisions.py
```

Run perf checks:

```bash
.venv/bin/python tests/perf/bench_bead.py --runs 5 --issues 500 --dependencies 250
SASE_BEAD_WORK_TIMING=1 pytest -q tests/test_bead/test_cli_work_epic_launch.py
```

After code changes in this repo, run:

```bash
just check
```

If the workspace-claim phase touches `../sase-core`, also run the relevant Rust/core tests from the matched
`sase-core_13` workspace before the final repo check.
