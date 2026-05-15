---
create_time: 2026-05-15 13:49:50
status: done
prompt: sdd/prompts/202605/ace_p0_responsiveness.md
bead_id: sase-3q
tier: epic
---
# ACE P0 Responsiveness Fixes Plan

## Context

This plan implements the P0 recommendations from `sdd/research/202605/ace_profile_20260515_131509_responsiveness.md`.

The profile showed that the latest `sase ace --profile` capture is no longer dominated by one-shot startup rebuilds. The
remaining P0 regressions are short, repeated, user-visible stalls on the Textual event loop:

- `_ring_tmux_bell()` runs a blocking `subprocess.run()` from the auto-refresh notification poll path.
- `AgentInfoPanel` rebuilds and lays out the full Rich `Text` every second because countdown is part of the exact-state
  cache key and `Static.update()` defaults to `layout=True`.
- Successful prompt submit unmounts the prompt bar through the cancel safety path, synchronously writing the submitted
  prompt as `cancelled=True` before the existing worker launch path writes the final non-cancelled history entry.

Each phase below is intended to be owned by a distinct agent instance. Phases are ordered so that independent low-risk
blockers land first, then the cross-cutting countdown optimization, then an integration verification pass.

## Guardrails

- Do not modify `.sase/memory` or `memory/` files without explicit approval.
- Keep behavior uniform across agent runtimes; none of these fixes should add runtime-specific logic.
- TUI presentation and event-loop scheduling changes stay in this repo. If any phase unexpectedly needs shared
  backend/domain behavior, move that behavior to `../sase-core/crates/sase_core` and call it through `sase_core_rs`.
- Run `just install` before validation in this ephemeral workspace if it has not already been refreshed recently.
- After code changes, run the narrow tests listed for the phase, then `just check` before final handoff.

## Phase 1: Make the tmux bell non-blocking

Owner scope:

- `src/sase/ace/tui/actions/agents/_notification_polling.py`
- Notification polling tests, primarily `tests/test_notification_toast_polling.py` and helpers in
  `tests/_notification_toasts_helpers.py`

Implementation:

- Replace the synchronous `_ring_tmux_bell()` call from `_poll_agent_completions()` with a non-blocking dispatch.
- Prefer a small async wrapper such as `_ring_tmux_bell_async()` that uses `asyncio.to_thread(self._ring_tmux_bell)` and
  is scheduled/awaited in a way that does not delay notification indicator updates or toast emission.
- Keep `_ring_tmux_bell()` as the synchronous leaf that contains the tmux subprocess invocation. This keeps existing
  fake apps/tests simple and gives later tests a clear boundary to patch.
- Decide deliberately whether bell failures should be logged or ignored. Match current behavior for `FileNotFoundError`;
  do not let bell failures break notification polling.

Tests:

- Add a regression test that patches `_ring_tmux_bell` to block on a worker thread and verifies
  `_poll_agent_completions()` still advances the event loop.
- Keep existing notification toast behavior tests passing: new notifications and expired snoozes still request exactly
  one bell per poll.
- Add a guard that `subprocess.run` is not invoked directly on the event-loop thread through
  `_poll_agent_completions()`. A monkeypatch around the sync leaf is enough; avoid sleeping tests unless needed to prove
  loop responsiveness.

Acceptance criteria:

- `_poll_agent_completions()` no longer waits on `Popen.communicate` from `_ring_tmux_bell`.
- Notification indicator counts, unread reconciliation, toast grouping, muted notification behavior, and expired-snooze
  behavior are unchanged.

## Phase 2: Avoid cancelled prompt-history writes on successful submit

Owner scope:

- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_mount.py`
- `src/sase/ace/tui/actions/agent_workflow/_launch_start.py`
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_submit.py` only if needed for call-site clarity
- Launch/prompt tests, especially `tests/ace/tui/test_agent_launch_non_blocking.py`,
  `tests/ace/tui/test_post_launch_jk_lag.py`, and helper harnesses under `tests/ace/tui/_agent_launch_helpers.py`

Implementation:

- Split prompt-bar unmount into two explicit paths:
  - cancel/dismiss path: preserve the current safety-net behavior and save non-trivial text as `cancelled=True`;
  - successful-submit path: transfer focus and detach the bar without calling `_save_bar_text_as_cancelled()`.
- Update `_finish_agent_launch(prompt)` to use the successful-submit unmount path after it has accepted the prompt and
  reserved the launch timestamp.
- Leave the final non-cancelled history write in the existing launch worker path. Do not introduce independent
  unsynchronized background prompt-history writes in this phase.
- Preserve empty prompt handling and actual cancel handling. Those paths should still unmount through the cancelled
  safety net where applicable.
- Preserve focus-transfer behavior before the synchronous detach, because this is part of the existing post-submit j/k
  responsiveness fix.

Tests:

- Add a unit test that successful `_finish_agent_launch("real prompt")` does not call `_save_bar_text_as_cancelled()` or
  `add_or_update_prompt(..., cancelled=True)`.
- Add/adjust tests that actual prompt cancellation and replacing an open prompt bar still save non-trivial text as
  cancelled.
