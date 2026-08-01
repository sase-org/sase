# Agent queued for a runner slot

An agent shown as `QUEUED` is at an admission boundary: it has finished every dependency, bead, and time wait and is
holding only for runner capacity. Its threshold may come from the effective global `max_running_agents` value
(configured default: 10) or an authored `%wait(runners=N)`. It may also have received an answer after temporarily
yielding its slot at `QUESTION`. Participants are top-level user agents—including every clan member launched
independently—plus parallel family members.

The ACE Agents header summarizes the same global state as `[R/L · Q queued]`: slots in use, effective limit, and live
waiters at the runner-slot admission gate. The effective value is an active machine-wide override from
`~/.sase/max_running_agents_override.json` first and merged configuration second. `Q` includes both implicit-cap and
authored-threshold waits.

Admission sorts waiters by lower numeric `%wait(priority=N)` first, then first-in, first-out within the same priority,
across all projects. ACE shows that full order as `#N/M` on `QUEUED` rows and as `queue #N of M` in details, even while
the pool is full or an authored threshold is not yet satisfied. Priority defaults to `10` and does not age, so sustained
higher-priority arrivals can starve default- or lower-priority waiters. An older low-threshold waiter does not block a
later launch whose higher threshold currently permits it to run. Parallel family members participate even when ACE
renders them as nested rows. Serial family follow-ups are exempt so a running parent can safely wait for child work;
workflow Python/bash steps and axe ChangeSpec runners are exempt as well.

The bundled epic phase and lander xprompts used by `sase bead work` do not set an authored wait priority. They use the
default priority (`10`) once their rendered phase-DAG and bead-dependency waits resolve. The independent bundled
`#bd/work_task` xprompt still carries `%wait(priority=15)` for standalone task-bead work. A project, user, or plugin
override of any bundled xprompt supplies its own body and may choose a different priority.

Selecting a ranked waiter in ACE also shows a bounded `QUEUE` ladder. Its `N ahead` count includes only earlier entries
whose runner threshold is greater than or equal to the selected waiter's threshold—the entries that become eligible no
later and therefore really can start first. Earlier, stricter drain waits use a parked amethyst accent instead of being
counted as ahead. That accent distinguishes their stricter threshold, not a different status: every entry is still
`QUEUED`. The ladder includes the front, up to two entries on either side of the selected waiter, and gap counts; short
queues show all entries, while long queues show at most seven actual queue entries. Explicit thresholds and non-default
priorities appear as `≤N` and `pN`. This is current admission context, not an ETA or a prediction that no new waiter
will arrive, and its entries are not digit-jump targets.

A deprioritized waiter — one whose priority is numerically worse than the `10` default — is additionally held back for a
bounded deference window before it may claim a freed slot, because the sort above only compares waiters already parked
at that instant. Dependency-chained work joins the queue seconds after its predecessor exits, so without the window a
long-parked `priority=20` agent would win the race against exactly the normal-priority successor it was meant to yield
to. Three properties matter when diagnosing a wait that looks longer than the queue explains:

- **Default and better priorities are unaffected.** `priority=10` or lower claims on the first eligible poll, with no
  window and no marker churn.
- **The window is bounded and priority-scaled**, `min((priority - 10) * 3, 60)` seconds with the default
  [`runner_slots`](../configuration.md#runner_slots) settings — 30s at `priority=20`, capped at 60s from `priority=30`
  up.
- **It exits early and resets.** The waiter defers only while some live, unstarted agent that has not yet parked holds a
  better priority; on the first poll where no such agent remains it claims immediately. The window measures _continuous_
  eligibility, so losing eligibility (a full cap, for example) clears it and the next window starts from scratch. This
  is deference only: no running agent is preempted and no waiter's priority improves over time.

The agent's own log records the transition with a single `Deferring for up to Ns (priority N)` line, and `waiting.json`
carries `eligible_since` for the window currently in progress.

An explicit priority is also visible in ACE, which is usually the fastest way to confirm which value the queue actually
used. `QUEUED` rows with an authored threshold suffix the rank with the slot marker and priority
(`QUEUED #4/4 ▶10→9 p20`), and the agent detail pane appends `· priority N` to its `runners: N/M in use · queue #P of Q`
line. The queue ladder shows any normalized non-default value as `pN` beside the entry it reordered. Press `w` on the
agent to open the wait modal and edit the priority in place.

To diagnose a wait:

1. Check active, queued, and waiting agents with `sase agent list` or the ACE Agents tab.
2. Inspect the launch's `waiting.json`. `wait_runners` is the effective existing-runner threshold and
   `slot_requested_at` is its FIFO request time; `runner_slot_queue_position` in `sase agent list -j` is its current
   priority/FIFO rank among all live slot waiters. `wait_priority` is the value that rank used, and
   `wait_priority_explicit` distinguishes a deliberate `priority=N` from the implicit `10` default.
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
closed for that poll, remains parked, releases the slot lock, and retries instead of crashing or silently admitting
against configuration alone.

A `%wait(runners=0)` launch is intentionally a drain barrier: it starts only at a true global lull. Newer immediate
slot-participating launches may start while the barrier is parked when their own thresholds permit it, keeping the
barrier waiting until they also finish. The barrier is a drain condition, not an exclusive fence: after it is admitted,
later work can still start whenever its own threshold permits.
