---
create_time: 2026-05-21 16:08:15
status: wip
prompt: sdd/prompts/202605/coder_visible_after_plan_approval.md
---
# Plan: Show plan‑chain coder agent without requiring tier‑2 refresh

## Problem

When the user approves a plan from the `sase ace` TUI with `run_coder=True`, the planner agent spawns a child coder
agent (via `create_followup_artifacts` in `src/sase/axe/run_agent_exec_plan.py`). The coder writes `agent_meta.json` and
`workflow_state.json` on disk, but it does **not** appear in the Agents tab until the user manually presses `,y`
(`full_history_refresh`, a tier‑2 full filesystem scan).

Today every other "agent is born" code path nudges the TUI via `_schedule_agents_async_refresh()` _and_ keeps the SQLite
artifact index in sync via `update_agent_artifact_index_for_marker_mutation()`. The plan→coder hand‑off skips both, so a
tier‑1 index query never returns the coder until the next `,y`.

## Goal

Make the plan‑chain coder visible automatically — without a manual full‑history refresh — using the same primitives
already used elsewhere:

1. **Update the tier‑1 SQLite artifact index** when the coder's artifacts dir is created, so a normal tier‑1 query picks
   it up.
2. **Signal the TUI** that a child agent is expected soon, so it polls the tier‑1 index over a short window after
   approval — analogous to the existing `_poll_starting_agent_transitions` poller that watches
   `STARTING → RUNNING/WAITING` transitions.

## Why two prongs (not just one)

Updating the index alone isn't enough because of timing:

- The TUI modal calls `_schedule_agents_async_refresh()` _immediately_ on approval (already wired at
  `_notification_modals.py:450`).
- The planner agent process, in its own runtime, then has to wake up, read `plan_response.json`, and call
  `create_followup_artifacts(...)`. That work is asynchronous and routinely lands **after** the modal's debounced
  refresh has already fired (default debounce is ~150 ms).
- Once the planner finally writes the coder's index row, nothing prompts the TUI to re-query unless an inotify event
  fires for that exact path (not guaranteed across platforms / mount types) or the user touches a refresh keymap.

The "expected child" poll closes that race the same way `_poll_starting_agent_transitions` closes the
`STARTING → RUNNING` race: a bounded, low‑cost stat poll on a per‑second tick.

## Scope

In scope:

- The plan‑chain coder hand‑off in `src/sase/axe/run_agent_exec_plan.py` (the runtime side, inside the planner process).
- The TUI plan‑approval modal in `src/sase/ace/tui/actions/agents/_notification_modals.py` and the refresh/polling
  machinery in `src/sase/ace/tui/actions/agents/_loading_refresh.py` and `src/sase/ace/tui/actions/_event_activity.py`.
- The same hand‑off for `tale`, `epic`, `legend` approvals, which also go through `create_followup_artifacts` and have
  the same bug.

Out of scope:

- Reworking the artifact‑index schema or query API.
- Replacing the existing STARTING poller — we extend the existing tick‑based polling, we don't fork it.
- Any change to how plan approval semantics are computed (`run_coder`, `commit_plan`, etc.).
- Inotify watcher reliability fixes — the poll is the belt‑and‑suspenders.

## Design

### Prong A — Runtime: keep the tier‑1 index in sync at child‑agent birth

In `src/sase/axe/run_agent_exec_plan.py`, immediately after each `create_followup_artifacts(...)` call that materializes
a child agent (currently around two sites — the standard `run_coder` branch near line 466 and the epic/legend branch
near line 386), call:

```python
update_agent_artifact_index_for_marker_mutation(state.current_artifacts_dir)
```

This mirrors the pattern already used in `run_agent_runner_setup.py:110`, `run_agent_markers.py`, and
`run_agent_exec_markers.py`. The child row lands in `~/.sase/agent_artifact_index.db` with the same fields any other
`STARTING` agent would have, so tier‑1 queries return it.

If `create_followup_artifacts` itself is the more natural home for this write (it is the function that knows the child
artifacts dir was just created and writes both `agent_meta.json` and `workflow_state.json`), consider moving the call
inside that helper so every caller — not just the plan‑chain path — gets index‑sync for free. The implementing agent
should make that judgement call during implementation; either site is correct, but centralizing inside the helper is the
more defensive choice provided no caller relies on the index _not_ being written.

### Prong B — TUI: "expected child" signal + bounded poll

Goal: after the modal closes with an action that we know will spawn a child agent, register the parent agent's identity
in an `_expected_child_agents` set, and have the existing per‑second tick poller check for the child's appearance.

#### B.1 — Register the expectation at approval time

In `_notification_modals.py::handle_plan_approval`, after the response file is written and the status override is
applied (around lines 186–198), if `_build_plan_approval_response(result)` indicates a child will be spawned —
`run_coder=True`, or action in `("tale", "epic", "legend")` — add the parent agent's identity to a new app‑level set:

```python
app._expected_child_agents[agent.identity] = ExpectedChildAgent(
    parent_identity=agent.identity,
    expected_after=time.monotonic(),
    deadline=time.monotonic() + EXPECTED_CHILD_WATCH_SECONDS,
    reason="plan_approval",
)
```

The set is initialized in `_state_init.py` next to `_starting_poll_meta_cache`. `EXPECTED_CHILD_WATCH_SECONDS` is a
small constant (default ~30s). The poller will evict entries past their deadline or once the child is seen.

#### B.2 — Extend the per‑second tick to poll for expected children

`_poll_starting_agent_transitions()` already runs every second from the countdown tick (`_event_activity.py:60`). Add a
sibling `_poll_expected_child_agents()` that, for each entry in `_expected_child_agents`:

