---
create_time: 2026-04-17 22:14:28
status: done
bead_id: sase-k
prompt: sdd/prompts/202604/repeat_agents_as_entries.md
---

# Plan: Spawn Each `%r:N` Iteration as Its Own Top-Level Agent Entry

## Background

The `%r:N` (alias `%repeat:N`) directive today runs N prompt iterations **inside a single runner process**. The
execution loop lives in `src/sase/axe/run_agent_runner.py:375-423`, persists live progress to `repeat_state.json`, and
writes a per-iteration marker `repeat_iter_<k>.json`. The TUI
(`src/sase/ace/tui/models/_loaders/_artifact_loaders.py:482-581`, function `load_repeat_iteration_children`) rehydrates
those markers as synthetic **child** entries under a single foldable parent — rendered as
`[workflow] sase (DONE) ↻2/4 … @sase-j` with `└─ 1/4`, `└─ 2/4`, … nested underneath (see
`src/sase/ace/tui/widgets/agent_list.py:373-384` for the `↻` counter and `_CHILD_INDENT` rendering).

The user finds this display unreadable: the tree crams many half-meaningful "1/4, 1/4, 1/4, 2/4, 2/4, 2/4" rows under
one synthetic workflow parent, sharing a single `@<name>` label, and the "workflow" abstraction is fake — there is only
one process.

**Desired behavior.** When a prompt contains `%r:N` (optionally with `%n:<base>`), spawn **N independent agents** — each
its own subprocess, workspace, `agent_meta.json`, and PID — named `<base>.1`, `<base>.2`, …, `<base>.N`. Each appears as
its own **top-level** entry in the Agents tab. The current "one parent, N iteration children" nesting is removed
entirely.

## Goal

After this plan lands:

1. A prompt containing `%r:4 %n:sase-z` spawns **four** separate agent processes, named `sase-z.1`, `sase-z.2`,
   `sase-z.3`, `sase-z.4`.
2. Each of the four appears as its own top-level row in the `sase ace` "Agents" tab — no foldable parent, no `↻N/M`
   glyph, no synthetic `[workflow]` node.
3. The `n` and `N` xprompt variables are still available inside each agent's prompt context (`n` = this agent's
   1-indexed slot; `N` = total count), so any downstream workflow that keys off the iteration number still works.
4. Bare `%n` (or absent `%n`) causes the whole batch to share one auto-generated base name (e.g. `a` → `a.1..a.N`). The
   base reserves its slot via `get_next_auto_name()` exactly once, per the existing `workflow_name`-vs-`name` convention
   already used in `src/sase/agent/names.py:454-464`.
5. The single-iteration case (`%r:1`) is a no-op — it behaves exactly like omitting `%r` (`%repeat:1` is already
   allowed-but-no-op today per `src/sase/xprompt/directives.py:497-500`; keep that behavior).
6. `repeat_state.json` and `repeat_iter_<k>.json` artifacts are no longer written. The TUI paths that consumed them are
   removed.

## Non-goals

- We do NOT change `%m(opus,sonnet)` / multi-model fan-out. That code path (`_launch_multi_model_agents` at
  `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py:298-380`) is the **template** for the new repeat fan-out,
  but we leave it untouched. Combining `%r:N` and `%m(...)` remains valid (see Phase 1 design decision below).
- We do NOT keep a "show `↻N/M` on the parent when collapsed" summary affordance. There is no parent after this change;
  the glyph is fully dead code.
- We do NOT migrate in-flight repeat agents that were already running under the old single-process model when this
  change lands. Those finish their current iteration and exit naturally (see the "Backward compatibility" decision
  below).
- We do NOT add a new directive or CLI flag. The `%r` / `%repeat` surface stays identical — only the under-the-hood
  dispatch changes.
- We do NOT change fail-fast semantics across iterations (see the "Parallel vs sequential" decision — with parallel
  independent agents, there is no cross-agent abort).

---

## Design decisions (open questions resolved)

### 1. Parallel vs sequential dispatch → **Parallel, staggered by 1 second**

The existing `_launch_multi_model_agents` helper (`_agent_launch.py:298-380`) launches each model's agent in sequence
with a `time.sleep(1)` between launches (line 329-330), but each call is fire-and-forget — the subprocesses then run
concurrently. Adopt the identical pattern for repeats.

Rationale:

- Cleanest architecturally: each agent is a fully independent subprocess with its own workspace. No cross-agent
  coordination.
- Matches an existing, battle-tested pattern (`_launch_multi_model_agents`).
- The stagger prevents timestamp collisions (`generate_timestamp()` is second-resolution; the sleep also spreads
  workspace claims).
- The current "fail-fast: a failing iteration stops the loop" behavior is lost. This is an **intentional semantics
  change** — call it out in the PR description. Repeat is typically used for iterative refinement sweeps where a failure
  mid-stream is not catastrophic, and independent agents are easier to kill/inspect individually. (Users who want
  sequential can chain prompts manually.)

### 2. Where to fan out → **`_agent_launch.py`, adjacent to `_launch_multi_model_agents`**

Fan-out happens at the TUI's launch layer, not at directive-parse time and not inside the runner. Concretely:
`_finish_agent_launch` already does multi-model detection via `split_prompt_for_models()` at `_agent_launch.py:245-250`.
We add a parallel check — `extract_repeat_count()` — and dispatch to a new `_launch_repeat_agents()` helper that mirrors
`_launch_multi_model_agents()` structurally.

Ordering matters with multi-model: **multi-model splits first, then each per-model prompt is checked for `%r:N`**. So
`%m(opus,sonnet) %r:3` yields 6 total agents (`opus.1..opus.3`, `sonnet.1..sonnet.3`) — each split first on model, then
each model-arm fans out into 3 repeat agents. This drops out naturally if `_launch_repeat_agents` is called **from
inside** `_launch_multi_model_agents`'s per-model loop — see Phase 1 for the exact insertion.

