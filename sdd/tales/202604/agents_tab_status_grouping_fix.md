---
create_time: 2026-04-27 08:55:42
status: done
prompt: sdd/prompts/202604/agents_tab_status_grouping_fix.md
---
# Agents Tab BY_STATUS Grouping Fix

## Problem

When the user cycles the `sase ace` "Agents" tab grouping to **BY_STATUS** (`g` key), several agent statuses land in the
wrong bucket. The current mapping conflates "needs your action" with "terminal-but-actionable" and pushes every
post-plan handoff state into the loud **Needs Attention** group, which makes the bucket noisy and dilutes its purpose
(an at-a-glance "what is blocking me right now").

The user wants **Needs Attention** to be a strict, narrow bucket — three statuses only — and wants the post-plan handoff
states to read as either "done" (planning is finished, code work has been spun off) or "running" (an approved plan is
actively being executed).

### Required behavior

- **Done** group must include: `PLAN DONE`, `EPIC CREATED` (in addition to `DONE`).
- **Needs Attention** group must include **only**: `PLANNING`, `FAILED`, `QUESTION`.
- **Running** group must include: `PLAN APPROVED` (in addition to `RUNNING` and the existing fallback states).

### Current behavior (from `src/sase/ace/tui/models/agent_groups.py:138-161`)

| Status                                 | Current bucket         | Required bucket             |
| -------------------------------------- | ---------------------- | --------------------------- |
| `DONE`                                 | Done                   | Done (unchanged)            |
| `PLAN DONE`                            | Needs Attention        | **Done**                    |
| `EPIC CREATED`                         | Needs Attention        | **Done**                    |
| `PLAN APPROVED`                        | Needs Attention        | **Running**                 |
| `PLANNING`                             | Running (via fallback) | **Needs Attention**         |
| `QUESTION`                             | Needs Attention        | Needs Attention (unchanged) |
| `FAILED` (no `retried_as_timestamp`)   | Needs Attention        | Needs Attention (unchanged) |
| `FAILED` (with retry pointer)          | Failed                 | Failed (unchanged)          |
| `FAILED (RETRIED)`                     | Failed                 | Failed (unchanged)          |
| `RUNNING`                              | Running                | Running (unchanged)         |
| `WAITING` + `wait_until`/`waiting_for` | Waiting                | Waiting (unchanged)         |
| `WAITING` (parked, no timer/dep)       | Needs Attention        | **See open question below** |

## Open question for the user

The current mapping puts `WAITING` _parked on user input_ (no `wait_until`, no `waiting_for`) into **Needs Attention**,
on the rationale that the user is implicitly being asked to unblock it. The user's new spec says Needs Attention is
**only** for `PLANNING`, `FAILED`, `QUESTION`, which excludes parked `WAITING`. Two reasonable resolutions:

1. **Collapse all `WAITING` into the `Waiting` bucket** (treat it as one bucket regardless of timer/dependency). This is
   the cleanest reading of "Needs Attention is only those three statuses."
2. **Keep parked `WAITING` in Needs Attention** as an exception, treating the user's list as "the post-plan/failure
   statuses" rather than an exhaustive enumeration.

The plan defaults to **option 1** (collapse all `WAITING` into `Waiting`), because the user's wording was unambiguous
("only ... PLANNING, FAILED, QUESTION"). Will confirm before making the change if the user prefers option 2.

## Design

### Where the change lives

A single function — `_status_bucket_for(agent)` in `src/sase/ace/tui/models/agent_groups.py:138-161` — owns the entire
status-to-bucket mapping. The bucket _order_ (`_STATUS_BUCKETS` at lines 84-90) does not need to change; the same five
buckets are still in play. The change is purely in which status falls into which bucket.

### New mapping (rewritten function logic)

```
status = agent.status or ""

if status in {"DONE", "PLAN DONE", "EPIC CREATED"}:
    return "Done"
if status in {"PLANNING", "QUESTION"}:
    return "Needs Attention"
if status == "PLAN APPROVED":
    return "Running"
if status == "WAITING":
    return "Waiting"          # collapse parked + timer/dependency into one bucket
if status.startswith("FAILED"):
    if not agent.retried_as_timestamp:
        return "Needs Attention"
    return "Failed"
return "Running"              # default fallback for RUNNING and any unknown in-flight state
```

