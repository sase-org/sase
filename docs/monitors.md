# Monitors

A **monitor shell** is a real [agent family](agent_families.md) member whose work is one
supervised OS command instead of an LLM turn. `sase monitor start` hands a slow command
off to a detached supervisor process and returns immediately, so an agent can run
`just check-full`, wait on a CI job, or sleep before a deploy without blocking its own
turn.

SASE agents are single-turn: a provider turn runs, the runner captures it, and the agent
is done. Provider-native background-execution or scheduled wake-up tools assume a
multi-turn session and do nothing useful here — the turn ends and the wake-up never
fires. Monitors are the SASE-native replacement: use `/sase_monitor` (or
`sase monitor start` directly) instead of any built-in monitor, background-execution, or
scheduled wake-up tool.

## The agent-family picture

Starting a monitor promotes the calling sase-agent to an agent family, exactly as
`%id(suffix, family=parent)` would, and adds the monitor as a proc shell member. The
follow-up agent is **not** launched yet — only after the command settles as `completed`,
`failed`, or `timeout` (not `stopped` or `lost`), and only when `--next` was set:

```
sase-agent "acme"    before                     right after `sase monitor start`
────────────────────────────────────────────────────────────────────────────────
acme                 (one-shell agent, RUNNING) acme            (agent family)
                                                ├─ acme--0      DONE       ← starter shell, killed
                                                └─ acme--mon    TESTING    ← monitor proc shell
```

After the command finishes with `--next` set:

```
acme
├─ acme--0      DONE
├─ acme--mon    TESTED     ← monitor finished
└─ acme--1      RUNNING    ← follow-up shell
```

| Term          | Meaning                                                                          |
| ------------- | -------------------------------------------------------------------------------- |
| starter shell | The agent shell that ran `sase monitor start` (absent for host-started monitors) |
| monitor shell | The `--mon` proc shell representing the supervised command                       |
| supervisor    | The detached process that runs the command and streams its output                |
| follow-up     | The agent shell launched under the family after the command finishes             |

`sase monitor start`, run from inside an agent, is the last thing that agent does: it
kills the calling agent's turn (the same handoff mechanism `sase plan propose` and
`sase questions` use), while the supervisor keeps the command running under the same
workspace claim. The workspace is never released and re-claimed between the starter and
the follow-up — the follow-up sees exactly the tree the monitor started with, plus
whatever the command itself changed.

A monitor shell has an ordinary artifacts directory, just like an agent shell, so
everything that already understands agent families — the Agents tab, family roster,
runtime aggregation, `sase chat`, `%wait`/`#fork` resolution — works on it with no
special casing. There is no separate monitor store: a monitor's durable record is its
`agent_meta.json` plus `done.json`, and `sase monitor list`/`show` are queries over the
existing agent artifact index.

## Starting a monitor

```bash
sase monitor start \
  -s TESTING -S TESTED \
  -r 'Verify the refactor before replying to the user' \
  -t 45m \
  -n 'Fix anything just check-full reported, then reply to the user.' \
  -- just check-full
```

- The command is the remainder after `--` (for example `-- just check-full`). That is
  the form `sase monitor start --help` shows. `-c/--command` still works as a hidden
  compatibility alias for a single shell string, but new invocations should use `--`.
- `-s/--start-status` and `-S/--stop-status` are **required** — the present-tense label
  shown while the command runs (e.g. `TESTING`) and the past-tense label shown when it
  finishes (e.g. `TESTED`). Each is capped at 20 characters; over-length values are
  truncated with a trailing `…` and a warning. `TESTING` / `TESTED` is the pair for
  `just check` and `just check-full`; a different kind of wait picks its own pair (for
  example `SLEEPING FOR 300s` → `SLEPT FOR 300s`).
- `-r/--reason` defaults to `run command`. `-t/--timeout` defaults to `1h` (bare
  seconds, or `90s` / `45m` / `2h`). Pass both when the default reason or budget would
  be misleading.
- `--idle-timeout` / `-i` is optional. It kills a command that stops producing output
  for the given duration, while still allowing intentionally quiet commands when
  omitted.
- `--next` / `-n` is the follow-up agent's instruction. Omit it for a fire-and-forget
  monitor: the command still runs to completion and its output, exit state, and runtime
  are recorded for later inspection, but no agent launches afterward.
- `--model` / `-m` selects a model or alias for that follow-up (for example `opus`,
  `opus@high`, `@small`, or `codex/gpt-5`). It requires `--next`. When omitted, the
  follow-up inherits the starter's model and reasoning effort.
