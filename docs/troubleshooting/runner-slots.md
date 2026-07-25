# Agent queued for a runner slot

An agent shown as `QUEUED` is at an admission boundary: it has finished every dependency, bead, and time wait and is
holding only for capacity under the effective global `max_running_agents` value (configured default: 10). It may also
have received an answer after temporarily yielding its slot at `QUESTION`. Participants are top-level user
agents—including every clan member launched independently—plus parallel family members. An authored `%wait(runners=N)`
threshold remains `WAITING`, because that row is held by its explicit condition rather than ambient global capacity.

The ACE Agents header summarizes the same global state as `[R/L · Q queued]`: slots in use, effective limit, and live
waiters governed by that effective limit. The effective value is an active machine-wide override from
`~/.sase/max_running_agents_override.json` first and merged configuration second. `Q` does not include waits with an
explicit `%wait(runners=N)` threshold.

Admission sorts waiters by lower numeric `%wait(priority=N)` first, then first-in, first-out within the same priority,
across all projects. ACE shows that full order as `#N/M` on `QUEUED` rows and as `queue #N of M` in details, even while
the pool is full or an authored threshold is not yet satisfied. Priority defaults to `10` and does not age, so sustained
higher-priority arrivals can starve default- or lower-priority waiters. An older low-threshold waiter does not block a
later launch whose higher threshold currently permits it to run. Parallel family members participate even when ACE
renders them as nested rows. Serial family follow-ups are exempt so a running parent can safely wait for child work;
workflow Python/bash steps and axe ChangeSpec runners are exempt as well.

To diagnose a wait:

1. Check active, queued, and waiting agents with `sase agent list` or the ACE Agents tab.
2. Inspect the launch's `waiting.json`. `wait_runners` is the effective existing-runner threshold and
   `slot_requested_at` is its FIFO request time; `runner_slot_queue_position` in `sase agent list -j` is its current
   priority/FIFO rank among all live slot waiters.
3. Press fixed `Ctrl+R` in the Models panel to edit `max_running_agents` persistently or apply/clear a temporary value.
   Parked implicit-cap agents reread the effective value and normally react within about two seconds. Setting another
   temporary value replaces the first; expiry or Clear resumes configured behavior.
4. Kill an unwanted parked agent normally. Dead or stale waiter PIDs are ignored automatically and cannot wedge the
   queue. A crashed running process likewise stops consuming a slot as soon as its PID is observed dead.

The slot gate runs in each agent process under a global file lock. It does not depend on the axe daemon, so restarting
axe does not release or repair a slot wait. Immediate slot-participating launches become admitted before primary and
linked-workspace preparation; dependency, time, and fork waiters do not consume a slot until those prerequisites
resolve.

An unanswered slot participant at `QUESTION` does not consume a runner slot. Its `pending_question.json` remains
authoritative while the user is deciding and while the answered agent is queued to resume. On answer, the agent uses the
current global cap to reacquire through the same locked priority/FIFO gate; a full cap therefore changes the row from
`QUESTION`/`ANSWERED` to the normal runner-slot `QUEUED` state. Killing it during either pause cleans up the question
and queue markers. Question continuations keep their authored priority while reacquiring under the current global cap.

Lowering the effective cap below current occupancy is safe and non-preemptive: no running process is killed or forced to
yield, but no implicit-cap participant is admitted until occupancy falls far enough. Raising it does not bypass
priority/FIFO order. If the bounded temporary-state lock or file read is briefly unavailable, an implicit launch fails
closed for that poll, remains published as waiting, releases the slot lock, and retries instead of crashing or silently
admitting against configuration alone.

A `%wait(runners=0)` launch is intentionally a drain barrier: it starts only at a true global lull. Newer immediate
slot-participating launches may start while the barrier is parked when their own thresholds permit it, keeping the
barrier waiting until they also finish. The barrier is a drain condition, not an exclusive fence: after it is admitted,
later work can still start whenever its own threshold permits.