The alternative (fan out at directive-parse time, before any workspace resolution) was considered and rejected: the
`_agent_launch.py` layer already owns workspace allocation (`get_first_available_axe_workspace`), timestamp generation
(`generate_timestamp`), and VCS-ref resolution. Moving the fan-out deeper would duplicate all of that or require
threading N workspace claims through a single directive parser. The launch layer is the right seam.

**CLI parity note.** The same fan-out must apply to `sase run` invocations, not just the TUI — a prompt with `%r:3` on
the CLI should also spawn three independent processes. That dispatch lives in the CLI entry point (to be located in
Phase 1 — likely `src/sase/main/run_handler.py` or `src/sase/axe/run_command.py`; the phase agent greps to confirm).
Extract the fan-out helper into a module reusable by both TUI and CLI (proposed location:
`src/sase/agent/repeat_launcher.py`).

### 3. Repeat-specific artifacts (`repeat_state.json`, `repeat_iter_<k>.json`) → **Obsolete, delete the write paths**

Each iteration is now its own agent, so each has its own `agent_meta.json`, `done.json`, diffs, response file, etc. —
exactly like a normal single agent. The old markers conveyed "which iteration is currently running" and "per-iteration
artifact pointers under one parent", both of which are no longer needed.

Plan:

- Remove `_write_repeat_state`, `_write_repeat_iter_marker`, and all call sites from `run_agent_runner.py` (lines
  ~49-86, ~375-423).
- Remove `load_repeat_iteration_children()` from `_artifact_loaders.py` (lines 482-581) and its single caller.
- Remove the `repeat_count` and `repeat_iteration` fields from the `Agent` dataclass
  (`src/sase/ace/tui/models/agent.py:150ish`) — they have no remaining consumers once the TUI render paths below are
  simplified.
- Any test that exercises these artifacts either deletes or adapts — see Phase 4.

### 4. TUI code to remove / simplify

Explicit removals in Phase 3:

- `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`: `load_repeat_iteration_children()` (function + call site).
- `src/sase/ace/tui/widgets/agent_list.py`: the `↻N/M` rendering branch (lines 373-384), the `_is_foldable_parent`
  special-case for repeat parents (line 94), and any fold-annotation logic in `_compute_fold_annotation` that reads
  `repeat_count` (lines 436-491 region).
- `src/sase/ace/tui/models/agent.py`: `repeat_count` and `repeat_iteration` fields + `Agent.__init__` if it populates
  them.
- `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`: `enrich_agent_from_meta` drops the
  `repeat_count`/`repeat_iteration` reads.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`: the "Repeat:" header line in the detail panel (added
  by `plans/202604/repeat_directive.md` Phase 6) — delete it.
- Grep `rg "repeat_count|repeat_iteration|↻|\\u21bb" src/sase/ace/` to catch any stragglers the phase agent missed.

After these deletions, existing workflow-step nesting (workflow parents with sub-step children) is untouched. The
fold/expand machinery already keys off `parent_timestamp`, and repeat children no longer set that, so they'll render as
flat top-level entries with no special handling.

### 5. Name collisions → **Let the user's `%n:<base>` win or fail loudly; auto-gen is conflict-free**

Cases:

- **Auto-gen base (no `%n` or bare `%n`):** `get_next_auto_name()` (`names.py:401-409`) already scans active agents'
  `workflow_name`-or-`name` and returns the first unused letter. Reserve that base once (e.g. `a`), then `a.1..a.N` are
  guaranteed free because nothing else can collide with `a.*` unless another repeat batch reused the same base, which
  `get_next_auto_name()` prevents via the `workflow_name`-or-`name` check on line 455. **No changes to `names.py` needed
  for this case.**

- **Explicit `%n:sase-z`:** If any of `sase-z.1..sase-z.N` is already claimed by an active agent (alive per
  `is_process_alive()` or pending `done.json`), **fail loud** with a user-facing error:
  `"agent name 'sase-z' would collide at 'sase-z.<k>' — dismiss or wait for the existing agent, or pick a different base name"`.
  Do NOT silently renumber (`sase-z.5` as the 1st iteration is confusing) and do NOT auto-pick a different base (the
  user explicitly asked for `sase-z`). Surface via `self.notify(..., severity="error")` in the TUI path; raise a clear
  exception on the CLI path.

- **Re-running the same `%n:sase-z` repeat later:** After the batch finishes and is dismissed (artifact dir deleted, per
  `_get_active_agent_names`'s "dismissal deletes it" comment at line 415), the names free up. The second run succeeds.
  If the user hasn't dismissed, they get the collision error above — which is the correct outcome.

Add a small helper in `src/sase/agent/names.py` (or the new `repeat_launcher.py`):

```python
def reserve_repeat_name_base(explicit_base: str | None, count: int) -> str:
    """Reserve a repeat-name base that has no collisions at <base>.1..<base>.N.

    If *explicit_base* is provided, verify none of <explicit_base>.k is already
    claimed and raise NameCollisionError otherwise. If *explicit_base* is None,
    call get_next_auto_name() and trust its scan covers <auto>.* via the
    workflow_name-vs-name convention already in place.
    """