1. Looks up the parent's artifacts dir from the in‑memory agents list.
2. Computes the expected child artifacts dir using the same `plan_chain_*` / `tale_chain_*` / `epic_chain_*` /
   `legend_chain_*` suffix logic the runtime uses (factor a small helper out of `create_followup_artifacts` so both
   sides agree on the path shape — or, simpler, scan the parent's sibling artifacts for a fresh child dir created after
   `expected_after`).
3. If a candidate child dir with `agent_meta.json` exists, call `request_agents_refresh("expected_child")` (the same
   debounced primitive `_poll_starting_agent_transitions` uses) and evict the entry.
4. If `time.monotonic() > deadline`, evict the entry (give up — the user can still `,y` if something went wrong).

We can prefer "scan parent's sibling artifacts created after `expected_after`" because it doesn't require the TUI to
predict the exact child name and is robust to suffix scheme changes. The cost is one `os.scandir` per expected parent
per second; with normally ≤1 outstanding expectation, this is negligible.

#### B.3 — Eviction on natural success

If the agents list refresh picks up the child for any reason (inotify, unrelated refresh, the index update from Prong A
landing in time), drop the parent from `_expected_child_agents` so the poll doesn't keep working after the child is
already visible.

### Naming

- App state attr: `_expected_child_agents` (mirrors `_starting_poll_meta_cache`).
- Poll method: `_poll_expected_child_agents()` (mirrors `_poll_starting_agent_transitions`).
- Refresh reason string: `"expected_child"` (mirrors `"starting_poll"`).

## Why this matches existing patterns

| Existing                                                                                                                                        | New                                                                                                                                      |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `update_agent_artifact_index_for_marker_mutation` after `agent_meta.json` is written in `run_agent_runner_setup.py:110`                         | Same call after `create_followup_artifacts()` in `run_agent_exec_plan.py`                                                                |
| `_poll_starting_agent_transitions` polls `agent_meta.json` mtime for known STARTING agents and nudges `request_agents_refresh("starting_poll")` | `_poll_expected_child_agents` scans parent sibling artifacts for an expected child and nudges `request_agents_refresh("expected_child")` |
| `_starting_poll_meta_cache` dict on app                                                                                                         | `_expected_child_agents` dict on app                                                                                                     |
| Modal already calls `_schedule_agents_async_refresh()` at line 450                                                                              | Unchanged — Prong B is the _follow‑up_ poll over the next few seconds                                                                    |

No new IPC, no new file format, no new schema.

## Files expected to change

- `src/sase/axe/run_agent_exec_plan.py` — call `update_agent_artifact_index_for_marker_mutation` after each
  `create_followup_artifacts` site (or push the call inside `create_followup_artifacts` in `run_agent_helpers.py`).
- `src/sase/ace/tui/actions/_state_init.py` — initialize `_expected_child_agents` dict.
- `src/sase/ace/tui/actions/agents/_notification_modals.py` — register expectation when the approval response will spawn
  a child.
- `src/sase/ace/tui/actions/agents/_loading_refresh.py` — add `_poll_expected_child_agents()` alongside
  `_poll_starting_agent_transitions()`.
- `src/sase/ace/tui/actions/_event_activity.py` — call the new poller from the per‑second tick (next to the existing
  STARTING poll call at line 60).

## Risk and edge cases

- **Suffix scheme drift**: predicting the exact child artifacts dir name couples the TUI to runtime naming. Mitigation:
  use the "fresh sibling artifacts dir created after `expected_after`" approach so the TUI doesn't need to know the
  suffix.
- **Approval that doesn't spawn a child**: `commit_plan=True, run_coder=False` does _not_ spawn a coder. The expectation
  must be conditioned on `_build_plan_approval_response(result)` actually indicating a child spawn (run_coder=True or
  action in tale/epic/legend), to avoid permanent stat thrash.
- **Reject path**: also doesn't spawn a child — skip.
- **Multiple rapid approvals**: the dict keys on parent identity, so a second approval for the same parent overwrites
  the first entry; this is fine.
- **Long planner wake‑up**: the 30s watch window should comfortably cover realistic planner reaction times. If a planner
  takes longer than that, the existing inotify watcher or the next user interaction will still refresh — we just lose
  the "instant" property in the extreme tail.
- **Prong A side effects**: `update_agent_artifact_index_for_marker_mutation` is already best‑effort and idempotent, so
  adding more callers is safe.

## Verification

1. Type checks: `just check`.
2. Manual smoke test in the TUI:
   - Launch a planner agent; let it reach a PLAN state.
   - Approve the plan with `run_coder=True` from the modal.
   - Confirm the new coder agent appears in the Agents tab within a few seconds **without** pressing `,y`.
   - Repeat with `commit_plan=True, run_coder=False` and confirm we do _not_ register an expectation (no permanent
     poll).
   - Repeat with the tale / epic / legend actions.
3. Unit‑test coverage:
   - A test that hits the runtime path and asserts a new row appears in the artifact index after
     `create_followup_artifacts` is called for a coder spawn.
   - A test that registers an expected child on the app and walks the poller once with a fake artifacts dir present,
     asserting `request_agents_refresh("expected_child")` fires and the entry is evicted.
   - A test asserting an expired expectation is dropped after the deadline.

## Not doing (deliberately)

- No new keymap, no new config knob — this should "just work."
- No change to the tier‑2 `,y` semantics; it remains the manual escape hatch.
- No refactor of `create_followup_artifacts` callers beyond the index‑sync call; everything else is structurally
  unchanged.