- `--next-output none|tail|file` controls how much retained command output is handed to
  the follow-up agent. `tail` is the default; `file` points at the on-disk log; `none`
  gives only the outcome summary and `sase monitor show --all-lines` pointer.
- `--label` / `-L`, `--agent` / `-a` (`--lane` remains accepted as a deprecated alias),
  `--cwd` / `-C`, and `--tail-lines` / `-T` are optional; see
  `sase monitor start --help` for the full list.

Only one monitor may be running per agent at a time. Repeating the same full request
returns the existing running record; changing the command, cwd, timeout, next action,
status labels, or output policy is rejected until the active monitor settles. A `lost`
monitor is never implicitly replayed.

### Resolving the implicit agent

`--agent` / `-a` is only needed to start a monitor outside an agent shell (no
`SASE_AGENT_NAME` set) or to target a different agent than the caller. From inside an
agent -- including an epic phase lane and a promoted agent family -- omitting it
resolves the calling agent shell metadata-first:

1. The caller's own artifacts dir (`SASE_ARTIFACTS_DIR`), when it belongs to the caller.
2. An exact `SASE_AGENT_NAME` match against an artifact's own name.
3. The newest non-monitor member of the caller's own family, when `SASE_AGENT_NAME`
   names a family container rather than a concrete shell -- family members can replace
   one another inside a single process, leaving `SASE_AGENT_NAME` set to the family
   while the running shell's own artifacts carry the concrete member name. A settled
   `--mon` member is never selected here, even when it is the newest member of the
   family.

An unresolvable caller (no artifacts match any of the above) is a clear error naming
`-a/--agent`, not a silent fallback to the current working directory or another agent's
lane. `sase monitor show`/`stop` with no id resolve the same way, against the caller's
own durable family -- never a parent's or sibling's.

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

### Display contract

A monitor's identity on every surface is the ordered pair of its two labels. Three
orthogonal signals carry the rest:

| signal     | carries                         | mechanism                                                     |
| ---------- | ------------------------------- | ------------------------------------------------------------- |
| **hue**    | _which_ kind of monitor this is | one deterministic accent color per pair                       |
| **weight** | live or settled                 | `bold` while running, normal weight once settled              |
| **glyph**  | how it went                     | `✓` completed, `⊘` stopped, `✗` failed, `⧖` timeout, `⚠` lost |

Failure keeps red: `failed`, `timeout`, and `lost` render bold red regardless of the
pair accent. Two different pairs can share a color; the words still differ. Reusing one
pair across related monitors (for example every `just check-full` wait as `TESTING` /
`TESTED`) makes those rows read as one lane.

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
agent shell launches under the same agent family once the command finishes and the
monitor settles. It receives:

- the starter's full prior conversation, via `#fork`;
- the original `--reason` and the `--next` instruction, verbatim, under its own heading;
- a command-run breakdown: outcome, exit code, elapsed time vs. the timeout budget, and
  the selected output policy from `--next-output`;
- the full log path and the exact `sase monitor show <id> --all-lines` invocation to
  read more than the tail.

By default, the follow-up inherits the starter's model and reasoning effort. Pass
`--model` / `-m` to replace that routing with a model, provider-qualified model, or
model alias; an optional `@effort` suffix travels with the selection. `%model` text in
`--next` remains literal prompt text and does not control routing.

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

The follow-up prompt's body is enclosed in an xprompt-disabled region, so directives,
`#xprompt` references, and `$(...)` command substitution inside `--reason`, `--next`,
table fields, and embedded output are delivered as literal text. Only the routing prefix
(`#fork:`, `%model:`, `%effort:`) remains live. When `--next-output tail` is used,
retained output is also fenced and labeled as untrusted program output. The command and
cwd fields are fenced too, so directive-shaped strings inside a shell command or path
remain literal even if the disabled region is ever removed. Use `--next-output file` for
large or hostile logs when the follow-up should inspect the log explicitly, or
`--next-output none` when the outcome summary and `sase monitor show --all-lines`
pointer are enough.

## Runner slots

