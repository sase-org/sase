# Named Tools and ToolRuns

A **named tool** is a project-declared command (`check`, `test`, ...) that
`sase tool run` executes exactly as declared and records as a **ToolRun**: who ran it,
when, with what result, how long each stage took, and what the repository and host
looked like before and after. History is machine-local and useful immediately.

A ToolRun is an execution record. It is not an [LLM Calls](ace.md) row, which is only
the Agents-tab view of what a provider did inside an agent run.

## Try it

```bash
sase tool                                   # list the catalog with LAST and TYPICAL
sase tool run check                         # run `just check`, record a ToolRun
sase tool run test -- tests/tool            # extra args, only where the tool allows them
sase tool run -- sh -c 'echo hi; exit 3'    # ad-hoc argv; the `--` is mandatory
sase tool runs -n 5                         # newest recorded runs for this project
sase tool show RUN                          # one run: stages, evidence, samples
sase tool show RUN -l                       # replay the retained full stdout/stderr
sase tool show RUN -j                       # the complete versioned JSON record
```

## Catalog provenance

Named tools live under `tools:` in the **project's own** `sase/sase.yml` and are read as
complete entries. User, machine, plugin, and builtin config cannot supply or alter argv;
a `tools:` key in those layers is diagnosed and ignored. Malformed entries are errors
(exit `2`) that name the entry and field, and nothing is spawned. Argv is never expanded
for shell syntax or environment variables; write `[sh, -c, ...]` when a shell is wanted.
Named tools run at the project root, ad-hoc commands at the invocation directory. See
the [field reference](configuration.md#sase-tool).

`tool_runs:` (retention and log caps) is separate operational policy and follows
ordinary config precedence.

## Project identity

Every run is recorded under the project identity of the repository that owns its
catalog, and an ad-hoc run under the identity of its working directory's repository.
That one identity fills `runs.project`, `fingerprint_before/after.project_identity`, and
`fingerprint.repos[0].identity`, and it is what `sase tool runs` (without `-a`) scopes
to. So `sase tool run check` from a linked repo checkout such as
`sase/repos/linked/sase-core` is recorded as that repo's `check`, not as the host
project's, and the two never share history, LAST, or flake evidence.

A repo that is a registered project keeps its registry key (`sase-core`,
`gh_sase-org__sase`). Any other repo gets a stable key derived from it:
`gh_<owner>__<repo>` from a GitHub `origin`, otherwise its directory name with a `_<N>`
workspace suffix stripped, so every numbered checkout of one repo shares an identity. A
repo nested inside another checkout is never claimed by it. `SASE_PROJECT` names the
agent's own project and is not consulted.

Rows recorded before this rule keep the identity they were recorded with; they are not
rewritten. Linked-repo `check` runs from that period carry the host project's identity
and are told apart only by `definition_digest`.

## Stage recording

A stage recorded by `tools/run_silent` is one row of the enclosing run. The stage
command runs without `SASE_TOOL_RUN_EVENTS` and `SASE_MONITOR_DIAGNOSTICS_DIR`, so a
nested `tools/run_silent` (or a test that invokes one) records nothing into the
enclosing run's stage timeline or monitor diagnostics. `SASE_TOOL_RUN_ID` stays, so a
nested `sase tool run` keeps its parent link. The test suite scrubs those variables and
`SASE_TOOL_RUN_ID` at session start, which covers `stages: none` tools such as `test`; a
test that needs them sets them explicitly.

## Run output versus retained output

A human at a terminal gets the child's stdout and stderr passed through unchanged; the
wrapper's own metadata goes to stderr. Every run also retains full output privately,
capped per run, and it is only shown by `sase tool show RUN -l`; truncation is stated
explicitly. Default JSON never contains child output.

| Flag | Meaning                                                                     |
| ---- | --------------------------------------------------------------------------- |
| `-q` | Compact output: metadata, the last `-T` failure lines, and a `show` pointer |
| `-T` | Tail lines kept in compact output (default 200)                             |
| `-v` | Stream child output live                                                    |

When retained output overflows `tool_runs.run_log_max_bytes`, the child is still drained
and streamed in full. The run footer, `sase tool show RUN -j` (`output_truncation`), and
`sase tool show RUN -l` each state how many bytes were dropped per stream, so a capped
log is never mistaken for a complete one.

Precedence: an explicit `-q` or `-v` wins; otherwise a direct agent invocation
(`SASE_AGENT_NAME`) defaults to compact and everything else streams. When the run is
already owned by a running monitor or proc that captures the output, the tool writes no
duplicate log and records the owner id and parent run instead. An inherited monitor or
proc id whose owner has already settled (agents launched by a monitored epic launch
inherit that id) is stale: it owns nothing and is not recorded. A SASE agent is always a
new ownership root: agent launches scrub every inherited `SASE_TOOL_*`,
`SASE_MONITOR_*`, and `SASE_PROC_*` variable (including `SASE_TOOL_BYPASS`), and a run
started from an agent's shell never attributes itself to an ancestor's monitor, proc, or
parent run.

## Stream fidelity

The child gets a single merged pipe (stdout and stderr into one stream, one pump)
whenever a single target receives both streams: when an enclosing owner holds the output
(monitor logs, `2>&1` tails), or when the wrapper's own fds 1 and 2 name the same device
and inode. Only the merged mode preserves the child's stdout/stderr interleaving; two
pipes pumped on two threads regroup output by stream. Inline compact mode (`-q`, or the
agent default) retains separate stdout and stderr logs and therefore keeps two pipes
even when the wrapper's fds share a target.

Merged runs retain the interleaved bytes in the stdout log; the stderr log stays empty.
`sase tool show RUN -l` replays each retained file to its own stream and claims no total
order between two retained streams: order across stdout and stderr is meaningful only
for merged runs.

## History and retention

`sase tool runs` filters by `-t` tool, `-s` state, `-A` agent, `-a` all projects, and
pages with `-n`/`-c`. `sase tool list` reports LAST (the newest native result) and
TYPICAL (the median of up to 30 normally exited runs in 30 days with the same
definition, no appended args). No samples render as an em dash, never as an ETA.
`sase disk list` shows the ToolRun owner, and `sase disk reap` previews its retention.

Retention keeps run summaries for `summary_days`, detailed stage and sample rows for
`detail_days`, and retained output and event files for `log_days` after settlement.
`log_max_bytes` is an aggregate target: once age has been applied, the oldest settled
runs' files are selected until the remainder fits. Unsettled runs and their files are
never selected; if they alone exceed the target, the preview and apply report the
`over_target_bytes` instead of hiding it. Reclaimed bytes count only files actually
unlinked (no-follow, confined to the ToolRun root), never SQLite row deletion.

## Incomplete evidence

Missing observations are recorded as absent with a typed reason: an unsupported host
field, a probe that timed out or exited non-zero, an input that does not exist, an
exhausted observation budget. They are never replaced with zero, and a run is never
called `mutated_input` unless both fingerprints are complete. A run whose wrapper was
SIGKILLed is later reported `lost`, without a guessed duration or exit code.

## Failure semantics

The child's exit code is returned, or `128+signal`; catalog and usage errors return `2`.
If recording fails (unwritable store, lock contention), the command still runs exactly
once with the same argv and exit code, a single warning is printed, and no durable id is
claimed. SIGTERM and SIGINT are forwarded and produce `143`/`signaled` and
`130`/`interrupted`.

Under a live monitor or proc owner the child shares the wrapper's process group, so the
owner's stop reaches the whole tree and the wrapper does not escalate on its own. An
inline run puts the child in its own session and escalates a forwarded SIGTERM/SIGINT to
SIGKILL on the child's process group after 5 seconds; on Linux the child is also killed
if the wrapper dies. When a later `sase tool run` finds a run whose wrapper is gone (the
run is settled `lost`), it reaps that run's leftover process group with SIGTERM, then
SIGKILL after 2 seconds, but only while the group leader still matches the recorded
child's start identity; a reused PID is never signaled. `sase tool runs` and
`sase tool show` reconcile lost runs without signaling anything.

## Hand-off and lifecycle control

A handed-off run has a durable identity before its caller lets go. The launcher reserves
a `created` run that already names its owner (a proc or a monitor), then starts the
owner, whose command is a hidden worker that atomically claims that exact run and
executes the frozen invocation. The printed handle is durable from the reservation on:
the run stays discoverable, followable, waitable, and stoppable through its id, and it
settles to either an authoritative outcome or an explicit, typed uncertainty. One
ToolRun links to exactly one proc; each `-H` invocation is a new request, and a run id
executes at most once.

```bash
sase tool run -H check     # returns at once with a run id; the shell may close
sase tool show RUN -F      # stream the run live until it settles, then summarize
sase tool wait RUN         # block until it settles; exit with its exit code
sase tool stop RUN         # ask the owner to stop it; reports requested vs stopped
```

Agents hand off through `sase monitor start` (which reserves the run and prints its id
before the turn ends); `sase tool run -H` refuses inside an agent or a live owner with
the exact monitor form to use instead (exit `2`).

Recording failures behave differently by leg. Explicit `-H` is **fail-closed**: if the
reservation cannot be committed, nothing starts (exit `1`, "nothing was started").
Foreground `sase tool run` stays **fail-open** as above. A monitor start's reservation
is **fail-open**: it falls back to wrapped execution with one reason line in the monitor
log, since the monitor id itself is already durable.

Every settlement records a typed `terminal_cause`: `exited`, `signal`, `interrupt`,
`stop_requested`, `timeout`, `launch_failed`, `owner_lost`, or `wrapper_lost`. A stop
settles `signaled`/`stop_requested`, including before the command started ("command was
not run"). Killing any process leaves either a recoverable run or a run that says, in a
typed field, why its outcome is unknown — nothing is replayed and no success is
fabricated. A reboot yields truthful reconciliation (`lost`), never a rerun. One ToolRun
is not an exactly-once guarantee for external side effects: a lost acknowledgement
retried by the caller creates a second run, and each run executes once.

Platform note: a terminal-launched proc stays in the terminal's cgroup unless its
`detach_scope` escapes to a scope; closing the terminal then still reaches the run.
`show` on a run whose owner row or logs were pruned reports the owner and the log as no
longer retained, by name — the summary survives.

## Rerunnable harness

```bash
just smoke-tool-runs                                    # core smoke + fixture harness
tools/smoke_sase_tool_runs --sase .venv/bin/sase -j     # per-case JSON report and DoD map
tools/smoke_sase_tool_runs --live                       # also real monitor/proc owners and overhead
tools/smoke_sase_tool_runs --keep                       # keep the temp fixtures (path printed)
```

The harness drives the executable named by `--sase` (default: `sase` on `PATH`) against
an isolated `SASE_HOME`, a private `HOME` so user config and plugin overlays cannot leak
in, a temporary git project, and a known fixture catalog. It inspects the real store
through versioned queries; it never runs the expensive SASE catalog, and its only fault
injection is at the filesystem and process boundary. The report records which Python and
`sase_core_rs` module the executable actually loaded. Default mode runs every hermetic
case and labels the live cases `not-run`; `--live` adds a real monitor, a real proc, the
hand-off fault matrix (acceptance, stop races, viewer detach, worker crash, delivery,
monitor hand-off), and the cold-start overhead measurement.
`tests/test_sase_tool_runs_smoke.py` is the pytest twin and shares the same cases.

A `--keep` directory holds one `world-*` subdirectory per case group. Inspect one with
`SASE_HOME=<kept>/world-NAME/sase-home HOME=<kept>/world-NAME/user-home sase tool runs -a`.

## Guarded recipes

`check` and `check-full` are guarded: run as a SASE agent, `just check` refuses unless
it runs inside `sase tool run check` for that project root, or with an explicit bypass.
`test` and `install` are never guarded. The guard is a guardrail against habit, not a
security boundary.

```bash
sase tool run check                                # the wrapped form agents use
SASE_TOOL_BYPASS='<why>' just check                # run raw on purpose; the value is the reason
```

### The environment contract

Three variables decide everything, and the decision is makeable without starting a
`sase` process — the override exists precisely for when `sase` is broken. Any repo can
implement this table from scratch (linked-repo catalogs do exactly that):

| Variable                 | Set by                  | Meaning                                                                       |
| ------------------------ | ----------------------- | ----------------------------------------------------------------------------- |
| `SASE_AGENT`             | the agent runner        | this process tree is a SASE agent's own shell                                 |
| `SASE_TOOL_NAME`         | `sase tool run`, always | the tree is inside `sase tool run <name>`, or `ad-hoc`                        |
| `SASE_TOOL_PROJECT_ROOT` | `sase tool run`, always | the resolved project root the named run executes in; empty for an ad-hoc run  |
| `SASE_TOOL_BYPASS`       | an agent or human       | run raw on purpose; any non-empty value bypasses, and the value is the reason |

`SASE_TOOL_NAME` is exported whether or not recording succeeded: recording stays
fail-open, so a guard keyed on the run id would refuse the child of a fail-open
`sase tool run check` and tell the agent to run the command it is already running.

`SASE_TOOL_PROJECT_ROOT` exists so a wrapper marker from one checkout cannot satisfy
another checkout's guard: the guard requires the name _and_ the root to match. Ad-hoc
runs (`SASE_TOOL_NAME=ad-hoc`, empty root) never match a guarded recipe's name.

### The guard rule

An agent may run a guarded recipe only from inside `sase tool run <that tool>` for
_that_ project root, or with an explicit bypass. The match is strict:
`sase tool run -- sh -c 'just install && just check'` does not satisfy the `check`
guard, because the named identity is what run history, fingerprints, and receipts key
on.

The guard is `tools/require_tool_run`, a dependency-free POSIX `sh` script wired as the
**first** `just` dependency of each guarded recipe, ahead of `_setup`. It refuses — it
does not redirect — printing the wrapped form and the bypass form and exiting 2:

- `SASE_AGENT` unset (humans, CI, finalizers, monitors, procs): allowed, silently.
- `SASE_TOOL_NAME` equals the tool _and_ `SASE_TOOL_PROJECT_ROOT` is the recipe's own
  root: allowed, silently.
- `SASE_TOOL_BYPASS` non-empty: allowed, with one stderr line naming the reason.
- `sase` not on `PATH` at all: allowed with one stderr line — fail open, since there is
  no wrapped form to print.
- Otherwise: refused with the wrapped and bypass forms on stderr, exit 2.

### Monitor wrapping

The guard cannot see detached runs: monitor supervisors scrub agent identity on purpose.
`verify`-profile monitors therefore wrap what they run — an exact catalog match upgrades
to a named `sase tool run <name>`, anything else wraps ad-hoc — in the proc argv only,
leaving the recorded command and `-f` completion bindings untouched. See
[Monitors](monitors.md) (§"Tool-run wrapping") for the policy table and the
`monitor.tool_wrap` config field.

## Measuring adoption

```bash
tools/tool_adoption_report -d 7 -j
```

The read-only report pairs each agent's normalized LLM tool-call records (per file, by
`tool_use_id`), classifies heavy (>=20 s) `just check` / `just check-full` invocations
as wrapped in `sase tool run`, raw, or bypassed (`SASE_TOOL_BYPASS=... just check`), and
reports count and wall-time shares with their denominators. It also counts refusals: an
exit-2 raw call carrying the guard marker, followed by a wrapped call. Each call is
filtered by its own timestamp rather than its file's modification time, so a window
cannot mix in older calls. Unpaired, negative, over-six-hour, truncated, undated, and
ambiguous (pipelines, multi-command) records are counted, not guessed. It does not read
the ToolRun ledger, so ledger counts and recording errors are separate coverage signals.
