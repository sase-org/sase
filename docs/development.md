# Development

This page orients contributors working in the `sase` repository. It covers local setup,
verification, source layout, and documentation publishing paths.

## Setup

Requirements:

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- [`just`](https://github.com/casey/just)

```bash
uv venv .venv
source .venv/bin/activate
just install
sase --help
```

`just install` installs the package in editable mode with development dependencies. When
a sibling `../sase-core` checkout is present and `cargo` is available, it also builds
and installs the local `sase_core_rs` extension before resolving Python dependencies.

The verification recipes cache their setup-validation verdicts inside the active virtual
environment. The cache is fingerprinted from `pyproject.toml`, `uv.lock`, the validator
implementations, the local `sase-core` version, and the installed environment metadata,
so dependency or environment changes revalidate automatically. Set
`SASE_TEST_SETUP_FORCE_REVALIDATE=1` on any `just` invocation to bypass the cache while
diagnosing setup problems.

## Verification Commands

```bash
just install       # Install with dev deps
just fmt           # Auto-format code and Markdown
just lint          # Run ruff, mypy, pyscripts, symvision, toobig, and keep-sorted
just test          # Fast parallel test run, excluding slow and PNG visual snapshot tests
just test-slow     # Slow pytest subset only
just test-visual   # ACE PNG visual regression snapshots only; the sole visual execution
just test-terminal-smoke  # Optional real-terminal ACE smoke test
just test-cov      # Parallel test run with coverage + 50% gate, excluding visual snapshots
just test-contexts # Record the per-test coverage baseline the selector consumes, and cache it host-locally
just test-contention  # Diagnostic soak: repeat the default lane under pinned-CPU contention and tally per-node failures
just check         # Agent default: whole-repo lint gates + a diff-scoped test lane
just check-full    # Exhaustive verification: whole-repo lint gates + the full test suite
just selection-health  # Health of the diff-scoped test lane, including false negatives
just selection-backtest  # Replay real history and measure selection recall against coverage
just refresh-contexts-baseline  # Cache CI's per-test coverage baseline for selection
just refresh-contract-manifest  # Regenerate tests/contract_manifest.txt from the marker
just test-tox      # Test across Python 3.12, 3.13, 3.14
just clean         # Remove build artifacts
just build         # Build wheel and sdist
```

### Diff-scoped checks (`just check`)

`just check` is the agent default: every whole-repo lint gate runs unchanged, but the
test stage is `just test-scoped` instead of `just test`. `tools/select_tests` builds a
cached import graph from `src/**` and `tests/**`, seeds it with the changed and
untracked files in the current diff against `$SASE_CHECK_BASE` (default
`origin/master`), and walks reverse import edges out to a bounded depth
(`SASE_TEST_SELECTION_DEPTH`, default `2`) to find the test files that plausibly
exercise the change. The selection always includes the curated `contract` set
(`tests/contract_manifest.txt`) and excludes `tests/ace/tui/visual/**` unconditionally.
The scoped run is serial (`-n 1`) unless the middle gear below wins it a small lease,
and it never queues behind other agents' runs either way.

Selection is a **heuristic**, not a guarantee: an unbounded closure would select the
vast majority of the suite because of a large import cycle in `src/sase`, so
depth-bounding is the mechanism, not a tuning knob. A handful of broadening rules
escalate to the full suite when the change touches something the closure cannot safely
reason about (a conftest, `pyproject.toml`, the `Justfile`, config schemas, the
selection engine itself, or a narrow set of environment-identity inputs — see "The
`core-identity-changed` escalation" below). A selection that survives those rules is
then costed rather than counted: it escalates when a serial run of it is estimated to
take longer than `SASE_TEST_SELECTION_MAX_SERIAL_SECONDS` (default: the full lane's
measured wall clock, 232s), and only where no such estimate is available does the
file-count ratio `SASE_TEST_SELECTION_MAX_RATIO` (default `0.25`) decide instead. An
escalated run falls through to the same governed, fully parallel lane as `just test`.

The runtime budget exists because file count is a 6x-spread proxy for runtime: measured
on athena on 2026-08-06, eight of 39 scoped runs took longer than the 232s full lane and
consumed 75% of the lane's total wall clock, and the worst — 494 files, which the ratio
rated as scoped — ran 1,032.6s where `just check-full` would have finished in ~291s.
Past the crossover the fast path is the slow path, so the lane stops taking it. Every
scoped manifest records both halves of the comparison (`max_serial_seconds` and the
`timings` block), and `tools/select_tests --explain` prints them whether or not the rule
fired —
`serial budget: estimated 180s against a 232s budget (within; 96% of the selection covered by the timing table)`.

Run `just check-full` — every lint gate plus the full test suite, `just test` unchanged
— before landing an epic's combined tree, whenever a change touches the broadening set
above, and any time a scoped run escalated or reported a selection that looks wrong. CI
always runs the full suite, so a scoped false negative surfaces there within roughly the
CI test leg's runtime; it is a backstop, not a silent gap.

Use `tools/select_tests --explain` to see which rules fired and why a given file was
pulled into (or excluded from) the current selection. The selection manifest — the
resolved base, changed files, rules fired, and selected test files — is written to
`.pytest_cache/sase-selection/manifest.json` on every scoped run.

#### Per-test-file timings

File count is a poor proxy for how long a selection takes to run: measured on athena on
2026-08-06, a 94-file selection ran 465s serially while a 517-file one ran 404s. So the
lane also measures cost. Every full-lane run and every scoped run loads
`tests/_test_selection_timings_plugin`, which sums each test's setup/call/teardown wall
seconds up to the **test file** and writes them to
`${SASE_HOME:-~/.sase}/test-selection/<project-key>/timings/`. One `just test` covers
every test file in a single pass, so the table bootstraps from a run that already
happens; a scoped run then refreshes the files the lane touches most. The newest eight
recordings are merged newest-wins and the rest pruned.

`tests._test_selection_timings.estimate_serial_seconds()` turns that table into what a
serial run of a given selection would cost. It never guesses silently: files the table
has not seen are extrapolated at the covered files' mean only while at least
`SASE_TEST_SELECTION_TIMINGS_MIN_COVERAGE` (default `0.8`) of the selection is covered,
and below that the answer is an explicit "insufficient data" rather than a number. Every
scoped manifest records the estimate, the coverage fraction, and the identity of the
table it came from, under `timings`.

The estimate is what the `serial-budget-exceeded` rule above decides on. Where it is
unavailable — a fresh host, a mostly-new selection, or
`SASE_TEST_SELECTION_TIMINGS_DISABLED=1` — nothing changes: the file-count ratio
decides, as it did before the table existed. `SASE_TEST_SELECTION_TIMINGS_DIR` relocates
the table.

#### The middle gear

The lane used to have two gears: one worker with no lease, or the whole governed suite.
`serial-budget-exceeded` is the one escalation a third gear can answer — the selection
is sound, it is merely too slow to run serially — so when that rule fires **alone**,
`tools/run_pytest` asks the suite gate for up to
`SASE_TEST_SELECTION_SCOPED_WORKER_CEILING` (default `4`) worker tokens and runs the
selection at whatever width it gets. The 494-file selection that ran 1,032.6s serially
is ~258s at four workers, against 232s for the whole suite.

The request is a **single non-blocking attempt** (`WorkerTokenLease.try_acquire`). If
the tokens are not free right now, the run escalates exactly as it did before — the lane
never queues behind another agent's run, which is the property the whole scoped lane
exists to deliver. The gear also declines a one-token grant (a serial run wearing
xdist's bookkeeping), a run that must stay serial anyway
(`--inline-snapshot=fix/review`), and any run already under a governed parent
(`SASE_TEST_GATE_DISABLED=1`). Setting the ceiling below `2` turns the gear off
entirely.

The width is the gate's decision, not the caller's, so scoped mode still rejects `-n`
and `SASE_PYTEST_WORKERS`. A change-set escalation — a conftest, the `Justfile`,
`core-identity-changed` — is never offered to the gear: those rules fire because the
closure cannot be trusted for that change, and no amount of parallelism answers that.

Every run that reached the gear records a `gear` block on its manifest (granted, width,
ceiling, and the refusal reason when there is one), and it shows up in `just check`'s
scoped summary line as `gear 4 workers` or `gear refused (tokens-unavailable)`. A
granted run is recorded as **not** escalated, because it ran a selection: its real
duration and its width both reach the health store, where `just selection-health` counts
the gear's runs and refusals and reports the width mix behind the duration percentiles.

#### The `core-identity-changed` escalation

`tools/validate_test_environment` already digests the installed environment to
invalidate its own validator-verdict cache — `pyproject.toml`, `uv.lock`, the venv's
`pyvenv.cfg`, the sibling `sase-core/Cargo.toml`, its own four validator scripts, every
installed distribution's `dist-info` metadata, the compiled `sase_core_rs` extension,
and the venv's `bin/python`. The selector reuses those same digests rather than forking
a second, divergent fingerprint, but as a **per-input map**
(`tools/validate_test_environment._fingerprint_inputs`) instead of one opaque combined
hash, so it can say _which_ input moved instead of only that the environment did.

Only some of those inputs are worth forcing the whole suite over.
`core-identity-changed` fires only when a bucket in
`tests._test_selection_manifest.ENVIRONMENT_ESCALATING_INPUTS` differs from the previous
scoped run's manifest: `pyproject`, `uv-lock`, `venv-config`, `core-cargo`, `extension`,
and `python`. Each is either invisible to `git diff` against the merge base (the sibling
repo's `Cargo.toml`, the compiled extension, the interpreter identity) or covers a case
the diff-visible `packaging-config` rule cannot: `pyproject.toml`/`uv.lock` already
broaden the selection via `packaging-config` when they are part of the current diff, but
this fingerprint also catches the same files changing between runs without being part of
it — a `git pull` that lands a dependency bump the working diff never touches. The four
`validator:*` scripts and every installed package's metadata (`environment-metadata`)
are recorded for attribution but do not escalate on their own: they are repository
tooling and environment bookkeeping, not something that changes which tests exercise the
diff. A run where only a non-escalating bucket changed falls back to the normal closure
plus `contract-set-always`, the same as any other unremarkable diff — not to silence,
since the manifest's `baseline.environment_changed_inputs` still lists every bucket that
moved, escalating or not, and `tools/select_tests --explain` prints it as
`environment inputs changed: ...` whenever it is non-empty.

The compiled extension's identity was previously untracked in practice: `sase_core_rs`
installs to the nested `site-packages/sase_core_rs/sase_core_rs.abi3.so`, but the old
glob (`sase_core_rs*.so` applied directly to `site-packages`) does not cross the `/`, so
it matched nothing and the `extension` input was silently empty — a rebuild was caught
only indirectly, through the dist-info `METADATA` version. It now searches
`site-packages` and `site-packages/sase_core_rs`, mirroring
`tools/purge_sase_core_rs_extensions`'s candidate directories, and hashes the file's
content instead of its `stat()`, so a rebuild that reproduces identical bytes is not a
change.

Measured on the epic's research (`2026-08-06`, 63 scoped runs against the real host
store): `core-identity-changed` fired in 16 of them, and was the _sole_ reason for
escalation in 8. The single-digest scheme those runs recorded could not say which input
caused any of them — that attribution is unrecoverable for those historical runs, which
is exactly the gap the per-input map above closes for every run recorded from here on.

#### Coverage-context ground truth

The import graph cannot see dynamic dispatch, plugin lookup, or config discovery.
Per-test coverage can. CI's `coverage-contexts` job runs the fast suite with
`--cov-context=test`, so its `.coverage` database records which test executed each line,
and publishes it as the `sase-coverage-contexts-<sha>` artifact.

That job is deliberately separate from the per-PR coverage leg, and runs on master
pushes only. Measured on athena on 2026-08-06 over the full fast suite at 12 workers:

| Variant                            | Suite runtime | `.coverage` |  gzipped |
| ---------------------------------- | ------------: | ----------: | -------: |
| branch coverage (the PR leg today) |          470s |       17 MB |   7.7 MB |
| branch coverage **+** contexts     |          538s |    _906 MB_ | _283 MB_ |
| contexts, line coverage only       |          474s |       49 MB |  12.1 MB |

Branch coverage stores every arc per context; line coverage stores one bitmap per (file,
context). Selection only ever asks "which tests executed this line", so
`coverage_contexts.toml` turns branch coverage off and the PR leg keeps its branch data
and its 50% gate untouched. Baselines are resolved as ancestors of an agent's `HEAD`, so
a per-PR database would be one nobody ever looks up.

```bash
just test-contexts                      # record a baseline locally (what CI runs) and cache it
just refresh-contexts-baseline          # newest master baseline that is an ancestor of HEAD
just refresh-contexts-baseline --force  # re-download even if already cached
```

There are two supply routes, and neither is a network dependency at selection time. The
artifact is published on master pushes and retained 14 days, so a host that has been
idle longer than that — or is offline, or never fetched — would otherwise run the scoped
lane on the static closure alone. `just test-contexts` closes that hole: on success it
runs `tools/install_coverage_contexts`, which files its own `.coverage` in the cache as
`<HEAD sha>.sqlite`. Because the cache is host-local rather than per-workspace, one
instrumented run in one numbered workspace supplies every workspace on the machine.
Instrumentation stays opt-in — nothing on the `just check` or `just check-full` path
records contexts — and `SASE_TEST_SELECTION_INSTALL_CONTEXTS=0` records without caching.

`cov-contexts` runs pin `COVERAGE_CORE=ctrace`. On Python 3.14 coverage otherwise
defaults to the `sysmon` core, which stops monitoring a code location once it has been
seen — so only the _first_ test to execute a line is credited with it, and per-test
attribution thins out as the suite runs. Measured on athena at `6b0976bcb`: over the
full suite, `tests/test_agent_lanes.py` recorded 6 contexts against `agent_lanes.py`
under `sysmon` and 32 under `ctrace`, which is what CI's Python 3.12 leg (already on
`ctrace`) records. A local baseline has to be the same ground truth, not a thinner one.

The installer refuses three databases that would be worse than no baseline at all, since
a baseline that resolves but contributes little silences `context-baseline-missing`
while adding few tests: one recorded against a `src/` tree with uncommitted changes (its
line numbers are not the commit's line numbers), one recorded over part of the suite,
and one whose attribution density — `(file, test)` pairs per measured file — is under
half that of the densest database already cached. The third guard is the one the other
two cannot see: a `sysmon`-cored run names the whole suite over a clean tree and still
holds an order of magnitude less ground truth. `--allow-dirty`, `--allow-partial`, and
`--allow-thin` override them deliberately; a refusal never fails the recording recipe.

Baselines are cached by SHA under `${SASE_HOME:-~/.sase}/test-selection/contexts/`,
newest five retained however they arrived, each beside a `<sha>.sqlite.breadth.json`
sidecar recording the context, attribution, and file counts its producer measured.
**Selection itself never touches the network**: among the cached ancestors of `HEAD` it
reads the nearest one that is not materially thinner than the broadest available, and an
absent or unreadable one is not an error — the run records `context-baseline-missing`
and proceeds on the static closure alone, so a fresh workspace with no connectivity
still gets a working `just check`.

Breadth is what breaks the tie, not recency. Ranking on file mtime held while every
baseline arrived the same way, as a CI artifact, and stopped holding once a local run
became a second producer: measured on athena at `b08862001`, a local `6b0976bcb`
database (14,349 contexts, 46,364 attribution pairs) outranked CI's `96183d71b` (58,770
and 597,959) purely by being written more recently, over a near-identical file count.
Every selection that resolved it got 13× less attribution while reporting a healthy
`context-selection`. So the cache now ranks ancestors by breadth first and commit
distance second, with anything holding at least 75% of the best candidate's attribution
pairs counted as comparable — a gate wide enough that ordinary run-to-run variation
still lets the _nearer_ baseline win.

Contexts are **unioned into** the selection, never substituted for it. They are ground
truth only for the code that existed when the baseline was recorded; they say nothing
about code added since, and a brand-new test file has no context rows at all. A baseline
more than `SASE_TEST_SELECTION_CONTEXTS_MAX_DISTANCE` commits behind `HEAD` (default
`50`), or one whose commit this workspace does not know, is still used but records
`context-baseline-stale` so `just selection-health`'s rule histogram can show whether
staleness correlates with false negatives. Set `SASE_TEST_SELECTION_CONTEXTS_DISABLED=1`
to ignore the cache entirely, and `SASE_TEST_SELECTION_CONTEXTS_DIR` to point it
elsewhere. The manifest's `contexts` block records the baseline SHA, its distance behind
`HEAD`, whether it was stale, which changed files it matched, and how many test files it
contributed.

Contexts are consulted only on the path that actually produces a narrowed selection. A
run a broadening rule forces to the full suite short-circuits before the cache is read,
so its `contexts` block records `"consulted": false` rather than a baseline of `null` —
an escalated run executed every test and was never exposed to a narrow selection, and
counting it as one that ran on the static closure alone is what used to inflate the
exposure reading below.

Line numbers are read on the **baseline side** of `git diff -U0 <baseline-sha>`,
restricted to the change set's own files, because the database is keyed by line numbers
as they were in the baseline.

##### When there is no usable baseline

A run that finds no usable baseline narrows on the static closure alone, which the
backtest below measures as a real blind spot — so it cannot simply carry on as if the
closure were sound. How often that happens is worth stating carefully, because the first
reading of it was wrong: `just selection-health` used to count every escalated run as
one without a baseline, which made absence look like half the lane. Escalated runs never
consult the cache and run every test anyway. Over the same store measured by consulted
runs only, a baseline was present in **21 of 23**; the 21 remaining scoped runs
escalated before contexts could matter.

So absence is uncommon on a host that fetches or records baselines — but it is not rare
where it counts. It is the standing condition of a workspace that has been idle past the
CI artifact's 14-day retention, one that is offline, or a host that has never fetched,
and there absence is persistent rather than occasional. Escalating on it would be sound
and is now known to be affordable at this frequency; the closure **walks one hop
deeper** instead because a measured 91% of the blind spot comes back for roughly double
the selected files, against 3,650 worker-seconds for a full run. That records
`no-baseline-depth-boost`, which appears in the manifest, in `just check`'s scoped
summary line, and in `just selection-health`'s rule histogram. The manifest's
`effective_depth` is the depth actually walked, configured depth plus whatever the
rename/delete and no-baseline compensations bought; `depth` stays the configured one.

Measured with
`just selection-backtest --limit 150 --include-descendant-baseline --baseline 96183d71b`
at `4651ed199` over 63 commits with usable ground truth (3 faithful baseline-ancestor
replays, 60 approximate baseline-descendant ones), closure-only:

| depth              | mean recall | p10 recall | worst recall | blind-spot commits | missed test files | median selection |
| ------------------ | ----------: | ---------: | -----------: | -----------------: | ----------------: | ---------------: |
| 2 (before)         |       96.0% |      85.3% |        23.5% |            13 / 63 |               116 |             6.4% |
| 3 (with the boost) |       99.2% |     100.0% |        81.3% |             5 / 63 |                11 |             8.8% |

The extra hop costs roughly double the selected files (`src/sase/agent_lanes.py`: 110 →
255 of 2,329, 1,117 → 2,514 tests, 57s → 164s serial on athena) and raises the replayed
escalation rate from 23/63 to 28/63 — historical whole-commit diffs, well above what a
working-tree change selects. It buys back 91% of the measured blind spot. On the
sharpest known shape, `src/sase/ace/tui/_app_layout.py` — widely executed but shallowly
imported — it lifts recall from 24.2% to 53.8% (69 missed of 91 down to 42) at 14.2% of
the suite, still under the escalation ratio. Directory-mirror expansion was measured as
the alternative for that shape and rejected: `tests/ace/tui/**` is 831 files, 35.7% of
the suite, so mirroring escalates to the full suite rather than staying scoped.

#### The contract set

Some tests audit the repository as a whole rather than one module: config-schema
conformance, generated-file drift, terminology guards, tool-script contracts. No import
edge connects them to the code they police, so the closure would never select them. They
are marked `@pytest.mark.contract` and added to **every** scoped selection
unconditionally.

`tests/contract_manifest.txt` is a generated projection of that marker, not a
hand-maintained list — the selector reads the committed file so it does not have to
collect the suite first. To add or remove a test file from the set, change the marker on
the test module and regenerate:

```bash
just refresh-contract-manifest   # rewrite tests/contract_manifest.txt from -m contract
```

`tests/test_contract_manifest.py` fails when the committed manifest disagrees with the
marker, so a forgotten refresh surfaces as a test failure rather than a silently stale
selection. The same module carries a **budget guard** bounding the size of the set:
every agent pays for it on every `just check`, so growth has to be deliberate. The guard
asserts a manifest-entry cap calibrated from the current measured serial cost instead of
timing a nested contract run; timing proved too load-sensitive to use as a correctness
oracle under real xdist contention.

Both guards live outside the contract set on purpose — regenerating and re-budgeting the
whole set from inside that same set would charge every `just check` for it twice — so
they run only in the exhaustive lane (`just test`, `just check-full`, CI). Marking a
test and forgetting the refresh therefore survives a `just check`: run `just check-full`
after changing a `contract` marker.

Once you do regenerate, the manifest change broadens the next selection by itself.
`tests/contract_manifest.txt` belongs to the `selection-tooling` broadening rule, so the
`just check` that lands a new contract test escalates to the full suite — that
escalation is the manifest edit, not the new test.

The contract set is also the floor. A change set that contributes no import-graph seeds
at all — a docs-only edit, an `sdd/**` change, a `.github/**` workflow tweak — records
the `contract-set-only` rule and runs exactly the contract tests. That rule does **not**
escalate: running the whole suite for a Markdown edit would be the heuristic failing in
the expensive direction.

**Expect selections to grow.** Over the 2026-08-06 baseline, 1,237 of the ~2,400
measured `src/` files have at least one line whose per-test contexts (40 tests or fewer)
include a test the depth-2 closure never selects. The sharpest case is
`src/sase/ace/tui/widgets/_file_completion_refresh.py`, where the closure selects
**zero** test files and contexts select 40 — a change there would previously have been
checked by nothing but the contract set. In the other direction, a line in a
widely-executed module really is executed by thousands of tests, and contexts say so,
which will push some selections over the escalation ratio and into the governed full
lane. Both directions are the heuristic being corrected rather than a malfunction; watch
`just selection-health` for what it does to the escalation rate and the false-negative
count.

SASE places a pytest safety boundary around its telemetry mutations and common axe
state/log writers when they target the OS account's real `~/.sase` tree. Telemetry
flushes and deletions fail with an actionable error; guarded best-effort daemon writes
are suppressed and warn once per target and category; and axe start, stop, and restart
requests are refused unless their test-only override is set. The pytest harness also
publishes `SASE_PYTEST_SANDBOX_DIR`; while that marker is present, bead-store writes
through the Python mutation facade or Rust CLI fast path are refused unless the target
store is at or below the sandbox root. `SASE_ALLOW_UNSANDBOXED_BEAD_WRITES=1` is the
deliberate test-only escape hatch for a genuine exception. SASE preserves pytest's
isolation marker when it starts runner and daemon subprocesses. These guards are not a
substitute for isolation: tests that exercise persistence should point `SASE_HOME` at a
per-test temporary directory and create bead stores under `tmp_path` or another path
inside the published sandbox. Run `just test-bead-store-soak` when changing bead
resolution or mutation paths; it runs the default suite and verifies the legacy
production plans sidecar's `beads/issues.jsonl` digest, bead-state git status, and git
HEAD are unchanged. The current guard still targets `SASE_SDD_PLANS_DIR/beads` and never
resolves the dedicated beads role. On a cleaned schema-3 project it exits with a
missing-file error instead of running the suite; if a legacy `beads/` copy remains under
`--plans`, the helper guards that stale copy rather than the active `--beads` store. If
an older test run already polluted the telemetry store, preview the exact-label cleanup
with `sase telemetry cleanup-test-data --dry-run` before deciding whether to rerun it
with `--yes`.

`just test`, `just test-slow`, `just test-visual`, and `just test-cov` share a
host-global pytest-xdist worker-token pool with every other checkout owned by the same
UID. An automatic run waits until it can lease a small floor, then greedily grows to its
per-run ceiling using whatever capacity is currently free. On the standard development
host, a solo run can receive 28 workers from the 32-token pool while leaving four tokens
for another run; concurrent runs scale down to their actual grants instead of each
independently oversubscribing the host. The granted count is the value passed to
`pytest -n`.

The default host budget reserves `max(1, cpu_count // 8)` CPUs and 8 GiB of available
memory, allows 950 MiB per worker, and never exceeds 32 tokens (the prior safe aggregate
ceiling). The CPU reserve is proportional rather than a flat count, so a small host
(e.g. a 4-vCPU CI runner) still gets real parallelism instead of collapsing to a single
worker. The memory allowance was calibrated from live worker RSS sampled across
concurrent sibling workspaces, which ranges from 0.74 to 0.85 GiB; 950 MiB keeps
headroom over the top of that range. Missing memory information falls back to a
conservative four-token limit, and small hosts clamp to at least one token. These
capacity safeguards are independent of xdist scheduling and individual test cost.

The runner defaults to pytest-xdist's `worksteal` scheduler. Workers begin with evenly
divided queues and can reclaim pending tests from a worker with a long queue, avoiding
the idle-worker tail caused by keeping an entire heavy test file on one worker. The
fallback is a one-variable change:

```bash
SASE_PYTEST_DIST=loadfile just test
```

`SASE_PYTEST_DIST` accepts only `worksteal` and `loadfile`; unsupported values fail with
a pytest usage error before the runner leases worker tokens. Inline-snapshot update and
review modes remain serial and omit both `-n` and `--dist` regardless of this setting.
Test selectors and other pytest options continue to pass through normally.

A post-change comparison on 2026-07-20 used the same 19,883-item fast-suite selection,
refreshed dependencies, and an exact governed grant of 28 workers. Aggregate CPU is
reported as the mean utilized cores divided by the 28-worker grant; the tail is wall
time from the first 99% progress report through completion.

| Scheduler   | Pytest time | Wall time | Grant utilization | 99%-finish tail |
| ----------- | ----------- | --------- | ----------------- | --------------- |
| `loadfile`  | 109.68s     | 111.93s   | 59.1%             | 41s             |
| `worksteal` | 102.34s     | 104.66s   | 61.8%             | 39s             |

`worksteal` reduced wall time by 7.27s (6.5%) while running the same assertions. The
slowest calls remained the two tests in `test_agents_zoom_panel_search.py` (roughly
16-20s each), so the improvement reflects better pending-work distribution rather than
removed test cost. Three complete `worksteal` runs at governed grants of 11, 16, and 28
workers passed while auditing for within-file order and shared-state assumptions.

### Final combined-suite verification

The completed optimization was measured on athena on 2026-07-20 with the current
19,921-item fast-suite selection. A crash-safe reservation held the measured 29-token
host pool across three consecutive samples so unrelated queued suites could not enter
between runs; each `just test` used 25 workers, the automatic ceiling for that capacity
after reserving the four-worker floor. Aggregate CPU is GNU time's mean utilized cores,
and grant utilization divides it by 25.

| Sample | Pytest time | Recipe wall | Workers | Aggregate CPU | Grant utilization |
| ------ | ----------- | ----------- | ------- | ------------- | ----------------- |
| 1      | 90.71s      | 93.14s      | 25      | 1809%         | 72.4%             |
| 2      | 90.84s      | 93.08s      | 25      | 1776%         | 71.0%             |
| 3      | 89.63s      | 92.05s      | 25      | 1803%         | 72.1%             |
| Mean   | 90.39s      | 92.76s      | 25      | 1796%         | 71.8%             |

Against the pre-optimization 4:04 recipe / 194s pytest / 14-worker / ~780% CPU baseline,
the mean recipe is **2.63x faster** and the pytest segment is **2.15x faster**.
Non-pytest recipe overhead fell from roughly 50s to 2.37s. The selection grew from
19,744 to 19,921 items while the work landed; no existing test was removed, skipped, or
moved out of the fast lane.

Coverage parity used the same 19,921-item selection with `just test-cov`: 19,915 tests
passed, 7 were skipped, total branch coverage was 80.07%, and the unchanged 50% gate
passed. `just test-cov` shares `just test`'s marker selection, which at the time of this
measurement still included the ACE PNG visual regression tests. Both recipes exclude
those tests today; see [Visual Snapshot Workflow](#visual-snapshot-workflow).

Sustained real-host demand also exercised the pool while these measurements were
prepared. With memory sizing the active budget at 20 tokens, three full suites
progressed simultaneously with grants of 12, 4, and 4 workers. Their sum never exceeded
20; available memory stayed healthy and swap remained at 2.3 GiB throughout the
observation. The process-level regression in `tests/test_suite_gate_integration.py`
makes the same guarantees deterministic in a temporary three-token pool: three
one-worker suites reach test execution together, a fourth waits, killing one holder
admits the waiter, and active grants remain exactly bounded before and after the
handoff.

Set `SASE_PYTEST_WORKERS=<N>` to request exactly that many governed workers; the request
must fit the shared capacity. Direct parallel `pytest -n ...` controllers use the same
pool and lease their resolved numeric, `auto`, or `logical` worker count exactly. Lock
descriptors survive the runner's exec and are released by the kernel even after
`SIGKILL`. Nested pytest processes inherit the disabled marker so they cannot deadlock
on the parent's tokens.

For deliberate diagnostics, `SASE_TEST_GATE_DISABLED=1` bypasses accounting: the run
takes no tokens and never queues. It is still clamped to the host budget and prints one
line saying so, because the pool cannot see it and every other run's budget assumes it
is absent — an unaccounted 64-worker controller against a 32-token pool once drove this
host to a load average of 97.6 with 25 GiB in swap. A benchmark that genuinely needs to
run wider raises `SASE_TEST_GATE_SLOTS` instead, which enlarges the pool where
concurrent runs can see it. A run whose exemption is corroborated by a real ancestor
lease (`SASE_TEST_GATE_GOVERNED=1`, or an xdist worker) is unaffected: its width was
already paid for, so it is granted untouched.

`SASE_TEST_GATE_SLOTS` overrides host-wide token capacity, `SASE_TEST_GATE_TIMEOUT`
controls bounded admission waits, and `SASE_TEST_GATE_DIR` selects the shared pool
directory. `SASE_PYTEST_WORKER_FLOOR` and `SASE_PYTEST_WORKER_CEILING` tune automatic
grants; invalid or inconsistent values fail before pytest starts. See
[Configuration](configuration.md#general) for the complete contract.

Test selectors are normalized from the directory where `just` was invoked, so this works
the same from the repository root or a subdirectory:

```bash
just test tests/main/test_parser.py::test_example
```

`just lint` and `just fix-keep-sorted` bootstrap a project-local `keep-sorted`
executable into `.venv/bin/` from `PATH`, or by running
`go install github.com/google/keep-sorted@v0.8.0` when Go is available. If neither
`keep-sorted` nor Go is installed, those recipes fail with a setup error before linting
YAML keep-sorted blocks.

Default test runs select `not slow and not visual`, so the ACE PNG snapshot regression
tests do not run in `just test`, `just test-cov`, or `just test-scoped`.
`just test-visual` is the only recipe that executes them; it installs the optional PNG
rasterizer dependencies when they are missing. The real-PTY smoke tests carry both
`terminal_smoke` and `slow`, so that same expression excludes them too —
`terminal_smoke` selects them, it does not deselect them. Direct `pytest` runs inherit
the identical default expression from `pyproject.toml` unless you pass your own `-m`
selector.

Use `just test-terminal-smoke` only when you need to verify the ACE startup path through
a real PTY. It installs `pexpect` and `pyte`, runs the optional `terminal_smoke` marker,
and stays out of default tests and CI until that path has proved stable. The recipe uses
the shared pytest runner's private disk-backed temp root and leak guard, but it is
always serial and never leases xdist worker tokens; `SASE_PYTEST_DIST` is therefore
ignored. Set `SASE_PYTEST_TMPDIR` to override its scratch root while diagnosing
temp-path behavior.

### Reproducing Timing Flakes (`just test-contention`)

The default lane's timing flakes are a class, not a list of nodes: individually rare,
collectively frequent, and historically only reproducible under accidental host load.
`just test-contention` makes them reproducible on demand, the same way
`just test-visual-contention` already does for PNG convergence: `taskset` pins a
26-worker pool to two CPUs (13x oversubscription), the selection runs N times, and the
run ends with a per-node tally naming each failing node, how many repeats it failed in,
and which ones.

```bash
just test-contention -- tests/ace/tui/util/test_stall_watchdog.py   # restrict the soak
SASE_CONTENTION_REPEAT=6 just test-contention -- tests/test_bead    # soak harder
```

Override the pinned CPU list, the worker count, and the repeat count with
`SASE_CONTENTION_CPUS`, `SASE_CONTENTION_WORKERS`, and `SASE_CONTENTION_REPEAT`
(defaults `0,1`, `26`, and `3`). A full-suite repeat is far too slow to iterate against,
so pass paths or node IDs; the tally is what turns "it went green once" into a
before/after measurement a fix can be falsified by.

Per-repeat failure records land in `.pytest_cache/sase-contention/repeat-NN.json`, so a
finished soak can be re-read without re-running it.

This lane is an opt-in diagnostic and is deliberately kept out of every governed path:
it takes no suite-gate lease, writes nothing to the durable selection-health store, and
is unreachable from `just check` and `just check-full`. A deliberately starved run is
not evidence about what a scoped run should have selected. It also starves the host on
purpose, so other agents' runs on the same machine slow down while it runs.

### Selection Health

`just test-scoped` selects tests from the change set with a depth-bounded reverse walk
of the import graph. That selection is a heuristic, so its cost and its mistakes are
both measured rather than assumed.

Every scoped run copies its selection manifest, and every full-lane run (`just test`,
`just test-cov`) copies the node IDs it saw fail, into a durable host-local store at
`${SASE_HOME:-~/.sase}/test-selection/<project-key>/`. The store is shared by every
numbered workspace of the project, so the report reads one project-wide sample rather
than one workspace's, and records older than 30 days are pruned on write. Sharing the
store is not the same as correlating across it: records carry the workspace and change
set that the false-negative rule below needs precisely so that one workspace's flake is
never charged to another workspace's selection.

```bash
just selection-health          # readable report
just selection-health --json   # the same numbers, machine-readable
```

The report covers how many scoped runs ran, how often they escalated to the governed
full lane, median and p90 selection size, scoped duration percentiles with the middle
gear's width mix behind them, worker-seconds of host demand avoided (charged at the
leased width, so a 100s run at four workers costs 400), which broadening rules fired,
and — the number that decides whether the fast lane is trustworthy — the **false
negatives**: tests that failed in a full run after a scoped run over _the same change_
excluded them. The target is zero of a sample that already excludes known flakes (see
below). A non-zero count means the heuristic itself is unsound as tuned; the response is
to raise `SASE_TEST_SELECTION_DEPTH` to 3, or mark the missed tests
`@pytest.mark.contract` and run `just refresh-contract-manifest`, and then re-measure —
not to explain the failures away.

The report also names the lane's own worst behaviour instead of letting the median hide
it: alongside p75/p90/max scoped duration it prints "scoped runs slower than the full
lane (`FULL_LANE_WALL_SECONDS`)", with each offending run's selected-file count and the
rules that produced it, so a latency regression like the one `budget` was built to fix
is visible in the project's own health metric rather than only in one-off timed
measurements. Escalated runs are called out separately as "cost not measured" rather
than folded into the percentiles at their recorded `duration: 0.0` — that zero is a
placeholder for a run handed off before the runner could time it, not a real duration,
and counting it as fast would silently hide exactly the regression this counter exists
to show.

"The same change" is what makes that number mean anything, and the report states the
rule on every run: a scoped run is charged with a full-run failure only when both
records name the same workspace, the scoped run's HEAD is an ancestor of the full run's,
and the full run's change set covers the scoped run's. Ancestry alone is not enough —
sibling workspaces normally sit on the same master HEAD, so `is_ancestor(head, head)` is
trivially true and every workspace's flakes would be charged to every other workspace's
selection.

Read the count together with the two lines under it. Records written before health
schema 2 carry no workspace or change set, cannot satisfy the rule, and are excluded
from correlation; the report says how many there are, so a zero is read as
zero-of-a-known-sample rather than mistaken for a clean one.

A failure that clears all of the above can still be a **known flake**:
`reproducible_flake_nodeids` (`tests/_test_selection_health.py`) looks at every full run
that saw the same node fail, and calls it reproducible when those runs' change sets
share no file — no single diff can explain a failure that recurs across
otherwise-unrelated work. Matches on a reproducible node are moved out of the
false-negative count and into a separate `flake-suppressed` line, counted and listed
exactly like the false negatives are, never silently dropped. A single occurrence is
never enough evidence on its own and stays a false negative until it recurs. This needs
no hand-maintained list of node IDs — the real store already showed failures reproducing
on nodes no bead had enumerated yet, including one caused by a stale `sase_core_rs`
build rather than test-isolation timing, so a fixed list would already have missed it.
(A missed test still charged by exactly one scoped selection's change set, rather than
reproducing across full runs, gets the older, softer hint instead — "matched across
unrelated changes; suspect a flake before a miss" — since that alone is not enough
evidence to suppress.)

The `coverage contexts` block reports baseline availability over the runs that
**consulted** the cache, not over every scoped run, and states separately how many
escalated before contexts could matter. Those two denominators differ by roughly the
escalation rate — on a store where half the runs escalate, counting them as
baseline-less made a lane with two genuinely closure-only runs read as twenty-three of
them.

Use `tools/select_tests --explain` to see why an individual test was or was not
selected. Set `SASE_TEST_SELECTION_HEALTH_DISABLED=1` to skip recording entirely, and
`SASE_TEST_SELECTION_HEALTH_DIR` to point the store somewhere else.

### Selection Backtest

`just selection-health`'s false-negative count can only grow when a full run happens
**in the same workspace** as an earlier scoped run over a subset change. In ephemeral
workspaces that combination essentially only occurs at landing, so the correlatable
sample grows about as fast as epics land. `just selection-backtest` answers the same
question from history instead, today.

```bash
just selection-backtest                                  # replay the last 50 commits
just selection-backtest --limit 150                       # a longer window
just selection-backtest --json                            # the same numbers, machine-readable
just selection-backtest --execute --execute-limit 1       # actually run the missed tests
```

For each replayed commit the harness checks the commit out into **its own throwaway
detached worktree** (never the invoking checkout), takes the commit's own diff against
its parent as the change set, rebuilds the import graph as of that commit, and computes
the selection the scoped lane would have produced. Ground truth for the same change set
comes from the cached coverage baseline: the test files coverage recorded as executing
the lines that commit touched. Recall is the share of that ground truth the selection
contained.

Recall is reported **twice**. `closure-only` runs with the contexts cache forced absent
and is what a workspace with no cached baseline actually gets. `closure+contexts` is
`1.0` by construction — the selector unions in the very same coverage query the ground
truth comes from — so it is not independent corroboration. The **gap between the two
arms is the exposure**, and it is the number a compensating action for a missing
baseline has to be tuned against.

Three limits bound what a reading proves, and the report states each of them rather than
burying them:

- **Ground truth needs a usable baseline.** By default only commits the baseline is an
  ancestor of are replayed. Since baselines arrive as a CI artifact on master pushes,
  that is a small window. `--include-descendant-baseline` also replays commits the
  baseline sits _ahead_ of; ground truth for those is widened by every later change to
  the same file, so recall reads pessimistically, and the report counts the two
  directions separately.
- **The replay is conservative.** `core-identity-changed` cannot fire historically — the
  venv a commit was tested against is gone — so runs that escalated in reality may
  replay as narrow selections. The harness under-reports recall.
- **Recall is a proxy.** A missed test file is a true false negative only if it would
  have failed. `--execute` checks that for the worst few blind spots by running the
  missed files at their commit. It is opt-in, slow, and deliberately absent from
  `just check` and `just check-full` (`tests/test_justfile_lint.py` pins that).

Measured on 2026-08-06 at `6b0976bcb`, over `--limit 150 --include-descendant-baseline`
against the `96183d71b` baseline — 65 commits with usable ground truth (1 faithful, 64
reverse-direction), 85 skipped and itemised:

| arm                | median recall | mean  | p10   | worst | commits with a blind spot | missed test files |
| ------------------ | ------------- | ----- | ----- | ----- | ------------------------- | ----------------- |
| `closure-only`     | 100.0%        | 96.2% | 86.7% | 23.5% | 13 / 65                   | 118               |
| `closure+contexts` | 100.0%        | 100%  | 100%  | 100%  | 0 / 65                    | 0                 |

25 of the 65 reached perfect recall by escalating rather than by selecting well. The
worst case — `6719992521ad`, `feat(sidecars): surface publication queue observability` —
recalled 23.5%, missing 75 of 98 covering test files. Median selection size was 6.4% of
the suite (p90 11.9%), so the closure-only arm is not paying for its misses with
breadth.

Note what the skip counts say about the sample: of the 150 commits examined, 46 changed
no `src/**.py` at all and 36 touched no file with a baseline-side line to query. A
recall figure here is a figure over commits that change already-covered production code,
not over all commits.

## Visual Snapshot Workflow

ACE visual tests live under `tests/ace/tui/visual/` and compare deterministic Textual
screenshots against committed PNG goldens. The renderer stack is exact-pinned in the
`visual` optional-dependency group in `pyproject.toml`, and
`tests/ace/tui/visual/renderer_env.json` records those package versions plus hashes of
the bundled fonts. A session-scoped fixture checks that fingerprint before any snapshot
runs, so a skewed environment fails once with an installation or upgrade instruction
instead of producing a wall of misleading pixel diffs.

The visual fixtures also pin the process environment that affects rendering:
`TERM=xterm-256color` and `COLORTERM=truecolor` select Rich's truecolor path,
`FORCE_COLOR` and `NO_COLOR` are removed, and `TZ=UTC` is applied with the process
timezone cache refreshed. Neither a contributor's terminal settings, local timezone, nor
CI's process environment participates in the golden corpus.

Run the focused suite normally first:

```bash
just test-visual
```

When a visual test fails, inspect the artifacts under
`.pytest_cache/sase-visual/<node>/<snapshot>/`. Each failure directory contains the
actual PNG capture and, when a golden exists, the expected PNG plus a diff PNG, a
human-readable `summary.txt`, and a structured `failure.json` sidecar. The sidecar
carries the test source location, repo-relative golden path, and pixel-diff stats so
tooling can map a failure back to the test and the committed golden.

To accept an intentional change to the full golden corpus on Linux, use the guarded
regeneration recipe:

```bash
just update-visual-snapshots
```

For a targeted UI change, the underlying pytest option still accepts a selector:

```bash
just test-visual -- --sase-update-visual-snapshots tests/ace/tui/visual/test_ace_png_snapshots.py
```

Both forms refuse to write if the renderer fingerprint is skewed or the host is not
Linux. Review changed PNG files as normal test data. Do not pass
`--sase-update-visual-snapshots` to `just check`, `just fmt`, or broad CI-style
commands.

Committed goldens are canonical to the pinned renderer. Rasterization goes through resvg
(`resvg_py==0.3.3`), a pure-Rust SVG renderer that carries its own font database
restricted to the bundled fonts in `tests/ace/tui/visual/fonts/` with
`skip_system_fonts=True`. No host font-config or graphics stack participates, so
rendering is stable and host-font-independent on the canonical Linux x86_64 platform.
Fira Code is named for every generic family, so it wins every glyph it carries; DejaVu
Sans is bundled purely as the fallback resvg reaches for on a codepoint Fira Code lacks.
Without it, symbol marks such as the notification tab icons would rasterize as
missing-glyph boxes in every golden while rendering correctly in a real terminal, and no
reviewer could tell the two apart by eye. `tests/ace/tui/visual/test_tab_icon_glyphs.py`
makes that check mechanical: it fails if the bundled fonts stop covering an icon ACE can
pick without configuration. PNG comparison is byte-exact by default locally and in every
visual-bearing CI lane; together with the fixture-level terminal and timezone pins, a
mismatch is a real rendering change or an unpinned environment defect to investigate.

Rasterization can still differ by a small, bounded amount on macOS arm64. The tolerance
environment variables remain available only as explicit escape hatches for local
iteration and renderer investigations. For the known macOS drift, use:

```bash
SASE_VISUAL_PNG_MAX_DIFF_RATIO=0.01 \
SASE_VISUAL_PNG_MATERIAL_DIFF_THRESHOLD=8 \
SASE_VISUAL_PNG_MAX_MATERIAL_DIFF_PIXELS=0 \
just test-visual
```

The ratio caps the changed image area. The material threshold measures the maximum
visible channel distance after alpha-aware compositing over black and white, and the
material-pixel cap still rejects any change above that threshold. These overrides never
update or implicitly accept a golden, and they do not bypass the Linux-only regeneration
gate. Per-assertion equivalents are `max_diff_pixels`, `max_diff_ratio`,
`max_material_diff_pixels`, and `material_diff_threshold`.

## Timestamp Display Convention

User-facing timestamp display must go through `sase.core.time.parse_local` or
`sase.core.time.format_local`, so stored UTC instants, offset-aware values, naive
configured-timezone wall times, and epoch values all render in the configured
`timezone`. Naive-model arithmetic keeps using `local_now` and `to_local`; storage and
wire contracts keep canonical UTC unless their owning schema says otherwise.

`tests/test_timezone_display_consistency.py` has the focused `tz_divergence` fixture
coverage and the `test_no_system_clock_display_sites` AST guard. A new bare
`datetime.now()`, argument-less `.astimezone()`, or tz-less `datetime.fromtimestamp()`
under `src/sase/` should normally be fixed by routing through the time helpers instead
of adding another guard allowlist entry.

Mismatch assertions, `summary.txt`, and `failure.json` report `material_diff_pixels`,
`material_diff_ratio`, and `material_diff_threshold` alongside the active area and
material limits. Inspect those fields to distinguish broad, low-amplitude renderer drift
from a small material UI change before using any override.

One accepted fidelity caveat: Fira Code ships no italic face and resvg does not
synthesize oblique, so `font-style: italic` renders upright. This is uniform across
every screen and host. Restoring visible italics would mean switching the bundled font
family, taken as a separate follow-up if it becomes necessary.

A second one no longer applies: emoji-presentation codepoints were uncovered because a
deterministic rasterizer cannot use a color-emoji font, but the monochrome Noto Emoji
static outline face (bundled as `NotoEmoji-Regular.ttf`) rasterizes them the same way
the other bundled fonts do. `tests/ace/tui/visual/test_emoji_glyphs.py` audits every
emoji codepoint `src/sase` actually uses the same way `test_tab_icon_glyphs.py` audits
tab icons.

### Intentional Renderer Upgrades

The pinned versions and font bytes define the golden corpus. Upgrade Textual, Rich,
resvg, a syntax grammar, Pillow, or another package in that stack as one reviewed
change:

1. Update the exact pins in the `visual` optional-dependency group in `pyproject.toml`.
2. Run `uv lock`, then `just install-visual` so the working environment matches the new
   pins.
3. Refresh the matching package versions in `tests/ace/tui/visual/renderer_env.json`. If
   bundled fonts changed, update their SHA-256 hashes too; the Python and platform
   fields are diagnostic only.
4. On Linux, run `just update-visual-snapshots`, then run `just test-visual` once more
   without update mode.
5. Review the complete PNG diff for unexpected content or layout changes and commit the
   pins, `uv.lock`, fingerprint, and regenerated goldens together.

Non-Linux contributors should use CI as the canonical renderer. Push the branch, let the
Linux `visual-test` job produce `ace-visual-artifacts`, and download that artifact from
the Actions run. Each failure directory contains an `actual.png` and a `failure.json`;
the sidecar's `expected_repo_path` identifies the golden that the actual image should
replace after review. The same fingerprint checks still require pins, lockfile, and
manifest to agree before CI will render the replacement corpus.

### CI Visual Lanes

The default lane (`just test`, `just test-cov`, and every leg of the Python matrix)
excludes visual tests. The dedicated Linux Python 3.12 `visual-test` job is the sole
visual execution: it runs the complete visual suite and uploads failure reports and raw
artifacts. This keeps one broad lane plus one diagnostic lane authoritative for
snapshots while preventing a future Python-specific rendering change from reddening the
whole matrix.

### Visual Failure Report

`tools/render_visual_snapshot_failure_report` consumes the `failure.json` sidecars and
writes `.pytest_cache/sase-visual-report/`:

- `visual-failure-report.html` - self-contained HTML with PNG/SVG embedded as data URIs,
  one anchored section per failure.
- `summary.md` - compact table for `$GITHUB_STEP_SUMMARY` with links into the report and
  to the committed golden.
- `annotations.sh` - escaped `::error file=...,line=...` workflow commands.
- `manifest.jsonl` - aggregate of every loaded `failure.json` for ad-hoc inspection.

Run it locally against a failed run with
`tools/render_visual_snapshot_failure_report --repo <owner/repo> --sha <commit>` and
open the HTML file directly. The script is safe to run when there are no failures; it
exits 0 without writing artifacts.

In GitHub Actions the `visual-test` job invokes the renderer twice on failure: once to
build the report before upload, then again after upload with
`--report-url "$VISUAL_REPORT_URL"` so the summary and annotations point at the freshly
uploaded artifact. The HTML is uploaded via `actions/upload-artifact@v7` with
`archive: false`, which is what makes the per-failure anchors browsable directly from
the Actions UI. Expected links point at the immutable
`https://github.com/<repo>/blob/<sha>/<expected_repo_path>` URL; actual/diff links point
at the report artifact rather than a public PNG URL because the raw PNGs are only
uploaded as a zipped `ace-visual-artifacts` bundle and have no stable per-file URL.

Add a visual test when the risk is layout, styling, focus highlighting, modal
composition, or a regression that is hard to express as state. Prefer a plain
state/widget test when the behavior can be asserted through model state, rendered text,
selection identity, key handling, or a small widget contract.

## Required Rust Core

Ported `sase.core` operations are served by the required Rust extension `sase_core_rs`,
distributed as the `sase-core-rs` package and built from the sibling `../sase-core` repo
during source development. Normal installs pull a prebuilt wheel; local source installs
can build the extension with `just install` or `just rust-install`.

There is no pure-Python fallback for ported operations. Use the health check after
install changes:

```bash
sase core health
```

See the [Rust backend reference](rust_backend.md) for the Python/Rust boundary, shipped
Rust-backed operations, source build path, and benchmark expectations.

## Source Map

The repository is organized around the CLI entry point, operational subsystems, provider
boundaries, and docs/tests:

| Path                           | Purpose                                                                                                |
| ------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `src/sase/main/`               | CLI parser registration and subcommand handlers.                                                       |
| `src/sase/ace/`                | ACE TUI, ChangeSpec rendering, query integration, actions, widgets, and TUI state.                     |
| `src/sase/agent/`              | Agent launch, detached spawn, prompt fan-out, running-agent metadata, artifact lookup, and naming.     |
| `src/sase/axe/`                | Axe orchestrator, lumberjacks, chop execution, scheduled jobs, maintenance mode, and automation state. |
| `src/sase/xprompt/`            | XPrompt expansion, directives, workflow loading, execution, tracing, explaining, and graphing.         |
| `src/sase/xprompts/`           | Bundled xprompt templates, workflows, and schemas shipped with the package.                            |
| `src/sase/xprompts/skills/`    | Bundled agent skill sources and the generated `SKILL.md` frame.                                        |
| `src/sase/skills/`             | `sase skill` CLI helpers, inventory, and use-log implementation.                                       |
| `src/sase/workflows/`          | Change lifecycle workflows for commit, mentor, CRS, accept, and rewind operations.                     |
| `src/sase/memory/`             | Memory inventory, audited read logs, and proposal write/review flows.                                  |
| `src/sase/core/`               | Python facade and stable wire records for operations served by `sase_core_rs`.                         |
| `src/sase/bead/`               | Python host layer for bead storage discovery, CLI integration, and epic launch flow.                   |
| `src/sase/sdd/`                | Spec-driven development file and bead integration helpers.                                             |
| `src/sase/llm_provider/`       | Built-in LLM providers and provider registry.                                                          |
| `src/sase/vcs_provider/`       | VCS provider hook specs, plugin registry, and built-in git provider.                                   |
| `src/sase/workspace_provider/` | Workspace provider hook specs, plugin registry, and bare-git workspace support.                        |
| `src/sase/running_field/`      | Workspace claim and slot-management helpers.                                                           |
| `src/sase/notifications/`      | Notification delivery and storage integration.                                                         |
| `src/sase/telemetry/`          | Local debugging metric accumulation, store queries, health checks, and shared numeric render helpers.  |
| `src/sase/version/`            | Runtime inventory collection and rendering for the `sase version` CLI command.                         |
| `src/sase/integrations/`       | Public helper APIs consumed by external plugins and editors.                                           |
| `src/sase/scripts/`            | Packaged utility scripts used by axe chops and support commands.                                       |
| `tests/`                       | Python test suite, with subdirectories mirroring major `src/sase/` areas.                              |
| `docs/`                        | MkDocs Material site source.                                                                           |
| `sase/sase.yml`                | Repository-local SASE configuration.                                                                   |
| `sase/xprompts/`               | Repository-local xprompts and workflows for SASE maintenance agents.                                   |
| `sase/memory/`                 | SASE memory files used by repository agents.                                                           |
| `sase/repos/`                  | Runtime-only linked, sidecar, and external repository checkouts.                                       |
| `tools/`                       | Development scripts used by `just` targets and CI checks.                                              |

Detailed subsystem pages often include narrower source-layout tables. Use this page for
initial orientation, then jump to the specific reference for the area you are changing.

## Repository XPrompts

The checkout's `sase/xprompts/` directory is project-local to the `sase` repository.
When SASE resolves prompts from this project checkout, those entries are namespaced as
`sase/<name>` so they do not collide with user or packaged prompts. Use the catalog's
`insertion` value to know whether an entry should be invoked with `#` or `#!`.

Useful visible entries include:

| Reference      | Purpose                                                                                                          |
| -------------- | ---------------------------------------------------------------------------------------------------------------- |
| `#!sase/reads` | Fan out a reading-recommendation request across Antigravity, Claude, and Codex, then consolidate the final list. |
| `#sase/sync`   | Sync the primary SASE workspace and restart axe.                                                                 |

`#!sase/reads` accepts a required `topic` and an optional `reference_query`. By default,
the workflow passes this Dataview query to the research agents:

```dataview
LIST WITHOUT ID title + " (" + url + ")"
FROM "ref"
WHERE
  source_path AND url AND (
    parent = [[ai_ref]]
    OR parent.parent = [[ai_ref]]
    OR parent.parent.parent = [[ai_ref]]
    OR parent.parent.parent.parent = [[ai_ref]]
    OR parent.parent.parent.parent.parent = [[ai_ref]]
  )
SORT title
```

Each research agent is expected to use `/bob_query` to run that query against Bryan's
Bob vault, treat every returned title and URL entry as already-known, and only then
search for new reading candidates. A normal invocation can rely on the default query:

```text
#!sase/reads(agent memory systems)
```

Some repository workflows are marked `hidden: true` because they are automation helpers,
such as docs refresh, recent bug/improvement audits, and Python line-limit splitting.
That flag hides workflow run rows in ACE; it does not mean the workflow is unavailable.
Use `sase xprompt list` or the ACE xprompt browser from a source checkout when you need
the exact current catalog.

## Documentation Workflow

The docs site is a MkDocs Material project:

| Path             | Purpose                                                                                           |
| ---------------- | ------------------------------------------------------------------------------------------------- |
| `mkdocs.yml`     | Main docs site configuration, strict build, navigation, blog, RSS, and theme settings.            |
| `mkdocs-pdf.yml` | PDF handbook build configuration, inheriting the main site config.                                |
| `docs/`          | Markdown, images, stylesheets, JavaScript, redirects, headers, and PDF templates.                 |
| `site/`          | Generated site output. It is rebuilt by docs commands and deployed as the static asset directory. |

Run the strict site build after changing docs navigation, links, images, or Markdown
pages:

```bash
just docs-check
```

Run SASE validation when a change can affect generated initialization files or SDD
artifact links. It is deliberately separate from source linting because it can report
user/home initialization drift and independently managed SDD state:

```bash
sase validate
```

Run the handbook build and validation when a change materially affects the public
handbook, PDF styling, navigation, or generated-site assets:

```bash
just docs-pdf-check
```

`just docs-check` installs only MkDocs tooling, then runs `mkdocs build --strict`.
`just docs-pdf-check` installs the PDF tooling, installs Chromium for Playwright, builds
`mkdocs-pdf.yml` in an isolated temporary site directory, post-processes and validates
the handbook there, and copies only `downloads/sase-handbook.pdf` back into `site/`.

## Docs Deployment

Production docs are deployed by `.github/workflows/docs-deploy.yml`, not by a Cloudflare
dashboard build command. The workflow:

1. Checks out the repo and installs `uv`, `just`, and Python 3.12.
2. Runs `just docs-check`.
3. Runs `just docs-pdf-check`.
4. Verifies `site/index.html`, `site/_headers`, the blog and series pages, and
   `site/downloads/sase-handbook.pdf`.
5. Deploys the prebuilt `site/` directory through `wrangler.jsonc`.
6. Smoke-tests the deployed handbook PDF from the deployment URL and `https://sase.sh/`.

The GitHub repository must provide a `CLOUDFLARE_API_TOKEN` Actions secret with
permission to deploy the `sase` Cloudflare Worker. Keep dashboard-managed Git builds
disabled or unused for production so they cannot race the checked in workflow's prebuilt
artifact deploy.
