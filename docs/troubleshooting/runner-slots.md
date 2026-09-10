# Agent queued for a runner slot

An agent shown as `QUEUED` is at an admission boundary: it has finished every
dependency, bead, and time wait and is holding only for runner capacity or an explicit
runner-count condition. The effective global `max_running_agents` value is an integer
capacity budget (configured default: 10). A normal launch claims `1.0` unit, while
`%queue(weight=...)` / `%q(w=...)` can request a positive finite fractional or larger
weight. An authored `%queue(runners=N)` is an additional count condition over occupied
participating lanes; it cannot bypass the global capacity budget.

The ACE Agents header summarizes the same global capacity state as `C/L` before the
status strip, for example `8.0/10.0 [8 running · 1 queued]`: occupied capacity units,
effective limit, and live waiters at the runner-capacity admission gate. The effective
value is an active machine-wide override from `~/.sase/max_running_agents_override.json`
first and merged configuration second. The queued count includes implicit-cap waits and
authored `runners=` waits.

Admission starts the first waiter that fits the current capacity and any explicit
runner-count condition, ordered by lower numeric `%queue(priority=N)` first and then
first-in, first-out within the same priority. Non-fitting waiters are skipped instead of
blocking later waiters that can run. ACE shows currently eligible waiters first, then
parked waiters by current blocker severity, with priority/FIFO preserved inside each
group. Priority defaults to `10` and does not age, so sustained higher-priority arrivals
can starve default- or lower-priority waiters. Parallel family members wait for their
own capacity even when ACE renders them as nested rows. Serial members ride a family
claim that is already live; after a processless gate releases capacity, the successor
must transfer a still-live claim or reacquire capacity normally. Workflow Python/bash
steps and axe Patch runners hold none of this capacity.

The bundled task and epic phase xprompts used by `sase bead work` do not set an authored
wait priority. The bundled epic lander authors `%q(w=2.0)`, so it claims two capacity
units once its rendered phase-DAG, bead-dependency, or other waits resolve. A project,
user, config, or plugin override of any bundled xprompt supplies its own body and may
choose a different priority or weight.

Selecting a ranked waiter in ACE also shows a bounded `QUEUE` ladder in that same
capacity-aware order. Its `N ahead` count is the number of earlier ladder entries.
Entries whose capacity or count condition is not currently satisfied use a parked
amethyst accent wherever they appear; the accent is display context, not a different
status, because every entry is still `QUEUED`. The heading adds `N parked` when any
waiter is currently blocked. The ladder includes the front, up to two entries on either
side of the selected waiter, and gap counts; short queues show all entries, while long
queues show at most seven actual queue entries. Explicit thresholds, non-default
priorities, and non-default weights appear as `≤N`, `pN`, and `wN`. This is current
admission context, not an ETA or a prediction that no new waiter will arrive, and its
entries are not digit-jump targets.

A deprioritized waiter — one whose priority is numerically worse than the `10` default —
is additionally held back for a bounded deference window before it may claim a freed
slot, because the sort above only compares waiters already parked at that instant.
Dependency-chained work joins the queue seconds after its predecessor exits, so without
the window a long-parked `priority=20` agent would win the race against exactly the
normal-priority successor it was meant to yield to. Three properties matter when
diagnosing a wait that looks longer than the queue explains:

- **Default and better priorities are unaffected.** `priority=10` or lower claims on the
  first eligible poll, with no window and no marker churn.
- **The window is bounded and priority-scaled**, `min((priority - 10) * 3, 60)` seconds
  with the default [`runner_slots`](../configuration.md#runner_slots) settings — 30s at
  `priority=20`, capped at 60s from `priority=30` up.
- **It exits early and resets.** The waiter defers only while some live, unstarted agent
  that has not yet parked holds a better priority; on the first poll where no such agent
  remains it claims immediately. The window measures _continuous_ eligibility, so losing
  eligibility (a full cap, for example) clears it and the next window starts from
  scratch. This is deference only: no running agent is preempted and no waiter's
  priority improves over time.

The agent's own log records the transition with a single
`Deferring for up to Ns (priority N)` line, and `waiting.json` carries `eligible_since`
for the window currently in progress.

An explicit priority is also visible in ACE, which is usually the fastest way to confirm
which value the queue actually used. `QUEUED` rows with an authored threshold suffix the
rank with the slot marker and priority (`QUEUED #4/4 ▶10→9 p20`), and the agent detail
pane appends `· priority N` to its `runners: N/M in use · queue #P of Q` line. The queue
ladder shows any normalized non-default value as `pN` beside the entry it reordered.
Press `w` on the agent to open the wait modal and edit the priority in place.

To diagnose a wait:

1. Check active, queued, and waiting agents with `sase agent list` or the ACE Agents
   tab.
2. Inspect the launch's `waiting.json`. `wait_runners` is the effective existing-runner
   threshold and `slot_requested_at` is its FIFO request time;
   `runner_slot_queue_position` in `sase agent list -j` is its current capacity-aware
   display rank among all live capacity waiters. `queue_weight` is the requested
   capacity units, and `wait_priority` is the value used inside each eligible or parked
   ordering group. `wait_priority_explicit` distinguishes a deliberate `priority=N` from
   the implicit `10` default.
3. Press fixed `Ctrl+R` in Launch Control to edit `max_running_agents` persistently or
   apply/clear a temporary value. Parked agents reread the effective capacity budget and
   normally react within about two seconds. Setting another temporary value replaces the
   first; expiry or Clear resumes configured behavior.
4. Kill an unwanted parked agent normally. Dead or stale waiter PIDs are ignored
   automatically and cannot wedge the queue. A crashed running process likewise stops
   consuming a slot as soon as its PID is observed dead.

The slot gate runs in each agent process under a global file lock. It does not depend on
the axe daemon, so restarting axe does not release or repair a slot wait. Immediate
slot-participating launches become admitted before primary and linked-workspace
preparation; dependency, time, and fork waiters do not consume a slot until those
prerequisites resolve.

After upgrading from a build that did not enforce weighted capacity, restart ACE and
AXE, then let old runner processes drain or relaunch them. The new runtime treats legacy
records with absent `queue_weight` as `1.0`, but that storage compatibility does not
make a mixed old/new scheduler fleet safe: an old runner binary cannot enforce weighted
claims for new work.

A modern unanswered `QUESTION` is a gate shell and consumes no runner capacity. On
answer, its next family member transfers or reacquires the family capacity claim through
the locked queue. Existing compatibility runs may instead carry `pending_question.json`;
that marker remains authoritative while the user decides and while the same process is
queued to resume. Killing a legacy run during either pause cleans up its question and
queue markers, and its authored priority is retained while reacquiring.

Lowering the effective cap below current occupied capacity is safe and non-preemptive:
no running process is killed or forced to yield, but no participant is admitted until
capacity falls far enough. Raising it does not bypass priority/FIFO order. If the
bounded temporary-state lock or file read is briefly unavailable, a launch fails closed
for that poll, remains parked, releases the slot lock, and retries instead of crashing
or silently admitting against configuration alone.

A `%queue(runners=0)` launch is intentionally a drain barrier: it starts only at a true
global participating-lane lull and when enough capacity is free for its requested
weight. Newer immediate launches may start while the barrier is parked when their own
conditions permit it, keeping the barrier waiting until they also finish. The barrier is
a drain condition, not an exclusive fence: after it is admitted, later work can still
start whenever its own conditions permit.
