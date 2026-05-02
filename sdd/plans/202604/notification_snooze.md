---
create_time: 2026-04-25 23:09:49
status: done
prompt: sdd/prompts/202604/notification_snooze.md
---
# Plan: Snooze Notifications from the Notification Panel

## Problem

The notification panel today has two "quiet it down" tools, and they're both blunt:

- **Mute (`m`)** — silence forever. Great when you've decided you don't care, but it requires a follow-up unmute later
  if you _do_ want to come back to it. People forget. The notification stays dim in the panel and the user loses the
  signal entirely.
- **Dismiss (`x`)** — throw it away. Nothing comes back.

What's missing is the middle option that everybody actually wants: _"shut up about this for an hour, then remind me."_
That's snooze. Mute already taught us how to quiet a row — snooze adds a timer that puts the row back into the unread
pool when it expires, with an audible ping so the user is _actually_ reminded rather than having to remember to look at
the panel.

The previous mute plan (`plans/202604/notification_mute_1.md`) explicitly listed _"Persisted snooze-until muting that
auto-unmutes after a duration"_ as out-of-scope future work. This is that work.

## Goals

1. **Mute with a deadline.** Snoozing a row is functionally identical to muting it _until_ a chosen time — no new
   indicator behavior, no new panel filtering rules, just a mute that knows when to expire.
2. **Single keystroke to start, single keystroke to pick a duration.** From the panel, `s` opens a quick picker and each
   preset is a one-key choice. The whole interaction is one→two keystrokes for the common case.
3. **Reliable expiry — even across restarts.** A notification snoozed at 14:00 for 1h re-surfaces at 15:00 whether or
   not the TUI was running the whole time. No background daemons, no clock drift fragility.
4. **Audible re-surface.** When a snooze expires the user gets the same tmux bell ring they'd get for a fresh unread
   arrival — they don't have to be staring at the indicator to know.
5. **Visually quiet, but legible.** A snoozed row reads as _muted, with a clock_ — not as a third unrelated state.
6. **Visible time-remaining.** The user can glance at the panel and see _how long_ until each snoozed row comes back, so
   they can reconfirm or change their mind.

## Non-Goals (v1)

- **Bulk snooze** ("snooze all unread for an hour"). Easy to add later if the keybinding is well-chosen now.
- **Per-sender snooze rules** ("always snooze fix-hook notifications for 30m"). Separate feature, separate config.
- **Absolute-time snooze** ("until 9am tomorrow", "until Monday"). v1 uses relative durations only via the existing
  `parse_duration` helper — that covers ~95% of cases without expanding the parser surface. Absolute times can layer on
  cleanly later (custom input becomes "duration _or_ time").
- **CLI entry point** (`sase notification snooze <id> --for 1h`). The TUI is the only surface for v1, matching how mute
  shipped.
- **Cross-machine snooze sync.** The notification store is local; snooze inherits that scope.
- **A separate snooze-only indicator badge.** Snoozed counts toward `muted` in the indicator. When the snooze fires, it
  moves into the unread (gold) count organically.

## Mental Model

The trick is that snooze is _not_ a third orthogonal flag. It's mute, plus an expiry timestamp. This keeps the design
small:

| `muted` | `snooze_until` | Meaning              | In panel? | In unread count? | Notes                                   |
| ------- | -------------- | -------------------- | --------- | ---------------- | --------------------------------------- |
| `False` | `None`         | Normal               | shown     | counts           | Default                                 |
| `True`  | `None`         | Permanently muted    | shown     | excluded         | Today's `m` keybinding                  |
| `True`  | `<ts>`         | **Snoozed**          | shown     | excluded         | Auto-unmutes at `ts`, rings bell        |
| `False` | `<ts>`         | _(invariant: never)_ | —         | —                | If we see this, treat as expired-snooze |

The expiry job's job is exactly one thing: walk the list, find rows where `snooze_until <= now`, and flip them to
`(muted=False, snooze_until=None)`. Everything else — what muted means, how the indicator renders, how rows are styled —
is unchanged from today's mute behavior. The indicator already moves a row from gold to muted-dim when the user mutes
it; we get the reverse motion (muted-dim → gold) for free at expiry.

This framing also dictates the "unmute on snoozed" answer cleanly: pressing `m` on a snoozed row sets `muted=False` and
`snooze_until=None` together. Snooze isn't a separate state to remember — it's just mute with a timer, so unmuting
cancels the timer.

## Design

### Duration picker modal

The picker is the only piece of new UI. It has to be _fast_ — the user has already pressed `s` to start, so we don't
want them stopping to type. Layout (centered, narrow, ~30 cols):