```

Implementation notes: the explicit-base path reads active agents (via `_get_active_agent_names()` but **not** filtered
on `workflow_name` — we need both `name` and `workflow_name` matches to catch `sase-z.2` specifically). One option is to
add `_get_active_agent_child_names()` that walks the same artifact tree and yields `data.get("name")` values — then
membership-test `f"{base}.{k}" for k in range(1, N+1)`.

### 6. Backward compatibility → **Hard cutover**

Any agent currently running with `repeat_count > 1` in its `agent_meta.json` will continue through its internal loop
until the new code lands. Agents are typically short-lived (minutes), so a hard cutover is fine:

- After the PR merges and the user's local `sase` is upgraded, **any new** agent launched with `%r:N` uses the new
  fan-out.
- **Any still-running** agent from before the upgrade keeps using the old loop (its code is loaded into memory; the
  runner doesn't re-import on each iteration).
- The TUI code is **upgraded immediately**: once the user launches `sase ace` post-upgrade, the new loader paths take
  effect. Old-style `repeat_iter_<k>.json` markers sitting in artifact directories from pre-upgrade agents **will no
  longer be surfaced as child entries** — the user will see only the parent (old-style) agent entry, with no iteration
  children. This is an acceptable regression for pre-upgrade agents; they'll disappear entirely when dismissed.

No migration script, no compat shim. Document the regression in the PR description.

### 7. `%n` aliasing within workflow YAML → **No impact**

Workflow YAML (`src/sase/xprompts/*.yml`) uses step types like `prompt_part`, `python`, `bash` — it has no `%repeat`
directive and does not reference `repeat_count`. Grep confirmed:

- `rg "repeat" src/sase/xprompts/` shows matches only in `skills/*.md` (unrelated, talks about "repeat the word back").
  No YAML workflow uses `%r`.

So this plan's changes do not touch any workflow YAML. The `n`/`N` template variables that `run_agent_exec.py:314-315`
injects today via `info.repeat_count` / `info.current_iteration` — these are **per-iteration prompt context variables**,
not workflow step inputs. They become **per-spawned-agent env vars** in Phase 2 (see below).

---

## Files to Add or Modify (full inventory, for reference across phases)

**New files**

- `src/sase/agent/repeat_launcher.py` — Phase 1. Shared fan-out helper used by both TUI launch and CLI `sase run`.
- `tests/test_repeat_launcher.py` — Phase 1. Unit tests for `reserve_repeat_name_base` and `spawn_repeat_batch`.
- `tests/test_agent_launch_repeat.py` — Phase 1. TUI-level integration smoke (monkeypatch `spawn_agent_subprocess`).

**Modified files**

- `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py` — Phases 1, 3.
- `src/sase/axe/run_agent_runner.py` — Phase 2. Strip the repeat loop + artifact writes.
- `src/sase/axe/run_agent_phases.py` — Phase 2. Plumb `n`/`N` from env vars instead of from the internal loop.
- `src/sase/axe/run_agent_exec.py` — Phase 2. Read `n`/`N` from the spawned agent's context (env vars), not from a local
  loop counter.
- `src/sase/xprompt/directives.py` — No code change expected, but verify `%r:1` stays a no-op. If `has_repeat_directive`
  is used anywhere that becomes dead code post-fan-out, prune.
- `src/sase/agent/names.py` — Phase 1. Add `reserve_repeat_name_base` + helper for child-name collisions.
- `src/sase/main/run_handler.py` (or the phase agent's grep-identified CLI entry) — Phase 1. Apply the same fan-out to
  `sase run`.
- `src/sase/ace/tui/models/_loaders/_artifact_loaders.py` — Phase 3. Delete `load_repeat_iteration_children` +
  enrichment reads.
- `src/sase/ace/tui/widgets/agent_list.py` — Phase 3. Drop `↻N/M` rendering + foldable-parent special case.
- `src/sase/ace/tui/models/agent.py` — Phase 3. Drop `repeat_count` / `repeat_iteration` fields.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` — Phase 3. Drop the "Repeat:" header line.
- `tests/test_axe_run_agent_runner_repeat.py` — Phase 4. Delete most tests (single-process repeat loop is gone);
  keep/adapt the ones that still make sense, or delete the file entirely.
- `tests/test_directives_types.py` — Phase 4. `test_repeat_*` parsing tests stay (directive parsing is unchanged).

---

## Phase 1: Launch-Time Fan-Out + Naming

**Goal.** Introduce the shared repeat-launcher module and wire it into both the TUI and CLI launch paths. When `%r:N` is
in the prompt, N independent agents get spawned (each with name `<base>.<k>` for `k in 1..N`), each with its own
timestamp, workspace, and `agent_meta.json`. The old runner loop still exists at the end of Phase 1 — it just never runs
because `_finish_agent_launch` never forwards a prompt with a live `%r` directive to the runner anymore (the launcher
strips `%r` and `%n` from the per-agent prompt and injects per-agent overrides instead).

### Context a fresh agent needs

- Read `plans/202604/repeat_directive.md` (DONE) and `plans/202604/repeat_iteration_nesting.md` (DONE) — those describe
  the feature as shipped today. Phase 1 is the first step of replacing them.
- Read `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py:298-380` (`_launch_multi_model_agents`). The new
  `_launch_repeat_agents` is a near-mirror.
- Read `src/sase/agent/names.py:401-479` to understand the `workflow_name`-vs-`name` convention and
  `_get_active_agent_names` scanning logic.
- Per `memory/short/workspaces.md`, run `just install` first.

### Changes

#### 1. `src/sase/agent/names.py` (modify)

Add two helpers below `get_next_auto_name`:

```python
class NameCollisionError(ValueError):
    """Raised when an explicit repeat-name base conflicts with existing agents."""


def _get_active_child_names(base: str) -> set[str]:
    """Return the set of active agent names starting with '<base>.'.

    Used to detect collisions like '<base>.1' already being claimed by an
    earlier agent. Walks the same artifact tree as _get_active_agent_names
    but returns names (not workflow_names) that match the <base>.<k> shape.
    """
    # Scan ~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json
    # Collect data.get("name") values matching rf"^{re.escape(base)}\.\d+$"
    # Skip dismissed suffixes, skip dead processes without done.json.


def reserve_repeat_name_base(explicit_base: str | None, count: int) -> str:
    """Return a repeat-batch base name that has N free <base>.<k> slots.

    If *explicit_base* is given, verify no <explicit_base>.k (k in 1..count)
    is currently active and raise NameCollisionError otherwise.
    If *explicit_base* is None, delegate to get_next_auto_name() — the auto
    sequence (a, b, ..., aa, ...) never collides because active agents'
    workflow_name reserves the base.
    """
```

Export both at the module level (add to `__all__` if present).

#### 2. `src/sase/agent/repeat_launcher.py` (new, ~180 lines)

```python
"""Fan out a `%r:N`-decorated prompt into N independent agents."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class RepeatAgentSpec:
    """One repeat agent's per-slot parameters."""

    name: str            # "<base>.<k>", e.g. "sase-z.3"
    iteration: int       # 1-indexed k
    total: int           # N
    prompt: str          # Prompt with %r and %n stripped


def extract_repeat_and_name(prompt: str) -> tuple[int | None, str | None, str]:
    """Return (repeat_count, explicit_base_name, prompt_without_r_or_n).

    Re-uses sase.xprompt.directives.extract_prompt_directives under the hood
    but strips the %r and (when a repeat is active) %n tokens from the prompt
    text so downstream runner code doesn't see them a second time.
    Returns (None, None, prompt) when no %r is present.
    """


def spawn_repeat_batch(
    prompt: str,
    *,
    base_spawn_fn: Callable[[RepeatAgentSpec], None],
    sleep_between: float = 1.0,
) -> list[RepeatAgentSpec]:
    """Resolve names + call *base_spawn_fn* once per slot.

    *base_spawn_fn* receives a RepeatAgentSpec and is responsible for all
    launch-site concerns (workspace claim, timestamp, env-var injection).
    Returns the specs actually spawned (for logging / UI feedback).

    Raises NameCollisionError if the explicit base name collides.
    """
```

Implementation sketch:

1. `count, explicit_base, prompt_no_directives = extract_repeat_and_name(prompt)`.
2. If `count is None` or `count <= 1`, return `[]` — caller handles the non-repeat path.
3. `base = reserve_repeat_name_base(explicit_base, count)`.
4. Build
   `specs = [RepeatAgentSpec(name=f"{base}.{k}", iteration=k, total=count, prompt=prompt_no_directives) for k in range(1, count + 1)]`.
5. For each spec, `base_spawn_fn(spec)`; `time.sleep(sleep_between)` between consecutive spawns.
6. Return `specs`.

Also add a module-level constant `REPEAT_NAME_ENV = "SASE_REPEAT_NAME"` and the `n` / `N` env var names
(`SASE_REPEAT_ITERATION`, `SASE_REPEAT_TOTAL`) — these get set by callers in Phase 2 so the runner can pick them up
without the prompt needing to carry `%r`/`%n` through a second parse.

#### 3. `src/sase/ace/tui/actions/agent_workflow/_agent_launch.py` (modify)

- Import the new module:
  `from sase.agent.repeat_launcher import spawn_repeat_batch, extract_repeat_and_name, NameCollisionError`.

- In `_finish_agent_launch` — after multi-model splitting is resolved (line 249, `if model_prompts is not None`) and
  before the single-agent launch at line 265 — add a repeat detection branch:

  ```python
  repeat_count, _, _ = extract_repeat_and_name(prompt)
  if repeat_count is not None and repeat_count > 1:
      self._launch_repeat_agents(
          prompt=raw_prompt,  # pass raw; spec.prompt strips %r/%n
          ctx=ctx,
          vcs_ref=vcs_ref,
          has_wait=has_wait,
      )
      return
  ```

- Add `_launch_repeat_agents(self, prompt, ctx, vcs_ref, has_wait)`. Structure mirrors `_launch_multi_model_agents`
  (lines 298-380):

  ```python
  def _launch_repeat_agents(self, prompt, ctx, vcs_ref, has_wait):
      def _run():
          try:
              def _spawn_one(spec):
                  timestamp = generate_timestamp()
                  workflow_name = f"ace(run)-{timestamp}"
                  ws_num, ws_dir = _allocate_workspace(ctx, has_wait)

                  # Pass %r/%n metadata via env so the runner does NOT re-loop.
                  env_overrides = {
                      "SASE_REPEAT_NAME": spec.name,
                      "SASE_REPEAT_ITERATION": str(spec.iteration),
                      "SASE_REPEAT_TOTAL": str(spec.total),
                  }
                  self._launch_background_agent(
                      cl_name=ctx.display_name,
                      project_file=ctx.project_file,
                      workspace_dir=ws_dir,
                      workspace_num=ws_num,
                      workflow_name=workflow_name,
                      prompt=spec.prompt,   # %r and %n already stripped
                      timestamp=timestamp,
                      update_target=ctx.update_target,
                      project_name=ctx.project_name,
                      history_sort_key=ctx.history_sort_key,
                      is_home_mode=ctx.is_home_mode,
                      vcs_ref=vcs_ref,
                      deferred_workspace=has_wait,
                      extra_env=env_overrides,
                  )

              specs = spawn_repeat_batch(prompt, base_spawn_fn=_spawn_one)
              self.call_later(self._load_agents)
              self.call_later(lambda: self.notify(
                  f"Started {len(specs)} repeat agent(s) for {ctx.display_name}"
              ))
          except NameCollisionError as e:
              self.call_later(lambda: self.notify(str(e), severity="error"))
          except Exception:
              log.exception("Repeat launch failed")
              self.call_later(lambda: self.notify(
                  "Repeat launch failed (see log)", severity="error"
              ))

      threading.Thread(target=_run, daemon=True).start()
      self.notify(f"Launching repeat agents for {ctx.display_name}...")
  ```

- Extract a local `_allocate_workspace(ctx, has_wait)` helper (or inline the logic from
  `_launch_multi_model_agents:335-347`). Reuse the same multi-model workspace rules verbatim — do NOT reinvent.

- Extend `_launch_background_agent` (line 530 signature) with an `extra_env: dict[str, str] | None = None` parameter.
  Forward to `spawn_agent_subprocess` — which itself may need a small signature extension. Grep `spawn_agent_subprocess`
  in `src/sase/agent/launcher.py`; if it builds a subprocess env, merge `extra_env` into that env.

- `_launch_multi_model_agents` needs the same treatment to support combined `%m(...) %r:N`: after its per-model loop
  builds `model_prompt`, call `extract_repeat_and_name(model_prompt)` and if positive, route that slot through the same
  repeat helper. Keep this minimal — can be a follow-up; note it in "Risks and Follow-ups" if deferred.

#### 4. CLI entry — grep for `sase run` dispatch

Locate (phase agent does this first; likely candidates):

- `src/sase/main/run_handler.py` — possible.
- `src/sase/axe/run_command.py` or `src/sase/axe/run.py` — also possible.
- `src/sase/main/parser_commands.py` — parser only; the actual handler is wired from there.

At the CLI entry, after prompt assembly but before the single `run_agent_runner.run(...)` call, apply the same
detection:

```python
repeat_count, _, _ = extract_repeat_and_name(prompt)
if repeat_count is not None and repeat_count > 1:
    specs = spawn_repeat_batch(
        prompt,
        base_spawn_fn=lambda spec: _spawn_cli_agent(spec, ...),
    )
    sys.exit(0)  # all spawned; individual agents own their exit codes
```

Where `_spawn_cli_agent` calls whatever the current single-agent CLI spawn is (likely `spawn_agent_subprocess` directly)
with the same `extra_env` env-var injection. Exact wiring TBD by the phase agent based on CLI code inspection.

#### 5. Tests

- `tests/test_repeat_launcher.py` (new, ~120 lines):
  - `test_extract_repeat_and_name_parses_r_and_n` — `"%r:4 %n:sase-z do X"` → `(4, "sase-z", "do X")`.
  - `test_extract_returns_none_when_no_r` — `"do X"` → `(None, None, "do X")`.
  - `test_extract_strips_bare_n` — `"%r:3 %n do X"` → `(3, None, "do X")` (bare `%n` means auto-gen).
  - `test_spawn_repeat_batch_calls_spawn_fn_N_times` — with `count=3`, assert `base_spawn_fn` called 3 times with specs
    `(name="a.1", iteration=1, total=3)`, `(name="a.2", iteration=2, total=3)`, `(name="a.3", iteration=3, total=3)`.
    Monkeypatch `reserve_repeat_name_base` to return `"a"`.
  - `test_spawn_repeat_batch_returns_empty_when_count_is_one` — `count=1` returns `[]` without calling spawn.
  - `test_reserve_repeat_name_base_explicit_no_collision` — no active agents; `reserve_repeat_name_base("sase-z", 4)`
    returns `"sase-z"`.
  - `test_reserve_repeat_name_base_explicit_collision_raises` — seed an active `agent_meta.json` with `name="sase-z.2"`
    in a fake artifacts tree; `reserve_repeat_name_base("sase-z", 4)` raises `NameCollisionError`.
  - `test_reserve_repeat_name_base_auto_delegates_to_get_next_auto_name` — monkeypatch `get_next_auto_name` to return
    `"c"`; `reserve_repeat_name_base(None, 3)` returns `"c"`.
  - `test_spawn_repeat_batch_stagger_sleep` — spy on `time.sleep`; with `sleep_between=0.01`, assert called N-1 times.

- `tests/test_agent_launch_repeat.py` (new, ~80 lines):
  - Construct an `AceApp` (or the mixin class in isolation) with monkeypatched `_launch_background_agent`; assert that a
    prompt with `%r:3 %n:foo` invokes `_launch_background_agent` three times with `extra_env` carrying the expected
    `SASE_REPEAT_*` values.
  - Assert that `%r:1` falls through to the single-agent path (no fan-out).
  - Assert that name collision surfaces via `self.notify` with `severity="error"`.

### Verification

- `just install && just check` passes from the workspace root (per `memory/short/build_and_run.md`).
- `pytest tests/test_repeat_launcher.py tests/test_agent_launch_repeat.py -v` passes.
- Manual smoke: `sase ace`, type `%r:3 %n:zz foo` and submit. Observe three top-level entries `zz.1`, `zz.2`, `zz.3` in
  the Agents tab, each with its own PID, workspace, and `agent_meta.json`. The OLD `↻N/M` parent still appears
  spuriously (Phase 3 removes that) — do NOT treat this as a regression in Phase 1 verification; call it out as
  expected.
- `rg "def _launch_repeat_agents" src/sase/` → one match.
- `rg "SASE_REPEAT_ITERATION|SASE_REPEAT_TOTAL|SASE_REPEAT_NAME" src/sase/` → matches in `repeat_launcher.py` only in
  Phase 1 (Phase 2 adds reads).
- No test that asserts `repeat_state.json` or `repeat_iter_*.json` is written by the NEW launch path. The old runner
  loop still writes them when reached, but our fan-out prevents it from being reached for new `%r:N` prompts.

---

## Phase 2: Strip Internal Loop, Move `n`/`N` to Env Vars

**Goal.** Remove the internal repeat loop from `run_agent_runner.py`. The runner now runs exactly one iteration of the
prompt, always. The `n`/`N` xprompt variables still resolve correctly per-agent — they're read from the
`SASE_REPEAT_ITERATION` / `SASE_REPEAT_TOTAL` env vars set by the Phase 1 launcher. Agents launched WITHOUT `%r` (no env
vars set) see `n`/`N` as the single-agent defaults (`n=1`, `N=1`).

### Context a fresh agent needs

- Phase 1 has landed. Repeat agents are already being spawned one-per-iteration; the runner's internal loop is now being
  entered with `repeat_count=1` (or not at all, since the launcher strips `%r` from the per-agent prompt).
- Read the current loop at `src/sase/axe/run_agent_runner.py:375-423` to understand what it does beyond iteration
  counting — anything else that lives inside the loop needs to be lifted out.
- Per `memory/short/workspaces.md`, run `just install` first.

### Changes

#### 1. `src/sase/axe/run_agent_runner.py` (modify)

- Delete the `for iteration in range(...)` loop wrapper around `run_execution_loop()` (lines ~375-423).
- Delete all `repeat_state.json` write calls and the helper that writes them (likely `_write_repeat_state` at ~lines
  49-62).
- Delete `repeat_iter_<k>.json` marker writes (lines ~65-86).
- Replace the loop with a single `run_execution_loop(...)` call — the body of one iteration.
- Preserve the fail handling: if that single run fails, the runner exits non-zero as before. No cross-iteration
  aggregation is needed.

#### 2. `src/sase/axe/run_agent_phases.py` (modify)

- `_AgentInfo.repeat_count` (line ~90ish) — remove the field entirely, OR keep it as `repeat_count: int = 1` for
  compatibility with external reads of `agent_meta.json`. **Preferred: remove it**, since Phase 3 removes the TUI
  readers.
- `extract_directives_and_write_meta()` — stop writing `repeat_count` to `agent_meta.json`. Grep for `"repeat_count"` in
  `agent_meta.json` writes (line ~136) and delete.

#### 3. `src/sase/axe/run_agent_exec.py` (modify)

At lines ~314-315 (where `n` and `N` are injected into the xprompt variable map):

```python
# Old:
xprompt_vars["n"] = str(current_iteration)
xprompt_vars["N"] = str(total_iterations)

# New:
xprompt_vars["n"] = os.environ.get("SASE_REPEAT_ITERATION", "1")
xprompt_vars["N"] = os.environ.get("SASE_REPEAT_TOTAL", "1")
```

Also propagate `SASE_REPEAT_NAME` (the `<base>.<k>` name) into `agent_meta.json` as the agent's `name`. Existing code in
Phase 1 already flows `%n` → `agent_meta.json["name"]` via `PromptDirectives.name`; with `%n` now stripped at the
launcher, we need a fallback: if `SASE_REPEAT_NAME` is in the env and no `%n:` is present in the per-agent prompt, use
`SASE_REPEAT_NAME` as the name. Thread this through `extract_directives_and_write_meta`.

Simplest approach: in `extract_directives_and_write_meta`, after directive extraction:

```python
name = directives.name  # parsed from %n in prompt
if name is None:
    name = os.environ.get("SASE_REPEAT_NAME")  # fallback for repeat agents
```

#### 4. `src/sase/agent/launcher.py` — `spawn_agent_subprocess` (modify)

Ensure `extra_env` from Phase 1 is threaded into the subprocess's `env=`:

```python
def spawn_agent_subprocess(..., extra_env: dict[str, str] | None = None):
    env = os.environ.copy()
    ...  # existing env setup
    if extra_env:
        env.update(extra_env)
    subprocess.Popen(..., env=env, ...)
```

If `spawn_agent_subprocess` already accepts an env dict, just merge; don't redesign.

#### 5. Tests

- `tests/test_axe_run_agent_runner_repeat.py` — most of these tests are obsolete. Specifically:
  - `TestWriteRepeatState` — delete; `repeat_state.json` is no longer written.
  - `TestRepeatIterationVariable` — adapt: set `SASE_REPEAT_ITERATION=3` in the test's env, invoke whatever code path
    resolves `n`, assert it returns `"3"`.
  - `TestRepeatDirectiveParsing` — move to `tests/test_repeat_launcher.py` (Phase 1), or leave in place but assert via
    the launcher API not the runner.

- Add/update a test in `tests/test_run_agent_exec.py` (or equivalent) asserting that with
  `SASE_REPEAT_ITERATION=2, SASE_REPEAT_TOTAL=5` set, the xprompt context has `n=2, N=5`; with neither set, it has
  `n=1, N=1`.

### Verification

- `just install && just check` passes.
- `pytest tests/test_axe_run_agent_runner_repeat.py tests/test_run_agent_exec.py -v` passes.
- `rg "repeat_state\.json|repeat_iter_" src/sase/` → matches ONLY in tests being deleted and in the TUI loader (which
  Phase 3 handles). `src/sase/axe/` is clean.
- `rg "for iteration in range|current_iteration.*=.*iteration" src/sase/axe/run_agent_runner.py` → no matches.
- Manual smoke from Phase 1 still works: `%r:3 %n:zz foo` spawns three agents, each writing its own
  `agent_meta.json["name"] == "zz.1" | "zz.2" | "zz.3"`. Inspect
  `cat ~/.sase/projects/<proj>/artifacts/ace-run/*/agent_meta.json` to confirm.
- No agent artifact directory contains `repeat_state.json` or `repeat_iter_*.json`.

---

## Phase 3: TUI Cleanup

**Goal.** Delete the now-dead TUI code that rendered `↻N/M` counters, synthesized iteration children, and treated repeat
parents as foldable. After this phase the Agents tab is visibly simpler — `%r:N` agents show as N plain top-level rows.

### Context a fresh agent needs

- Phases 1 + 2 have landed. No new agent produces `repeat_state.json` or `repeat_iter_*.json`. Old agents' artifacts may
  still have these files; they should be gracefully ignored (the loader we're deleting reads them — once deleted,
  they're inert).
- Read `src/sase/ace/tui/widgets/agent_list.py:373-384` (the `↻` renderer),
  `src/sase/ace/tui/models/_loaders/_artifact_loaders.py:482-581` (the child synthesizer), and
  `src/sase/ace/tui/models/agent.py` around the `repeat_count` field.
- Per `memory/short/workspaces.md`, run `just install` first.

### Changes

#### 1. `src/sase/ace/tui/models/agent.py` (modify)

- Remove `repeat_count: int | None = None` and `repeat_iteration: int | None = None` fields from the `Agent` dataclass.
- Remove any `__post_init__` or constructor plumbing that sets them.
- Grep `rg "agent\.repeat_count|agent\.repeat_iteration" src/sase/` and update/delete all call sites.

#### 2. `src/sase/ace/tui/models/_loaders/_artifact_loaders.py` (modify)

- Delete `load_repeat_iteration_children()` (lines ~482-581) entirely.
- Delete its call site (likely in `agent_loader.py` per the `repeat_iteration_nesting.md` plan —
  `rg "load_repeat_iteration_children" src/sase/`).
- In `enrich_agent_from_meta()`, remove the block that reads `repeat_count` from `agent_meta.json` and
  `repeat_state.json`.
- Remove imports of `repeat_state.json` and `repeat_iter_*.json` paths (if any constants are defined, drop them).

#### 3. `src/sase/ace/tui/models/agent_loader.py` (modify)

- Remove the repeat-children insertion from `_sort_and_reorder` (per `repeat_iteration_nesting.md` Phase 3) — the
  `agent.repeat_count is not None and agent.repeat_count > 1` branch is now dead.
- Remove any `workflow_agent_steps` augmentation that came from repeat children.

#### 4. `src/sase/ace/tui/widgets/agent_list.py` (modify)

- Delete the `↻N/M` rendering branch (lines 373-384). Grep `\\u21bb` to find any stragglers.
- Delete or simplify the `_is_foldable_parent` special-case that returns `True` for repeat parents (line 94 — check if
  it also covers workflows; keep only the workflow-parent case).
- Delete the `_compute_fold_annotation` paths (lines 436-491) that read `repeat_count` for fold-counts; leave the
  workflow-step fold logic untouched.
- Delete any `fold_counts` state related to repeat children.

#### 5. `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` (modify)

- Delete the `"Repeat:"` header line added by `repeat_directive.md` Phase 6. Grep `"Repeat:"` to find it.
- No replacement — each spawned agent has its own header panel; the `<base>.<k>` is visible in the `@<name>` suffix in
  the list view.

#### 6. Tests

- Delete tests in `tests/test_agent_list.py` (or similar) that assert `↻` rendering or fold behavior for repeat parents.
- Delete tests in `tests/test_artifact_loaders.py` (or similar) that exercise `load_repeat_iteration_children`.
- Keep tests that exercise workflow-step nesting — they use a different code path and must still pass.
- Add a small integration test: seed two `agent_meta.json` files in a tmp tree with `name="zz.1"` and `name="zz.2"` (no
  `parent_timestamp`, no `repeat_count` field); invoke the loader; assert both appear as top-level `Agent` entries with
  `parent_timestamp=None` and no synthetic parent is fabricated.

### Verification

- `just install && just check` passes.
- `pytest tests/ace/ -v` (or whatever path covers TUI tests) passes.
- `rg "repeat_count|repeat_iteration" src/sase/ace/` → no matches.
- `rg "↻|\\u21bb" src/sase/ace/` → no matches.
- `rg "load_repeat_iteration_children" src/sase/` → no matches.
- `rg "repeat_state\.json|repeat_iter_" src/sase/ace/` → no matches (the TUI no longer reads these).
- Manual smoke: run `%r:3 %n:zz foo` in `sase ace`. The Agents tab shows three top-level rows `zz.1`, `zz.2`, `zz.3`,
  each with its own status. No foldable parent, no `↻3/3` glyph, no indented children. Dismiss one (`x`) and the other
  two remain visible and independent.
- Manual smoke: workflow-step nesting unaffected. Run a standard multi-step workflow (e.g. the `#sync` workflow) and
  confirm its `[workflow]` parent + `[agent]`/`[bash]` step children still render with the usual fold behavior.

