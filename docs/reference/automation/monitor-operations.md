---
title: Monitor operations
description: Inspect, stop, and view monitors in the SASE TUI.
---

# Monitor operations

This page names how to inspect, stop, and view monitors in sase's TUI.

## Inspecting and stopping monitors

```bash
sase monitor list                          # active monitors, newest first
sase monitor list --all --agent acme       # include finished monitors for one agent
sase monitor list --status failed --status timeout

sase monitor show <id>                     # details plus an output tail
sase monitor show <id> --follow            # stream new output until it finishes
sase monitor show <id> --all-lines --output-only
sase monitor show <id> --diagnostics       # selected failed-stage diagnostics
sase monitor show <id> --range 0:65536     # retained raw-output byte range
sase monitor resume <id> [-j] [-k checkpoint.yml] [-m codex/gpt-5]

sase monitor stop [<id>]                   # stop a running monitor; omit id to target
                                            # the calling agent's active monitor
```

`ID` accepts a monitor id (or unique prefix), the monitor turn's agent name, or the
owning sase-agent name. `sase monitor stop` never launches the recorded follow-up agent,
even when `--next` was given.

`sase agent kill -n <name>` uses the same stop behavior when the name resolves to a live
monitor member or its owner. `sase monitor stop` remains the clearest explicit form.

Every subcommand can emit machine-readable output, but not with the same flag: `start`,
`list`, `resume`, and `stop` take `-j/--json`, while `list` and `show` take
`-f/--format` (`table`/`markdown`/`json` for `list`, `markdown`/`json` for `show`).
`sase monitor show` has **no** `-j` — use `--format json` there. Short options also
differ by subcommand: `-f` is `--completion` on `start` but `--format` on `list` and
`show`, and `-a` is `--agent` on `start` but `--all` on `list`, where `-l` is `--agent`.
See `sase monitor --help` and each subcommand's `--help` for the complete flag
reference, or the [CLI command groups](../cli/index.md).

`--diagnostics` reads the bounded stage diagnostics selected for a failed monitor;
`--range START:END` reads a bounded byte interval from retained raw output. Both default
to at most 65,536 bytes and accept `-b/--max-bytes`. They are snapshot modes, so neither
can be combined with `--follow`; diagnostics and ranges are mutually exclusive, and a
range cannot be combined with `--all-lines`.

`sase monitor resume <id>` reconciles a terminal monitor's frozen result and launches an
eligible requested follow-up without rerunning the monitored command. Repeating a
successful resume returns the same acknowledged successor. Supplying `-k/--checkpoint`
or `-m/--model` creates an immutable manual-recovery branch only when the original
delivery was not already acknowledged. Concurrent receiver adoption is revalidated under
the delivery lock before any undelivered branch is fenced, so an acknowledged delivery
is never overwritten. A dispatching branch whose launch receipts or process identity
cannot prove the receiver uninvoked is recorded as `needs_attention` instead of spawning
another successor. When settlement recorded a follow-up as `not-launchable` only because
the starter had not settled in time, resume first repairs that missing parent link.
Ineligible monitors — still running, stopped or lost, fire-and-forget, owned by host
completion, or already delivered, among others — make `resume` exit `2` and print the
precise eligible resume command to stderr when one exists; with `-j`, the JSON result
carries `code` and `suggested_command` fields. If the starter settled but its
continuation capture failed, the `not-launchable` error names that capture failure and
gives the `-k FILE` / `-m MODEL` resume command.

If a proc-backed monitor loses its supervisor, its failure message in
`sase monitor show` and `done.json` includes `last supervisor error: <line>` when the
supervisor log has a readable diagnostic. SASE reads only the last 4 KiB and caps the
final non-empty line at 500 characters. Disk-exhaustion errors include a `disk full`
hint. A missing, empty, or unreadable log leaves the generic loss message. Lost monitors
do not automatically launch a follow-up.

