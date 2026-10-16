---
title: Recover an interrupted agent
description: Check whether an interrupted agent restarts itself, retry it, or revive it.
---

# Recover an interrupted agent

This guide recovers an agent that died or vanished: one interrupted by a live update,
one the restart service declined, or one dismissed from the active list. It assumes you
have the agent's name; if the run never started, see
[Unstick a queued agent](unstick-queued-agent.md) instead.

## Before you start

You need the agent's name as shown on the Agents tab or in `sase agent list`. Recovery
keeps the same name and preserves the failure evidence with the new run.

## 1. Check whether it restarts itself

Agents interrupted by a live update restart automatically, once per run. List the
pending and settled records, newest first:

```bash
sase agent auto-restart list -a
```

A `launching` or `launched` record means recovery is already moving; watch the Agents
tab for the amber `↻ RESTARTING` row. A `declined` record names its reason: provider
errors, rate limits, kills, and post-model-turn deaths never restart automatically.

## 2. Retry a declined agent by hand

When the record says the run could not restart automatically, retry it yourself from the
Agents tab. Its one automatic restart is spent only when a replacement already ran and
broke again; anything else is a real failure worth investigating as one.

## 3. Re-arm after a storm pause

When many agents break in one update, the storm breaker pauses automatic recovery with
an "Auto-restart paused" message. Re-arm it once the update proves safe:

```bash
sase agent auto-restart resume
```

## 4. Revive a dismissed agent

Dismissed runs never restart on their own. Select the run on the Agents tab and revive
it (`!R`, or `R` to retry), then audit what happened:

```bash
sase revive-log --limit 20
```

## If it goes wrong

Replay the classifier over recent failures without touching anything:

```bash
sase agent auto-restart scan -s 7d -l 50
```

The scan is read-only and explains each verdict. A row that sits `pending` with no
ledger record means the scheduler is not running; start it and nothing was spent. For
anything else, start with [Diagnose problems with sase doctor](diagnose-with-doctor.md).

## Related

- [Agent auto-restart](../reference/agent-auto-restart.md) — eligibility, evidence, and
  current limits.
- [Agent revive log](../reference/agent-revive-log.md) — the audit record schema.
- [Automation and human checkpoints](../concepts/automation.md) — why recovery pauses
  for decisions.