### Constants to update

- `_NEEDS_ATTENTION_STATUSES` (lines 102-104) — currently `{"PLAN DONE", "EPIC CREATED", "QUESTION", "PLAN APPROVED"}`.
  Replace with `{"PLANNING", "QUESTION"}` (FAILED is handled via its own `startswith("FAILED")` branch and so does not
  belong in the static frozenset).
- The block comment above `_NEEDS_ATTENTION_STATUSES` (lines 92-101) describes the old semantics in detail and must be
  rewritten to match the new mapping. It should also explain the new "Done" inclusions and why `PLANNING` is now there.

### Constants to leave alone

- `_NEEDS_INPUT_STATUSES` (lines 109-111) and `_AWAITING_STATUSES` (line 577) are **not** the bucketing source of truth.
  They drive the banner summary / "needs user input" filter — a separate concern from group placement. Touching them
  would silently change banner text and query-filter behavior. Leave both untouched and call this out in the PR
  description so a reviewer doesn't mistake the omission for a miss.
- `DISMISSABLE_STATUSES` in `src/sase/ace/tui/actions/agents/_loading_helpers.py:15-21` is also unrelated — it controls
  the footer "x dismiss" affordance for terminal states. No change needed.

### Tests to update

`tests/ace/tui/models/test_agent_groups_grouping_mode.py` directly asserts the old mapping. Each impacted test must be
updated to assert the new bucket:

- `test_status_bucket_planning_is_running` (line 70) → rename to `..._is_needs_attention`, assert `Needs Attention`.
- `test_status_bucket_plan_approved_is_needs_attention` (line 79) → rename to `..._is_running`, assert `Running`.
- `test_status_bucket_plan_done_is_needs_attention` (line 83) → rename to `..._is_done`, assert `Done`.
- `test_status_bucket_epic_created_is_needs_attention` (line 87) → rename to `..._is_done`, assert `Done`.
- `test_status_bucket_waiting_without_wait_until_or_waiting_for_needs_attention` (line 91) → rename to `..._is_waiting`,
  assert `Waiting` (assuming option 1 above).

The unchanged tests (`DONE` → Done, `RUNNING` → Running, `QUESTION` → Needs Attention, `FAILED` no-retry → Needs
Attention, `FAILED` with retry pointer → Failed, `FAILED (RETRIED)` → Failed, unknown → Running, empty → Running, and
the timer/dependency `WAITING` cases) should keep passing as-is — useful as regression anchors.

Also check `tests/ace/tui/models/test_agent_groups_layout.py` and `tests/ace/tui/widgets/test_agent_list_grouping.py`
for any fixtures that bake in the old grouping; update assertions where they reference the changed statuses.

### Out of scope

- Status string rendering / colors in `src/sase/ace/tui/widgets/_agent_list_rendering.py:314-373` — colors are
  per-status decorations and are independent of grouping.
- Banner summary copy (driven by `_AWAITING_STATUSES`) — separate concern.
- Help-modal description of the `g` cycling — quickly skim it; only update if it currently enumerates which statuses
  fall in which bucket (typically it does not, it just names the modes).
- The `STANDARD` and `BY_DATE` grouping modes — untouched.

## Validation

1. `just install` (workspace may be cold).
2. `just test` — confirms the targeted unit tests pass and nothing else regressed.
3. `just check` — required by repo convention before reply/commit.
4. Manual smoke: launch `sase ace`, press `g` until BY_STATUS, eyeball each bucket against a few representative agents
   (one each in PLAN DONE, EPIC CREATED, PLAN APPROVED, PLANNING, FAILED, QUESTION). The TUI re-renders on grouping
   change so no other state mutation is needed.

## Risk

Low. Single pure function, fully covered by a focused unit-test file. No persistence, no migrations, no cross-tab
implications. The only gotcha is the `WAITING`-parked judgement call (open question above) — confirming with the user
before coding the `WAITING` collapse keeps the blast radius bounded.
