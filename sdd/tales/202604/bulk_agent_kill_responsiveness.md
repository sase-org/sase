---
create_time: 2026-04-24 16:31:09
status: done
prompt: sdd/prompts/202604/bulk_agent_kill_responsiveness.md
---
# Plan: Make Bulk Agent Kill Immediate in the Agents Tab

## Problem

Launching is now responsive because expensive list reload and detail rendering work happens after the immediate UI
update. Bulk killing marked agents still lags because the marked-agent path calls the single-agent kill path once per
selected agent:

- Each agent runs `_do_kill_agent()`.
- `_do_kill_agent()` rebuilds panel indices and refreshes the Agents list.
- It dismisses notifications synchronously per agent, which can repeatedly load and write notification state.
- It schedules one persistence task per killed agent.
- After the loop, `_bulk_kill_marked_agents()` clears marks and refreshes again.

That means killing `N` marked agents produces roughly `N + 1` UI refreshes and several repeated synchronous side
effects. The fix should make bulk kill behave like one optimistic transaction: signal processes, remove all affected
rows from memory, refresh once, then persist everything in the background.

## Goals

- Return control to the TUI immediately after confirming a marked-agent bulk kill.
- Remove killed/dismissed rows from the Agents tab in one list update.
- Preserve existing behavior for single-agent kill, dismiss, workflow parent/child cleanup, pinned agents, status
  overrides, and notification count refresh.
- Keep post-kill disk/project-file persistence asynchronous.
- Add regression tests that fail if bulk kill reintroduces per-agent display refreshes or synchronous persistence work.

## Non-Goals

- Do not redesign the Agents tab layout or keymaps.
- Do not change confirmation modal behavior.
- Do not change the persisted file formats for dismissed agents, workflow bundles, notifications, hooks, mentors,
  comments, or RUNNING fields.
- Do not make all single-agent dismissal paths asynchronous in this pass, except where shared helpers are needed for
  bulk kill.

## Proposed Implementation

### 1. Split kill classification and immediate state mutation into reusable helpers

In `src/sase/ace/tui/actions/agents/_killing.py`, extract the non-UI pieces of `_do_kill_agent()` so single and bulk
paths can share them:

- `_classify_kill_kind(agent) -> KillKind | None`
  - Contains the existing workflow/hook/mentor/CRS/running classification logic.
  - Keeps the same unknown-agent error behavior for single-agent kill.

- `_collect_immediate_kill_identities(agent) -> set[AgentIdentity]`
  - Returns the killed agent identity.
  - For a workflow parent, also returns child-step identities matching `parent_timestamp` and `parent_workflow`.

- `_apply_killed_agents_in_memory(agents, identities)`
  - Adds identities to `_dismissed_agents`.
  - Clears `_agent_status_overrides` and `_agent_pre_question_status`.
  - Removes all matching identities from `_agents` and `_agents_with_children`.
  - Rebuilds panel indices once.
  - Clamps `current_idx` against the active list/panel once.

Then rewrite `_do_kill_agent()` to use these helpers but preserve its current single-agent behavior: one process signal,
one notification, one deferred-detail display refresh, one async persistence call.

### 2. Add a true batched kill path for marked agents

In `src/sase/ace/tui/actions/agents/_marking.py` or `_killing.py`, add a bulk method owned by the kill mixin, for
example:

`_do_bulk_kill_agents(killable: list[Agent], dismissable: list[Agent]) -> None`

The confirmed marked-agent callback should call this method instead of looping over `_do_kill_agent()`.

The bulk method should:

- Snapshot live marked agents once, using identities to skip duplicates caused by workflow parent/child cascades.
- Classify killable agents once.
- Send `SIGTERM` to each killable PID synchronously, because `os.killpg` is a fast syscall and gives immediate
  permission/error feedback.