---

## Phase 4: Test Cleanup + Docs

**Goal.** Remove/adapt obsolete tests, ensure the test suite no longer references the old single-process repeat model,
and update any user-facing docs or xprompt skill descriptions that describe the old behavior.

### Context a fresh agent needs

- Phases 1-3 have landed. All code paths now treat `%r:N` as launch-time fan-out.
- Search for documentation: `rg -l "repeat.*iteration|repeat_state|↻" docs/ .sase/ memory/ src/sase/xprompts/` — any
  hits describing "iterations run in the same process" are stale.

### Changes

#### 1. `tests/test_axe_run_agent_runner_repeat.py` (modify or delete)

- Delete test classes/functions that exercise the internal loop (`TestWriteRepeatState`, `TestRepeatIterationVariable` —
  assuming Phase 2 already moved the usable piece; if not, do it here).
- If the file is now empty, delete it. Otherwise rename to reflect the new scope.

#### 2. `tests/test_directives_types.py` (modify)

- `test_repeat_*` parsing tests stay — directive parsing didn't change.
- Add one test: `test_extract_prompt_directives_preserves_repeat_for_launcher` — assert that after
  `extract_prompt_directives("%r:4 do X")`, the returned `repeat_count == 4`. (Sanity check that the launcher's
  `extract_repeat_and_name` and the parser stay in sync.)

