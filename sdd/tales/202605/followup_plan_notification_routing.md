---
name: Followup Plan Notification Routing Bug
description:
  Diagnose why /sase_plan from a Q&A-resumed agent never produces a visible plan notification, then fix the
  env-var/timestamp mismatch that breaks routing.
---

## Problem

When an agent asks a question via `/sase_questions`, the user answers it, and the agent resumes — the resumed agent's
`/sase_plan` call appears to do nothing. No "PLAN" badge appears on the agent row in `sase ace`, and the plan-approval
modal/popup that normally shows up after a successful `/sase_plan` never arrives.

The issue is reproducible in the user's current `sase ace` snapshot: agent `@gc.2` (the followup of `@gc` after the
first question round) is sitting in QUESTION state, having just asked a _second_ question. The original prompt asks the
agent to "create a sase plan to activate/work that epic", so we'd expect the agent to eventually emit a plan — but no
`PlanApproval` notification has been observed despite multiple Q&A rounds.

Initial plan-mode flows (e.g. `@f9.plan`, `@f8.plan` in the same snapshot, both ending in `PLAN DONE`) do work
correctly. The bug is specific to plan submissions made from a _followup_ iteration of the agent runner's exec loop —
i.e. from any iteration that happens _after_ a Q&A or feedback round.

## Root-cause hypothesis (high confidence)

**The followup agent's artifacts-directory timestamp diverges from the launch-time `SASE_AGENT_TIMESTAMP` env var, and
notification routing keys off the env var.**

Concretely:

1. The agent runner is launched once. The Rust core (`sase-core/crates/sase_core/src/agent_launch/mod.rs:1128-1131`)
   sets `SASE_AGENT_TIMESTAMP=<original launch timestamp T1>` in the runner subprocess env. This value is never updated
   for the lifetime of the runner.

2. When a Q&A round completes, `handle_questions_marker` (`src/sase/axe/run_agent_exec_plan.py:601-617`) calls
   `create_followup_artifacts`, which mints a **new** timestamped artifacts directory `T2` via
   `create_artifacts_directory("ace-run", ...)` (`src/sase/axe/run_agent_helpers.py:357`). The followup agent's
   prompt_step markers, agent_meta, workflow_state, and `done.json` are all written under `T2`.

3. The TUI workflow-step loader (`src/sase/ace/tui/models/_loaders/_workflow_step_loaders.py:124`) constructs the
   `Agent` row for the followup with `raw_suffix=timestamp_dir.name` — i.e. `T2`. So the visible row representing the
   followup phase is keyed on `T2`.

4. When the followup calls `sase plan`, control returns to the runner, which invokes `handle_plan_approval`
   (`src/sase/llm_provider/_plan_utils.py:108-182`). At line 170 it reads
   `agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")` — still `T1` — and passes it into `notify_plan_approval`
   as `action_data["agent_timestamp"]`.

5. In the TUI, `_apply_status_overrides` (`src/sase/ace/tui/actions/agents/_notifications.py:147-176`) tries to find the
   matching agent row to flip its status badge to "PLANNING":

   ```python
   agent_timestamp = notification.action_data.get("agent_timestamp")  # T1
   ...
   if agent_timestamp and agent.raw_suffix != agent_timestamp:  # T1 != T2
       continue
   ```

   **No agent matches**, so no PLANNING override is applied. The same comparison is used for routing `UserQuestion`
   overrides on followups (so any Q&A round after the first will silently fail to badge the right row, too — explaining
   the 🛑 stuck-looking @gc.2 in the snapshot).

6. The notification is appended to the inbox (the inbox count `✉ 13` is consistent with this), but it is orphaned from
   the agent it belongs to — so the modal/popup that normally pops up scoped to that agent never arrives, and the
   agent's status badge does not advance. From the user's perspective, "/sase_plan does nothing."

The same `SASE_AGENT_TIMESTAMP` is also read by `notify_user_question` (`src/sase/axe/run_agent_helpers.py:473`), which
means _every_ question round after the first inherits the same bug (only the very first question, raised from the
original artifacts dir `T1`, has a routable timestamp).

### Why it works on the _first_ `/sase_plan`

