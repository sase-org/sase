---
name: pending_question_marker
description: Show QUESTION status for agents currently blocked on an unanswered user
  question, decoupled from notification state.
type: ace_tui
create_time: 2026-05-11 11:30:27
status: done
prompt: sdd/prompts/202605/pending_question_marker.md
---

# Pending Question Marker → QUESTION Status (Decouple From Notifications)

## Problem

In the Agents tab, several currently-claimed agents (e.g. `fa.3.2.q`, `gc.q`, `jo.q`) show as **RUNNING** even though
their Python process is blocked inside `handle_questions_flow()` waiting for a user response to a question they
submitted. They should show as **QUESTION**.

### Root cause

Today, the TUI has exactly two ways to set `status = "QUESTION"`:

1. **Notification poll** — `_apply_notification_status_overrides()` in
   `src/sase/ace/tui/actions/agents/_notifications.py` scans **unread, non-dismissed** `UserQuestion` notifications and
   sets a runtime override keyed by `(cl_name, raw_suffix)`.
2. **Workflow-relationship override** — `apply_status_overrides()` in
   `src/sase/ace/tui/models/_agent_status_overrides.py` (lines 251–262) flips a _DONE_ agent to `QUESTION` if it has
   `questions_times` and no `.q` follow-up child.

Both paths break for the case at hand:

- The agent is still **RUNNING** (PID alive, workspace claim held) so path 2 never fires.
- The matching `UserQuestion` notification has been **dismissed** in the store. Snapshot reads use
  `include_dismissed=False`, so the override never fires either, and the agent stays at the loader's default `RUNNING`.

I confirmed this on the live store: `~/.sase/notifications/notifications.jsonl` contains `dismissed=true` UserQuestion
rows for `260510_111904`, `260510_132253`, and `20260511104750` — exactly the three RUNNING `.q` workspace claims in
`~/.sase/projects/sase/sase.gp`. Dismissals happen legitimately (the response-submit path calls `mark_dismissed` after
the user answers; cleanup paths dismiss when killing/dismissing agents) so we cannot "just stop dismissing." The
dismissal is correct policy; **the bug is that QUESTION status is sourced from the notification at all.**

`questions_submitted_at` in `agent_meta.json` is also not a reliable signal — it's a historical timestamp that stays set
after the question has been answered and the agent has moved on.

### Why this matters

- The Agents tab is the user's main "where is each agent right now?" surface. An agent blocked on user input is
  indistinguishable from an actively executing one, so the user can't tell at a glance who is waiting on them.
- This bug is now permanent in steady state: every `.q` follow-up that itself asks another question will end up
  RUNNING-but-blocked once the previous notification is dismissed by any unrelated code path.

## Goal

A currently-running agent that is **blocked waiting for a user response to a question** must show `QUESTION` in the
Agents tab regardless of the notification's dismissed/read state.

When the agent receives a response (or is killed), the status must revert to RUNNING (or terminal status) on the very
next poll tick.

## Design overview

Introduce a **filesystem marker** that lives only for the duration of the blocking poll loop — the same pattern the
codebase already uses for `WAITING` status (`waiting.json` set/cleared by the workflow runner; observed by the TUI
loader). The marker is the agent's own "I am paused on a question" signal, so TUI status no longer depends on
notification state.

Concretely:

1. **Producer** — In `run_agent_exec_plan.py`'s question step (around `handle_questions_flow()`), write
   `pending_question.json` to the agent's `artifacts_dir` _before_ entering the poll loop, and delete it on every exit
   path (response received, killed, exception).
2. **Consumer** — In `_meta_enrichment.py`, add a check right alongside the existing `waiting.json` block: if
   `pending_question.json` exists and the agent is still `RUNNING`, set `agent.status = "QUESTION"`.
3. **Wire path** — Mirror the new field on `RunningMarkerWire` / `AgentArtifactRecordWire` so the snapshot-based loader
   sees the same signal (parity with how `waiting.json` is surfaced through the wire today).

