---
create_time: 2026-06-19 10:25:59
status: done
prompt: sdd/prompts/202606/fork_wait_defers_workspace.md
---
# Plan: Make the Implicit `#fork:<name>` Wait Also Defer Workspace Allocation

## Context

The recently-shipped change (`sdd/tales/202606/fork_implies_wait.md`, commit `e64a9ebf1`) made a top-level
`#fork:<name>` reference imply `%wait:<name>`. The stated goal was that a bare `#fork:foo` should "automatically behave
as if `%w:<name>` were also present."

That goal is only **partially** met. The implicit wait was added as _runner_ metadata only, in
`extract_directives_and_write_meta` (`src/sase/axe/run_agent_directives.py`): the fork target is appended to
`wait_names`, which drives `agent_meta["wait_for"]`, `AgentInfo.wait_names`, and the real `wait_for_dependencies()` call
inside the agent process.

However, the **launch-time** decision of whether to _defer workspace allocation_ is made by a separate predicate,
`has_deferred_start_directive()` in `src/sase/xprompt/directives.py`, which only matches `%wait`/`%w`/`%time`/`%t`. It
has no knowledge of the implicit fork wait.

All three launch entry points use this predicate:

- `src/sase/agent/launch_cwd_agents.py:357` — `has_wait = has_deferred_start_directive(query)`
- `src/sase/agent/multi_prompt_launcher.py:271` — per segment
- `src/sase/ace/tui/actions/agent_workflow/_launch_body.py:312`

The resulting `has_wait` flows to `deferred_workspace=has_wait` (multi-prompt launcher) and to workspace claiming in
`launch_cwd_agents` (`fixed_workspace = is_home_mode or has_wait`). There is no compensating fork-awareness anywhere in
the executor / VCS / workspace-claim layer — `deferred_workspace` flows straight from `has_deferred_start_directive`.

### The bug

A bare `#fork:foo`:

- **Before** the prior change: did not wait at all (consistent — no defer, no wait).
- **After** the prior change: _waits_ in the runner (good) but the launcher does **not** defer the workspace. The forked
  agent therefore claims a numbered `sase_<N>` workspace immediately and **holds it idle** for the entire time the
  parent runs, then proceeds.

By contrast, the explicit `#fork:foo %w:foo` form _does_ defer (the `%w` is detected), so it sits on a placeholder
workspace and only claims a real one once the dependency is satisfied. The two forms are therefore **not equivalent**,
contradicting the prior plan's intent, and forking a long-running agent can needlessly hold / starve the limited
numbered-workspace pool.

## Goal

Make a bare `#fork:foo` defer workspace allocation exactly like `#fork:foo %w:foo`, so the implicit fork wait is fully
equivalent to the explicit form across every launch surface.

## Proposed Approach

### 1. Add a detection-only fork-reference helper

Add `has_fork_reference(prompt: str | None) -> bool` in `src/sase/agent/names/_resume.py` and export it from
`src/sase/agent/names/__init__.py`.

It mirrors `first_fork_agent_name`'s matching exactly — fenced-block and disabled-region protection plus `_FORK_REF_RE`,
so legacy `#resume`, `#fork_by_chat`, and bare `#fork` (no name) are all excluded — but it must **not** resolve the
agent-name template. Detection-only means:

- It never touches the filesystem / active-agent registry.
- It never raises on an unresolvable template such as `#fork:build-@` (which would otherwise blow up at launch).
  Resolution failures should keep surfacing where they do today — during directive extraction inside the runner — not at
  the workspace-allocation boundary.

It returns `True` as soon as it sees a top-level `#fork:<name>` reference with a non-empty argument.

### 2. Collapse the parsing duplication

`first_fork_agent_name` is already a near-verbatim copy of `first_resume_agent_name`; adding `has_fork_reference` would
create a third copy. Extract one shared private generator (e.g.
`_iter_reference_args(prompt, pattern, *guard_substrings)`) that applies the protection passes and yields each reference
argument string. Re-express all three helpers on top of it:

