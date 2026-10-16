---
title: Monitors
description:
  Start and supervise commands that outlive the SASE agent that launched them.
---

# Monitors

This page names how a monitor turn starts, runs a supervised command, and reports the
outcome. A monitor turn is a real agent-session member whose work is one OS command
instead of an LLM turn.

## The agent-session picture

Starting a monitor promotes the calling sase-agent to an agent session, exactly as
`%id(suffix, session=parent)` would, and adds the monitor as a named proc member. No
successor is launched yet. After the command settles, the frozen outcome branch may
launch one ordinary follow-up, complete through the host, or do nothing. `stopped` and
`lost` always do nothing:

```
sase-agent "acme"    before                     right after `sase monitor start`
────────────────────────────────────────────────────────────────────────────────
acme                 (one-turn agent, RUNNING) acme            (agent session)
                                                ├─ acme--0      DONE       ← starter turn, killed
                                                └─ acme--mon    TESTING    ← monitor named proc
```

After the command finishes on an ordinary `continue` branch:

```
acme
├─ acme--0      DONE
├─ acme--mon    TESTED     ← monitor finished
└─ acme--1      RUNNING    ← follow-up turn
```

| Term         | Meaning                                                                         |
| ------------ | ------------------------------------------------------------------------------- |
| starter turn | The agent turn that ran `sase monitor start` (absent for host-started monitors) |
| monitor turn | The `--mon` named proc representing the supervised command                      |
| supervisor   | The detached process that runs the command and streams its output               |
| follow-up    | The agent turn launched under the session after the command finishes            |

`sase monitor start`, run from inside an agent, is the last thing that agent does: it
kills the calling agent's turn (the same handoff mechanism `sase plan propose` and
`sase questions` use), while the supervisor keeps the command running under the same
workspace claim. The workspace is never released and re-claimed between the starter and
the follow-up — the follow-up sees exactly the tree the monitor started with, plus
whatever the command itself changed.

A monitor turn has an ordinary artifacts directory, just like an agent turn, so
everything that already understands agent sessions — the Agents tab, session roster,
runtime aggregation, `sase chat`, `%wait`/`#fork` resolution — works on it with no
special casing. There is no separate monitor store: a monitor's durable record is its
`agent_meta.json` plus `done.json`, and `sase monitor list`/`show` are queries over the
existing agent artifact index.

## Starting a monitor

Host finalizer recovery and conflict-repair turns cannot hand off through
`sase monitor start`, `sase pipe`, plan proposal, or questions. Those turns are owned by
an already-running finalizer that must receive their result in the same invocation; a
handoff cannot complete that contract. The CLI refuses before creating the handoff.
Finish the repair and any verification inline, or report the blocker to the host.

```bash
sase monitor start \
  -p verify \
  -r 'Verify the refactor before replying to the user' \
  -t 45m \
  -n 'Fix anything just check reported, then reply to the user.' \
  -- just check
```

When `just check-full` is explicitly requested (typically to repair a CI failure), use
the same `verify` profile — never run it inline.

Use the same shape when the command you need is an agent-completion gate. The intended
composition is a monitor running `sase agent wait`, followed by a normal follow-up agent
that acts on the result:

```bash
sase monitor start \
  -s WAITING -S WAITED \
  -n 'agents finished; land the epic' \
  -- sase agent wait -a
```

That keeps the wait outside the current provider turn, preserves the workspace claim,
and records the wait output where the follow-up can inspect it.

- The command is the remainder after `--` (for example `-- just check`). That is the
  form `sase monitor start --help` shows. `-c/--command` still works as a hidden
  compatibility alias for a single shell string, but new invocations should use `--`. A
  single word after `--` is used verbatim as the shell command, so quote a pipeline or
  `&&` chain as one argument (`-- 'just fix && just check'`). Several words are
  re-quoted with `shlex.join`, so each stays one literal argument and shell operators
  among them are not interpreted. SASE already runs the command with `/bin/sh -c`, so do
  not wrap it in `bash -c` or `sh -c`; `sase monitor start` warns when it sees that
  redundant wrapper.
- `-p/--profile verify` supplies the standard verification policy: `TESTING` / `TESTED`
  labels, `--next-output auto`, no continuation after success, and a recovery
  continuation after failure or timeout. `-n/--next` replaces the built-in recovery
  instruction. Profile selection alone never authorizes host completion; prepared
  completion still requires `-f/--completion`.
