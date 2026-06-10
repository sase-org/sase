---
create_time: 2026-06-10 10:01:29
status: done
prompt: sdd/prompts/202606/tui_perf_background_tasks.md
---
# Mention tracked background tasks in `memory/long/tui_perf.md`

## Context

`memory/long/tui_perf.md` (created today, commit 20d129453) tells agents to push slow work off the Textual event loop
with `asyncio.to_thread()` / `run_worker(..., thread=True)` (rule 1). That is necessary but no longer the whole story:
two recent commits moved the last big ad-hoc off-thread flows onto the central **tracked task queue**, and that is now
the established vehicle for slow, user-initiated work in the TUI:

- `eb5db8a27` — _feat: track TUI agent launches in task queue_ (all five launch fanout paths now submit tracked tasks
  via `LaunchTaskMixin._submit_launch_task`, `src/sase/ace/tui/actions/agent_workflow/_launch_tasks.py`).
- `d204dae4a` — _feat: track agent kill/dismiss persistence in task queue_ (all four kill/dismiss persistence flows now
  submit tracked tasks via `CleanupTaskMixin._submit_cleanup_task`, `src/sase/ace/tui/actions/agents/_cleanup_tasks.py`,
  replacing ad hoc `call_later(asyncio.to_thread(...))` coroutines).

The memory should mention this option so future agents reach for the task queue — not a new fire-and-forget code path —
when they move slow work off the event loop.

## Research performed

- Audited read of the current `memory/long/tui_perf.md` via `sase memory read`.
- Read the task-queue infrastructure: `TaskActionsMixin._submit_tracked_task()` and the simpler per-CL
  `_submit_background_task()` wrapper (`src/sase/ace/tui/actions/task_actions.py`), `TaskQueue`
  (`src/sase/ace/tui/task_queue.py`), `TaskIndicator` (`src/sase/ace/tui/widgets/task_indicator.py`), and the Task Queue
  modal (`src/sase/ace/tui/modals/task_queue_modal.py`, opened with `t`, live output via the task's `_live_buffer`, `K`
  kills a running task).
- Read both consumer mixins (`_launch_tasks.py`, `_cleanup_tasks.py`) to extract the shared shape: optimistic UI stage
  first; a **synchronous** worker body returning a frozen typed outcome; completion effects applied on the UI thread in
  an `on_complete` callback; `dedup_key` (uuid-suffixed where per-CL dedup must not collide).
- Confirmed what "tracked" buys over bare `run_worker`/`to_thread`: visibility in the top-right task indicator and the
  Task Queue modal, duplicate-submission dedup, inclusion in the quit-confirmation count (commit 16dbe5b1e — in-flight
  persistence is not silently lost on quit), automatic stdout/stderr capture, and inspectable success/error records.
- Verified nothing in `src/`, `sdd/`, or tests references the memory's rule numbers, so renumbering is safe.

## Proposed change to `memory/long/tui_perf.md`

Insert a new **rule 2** immediately after rule 1 (which it directly qualifies), renumbering current rules 2–8 to 3–9:

```markdown
2. **Run slow user-initiated operations as tracked background tasks.** Off-thread is not enough for multi-second work
   (agent launches, kill/dismiss persistence, ChangeSpec actions): route it through `_submit_tracked_task()` /
   `_submit_background_task()` (`src/sase/ace/tui/actions/task_actions.py`) instead of ad hoc
   `call_later(asyncio.to_thread(...))` fire-and-forget coroutines. Tracked tasks appear in the top-right task indicator
   and the Task Queue modal (`t`; live output, `K` kills), dedup duplicate submissions, are counted by the
   quit-confirmation flow so in-flight work isn't silently lost, and leave inspectable success/error records. Follow the
   shape in `LaunchTaskMixin` / `CleanupTaskMixin` (`_launch_tasks.py`, `_cleanup_tasks.py`): optimistic UI stage first,
   synchronous worker body returning a typed outcome, completion effects applied on the UI thread in `on_complete`.
```

Why position 2 rather than appending as rule 9: rule 1 ends by telling agents to push work off-thread; this rule is the
immediate follow-on decision ("which off-thread vehicle?"). The remaining rules are unrelated to each other in order,
and nothing references the old numbering.

No other edits: rule 1's `asyncio.to_thread()` / `run_worker(..., thread=True)` guidance stays — it remains correct for
sub-second glue (mtime probes, notification-count refreshes) that doesn't warrant a task-queue row.

## File changes

1. **Edit `memory/long/tui_perf.md`**: insert the rule above as rule 2; renumber existing rules 2–8 to 3–9. Keep lines ≤
   120 columns (prettier) and leave the initializer-managed `description:` frontmatter untouched.

No other files change:

- The `AGENTS.md` Tier 2 description ("Read before changing anything that affects TUI performance or responsiveness…")
  already covers this content — no update needed, which avoids another round with the managed-AGENTS generator.
- No skill sources change, so no `sase skills init` regeneration is needed.

Per repo policy, memory files are only modified with user approval — approval of this plan is that approval.

## Verification

- `sase memory read long/tui_perf.md -r "verify background-task rule landed"` shows the new rule 2 and 9 total rules.
- `sase memory init -c` reports no memory drift.
- `just install && just check` passes (memory markdown is prettier-formatted, so the no-check exceptions don't apply).
