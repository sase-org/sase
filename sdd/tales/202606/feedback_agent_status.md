---
create_time: 2026-06-28 10:13:37
status: done
prompt: sdd/prompts/202606/feedback_agent_status.md
---
# Plan: Add a `FEEDBACK` agent status for planner rounds that received user feedback

## Product context

In the `sase ace` TUI Agents tab, an agent that proposes a plan can be resolved three ways by the user:

- **approve** → spawns a code/tale/epic/etc. follow-up; the planner shows `PLAN APPROVED` / `TALE APPROVED` / etc.
- **reject** → `PLAN REJECTED` (terminal).
- **feedback** → the user leaves feedback on the plan, which spawns a _new planner round_ to revise it.

Today there is no distinct status for the "feedback" outcome. When a planner round receives feedback and a later round
eventually gets approved, the TUI mis-attributes the family's _approved_ status to the **first** planner (the one that
actually got feedback), and the later round that was actually approved is shown as plain `DONE`. The first planner's
runtime is also inflated because it is anchored to the _latest_ round's plan submission instead of its own.

We want a new **`FEEDBACK`** agent status, with a distinct color, that is shown on any planner row whose proposed plan
the user left feedback on. By the existing "root mirrors the newest child" rule, the family root will automatically show
`FEEDBACK` when the feedback round is the most recent child to run.

### Concrete worked example (ground-truth data)

Family `08w` (project `bob-cli`), confirmed from the on-disk `agent_meta.json` files:

| Row                                           | role      | own `plan_submitted_at` | own `feedback_submitted_at`              | `plan_action` / `plan_approved` | run_started |
| --------------------------------------------- | --------- | ----------------------- | ---------------------------------------- | ------------------------------- | ----------- |
| `08w` (root / first planner, suffix `--plan`) | root/plan | `13:29:35` (P1)         | `13:36:05` (F1)                          | `tale` / `true`                 | `13:17:57`  |
| `08w--plan-0` (feedback round)                | feedback  | `13:47:25` (P2)         | `13:36:05` (F1, the _creating_ feedback) | `tale` / `true`                 | `13:36:08`  |
| `08w--code`                                   | code      | —                       | —                                        | (tale handoff)                  | `13:48:17`  |

Sequence: first planner submits P1 → user gives feedback F1 (P1 < F1) → feedback round `08w--plan-0` submits revised
plan P2 → user approves it (`tale`) → code agent starts.

**Current (buggy) display** — matches the screenshot `.sase/home/tmp/screenshots/20260628_094909.png`:

- `08w--plan` → `TALE APPROVED`, runtime `29m28s` (P2 − run_start = 13:47:25 − 13:17:57). **Wrong.**
- `08w--plan-0` → `DONE`. **Wrong.**
- `08w--code` → `WORKING TALE`; root → `WORKING TALE`. (Correct.)

**Desired display after this change:**

- `08w--plan` → **`FEEDBACK`** (its plan P1 got feedback F1), runtime anchored to its own plan submission P1 (≈
  `11m38s`), not the later round's P2.
- `08w--plan-0` → **`TALE APPROVED`** (it is the latest planner round and its own `plan_action == "tale"`,
  `plan_approved == true`).
- `08w--code` → `WORKING TALE`; root → `WORKING TALE` (unchanged; the newest child is the coder, not the feedback
  round).

> **Note on `PLAN APPROVED` vs `TALE APPROVED`.** The request asks for `08w--plan-0` to show `PLAN APPROVED`. The
> on-disk metadata for this family is unambiguously a _tale_ approval (`plan_action == "tale"` on the round, root, and
> the code handoff renders `WORKING TALE`). The approved-status flavor is therefore data-driven and will render as
> `TALE APPROVED` here. "`PLAN APPROVED`" in the request is read as "the approved-plan status family"; the concrete
> flavor follows `plan_action` exactly as it already does for every other approved planner. If the intent is instead
> that this specific family should have been a plain `approve` (and the `tale` everywhere is itself wrong), that is a
> separate bug — flag during plan review.

## Why it happens today (root cause)

Status synthesis lives entirely in Python (the Rust core only stores raw metadata fields such as
`feedback_submitted_at`, `plan_action`, `plan_approved`; it emits **no** display-status strings — so **no
Rust/`sase-core` change is needed**).

The relevant Python pieces:

- `src/sase/ace/tui/models/_agent_status_apply.py` — `apply_status_overrides()` orchestrates per-row status. It (a)
  propagates each feedback round's `plan_times` / `feedback_times` up to the family root (so the root accumulates
  `plan_times == [P1, P2]`), (b) syncs the logical `--plan` child from the root, and (c) finally makes the root mirror
  its newest child.