Log write failures keep draining command output, recording an incomplete log without
changing a known command exit. If settlement runs out of disk space or quota, the
supervisor retries for up to 70 minutes, allowing housekeeping to reclaim space. A
successful retry publishes the original command result.

Reading monitors also performs dead-supervisor reconciliation. `sase monitor list`, the
sase's TUI Agents tab refresh path, and the axe scheduler look for running monitor turns
whose supervisor identity is no longer alive. Shared outcome freeze lives in the Rust
proc store: `begin_proc_settlement` persists the observed status, reason, exit code, and
command-end time under the same lock that moves the proc into `settling`. Python keeps
process control and settlement side effects and must consume that frozen observation.
Same-boot dead supervisors whose command was never observed are reconciled to `failed`
on the artifact path, or `lost` on the proc-backed path: SASE kills a leftover process
group only when no frozen or sidecar evidence shows the command has already exited,
finalizes the log, disposes the workspace claim, and launches or records the follow-up
disposition. A same-boot supervisor that already froze a command result resumes that
result and applies the original continuation policy once. Pre-reboot supervisors without
a frozen observation reconcile to `lost`; their command effects are unknown, so the
follow-up is recorded as not launched. A frozen observation survives reboot without
changing its facts. The follow-up error for an unknown outcome does not claim a reboot
unless the persisted termination reason is `reboot`.

## In sase's TUI

