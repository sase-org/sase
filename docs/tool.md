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
inherit that id) is stale: it owns nothing and is not recorded.

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
case and labels the live cases `not-run`; `--live` adds a real monitor, a real proc, and
the cold-start overhead measurement. `tests/test_sase_tool_runs_smoke.py` is the pytest
twin and shares the same cases.

A `--keep` directory holds one `world-*` subdirectory per case group. Inspect one with
`SASE_HOME=<kept>/world-NAME/sase-home HOME=<kept>/world-NAME/user-home sase tool runs -a`.

## Measuring adoption

```bash
tools/tool_adoption_report -d 7 -j
```

The read-only report pairs each agent's normalized LLM tool-call records (per file, by
`tool_use_id`), classifies heavy (>=20 s) `just check` / `just check-full` invocations
as wrapped in `sase tool run` or raw, and reports count and wall-time shares with their
denominators. Unpaired, negative, over-six-hour, truncated, and ambiguous (pipelines,
multi-command) records are counted, not guessed. It does not read the ToolRun ledger, so
ledger counts and recording errors are separate coverage signals.