- `src/sase/ace/tui/models/_agent_status_family.py`:
  - `sync_planner_child_from_parent()` copies the root's _accumulated_ `plan_times` onto the `--plan` child — this is
    why the first planner's runtime anchors to P2.
  - `planner_child_status()` → `_approved_planner_status()` returns the family's approved status (`TALE APPROVED`) for
    the `--plan` child because the root carries `plan_action == "tale"` / `plan_approved == true` and a code child
    exists — even though the `--plan` round itself was fed back on.
  - `approved_followup_planner_status()` returns `None` for role `"feedback"` rows, so the actually-approved
    `08w--plan-0` is never promoted out of `DONE`.
- `src/sase/ace/tui/models/agent_time.py` — `_row_runtime_terminal_time()` anchors planner- phase rows to
  `max(plan_times)`, i.e. P2 for the synced `--plan` child.

The fix's central insight: **a planner round is only ever superseded by a later planner round via feedback** (approval
spawns a coder, rejection is terminal). So "this planner-family row has a later-launched planner-family sibling" is an
exact, structural signal that the row received feedback.

## High-level design

### 1. Define the status + bucketing — `src/sase/agent/status_buckets.py`

- Add `FEEDBACK_STATUS = "FEEDBACK"`.
- Add `FEEDBACK_STATUS` to `_TERMINAL_STATUSES` so it buckets as **Done** (it is a completed, superseded planner;
  nothing for the user to act on) and date-sorts by `stop_time`.
- Deliberately keep it **out of** `AGENT_ASKING_STATUSES`, `_NEEDS_INPUT_STATUSES`, `_STOPPED_STATUSES`, and
  `ACTIVE_PLAN_HANDOFF_STATUSES` (feedback was already given; the row is not awaiting input and is not actively
  executing).
- Leave `DISMISSABLE_STATUSES` / `RESUMABLE_DONE_STATUSES` in `src/sase/ace/tui/models/agent_status.py` unchanged
  (FEEDBACK rows are child rows, not dismiss/resume targets) — revisit only if review wants them dismissable.

### 2. Distinct color at the three render sites

Introduce a single distinct color (proposed **`#FF5FD7`**, a magenta — clearly separated from PLAN's pink `#FF87AF`, the
approved teals, QUESTION amber, and WAITING amethyst; final value open to taste). Wire it in everywhere statuses are
colored:

- `src/sase/ace/tui/widgets/_agent_list_render_agent.py` — add a `FEEDBACK_STATUS` branch in the status-coloring chain.
- `src/sase/ace/tui/modals/zoom_panel_modal.py` — add `FEEDBACK_STATUS` to the `_status_text` style map (it stays out of
  `_ACTIVE_STATUSES`, so it renders with the non-active `●` glyph).
- `src/sase/ace/tui/widgets/prompt_panel/_workflow_render.py` — add `FEEDBACK_STATUS` to the `status_style` map.

(No status legend exists in `help_modal.py`, so no help-popup change is required. No keymap change, so
`default_config.yml` is untouched.)

### 3. Detect & assign `FEEDBACK` — `_agent_status_family.py` + `_agent_status_apply.py`

- Add a helper in `_agent_status_family.py`, e.g. `superseded_by_feedback_round(agent, children_by_parent) -> bool`:
  returns True when, among the agent's planner-family siblings (same `parent_timestamp`, role in `{"plan", "feedback"}`,
  including both the synced/synthetic `--plan` child and non-workflow `--plan-N` follow-ups), some sibling has a
  strictly later `child_launch_time`.
- Add a dedicated late pass in `apply_status_overrides()`, placed **after** the existing approved/handoff passes and
  **before** the "root mirrors newest child" pass: for every planner-family row where
  `superseded_by_feedback_round(...)` is true, set `agent.status = FEEDBACK_STATUS`. This overrides the stale
  `TALE APPROVED` the sync path put on the first planner, and — because it runs before root mirroring — lets the root
  show `FEEDBACK` automatically when the feedback round is the newest child.
- Broaden `approved_followup_planner_status()` to accept role `"feedback"` (today it requires `"plan"`), keeping the
  existing `plan_action in {"approve", "tale"}` guard. This promotes the _latest_ approved feedback round
  (`08w--plan-0`, own `plan_action == "tale"`) from `DONE` to `TALE APPROVED`. Superseded rounds are unaffected: they
  have no approved `plan_action`, and the late FEEDBACK pass overrides them regardless.

Net effect on the example: `08w--plan` (superseded) → `FEEDBACK`; `08w--plan-0` (latest, approved) → `TALE APPROVED`;
`08w--code` → `WORKING TALE`; root mirrors newest (`08w--code`) → `WORKING TALE`.

### 4. Fix the inflated runtime — `agent_time.py` (+ preserve own timestamps)