```
┌─ Snooze ─────────────────────┐
│                              │
│   1   15 minutes             │
│   2   1 hour                 │
│   3   4 hours                │
│   4   Tomorrow morning       │
│                              │
│   c   Custom…                │
│                              │
│   esc  cancel                │
└──────────────────────────────┘
```

Decisions worth flagging:

- **Four presets, not eight.** More options means more reading. Five-minute and ten-minute snoozes are a smell — if you
  _really_ want to be reminded that fast, just stay in the panel. Sub-15m is a power-user case and the custom input
  handles it.
- **"Tomorrow morning" is anchor-time-aware.** Computed as `09:00 local` _on the next day where it's still in the
  future_. If you snooze at 22:00 on Tuesday for "tomorrow morning", you get Wednesday 09:00. If you snooze at 06:00 on
  Tuesday, you also get Wednesday 09:00, not Tuesday 09:00 (which would be only 3 hours away — surprising). Rationale:
  "tomorrow morning" should always feel like _real_ tomorrow.
- **Number keys, not arrow-then-enter.** Arrow navigation in a 4-row list is slower and forces visual scanning.
  Single-digit shortcuts mean the user can press `s 2` without ever moving their hand.
- **Custom is `c`, not `0` or `5`.** Numbers stay reserved for presets so we can grow the list (5/6/7…) without
  reshuffling muscle memory.

The custom flow opens a tiny inline `Input` (in the same modal — no extra screen push) with placeholder
`e.g., 30m, 2h, 1h30m`. Submission feeds the string through the existing `sase.xprompt._directive_time.parse_duration`
helper — same `XhYmZs` syntax used by `wait` directives, so the user's muscle memory transfers. Bad input shows a
one-line red error and keeps the input focused.

The modal returns a `timedelta` (or `None` on cancel). The notification modal converts it into an absolute
`snooze_until` timestamp at write time, not the picker — that way "tomorrow morning" semantics live in one place.

### Storage & schema

One new field on `Notification`:

```python
snooze_until: str | None = None  # ISO-8601 with timezone, or None
```

Backward-compat: missing field loads as `None` via `data.get("snooze_until")` in `_notification_from_dict`. No
migration. Old records with `muted=True` and no `snooze_until` continue to mean "permanently muted" — exactly what they
meant before this feature existed.

New store function: `mark_snoozed(notification_id: str, until: datetime) -> bool`. Implementation:

1. Load the JSONL.
2. Find the row by id. Set `muted = True`, `snooze_until = until.isoformat()`.
3. Rewrite. Same fcntl-locked path as `mark_muted` / `mark_dismissed` — no new I/O surface.

Returns `True` if found, `False` otherwise. Consistent with the rest of the `mark_*` API.

`mark_muted(id, muted=False)` is updated to clear `snooze_until` along with `muted` — preserving the invariant that
`muted=False` implies `snooze_until=None`. (Calling `mark_muted(id, True)` does _not_ touch `snooze_until` — muting an
already-snoozed row is a no-op on the timer; the user can re-snooze with `s` if they want a different deadline.)

### Expiry: lazy, not timed

The expiry mechanism is _entirely lazy_ and _entirely poll-driven_. Specifically: in `_poll_agent_completions` (which
runs on every TUI refresh tick), after `load_notifications()` we call:

```python
expired = expire_due_snoozes(notifications)  # mutates store + returns list
```

`expire_due_snoozes` walks the loaded list, finds rows where `snooze_until` is set and `<= now`, sets `muted=False` and
`snooze_until=None` on them in-memory _and_ on disk (one rewrite for any expirations in the batch — no per-row
rewrites), and returns the list of rows that just expired. The caller then:

- **Rings the bell once** if `expired` is non-empty. (Once, not per row — same as how arrival batches ring once.)
- **Lets the rest of the existing flow re-categorize them.** The newly-unmuted rows naturally land in `unread_priority`
  / `unread_rest` and contribute to the gold indicator count, and they appear in `new_notifications` via the existing
  `current_ids - self._last_unread_ids` diff — so they'll _also_ trigger the toast. That's the intended behavior: a
  re-surfaced snoozed item is, from the user's perspective, indistinguishable from a fresh arrival.

Why lazy and not `set_timer`:

1. **Survives restarts.** If the TUI is closed when a snooze expires, the bell wouldn't ring anyway — so the only thing
   that matters is _when the user next looks_, which is when the TUI starts and runs its first poll. Lazy gets this for
   free; timers don't.
2. **Survives clock changes.** Suspended laptop wakes up, system time leaped forward 8 hours — every snooze that expired
   during sleep fires on the next poll.
