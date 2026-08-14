# Monitors

A **monitor member** is a real [agent family](agent_families.md) member whose work is
one supervised OS command instead of an LLM turn. `sase monitor start` hands a slow
command off to a detached supervisor process and returns immediately, so an agent can
run `just check-full`, wait on a CI job, or sleep before a deploy without blocking its
own turn.

SASE agents are single-turn: a provider turn runs, the runner captures it, and the agent
is done. Provider-native background-execution or scheduled wake-up tools assume a
multi-turn session and do nothing useful here — the turn ends and the wake-up never
fires. Monitors are the SASE-native replacement: use `/sase_monitor` (or
`sase monitor start` directly) instead of any built-in monitor, background-execution, or
scheduled wake-up tool.

## The lane picture

Starting a monitor promotes the calling agent's lane to a family, exactly as
`%i(suffix, family=parent)` would, and adds the monitor as a member:

```
lane "acme"          before                     after `sase monitor start`
─────────────────────────────────────────────────────────────────────────────
acme                 (single agent, RUNNING)    acme            (family container)
                                                ├─ acme--0      DONE      ← starter, killed
                                                ├─ acme--mon    MONITORING ← the command
                                                └─ acme--1      RUNNING   ← follow-up agent
```

| Term           | Meaning                                                                    |
| -------------- | -------------------------------------------------------------------------- |
| starter        | The agent that ran `sase monitor start` (absent for host-started monitors) |
| monitor member | The `--mon` family member representing the supervised command              |
| supervisor     | The detached process that runs the command and streams its output          |
| follow-up      | The agent launched into the lane after the command finishes                |

`sase monitor start`, run from inside an agent, is the last thing that agent does: it
kills the calling agent's turn (the same handoff mechanism `sase plan propose` and
`sase questions` use), while the supervisor keeps the command running under the same
workspace claim. The workspace is never released and re-claimed between the starter and
the follow-up — the follow-up sees exactly the tree the monitor started with, plus
whatever the command itself changed.

A monitor member is an ordinary artifacts directory, just like an agent, so everything
that already understands agent families — the Agents tab, family roster, runtime
aggregation, `sase chats`, `%wait`/`#fork` resolution — works on it with no special
casing. There is no separate monitor store: a monitor's durable record is its
`agent_meta.json` plus `done.json`, and `sase monitor list`/`show` are queries over the
existing agent artifact index.

## Starting a monitor

```bash
sase monitor start \
  --command 'just check-full' \
  --reason 'Verify the refactor before replying to the user' \
  --timeout 45m \
  --next 'Fix anything just check-full reported, then reply to the user.'
```

- `--command` / `-c` is the full command handed to the shell.
- `--reason` / `-r` and `--timeout` / `-t` (bare seconds, or `90s` / `45m` / `2h`) are
  required — a monitor always says why it exists and has a bounded budget.
- `--idle-timeout` / `-i` is optional. It kills a command that stops producing output
  for the given duration, while still allowing intentionally quiet commands when
  omitted.
- `--next` / `-n` is the follow-up agent's instruction. Omit it for a fire-and-forget
  monitor: the command still runs to completion and its output, exit state, and runtime
  are recorded for later inspection, but no agent launches afterward.
- `--next-output none|tail|file` controls how much retained command output is handed to
  the follow-up agent. `tail` is the default; `file` points at the on-disk log; `none`
  gives only the outcome summary and `sase monitor show --all-lines` pointer.
- `--start-status` / `-s` and `--stop-status` / `-S` override the default `MONITORING` /
  `MONITORED` labels shown on the row — useful for a `sleep`-based wait
  (`SLEEPING FOR 300s` → `SLEPT FOR 300s`).
- `--label` / `-L`, `--lane` / `-l`, `--cwd` / `-C`, and `--tail-lines` / `-T` are
  optional; see `sase monitor start --help` for the full list.

Only one monitor may be running per lane at a time. Repeating the same full request
returns the existing running record; changing the command, cwd, timeout, next action,
status labels, or output policy is rejected until the active monitor settles. A `lost`
monitor is never implicitly replayed.

The command is executed through the platform shell (`sh -c` on Unix), so shell quoting,
redirection, and variable expansion are the caller's responsibility. Monitors are for
batch commands: do not use them for interactive programs or commands that require a TTY.

### Supervision guarantees