- Add `FEEDBACK_STATUS` to `_PLANNER_PHASE_ENDED_STATUSES` so a FEEDBACK row is treated as a finished planner-phase row.
- In `_row_runtime_terminal_time()`, add a `FEEDBACK_STATUS` branch **before** the generic `max(plan_times)` /
  `stop_time` branches that anchors to _the latest plan submission at or before the latest feedback time_ (mirroring the
  existing `_segmented_followup_plan_time` pattern: `max(p for p in plan_times if p <= max(feedback_times))`, falling
  back to `max(plan_times)` then `stop_time`). For the example this yields P1 (P2 is after F1), giving the correct
  ≈`11m38s` instead of `29m28s`.
- To make the "own plan submission" available on the synced `--plan` child, change `sync_planner_child_from_parent()` to
  **not clobber** a concrete child's own `plan_times` / `feedback_times` when it already has them (fill-only-if-empty).
  The family root keeps the accumulated timeline for the detail panel; the row keeps its own anchor. (The "≤ latest
  feedback" filter above also keeps the purely-synthetic, accumulated case correct since the synthetic child only ever
  represents the first `--plan` round.)
- Confirm `runtime_suffix_ticks()` returns False for FEEDBACK (it will: the row has a `stop_time`); the anchored runtime
  must remain frozen, not tick.

## Files to change (summary)

- `src/sase/agent/status_buckets.py` — `FEEDBACK_STATUS` constant + bucket membership.
- `src/sase/ace/tui/widgets/_agent_list_render_agent.py` — color branch.
- `src/sase/ace/tui/modals/zoom_panel_modal.py` — color map entry.
- `src/sase/ace/tui/widgets/prompt_panel/_workflow_render.py` — color map entry.
- `src/sase/ace/tui/models/_agent_status_family.py` — `superseded_by_feedback_round()` helper; broaden
  `approved_followup_planner_status()`; fill-only-if-empty in `sync_planner_child_from_parent()`.
- `src/sase/ace/tui/models/_agent_status_apply.py` — late FEEDBACK pass.
- `src/sase/ace/tui/models/agent_time.py` — FEEDBACK runtime anchor + planner-phase membership.

**No `sase-core` / Rust changes** (status is a Python presentation concern; the raw `feedback_submitted_at` field is
already on the wire).

## Tests

Update existing (in `tests/test_agent_loader_status_override_followups.py`):

- `test_apply_status_overrides_feedback_child_approved_by_metadata_stays_done` — the latest approved feedback round
  should now be the approved status, not `DONE`. Re-point expectation to the approved status (e.g. `PLAN APPROVED` for
  `plan_action == "approve"`) and rename.
- `test_apply_status_overrides_feedback_child_after_code_handoff_stays_done` — align with real data by giving the
  feedback round its own `plan_action` and asserting it shows the approved status (`TALE APPROVED`) while the root still
  mirrors the newer coder (`WORKING TALE`).

Add new coverage:

- First-planner-superseded scenario (the screenshot): root/`--plan` + approved `--plan-0` + active `--code` →
  `FEEDBACK`, `TALE APPROVED`, `WORKING TALE`, root `WORKING TALE`.
- Multi-round: `--plan` → `--plan-0` (both fed back on) → `--plan-1` latest → first two `FEEDBACK`, last one its
  review/approval status.
- Root mirrors `FEEDBACK` when the feedback round is the newest child (no coder yet).
- Runtime anchoring for a FEEDBACK row in `tests/ace/tui/widgets/test_agent_list_runtime_planning.py` (ends at own plan
  submission ≤ feedback, not the later round's submission; does not tick).
- Status bucketing: extend `tests/ace/tui/models/test_agent_groups_grouping_mode_status.py` (or a `status_buckets` unit
  test) to assert `FEEDBACK` → Done bucket.
- A render/color assertion for the new status (e.g. in `tests/ace/tui/widgets/test_agent_render_key_badges.py` or the
  zoom-panel tests).
- Optional: a PNG visual fixture exercising a `FEEDBACK` row + golden, regenerated with `--sase-update-visual-snapshots`
  (see `just test-visual`).

Review for incidental regressions: `tests/test_agent_loader_status_override_feedback.py` (timestamp dedup/propagation —
should be unaffected, status-only change).

## Validation

- `just install` then `just check` (lint + mypy + full test suite, including PNG snapshots).
- Manually confirm in `sase ace` against the `08w` family (or a fresh feedback round) that the superseded planner shows
  `FEEDBACK` in the distinct color, the approved round shows the approved status, the root mirrors the newest child, and
  the `FEEDBACK` row's runtime is no longer inflated.

## Open question for review

- Confirm the approved round should render its _data-driven_ flavor (`TALE APPROVED` for this family) rather than a
  literal `PLAN APPROVED`, per the note above.