The first iteration of the loop runs against the original artifacts dir `T1`. The notification carries `T1`, and the
agent row's `raw_suffix` is also `T1` — they match, the override fires, the badge appears, the modal pops. As soon as
the loop swaps to a followup dir, the env-var-vs-row-timestamp invariant breaks.

### Why it isn't a missing-skill problem

`/sase_plan` is delivered via `~/.claude/skills/sase_plan/SKILL.md`, loaded automatically by Claude Code from the
user-level skills directory. Claude subprocesses are spawned with default env inheritance (`subprocess.Popen` in
`src/sase/llm_provider/claude.py:246-252`, no `env=` override), so the followup agent has the skill _and_
`SASE_AGENT`/`SASE_ARTIFACTS_DIR`/`SASE_AGENT_TIMESTAMP` available. The followup agent can and does call `sase plan`;
the bug is purely in how the resulting notification is routed back to the visible row.

## Verification plan (do these _before_ writing any fix)

The hypothesis is well-supported by the code, but worth confirming directly before changing anything:

1. **Inbox spelunking.** Look at `~/.sase/notifications/<recent>/*.json` (or wherever `append_notification` lands —
   inspect `senders.py` `append_notification`) for `action: "PlanApproval"` entries. If a PlanApproval notification is
   sitting unread with `action_data.agent_timestamp` matching the _original_ launch timestamp (the parent `@gc`'s
   timestamp, not `@gc.2`'s), the hypothesis is confirmed.

2. **Followup artifacts cross-check.** For an in-progress followup like `@gc.2`, verify the artifacts directory
   timestamp differs from `SASE_AGENT_TIMESTAMP` of the runner. The runner PID is in the followup dir's
   `agent_meta.json["pid"]`; reading `/proc/<pid>/environ` will show `SASE_AGENT_TIMESTAMP`.

3. **Question-override sanity check.** If the second-question QUESTION badge on @gc.2 in the snapshot is actually coming
   from agent*meta `role_suffix=".q"` rather than the override, that tells us the override path is _also* silently
   broken for that round (and it just happens that the badge surfaces another way). Scan `_workflow_step_loaders.py` and
   `agent.py` for fallback status sources.

## Fix design

Three plausible fixes; the first is the smallest and most surgical and is probably the right one.

### Option A (recommended): re-publish `SASE_AGENT_TIMESTAMP` per loop iteration

In `run_execution_loop` (`src/sase/axe/run_agent_exec.py:548-551`), alongside the existing
`os.environ["SASE_ARTIFACTS_DIR"] = state.current_artifacts_dir`, also set `os.environ["SASE_AGENT_TIMESTAMP"]` to the
followup directory's timestamp (derived from `state.current_artifacts_dir` via `os.path.basename` and normalized with
`convert_timestamp_to_artifacts_format` / `normalize_to_14_digit` to match `raw_suffix` exactly).

This makes every `notify_*` call from the followup carry the _current_ phase's timestamp, which the TUI loaders already
use as `raw_suffix`. The override matching just works.

Trade-off: anything else relying on `SASE_AGENT_TIMESTAMP` to identify the _whole agent run_ (rather than the current
phase) will see the value change mid-run. Audit those callers — only a handful exist:

- `src/sase/scripts/sase_commit_stop_hook.py:291` — uses it as a session/dedup key. Phase-specific is fine (or arguably
  _better_, since each followup phase is its own commit session).
- `src/sase/workflows/commit/checkpoint.py:48` — same pattern, same conclusion.
- `src/sase/llm_provider/_plan_utils.py:170` and `src/sase/axe/run_agent_helpers.py:473` — exactly the call sites this
  fix targets.
- Tests under `tests/test_sibling_commit_stop_hook.py` and `tests/test_commit_workflow_checkpoint.py` — adjust to cover
  the new invariant if needed.

### Option B: bypass the env var, pass the timestamp explicitly

In `handle_plan_marker` and `handle_questions_marker`, call `notify_plan_approval` / `notify_user_question` with an
explicit `agent_timestamp` derived from `state.current_artifacts_dir`. Drop the env var read in `_plan_utils.py` and
`run_agent_helpers.py` (or fall back to it only when no explicit value is given). More changes, but more obviously local
to the routing problem.

### Option C: relax the matcher in `_apply_status_overrides`