The detached supervisor owns the command's process group and writes combined stdout and
stderr to a bounded rotating log. Completion is based on process exit, not pipe EOF, so
a backgrounded grandchild that holds stdout open cannot keep the monitor running after
the command process exits. Total timeouts and TERM-to-KILL escalation are checked on
every supervisor tick, independent of whether the command is quiet, chatty, writing
partial lines, or emitting non-UTF-8 bytes. Non-UTF-8 output is retained with
replacement characters rather than crashing the supervisor.

Monitor logs are bounded. The active log is `live_reply.md`; when it rotates, readers
stitch the rotated `live_reply.md.1` and active file where appropriate. Very large
output therefore keeps a recent on-disk view and a head-plus-tail retained summary for
the follow-up agent rather than preserving unlimited bytes.

The command does not inherit the starter agent's `SASE_AGENT*` identity or
`SASE_ARTIFACTS_DIR`, so tools run by the command cannot accidentally write artifacts or
variables into the dead starter's directory.

### Surviving the starter's teardown

`sase monitor start`, run from inside an agent, hands the command to a supervisor and
then kills the calling agent's runner group as part of the same handoff. The supervisor
must not be a casualty of that kill: it is spawned through a double-fork bootstrap that
reparents it to PID 1 _before_ `start_monitor` returns, so a process-tree teardown
launched after the call cannot reach it by walking PPIDs. The supervisor also sets
`SIGHUP` to ignored and installs its `SIGTERM`/`SIGINT` handling in the first statements
it runs, before any expensive import, closing the startup window in which a stray signal
could kill it silently.

### Startup acknowledgement

`start_monitor` never hands back a `running` record for a supervisor that is not
provably alive, because its caller's very next act — inside an agent — is to kill
itself. Once the supervisor has taken ownership (dispositions set, meta read, output log
opened) it writes a `.monitor_started` marker carrying its real pid, pgid, and identity;
`start_monitor` blocks on that marker for up to 20 seconds, polling the supervisor's
liveness too so a pid that is already dead fails fast instead of waiting out the full
budget. A missing acknowledgement terminates the supervisor, hands the workspace claim
back to the still-live starter exactly as it held it (never releasing it into the free
pool), tears the member down as terminal `failed`, and raises `MonitorError` — so the
starter agent stays alive, `sase monitor start` exits non-zero, and nothing downstream
ever hands off to a phantom.

### A monitor owns its workspace until it is reconciled

A running monitor's workspace claim is not released just because its supervisor's pid
looks dead. The stale-claim sweeper reconciles a monitor's own markers first (killing a
confirmed-dead process group, finalizing the log, disposing the claim, and running or
recording the follow-up disposition) and only then releases the claim — and if
reconciliation itself fails, the sweeper leaves that claim in place rather than
guessing. This closes the window where another agent could be handed a workspace a
monitor is still using: a not-yet-reconciled dead supervisor is exactly the state a live
monitor is in from the outside, so a bare dead-pid check is not sufficient evidence to
release.

### Status and bucket

The displayed status is always the configured label. Because those labels are arbitrary
strings, the underlying **bucket** (Running / Done / Failed, used for grouping and
counting) is tracked separately from the label, from `monitor_state`:

| `monitor_state` | Bucket  | Displayed status                                   |
| --------------- | ------- | -------------------------------------------------- |
| `running`       | Running | start status                                       |
| `completed`     | Done    | stop status                                        |
| `failed`        | Failed  | stop status (+ exit code or supervisor error)      |
| `timeout`       | Failed  | stop status (+ total-timeout or idle-timeout note) |
| `stopped`       | Done    | stop status                                        |
| `lost`          | Failed  | stop status; command outcome is unknown            |

The stop-status label is descriptive text, not a success condition. It is reused for
every terminal state, including an explicit stop; use the bucket, `monitor_state`, exit
code, and output to decide what happened.

A monitor is terminal only after it is settled: the command has exited or been
reconciled, the log has been finalized, the workspace claim has been released or
transferred, and the follow-up has launched or its disposition has been recorded.
Polling commands such as `sase monitor show --follow` and `%wait` continue waiting while
a monitor is stopped but not yet settled.

