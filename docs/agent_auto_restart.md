# Agent Auto-Restart

SASE has a recovery service for agents interrupted by a live update. It classifies the
failure, records its evidence, and can relaunch an eligible agent under the same name.
It is enabled by default and runs through the scheduler's `agent_auto_restart` job. The
[current limitations](#current-limitations) below affect which failures actually reach
relaunch.

An automatic restart uses the same stop, wipe, and relaunch machinery as
[`sase agent restart NAME`](cli.md), with preserved failure evidence and the live
autonomy profile. Each lineage (the original run and its retry chain) gets at most one
automatic restart. A claimed lineage that is later declined cannot be automatically
retried. Manual restart remains available.

## When a restart happens

The classifier recognizes specific update-skew signatures and checks corroborating
evidence. W1 means the runner's boot code identity differs from the current tree; W2
means an update journal entry falls between boot and failure; W3 is file-level evidence
of a changed symbol or culprit commit; W4 is a successful fresh-interpreter import
probe.

| Failure family                                                | Core classifier requirement for a relaunch verdict                                |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Torn Python imports or module attributes in SASE-managed code | Matching signature, W1 or W2, and W4                                              |
| Stale `sase_core_rs` binding or wire schema                   | Matching signature and W4; without a probe, W1 or W2 permits deferral for probing |
| Data-format skew, such as "written by a newer sase version"   | Matching signature and W1 or W2                                                   |
| Managed-code `TypeError` signature mismatch or `NameError`    | Annotate only; never automatically relaunch                                       |

W3 helps explain and group the incident; it does not independently authorize a relaunch.
The healer also runs an import probe before executing a relaunch, including for a
data-format verdict. A successful import checks that current modules load; it does not
run the agent's task or its tests.

The healer also waits for **quiescence**: no update holds the code-swap writer lock and
the tree has been quiet for `quiescence_seconds`. A pass that cannot act yet defers (up
to `max_defer_seconds`) instead of giving up.

## Phases and modes

Current runners write lifecycle markers. A known death **before the model turn**
(`booting`, `waiting`, `preparing`) is eligible; a known later phase is not:

| Death phase                                         | Mode                   | What happens                                                  |
| --------------------------------------------------- | ---------------------- | ------------------------------------------------------------- |
| Before the model turn                               | `relaunch`             | Relaunched once under the same name                           |
| After the model turn (`provider_running` and later) | `notify_post_provider` | Not relaunched; you are notified with held-workspace guidance |
| Plan, question, monitor, gate, or pipe handoff      | `ask`                  | Not relaunched; you are asked to decide                       |

Older records without lifecycle markers use traceback and log heuristics. The current
classifier also allows an `unknown` phase to reach a relaunch verdict when its signature
and witness checks pass; it does not require affirmative proof of a pre-provider phase
for those records.

Never restarted: provider errors, rate limits, auth, kills and cancels,
OOM/timeout/disk-full, directive or macro errors, tool and test failures, and any
`ImportError` from workspace or third-party code. Remote rows are also excluded.
Anything the restart planner refuses is also left alone.

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

A bare `sase agent auto-restart` delegates to `list`, which shows pending claims, newest
first and grouped by update episode. Use `list -a` to include launched, settled, and
declined records.

| Command                                                                           | Purpose                                                                                                           |
| --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `list [-a/--all] [-j/--json]`                                                     | Pending ledger claims (`claimed`, `deferred`, `launching`); `-a` includes launched, settled, and declined records |
| `resume`                                                                          | Re-arm after the storm breaker trips                                                                              |
| `run (NAME \| -a/--artifacts-dir DIR \| -p/--pending) [-n/--dry-run] [-j/--json]` | Run the healer; `-p` is the scheduler job's target and a manual run still honors the ledger                       |
| `scan [-j/--json] [-l/--limit N] [-s/--since DURATION]`                           | Read-only replay of the classifier over history; never writes the ledger                                          |
| `show TARGET [-j/--json]`                                                         | One card: verdict, witness checklist, state timeline, evidence paths                                              |

```bash
sase agent auto-restart list -a
sase agent auto-restart show my-agent
sase agent auto-restart scan -s 7d -l 50
```

`show` accepts a ledger key, lineage root, or agent name. `scan` defaults to the last
seven days and 50 displayed rows; `-l` must be positive and limits only the human table.
The summary and `-j` output cover the entire matching set. A scan collects evidence and
classifies history without running W4, so `defer` can mean that the import probe is
still needed.

For a non-empty resolved target set, `run -j` returns one JSON envelope and currently
exits `0` even when an individual outcome is `error`. Inspect every `outcomes[].action`
and `reason`. Without `-j`, an `error` outcome exits `1`. An empty target set prints
`No pending failures to heal.` even with `-j`; a disabled healer exits `3` without a
JSON envelope.

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

Set `enabled: false` to disable automatic recovery. `run` then refuses before claiming
or relaunching anything. While disabled or paused, the scheduler resurfaces pending
failures instead of submitting healer work, so that scheduler path does not spend a
lineage's restart. A manual `run` during a storm pause can still claim or decline a
record; clear the pause with `resume` before requesting recovery.

See the [configuration reference](configuration.md#agent_auto_restart) for field types
and defaults. `resume` clears a storm pause; it does not turn a disabled setting back on
or reset a lineage's record.

## Current limitations

- **Python and binding skew can stay deferred after a passing probe.** Input assembly
  supplies W1–W3 but no W4. The classifier returns `defer` for eligible Python/binding
  failures, and the healer runs the probe without updating the witnesses or
  reclassifying. It retains the original `defer` verdict even if imports pass. These
  claims can remain deferred until `max_defer_seconds` expires. Inspect `show TARGET`
  and use `sase agent restart NAME` or the TUI's `,x` when manual recovery is needed.
- **`run --dry-run` is not a full eligibility preview.** For an unclaimed lineage it
  returns before signature, witness, probe, or restart-planning checks. For an existing
  stale claim it can enter recovery paths that write a deferred ledger record or update
  the failed row's recovery marker. Use `scan`, `list`, and `show` for read-only
  inspection.
- **Legacy phase and JSON behavior have limits.** Unknown phases are not categorically
  excluded, and JSON behavior is as described above. Inspect the verdict and evidence
  rather than treating command success as proof of relaunch.

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

Dependency waits remain parked while recovery is `pending`, `deferred`, or `launching`.
Name-based waits find the replacement by name; waits pinned to the old artifacts
directory can follow the ledger's replacement mapping after the wipe. They then wait for
the replacement's actual outcome.

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
