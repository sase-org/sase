---
create_time: 2026-05-29 08:34:43
status: done
prompt: sdd/prompts/202605/muted_notification_tab.md
---
# Plan: Add a Muted tab to the notification modal

## Goal

Add a top-level `Muted` tab to the ACE notification modal so muted notifications are grouped in one quiet backlog tab.
The modal should continue to render flat, newest-first rows inside the active tab, with no section headers.

## Current behavior

The current modal taxonomy is owned by `src/sase/ace/tui/modals/notification_modal_tags.py`:

- `PlanApproval`, `UserQuestion`, and `HITL` actions go to the synthetic `HITL` tab.
- `is_error(notification)` rows go to the synthetic `Errors` tab.
- Other rows use stored notification tags.
- Untagged rows go to `General`.

Rows are rendered by `src/sase/ace/tui/modals/notification_modal_options.py` as a flat list for the active tab, sorted
by `timestamp_sort_key(...), reverse=True`.

Muted state already exists on `Notification.muted`, is persisted through `mark_muted`, is counted separately by the
notification snapshot/count code, and is rendered with dim styling plus the `~ ` prefix. Snoozed notifications are also
muted rows (`muted=True` plus `snooze_until`).

One important current test, `tests/test_notification_modal_sections.py::test_muted_hitl_notification_stays_in_hitl_tab`,
explicitly says muted state is styling rather than tab taxonomy. This request should replace that contract.

## Proposed product contract

Muted state becomes tab taxonomy:

- Any `notification.muted` row belongs to `Muted`.
- `Muted` has higher precedence than `HITL`, `Errors`, stored tags, and `General`.
- A muted plan/question/HITL row appears in `Muted`, not `HITL`.
- A muted error row appears in `Muted`, not `Errors`.
- A muted tagged row appears in `Muted`, not its stored tag tab.
- A snoozed row appears in `Muted` because snooze is implemented as muted-with-a-timer.

This restores the old "mute dominates classification" mental model from the sectioned modal and keeps active tabs
aligned with the indicator counts: high-attention tabs show active unmuted work, while muted work is isolated.

## Tab key and ordering

Add a synthetic muted tab key in `notification_modal_tags.py`, e.g. `MUTED_TAB_KEY`.

Recommended internal representation:

- Use a reserved internal key such as `"__muted__"` for the new synthetic tab rather than the literal stored tag
  `"muted"`.
- Label it as `Muted` through `_SYNTHETIC_TAB_LABELS`.
- This avoids accidentally treating a non-muted notification tagged `muted` as part of the synthetic muted backlog.

Keep existing `HITL` and `Errors` keys unchanged to avoid broad churn.

Recommended display order:

1. `HITL`
2. `Errors`
3. `General`
4. `Done`
5. Remaining stored tags alphabetically by displayed label
6. `Muted`

Rationale: muted rows are intentionally quiet and should not precede active unread work. If muted rows are the only rows
present, `Muted` is naturally the initial tab because it is the only tab.

## Code changes

1. Update tab classification in `notification_modal_tags.py`.
   - Add `MUTED_TAB_KEY` and a `Muted` synthetic label.
   - Make `_notification_modal_tab_keys()` return `[MUTED_TAB_KEY]` before checking action, error, tags, or `General`
     when `notification.muted` is true.
   - Add `MUTED_TAB_KEY` to the build order as a pinned synthetic tab placed last.

2. Preserve flat row rendering in `notification_modal_options.py`.
   - No new sectioning or rendering path is needed.
   - Existing `notification_matches_tag_tab()` filtering should pick up the muted classification automatically.
   - Existing dim styling, snooze badge, mark state, file counts, action badges, and tag badges should remain unchanged.

3. Make mute/unmute rebuild behavior intentional in `notification_modal_actions.py` and `notification_modal.py`.
   - Muting a row from an active non-muted tab will usually move it out of that tab.
   - Unmuting a row from `Muted` will move it back to `HITL`, `Errors`, a stored tag tab, or `General`.
   - Capture `previous_tabs` and the current visual-order replacement before toggling.
   - After the classification change, keep the current tab if it still has rows and highlight the next/previous visible
     row in that tab.
   - If the current tab becomes empty, choose a sensible fallback tab and highlight its first visible row. For a one-row
     modal, this naturally switches to the row's new tab.
   - Clear stale marks or pending dismiss confirmations only if the action switches tabs; ordinary mute/unmute should
     not unexpectedly clear unrelated modal state.

4. Keep notification store and provider code unchanged.
   - The modal already receives unread muted rows from `_read_unread_notification_page_from_provider()`.
   - Counts already maintain a separate muted bucket.
   - This change is presentation-layer taxonomy only, so it stays in the Python TUI layer and does not cross the Rust
     core boundary.

## Tests

Update focused modal tests:

- Replace `test_muted_hitl_notification_stays_in_hitl_tab` with coverage that a muted HITL row appears only in `Muted`.
- Add a muted error case proving muted rows do not populate `Errors`.
- Add a muted tagged case proving muted rows do not populate stored tag tabs or `General`.
- Add a snoozed case proving snoozed rows appear in `Muted` and retain the snooze badge.
- Add ordering coverage for mixed tabs: `HITL`, `Errors`, `General`, `Done`, remaining tags, `Muted`.
- Add a collision guard if using a reserved key: a non-muted notification tagged `muted` should produce a normal stored
  tag tab, while an actually muted notification should produce the synthetic `Muted` tab.
- Update active-tab option tests so `Muted` renders rows newest-first, like every other tab.
- Update mute action tests so toggling mute moves the row into or out of the `Muted` tab and rebuilds with a sensible
  highlight.
- Update dismiss/bulk/jump tests only where expected visual order changes because muted rows no longer remain in the
  original active tab.

Likely files:

- `tests/test_notification_modal_sections.py`
- `tests/test_notification_modal_mute_snooze.py`
- `tests/test_notification_modal_dismiss_actions.py`
- `tests/test_notification_modal_mark_and_tabs.py`
- `tests/test_notification_modal_jump.py` only if jump expectations include muted rows in non-muted tabs

## Verification

Run focused tests first:

```bash
.venv/bin/python -m pytest \
  tests/test_notification_modal_sections.py \
  tests/test_notification_modal_mute_snooze.py \
  tests/test_notification_modal_dismiss_actions.py \
  tests/test_notification_modal_mark_and_tabs.py \
  tests/test_notification_modal_jump.py
```

Then run the repository-required checks after implementation file changes:

```bash
just install
just check
```

If `uv run pytest ...` still rejects the local lockfile, use the project venv pytest path after `just install`, matching
the prior notification-tabs implementation.

## Risks and decisions to confirm during implementation

- The most visible behavior change is that pressing `M` on a row can make it leave the current tab. The implementation
  should treat this like a dismiss-style triage action and keep the cursor on the nearest remaining row when possible.
- If a user expects muted rows to remain visible in `HITL` or `Errors`, this plan intentionally does not do that. The
  reason is consistency with muted counts and the older mute-dominates section taxonomy.
- The reserved synthetic tab key prevents a real stored tag named `muted` from being conflated with muted state. If the
  existing tab key namespace is expected to stay human-readable, this can be implemented with the literal `"muted"`
  instead, but that is less precise.
