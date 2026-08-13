# Monitors

A **monitor member** is a real [agent family](agent_families.md) member whose work is
one supervised OS command instead of an LLM turn. `sase monitor start` hands a slow
command off to a detached supervisor process and returns immediately, so an agent can
run `just check-full`, wait on a CI job, or sleep before a deploy without blocking its
own turn.

SASE agents are single-turn: a provider turn runs, the runner captures it, and the agent
is done. Provider-native "background task" or "scheduled wake-up" tools assume a
multi-turn session and do nothing useful here — the turn ends and the wake-up never
fires. Monitors are the SASE-native replacement: use `/sase_monitor` (or
`sase monitor start` directly) instead of any built-in monitor, background-task, or
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
| `stopped`       | Done    | `STOPPED`                                          |
| `lost`          | Failed  | stop status; command outcome is unknown            |

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
`--next` was given. Every subcommand accepts `-j/--json` (or `-f/--format` for `list`
and `show`) for machine-readable output. See `sase monitor --help` and each subcommand's
`--help` for the complete flag reference, or [CLI Reference](cli.md).

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
ran one command. Selecting a monitor row shows its command, working directory, reason,
next action, state, and timeout budget in a `MONITOR` detail section, with the captured
output rendered as a plain log rather than markdown. See
[Agent Row Glyphs](ace.md#agent-row-glyphs) and
[Sequential Agent Families](agent_families.md#sequential-agent-families).

## Example: approved epic launches

Launching an approved epic (`sase bead work <plan> --yes-to-all …`) is itself a
long-running command, so it runs under a monitor rather than a bare detached task: the
planner's `EPIC APPROVED` status becomes `EPIC CREATED` once `sase bead work` finishes
launching every phase. The monitor takes a zero workspace claim (the launch runs in the
project's primary workspace, not the planner's), and no follow-up agent is recorded —
`sase bead work` launches the phase agents itself. If the planner's lane cannot be
resolved (a very old artifacts layout, a wiped agent), the launch falls back to the
original detached-task submission rather than silently dropping the approval.

## See also

- [Agent Clans, Families, and Tribes](agent_families.md) for how a monitor member fits
  into a sequential agent family.
- [CLI Reference](cli.md) for the full `sase monitor` command table.
- [ACE TUI User Guide](ace.md) for how monitor rows render in the Agents tab.