#### 3. `memory/long/` and `.sase/memory/long-*.md` (review)

- Grep `rg "%r|%repeat|repeat_state|repeat_iter" memory/ .sase/` for any stale descriptions of the old behavior.
- Update or remove those passages. Keep them terse — the `%r` user-facing contract did NOT change, so only
  internal-architecture descriptions need updating.

#### 4. `docs/` (review)

- `rg "%r|%repeat" docs/` — update any examples that describe "iterations run sequentially in one process".
- The user-facing directive docs (`%r:N` runs the prompt N times) can stay as-is; only the implementation-detail notes
  change.

#### 5. `src/sase/xprompts/skills/*.md` (review)

- `rg "%r|%repeat|↻" src/sase/xprompts/skills/` — per `.sase/memory/long-generated-skills.md`, these are **source**
  files; edit them if they describe the old UI nesting, then run `sase init-skills --force` to regenerate the
  chezmoi-deployed `SKILL.md` files. Do NOT edit the deployed chezmoi files directly. Do NOT run `chezmoi apply` (user's
  responsibility).

#### 6. Delete any `plans/202604/repeat_*` references in CLAUDE.md / AGENTS.md if stale.

### Verification

- `just install && just check` passes.
- `pytest tests/ -v` — full suite green.
- `rg "repeat_state\.json|repeat_iter_" .` → matches only in this plan file + git history (no live code, no live tests).
- `rg "for iteration in range" src/sase/` → no matches.
- If any skill source was edited, `sase init-skills --force` runs cleanly and the diff vs prior deployed `SKILL.md`
  files is the intended edit only.