3. **Survives multiple sase processes.** Two TUIs running against the same notification store both expire the same
   snooze on their next poll cycle. The fcntl-locked rewrite makes the second one a no-op (snooze_until already
   cleared). No coordination needed.
4. **No new infrastructure.** No `Textual.set_timer`, no asyncio task, no thread.

The only thing lazy gets _wrong_ is the latency between "snooze deadline" and "bell rings": it's bounded by the poll
interval (≈1s). For a feature whose unit of time is _minutes_ at the smallest preset, a 1s ring delay is invisible.

### Visual treatment in the panel

A snoozed row is a muted row + a remaining-time badge. Concretely, in `_create_styled_label`:

```
~ [sender] message text  3m ago  [plan]  · in 14m
```

The new bit is the trailing `· in 14m` segment, rendered dim. Styling rules:

- **Prefix** stays `~ ` (dim) — same as muted today. We don't introduce a `z` or `💤` prefix; the badge does the
  differentiation, the prefix carries the "quiet" signal.
- **Body styling** stays dim — same as muted today.
- **The badge format** is `· in {relative}` where `{relative}` reuses the same `Xm`/`Xh`/`Xd` rendering as
  `format_relative_time`, but reading _forward_. (Helper: `format_relative_until(iso_timestamp)` mirrored in
  `models.py`.) "in 14m" is human-friendly without needing to parse a clock time. Examples: `in 14m`, `in 2h`, `in 1d`.
  Under 1 minute → `< 1m`. (Past-due — shouldn't happen post-expiry-pass — renders as `expiring…`.)
- **The `·` separator** matches the indicator's secondary-segment glyph from the mute plan. Visual consistency: the same
  dot tells the user "this is a quiet sub-piece of information".
- **The badge does not move** with focus or selection — it's part of the row label. Re-rendering happens whenever the
  list rebuilds, which already happens every refresh tick via `_refresh_notification_count_async`. (Footnote: the modal
  itself rebuilds on `_rebuild_list`, which is called by mute/dismiss/read-all actions — not on every tick. That's fine:
  the user is interacting; the badge being a few seconds stale inside an open modal is a non-issue.)

For the closed-modal indicator: snoozed rows count exactly as muted today. No new chrome. When a snooze expires they
flip into the unread count — the existing gold→dim animation logic handles the visual change for free.

### Keybinding & action wiring

Add one binding in `NotificationModal`:

```python
("s", "snooze", "Snooze"),
```

The action method `action_snooze`:

1. Get the highlighted notification. Bail if none.
2. Push the `SnoozeDurationModal` and `await` its return.
3. If `None` (cancelled): show `"Snooze cancelled"` toast, done.
4. If a `timedelta`: compute `snooze_until = datetime.now(get_timezone()) + delta` (or for "tomorrow morning", compute
   the absolute datetime directly inside the picker callback).
5. Call `mark_snoozed(notification.id, snooze_until)`.
6. Update the local `notification.muted = True; notification.snooze_until = snooze_until.isoformat()`.
7. Rebuild the list, keeping the highlight on the same row (matches mute's "don't move the user" pattern).
8. Toast `"Snoozed for 15m"` / `"Snoozed until tomorrow morning"`.

Behavior on already-muted / already-snoozed rows:

- `s` on a permanently-muted row → snoozes it. (Equivalent to "demote permanent mute to a timer.")
- `s` on a snoozed row → re-snoozes with new duration. The toast confirms the new deadline.
- `m` on a snoozed row → unmutes _and_ clears `snooze_until` (handled by the `mark_muted(id, False)` change above).
  Toast: `"Unmuted (snooze cancelled)"`.

Hint label update (`#notification-hints` line 101):

```
Enter: select  x: dismiss  m: mute  s: snooze  e: edit  …
```

### Audible ping

Identical to today's arrival ring — `_ring_tmux_bell()` with the existing `("3", "0.1")` args. Rationale: a snoozed
notification re-surfacing _is_ a new arrival from the user's perspective, and we want the affordance to be
indistinguishable. Inventing a separate ring pattern for snooze expiry would be more sound design than the feature
warrants in v1, and would risk training the user to ignore one of the two. (If users later want a different sound,
that's a generic notification-sound-customization feature, not a snooze-specific one.)

The bell rings _once per poll cycle_ even if multiple snoozes expire in the same tick — same batching as fresh arrivals.

### Indicator behavior

No new indicator chrome. Snoozed rows count toward `muted` (the dim secondary count), permanently-muted rows count
toward `muted` — they're indistinguishable in the header, which matches the "mute with a timer" mental model. When a
snooze expires, the row leaves the muted bucket and re-enters the active-unread bucket, so:

- `unread` count goes up by 1
- `muted` count goes down by 1

The transition happens during the same poll tick that runs `expire_due_snoozes`, before `set_counts` is called, so the
indicator update is atomic from the user's perspective: bell rings, gold count ticks up, dim count ticks down.

### Status-override interaction

The mute plan's invariant — _muting quiets the indicator, not the agent's lifecycle_ — applies equally to snooze. A
plan-approval notification that's snoozed still triggers the agent's `PLANNING` status override, exactly as a muted
plan-approval does today (`unread_active + unread_muted` is passed to `_apply_notification_status_overrides` regardless
of mute state). No code change here — the existing union covers it.

## Reliability

- **Persistence:** `snooze_until` rides the same fcntl-locked JSONL rewrite as every other field. No new storage
  surface, no new failure modes.
- **Default:** `snooze_until=None` for new notifications and for old records without the field. Backward-compatible.
- **Idempotency:** `mark_snoozed(id, ts)` is a single read-decide-write. Calling it twice with the same `ts` is a
  redundant rewrite, not a corruption risk.
- **Concurrency:** if a sender appends a fresh notification while expiry is rewriting, the exclusive lock serializes
  them — same guarantee `mark_dismissed` provides today. Worst case: a brand-new notification is read in by the expiry
  pass and rewritten unchanged.
- **Two-process expiry race:** if two TUIs both poll at the same second and both see a snooze that just expired, both
  will rewrite. Both rewrites set the same end state (`muted=False, snooze_until=None`); the second one is a no-op
  data-wise. Both will ring their bells — which is the correct behavior, because they're _two different views_ for the
  user.
- **Clock changes / DST:** snooze timestamps are stored with timezone (`datetime.now(get_timezone()).isoformat()`), so a
  DST shift doesn't move the deadline. A user-initiated clock jump _will_ shift it — but that's expected; the comparison
  is `now() >= snooze_until` and `now()` reflects the wall clock the user is currently looking at.
- **Edge case — snooze for 0s** (e.g., a custom input of `0s`): the picker rejects parses that yield `<= 0` seconds with
  the same red error as malformed input. Eliminates a race where a snooze expires on its own creation tick.
- **Edge case — snooze beyond reason** (e.g., `9999h`): no cap. The user knows what they're doing. The store doesn't
  care. The badge gracefully degrades to `in Nd` for very long horizons.

## Edge cases

- **Read (`R`)**: marking all as read includes snoozed rows. Snooze persists across read state — a snoozed-then-read
  notification is `read=True, muted=True, snooze_until=<ts>`. When the snooze expires, it flips to
  `muted=False, snooze_until=None` but stays `read=True`. _It does not re-enter the unread count._ Rationale: the user
  explicitly said they'd seen it; snooze expiring is a "remind me", and we still ring the bell, but we don't silently
  invent unread-ness on the user's behalf. (Open question: ring bell in this case at all? Answer: yes — the user opted
  into a reminder. Read-state is independent. The bell is the reminder, not the unread count.)
- **Dismiss (`x`)**: independent of snooze. Dismissing a snoozed row removes it from disk like any other; no bell fires
  later because the row no longer exists.
- **Snooze + sender mute** (future): out of scope. If sender-level mute lands later, snooze on an individual row takes
  precedence in the same way per-row mute does today.
- **Snooze on a `silent` notification**: `silent` means the sender requested no toast/bell on _arrival_; snooze is set
  by the user post-arrival. Snooze's expiry bell ignores `silent` — the user explicitly asked to be reminded.
  (Filtering: `silent` notifications are excluded from `unread_*` buckets today; that doesn't change. The expiry pass
  operates on the full `notifications` list, so silent-snoozed rows do expire and do ring.)
- **External response auto-dismiss** (Telegram-approved plans): unaffected. Auto-dismiss runs over all unread, including
  snoozed-but-active rows, and dismisses them — at which point the snooze becomes moot.

## Files Changed

| File                                                       | Change                                                                                                                                                                                                                                                                |
| ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/notifications/models.py`                         | Add `snooze_until: str \| None = None` to `Notification`. Add `format_relative_until(iso_ts)` helper.                                                                                                                                                                 |
| `src/sase/notifications/store.py`                          | Read `snooze_until` in `_notification_from_dict`. Add `mark_snoozed(id, until: datetime)`. Update `mark_muted(id, False)` to clear `snooze_until`. Add `expire_due_snoozes(notifications) -> list[Notification]` (mutates list + rewrites if any expired).            |
| `src/sase/notifications/__init__.py`                       | Export `mark_snoozed`, `expire_due_snoozes`, `format_relative_until`.                                                                                                                                                                                                 |
| `src/sase/ace/tui/modals/snooze_duration_modal.py` _(new)_ | New `SnoozeDurationModal` — number-key presets, `c` for custom, `esc` to cancel. Returns `timedelta \| datetime \| None`.                                                                                                                                             |
| `src/sase/ace/tui/modals/__init__.py`                      | Export `SnoozeDurationModal`.                                                                                                                                                                                                                                         |
| `src/sase/ace/tui/modals/notification_modal.py`            | `s` keybinding + `action_snooze`. Updated `_create_styled_label` to render the `· in 14m` badge. Updated hints label.                                                                                                                                                 |
| `src/sase/ace/tui/actions/agents/_notifications.py`        | Call `expire_due_snoozes(notifications)` at the top of `_poll_agent_completions`. Existing `new_notifications`/`_ring_tmux_bell` flow handles the rest naturally.                                                                                                     |
| `tests/test_notification_models.py`                        | Default-value snapshot includes `snooze_until=None`. `format_relative_until` covers `< 1m`, `Xm`, `Xh`, `Xd`, past-due.                                                                                                                                               |
| `tests/test_notification_store.py`                         | `mark_snoozed(id, ts)` round-trip. `mark_muted(id, False)` clears `snooze_until`. `expire_due_snoozes` flips ready rows, leaves not-ready rows, returns the flipped list, single rewrite per batch. Backward-compat: load record without `snooze_until` field.        |
| `tests/test_notification_modal.py`                         | Pressing `s` opens the picker. Picker preset → `mark_snoozed` called with right delta. Picker custom → parses `1h30m`. Picker cancel → no store call. `s` on snoozed row re-snoozes. `m` on snoozed row clears both. Row label includes `· in Xm` badge when snoozed. |
| `tests/test_notification_snooze_modal.py` _(new)_          | `SnoozeDurationModal` keypress 1/2/3/4 returns the right timedelta/datetime. `c` opens custom input. Bad custom input shows error and keeps focus. `esc` returns `None`.                                                                                              |
| `tests/test_notification_indicator.py`                     | (No new tests required — snooze rolls into existing muted count behavior. Add one assertion that confirms a snooze-then-expire transition flips the count from muted to unread.)                                                                                      |
| `tests/test_notifications_polling.py` _(or equivalent)_    | Integration: a notification with `snooze_until` in the past + `muted=True` → after `_poll_agent_completions`, the row is `muted=False`, the bell rang once, the indicator unread count went up.                                                                       |

No CSS changes — picker styling is inline with rest of modal CSS. No vendored-tool changes — the bell script is reused
as-is.

## Acceptance

- Pressing `s` on a notification opens the snooze picker.
- Pressing `1`/`2`/`3`/`4` from the picker snoozes for 15m / 1h / 4h / next-9am-local respectively, dismisses the
  picker, and shows a confirmation toast naming the duration.
- Pressing `c` from the picker opens a custom-duration input. Submitting `1h30m` snoozes for 90 minutes; submitting
  garbage shows a red one-line error and keeps focus on the input. `esc` from custom returns to the preset list; `esc`
  from the preset list returns `None`.
- A snoozed row in the panel renders with the `~ ` prefix, dim body, and a trailing `· in {time-remaining}` segment.
- Pressing `m` on a snoozed row unmutes it _and_ clears the snooze (no leftover timer).
- The indicator shows snoozed rows as part of the dim muted-count, not the gold unread-count.
- After a snooze expires (waited or fast-forwarded clock in tests): on the next poll the row is `muted=False`,
  `snooze_until=None`; the tmux bell rings once for the batch; the indicator's gold count goes up by 1; the dim muted
  count goes down by 1; a toast appears for the re-surfaced notification.
- Closing and reopening the TUI mid-snooze preserves the `snooze_until` deadline. Reopening _after_ the deadline runs
  the expiry pass on the first poll and rings the bell.
- Old notification records without a `snooze_until` field load cleanly with `snooze_until=None`.
- `just check` passes.

## Out of scope (future work)

- Bulk snooze (`S` to snooze all unread for a chosen duration).
- Per-sender snooze rules.
- Absolute-time snooze inputs ("until 9am", "until Monday"). v1 covers "tomorrow morning" as a preset; broader
  absolute-time parsing layers on as a custom-input upgrade.
- Customizable snooze ring (different sound / pattern from arrival).
- A "currently snoozed" filter view in the panel.
- Notification-store-level retention policy for very-long-lived snoozes (e.g., snoozed for 30d) — today the row stays in
  the JSONL indefinitely until dismissed, which is fine.