A failing `just check-full` shows up as a Failed member with its exit code visible, and
the follow-up agent still launches so it can fix what broke. A timed-out command is
killed (its whole process group, not just the shell), and the follow-up is told plainly
which budget fired: total runtime or no-output idle time. A `lost` monitor means the
supervisor belongs to a previous boot, so SASE cannot know whether the command finished
or what it changed. Lost monitors are not automatically re-run, and their recorded
follow-up action is not launched.

## The follow-up agent

When `--next` is set and the monitor did not end in `stopped` or `lost`, one follow-up
agent launches into the same lane once the command finishes and the monitor settles. It
receives:

- the starter's full prior conversation, via `#fork`;
- the original `--reason` and the `--next` instruction, verbatim, under its own heading;
- a command-run breakdown: outcome, exit code, elapsed time vs. the timeout budget, and
  the selected output policy from `--next-output`;
- the full log path and the exact `sase monitor show <id> --all-lines` invocation to
  read more than the tail.

The follow-up inherits the starter's model, provider, and reasoning effort, so it is the
same kind of agent that started the monitor.

The launch is not coupled to a workspace-claim handoff that can fail: if the monitor's
own workspace claim can no longer be transferred to the follow-up (for example, a stale
sweep already released it), the follow-up still launches — first against a fresh claim
on the same workspace, then against workspace `0` if that workspace has since been taken
by another agent. Either fallback is recorded as a **degraded** launch, and the
follow-up prompt says plainly which happened, because a follow-up in a different
workspace than the monitor ran in cannot assume the command's artifacts are present.
Only when a follow-up genuinely cannot be launched at all is it dropped — and even then
the composed prompt is persisted as a durable artifact so the instruction can be
replayed by hand instead of surviving only as an error string. See
[Visibility](#visibility) below for how a dropped or degraded follow-up is surfaced.

When `--next-output tail` is used, retained output is fenced and labeled as untrusted
program output. The command and cwd fields are also fenced so directive-shaped strings
inside a shell command or path are treated as literal data. Use `--next-output file` for
large or hostile logs when the follow-up should inspect the log explicitly, or
`--next-output none` when the outcome summary and `sase monitor show --all-lines`
pointer are enough.

## Inspecting and stopping monitors

```bash
sase monitor list                          # active monitors, newest first
sase monitor list --all --lane acme        # include finished monitors for one lane
sase monitor list --status failed --status timeout

sase monitor show <id>                     # details plus an output tail
sase monitor show <id> --follow            # stream new output until it finishes
sase monitor show <id> --all-lines --output-only

sase monitor stop [<id>]                   # stop a running monitor; omit id to target
                                            # the calling agent's lane
```

`ID` accepts a monitor id (or unique prefix), the monitor member's agent name, or a lane
name. `sase monitor stop` never launches the recorded follow-up agent, even when
`--next` was given.

Every subcommand can emit machine-readable output, but not with the same flag: `start`,
`list`, and `stop` take `-j/--json`, while `list` and `show` take `-f/--format`
(`table`/`markdown`/`json` for `list`, `markdown`/`json` for `show`).
`sase monitor show` has **no** `-j` — use `--format json` there. See
`sase monitor --help` and each subcommand's `--help` for the complete flag reference, or
[CLI Reference](cli.md).

Reading monitors also performs dead-supervisor reconciliation. `sase monitor list`, the
ACE Agents tab refresh path, and the axe scheduler look for running monitor members
whose supervisor identity is no longer alive. Same-boot dead supervisors are reconciled
to `failed`: SASE kills the recorded process group, finalizes the log, disposes the
workspace claim, and launches or records the follow-up disposition. Pre-reboot
supervisors reconcile to `lost`; their command effects are unknown, so the follow-up is
recorded as not launched.

## In the ACE TUI

A monitor row renders with its own amber `⏱` glyph beside the agent list's bash/python
step glyphs, its configured label as the row title with the command as an annotation,
and a live elapsed suffix while running or an exit-code / timeout badge once terminal.
Monitor members appear in the family roster and contribute to the family's total
runtime, but — like workflow steps — they are not counted as agents in `sase stats` or
tribe/clan summaries: a family with one agent and one monitor is a one-agent family that
ran one command.

Selecting a monitor row keeps the ordinary agent header and renders a `MONITOR` detail
section in place of the usual prompt and reply body. It shows the shell-highlighted
`Command`, then whichever of `Cwd`, `Reason`, and `Next action` were recorded, then
`State` (a colored glyph plus the state name, with `(exit N)` appended once an exit code
is known). `Timeout` reports elapsed time against the budget (`3m12s of 45m0s budget`),
falling back to a plain `Elapsed` row for a record with no recorded budget, and an
`--idle-timeout` adds its own `Idle timeout` row. The section ends with the full
`Monitor id`, its short form, and the exact `sase monitor show <short-id> --follow`
command to stream the rest from a shell.

Beneath that, an `OUTPUT` block renders the captured stdout/stderr. Because
`live_reply.md` holds a command's raw merged output rather than prose, it is rendered as
a plain ANSI-aware log rather than through the markdown path used for agent replies, and
a monitor whose retained output was capped shows an
`… output truncated (head + tail retained) …` notice above it. A monitor that has not
written anything yet shows `No output yet.`.

With a **running** monitor row selected, the Agents tab's kill key (`x` by default)
stops the monitor instead of killing an agent: it opens a `Stop Monitor` confirmation
that defaults to **Keep running**, and confirming runs the same `stop_monitor` path as
`sase monitor stop`, so no follow-up agent launches. On a settled monitor row, `x`
behaves like an ordinary dismiss. See [Agent Row Glyphs](ace.md#agent-row-glyphs) and
[Sequential Agent Families](agent_families.md#sequential-agent-families).

## Visibility

A stalled lane — a supervisor that never reported a real outcome, or a follow-up that
never launched — is not something a project owner should have to notice by its absence.
Two independent conditions render distinctly, in the Agents tab and `sase monitor list`,
wherever the plain exit-code/timeout badges above do not already cover them:

- **A terminal monitor with no recorded exit code.** A `failed` or `lost` monitor whose
  supervisor never reported a real exit code (died on arrival, or belongs to a previous
  boot) renders with a red `⚠` badge in place of the exit-code badge — the command's
  outcome is unknown, not merely non-zero.
- **A dropped or degraded follow-up.** A monitor carrying a `--next` action that did not
  launch, or launched degraded, renders with an amber `⚑` flag independent of the
  monitor's own state — a monitor can finish cleanly and still strand its follow-up.

`sase monitor list` marks the same lane with the `⚑` flag next to its `STATE` cell (in
both the table and `--format markdown` output) so a stalled lane is visible without
`--json` plumbing; `sase monitor show <id>` prints a `Follow-up error` line for a
dropped follow-up and a `Follow-up degraded` line for a degraded one, and both commands'
JSON envelopes carry `followup_outcome` (`launched` / `launched-degraded` /
`not-launchable`), `followup_error`, and `followup_degraded_reason`.

Monitors themselves are notification-neutral: a monitor is an execution and handoff
mechanism, not a workflow that files notifications, so neither a completed monitor nor a
dropped `--next` appends a notification row. The badges and flags above, plus
`monitor_followup_outcome` / `monitor_followup_error` in `agent_meta.json` and
`done.json`, are the durable signals — read them with `sase monitor list`,
`sase monitor show <id>`, or the Agents tab.

## Example: approved epic launches

Launching an approved epic (`sase bead work <plan> --yes-to-all …`) is itself a
long-running command, so it normally runs under a monitor rather than a bare detached
proc. Its monitor member reads `EPIC APPROVED` while running and uses the configured
`EPIC CREATED` label after every terminal state, even failure, timeout, stop, or loss;
check the state and exit details instead of treating that label as success. A successful
launch attempts to back-fill the epic ID; when that metadata lands, the planner row
itself moves to `EPIC CREATED`, and otherwise it remains `EPIC APPROVED`. The monitor
takes a zero workspace claim (the launch runs in the project's primary workspace, not
the planner's), and no follow-up agent is recorded — `sase bead work` launches the phase
agents itself. If the planner's lane cannot be resolved (a very old artifacts layout, a
wiped agent), the launch falls back to the original global `detached` proc submission
rather than silently dropping the approval. Other monitor-start errors fail the approval
instead of using the proc fallback. See
[Plan Approval Flow](beads.md#plan-approval-flow) for the approval side of that handoff.

## See also

- [Agent Clans, Families, and Tribes](agent_families.md) for how a monitor member fits
  into a sequential agent family.
- [CLI Reference](cli.md) for the full `sase monitor` command table.
- [ACE TUI User Guide](ace.md) for how monitor rows render in the Agents tab.