A monitor row renders with an amber `⚙` glyph beside the agent list's bash/python step
glyphs and omits a left-side title — identity is the right-hand `%id`
(`<session>--mon`), not the configured monitor label or command. A live elapsed suffix
shows while running, or an exit-code / timeout badge once terminal. Monitor turns appear
in the session roster and contribute to the session's total runtime (unlike a gate turn,
whose window is a human wait and is excluded from that total), but — like workflow steps
— they are not counted as agents in the
[Statistics tab](../tui/machines-and-tools.md#statistics-tab) or tribe/clan summaries: a
session with one agent and one monitor turn is a one-agent session that ran one command.
A collapsed session or clan container row carries an amber `⚙N` badge for its running
monitors and a grey `⚙N` badge for its finished ones, so both counts are visible without
expanding the subtree; the two badges partition the subtree's monitors exactly, and a
failed, timed-out, or lost monitor counts in the finished (grey) lane along with a clean
completion. The tribe panel title aggregates both lanes across the whole tribe, so a
fully collapsed panel still reports running and completed monitored work.

Selecting a monitor row keeps the ordinary agent header and renders a `MONITOR` detail
section in place of the usual prompt and reply body. It opens with compact `Result`,
`Next`, and `Evidence` rows, then shows the shell-highlighted `Command`, whichever of
`Cwd`, `Reason`, `Next action`, `Next model`, `Next output`, profile, policy, and
completion fields were recorded, then `Status` (the effective label in its pair accent,
with the other half dim after a `→`) and `State` (a colored glyph plus the machine state
name, with `(exit N)` appended once an exit code is known). `Timeout` reports elapsed
time against the budget (`3m12s of 45m0s budget`), falling back to a plain `Elapsed` row
for a record with no recorded budget, and an `--idle-timeout` adds its own
`Idle timeout` row. Next come the full `Monitor id`, its short form, and the exact
`sase monitor show <short-id> --follow` command to stream the rest from a shell. When
recorded, trailing rows show a follow-up error (`Follow-up`) or degradation
(`Degraded`), the host-completion status (`Host final`), and the evidence and
continuation locators: `Diagnostics`, `Retained log`, `Result ref`, `Checkpoint`,
`Node ref`, `Manifest`, `Budget`, and `Saved prompt`.

Beneath that, an `OUTPUT` block renders the captured stdout/stderr. Because
`live_reply.md` holds a command's raw merged output rather than prose, it is rendered as
a plain ANSI-aware log rather than through the markdown path used for agent replies, and
a monitor whose retained output was capped shows an
`… output truncated (head + tail retained) …` notice above it. A monitor that has not
written anything yet shows `No output yet.`.

When the monitor's session (or its starter) is selected, that same block appears inline
as a `MONITOR` phase in the AGENT REPLY stream, at the starter's position in the session
conversation: an amber `⚙ MONITOR` divider, the command, the recorded detail fields, and
the full captured output. File-hint mode renders the monitor document with `[N]` markers
on the command and log instead of falling back to the empty prompt view.

With a **running** monitor row selected, the Agents tab's kill key (`x` by default)
stops the monitor instead of killing an agent: it opens a `Stop Monitor` confirmation
that defaults to **Keep running**, and confirming runs the same `stop_monitor` path as
`sase monitor stop`, so no follow-up agent launches. On a settled monitor row, `x`
behaves like an ordinary dismiss. See
[Agent Row Glyphs](../tui/agent-row-glyphs.md#agent-row-glyphs-1) and
[Sequential Agent Sessions](../agents/agent-sessions.md#sequential-agent-sessions).

A monitor row is also a fork target, active or settled: `F` opens a prompt prefilled
with `#fork:<id>`, where `<id>` is the monitor's exact durable proc ID (not the reusable
`<session>--mon` proc name), so a later monitor that reuses the same proc name can never
hijack an already-queued fork. The footer and prompt label still show the friendly proc
name. Because a monitor has no chat, retry, edit-chat, and rename are never offered for
it. The injected fork content is the same command execution record described above
(`Command`, `Status`/`State`, timeout/elapsed, and the captured `OUTPUT`), explicitly
labeled as untrusted program output rather than a prior conversation. An implicit
`%wait` on a monitor fork target releases on that monitor's terminal state — completed,
failed, timed out, stopped, or lost — not only on a clean completion.

## Visibility

A stalled monitor handoff — a supervisor that never reported a real outcome, or a
follow-up that never launched — is not something a project owner should have to notice
by its absence. Two independent conditions render distinctly, in the Agents tab and
`sase monitor list`, wherever the plain exit-code/timeout badges above do not already
cover them:

- **A terminal monitor with no recorded exit code.** A `failed` or `lost` monitor whose
  supervisor never reported a real exit code (died on arrival, or belongs to a previous
  boot) renders with a red `⚠` badge in place of the exit-code badge — the command's
  outcome is unknown, not merely non-zero.
- **A dropped or degraded follow-up.** A monitor whose outcome selected `continue` but
  did not launch, or launched degraded, renders with an amber `⚑` flag independent of
  the monitor's own state — a monitor can finish cleanly and still strand its follow-up.

`sase monitor list` marks the same monitor row with the `⚑` flag next to its `STATE`
cell (in both the table and `--format markdown` output) so a stalled handoff is visible
without `--json` plumbing; `sase monitor show <id>` prints a `Follow-up error` line for
a dropped follow-up and a `Follow-up degraded` line for a degraded one, and both
commands' JSON envelopes carry `followup_outcome` (`launched` / `launched-degraded` /
`not-launchable` / `host-completed`), `followup_error`, and `followup_degraded_reason`,
plus versioned `result`, `evidence`, `continuation`, and `context_budget` objects for
compact clients.

Ordinary continuation delivery is keyed by monitor result and outcome branch. SASE
reserves the successor identity before spawning it, and the intended receiver
acknowledges that reservation before its provider is invoked. Concurrent settlement or
reconciliation therefore discovers the same delivery instead of launching a duplicate
model turn. A dispatch that cannot be proved safe remains visible as not launchable or
needing attention with its saved prompt and delivery record.

Monitors themselves are notification-neutral: a monitor is an execution and handoff
mechanism, not a workflow that files notifications, so neither a completed monitor nor a
dropped `--next` appends a notification row. The badges and flags above, plus
`monitor_followup_outcome` / `monitor_followup_error` in `agent_meta.json` and
`done.json`, are the durable signals — read them with `sase monitor list`,
`sase monitor show <id>`, or the Agents tab. Two related notifications belong to other
features: an agent whose `%wait` targets a monitor that ended without a launchable
follow-up gets a `wait_checks` "never self-resolve" notification, and the approved-epic
launcher below releases the planner's completion notification when its monitor settles.

## Example: approved epic launches

Launching an approved epic (`sase bead work <plan> --yes-to-all …`) is itself a
long-running command, so it normally runs under a monitor rather than a bare detached
proc. Its monitor turn reads `EPIC APPROVED` while running and uses the configured
`EPIC CREATED` label after every terminal state, even failure, timeout, stop, or loss;
check the state and exit details instead of treating that label as success. A successful
launch attempts to back-fill the epic ID; when that metadata lands, the planner row
itself moves to `EPIC CREATED`, and otherwise it remains `EPIC APPROVED`. The launch
acquires an operational workspace lease for the project and runs in that leased
checkout, never in the user's primary checkout; the lease's claim moves to the monitor.
The monitor records an explicit zero queue weight, and no follow-up agent is recorded —
`sase bead work` launches the phase agents itself. If the planner's agent session cannot
be resolved (a very old artifacts layout, a wiped agent), the launch falls back to a
detached proc in the same leased workspace rather than silently dropping the approval.
Other monitor-start errors fail the approval instead of using the proc fallback. The
planner's completion notification is held until the launch monitor settles, folds in the
launch outcome, and is published once even if more than one settlement path observes the
result. AXE's `epic_launch_flush` job flushes a held notification whose launch never
settled after a 90-second grace period, with a resume command. See
[Plan Approval Flow](../work-units/bead-tui.md#plan-approval-flow) for the approval side
of that handoff.

The host-owned epic launcher keeps `sase bead work` as the visible logical command. If
an editable-source update is swapping that checkout when approval arrives, a minimal
pre-import bootstrap prints
`sase: waiting for the source-tree swap to finish before launching`, waits for the
shared lock, and only then starts `sase bead work` against one consistent source tree.
This waiting exception is specific to host-owned approved-epic launches; running
`sase bead work` directly remains fail-fast during a swap.

## Pipe vs. monitor

`sase pipe '<prompt>'` (the `/sase_handoff` skill) continues the run as a new session
member after the calling turn ends. Both commands support immediate and
[staged handoffs](../agents/agent-sessions.md#handoff-completion). A monitor runs and
waits on an OS command; nothing about the command's content is an LLM turn. Pipe hands
the agent's own unfinished _turn_ to a fresh successor: no command runs, nothing is
captured or timed out, and the successor's prompt is written by the agent, not derived
from a command's outcome.

Concretely:

|                         | Monitor                                      | Pipe                                            |
| ----------------------- | -------------------------------------------- | ----------------------------------------------- |
| What runs               | A supervised OS command                      | Nothing — the successor is an ordinary LLM turn |
| New member's turn       | `--mon` named proc, then a `--<n>` follow-up | One `--<n>` (or `--<name>`) session member      |
| Follow-up prompt source | `--next` text plus a command-run breakdown   | The `PROMPT` argument, verbatim                 |
| Bound                   | One monitor active per agent                 | `max_agent_pipe_chain` config field             |

Use `sase pipe` for a hand-off that does not supervise a command. See the
`/sase_handoff` skill for the command's flags and hazards, and
[Automation migration notes](../upgrading/automation.md#monitor-hand-off-is-sase-pipe)
for the retired `sleep 1` pattern.

<a id="see-also"></a>

## Related

- [Monitors](monitors.md)
- [Named tools and ToolRuns](tools.md)
- [`sase monitor`](../cli/monitor.md)
- [Agent queued for a runner slot](../runner-slots.md)
- [Automation migration notes](../upgrading/automation.md)