A monitor is not a way to free runner capacity. The family keeps its one
[`max_running_agents`](configuration.md#max_running_agents) slot for the monitor's whole
lifetime and then hands that same slot to the `--next` agent. The starter's runner
process exits at handoff, but occupancy stays continuous: the monitor member counts as
soon as it has a recorded supervisor pid, and the follow-up inherits the family's slot
instead of waiting at the admission gate. A fire-and-forget monitor (no `--next`) still
holds the slot until the command settles. In-process successors such as `sase pipe` keep
the same family's slot as well; they never become a second occupant.

Holding a slot and waiting for one stay separate. Only a root or a live parallel family
member parks at the gate. Serial family members — the monitor and its `--next` agent
included — ride the slot the family already holds. See
[Agent queued for a runner slot](troubleshooting/runner-slots.md).

## Inspecting and stopping monitors

```bash
sase monitor list                          # active monitors, newest first
sase monitor list --all --agent acme       # include finished monitors for one agent
sase monitor list --status failed --status timeout

sase monitor show <id>                     # details plus an output tail
sase monitor show <id> --follow            # stream new output until it finishes
sase monitor show <id> --all-lines --output-only

sase monitor stop [<id>]                   # stop a running monitor; omit id to target
                                            # the calling agent's active monitor
```

`ID` accepts a monitor id (or unique prefix), the monitor shell's agent name, or the
owning sase-agent name. `sase monitor stop` never launches the recorded follow-up agent,
even when `--next` was given.

`sase agent kill -n <name>` uses the same stop behavior when the name resolves to a live
monitor member or its owner. `sase monitor stop` remains the clearest explicit form.

Every subcommand can emit machine-readable output, but not with the same flag: `start`,
`list`, and `stop` take `-j/--json`, while `list` and `show` take `-f/--format`
(`table`/`markdown`/`json` for `list`, `markdown`/`json` for `show`).
`sase monitor show` has **no** `-j` — use `--format json` there. See
`sase monitor --help` and each subcommand's `--help` for the complete flag reference, or
[CLI Reference](cli.md).

Reading monitors also performs dead-supervisor reconciliation. `sase monitor list`, the
ACE Agents tab refresh path, and the axe scheduler look for running monitor shells whose
supervisor identity is no longer alive. Same-boot dead supervisors are reconciled to
`failed`: SASE kills the recorded process group, finalizes the log, disposes the
workspace claim, and launches or records the follow-up disposition. Pre-reboot
supervisors reconcile to `lost`; their command effects are unknown, so the follow-up is
recorded as not launched.

## In the ACE TUI

A monitor row renders with an amber `⚙` glyph beside the agent list's bash/python step
glyphs and omits a left-side title — identity is the right-hand `%id` (`<family>--mon`),
not the configured monitor label or command. A live elapsed suffix shows while running,
or an exit-code / timeout badge once terminal. Monitor shells appear in the family
roster and contribute to the family's total runtime, but — like workflow steps — they
are not counted as agents in `sase stats` or tribe/clan summaries: a family with one
agent and one monitor shell is a one-agent family that ran one command. A collapsed
family or clan container row carries an amber `⚙N` badge for its running monitors and a
grey `⚙N` badge for its finished ones, so both counts are visible without expanding the
subtree; the two badges partition the subtree's monitors exactly, and a failed,
timed-out, or lost monitor counts in the finished (grey) lane along with a clean
completion. The tribe panel title aggregates both lanes across the whole tribe, so a
fully collapsed panel still reports running and completed monitored work.

Selecting a monitor row keeps the ordinary agent header and renders a `MONITOR` detail
section in place of the usual prompt and reply body. It shows the shell-highlighted
`Command`, then whichever of `Cwd`, `Reason`, and `Next action` were recorded, then
`Status` (the effective label in its pair accent, with the other half dim after a `→`)
and `State` (a colored glyph plus the machine state name, with `(exit N)` appended once
an exit code is known). `Timeout` reports elapsed time against the budget
(`3m12s of 45m0s budget`), falling back to a plain `Elapsed` row for a record with no
recorded budget, and an `--idle-timeout` adds its own `Idle timeout` row. The section
ends with the full `Monitor id`, its short form, and the exact
`sase monitor show <short-id> --follow` command to stream the rest from a shell.

Beneath that, an `OUTPUT` block renders the captured stdout/stderr. Because
`live_reply.md` holds a command's raw merged output rather than prose, it is rendered as
a plain ANSI-aware log rather than through the markdown path used for agent replies, and
a monitor whose retained output was capped shows an
`… output truncated (head + tail retained) …` notice above it. A monitor that has not
written anything yet shows `No output yet.`.

When the monitor's family (or its starter) is selected, that same block appears inline
as a `MONITOR` phase in the AGENT REPLY stream: an amber `⚙ MONITOR` divider, the
command, the recorded detail fields, and the full captured output. File-hint mode
renders the monitor document with `[N]` markers on the command and log instead of
falling back to the empty prompt view.

With a **running** monitor row selected, the Agents tab's kill key (`x` by default)
stops the monitor instead of killing an agent: it opens a `Stop Monitor` confirmation
that defaults to **Keep running**, and confirming runs the same `stop_monitor` path as
`sase monitor stop`, so no follow-up agent launches. On a settled monitor row, `x`
behaves like an ordinary dismiss. See [Agent Row Glyphs](ace.md#agent-row-glyphs) and
[Sequential Agent Families](agent_families.md#sequential-agent-families).

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
- **A dropped or degraded follow-up.** A monitor carrying a `--next` action that did not
  launch, or launched degraded, renders with an amber `⚑` flag independent of the
  monitor's own state — a monitor can finish cleanly and still strand its follow-up.

`sase monitor list` marks the same monitor row with the `⚑` flag next to its `STATE`
cell (in both the table and `--format markdown` output) so a stalled handoff is visible
without `--json` plumbing; `sase monitor show <id>` prints a `Follow-up error` line for
a dropped follow-up and a `Follow-up degraded` line for a degraded one, and both
commands' JSON envelopes carry `followup_outcome` (`launched` / `launched-degraded` /
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
proc. Its monitor shell reads `EPIC APPROVED` while running and uses the configured
`EPIC CREATED` label after every terminal state, even failure, timeout, stop, or loss;
check the state and exit details instead of treating that label as success. A successful
launch attempts to back-fill the epic ID; when that metadata lands, the planner row
itself moves to `EPIC CREATED`, and otherwise it remains `EPIC APPROVED`. The monitor
takes a zero workspace claim (the launch runs in the project's primary workspace, not
the planner's), and no follow-up agent is recorded — `sase bead work` launches the phase
agents itself. If the planner's agent family cannot be resolved (a very old artifacts
layout, a wiped agent), the launch falls back to the original global `detached` proc
submission rather than silently dropping the approval. Other monitor-start errors fail
the approval instead of using the proc fallback. See
[Plan Approval Flow](beads.md#plan-approval-flow) for the approval side of that handoff.

The host-owned epic launcher keeps `sase bead work` as the visible logical command. If
an editable-source update is swapping that checkout when approval arrives, a minimal
pre-import bootstrap prints
`sase: waiting for the source-tree swap to finish before launching`, waits for the
shared lock, and only then starts `sase bead work` against one consistent source tree.
This waiting exception is specific to host-owned approved-epic launches; running
`sase bead work` directly remains fail-fast during a swap.

## Pipe vs. monitor

`sase pipe '<prompt>'` (the `/sase_pipe` skill) looks similar — it also kills the
calling agent and continues the run as a new family member — but it solves a different
problem. A monitor runs and waits on an OS command; nothing about the command's content
is an LLM turn. Pipe hands the agent's own unfinished _turn_ to a fresh successor: no
command runs, nothing is captured or timed out, and the successor's prompt is written by
the agent, not derived from a command's outcome.

Concretely:

|                         | Monitor                                      | Pipe                                            |
| ----------------------- | -------------------------------------------- | ----------------------------------------------- |
| What runs               | A supervised OS command                      | Nothing — the successor is an ordinary LLM turn |
| New member's shell      | `--mon` proc shell, then a `--<n>` follow-up | One `--<n>` (or `--<name>`) family member       |
| Follow-up prompt source | `--next` text plus a command-run breakdown   | The `PROMPT` argument, verbatim                 |
| Bound                   | One monitor active per agent                 | `max_agent_pipe_chain` config field             |

Before this command existed, agents got a successor by monitoring a no-op command:

```bash
sase monitor start -s SLEEPING -S SLEPT -r '...' -n '<the real prompt>' -- sleep 1
```

That only worked because `sase monitor start` already kills the caller and its
supervisor already launches a family follow-up once the command settles — a monitor
supervisor, a proc row, and a one-second sleep, purely to obtain a hand-off. Use
`sase pipe` for a hand-off instead; the `sleep 1 --next '...'` pattern is no longer
necessary. See the `/sase_pipe` skill for the command's flags and hazards.

## See also

- [Agent Clans, Families, and Tribes](agent_families.md) for how a monitor shell fits
  into a sequential agent family.
- [CLI Reference](cli.md) for the full `sase monitor` command table.
- [ACE TUI User Guide](ace.md) for how monitor rows render in the Agents tab.
- [Agent queued for a runner slot](troubleshooting/runner-slots.md) for occupancy versus
  admission, including why a monitor still counts against `max_running_agents`.
