# Agent waiting for a runner slot

An agent shown as `WAITING` on runner slots has finished its dependency and time-based waits, but has not yet entered
the execution loop. SASE limits live root agents globally using `max_running_agents` (default: 10). A prompt can use
`%wait(runners=N)` to override the threshold for that launch.

The queue is first-in, first-out across all projects. A live earlier waiter is therefore allowed to start before later
launches, even when a later launch has a higher threshold. Child agents are exempt so a running parent can safely wait
for child work.

To diagnose a wait:

1. Check active and waiting agents with `sase agent list` or the ACE Agents tab.
2. Inspect the launch's `waiting.json`. `wait_runners` is the effective existing-runner threshold and
   `slot_requested_at` is its FIFO queue time.
3. Raise `max_running_agents` in `sase.yml` if more concurrency is safe. Parked agents reread configuration and normally
   react within about two seconds.
4. Kill an unwanted parked agent normally. Dead or stale waiter PIDs are ignored automatically and cannot wedge the
   queue.

The slot gate runs in each agent process under a global file lock. It does not depend on the axe daemon, so restarting
axe does not release or repair a slot wait. A `%wait(runners=0)` launch is intentionally a drain barrier: it starts only
after all currently running root agents finish, and later launches queue behind it.