- Skip only agents whose process-group kill fails.
- Emit a single summary notification such as `Killed 6 agents` rather than one toast per process.
- Apply all in-memory removals in one batch.
- Clear `_marked_agents` before the display refresh so stale mark glyphs never render.
- Refresh notification count once, and defer this if notification dismissal moves fully into the worker.
- Run one `_refresh_agents_display(list_changed=True, defer_detail=True)` on the Agents tab.
- Schedule one background persistence task for all successfully killed agents.

### 3. Batch background persistence

Add an async method such as `_run_bulk_kill_persistence_async(kill_items)` where each item contains:

- the agent
- its `KillKind`
- any snapshot needed for workflow children

The worker side should:

- Persist each kill side effect using existing `_persist_kill_side_effects()`.
- Save dismissed agents once at the end with a snapshot that includes all identities removed by the immediate stage.
- Dismiss notifications in a batched form, avoiding repeated `load_notifications()` calls per agent.
- Schedule one final async agent refresh when finished.

To keep this scoped, the existing per-agent `_run_kill_persistence_async()` can remain for single kills, but the shared
worker helpers should avoid duplicating logic.

### 4. Move notification dismissal out of the bulk critical path

The current `_do_kill_agent()` calls `dismiss_notifications_for_agent(agent)` synchronously. For bulk kill, avoid
calling this per agent before the UI returns.

Add a batch utility in `_killing_utils.py`, for example:

`dismiss_notifications_for_agents(agents: Iterable[Agent]) -> int`

It should load notifications once, match against a set of `(cl_name, raw_suffix)` style keys, and mark matching
notifications dismissed. The bulk persistence worker should call this helper. Single-agent kill can keep the existing
synchronous call for now, or switch to the batch helper in the existing async persistence stage if tests show that is
safe.

### 5. Keep dismissable marked agents from blocking the bulk kill path

The marked-agent action may include done/no-PID agents. `_do_dismiss_all()` is currently synchronous and performs
filesystem cleanup. To keep mixed marked sets responsive:

- For the first implementation, call `_do_dismiss_all()` only after the kill batch UI update if dismissable count is
  small enough, but this still risks lag.
- Preferred: add a lightweight batched dismiss path mirroring kill:
  - Immediate in-memory removal via `_apply_dismissal_in_memory()` or a new helper.
  - Background artifact deletion, bundle saves, workspace release, notification dismissal, and
    `save_dismissed_agents()`.

This should be included if the test surface is manageable, because users marking many agents may naturally include
completed rows.

### 6. Tests

Add focused tests in `tests/ace/tui/test_agent_marking.py` and/or `tests/test_agent_kill.py`:

- Bulk kill confirmation calls a batched kill method instead of `_do_kill_agent()` once per agent.
- Bulk kill removes all killed agents from `_agents` and `_agents_with_children` before async persistence runs.
- Bulk kill performs exactly one display refresh with `list_changed=True, defer_detail=True`.
- Bulk kill schedules exactly one persistence task for multiple agents.
- Workflow parent bulk kill removes matching child steps in the same immediate batch.
- Failed `os.killpg` for one PID leaves that agent visible while successful kills are removed.
- Mixed killable/dismissable marked agents clear marks and refresh once.

Update fake app test method signatures where `_refresh_agents_display()` now expects `defer_detail`.

### 7. Verification

Run targeted checks first:

```bash
uv run pytest -q tests/ace/tui/test_agent_marking.py tests/test_agent_kill.py tests/ace/tui/test_agents_refresh_coalescing.py tests/ace/tui/test_agent_display_defer_detail.py
uv run ruff check src/sase/ace/tui/actions/agents/_killing.py src/sase/ace/tui/actions/agents/_marking.py src/sase/ace/tui/actions/agents/_killing_utils.py tests/ace/tui/test_agent_marking.py tests/test_agent_kill.py
```

Because this repo memory requires it after changes, run:

```bash
just install
just check
```

## Expected Result

After confirming bulk kill, the modal should disappear and `j`/`k` navigation should be available immediately. The
marked rows should vanish in one UI update, with detail rendering deferred. Disk cleanup, project-file status updates,
notification dismissal, and final disk reload should complete in the background without causing refresh storms.