- `-s/--start-status` and `-S/--stop-status` are required when no profile supplies them
  — the present-tense label shown while the command runs (e.g. `TESTING`) and the
  past-tense label shown when it finishes (e.g. `TESTED`). Each is capped at 20
  characters; over-length values are truncated with a trailing `…` and a warning.
  `TESTING` / `TESTED` is the pair for `just check` and `just check-full`; a different
  kind of wait picks its own pair (for example `SLEEPING FOR 300s` → `SLEPT FOR 300s`).
- `-r/--reason` defaults to `run command`. `-t/--timeout` defaults to `1h` (bare
  seconds, or `90s` / `45m` / `2h`). Pass both when the default reason or budget would
  be misleading.
- `--idle-timeout` / `-i` is optional. It kills a command that stops producing output
  for the given duration, while still allowing intentionally quiet commands when
  omitted.
- `--next` / `-n` is the shared follow-up instruction. Without a profile, policy, or
  prepared completion, omitting it makes the monitor fire-and-forget: the command still
  runs to completion and its output, exit state, and runtime are recorded, but no agent
  launches afterward.
- `--model` / `-m` selects a model or alias for an ordinary follow-up (for example
  `opus`, `opus@high`, `@small`, or `codex/gpt-5`). It may accompany `--next`, a
  profile, an outcome policy, or a prepared completion that has a recovery branch. When
  omitted, an ordinary follow-up inherits the starter's model and reasoning effort.
- `-o/--next-output auto|tail|file|none` controls how much retained command output is
  handed to the follow-up agent. `auto` is the default and selects outcome-aware
  evidence; `tail` embeds a bounded raw tail; `file` points at refs and log locators;
  `none` gives only the outcome summary and `sase monitor show --all-lines` pointer.
- `-k/--checkpoint FILE` binds an authored YAML/JSON checkpoint by content digest. Use
  it to preserve the objective, constraints, findings, unresolved decisions, remaining
  work, source refs, or coverage separately from `--next`.
- `-P/--policy FILE` loads a per-outcome JSON/YAML policy. It is mutually exclusive with
  `-p/--profile`; both are validated and frozen before SASE creates the monitor member.
- `-f/--completion REF` binds a single-use host-completion intent produced by
  `sase final prepare`. The monitored argv must exactly match the intent's verification
  command.
