# Agent waiting for a runner slot

An agent shown as `WAITING` on runner slots is at an admission boundary: it has finished its dependency and time-based
waits, or it has received an answer after temporarily yielding its slot at `QUESTION`. SASE limits slot-participating
user agents globally using `max_running_agents` (default: 10). Participants are top-level user agents—including every
clan member launched independently—plus parallel family members. A prompt can use `%wait(runners=N)` to override the
threshold for its initial launch.

The ACE Agents header summarizes the same global state as `[R/L · Q queued]`: slots in use, configured limit, and live
waiters governed by that configured limit. `Q` does not include waits with an explicit `%wait(runners=N)` threshold.

Admission sorts eligible waiters by lower numeric `%wait(priority=N)` first, then first-in, first-out within the same
priority, across all projects. Priority defaults to `10` and does not age, so sustained higher-priority arrivals can
starve default- or lower-priority waiters. An older low-threshold waiter does not block a later launch whose higher
threshold currently permits it to run. Parallel family members participate even when ACE renders them as nested rows.
Serial family follow-ups are exempt so a running parent can safely wait for child work; workflow Python/bash steps and
axe ChangeSpec runners are exempt as well.

To diagnose a wait:

1. Check active and waiting agents with `sase agent list` or the ACE Agents tab.
2. Inspect the launch's `waiting.json`. `wait_runners` is the effective existing-runner threshold and
   `slot_requested_at` is its FIFO time among currently eligible waiters.
3. Raise `max_running_agents` in `sase.yml` if more concurrency is safe. Parked agents reread configuration and normally
   react within about two seconds.
4. Kill an unwanted parked agent normally. Dead or stale waiter PIDs are ignored automatically and cannot wedge the
   queue. A crashed running process likewise stops consuming a slot as soon as its PID is observed dead.

The slot gate runs in each agent process under a global file lock. It does not depend on the axe daemon, so restarting
axe does not release or repair a slot wait. Immediate slot-participating launches become admitted before primary and
linked-workspace preparation; dependency, time, and fork waiters do not consume a slot until those prerequisites
resolve.

An unanswered slot participant at `QUESTION` does not consume a runner slot. Its `pending_question.json` remains
authoritative while the user is deciding and while the answered agent is queued to resume. On answer, the agent uses the
current global cap to reacquire through the same locked priority/FIFO gate; a full cap therefore changes the row from
`QUESTION`/`ANSWERED` to the normal runner-slot `WAITING` state. Killing it during either pause cleans up the question
and queue markers. Question continuations keep their authored priority while reacquiring under the current global cap.

A `%wait(runners=0)` launch is intentionally a drain barrier: it starts only at a true global lull. Newer immediate
slot-participating launches may start while the barrier is parked when their own thresholds permit it, keeping the
barrier waiting until they also finish. The barrier is a drain condition, not an exclusive fence: after it is admitted,
later work can still start whenever its own threshold permits.