Notification-driven `_apply_notification_status_overrides()` is **kept**. It still serves the case where an agent
submitted a question, the process exited (or hadn't yet written the marker on first paint), and an unread notification
exists. Treating the two signals as additive — either one flips the status — gives us correct behavior under all
observed orderings without removing existing infrastructure.

### Marker content

The file's contents are _not_ read by the TUI today; the existence check is sufficient. We still write a small JSON
payload to make the file self-documenting and to leave room for future TUI use (e.g. surfacing the session_id so the
"press <enter> on agent → open question modal" shortcut can work even when the notification is dismissed):

```json
{
  "session_id": "<question session id>",
  "request_path": "<absolute path to question_request.json>",
  "submitted_at": "<ISO-8601 UTC>"
}
```

## Phases

### Phase 1 — Filesystem marker producer

- `src/sase/axe/run_agent_helpers.py` (`handle_questions_flow` / its poll loop, or `run_agent_exec_plan.py` at the
  question step site, whichever controls the response-wait window): write `pending_question.json` to the agent's
  artifacts dir immediately _before_ the wait loop starts; delete it on every loop exit path (response received,
  `was_killed()`, `JSONDecodeError`/`OSError` exhaust, exception). Use a `try/finally` around the wait loop to guarantee
  cleanup.
- New tests under `tests/axe/` (or wherever question-flow tests live): marker is created before the poll begins, deleted
  on response, deleted on kill.

### Phase 2 — TUI consumer

- `src/sase/ace/tui/models/_loaders/_meta_enrichment.py`:
  - In `enrich_agent_from_meta()`, after the `waiting.json` block, add:
    `if (Path(artifacts_dir) / "pending_question.json").exists()    and agent.status == "RUNNING": agent.status = "QUESTION"`.
  - Same treatment in `enrich_agent_from_meta_wire()` using the new wire field (Phase 3).
- New unit tests for both enrichment functions: marker present + `RUNNING` → `QUESTION`; marker present +
  `DONE`/`FAILED` → unchanged; marker absent → unchanged.

### Phase 3 — Rust scanner + wire parity

- `../sase-core/crates/sase_core/src/agent_scan/scanner.rs` and `wire.rs`: add a `pending_question` boolean to
  `AgentArtifactRecordWire` (or to `RunningMarkerWire`, mirroring the field that carries `waiting.json` today). Set it
  by stat'ing `pending_question.json` next to the existing scan.
- Regenerate Python bindings via the usual flow, then surface the new field to `_running_loaders.py` so home-mode and
  project-mode agents both benefit.
- Tests on the Rust side (alongside existing scanner tests): marker present is surfaced; absent is not.

### Phase 4 — Footer / "jump to notification" affordance

- `src/sase/ace/tui/actions/agents/_notifications.py:_jump_to_agent_notification` short-circuits when the _agent's_
  status is `QUESTION` and there's no matching unread notification (the dismissed case). Fall back to reading the
  request file directly from the marker payload and opening the `UserQuestionModal` so the "go to current agent's
  question" keybind keeps working in the dismissed-notification scenario.
- Per `src/sase/ace/AGENTS.md`, the footer condition list and the `?` help popup may need re-verification — verify the
  conditional binding still appears correctly when the agent is in `QUESTION` state.

### Phase 5 — Regression sweep + cleanup

- Delete any obsolete dismissed-but-still-blocked notification rows in tests that previously relied on the broken
  behavior.
- Manual TUI walkthrough: launch a question-asking agent, dismiss the notification before responding (e.g. via the
  notification modal `x` binding), confirm the agent row flips RUNNING → QUESTION via the marker. Respond; confirm it
  flips back.
- `just check` must pass; `just pyvision` must report no unused symbols.
- Close the epic bead and stamp the plan-file frontmatter `status: done`.

## Out of scope

- Rewriting the existing notification-driven QUESTION override. It stays as a redundant signal — additive, not
  replacement.
- Persisting QUESTION across TUI restarts independently of the marker. The marker is filesystem state; it already
  survives restarts naturally.
- Changing dismissal policy. Dismissing a UserQuestion notification remains legitimate; this plan just stops making it
  the _only_ signal for QUESTION.

## Risk / unknowns

- Rust ↔ Python wire parity is the most invasive piece (Phase 3). If the schedule is tight, Phase 3 can be deferred —
  Phase 1+2 alone fix the filesystem-scan loader path, which is what the affected workspace claims use today. Snapshot
  loader users will lag until Phase 3 lands.
- The `pending_question.json` cleanup path needs to be bullet-proof under process crashes; otherwise stale markers will
  keep DONE/FAILED agents flagged as QUESTION on next TUI restart. Two mitigations: (a) the consumer only applies the
  override when `agent.status == "RUNNING"`, which already excludes terminal rows, and (b) load-time stale-marker
  cleanup analogous to `running.json`'s `is_process_running()` sweep in `_running_loaders.py`.
