# Agent waiting for a runner slot

An agent shown as `WAITING` on runner slots has finished its dependency and time-based waits, but has not yet entered
the execution loop. SASE limits live root agents globally using `max_running_agents` (default: 10). A prompt can use
`%wait(runners=N)` to override the threshold for that launch.

Admission is first-in, first-out among waiters that are eligible at the current running count, across all projects. An
older low-threshold waiter does not block a later launch whose higher threshold currently permits it to run. Child
agents are exempt so a running parent can safely wait for child work.

To diagnose a wait:

1. Check active and waiting agents with `sase agent list` or the ACE Agents tab.
2. Inspect the launch's `waiting.json`. `wait_runners` is the effective existing-runner threshold and
   `slot_requested_at` is its FIFO time among currently eligible waiters.
3. Raise `max_running_agents` in `sase.yml` if more concurrency is safe. Parked agents reread configuration and normally
   react within about two seconds.
4. Kill an unwanted parked agent normally. Dead or stale waiter PIDs are ignored automatically and cannot wedge the
   queue. A crashed running process likewise stops consuming a slot as soon as its PID is observed dead.

The slot gate runs in each agent process under a global file lock. It does not depend on the axe daemon, so restarting
axe does not release or repair a slot wait. Immediate roots become admitted before primary and linked-workspace
preparation; dependency, time, and fork waiters do not consume a slot until those prerequisites resolve.

A `%wait(runners=0)` launch is intentionally a drain barrier: it starts only at a true global lull. Newer immediate
roots may start while the barrier is parked when their own thresholds permit it, and those roots keep the barrier
waiting until they also finish. The barrier is a drain condition, not an exclusive fence: after it is admitted, later
work can still start whenever its own threshold permits.