- `first_resume_agent_name` — resolve-template on the first yielded arg (uses `_RESUME_REF_RE`).
- `first_fork_agent_name` — resolve-template on the first yielded arg (uses `_FORK_REF_RE`).
- `has_fork_reference` — return `True` if the generator yields anything (no resolution).

Behavior of the two existing functions must remain identical (their tests should be untouched and still pass).

### 3. Teach the launch-time predicate about fork

Update `has_deferred_start_directive()` in `src/sase/xprompt/directives.py` to also return `True` when
`has_fork_reference(prompt)` is `True`, via a function-local `from sase.agent.names import has_fork_reference`. This
matches the existing pattern in that file (it already does function-local `from sase.agent.names import ...`) and avoids
a circular import (`agent.names` does not import `xprompt.directives`). A single change here fixes all three launch call
sites uniformly.

This keeps the launcher and the runner consistent:

- Runner waits iff `first_fork_agent_name(...)` is non-`None`.
- Launcher defers iff `has_fork_reference(...)` is `True`.

For every normal case these agree. For the pathological unresolvable-template case, the launcher defers and the runner
then raises during extraction (the pre-existing behavior) rather than silently mismatching.

### 4. Verify the deferred-workspace invariant still holds

With the fix, a bare `#fork:foo` sets `has_wait=True` at launch → `deferred_workspace=True`. The runner independently
sets `has_wait=True` (fork target is in `wait_names`), so the
`if deferred_workspace and not is_home_mode and not has_wait` guard in `src/sase/axe/run_agent_runner.py` does **not**
fire. Bare fork is thereby routed through the same deferred-workspace path that explicit `#fork %w` already exercises —
no new code path, just wider reuse of a tested one.

## Tests

- `tests/test_directives_has_helpers.py`: `has_deferred_start_directive` is `True` for `#fork:foo`, `#fork(foo)`, and
  `` #fork:`foo bar` ``; and `False` for bare `#fork`, `#fork_by_chat:x.md`, `#resume:foo`, and `#fork:...` inside
  fenced / disabled regions.
- `tests/test_agent_names.py`: unit tests for `has_fork_reference` paralleling the existing `first_fork_agent_name`
  cases, explicitly asserting it does **not** raise for an unresolvable template `#fork:build-@` (detection-only).
- A launch-level test (follow `tests/test_multi_prompt_launcher_launch.py`, which already asserts `deferred_workspace` /
  `workspace_num` kwargs, and/or `tests/test_cd_launch_from_cwd.py`) showing a bare `#fork:foo` defers workspace
  allocation, matching `#fork:foo %w:foo`.
- Because main-repo source files change: `just install` then `just check`.

## Out of Scope (considered, deliberately no change)

- **`src/sase/default_xprompts/research_swarm.md:39`** now carries a redundant `%wait:research.@.final` alongside
  `#fork:research.@.final`. It is harmless; editing a default xprompt risks behavior changes for little benefit.
- **Template-resolution timing**: `#fork:build-@` with no concrete target now raises during extraction even with an
  explicit `%name`/auto-dismiss. This is pre-existing parity with `first_resume_agent_name` and not worth changing.
- **`#fork:X %name:X` self-wait**: pathological; the explicit name-claim collision on `X` fails the launch before any
  wait, so no deadlock is reachable.
- **Sibling repo `sase-telegram`**: no change. It only emits copy text (`#fork:<name>`); the runner enforces the wait,
  and this plan only affects the launch-time deferral on the main repo.

## Risks

- The fix widens the set of prompts that defer workspace allocation. Mitigated by routing through the already-tested
  explicit `#fork %w` deferred path and by keeping launcher/runner detection logic symmetric.
- `has_deferred_start_directive` becomes marginally heavier (a regex scan with protection passes for prompts containing
  `#fork`). This is launch-time only, not a hot loop, and `first_resume_agent_name` is already invoked at launch in the
  name allocators, so the cost profile is unchanged in practice.
