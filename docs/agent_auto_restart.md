# Agent Auto-Restart

If a sase update breaks a running agent before it did any model work, sase puts it back
once, under the same name, and tells you exactly what it did and why.

An automatic restart is `,x` plus an unmodified submit, run headlessly. Each lineage
gets one automatic restart. Every other update-shaped failure is surfaced with its
reason and never silently swallowed.

## When a restart happens

Three things must all hold before sase relaunches anything:

1. **Signature.** The error belongs to a known update-skew family: a torn `ImportError`
   / `ModuleNotFoundError` / module `AttributeError` in sase's own code, a stale
   `sase_core_rs` binding or wire schema, or a data-format skew ("written by a newer
   sase version"). A matching error pattern alone is never enough. `TypeError` /
   `NameError` signature mismatches are always treated as real bugs and only annotated.
2. **Witness.** At least one independent witness must corroborate the update: the
   runner's boot code identity no longer matches the current tree (W1), a `sase update`
   journal row falls between boot and the failure (W2), or file-level proof names the
   culprit commit (W3).
3. **Probe.** A fresh interpreter must import the current versions of every managed
   module on the failing traceback (W4), proving the new tree is healthy and the death
   was the swap, not the code.

The healer also waits for **quiescence**: no update holds the code-swap writer lock and
the tree has been quiet for `quiescence_seconds`. A pass that cannot act yet defers (up
to `max_defer_seconds`) instead of giving up.

## Phases and modes

Only deaths **before the model turn** are relaunched (`booting`, `waiting`,
`preparing`):

| Death phase                                         | Mode                   | What happens                                                  |
| --------------------------------------------------- | ---------------------- | ------------------------------------------------------------- |
| Before the model turn                               | `relaunch`             | Relaunched once under the same name                           |
| After the model turn (`provider_running` and later) | `notify_post_provider` | Not relaunched; you are notified with held-workspace guidance |
| Plan, question, monitor, gate, or pipe handoff      | `ask`                  | Not relaunched; you are asked to decide                       |

Never restarted: provider errors, rate limits, auth, kills and cancels,
OOM/timeout/disk-full, directive or macro errors, tool and test failures, and any
`ImportError` from workspace or third-party code. Anything the restart planner refuses
is also left alone.

Skipped on purpose, every time: killed or dismissed agents, agents mid-`,x`, and agents
holding a question or gate. User intent wins.

## The ledger and the one-restart guarantee

Claims live outside every artifacts directory under `~/.sase/agent_auto_restart/` so a
workspace wipe can never remove them:

- `ledger/<project>__<lineage_root>.json` — one record per lineage, claimed atomically
  before any mutation.
- `doorbell/<project>__<artifacts_timestamp>.json` — dropped by the dying runner;
  deleted once a ledger record owns the failure.
- `episodes/<episode_slug>.report.json` — the live per-episode report, re-rendered on
  every change.
- `state.json` — storm-breaker pause state.

The state machine is `claimed → deferred | declined | launching`, then
`launching → launched | settled_failed` and `launched → settled_ok | settled_failed`. A
replacement that fails again is reported and never retried. When a claimer died
mid-launch, a later pass adopts the replacement it finds or settles the record as failed
— it never launches twice, because forced name reuse would wipe the replacement it just
started.

Update episodes are grouped by culprit commit (for example `sase@9fd8a08`), so one
update that breaks five agents produces one story, not five.

## CLI

A bare `sase agent auto-restart` lists ledger records, newest first, grouped by episode.

| Command                                                                           | Purpose                                                                                     |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `list [-a/--all] [-j/--json]`                                                     | Ledger records, newest first, grouped by episode                                            |
| `resume`                                                                          | Re-arm after the storm breaker trips                                                        |
| `run (NAME \| -a/--artifacts-dir DIR \| -p/--pending) [-n/--dry-run] [-j/--json]` | Run the healer; `-p` is the scheduler job's target and a manual run still honors the ledger |
| `scan [-j/--json] [-l/--limit N] [-s/--since DURATION]`                           | Read-only replay of the classifier over history; never writes the ledger                    |
| `show TARGET [-j/--json]`                                                         | One card: verdict, witness checklist, state timeline, evidence paths                        |

## Configuration

```yaml
agent_auto_restart:
  enabled: true # permanent kill switch
  quiescence_seconds: 30 # tree-quiet wait before acting
  max_defer_seconds: 1800 # longest a claim waits for quiescence
  pending_resurface_seconds: 600 # stale pending rows are re-surfaced loudly
  storm_max_per_episode: 12 # storm breaker: launches per episode
  storm_max_per_30m: 20 # storm breaker: launches per 30 minutes
```

Set `enabled: false` to turn the feature off permanently. While off or paused, pending
failures are re-surfaced loudly instead of healed, and the ledger is never written —
disabling never swallows a failure and never spends a lineage's one restart.

## Notifications

One upserted amber `↻` row per update episode (`sender=agent.auto-restart`,
`action=ViewReport`). The first relaunch creates the row and its single information
toast; every further relaunch in the episode appends one `+1` note without toasting and
refreshes the title and the inline report snapshot in place. The title never contains
"fail" or "error"; exception text appears only in note 2 or later.

The live report (headline, update/culprit/witness facts, per-agent rows with a live
**Now** column, left-alone bullets, why-text, prevention line) is linked from the row.
Escalations are loud and land in the Errors bucket: post-provider deaths name the held
workspace, declined relaunches name the reason, re-broken replacements say sase will not
retry, and a tripped storm breaker pauses the feature until
`sase agent auto-restart resume`.

In the Agents tab, in-flight recoveries render as amber `↻ RESTARTING` with a dim reason
instead of red `FAILED`. The replacement keeps the same name with a `↻` chip and a
provenance block naming the update, the signature, and the preserved `error_report.md`
(opened with the existing `v` key).

## Troubleshooting

- **`auto-restart never ran — is the sase scheduler running?`** The row sat `pending`
  past `pending_resurface_seconds` with no ledger record. Start the scheduler; nothing
  was claimed or spent.
- **"Couldn't restart \<name> automatically — \<reason\>."** The classifier, probe, or
  quiescence gate declined. Press `,x` on the row to retry by hand.
- **"This was its automatic restart — not retrying."** The replacement broke again. Its
  one restart is spent; investigate it as a real failure.
- **"Auto-restart paused: N agents broke within one update."** The storm breaker
  tripped. If the update really is that breaking, run `sase agent auto-restart resume`
  to re-arm.
- **`sase agent auto-restart scan -s 120d`** replays the classifier over history
  read-only. Zero `relaunch` verdicts among non-skew failures means the classifier is
  not over-eager.
- **Evidence.** Every relaunch preserves the error report, traceback, log tail, facts,
  and verdict in the recovery bundle linked from the ledger record (`show TARGET`) and
  the episode notification.