---

## Cross-Phase Constraints

- **Build gate** — per `memory/short/build_and_run.md` + `memory/short/workspaces.md`, each phase must run
  `just install && just check` before closing. If the workspace is stale, `just install` first.
- **CLI options** — per `memory/short/gotchas.md`: every sase CLI option needs both a short and long form. This plan
  adds no new CLI flags, so no action, but a reminder if the phase agent is tempted to add one.
- **Treat all runtimes uniformly** — per `memory/short/gotchas.md`: do NOT branch on Claude vs Gemini vs Codex in any
  launch path touched here. Repeat behavior is identical across runtimes.
- **Skill generation** — per `.sase/memory/long-generated-skills.md`: if `src/sase/xprompts/skills/*.md` is edited
  (Phase 4), run `sase init-skills --force` afterward. Do NOT hand-edit chezmoi files. Do NOT run `chezmoi apply` —
  that's the user's responsibility.
- **Strict phase ordering** — P1 → P2 → P3 → P4. Each phase's Verification is the handoff contract. In particular: Phase
  3's TUI deletion depends on Phase 2 having removed the writers of `repeat_state.json` / `repeat_iter_*.json`;
  otherwise live agents would write files that the TUI no longer reads (functionally harmless but confusing during
  debugging).

---

## Risks and Follow-ups

