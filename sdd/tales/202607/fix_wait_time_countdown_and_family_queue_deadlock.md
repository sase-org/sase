---
create_time: 2026-07-06 13:35:55
status: done
prompt: sdd/prompts/202607/fix_wait_time_countdown_and_family_queue_deadlock.md
---
# Fix `%wait` time countdown + queued family child launch deadlock

## Problem

Launching an agent with `%n(<parent>, <suffix>)` while the parent is still running (the sase-5f.4 "queue family children
behind running parents" feature, commit `dfd9f50f0`) combined with a `%wait(time=...)` floor (e.g. via `#t:5m`)
misbehaves in two user-visible ways:

1. **The live countdown in the agent row is wrong.** The `WAITING <n>s` countdown starts ticking from agent creation
   time instead of from the moment the waited-for agents finish. The countdown should not run at all until every agent
   dependency has resolved.
2. **The queued agent never launches.** Even after the bogus countdown reaches zero, and even after the _correct_
   deadline (parent finish + duration) passes, the agent stays `WAITING` forever (until the 24h wait timeout).

## Reproduced diagnosis (verified against a live stuck run)

Observed run: `#gh:sase %n(b, launch) ... #t:5m` launched at 13:10:04 while agent `b` (artifact `20260706130831`) was
running; `b` finished at 13:13:08 and wrote a successful `done.json`.

The queued child's artifact (`20260706131004`) shows how the pieces connect:

- `src/sase/axe/run_agent_directives.py` (family-attach branch, ~lines 110–120 and 283–298) gives the queued child
  `wait_for: ["b"]` **plus** an identity dep pinned to the parent's artifact dir, and — critically — writes the child's
  own meta with `workflow_name: "b"`, `agent_family: "b"`, `parent_timestamp: "20260706130831"`. The queued child is
  therefore itself a member of the family generation it waits on.
- `src/sase/axe/run_agent_wait.py::wait_for_dependencies` writes `waiting.json` (`waiting_for` + `wait_for_artifacts` +
  `wait_duration`) and polls for `ready.json`. The duration timer is only started (and `wait_until` only written into
  `waiting.json`) _after_ `ready.json` appears. This runner logic is correct.
- The wait_checks chop (`src/sase/scripts/sase_chop_wait_checks.py`) decides when to write `ready.json`, via
  `src/sase/core/wait_dependency_resolution.py::dependency_resolution_status`.

### Root cause 1 — self-deadlock in wait dependency resolution (never launches)

`WaitDependencyIndex.identity_status` expands a pinned parent artifact through `family_candidate_for_root`, which
aggregates _every_ family-generation member (`timestamp == root.timestamp or parent_timestamp == root.timestamp`) and
requires all of them to be resolved. The queued child **is** such a member (its `parent_timestamp` is the root's
timestamp and its `workflow_name`/`agent_family` put it in `families[<base>]`), and it is unresolved by definition while
it waits. So the child's own artifact permanently blocks the child's own wait: resolution returns `waiting` forever,
`ready.json` is never written, the timer never starts, and the agent never launches.

Verified empirically: rebuilding the real index and evaluating `dependency_resolution_status` returns `waiting` even in
a counterfactual where the parent's successful `done.json` is present. In the live index, `families["b"] == [b--launch]`
— the waiter itself is the only "generation member" consulted (the parent root has no `workflow_name` in its meta, so
only the attached child lands in the families bucket).

Note the same shape also mutually deadlocks **two** queued siblings attached to one running parent (each blocks on the
other's unresolved artifact), so excluding only "self" is not sufficient.

The existing family-generation expansion is intentional and must be preserved: the tests in
`tests/test_axe_chop_wait_checks_plan_families.py` pin that waiting on a plan-chain root only resolves when the whole
generation (e.g. the `--code` child) succeeds, and that a failed/killed generation member cancels the wait.

### Root cause 2 — TUI countdown anchored at agent start (wrong countdown)

`src/sase/ace/tui/models/agent_time.py::wait_remaining_seconds` falls back to `agent.start_time + wait_duration`
whenever `agent.wait_until` is unset. For a wait with agent dependencies, `wait_until` is only written by the runner
once dependencies resolve — until then there is no running timer, so this fallback fabricates a countdown anchored at
launch time. The Agents-tab row renderer (`src/sase/ace/tui/widgets/_agent_list_render_agent.py`, `WAITING` branch)
displays it as soon as its `wait_deps_satisfied` heuristic (TUI status buckets, an optimistic display-only check in
`src/sase/ace/tui/agent_completion.py`) says the deps look done — which can disagree with the chop's authoritative
resolution, as it did here. The detail header (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py`) already
gates its duration countdown on `not agent.waiting_for`; the row path and the shared helper do not.

`wait_countdown_ticks` (same module) has the same unconditional `wait_duration + start_time` condition, so rows tick
per-second (render-cache invalidation) even when nothing meaningful is counting down.

### Root cause 3 (secondary, discovered while diagnosing) — cleanup wedges waiters

While the agent sat wrongly queued, a TUI cleanup/dismiss
(`src/sase/ace/tui/actions/agents/_killing_utils.py::delete_agent_artifacts`, backed by the `delete_agent_artifacts`
core binding) removed the _parent's_ `done.json` (observed: marker written at 13:13:08, deleted at 13:22:24). After
that, no resolver can ever see the dependency as done — waiters hang until the 24h timeout even with root causes 1–2
fixed. Cleaning up a terminal agent that other agents are still waiting on silently strands them.

## Fix plan

### Phase 1 — core: queued artifacts must not gate wait resolution

In `src/sase/core/wait_dependency_resolution.py`:

1. Teach `WaitDependencyIndex.add` to detect a **queued** artifact: `waiting.json` exists in the artifact dir and there
   is no `done.json`. Record it on `_ArtifactCandidate` (e.g. `is_queued`).
2. Exclude queued candidates from _generation aggregation_ in `family_candidate`, `family_candidate_for_root`, and
   `workflow_candidate` (membership of `generation` / the aggregate `is_resolved` / `is_done` / `is_identity_success` /
   `is_failed` computations). Semantics: an agent still queued at its wait barrier has not started its work, so it
   neither satisfies nor blocks a family/workflow wait. A terminal artifact that still has a stale `waiting.json` (e.g.
   killed mid-wait) keeps its terminal semantics (failure still cancels).
3. If filtering leaves `family_candidate_for_root` with an empty generation, return `None` so `identity_status` falls
   back to the pinned candidate's own terminal state — that is exactly the "wait for the parent agent itself" intent of
   the queue-behind-running-parent feature.
4. Keep queued artifacts' **named** candidates untouched: an explicit `%wait` on a queued agent's own name must still
   block until that agent actually runs and finishes.
5. Belt-and-braces: thread an optional `self_artifact_dir` exclusion through `dependency_resolution_status`, passed by
   the chop (the waiting marker's own dir) and by `run_agent_wait._initial_dependency_result` (its `artifacts_dir`).
   This covers the initial-check window before the waiter's `waiting.json` exists.

The root-b-style case (parent root without `workflow_name` in meta) then resolves via the pinned candidate / `named`
path; the plan-family cases keep their generation semantics because their in-flight members are running (not queued).

### Phase 2 — TUI: countdown only when a timer is actually running

In `src/sase/ace/tui/models/agent_time.py`:

1. `wait_remaining_seconds`: keep the `wait_until` branch (authoritative — the runner writes it into `waiting.json` when
   the floor timer really starts). Only use the `start_time + wait_duration` anchor when the agent has **no** pending
   agent dependencies (`not agent.waiting_for`) — i.e. pure duration waits, where the timer genuinely starts at launch.
   Otherwise return `None`.
2. `wait_countdown_ticks`: mirror the same condition so tick scheduling and rendered text stay consistent (no per-second
   render-cache invalidation for rows that render a static label — see `memory/tui_perf.md` rule about mtime/memoized
   render caches).

In `src/sase/ace/tui/widgets/_agent_list_render_agent.py` (`WAITING` branch):

3. While agent deps are pending and a duration floor exists, render a static, non-ticking hint (e.g. `WAITING +5m`,
   mirroring the detail header's `b ✓ + 5m`) instead of a countdown. Once the runner writes `wait_until`, the existing
   countdown path takes over naturally.
4. Keep `wait_deps_satisfied` (status buckets) for badge/hint display only; it can no longer fabricate a countdown
   because the helper now requires `wait_until` when dependencies exist.

Optional consistency cleanup: have the detail header's duration-countdown branch call `wait_remaining_seconds` instead
of duplicating the anchor logic.

### Phase 3 — hardening: don't strand waiters when a dependency's markers are deleted

Scoped, severable follow-up (can be split into its own change if review prefers):

In the Python cleanup/dismiss wrapper (`src/sase/ace/tui/actions/agents/_killing_utils.py::delete_agent_artifacts`),
before deleting loader-visible markers for an agent, resolve any active waiters that reference it: scan the project's
`waiting.json` markers (same traversal the chop uses), match identity deps by `artifact_dir` and name deps by the
deleted agent's name, and write the appropriate `ready.json` (resolved when the deleted agent's `done.json` outcome was
successful; cancelled `dependency_failed` otherwise), reusing the chop's marker formats. This makes cleanup of a DONE
dependency behave as "the dependency finished" instead of "the dependency never finishes".

## Tests

- `tests/test_axe_chop_wait_checks*.py`:
  - New: queued family child attached to a running parent (child meta has
    `workflow_name`/`agent_family`/`parent_timestamp` of the parent, plus its own `waiting.json` with an identity dep on
    the parent) → `ready.json` written once the parent's `done.json` lands; both when the parent root has
    `workflow_name` meta and when it does not (the observed case).
  - New: two queued siblings behind one running parent both resolve (no mutual deadlock).
  - New: queued member with a _failed_ terminal marker still cancels (stale `waiting.json` + killed `done.json`).
  - Existing plan-family generation tests must stay green unchanged.
- `tests/test_run_agent_wait.py`: initial-check self-exclusion (agent deps + no duration, self artifact present in the
  family index) does not deadlock.
- Agent-time unit tests: `wait_remaining_seconds` returns `None` for `waiting_for + wait_duration` without `wait_until`;
  returns the countdown once `wait_until` is set; keeps the start-anchored countdown for duration-only waits.
  `wait_countdown_ticks` matches in all three cases.
- Row-render test: `WAITING` row with pending deps + duration shows the static `+5m` hint and no ticking countdown (even
  with `wait_deps_satisfied=True`); shows the countdown once `wait_until` is present.
- Phase 3: cleanup of a done dependency writes `ready.json` for its waiters.

## Notes

- **Rust core boundary**: all touched logic already lives in this repo's Python (`sase.core.wait_dependency_resolution`
  is the shared resolver used by the chop and runner; the rest is TUI presentation). No `sase-core` wire/API changes are
  needed; Phase 3 hooks in the Python wrapper before delegating to the existing `delete_agent_artifacts` binding.
- **Remediation for the currently stuck agent**: the live `b--launch` runner will poll `ready.json` for up to 24h.
  Because its parent's `done.json` was already cleaned up, Phase 1 alone cannot unstick it — kill the stuck agent (or
  hand-write its `ready.json`) after landing the fix.
- The TUI `wait_deps_satisfied` status-bucket heuristic still differs from the chop's resolver (optimistic,
  display-only). With the countdown re-anchored on `wait_until` this is cosmetic; unifying the two is intentionally out
  of scope.
