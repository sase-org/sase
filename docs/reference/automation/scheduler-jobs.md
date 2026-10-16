---
title: Scheduler jobs
description:
  Script jobs, manual runs, job history, service views, and job-agent records.
---

# Scheduler jobs

This page covers scheduler job definitions, runs, and their service views.

## Script Jobs

Every job is an external executable. Axe resolves the exact configured `script` value
(or `name` when `script` is omitted) in this order:

1. An exact-name executable in one of `axe.job_script_dirs`.
2. An exact-name executable beside the running Python interpreter.
3. An exact-name executable on `$PATH`.

No prefix is added automatically. Builtin jobs therefore declare names such as
`script: sase_job_hook_checks` explicitly. As a discovery convenience, the
available-script inventory (`sase axe job list -a`) lists every executable in
`axe.job_script_dirs` plus `sase_job_*` executables beside the interpreter and on
`$PATH`. `sase_chop_*` executables are still installed and discovered, but when both
spellings resolve to the same file or console-script entry point the inventory shows
only the `sase_job_*` name. Resolution always uses the configured full name. See
[Automation migration notes](../upgrading/automation.md#scheduler-routine-and-job-names).

Axe runs script jobs as:

```bash
<script> --context <context.json>
```

The context file contains the effective runner limits, zombie timeout, query, routine
name, routine state directory, paths to serialized `all_changespecs.json` and
`filtered_changespecs.json` files, the current `target`, configured `vars`, the run
source (`scheduled`, `manual`, or `oneshot`), the `dry_run` flag, and the run-local
result path. The result path is also exported as `SASE_JOB_RESULT_FILE`; the source and
dry-run flag are mirrored as `SASE_JOB_SOURCE` and `SASE_JOB_DRY_RUN` (`1` for true, `0`
for false). `SASE_JOB_VERBOSE` enables opt-in debug output. Target fields are exported
as `SASE_JOB_TARGET_<FIELD>` along with `SASE_JOB_TARGET_KEY`. Each of these variables
is also mirrored under its `SASE_CHOP_*` spelling for older scripts; configuring both
spellings with different values is rejected. Scripts with direct side effects must honor
`dry_run` before mutating external state; runner-level dry-run only previews launch
proposals. Scheduled script jobs within one routine tick run concurrently; use `timeout`
or `job_timeout` to keep a slow script from blocking later ticks indefinitely.

Script job stdout and stderr are streamed to the job's per-run log file while the
subprocess is still alive (see [Job Run History](#job-run-history) below). The
Services-tab dashboard tails that file so a long-running job's output becomes visible
immediately rather than only after process exit.

Job output is part of the operator contract. Every actual job run should write a
compact, human-readable summary for both no-op and action paths. At minimum, include the
job identity or run scope, counts of inspected/skipped/updated or launched items, an
explicit no-op reason, and bounded identifiers for any affected items. Avoid tokens,
full notification bodies, full prompts, and unbounded command output in ordinary AXE
logs. A job with a meaningful structured story should also publish a report while
keeping this compact stdout summary unchanged; logs and notifications continue to use
the summary line.

### Structured Results and Launch Proposals

Exit-code-only scripts remain supported: exit zero means `success`, a non-zero exit
means `failure`, and no result file is required. A proposal-emitting script atomically
writes a schema-versioned JSON document to `SASE_JOB_RESULT_FILE`:

```json
{
  "schema_version": 1,
  "status": "ok",
  "summary": "refresh_docs: targets=1 proposals=2",
  "counters": { "targets": 1, "proposals": 2 },
  "proposed_launches": [
    {
      "id": "update",
      "prompt": "Refresh the user documentation.",
      "workspace": "gh:sase-org/sase"
    },
    {
      "id": "polish",
      "prompt": "Fact-check and polish the documentation update.",
      "workspace": "gh:sase-org/sase",
      "wait_on": "update"
    }
  ]
}
```

Result `status` is `ok`, `no_op`, or `check_error`. Results can also carry a `reason`,
integer `counters`, and relative `evidence` file paths. Each proposal requires `prompt`
and `workspace`; optional fields are `id`, `agent_name`, `clan`, `clan_summary`,
`tribe`, `model`, `effort`, `env`, `dedupe_key`, and `wait_on` (an earlier proposal
index or ID). With `clan`, `agent_name` is the member ID and the runner owns concrete
clan allocation plus the full `<clan>.<member>` identity. Clan proposals cannot also set
`tribe`; the first accepted member declares the clan with the default job tribe.

The built-in job tribe is stored under its historical `chop` identity and displayed as
`job` on public surfaces. A proposal that sets `tribe: job` (or omits `tribe`) resolves
to that stored identity before anything is written, so scaffolded directives read
`tribe=chop`. Tribe resolution is provenance-aware: agents whose stored tribe is already
a literal `job` keep it, and configuring display entries for both `ace.tribes.job` and
`ace.tribes.chop` is reported as an alias-collision diagnostic.

`clan` and `agent_name` may each carry at most one `@` auto-name template marker, so a
composed clan-member identity holds up to two. The runner resolves them in two stages:
it picks one clan token for the whole group first, then allocates each templated member
name inside that concrete clan, so `clan="toobig-@"` with
`agent_name="split_file.src.pkg.large.@"` plans to
`toobig-0.split_file.src.pkg.large.0`. Two members sharing one template therefore land
on `.0` and `.1` instead of colliding. A clan token is taken only when the clan name and
every member identity in the group are free together; otherwise the whole group moves to
the next clan token and the member tokens tried under the rejected one are discarded.

`clan_summary` is an optional literal Rich-markup summary and is valid only with `clan`.
Every non-null summary attached to the same raw clan template must be identical; members
that omit it inherit that agreed value before once-per filtering. The first accepted
member therefore retains and declares the summary even when an earlier member is
deduplicated. Different raw clan templates may have different summaries. A summary must
be nonblank, contain no NUL byte, fit within 32 KiB of UTF-8, and avoid both the `]]`
text-block terminator and `+` (which macro argument decoding would turn into a space).

A proposal that also carries an active `%if` predicate is admitted through the typed
launch path (see
[Agent Launch Flow](../../contribute/architecture.md#agent-launch-flow)), so a member
statically planned to declare the clan can still be skipped at admission time. That
promotion works the same way once-per filtering already promotes the first accepted
member: admission-time filtering promotes the first surviving (eligible, dispatched)
member of an undeclared clan to declarer regardless of which member was planned to
declare it, carrying the group's agreed `tribe` and `clan_summary` with it. A skipped or
condition-errored member never claims the role, and an all-skipped batch declares no
clan. The declarer claim is recorded durably before that member's launch attempt runs,
so a launch failure cannot let a later member declare the same clan a second time, and a
detached coordinator resuming in a fresh process still honors an earlier claim.

`report` is an optional structured document rendered with the result on sase's TUI
Services tab. Job authors supply semantic tones rather than colors, and the frontend
owns the palette and width-responsive layout. The public SDK keeps report construction
typed and validates the finished result through the Rust contract:

```python
from sase.jobs import JobReport, JobResultBuilder

report = JobReport(title="CI WATCH")
report.headline("4 green · 1 red · 1 fix proposed", tone="warn")
report.heading("REPOSITORIES")
rows = report.rows(columns=("REPOSITORY", "STATE", "EVIDENCE"))
rows.row(("sase-org/sase", "red", "ci / test · streak 2/2"), tone="error")
rows.row(("sase-org/sase-core", "green", "a1b2c3d"), tone="ok")
report.divider().kv({"mode": "dry run"}, tone="muted")

JobResultBuilder(
    status="ok",
    summary="ci_watch: repos=5 green=4 red=1",
    report=report,
).write(context=invocation.context)
```

A report has an optional `title` and a non-empty `blocks` list. The closed block
vocabulary is:

- `headline`: `text` and optional `tone`.
- `heading`: `text`.
- `text`: literal `text` and optional `tone`.
- `kv`: non-empty `items` of `key`, `value`, and optional `tone`.
- `rows`: optional `columns` plus non-empty `rows`; each row has `cells`, optional
  `tone`, and optional `glyph`.
- `bullets`: non-empty `items` of `text`, optional `tone`, and optional `glyph`.
- `gauge`: `label`, non-negative `value`, positive `max`, and optional `tone`. Values
  may exceed `max`.
- `divider`: no additional fields.

The tone vocabulary is `neutral` for ordinary content, `muted` for secondary context,
`info` for useful context, `ok` for healthy outcomes, `warn` for attention, `error` for
failures, and `accent` for report emphasis. A job cannot supply a color. Optional row
and bullet glyphs are restricted to `▲ ◆ • · ● ○ ✓ ✗ ↗ ↷ ⏱ ! ▸ ─`; omitting a glyph lets
the renderer choose one from the tone.

The validated report must fit within 32 KiB of UTF-8 and contain 1–48 blocks. A `kv`,
`rows`, or `bullets` block holds 1–64 entries. Rows contain 1–6 cells; when column names
are present there must be 1–6 of them and every row must have the same number of cells.
Titles are limited to 64 characters, and every other string field to 512 characters.
Required strings must be nonblank single-line text with no control characters.
`JobReport` collapses whitespace, removes controls, truncates bounded strings with a
trailing ellipsis, drops empty blocks, and rejects invalid tones, glyphs, gauges, or row
shapes before writing. Unknown fields, block kinds, and tones are rejected fail-closed
by result validation.

The runner validates the full document before launching anything. It injects the
workspace reference, a deterministic agent name and the job tribe (`tribe=chop`) in one
`%id(...)` directive, model/effort directives, and a `%wait` dependency for `wait_on`,
then launches proposals in document order. Clan-scoped proposals are preplanned as one
multi-prompt batch: the first surviving member declares one concrete clan generation and
later members join it, while waits use their full resolved names. The declarer receives
`%id:<full name>` plus `%clan(<name>, tribe=chop)`, or
`%clan(<name>, tribe=chop, summary=[[<literal Rich markup>]])` when it carries a
summary; joiners receive only `%id(<member>, clan=<name>)`. Axe neither executes the
summary as a script nor inserts it into any proposal's work prompt. Standalone
`#!workflow` references are forbidden in proposal prompts; reusable inline `#macro`
references remain valid. The runner records every launched agent in `agent_chops.json`
and finalizes the job only when the linked agents reach terminal state.

A launcher can still fail partway through an otherwise valid batch. The caller receives
`action_failed` immediately. When at least one proposal already started, however, the
persisted job run remains active as `launched` until every started agent finishes; it
then finalizes as `action_failed` with both the original launch error and any agent
failures. Once-per keys for accepted proposals that never started are released
immediately. A started proposal keeps its key while it runs, then releases it only if
that agent fails, so successful work remains de-duplicated. A key-release error is
appended to the job output and does not replace the original launch or agent outcome.

A proposal's `prompt` may contain typed directives such as `%if::` (a Bash or Python
condition fence) or `%proc`. A batch containing an active directive routes through the
same durable typed admission coordinator used by sase's TUI, `sase run`, and
LaunchApproval, joining AXE as a fourth typed-admission source; see
[Agent Launch Flow](../../contribute/architecture.md#agent-launch-flow). A `%if`
predicate evaluates after its unit's `%wait` dependency settles and before any runner,
agent identity, proc identity, or model request is allocated. For a selected managed
project, the predicate itself briefly uses a claimed, prepared operational workspace so
stale job checkouts can observe newer pushed work before admission decides. Exit `0`
admits the unit normally; exit `1` records a skip with no runner, identity, proc, or
model allocation. AXE owns the admission bundle across the run, keeping the job in
active `launched` state until every admitted unit reaches its own terminal state, and
treats predicate skips as successful no-op outcomes rather than once-per duplicates or
launcher errors. A structured proposal `wait_on` becomes both a typed admission-order
edge and, for an admitted Agent unit, a restored named-agent `%wait` in the prompt AXE
dispatches to the runner. If admission skips or condition-errors an intermediate
proposal, AXE relinks that runner wait to the nearest earlier proposal that actually
launched; if no ancestor launched, it dispatches without a named wait. A batch with no
active `%if`/`%proc` directive keeps using the plain launch path unchanged.

Python job packages should use the public `sase.jobs` SDK (`load_job_invocation`,
`JobLogger`, `JobReport`, `JobResultBuilder`, and `launch_proposal`) for argument
parsing, summaries, reports, validation, and atomic result writes.

### Publishing a Report a Notification Can Open

Per-job run history is capped, so a report that only rides along with a job result
answers "what did this tick do", not "where do things stand". A job that wants the
second answer should **publish** a standalone report document into its own state
directory (`invocation.context.state_dir`) and point a notification at it:

```python
from sase.jobs import JobReport, validate_job_report

report = JobReport(title="RELEASES")
report.headline("2 merged today · 3 pending", tone="warn")
document = validate_job_report(report.to_dict())
# atomically write `document` to <state_dir>/<name>.report.json on every tick
```

`validate_job_report` runs the same Rust job-result contract used for an embedded
`report`, so an invalid document is caught before it is written; log and skip that tick
rather than raising, leaving the previous good file in place. Rewriting the file on
every tick — including no-op ticks — is what keeps the published picture fresh without
any network call or latency inside the TUI.

The notification then carries `action: "ViewReport"` with
`action_data: {"report_path": "<state_dir>/<name>.report.json", "report_title": "..."}`.
Selecting it in sase's TUI renders the document in the notification modal's right pane
and Enter opens it full-screen; see the notifications reference for the contract, the
inline-snapshot alternative, and the fail-closed loader limits. Prefer the published
path over inlining a snapshot into `action_data` whenever the job has a durable state
directory. Timestamps inside a published document should be absolute, because the file
may be read long after it was written; relative freshness belongs to the single
provenance line the reader sees.

### Triggers, Guards, Dedupe, and Targets

Policy is runner-owned and evaluated before the script:

- `run_every` limits cadence for each expanded job instance. A guard skip does not
  consume this cadence, so a guarded job re-evaluates its guard on the next tick rather
  than waiting out the full interval; a trigger skip (the condition was evaluated and
  not met) still advances the clock as before. Guard evaluation is not free — put a
  guard on a lane whose tick interval matches the cost of re-checking it.
- `inhibit_if` supports `patch`, `agent_hood`, `agent_clan`, and `agent_runners` guards.
  The `changespec` guard key remains accepted as an alias of `patch`.
  `agent_clan.name_prefix` matches canonical clan metadata on active agents only; dotted
  agent names are not treated as clans. `agent_runners.max` defaults to `0` and inhibits
  while more than that many participating lanes are occupied, a participating-lane count
  distinct from the weighted `%queue(capacity=N)` budget. Weighted runner capacity is
  tracked separately by the host-wide capacity budget. A `STARTING` agent has not yet
  been admitted and does not count; an agent parked on a question has yielded capacity
  and does not count. A match records a visible `skipped` run naming the guard and
  matching agent.
- `trigger` defaults to `always`. `git.commits_since` observes a project repository,
  fires when its threshold is met, and owns its checkpoint under the job's state
  directory. A missing checkpoint fires once so a new job is not silently inert.
- `fs` fires when a cheap state token computed from `paths` differs from the token at
  its last fire. Each entry in `paths` is a bare path string or a `{path, glob}` object;
  a bare path is stat'd directly (existence, mtime, size, plus a non-recursive child
  count for directories), and `glob` shallow-matches entries inside a directory path
  (name, mtime, size per match — no recursion, no content reads). Relative paths resolve
  against the SASE state root (`~/.sase`, or `$SASE_HOME`); absolute paths and `~` pass
  through unchanged. `max_quiet` is a required positive compound duration: the trigger
  fires unconditionally once that long has passed since its last fire, even with no
  watched-path change, so a missed observation only delays work. Any watch path that
  cannot be read (as opposed to one that does not exist, which is itself a valid token
  state) fails open and fires without advancing the checkpoint. `fs` always uses
  `on_observation` checkpoint semantics; it has no `checkpoint_policy` setting.
- Checkpoint policy can be `on_observation`, `on_action_accepted`, or
  `on_action_success`. The last option advances only after every linked proposal agent
  succeeds.
- `once_per` renders a bounded per-proposal key; a proposal's own `dedupe_key` takes
  precedence. Duplicate proposals are skipped without relaunching work. Accepted keys
  remain reserved for successful launches, but are released when their proposal never
  starts or its launched agent reaches terminal failure, allowing a later run to retry
  that work. `dedupe_key` is durable work identity, not a retry clock: a key means "this
  is the same unit of work," and a successful no-op launch reserves it permanently. Jobs
  whose work can go stale between scans should recheck eligibility with `%if` (below)
  instead of folding a repository revision into the key.
- `for_each` accepts literal target rows or `source: projects`. Expansion creates stable
  instances such as `refresh_docs[sase-core]`, each with independent cadence, history,
  checkpoints, and dedupe state. Target overrides can patch per-instance fields such as
  `run_every` and trigger thresholds.

Manual CLI/TUI runs bypass configured triggers because the operator explicitly requested
a run, but still honor guards. With `agent_runners`, a manual run while participating
lanes are occupied skips unless `-f/--force` is passed to bypass both for that run.

Once-per filtering keeps proposal chains connected. If a surviving proposal's `wait_on`
points to a duplicate, AXE follows the skipped proposal's own dependency until it
reaches the nearest earlier proposal that also survived the filter. If no such proposal
exists, AXE removes the wait. Dry-run and recorded proposal previews put the resulting
dependency in `wait_on` and explain the change in `dedupe_reason`, so removing duplicate
work does not also discard a new downstream proposal. For a clan, the first surviving
member becomes the declarer; dry runs show the same concrete clan, declaration/join
roles, declarer-only `clan_summary`, full member names, exact scaffolded prompts, and
effective waits without reserving names or spawning agents.

A proposal that supplies an explicit `agent_name` treats a name collision at launch as
idempotency, not failure: the sequential launch path records that proposal as skipped
with a name-collision reason, releases its once-per key, and relinks dependent waits the
same way once-per dedupe does. If every proposal is skipped the run finishes `skipped`;
otherwise launched proposals proceed normally. Collisions on runner-derived names (which
embed a per-run token) and in clan batch launches remain hard failures.

### Builtin `external_pr_mirror`

`sase_job_external_pr_mirror` fans out across enabled `git` and `gh` projects with
`for_each: {source: projects, vcs: [git, gh]}`. Each instance uses the target's
ProjectSpec directory key for local Patch files and the target workspace directory for
provider calls. A structural capability probe skips providers that cannot list PRs.

Incremental runs fetch a bounded PR inventory because the provider seam exposes a record
limit, not pagination. The job records `seen`, `fetched`, `unmirrored`, `created`,
`repaired`, `refreshed`, `skipped`, `conflicts`, `errors`, `budget_exhausted`, and
`checkpoint_advanced` in its summary. Cursor and backoff state live at a stable path
under `~/.sase/external_mirror/`, independent of whichever routine the job is configured
in, so `sase patch sync-external` reads and writes the same files. A ten-minute overlap
window covers incremental passes; the cursor advances only after a clean pass, and a
daily full scan ignores it so missed repairs are eventually found.

`unmirrored` counts fetched PRs dropped by
[`external_mirror.pull_requests.filters`](../config/automation-behavior.md#externalmirror),
which ships with head-ref exclusions for release-please and release-plz PRs so those
never become Patches; every other criterion is empty by default, adopting every other PR
SASE did not create. Dropped records never reach the checkpoint, so a filter change
(clearing, narrowing, or widening one) forces the next pass to go full and re-examine
them. Filters gate creation only — a PR a filter now excludes keeps whatever Patch it
already has. The last pass's `unmirrored` count per project is also written to a
lane-independent document that feeds the CLI's `Filtered` column and the Patches pane's
`· M remote-only` banner chip.

Open draft PRs become `Draft` Patches, open non-draft PRs become `Mailed`, and merged or
closed PRs are appended directly to the archive ProjectSpec as `Submitted` or
`Archived`. The `SASE_PATCH` marker identifies PRs created by SASE's tracked PR
workflow, not PRs created by any SASE agent. An agent that bypasses the tracked workflow
and calls `gh pr create` directly is indistinguishable from a human and is adopted as
`external`.

Adoption is not one-shot: a Patch that already owns a PR is refreshed whenever its
recorded `STATUS` no longer matches the state that PR now maps to, so a PR adopted while
open follows its own merge or close instead of freezing at its adoption-time status. A
refresh rewrites the status in place and, when the PR reaches a terminal state, moves
the Patch out of the active ProjectSpec into the archive. `refreshed` counts these
updates separately from `repaired`, which stays specific to a corrected `PR_ORIGIN`
marker.

Refreshes are guarded to `pr_origin: external` Patches only: a Patch SASE's own tracked
workflow created has a lifecycle AXE owns, and the mirror never writes its status.
Ownership is re-checked under the ProjectSpec lock, so a Patch that changed hands since
the pass planned its work is skipped rather than overwritten. Each refresh is a mutation
charged against the same per-pass budget and deadline as an adoption, which makes the
daily full scan load-bearing rather than merely defensive: a PR that merges long after
adoption can fall outside the ten-minute incremental overlap window.

### Builtin `refresh_docs`

`sase_job_refresh_docs` replaces the former scheduled macro workflow. It expects an
expanded target with a `workspace`, then emits an `update` proposal and a `polish`
proposal whose `wait_on` points to `update`. Commit counting and checkpoints belong to
`git.commits_since`; project fan-out belongs to `for_each`:

```yaml
axe:
  routines:
    docs:
      description:
        Refresh project documentation when repositories accumulate meaningful changes
      interval: 300
      jobs:
        refresh_docs:
          script: sase_job_refresh_docs
          description: Refresh documentation after meaningful repository drift
          run_every: "30m"
          trigger:
            git.commits_since:
              project: "{target.name}"
              threshold: 25
              checkpoint: on_action_success
          for_each:
            source: projects
            vcs: [git, gh]
```

The builtin supplies plain-language update and polish prompts that are strictly scoped
to documentation files. They direct agents to document the current behavior and report
suspected code bugs instead of changing source code, tests, build configuration, or
other non-documentation files. Override the defaults with non-blank `vars.prompt` and
`vars.polish_prompt` strings; operators are responsible for including appropriate scope
restrictions in replacement prompts. The script only proposes work; it never calls
`sase run` or updates marker files.

## Manual Job Runs

Scheduled routine ticks are not the only way a job runs. Operators can launch any
configured job on demand from both the CLI and sase's TUI; manual runs share the same
execution path, run history, and live-output streaming as scheduled runs.

**From the CLI:**

```bash
sase axe job run <job>                    # name must be unique across routines
sase axe job run <job> --routine <routine> # explicit routine (short form: -L <routine>)
sase axe job run <job> --dry-run          # -n: validate and preview; launch nothing
sase axe job run <job> --job-verbose      # -V: script diagnostics + full result
sase axe job run <job> --force            # -f: bypass guards (triggers already bypassed)
```

When the same job name appears under multiple routines, `sase axe job run <job>` fails
with an unambiguous error listing the candidate routines (exit code 2). Pass
`-L/--routine` to pick one. A name that is not configured anywhere but matches a
discoverable executable still runs, attributed to the synthetic `_oneshot` routine. The
CLI run is recorded under `~/.sase/axe/lumberjacks/<routine>/chops/<job>/` exactly like
a scheduled run, except its metadata is tagged with `source = "oneshot"` (vs
`"scheduled"`). The command exits 0 for `success`, `skipped`, `no_op`, `launched`, and
`action_succeeded` outcomes, and non-zero otherwise, including when the same job already
has a live run.

**From sase's TUI:**

On the Services tab, press `r` while a job row is selected to launch that exact
`(routine, job)` manually. The run uses the job's configured script, environment, and
timeout, but bypasses any `run_every` cadence because the user explicitly asked for it.
The TUI does not block while the script runs; once the subprocess starts, the new run
becomes the newest entry in the job's run history and the detail panel switches to it.

If the selected job already has a live script run in flight for the same
`(routine, job)`, `r` notifies and skips the launch rather than starting an overlapping
duplicate. On non-job rows — routine rows and running bgcmd rows — `r` is a no-op; on a
completed bgcmd row, `r` continues to re-run the bgcmd.

Manual runs participate in `Ctrl+N` / `Ctrl+P` history navigation just like scheduled
runs. TUI runs are tagged `source = "manual"`, and the job-detail header marks any
non-scheduled run with a `Source:` chip (`manual` or `oneshot`) so it is easy to tell at
a glance why a run started.

## Job Run History

Every job execution — whether kicked off by a scheduled routine tick or by
`sase axe job run …` — is recorded as a separate run under
`~/.sase/axe/lumberjacks/<routine>/chops/<job>/`. Each run is assigned a sortable,
microsecond- precision `run_id`. `index.json` (kept next to `runs/`) lists the job's run
IDs newest-first:

```
~/.sase/axe/lumberjacks/<routine>/chops/<job>/
├── index.json              # Ordered run IDs (newest first)
└── runs/
    ├── <run_id>.json         # Run metadata (see below)
    ├── <run_id>.log          # Streamed stdout+stderr from the job process
    ├── <run_id>.context.json # Private context passed to this invocation
    └── <run_id>.result.json  # Structured result, when the script writes one
```

Each `<run_id>.json` is a serialized `ChopRunEntry` (see `src/sase/axe/state.py`). The
most relevant fields are `status`, `started_at`, `finished_at`, `duration_ms`,
`exit_code`, `pid`, `source` (`scheduled`, `manual`, or `oneshot`), `started_by`,
`output_bytes`, `result`, proposal previews, launches, and the recorded skip/error
`reason`.

A run starts as `running`. Exit-code-only scripts end as `success`, `failure`,
`timeout`, or `missing_script`. Policy rejections are `skipped`; structured healthy
no-work and degraded probes are `no_op` and `check_error`. A result with accepted
proposals moves to `launched`, then the housekeeping pass finalizes it as
`action_succeeded` or `action_failed` from linked agent completion artifacts. `running`
and `launched` are active states, so `finished_at` is `null` for both.

If a linked agent's process has stopped and its live `done.json` is absent, finalization
looks for the top-level dismissed-agent archive entry with the same artifact timestamp.
Workflow-child archive rows do not stand in for that top-level run. Only a `DONE`
archive status counts as success; `FAILED`, `KILLED`, any other status, or a missing
entry fails the action.

History is pruned after every run write, retaining the newest `MAX_CHOP_RUN_HISTORY`
(10) terminal runs per job. Active `running` and `launched` entries are always kept
regardless of position, so slow scripts and pending actions are never deleted out from
under their lifecycle owners.

## Services Tab Views

The Services tab sidebar is four panels: **Service Procs** (daemon procs plus any
background commands (`!!`) under a `── oneshots ──` divider) followed by one panel per
routine declaring source — **User Routines**, **Plugin Routines**, then **Builtin
Routines** — each routine a top-level row with its configured jobs as indented children.
Source is the first config layer that declared the routine, not the layer that last
changed one of its fields: a builtin routine with a user interval override stays
Builtin, a plugin routine with user overrides stays Plugin, and jobs always render in
their parent routine's panel. Routines sort alphabetically within their panel so status
or interval changes never reorder rows. `j` / `k` move across panel boundaries on the
underlying global list, while `J` jumps to the first row of the next panel and `K` to
the last row of the previous panel (wrapping, skipping empty panels). Builtin rows start
folded on first sight (`ace.services.fold_builtin_routines`, default `true`); a folded
row still reports its jobs' health as a red `!N` badge on the parent row. Each job row
shows a status marker derived from its newest cached run: active `running` / `launched`,
successful `success` / `action_succeeded`, healthy `no_op`, policy `skipped`, degraded
`check_error`, failed `failure` / `timeout` / `action_failed`, or `missing_script`. Jobs
with no history remain marked as never run. Selection drives three distinct dashboard
views:

- **Routine overview** — selecting a routine row shows its status, interval, cycle
  count, error count, and a per-job table with each job's last-run status, relative
  timestamp, and duration. For a job whose newest run is still active, the duration
  column shows live elapsed runtime rather than the stale `0ms` you would otherwise see
  before the run finalizes.
- **Job detail** — selecting a job row renders one width-responsive document. A
  universal **RESULT** card summarizes status, counters, reason, dry-run/source markers,
  proposals, launches, evidence, and failures from the cached run entry. A job-authored
  structured report follows when the result document provides one, then **OUTPUT**
  preserves the run's ANSI-rendered `.log` tail. Until the log has accumulated any
  bytes, the output section shows a `Waiting for output…` placeholder; the exit code is
  suppressed until the run finalizes. Active `running` and `launched` runs continue
  following the output tail, while selecting a terminal run leaves the RESULT card at
  the top of the scroll region.
- **Background command output** — the live output stream of the focused `!!` oneshot row
  (its durable proc log), with the recorded exit code in the status line once it
  finishes.

A job whose run blocked its routine's tick for at least the routine's `interval` is
marked **overrun** — amber `⚠` with a `2.4×`-style ratio of blocking time to interval.
The newest sampled run being over is level `over` (bold); an older sampled run in the
cached history being over while the newest is not is level `intermittent` (dim), so a
job that alternates does not flap its mark on and off across refreshes. The sidebar job
chip and its parent routine's roll-up chip always show the **worst** ratio in the cached
window, so a collapsed-then-expanded tree tells the same story every time; the routine
overview's `PACE` column and the job detail header instead describe the **latest** run
specifically, matching the rest of those views. A job that launches agents is measured
on its script's own wall-clock time, not on how long the launched agents ran — the tick
never waited for them, so their lifetime is excluded from the measurement.

`Ctrl+N` / `Ctrl+P` on the Services tab page through the focused job's run history
(newer / older). The viewer pins to the run you selected so that a fresh tick prepending
a new run does not bump you forward; the pin is cleared automatically if the pinned run
is pruned or itself becomes the newest run.

The same structured report renderer is used by `sase axe job run` when that command
prints a structured result (dry run or job-verbose mode), so semantic tones, rows,
gauges, and literal-text safety do not drift between the CLI and sase's TUI Services
tab.

## Job-Agent Registry

The durable `agent_chops.json` linkage associates launched proposals with job lifecycle
state. Configuration is always script-based. Each launched agent receives
`SASE_JOB_ROUTINE`, `SASE_JOB_NAME`, `SASE_JOB_RUN_ID`, and a prompt hash; the
housekeeping pass uses the registry plus normal agent completion artifacts to finalize
`launched` runs. The same values are mirrored under the `SASE_CHOP_*` names, which are
still accepted from installed callers but are not the documented authoring surface. See
[Automation migration notes](../upgrading/automation.md#scheduler-routine-and-job-names).

Linkage is explicit: a registry record is created only for proposal launches the runner
itself performs and for continuation respawns (retry or model-fallback) of an
already-linked agent. Ambient `SASE_JOB_*` and `SASE_CHOP_*` context is scrubbed from
every other spawned child's environment, so nested launches by job agents and launches
performed by job scripts themselves neither register nor inherit job identity.

Housekeeping matches registry records to the run entry's own recorded launches by
artifacts timestamp, following retry successors through `retried_as_timestamp` chains.
Unmatched records are logged into the run output and ignored for status purposes; a
launch with no matching record still fails the run closed. Records whose run entry is
missing or already terminal are garbage-collected during the housekeeping pass.

## Concurrency Management

Axe uses a cross-process runner pool to enforce global runner-capacity limits. The
`SharedRunnerPool` uses `fcntl.flock` on a shared file
(`~/.sase/axe/shared/runner_count`) to coordinate capacity claims and participating-lane
counts across all routine processes atomically.

Hook runners and agent runners have separate limits (`max_hook_runners` and
`max_agent_runners`), allowing fine-grained control over background resource usage.

## Agent Completion Artifacts

When an agent run finalizes, axe writes the normal completion metadata and sends the
workflow-complete notification. Successful runs also scan the agent workspace for
generated image files (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`), video files (`.mp4`,
`.m4v`, `.mov`, `.webm`), and Markdown files (`.md`, `.markdown`). When 10 or fewer
Markdown sources are discovered after filtering, they are rendered to PDFs under the
agent artifact directory, then the generated PDF paths are appended after the standard
chat/diff notification attachments and before image/video attachments. The PDF list is
persisted as `done.json.markdown_pdf_paths`; the image and video lists are persisted as
`done.json.image_paths` and `done.json.video_paths`. Explicit artifacts created during
the run with `sase artifact create -p <path> [-l <label>] [-k <kind>]` are appended
after generated media attachments when their stored files still exist.

The scan uses git name-status output, untracked files, saved diff metadata, and the
latest commit when the agent committed or opened a PR. Deleted, missing, unsupported,
and duplicate paths are ignored. If more than 10 Markdown sources remain, Axe skips
Markdown PDF rendering for that completion and adds a note to the notification. PDF
rendering is otherwise best-effort: missing conversion tools or render failures omit
that source without failing the agent run. Generated Markdown PDFs are optimized for
narrow viewers with a small portrait page, small margins, and larger type. As PDFs are
prepared, axe updates `workflow_state.json.pdf_status` and a compact `activity` label so
sase's TUI can show live finalization progress such as `PDF 2/4 <path>` or
`PDFs done 3/4 (1 skipped)` in the prompt/detail header's labeled `Activity:` field.
Successful runs also copy discovered media artifacts, plus prompt-referenced images and
videos, into persistent SASE artifact storage for sase's TUI. Prompt-referenced media
are not appended to completion notifications unless they were also generated/modified
files or explicit artifacts. See [`agent_images.md`](../agent-attachments.md) for the
full contract.

The Agents tab exposes completion artifacts through the `a` action. When artifacts
exist, sase's TUI opens the artifact panel for selection. Chat transcripts, plan files,
generated PDFs/images/videos, prompt-referenced media from saved prompt artifacts, and
explicit artifacts created with
`sase artifact create -p <path> [-l <label>] [-k <kind>]` all participate in the same
list. Explicit artifacts are stored under `~/.sase/artifacts/` with a persistent
association so they remain available after dismissing and later reviving the agent.
sase's TUI shows the picker even for a single artifact. Inside that picker, `m` marks
rows, `Enter` opens the marked set or highlighted row, and `A` opens the full list. Only
one plan artifact is listed for an agent, preferring the committed SDD plan path when
one exists. Inside tmux, artifact viewing opens in a right-side tmux pane, collapses the
Agents list while live, uses `l` to focus the pane, and uses lowercase `a` to close it;
outside tmux, sase's TUI suspends and uses the current pane. The viewer supports images,
videos, Markdown, PDFs, and text fallbacks, wraps `j`/`k` page navigation at the ends,
uses `n`/`p` for artifact-sequence navigation, and warns when required
terminal/rendering tools are missing. The direct agent run-log binding is `V`.

## Related

- [Scheduler](scheduler.md)
- [Scheduler configuration](scheduler-configuration.md)
- [Default scheduler routines](scheduler-default-routines.md)
- [Automation migration notes](../upgrading/automation.md)