Make the TUI accept any agent in the _same workflow chain_ (matched by `cl_name` + `parent_workflow` /
`parent_timestamp`) when an exact `raw_suffix` match fails. Lossy and will mis-route if the user has multiple parallel
chains for the same `cl_name`. Not recommended.

### Recommended path

Option A. The whole rest of the codebase already treats "phase timestamp == artifacts dir timestamp" as the identity, so
making `SASE_AGENT_TIMESTAMP` follow that invariant is the cheapest correct change.

## Implementation outline (Option A)

1. **Add a helper.** In `src/sase/axe/run_agent_exec.py`, factor out a `_publish_phase_env(artifacts_dir: str)` helper
   that sets both `SASE_ARTIFACTS_DIR` and `SASE_AGENT_TIMESTAMP` (the latter derived from the basename of
   `artifacts_dir`, normalized so it matches what the TUI loaders see in `raw_suffix`). Use it on line ~550 in place of
   the bare `os.environ["SASE_ARTIFACTS_DIR"] = ...`.

2. **Restore on finalize.** In `_finalize_loop`, ensure `SASE_AGENT_TIMESTAMP` is _not_ leaked back to a stale value —
   the existing `os.environ.pop("SASE_ARTIFACTS_DIR", None)` block (line 212) is the right place to also reset / pop
   `SASE_AGENT_TIMESTAMP` if we mutated it. Alternatively, snapshot the original value at runner startup and restore on
   finalize. Pick whichever keeps the smallest blast radius for `commit_stop_hook` / `checkpoint.py` callers.

3. **Audit callers of `SASE_AGENT_TIMESTAMP`.** Walk every reader (`_plan_utils.py:170`, `run_agent_helpers.py:473`,
   `sase_commit_stop_hook.py:291`, `checkpoint.py:48`) and confirm phase-scoped semantics are fine. Add a one-line
   comment at each call site documenting "this is the current phase's timestamp" so future readers don't get surprised.

4. **Tests.** Add a unit test in `tests/` that:
   - Drives `run_execution_loop` through a Q&A → followup transition with a fake workflow that emits a
     `.sase_plan_pending` marker on the second iteration.
   - Asserts that the `notify_plan_approval` call (mock or stub) receives an `agent_timestamp` equal to the followup
     artifacts dir's basename timestamp, _not_ the original launch timestamp.
   - Optionally, assert `SASE_AGENT_TIMESTAMP` env after `_finalize_loop` is back to the original value (or unset,
     depending on policy chosen in step 2).

5. **TUI integration sanity test.** A focused test that constructs an Agent with `raw_suffix=T2` and a PlanApproval
   notification with `action_data.agent_timestamp=T2`, then runs `_apply_status_overrides` and asserts the agent's
   status flips to PLANNING. (And the symmetric test for UserQuestion → QUESTION.)

6. **Manual verification.** After landing the change, reproduce the original scenario: spawn an agent that asks a
   question, answer it, watch the followup call `/sase_plan`, and confirm the PLANNING badge and approval modal both
   appear within a refresh cycle.

## Out of scope

- Re-architecting the followup as a fresh detached child process (similar to spawn-on-retry). The current loop is fine;
  the routing bug is independent of how the followup is hosted.
- Changing the `followup_prompt-*.md` artifact handling. It is correctly written and already used as the basis of
  `state.current_prompt`; nothing about the prompt content is implicated.
- Reworking the workspace claim / `running.json` to track followup phases. The TUI loads followup rows from
  `prompt_step_*.json` markers in their own artifacts dirs — the claim metadata is not load-bearing for this bug.

## Risks

- **Mutating `SASE_AGENT_TIMESTAMP` mid-run** can affect commit-hook dedup keys. Mitigation: phase-scoped session keys
  are arguably correct anyway (each followup phase is its own logical commit attempt). Verify with the commit_stop_hook
  tests after the change.
- **Inheritance into Claude subprocesses.** Each subprocess gets a fresh env snapshot at `Popen` time, so the updated
  value will propagate naturally. No extra wiring needed.
- **Backwards compatibility with already-running agents.** Any agent currently mid-run was launched with the old
  semantics; the fix only takes effect for newly launched runs. Old in-flight followups will continue to route
  notifications to the original timestamp — acceptable (they were already broken).
