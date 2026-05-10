---
create_time: 2026-05-10 12:16:58
status: done
---
# Plan: Notification Panel — Blank-line section gaps + new ERRORS section

## Goal

Two related changes to the TUI notification modal:

1. **Visual breathing room**: insert a blank line between adjacent populated sections in the notification panel.
2. **New ERRORS section** rendered directly beneath PRIORITY. Two notification kinds currently classified as priority
   should move into ERRORS:
   - **Axe error digest notifications** — sender `axe`, action `ViewErrorReport` (emitted by `notify_axe_error_digest()`
     in `src/sase/notifications/senders.py`).
   - **Failed-agent error reports** — sender `user-agent`, action `ViewErrorReport` (emitted from
     `src/sase/axe/run_agent_runner_finalize.py`).

   Other axe-sourced notifications (e.g. axe priority workflows that aren't error digests) stay in PRIORITY.

## Why this matters

- ERRORS is a qualitatively different "thing requires attention" than PlanApproval / UserQuestion / mentor reviews.
  Mixing them in a single PRIORITY block means the red bar above plan approvals is the same red bar above an axe crash
  report — the user loses the ability to triage at a glance.
- Section gaps simplify scanning when a user has 5+ priority items + a busy inbox; the current rendering puts headers
  flush against the previous section's last row.

## Section taxonomy (after change)

Render order, top to bottom:

1. **PRIORITY** — PlanApproval, UserQuestion, JumpToMentorReview, `crs` sender, non-error `axe` notifications. Color:
   red `#FF4444` (unchanged).
2. **ERRORS** _(new)_ — `axe`+`ViewErrorReport`, `user-agent`+`ViewErrorReport`. Color: recommend a distinct hue from
   PRIORITY red and INBOX gold — e.g. orange `#FF8C00` or magenta `#FF00AF` — so the eye separates "needs your input"
   (priority) from "something broke" (errors). Final color is a styling call; pick during implementation.
3. **INBOX** — everything not classified above and not muted.
4. **MUTED** — `muted == True` (mute still dominates all other classifications).

Mute precedence rule is preserved: a muted error goes to MUTED, not ERRORS.

## Classification: where the rule lives

Categorization currently lives in two parallel places that must stay in sync:

- **Python**: `src/sase/notifications/priority.py` → `is_priority()`. Used by `_section_for()` in
  `notification_modal_options.py` and by anything else that asks "is this priority?".
- **Rust**: `sase-core/crates/sase_core/src/notifications/mobile.rs` → `mobile_notification_priority_from_wire()`.
  Drives the `NotificationCountsWire.priority` count returned by the store (`store.rs:525`) — consumed by indicator
  badges and mobile cards.

Per the rust-core boundary memory, classification is shared backend logic: any frontend (mobile, future web, indicator
badges) needs the same answer the TUI gets. So **both** sides change.

### Approach: introduce a parallel `is_error` classifier

- Add `is_error(notification)` in `src/sase/notifications/priority.py` (same module — it's a sibling classifier, not a
  separate concern). Rule: `action == "ViewErrorReport" and sender in {"axe", "user-agent"}`.
- **Remove** the corresponding clauses from `is_priority()`:
  - the `user-agent + ViewErrorReport` special case (line 25-26)
  - axe+ViewErrorReport gets removed implicitly: change `_PRIORITY_SENDERS` matching so axe notifications with
    `ViewErrorReport` action are excluded (or just call `is_error()` first and short-circuit).
- Mirror in Rust: add `mobile_notification_error_from_wire()` and update `mobile_notification_priority_from_wire()` to
  exclude error cases.
- Add `errors: u64` field to `NotificationCountsWire` and bump count logic in `store.rs` (`build_counts` near line
  520-535). Bindings + Python wrapper of the wire struct picks up the new field automatically if it's plain serde.

The classifier change is the load-bearing edit — once `is_error()` exists and `is_priority()` excludes errors, the panel
`_section_for()` just needs a new branch.

## TUI changes

### File: `src/sase/ace/tui/modals/notification_modal_constants.py`

Add `("errors", "ERRORS", <color>)` between `priority` and `inbox` in `SECTIONS`. The list-of-tuples shape is the
contract the modal already iterates; ordering is render ordering.

Add an `[error]` action badge (already present at line 14 — keep as-is).

### File: `src/sase/ace/tui/modals/notification_modal_options.py`

- `_section_for()` (line 100): add an `is_error(n)` branch ahead of the priority branch, so axe/user-agent
  ViewErrorReport flows into `"errors"` even though `is_priority()` no longer claims them.
- `_create_sectioned_options()` (line 119): after emitting each populated section's rows, if **another** populated
  section follows, emit a blank disabled `Option` (`Option(Text(""), id="hdr:gap:<key>", disabled=True)`) as a spacer
  row.
  - Use a distinct id prefix (e.g. `hdr:gap:`) so `_visual_notification_index_order()` keeps filtering it out (it
    already filters anything starting with `HEADER_ID_PREFIX = "hdr:"` — gap rows are covered for free).
  - Spacer must be `disabled=True` so navigation skips it.
  - Don't emit a trailing spacer after the last populated section.

### Stylesheet — `src/sase/ace/tui/styles.tcss`

No required change. If the blank `Option` doesn't render with enough vertical breath, TCSS can apply margin to the gap
rows, but try the simple approach first.

## Indicator / badge implications (call out, don't expand scope)

The indicator badge currently goes red when `priority > 0`. After the split:

- An "agent crashed" event no longer increments `priority` — it increments `errors`.
- Without a follow-up, the indicator would NOT light up for an axe crash.

Recommended scope for **this** change: indicator goes red when `priority + errors > 0` (i.e. errors share the priority
indicator). That preserves user-visible alerting without designing a third indicator state.

A future change could give errors their own indicator color/state — out of scope here. The plan should land as one
cohesive change; don't introduce a regression in alerting behavior.

## Tests

- **Python**: extend tests for `is_priority` / new `is_error` covering each rule (axe+ViewErrorReport → error not
  priority; axe+other action → still priority; user-agent+ViewErrorReport → error; muted+error → muted).
- **TUI**: extend the notification modal option-rendering test (find via `tests/.../notification_modal*`) to assert (a)
  ERRORS section renders between PRIORITY and INBOX when populated, (b) a blank disabled spacer row sits between
  populated adjacent sections, (c) `_visual_notification_index_order()` excludes spacers and headers.
- **Rust**: add a test in `sase-core` mirroring the priority/error split and the new `errors` count.

## Risks / open decisions

1. **ERRORS color** — pick during impl. Suggestion: orange `#FF8C00` (urgency without collision against PRIORITY red and
   INBOX gold).
2. **Indicator semantics** — recommended `priority + errors` for the red indicator; confirm during review.
3. **External consumers of `NotificationCountsWire.priority`** — adding `errors` doesn't break old consumers, but the
   priority count value changes (it drops error notifications). Check whether any code path treats `priority` as "needs
   attention" total; if so, switch it to `priority + errors`.

## Files touched (summary)

Python (this repo):

- `src/sase/notifications/priority.py` — split classifier
- `src/sase/notifications/__init__.py` — re-export `is_error` if `is_priority` is re-exported there (it is — line 20 of
  `notification_modal_options.py` imports it from `sase.notifications`)
- `src/sase/ace/tui/modals/notification_modal_constants.py` — SECTIONS entry
- `src/sase/ace/tui/modals/notification_modal_options.py` — `_section_for`, gap rows
- Tests under `tests/`

Rust (`../sase-core`):

- `crates/sase_core/src/notifications/mobile.rs` — split classifier
- `crates/sase_core/src/notifications/wire.rs` — `errors` count field
- `crates/sase_core/src/notifications/store.rs` — count tally update
- Crate tests