- `--label` / `-L`, `--agent` / `-a` (`--lane` remains accepted as an alias), `--cwd` /
  `-C`, and `--tail-lines` / `-T` are optional; see the generated
  [`sase monitor start`](../cli/monitor.md#sase-monitor-start) page for the full flag
  list.
- `-k`, `-P`, `-p`, and `-f` are always available: every new monitor persists versioned
  continuation records, so checkpoint, outcome-policy, profile, and host-completion
  controls work unconditionally.

`--cwd` may name any directory inside a managed checkout, including a repository opened
with `sase repo open`. When `--cwd` is omitted, the default is the current directory
when it is inside a repo opened with `sase repo open`, else the agent's workspace, else
`$PWD`. The command runs in that directory, but the monitor records and claims the
checkout that contains it, and an ordinary follow-up starts at that checkout's root.
When the directory is inside the caller's own workspace, the caller's claim moves to the
monitor; inside a different managed workspace, the monitor takes a fresh claim and the
caller keeps its own. A directory outside every managed checkout uses workspace `0`.

Before it creates the monitor member or binds a completion intent, `sase monitor start`
checks the target workspace's claims. If another live process holds that workspace, the
start fails with `could not claim workspace for monitor: …` and leaves no monitor row
behind. A claim left by the same agent whose process has died is taken over instead.

Only one monitor may be running per agent at a time. Repeating the same full request
returns the existing running record; changing the command, cwd, reason, label, timeout,
idle timeout, next action, model, status labels, tail lines, profile, checkpoint,
policy, completion intent, output policy, or joined run is rejected until the active
monitor settles. A `lost` monitor is never implicitly replayed: repeating the identical
request is refused with a pointer to `sase monitor show`, while a different request may
start a new monitor.

### Joining a detached ToolRun

(Agents only.) `sase monitor start -J/--join RUN` adopts an existing starter-scoped
detached ToolRun — the kind `sase tool run -d` starts — instead of starting a command.
The run keeps one id end to end, and its executing proc stays the owner; the monitor
only follows it:

```bash
sase monitor start -J 0f1a2b3c -p verify -n 'finish check'
```

The display command replays the original `sase tool run` words (ad-hoc argv included),
the default label is `tool:<name> (joined)`, and the default reason is
`finish <tool> (joined run)`. `-J` cannot be combined with a command remainder, `-c`,
`-f` (pass `-n` for a follow-up instead), or `-a`: the join always runs on the calling
agent's lane. The caller must be the agent that started the run; anything else — outside
an agent, a run with no starter scope, or another agent's run — is refused with exit
`2`. A run that already settled, has a stop request, or is joined elsewhere is refused
with exit `1`, showing the state and a `sase tool show RUN` pointer. No monitor starts
on any refusal.

The join records atomically after the monitor member exists and before its proc submits;
a refused or failed start tears the member down (releasing the join) and runs nothing.
The monitor proc follows the run into the monitor log without a deadline, then renders a
compact summary with the triage footer and exits with the run's mapped code. In the
Procs tab that proc carries a `tool-run-join:<id>` tag, so `Enter` opens Admin Center →
Tools focused on the run (`⏎: run`) instead of jumping to the monitor's agent. A monitor
that owns a reserved run uses `tool-run:<id>` and opens the same way. See
[Opening a row](../tui/procs-tab.md#opening-a-row). `stop`, timeout, and a lost joiner
converge through the detached-run watchdog with the `stop_requested` reason preserved,
and `sase tool stop RUN` on a joined run stops the active joining monitor (suppressing
its follow-up) rather than the run's proc.

### Tool-run wrapping

A `verify`-profile monitor runs its command inside `sase tool run`, so the run is
recorded with the monitor as owner and the starter agent attributed — plain
`-- just check` is equivalent to `-- sase tool run check` and agents need not remember
the wrapper. Only the argv the proc supervisor execs is wrapped: `monitor_command` and
`monitor_execution_argv` stay exactly as written, so every prepared-completion `-f`
binding keeps resolving the raw command. The wrapper is built from the supervisor's own
Python (`sys.executable -m sase`), never `PATH`. The starter's provider rides along as
`SASE_TOOL_RUN_PROVIDER` for the run's demand context; ceilings are never forwarded,
because a monitor has none.

Where the table below resolves to a tool run, the start reserves that run up front — a
`created` hand-off run owned by the monitor id — and the proc execs the claiming worker
instead of the wrapped argv, so one semantic run is never recorded twice. The run id
prints in the start output (`Tool run`), rides the `--json` envelope (`tool_run_id`),
persists as the flat `monitor_tool_run_id` meta field, and shows in `sase monitor show`,
so the follow-up can `sase tool show RUN -F`, `sase tool stop RUN`, or
`sase tool wait RUN` on it. If the reservation cannot be committed, the start keeps the
wrapped argv (fail-open) and pre-writes one `sase: tool run not reserved (...)` reason
line to the monitor log.

| Monitor                                                                                                | Proc argv                                    |
| ------------------------------------------------------------------------------------------------------ | -------------------------------------------- |
| Host-owned `execution_argv` launch (an epic `sase bead work`)                                          | unchanged, **never** wrapped                 |
| Exactly one `sase tool run …` already                                                                  | unchanged                                    |
| `SASE_TOOL_BYPASS` set or `monitor.tool_wrap: off`                                                     | unchanged, plus one reason line in the log   |
| No profile or a non-`verify` profile under the default `monitor.tool_wrap: verify`                     | unchanged, plus one reason line in the log   |
| The project tool catalog cannot be loaded                                                              | unchanged, plus one reason line in the log   |
| A simple command equal to a catalog tool's argv, with the monitor's cwd at that catalog's project root | `<sase> tool run <name>` (**named upgrade**) |
| Anything else under `-p verify` (or with any or no profile under `monitor.tool_wrap: all`)             | `<sase> tool run -- /bin/sh -c CMD` (ad-hoc) |

Rows are checked top to bottom and the first match wins. A simple command is one shell
word-split with no operators, redirects, globs, expansions, or leading `NAME=value`
assignment: `just check` upgrades by name, while `just install-venv && just check`,
`just check 2>&1 | tail -20`, or `FOO=1 just check` wraps ad-hoc with the command
verbatim, so the run is at least as faithful as the raw command. Extra arguments match
only where that tool's `args: allow` policy permits them. Every unwrapped-by-policy case
writes exactly one `sase: running unwrapped (<reason>)` line at the top of the monitor
log, so the log explains itself. `monitor.tool_wrap` (`off | verify | all`, default
`verify`) changes the policy without a code change: `all` widens wrapping to every
monitor and `off` disables it; see [Tool runs](tools.md) for the environment contract
and the guarded recipes this pairs with.

### Checkpoints and outcome policies

An authored checkpoint is a bounded (at most 256 KiB), UTF-8 YAML or JSON object. It
must provide at least one of `objective`, `constraints`, `findings`,
`unresolved_decisions`, or `remaining_work`; each accepts a string or a list of strings.
Optional `source_refs` and `coverage` identify the evidence and scope already handled.
Do not put `next` or `next_action` in the file: the checkpoint records durable state,
while `-n/--next` records what the successor should do.

```yaml
objective: Finish the parser refactor safely.
constraints:
  - Preserve the public CLI.
findings:
  - The focused tests pass.
remaining_work:
  - Run the full verification gate.
source_refs:
  - file:explicit:parser-notes
coverage:
  - parser
  - cli
```

An explicit outcome policy chooses `continue`, `none`, or `complete` independently for
`completed`, `failed`, and `timeout`. It may also spell out `stopped` and `lost`, but
those two outcomes never dispatch. A `continue` branch can set `next_action`, `model`,
and evidence policy; an explicit branch overrides the shared `--next`, `--model`, and
`--next-output` values. A `complete` branch is rejected unless `--completion` binds a
prepared intent.

```yaml
completed:
  action: none
failed:
  action: continue
  next_action: Repair the failed verification, then finish the task.
  model: opus@high
timeout:
  action: continue
  next_action: Diagnose the timeout without rerunning the command blindly.
```

SASE freezes the validated policy, inherited route, prepared-completion ref, and
checkpoint before changing workspace claims. Editing the source files afterward cannot
change a running monitor's settlement decision.

### Prepared host completion

`sase final prepare` turns a normal finalizer declaration plus one exact verification
command into a host-sealed, single-use intent. Preparation publishes the current final
context and records the relevant repositories' HEAD, index, dirty paths, and protected
or foreign state. It does **not** accept a final submission, run a finalizer, commit, or
end the turn.

Prepare retains observations for every relevant repository as evidence, but eligibility
and the worktree-staleness fingerprint use only repositories with a repository decision.
Those are the repositories host completion can commit; unrelated sidecars may have
pre-existing dirt or receive concurrent commits without making a safe completion stale.

```json
{
  "success_message": "Required checks passed in {duration}.",
  "verification": { "command": ["just", "check-full"] },
  "declaration": {
    "schema_version": 2,
    "context_digest": "<from sase final context>",
    "plan_digest": "<from sase final context>",
    "payloads": [
      {
        "instance_id": "commit",
        "payload": {
          "repositories": [
            {
              "repo_id": "<repository obligation id>",
              "action": "commit",
              "message": "docs: refresh user documentation"
            }
          ],
          "deferrals": []
        }
      }
    ]
  }
}
```

Prepare the wrapper, then bind the returned `intent_ref` to the matching command:

```bash
sase final prepare completion.json -j
sase monitor start -p verify -f '<intent-ref>' -- just check
```

Binding is atomic. A command mismatch creates no monitor, and a failed monitor startup
returns the intent to the prepared state; once a live monitor has bound it, the intent
cannot be reused. If the command completes successfully and the sealed command,
finalizer plan, repository observations, workspace, and diagnostics remain eligible, the
host installs the prepared declaration and runs its finalizers without another model
turn. The monitor reports `Completed by host` and retains a completion receipt.

A failed or timed-out command, stale repository state, or another eligibility failure
invalidates host completion and launches one ordinary recovery continuation instead.
That successor receives the reason and must repair or finish normally; without `--next`,
it is told to diagnose the failure or stale verification and then finish the requested
change. Stopped and lost monitors never complete or continue automatically.

The monitor's host-completion status (`Host final` in sase's TUI) reads `finalizing`
while the finalizers run, `completed_by_host` once they succeed, and `recovery` after
the intent was invalidated and handed to a recovery continuation. `needs_attention`
means a commit receipt is ambiguous, so SASE neither completes nor continues
automatically; inspect the receipt and finish the change by hand. A monitor that carries
a host-completion status cannot be resumed with `sase monitor resume`. See
[Commit Finalizer](../../contribute/commit-workflow-orchestrator.md#commit-finalizer)
for the declaration side of the protocol.

### Resolving the implicit agent

`--agent` / `-a` is only needed to start a monitor outside an agent turn (no
`SASE_AGENT_NAME` set) or to target a different agent than the caller. From inside an
agent -- including an epic phase lane and a promoted agent session -- omitting it
resolves the calling agent turn metadata-first:

1. The caller's own artifacts dir (`SASE_ARTIFACTS_DIR`), when it belongs to the caller.
2. An exact `SASE_AGENT_NAME` match against an artifact's own name.
3. The newest non-monitor member of the caller's own session, when `SASE_AGENT_NAME`
   names a session container rather than a concrete turn -- session members can replace
   one another inside a single process, leaving `SASE_AGENT_NAME` set to the session
   while the running turn's own artifacts carry the concrete member name. A settled
   `--mon` member is never selected here, even when it is the newest member of the
   session.

An unresolvable caller (no artifacts match any of the above) is a clear error naming
`-a/--agent`, not a silent fallback to the current working directory or another agent's
lane. `sase monitor show`/`stop` with no id resolve the same way, against the caller's
own durable session -- never a parent's or sibling's.

The stored command string is executed with `/bin/sh -c`, so shell quoting, redirection,
and variable expansion in a single-string command are the caller's responsibility.
Monitors are for batch commands: do not use them for interactive programs or commands
that require a TTY.

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
variables into the dead starter's directory. It receives `SASE_MONITOR_ID`,
`SASE_MONITOR_ARTIFACTS_DIR`, and `SASE_MONITOR_DIAGNOSTICS_DIR` instead. Only the
command's own `tools/run_silent` stages record into that diagnostics directory: a
stage's children never inherit it, so a nested `tools/run_silent` cannot add stages of
its own.

### Surviving the starter's teardown

`sase monitor start`, run from inside an agent, hands the command to a supervisor and
then kills the calling agent's runner group as part of the same handoff. The supervisor
must not be a casualty of that kill: it is spawned through a double-fork bootstrap that
reparents it to PID 1 _before_ `start_monitor` returns, so a process-tree teardown
launched after the call cannot reach it by walking PPIDs. The supervisor also sets
`SIGHUP` to ignored and installs its `SIGTERM`/`SIGINT` handling in the first statements
it runs, before any expensive import, closing the startup window in which a stray signal
could kill it silently.

On Linux, when the starter runs inside a SASE-owned systemd unit or scope such as
`sase.service` or under a reachable user systemd manager, the supervisor also moves into
its own transient `systemd-run --user --scope` (with `OOMPolicy=continue`), so
restarting that service does not kill a running monitor. Set
`SASE_DETACH_SCOPE_DISABLE=1` to opt out.

### A start is fast, and never silent

An in-agent `sase monitor start` has to finish inside the harness's own tool budget:
Codex's yielding `exec_command` hands control back to the model after about 30 seconds
while the command keeps running, and anything still running when the turn ends is
killed. So the start touches only what it needs and says so at once:

- Inside an agent it prints one line to stderr before any slow work
  (`sase monitor start: starting monitor for lane <lane>; ... wait for it to exit`), so
  a yielded result is never empty. All stdout, including the `--json` envelope, still
  prints before the runner is killed.
- The calling agent is resolved by reading its own `SASE_ARTIFACTS_DIR` directly. The
  full project scan is only the fallback for a missing, stale, or foreign pin.
- The lane's existing monitors are read once, through the artifact index's
  `agent_session` candidate filter, and that snapshot answers the replay check and the
  `--mon` suffix allocation. A lane read does not hydrate other lanes' records or walk
  the project's source directories.
- Each phase of the start (identity, lane lock, replay lookup, lane resolution, claim
  preflight, member creation, ToolRun reservation, supervisor spawn and ack, intent
  persistence) is timed. The timings are logged at debug level and written to
  `monitor_start_timing.json` in the new member's artifacts directory.

On a host with about 12,000 artifact records this took an in-agent start from roughly
20-40 seconds to well under one.

### Startup acknowledgement

The monitored command runs under the durable proc service's detached supervisor, and
`start_monitor` never hands back a `running` record for a supervisor that is not
provably alive, because its caller's very next act — inside an agent — is to kill
itself. Once the supervisor has taken ownership, it writes a `.proc_started`
acknowledgement in its proc runtime directory. `start_monitor` waits for that marker for
up to 20 seconds (`SASE_PROC_START_ACK_TIMEOUT_SECONDS` overrides the budget), polling
the supervisor's liveness too so a supervisor that is already dead fails fast instead of
waiting out the full budget. A failed start hands the workspace claim back to the
still-live starter exactly as it held it (never releasing it into the free pool),
returns any bound completion intent to the prepared state, tears the member down as
terminal `failed`, and raises `MonitorError` — so the starter agent stays alive,
`sase monitor start` exits non-zero, and nothing downstream ever hands off to a phantom.

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
pair across related monitors (for example every `just check` wait as `TESTING` /
`TESTED`) makes those rows read as one lane.

A monitor is terminal only after it is settled: the command has exited or been
reconciled, the log has been finalized, the workspace claim has been released or
transferred, and the follow-up has launched or its disposition has been recorded.
Polling commands such as `sase monitor show --follow` and `%wait` continue waiting while
a monitor is stopped but not yet settled.

A failing `just check` shows up as a Failed member with its exit code visible, and the
follow-up agent still launches so it can fix what broke. A timed-out command is killed
(its whole process group, not just the shell), and the follow-up is told plainly which
budget fired: total runtime or no-output idle time. A `lost` monitor means the command
outcome is unknown: the supervisor died or belongs to a previous boot without a frozen
command result. Lost monitors are not automatically re-run, and their recorded follow-up
action is not launched. A known command result that survived a later bookkeeping crash
is not lost: settlement resumes the frozen status, exit code, reason, and command-end
time, finishes remaining artifacts and follow-up work, and does not rerun the command.
`sase monitor resume` still rejects `lost`; this repair does not scan or rewrite
historical monitors that were already terminalized as lost.

## The follow-up agent

When the frozen outcome branch selects `continue`, one follow-up agent turn launches
under the same agent session once the command finishes and the monitor settles. A shared
`--next`, the `verify` profile, or an explicit policy may supply that branch. It
receives:

- the starter's full prior conversation, via `#fork`, once the starter's own record has
  settled (settlement waits up to 60 seconds for it); the follow-up joins the session it
  forks and does not wait on or list itself, though it still waits for any other live
  session member;
- the original `--reason` and the resolved next instruction, verbatim, under its own
  heading;
- the authored checkpoint, when supplied, as protected state distinct from the next
  action;
- a command-run breakdown: outcome, exit code, elapsed time vs. the timeout budget, and
  the selected output policy from `--next-output`;
- the full log path and the exact `sase monitor show <id> --all-lines` invocation to
  read more than the tail.

By default, the follow-up inherits the starter's model and reasoning effort. Pass
`--model` / `-m` to replace that routing with a model, provider-qualified model, or
model alias; an optional `@effort` suffix travels with the selection. `%model` text in
`--next` remains literal prompt text and does not control routing.

### Failure triage in follow-ups

When a failed monitor has a settled ToolRun with triage, its follow-up prompt inserts a
`## Failure triage` section before selected diagnostics. It gives the verdict, NEW and
UNKNOWN items with their evidence and possible owners, KNOWN/FLAKY counts, and the exact
`sase tool show RUN -j` command. The section is absent only when no stored triage is
available; it never changes the monitor result or the command's exit code.

Continuation history is replayed from versioned parent links rather than reconstructed
from turn names. Each ancestor is hydrated once in order, including local authored
prompt segments, host instructions, final responses, checkpoints, and monitor-result
evidence. A missing ancestor is disclosed as a gap; SASE does not guess across uncertain
history. Artifact-run pruning keeps old runs that a live or recoverable continuation
still references, and SASE registers required checkpoints and monitor results as
portable artifacts, so replay can still hydrate them after the local files are gone.

Automatic retries keep failed-attempt evidence under `attempts/<N>/`, but continuation
replay excludes superseded failed attempts from the ancestor chain. A later `#fork`
therefore follows the settled attempt and its original launch lineage without injecting
obsolete retry errors as extra conversation turns. Prior attempts remain inspectable in
the TUI's [attempt view](../tui/agent-workflows.md#prior-agent-attempts).

Before invoking the provider, SASE measures the fully expanded continuation against its
context and transport budget. If essential content is too large, the provider is not
called: the follow-up becomes `not-launchable`, the budget decision and composed prompt
remain inspectable, and recovery guidance asks for an adequate checkpoint or a route
with more context. The monitored command is not rerun merely to reconstruct context.

A follow-up that cannot launch keeps its recovery evidence. Before SASE releases the
monitor's workspace, it saves a best-effort `git diff HEAD` plus untracked files as
`diagnostics/worktree_recovery.diff` (recorded as `monitor_worktree_recovery_diff_path`)
and links it from the saved prompt. An agent waiting on that monitor gets a
[terminally blocked wait](../macros/directive-syntax.md#syntax) notification that names
the `sase monitor resume <id>` command and the saved diff. If the follow-up was blocked
only because the starter had not settled yet, a later `sase monitor resume` repairs the
missing parent link and launches normally.

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
[Visibility](monitor-operations.md#visibility) below for how a dropped or degraded
follow-up is surfaced.

The follow-up prompt's body is enclosed in a macro-disabled region, so directives,
`#macro` references, and `$(...)` command substitution inside `--reason`, `--next`,
table fields, diagnostics, and embedded output are delivered as literal text. Only the
routing prefix remains live: `#fork:`, `%model:`, `%effort:`, a `%queue(...)` line that
carries the monitor's recorded queue weight (plus any recorded priority or capacity),
and the starter's VCS workspace reference. Successors inherit autonomy structurally from
the starter member's live record; an explicit `%auto` in agent-authored follow-up text
can only narrow, and a widening request keeps the inherited record. When
`--next-output tail` is used, retained output is also fenced and labeled as untrusted
program output. The command and cwd fields are fenced too, so directive-shaped strings
inside a shell command or path remain literal even if the disabled region is ever
removed. `--next-output auto` defaults completed runs to facts and refs, failed runs to
bounded selected diagnostics when available, and timeouts to a bounded raw tail. Use
`--next-output file` for large or hostile logs when the follow-up should inspect the log
explicitly, or `--next-output none` when the outcome summary and
`sase monitor show --all-lines` pointer are enough. The continuation evidence limits
live under `monitor.evidence_limits` in `sase.yml`; the shipped defaults are 8 KiB
selected diagnostics, 4 KiB fallback tail, 12 KiB total raw excerpt budget, and 200
raw-tail lines.

## Runner slots

A monitor is not a way to free runner capacity. The session keeps its one weighted claim
against [`max_running_agents`](../config/agents-and-runners.md#maxrunningagents) for the
monitor's whole lifetime, and the monitor inherits the starter's queue weight. The
starter's runner process exits at handoff, but occupancy stays continuous: the monitor
member counts as soon as it has a recorded supervisor pid. An ordinary follow-up carries
that weight forward in its `%queue(...)` prefix and, as a serial session member,
continues the session's claim. A fire-and-forget monitor (an outcome policy with no
continuation) still holds the claim until the command settles. In-process successors
such as `sase pipe` keep the same session's claim as well; they never become a second
occupant.

The host-owned monitor that launches an approved epic is the exception: it records an
explicit zero queue weight and consumes no capacity, because the phase agents it
launches claim their own. That host-set zero applies to the monitor member only:
successors inherit the starter's weight (or the default `1.0`), never the monitor's
zero. Only a user-authored `%q(w=0)` propagates zero weight to successors.

Holding a claim and waiting for one stay separate. Only a root or a live parallel clan
member parks at the gate. Serial session members — the monitor and any ordinary
follow-up included — ride the claim the session already holds. See
[Agent queued for a runner slot](../runner-slots.md).

## Related

- [Monitor operations](monitor-operations.md)
- [Named tools and ToolRuns](tools.md)
- [`sase monitor`](../cli/monitor.md)
- [Automation migration notes](../upgrading/automation.md)
