---
create_time: 2026-06-30 07:21:02
status: done
prompt: sdd/prompts/202606/dismiss_unread_agent_dismisses_notification.md
---
# Dismiss the completion notification when an unread agent is dismissed

## Problem / Motivation

The `sase ace` Agents tab maintains a **one-to-one contract** between a completed agent row and its completion
notification: a terminal-status row is "unread" iff its matching completion notification (`sender="user-agent"`,
`action` in `JumpToAgent`/`ViewErrorReport`) is still active (not dismissed). This contract is enforced on the _read_
side — when the user acknowledges/reads a row, `_clear_agent_unread_and_dismiss_notification()` synchronously:

1. discards the row's identity from `_unread_completed_agent_ids`,
2. dismisses the matching completion notification on disk (`dismiss_agent_completion_notifications_matching_agents`),
3. surgically removes it from the in-memory snapshot cache (`_remove_agent_completion_notifications_from_cache`), and
4. refreshes the notification indicator badge.

The **dismiss** side does _not_ honor this contract uniformly. When the user _dismisses_ an unread completed agent, the
corresponding completion notification can be left dangling in the notification panel / indicator badge. There are two
distinct defects:

1. **Marked-group "save and dismiss" never dismisses notifications (functional bug).** The `m` (mark) + `s` (save group)
   flow calls `_persist_marked_agent_group_save()`, which saves bundles, the saved-group archive, and the
   dismissed-agents set, but **never** dismisses the members' completion notifications. The agent disappears from the
   Agents tab while its completion notification stays active in the panel and keeps incrementing the indicator badge.

2. **No dismiss path updates the live unread set / notification cache synchronously (consistency + UX bug).** The
   single-`x`, bulk ("dismiss all done"), and kill paths _do_ dismiss the notification on disk — the Rust cleanup
   planner emits `notification_dismiss_candidates`, executed by `persist_cleanup_side_effect_intents()`. But that work
   runs in a background persistence worker and only triggers an **async** indicator recount
   (`refresh_notifications=True` → `_refresh_notification_count_async`). Unlike the read path, these dismiss paths never
   clear `_unread_completed_agent_ids` for the dismissed identities nor surgically update the cached notification
   snapshot. The panel/badge therefore lag (and, on the daemon notification provider, the cached snapshot can stay
   stale), so the dismissed agent's notification appears to linger.

### Goal

Every way of dismissing an agent from the Agents tab — single `x`, bulk "dismiss all done", and marked-group "save and
dismiss" — must dismiss the agent's matching **completion** notification, both on disk and in the live panel/indicator,
immediately and consistently. This makes the dismiss side symmetric with the already-correct read side.

## Relevant Code

- `src/sase/ace/tui/actions/agents/_unread.py`
  - `AgentUnreadMixin._clear_agent_unread_and_dismiss_notification()` — the read-side reference behavior to mirror.
  - `AgentUnreadMixin._remove_agent_completion_notifications_from_cache()` — surgical in-memory cache + indicator update
    keyed on completion-notification matching.
- `src/sase/ace/tui/actions/agents/_dismissing.py`
  - `_dismiss_planned_agent()` (single `x`), `_do_dismiss_all()` (bulk), `_persist_single_dismiss_transaction()`,
    `_persist_bulk_dismiss_transaction()`.
- `src/sase/ace/tui/actions/agents/_marking.py`
  - `_save_marked_agent_group()` (in-memory) and the module-level `_persist_marked_agent_group_save()` (disk) — the path
    missing notification dismissal entirely.
- `src/sase/ace/tui/actions/agents/_dismiss_persistence.py`
  - `persist_cleanup_side_effect_intents()` — already dismisses notifications for single/bulk/kill via Rust
    `notification_dismiss_candidates`.
  - `agents_related_to_dismissal()` — primary agent + workflow-child steps.
- `src/sase/ace/tui/actions/agents/_killing_utils.py`
  - `dismiss_notifications_for_agents()` — thin wrapper over the Rust-backed `dismiss_notifications_matching_agents`
    store API.
- `src/sase/ace/tui/actions/agents/_notification_polling.py`
  - `_refresh_notification_count()` / `_refresh_notification_count_async()` — the async recount the dismiss paths
    currently rely on.
- Rust core: `crates/sase_core/src/agent_cleanup/planner.rs` (`add_notification_candidate`, `build_side_effects`) —
  already emits notification dismiss intents for dismiss/kill items. No change expected here.
- Tests: `tests/ace/tui/test_agents_tab_completion_dismiss_e2e.py` — drives the real Rust-backed notification store;
  currently covers reading a row and dismissing a _notification_, but **not** dismissing an _agent_.

## Approach

### 1. Add a shared "dismiss notifications for dismissed agents" helper

Introduce one helper (on `AgentUnreadMixin`, alongside the existing read-side helpers, so all dismiss mixins can reach
it via the composed `AceApp`) that, given the set of agents being dismissed, synchronously brings the
unread/notification UI into the post-dismiss state — mirroring `_clear_agent_unread_and_dismiss_notification()` but for
the dismiss direction and for a batch:

- discard each agent identity from `_unread_completed_agent_ids` and `_manual_unread_agent_ids`;
- dismiss the matching **completion** notifications on disk via `dismiss_agent_completion_notifications_matching_agents`
  (completion-only, to avoid nuking still-actionable `PlanApproval`/`UserQuestion` notifications — important because
  marked-group members are revivable);
- call `_remove_agent_completion_notifications_from_cache(agents)` to drop them from the cached snapshot and update
  `_last_unread_ids`;
- refresh the indicator count once.

Make it idempotent and defensive (the dismiss persistence may also dismiss on disk; a second completion-only dismiss is
a no-op) and guard optional attributes with `getattr` so the lightweight test apps in the suite keep working.

### 2. Invoke the helper from every in-memory dismissal entry point

Call the new helper (after `_apply_dismissal_in_memory(...)`) from:

- `_dismiss_planned_agent()` — single `x`,
- `_do_dismiss_all()` — bulk "dismiss all done",
- `_save_marked_agent_group()` — marked-group save.

Pass the **full related-agent set** (primary + workflow children) so workflow parents clear their children's
notifications too. Reuse `agents_related_to_dismissal()` (single) and the existing related-set accumulation (bulk) to
compute it; the marked-group candidates already include children.

This guarantees the panel/badge reflect the dismissal immediately instead of waiting on the async background recount,
and it closes the daemon-provider stale-cache gap.

### 3. Close the marked-group disk-side gap

In `_persist_marked_agent_group_save()`, dismiss the members' completion notifications on disk (e.g. via
`dismiss_agent_completion_notifications_matching_agents` over the saved agents), so the on-disk store matches the
in-memory update from step 2 and survives a restart / cross-session reload. Keep `refresh_notifications=True` on the
resulting `CleanupTaskOutcome`.

### 4. Verify (no change expected) single/bulk/kill disk behavior

Confirm that single/bulk/kill continue to dismiss notifications on disk through the Rust cleanup intents. No Rust change
is anticipated — `planner.rs` already pushes `notification_dismiss_candidates` for every dismiss/kill item. If
verification shows a gap, prefer fixing it in the Rust planner/binding rather than re-implementing matching in Python.

## Rust Core Boundary

The _decision and execution_ of notification dismissal is already core/back-end behavior: the Rust cleanup planner owns
the "dismissing an agent dismisses its notification" intent (`notification_dismiss_candidates`), and the notification
store mutation is the Rust-backed `dismiss_notifications_matching_agents` /
`dismiss_agent_completion_notifications_matching_agents` API. This plan does **not** re-implement any of that in Python:

- The marked-group fix (step 3) calls the existing Rust-backed store API from one additional Python call site (the
  marked-group flow intentionally bypasses the cleanup planner because it builds a revivable `SavedAgentGroupWire`, not
  a cleanup plan).
- Everything in steps 1–2 — `_unread_completed_agent_ids`, the in-memory notification snapshot cache, and the indicator
  badge — is presentation-only Textual state that rightly lives in this repo.

No Rust wire/API change is expected. If step 4 surfaces a real planner gap, that fix belongs in `../sase-core`.

## Testing

Extend `tests/ace/tui/test_agents_tab_completion_dismiss_e2e.py` (real Rust-backed store) with dismiss-side contract
tests symmetric to the existing read-side ones:

- Dismissing a single unread DONE agent dismisses exactly that agent's completion notification, clears exactly its
  unread id, and leaves unrelated completion and non-completion (`PlanApproval`/`UserQuestion`) notifications untouched.
- Bulk "dismiss all done" dismisses every selected agent's completion notification and clears their unread ids.
- Marked-group "save and dismiss" dismisses the members' completion notifications while preserving still-actionable
  interactive notifications (so a revive isn't crippled).
- `raw_suffix` disambiguation: dismissing one of two same-`cl_name` runs dismisses only that run's notification.
- A workflow parent dismissal clears its children's completion notifications.

Add focused unit coverage for the new helper (idempotency; respects `_manual_unread` guard semantics consistently with
the read path) and for `_persist_marked_agent_group_save()` now issuing the completion-notification dismissal.

Run `just check` (after `just install`) plus the visual snapshot suite if any indicator/panel rendering is affected.

## Risks / Considerations

- **Completion-only vs. all-matching.** Use completion-only dismissal on the new code paths (matches the read path and
  the cache helper, and protects interactive `PlanApproval`/`UserQuestion` notifications for revivable saved groups).
  Note the pre-existing single/bulk/kill paths dismiss _all_ matching notifications via the Rust intent; narrowing those
  to completion-only is **out of scope** unless desired, but the discrepancy should be called out in review.
- **Idempotency / double dismissal.** The in-memory helper (step 2) and the background persistence both dismiss on disk;
  ensure the second is a harmless no-op and the indicator recount is not double-counted.
- **Manual-unread guard.** The read path skips clearing when an identity is in `_manual_unread_agent_ids`. For an
  explicit _dismiss_ action, the agent is leaving the panel, so the dismissed identity should be removed from the
  manual-unread set too (decide and document this; it differs from the read path's "leave manually-unread rows alone"
  behavior).
- **Revive symmetry.** Reviving a saved/dismissed agent already re-projects unread state from active completion
  notifications on the next reconcile; since we dismiss only the completion notification (not interactive ones), revive
  behavior is unaffected. Worth a smoke check.