- Keep the existing non-blocking launch tests asserting that `_finish_agent_launch` schedules
  `_run_agent_launch_body_async` via `call_later` and does not run the body inline.

Acceptance criteria:

- `_save_prompt_history` no longer appears under `on_prompt_input_bar_submitted` for successful launches.
- Cancelled/dismissed prompt text is still protected against silent loss.
- The prompt bar still disappears immediately and focus returns to the active list widget.

## Phase 3: Gate AgentInfoPanel countdown render/layout churn

Owner scope:

- `src/sase/ace/tui/widgets/agent_info_panel.py`
- `src/sase/ace/tui/actions/agents/_display_detail.py`
- `src/sase/ace/tui/actions/_event_activity.py` only if call-site routing needs a countdown-only branch
- Tests in `tests/ace/tui/widgets/test_agent_info_panel.py`, `tests/ace/tui/test_agent_panel_index_integration.py`, and
  startup/loading indicator tests

Implementation:

- Separate stable panel state from countdown state. Stable state should include position, total/visible counts, status
  metrics, loading, view mode, grouping mode, search query, and keymap registry. Countdown should not invalidate the
  stable state cache.
- Add a countdown-only update path on `AgentInfoPanel`, for example `update_countdown_only(countdown, interval)`, that
  returns early when the rendered countdown text is unchanged.
- Ensure panel updates that cannot change height call `self.update(text, layout=False)` when Textual supports that
  keyword. If compatibility is a concern, wrap this in a local helper that falls back to `self.update(text)`.
- Avoid rebuilding the panel on every agents-tab tick when only the countdown changed. The lowest-risk approach is to
  keep the countdown visible but make `_update_agents_info_panel_impl()` and/or `AgentInfoPanel.update_state()` route
  countdown-only changes through the cheaper repaint path.
- Keep loading behavior unchanged: `Agents: ...` should still short-circuit other badges and metrics.
- Do not change AgentList runtime row patching in this phase. It is P1 in the research doc and should be left for a
  separate follow-up.

Tests:

- Add a test that repeated countdown-only updates do not rebuild stable panel content or request layout. This can patch
  `AgentInfoPanel.update` and assert the `layout=False` keyword on countdown-only refreshes.
- Add a test that changing metrics/search/grouping/view mode still rebuilds the panel and preserves current display
  text.
- Keep existing Rich style tests for metric counts and labels passing.
- If a call-site split is added, add a focused fake-app test proving `_on_countdown_tick()` on the agents tab uses the
  countdown-only path when no agent metrics changed.

Acceptance criteria:

- Pure countdown ticks no longer bypass the exact-state guard by forcing a full Rich `Text` rebuild.
- `Static.update(layout=True)` is not used for one-line countdown-only changes.
- Existing text output and style semantics are preserved except for any intentionally documented countdown cadence
  change.

## Phase 4: Integration verification and profile follow-up

Owner scope:

- No feature ownership unless prior phases reveal small integration defects.
- Test/profiling orchestration and documentation updates under `sdd/research` if a new profile artifact is produced.

Implementation:

- Rebase or merge the three phase branches in order: Phase 1, Phase 2, Phase 3.
- Resolve conflicts conservatively. Phase 1 should not overlap with Phase 2/3; Phase 2 and Phase 3 should also be
  disjoint except for shared app tests.
- Run targeted tests first:
  - `pytest tests/test_notification_toast_polling.py`
  - `pytest tests/ace/tui/test_agent_launch_non_blocking.py tests/ace/tui/test_post_launch_jk_lag.py`
  - `pytest tests/ace/tui/widgets/test_agent_info_panel.py tests/ace/tui/test_startup_loading_indicators.py`
- Run `just check`.
- If practical in the environment, rerun `sase ace --profile` with a comparable interaction session and compare against
  `sdd/research/202605/ace_profile_20260515_131509_responsiveness.md`.

Acceptance criteria:

- The combined change passes `just check`.
- The profile no longer shows:
  - `Popen.communicate` under `_ring_tmux_bell` in the UI-thread tree;
  - `_save_prompt_history` under `on_prompt_input_bar_submitted` for successful submit;
  - recurrent `AgentInfoPanel.update` / `Static.update(layout=True)` work on countdown-only ticks.
- Any remaining visible responsiveness costs are documented as P1/P2 follow-up, not mixed into this P0 work.

## Risks and sequencing notes

- Phase 2 is correctness-sensitive because prompt-history writes are serialized by file locks and existing semantics
  intentionally avoid downgrading non-cancelled entries. Avoid background write queues unless a later plan handles
  ordering explicitly.
- Phase 3 is Textual-version-sensitive because `Static.update(layout=False)` is the key optimization. Use a tiny
  compatibility helper if tests or type checks show the installed Textual signature differs.
- Do not bundle P1 fixes into these phases. In particular, xprompt hint debouncing, file-panel diff key caching, AXE
  ChangeSpec parsing, AgentList cache invalidation, and lazy syntax cache scope are valuable but should be separate
  follow-up work after P0 is stable.