- **Behavior change: fail-fast lost.** Today a failing iteration stops the remaining ones. After this change, each
  iteration is a truly independent agent; one failing does not stop the others. This is intentional (parallel dispatch,
  no shared state to coordinate through) but is a visible behavior change. Document in the PR description. A follow-up
  could add a `%r:N-serial` alias that restores fail-fast if users complain — not planned here.

- **Workspace pressure.** N agents claim N workspaces (per `get_first_available_axe_workspace`). Today's `%r:10` used
  one workspace; the new `%r:10` claims ten. For users with few workspace slots, this can hit the workspace pool
  ceiling. The existing pool-growth logic in `plans/202604/grow_memory_pool.md` (already DONE) handles this. Mention in
  release notes.

- **Concurrent writes to a shared VCS ref.** If the repeat prompt mutates a shared CL / branch, N agents writing
  concurrently will conflict. The `%m(opus,sonnet)` multi-model precedent has the same exposure — users already know not
  to point it at a shared mutable target. Call this out in user-facing docs.

- **`has_repeat_directive` usage.** The fast-check helper added by `repeat_directive.md` Phase 1 may have callers
  elsewhere. `rg "has_repeat_directive" src/sase/` during Phase 1 to confirm. Drop it if orphaned after the runner-loop
  removal.

