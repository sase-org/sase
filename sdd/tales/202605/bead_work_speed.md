---
create_time: 2026-05-09 15:47:37
status: done
prompt: sdd/prompts/202605/bead_work_speed.md
---
# Make `sase bead work` Faster

## Problem

`sase bead work <epic-or-legend>` can feel slow before it returns control to the caller, even though the spawned agents
run asynchronously. The current implementation does substantial synchronous parent-side work:

- builds the bead work plan;
- scans live agent artifacts for generated-name collisions;
- flips the parent bead's `is_ready_to_work` flag;
- pre-claims every phase bead one at a time;
- resolves VCS/xprompt context;
- launches each multi-prompt segment through the generic sequential multi-prompt launcher.

The old 30-second naming-timeout failure mode appears to be fixed in this checkout: `multi_prompt_launcher.py` now uses
the last spawned segment's `request.project_name` for the legacy naming poll. The remaining slow cases are ordinary
linear or near-linear costs that grow with artifact count and phase count.

## Findings

The deterministic work-plan build is not the primary bottleneck. Existing local benchmarking through
`tests/perf/bench_bead.py` shows `build_epic_work_plan` around 20-23 ms for a 500-issue synthetic store. That is not
large enough to explain multi-second `bead work` starts.

The pre-claim loop is a real bottleneck for larger epics. The Python handler currently calls `proj.update()` once per
phase. Each update crosses into Rust, loads `issues.jsonl`, modifies one issue, and rewrites the full JSONL file. In a
synthetic local measurement:

- 10 phase claims: about 23 ms total;
- 50 phase claims: about 298 ms total;
- 100 phase claims: about 1.08 s total;
- 250 phase claims: about 5.3 s total.

That shape is effectively quadratic because each phase claim rewrites the whole store.

The collision check can also be noticeable on mature machines. `find_live_name_collisions()` calls
`get_live_agent_name_map()`, which walks every project under `~/.sase/projects/*/artifacts/ace-run/*` and reads live
metadata before intersecting with the small set of generated bead-work names. On this machine, with about 9,254 artifact
directories and 9,189 `agent_meta.json` files, the scan took about 737 ms to find 34 live names.

Generic multi-prompt launch remains sequential. For each segment it normalizes VCS context, optionally expands xprompts
for fan-out planning, serializes segment-local xprompts, allocates timestamps/workspaces, spawns a child process, and
records workspace/running state. This is partly necessary, but `bead work` is a highly structured caller: it already
knows every generated name and dependency edge before launch, so it should avoid generic fallback work where possible.

## Recommendation

Prioritize a Rust-backed batch preclaim transaction for epic `sase bead work`, then tighten live-name collision lookup.
This gives the best payoff with the least behavioral risk because it preserves the existing agent-launch semantics while
removing the most obvious O(phase_count \* store_size) parent-side cost.

## Implementation Plan

1. Add a core batch mutation for epic phase preclaims.
   - In `../sase-core/crates/sase_core`, introduce a mutation such as `bead_preclaim_epic_work_plan`.
   - Input should include the beads dir, epic id, expected phase assignments, and `now`.
   - The mutation should load the store once, validate all target phase beads still exist and are not closed, capture
     prior `status` and `assignee` for rollback, apply all `status=in_progress` / `assignee=<agent_name>` updates, and
     save once.
   - Return the updated issues and a rollback payload containing each bead's prior status/assignee.

2. Expose the batch mutation through the Python Rust facade.
   - Add a wire conversion in `src/sase/core/bead_mutation_facade.py`.
   - Add a `BeadProject.preclaim_epic_work(...)` method or a narrow helper used only by `sase bead work`.
   - Keep single-issue `update()` semantics unchanged.

3. Update `src/sase/bead/cli_work.py` to use the batch preclaim.
   - Replace the nested `for wave` / `proj.show()` / `proj.update()` loop with one batch call.
   - Preserve the current rollback behavior by adapting the returned rollback payload to the existing
     `rollback_work_launch()` structure.
   - Keep `--dry-run`, confirmation, `is_ready_to_work`, and partial-launch SIGTERM handling unchanged.

4. Add a targeted live-name lookup path for generated bead-work names.
   - Add a function such as `get_live_agent_name_subset(expected_names: set[str]) -> dict[str, str]`.
   - It can still walk artifacts initially, but it should skip work aggressively and short-circuit once all expected
     names are found.
   - Prefer using the Rust artifact scan/index if it can filter names without materializing the full historical tree.
   - Use it in `find_live_name_collisions()` and `_find_live_legend_name_collisions()`.

5. Add performance regression coverage.
   - Extend `tests/perf/bench_bead.py` with a `preclaim_epic_work` scenario for at least 50, 100, and 250 phases.
   - Record expected improvement against the current one-update-per-phase loop.
   - Add unit coverage for all-or-nothing batch preclaim rollback payloads and validation failures.

6. Consider a structured bead-work launch fast path after the mutation fix lands.
   - Longer term, `sase bead work` could pass a launch plan directly to the launch executor rather than rendering a
     generic multi-prompt and rediscovering names/context per segment.
   - This is a larger change because it crosses the agent-launch boundary, so it should follow the batch mutation unless
     profiling after Phase 1 still shows multi-prompt launch overhead as the dominant cost.

## Validation

Run focused tests first:

```bash
just install
pytest tests/test_bead/test_cli_work_epic.py tests/test_bead/test_cli_work_collisions.py tests/test_bead/test_work_epic_plan.py
pytest tests/test_core_facade/test_bead_mutation.py tests/test_bead/test_project.py
```

Then run the relevant perf smoke:

```bash
.venv/bin/python tests/perf/bench_bead.py --runs 5 --issues 500 --dependencies 250
just bead-perf-smoke
```

Finally run the required repository check after code changes:

```bash
just check
```

## Expected Outcome

Large epic launches should stop paying one full JSONL load/rewrite per phase before the agents even start. For epics in
the 100-250 phase range, the parent-side preclaim portion should drop from seconds to roughly one store load, one
in-memory mutation pass, and one store save. Collision checking should also become less sensitive to the user's total
historical artifact count.
