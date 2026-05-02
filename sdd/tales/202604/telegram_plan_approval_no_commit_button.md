---
name: telegram_plan_approval_no_commit_button
description: Replace the Telegram "📦 Commit" button on plan-approval messages with
  a "🚀 Run" button that approves + runs coder + skips the plan-file commit.
create_time: 2026-04-23 17:01:05
status: done
prompt: sdd/prompts/202604/telegram_plan_approval_no_commit_button.md
---

# Replace Telegram "📦 Commit" with "🚀 Run" (approve, no plan commit)

## 1. Problem

When a planner agent finishes, Telegram sends a plan-approval message with five inline buttons:

```
Row 1:  ✅ Approve    📦 Commit    📋 Epic
Row 2:  ❌ Reject     💬 Feedback
```

Each preset maps to one cell of the `(commit_plan, run_coder)` grid:

| Button      | `commit_plan` | `run_coder` | Outcome                                    |
| ----------- | ------------- | ----------- | ------------------------------------------ |
| ✅ Approve  | True          | True        | Commit plan, then hand off to coder        |
| 📦 Commit   | True          | False       | Commit plan, stop (no coder)               |
| 📋 Epic     | True (forced) | n/a         | Convert plan into bead epic                |
| ❌ Reject   | False         | False       | Discard plan                               |
| 💬 Feedback | False         | False       | Discard with feedback → triggers replanner |

The `(commit_plan=False, run_coder=True)` cell — "approve this plan and run the coder, but **don't** commit the plan
file to git" — has no button. Users who want that behavior today have to open the ace TUI and use the
`ApproveOptionsModal` switches.

The request is to replace `📦 Commit` with a button that covers exactly that missing cell.

## 2. Design decision

### Why swap `📦 Commit` specifically

`📦 Commit` is the least-used preset in practice: it is the only button that approves _without_ running the coder, and
the same outcome is available in the ace TUI (`A`=Options → toggle `run_coder` off). Meanwhile the missing
`no-commit + run-coder` cell has no equivalent at all from Telegram. Trading the underused slot for the missing one is a
net win.

The backward-compat branch in `_plan_utils.py:230-234` that translates the old `"commit"` action stays — old unprocessed
response JSONs on disk still work.

### Button label and emoji: `🚀 Run`

```
Row 1:  ✅ Approve    🚀 Run      📋 Epic
Row 2:  ❌ Reject     💬 Feedback
```

Rationale:

- **Verb form** matches the rest of the keyboard (Approve / Reject / Run).
- **Semantic contrast with Approve.** `✅ Approve` reads as "approve _and record_" — the checkmark implies the plan goes
  into git history. `🚀 Run` reads as "just run it" — ephemeral, no ceremony. The rocket emoji is a widely recognized
  "launch / go now" signal (GitHub reactions, CI dashboards, Slack).
- **Position in row 1** (the "move forward" row) keeps the destructive buttons (Reject / Feedback) visually separated in
  row 2.
- **Short label.** Two-char emoji + 3-char word = narrow button → plays well on mobile where row 1 gets cramped on small
  screens.

Rejected alternatives:

- `⚡ Approve` / `⚡ Quick` — ambiguous; "quick" doesn't tell users _what_ is being skipped.
- `🚀 Approve (no commit)` — too long; Telegram buttons wrap awkwardly past ~12 chars.
- `🪶 Light Approve` — cute but cryptic.
- `🏃 Proceed` — fine, but "Run" is crisper and matches the mental model of "run the coder".

### Callback choice key: `run`

New callback: `plan:<prefix>:run`. Short, stays well under Telegram's 64-byte callback-data cap, and reads naturally
alongside `approve` / `reject` / `epic` / `feedback`.

### Response JSON shape

The telegram inbound handler for `run` writes:

```json
{ "action": "approve", "commit_plan": false, "run_coder": true }
```

`_plan_utils.py` already parses `commit_plan` and `run_coder` from the response with correct defaults — no changes
needed on the sase side. The coder-path logic in `run_agent_exec_plan.py:297-306` already respects `commit_plan=False`
for non-epic actions (it simply skips `_commit_sdd_files`).

### Answer-text toast

Telegram shows a short toast after a button press. Use: `"Running coder (no commit)"` to make the no-commit aspect
explicit so users who mis-tap can still catch it.

## 3. Scope

### In scope

1. **`sase-telegram/src/sase_telegram/formatting.py`** — swap the `📦 Commit` button for `🚀 Run` with callback choice
   `run`. Row/column position unchanged (row 1, middle).
2. **`sase-telegram/src/sase_telegram/inbound.py`** — replace the `elif cb.choice == "commit":` branch with an
   `elif cb.choice == "run":` branch that writes `{"action": "approve", "commit_plan": False, "run_coder": True}` and
   answers `"Running coder (no commit)"`.
3. **Tests** in sase-telegram for both files (formatting snapshot of the button row + inbound dispatch to
   `ResponseAction`). The existing tests for `📦 Commit` become tests for `🚀 Run` (updated labels/choices/payloads).
4. **Docs / changelog** in the sase-telegram repo if there is one (AGENTS.md / README).

### Out of scope (intentional)

- **No changes to `sase_103`.** The `_plan_utils.py` backward-compat branch for the legacy `"commit"` action is kept
  untouched — it protects any in-flight plan sessions during deploy and costs nothing.
- **No change to the ace TUI.** The TUI already exposes both toggles via `ApproveOptionsModal`; nothing to swap.
- **No change to `PlanApprovalResult` dataclasses, `run_agent_exec_plan.py`, or auto-approve behavior.**

## 4. UX walkthrough

Before:

```
📋 CLAUDE(opus) Plan Review
  @planner-abc

> (plan body in expandable blockquote)

[ ✅ Approve ] [ 📦 Commit ] [ 📋 Epic ]
[ ❌ Reject ] [ 💬 Feedback ]
```

After:

```
📋 CLAUDE(opus) Plan Review
  @planner-abc

> (plan body in expandable blockquote)

[ ✅ Approve ] [ 🚀 Run ] [ 📋 Epic ]
[ ❌ Reject ] [ 💬 Feedback ]
```

Tap **🚀 Run** → toast `"Running coder (no commit)"` → coder starts on the plan, plan file stays uncommitted in the
workspace for the user to review / edit / discard.

## 5. Validation plan

- Run the sase-telegram test suite — ensure the renamed button appears in plan-approval formatting tests and in the
  inbound-dispatch tests.
- Manual smoke test: trigger a plan approval (e.g. via `just plan` or equivalent), tap `🚀 Run` in Telegram, confirm:
  - Telegram shows the `"Running coder (no commit)"` toast.
  - The plan file is **not** committed (no new commit in `git log` after the coder runs).
  - The coder agent launches normally.
- Regression check: tap `✅ Approve` on a separate plan, confirm the plan file _is_ committed as before.

## 6. Risks / open questions

- **Do any users rely on the `📦 Commit` behavior today?** If yes, they lose the one-tap "commit without coder" preset.
  Mitigation: the ace TUI (`A`=Options) still supports that combination. If the loss is considered too abrupt, a
  follow-up can add a second row-1 slot for a dedicated commit-only button — but the current row-1 width (3 buttons
  already) is near the mobile readability limit.
- **Naming.** If `🚀 Run` tests poorly with users, fallback candidates in priority order: `🚀 Approve (no commit)`,
  `🏃 Proceed`, `⚡ Quick Run`. Swapping the label later is a one-line change.