- **Auto-name exhaustion.** The auto-name sequence `a, b, …, z, aa, ab, …` can theoretically exhaust if the user has
  702+ live agents. Not a practical concern, and the `reserve_repeat_name_base` helper delegates to the existing
  `get_next_auto_name`, so this risk is unchanged from today.

- **Old agent artifacts in live artifact trees.** Pre-upgrade agents may leave `repeat_state.json` +
  `repeat_iter_*.json` files behind. After Phase 3 deletes the loader, those files become inert — no cleanup needed, no
  harm done. If the user wants tidy artifacts, a follow-up `sase ace --cleanup-stale-repeat-markers` could sweep them.
  Not planned here.

- **`%m(...)` + `%r:N` nesting.** Phase 1 notes a minimal hook in `_launch_multi_model_agents` to flow multi-model slots
  through `spawn_repeat_batch`. If this turns out to be fiddly (e.g. naming interactions: does
  `%m(opus,sonnet) %r:3 %n:foo` produce `foo.opus.1..foo.opus.3`, `foo.sonnet.1..foo.sonnet.3`, or something flatter?),
  split it into a follow-up plan. Safe default: in Phase 1, if both `%m` and `%r` are present, error out with "combining
  %m and %r is not yet supported" and defer to a follow-up.

- **`n` / `N` env-var leakage.** If a user runs `sase run` inside a shell where they've manually set
  `SASE_REPEAT_ITERATION`, a non-repeat agent would see `n=<leaked value>`. Mitigate by unsetting in
  `spawn_agent_subprocess` unless explicitly provided by the launcher. Add a test.

## Out of Scope

- A per-iteration `--index k` CLI flag to re-run only iteration k of a prior batch.
- Cross-agent result aggregation (e.g. "show a summary of all N agents' diffs in one pane").
- Any change to the `%m(...)` multi-model directive itself.
- A general "launch N of this prompt with these per-slot params" framework beyond `%r`. Could be built later by lifting
  the `repeat_launcher.py` module's machinery; not a goal of this plan.
- Retroactive UI for old `repeat_state.json` / `repeat_iter_*.json` artifacts from pre-upgrade runs (those agents are
  orphaned on upgrade; see backward-compat decision above).
