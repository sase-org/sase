---
title: Unstick a queued agent
description: Tell capacity waits apart from holds and clear whichever blocks the agent.
---

# Unstick a queued agent

This guide frees an agent shown as `QUEUED`. It assumes the agent finished its
dependencies and waits: dependency, bead, and time waits clear on their own and are not
covered here.

## Before you start

You need `sase agent list` (or the Agents tab) showing the stuck run. A row that ends
with `held by …` waits on a hold; any other `QUEUED` row waits on runner capacity.

## 1. Clear a capacity wait

Check the fleet load in the Agents header (`load: 8/10` means 8 of 10 capacity units are
taken) and pick one:

- Wait for a slot: waiters start in priority order as running agents finish, with no
  action needed.
- Raise the cap briefly: press `Ctrl+R` in Launch Control to set a temporary
  `max_running_agents`. Parked agents react within about two seconds.
- Kill an unwanted parked agent normally: dead waiter processes are ignored
  automatically and cannot wedge the queue.

Lowering the cap below current load is safe and never kills running work; admission
simply pauses until capacity frees up. Confirm the agent leaves `QUEUED` on its next
poll.

## 2. Clear a hold

A hold keeps its agents queued even when capacity is free. List active holds and release
the one that matches:

```bash
sase agent hold list
sase agent hold release -k <armer-key>
```

The held agent is admitted on its next poll if capacity allows. Otherwise the hold ends
by itself when its armer ends or its TTL expires. Report and prune holds whose armer
died with:

```bash
sase doctor -C agent_holds.stale
```

## If it goes wrong

A wait that matches neither capacity nor a hold is a different gate: run
[Diagnose problems with sase doctor](diagnose-with-doctor.md) and inspect the run's
`waiting.json` as described in [Runner slots](../reference/runner-slots.md).

## Related

- [Runner slots](../reference/runner-slots.md) — admission budgets, weights, priorities,
  and every `waiting.json` field.
- [Agents, sessions, and workspaces](../concepts/agents.md) — how delegated work runs.
