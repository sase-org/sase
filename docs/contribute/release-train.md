---
title: "Release train"
description:
  "Every sase release is a sealed candidate built once at its tag: the wheel and sdist
  plus an exact sase-core-rs with its full file set and digests."
---

# Release train

Every sase release is a sealed candidate built once at its tag: the wheel and sdist plus
an exact `sase-core-rs==X.Y.Z` with its full file set and digests. It is qualified
against the published core, exercised on Linux and macOS, published from the retained
bytes with digest-checked resume, and confirmed from PyPI before it is un-drafted.

## Topology

`release.yml` runs the whole train. Its jobs are `identity`, `build`, `stash`,
`qualify`, `exercise`, `publish` and `confirm`. `publish` needs `qualify` and
`exercise`. Concurrency is `release-${{ github.ref }}` with no cancel; the qualify call
uses `qualify-<sha>`, never cancelled.

`tools/release_candidate` owns the candidate manifest: `seal` writes the immutable
sealed fields, `observe` appends one observation asset, `verify` rechecks a sealed
manifest, `evaluate` runs the promotion predicate, `show` prints a manifest, `download`
resolves an asset locator, `core-files` fetches the core PyPI file list and cross-checks
`uv.lock`, `core-suffixes` parses the completeness set from sase-core's
`release-plz.yml`, `publish-plan` diffs the sealed dist set against PyPI for a
digest-checked upload plan, and `confirm` verifies every sealed file is listed on PyPI
with a matching SHA-256 and nothing extra.

## Modes

| Mode       | Dispatched at                    | Stores evidence in       | Publishes                       |
| ---------- | -------------------------------- | ------------------------ | ------------------------------- |
| `release`  | a `v*` tag                       | the draft GitHub release | yes, once qualified             |
| `resume`   | a `v*` tag with passing evidence | the draft GitHub release | only `publish` + `confirm`      |
| `rehearse` | a branch (normally `master`)     | workflow artifacts       | never; `publish` is verify-only |

`rehearse` accepts a `core_version` override, sealed into the manifest as `override`.
The override is refused outside `rehearse` mode.

## Identity rule

In `release` and `resume` modes the tag, the peeled tag SHA, `GITHUB_SHA`,
`pyproject.toml`'s version and `__version__` must all agree. In `rehearse` mode the
branch ref SHA, the checkout SHA, `pyproject.toml` and `__version__` must all agree. Any
mismatch refuses.

## Manifest schema

Sealed at build and immutable: the repository, version, tag (or the rehearsal ref),
peeled SHA and tree; the candidate ID and build generation; the builder workflow
revision, run ID and attempt; the core source pin; the exact core version with its full
file set and PyPI digests; and every dist's filename, size and SHA-256 plus its asset
locator.

The candidate ID derives only from sealed fields: it is stable across observations and
changes with the generation. A rebuild at the same tag is a new generation that must be
qualified again, and it requires the `rebuild: true` input so a duplicate dispatch can
never double-build.

Observations are append-only, each its own asset named by generation, kind, run ID and
attempt. The kinds are `qualification`, `exercise`, `publication`, `confirmation`,
`abandoned` and `veto`.

## Exercise

The `exercise-legs` job installs the sealed wheel and sdist into clean environments and
proves the candidate works from its exact files. The matrix is `os` (`ubuntu-latest`,
`macos-latest`) by `artifact` (`wheel`, `sdist`) with `fail-fast: false`, so one red
platform never hides the other. Each leg downloads the sealed build, verifies its
SHA-256 against the manifest before installing anything, then runs
`tools/exercise_release run-leg`:

1. Install the exact file with `uv tool install --python 3.12`, with dependencies from
   public PyPI, into an isolated home (`HOME`, `SASE_HOME`, `XDG_*`, `UV_TOOL_DIR`,
   `UV_TOOL_BIN_DIR`) with `UV_NO_CACHE=1`. The tool scrubs caller-session `SASE_*`
   leaks and seeds the smallest owner identity a clean home needs.
2. Assert the installed `sase-core-rs` equals the manifest's exact pin
   (`sase version -j`).
3. Create durable work with a real fakey agent launch (`sase run %model:fakey-large`),
   wait for it, then reload its record in a new process.
4. Prove the host/worker crossing from the durable record (fakey provider, worker
   invocation records, terminal `done.json`).
5. Render one frame through `sase screenshot`, the visual-snapshot tooling.
6. Run `uv pip check` and `sase core health --json` against the install.
7. On `wheel` legs only, install the newest still-installable PyPI release at or below
   the candidate (strictly older at real tags; the released same-version bytes in
   version-equals-last-release rehearsals, since retention deletes old cores and an
   uninstallable newest-older is skipped, never forced), create durable state with it,
   upgrade to the candidate wheel, then reload the state and rerun health.

Each leg uploads `exercise-<os>-<artifact>.json` with the verdict, the first failed step
and its reason. The `exercise` summary job merges the four legs into one `exercise`
observation: all green means pass, while any red, missing or unreadable leg yields
`EXERCISE_RED(<os>)`, which withholds publication. In `release` mode the observation is
stashed on the draft release; in `rehearse` mode it is a workflow artifact.

The rehearse-only `probe` input injects faults: `break-macos` deletes one imported
module from the installed package on the macOS legs only, so those legs must go red and
the merge must report `EXERCISE_RED(macos)`. Probes are refused in `release` and
`resume` modes.

## Qualify

The `qualify-prepare` job downloads the current run's `candidate-build` artifact and
binds the sealed manifest: candidate ID, generation, SHA, core version and inventory
digest. `qualify-ci` then calls the reusable `.github/workflows/ci.yml` at the exact
identity SHA with `core-source` `published`, so the blocking jobs run against the sealed
published core instead of a source build. `qualify` reads the completed `qualify-ci`
jobs through paginated Actions API requests under the exact `qualify-ci` call scope and
evaluates them with `tools/release_candidate qualify`: missing, skipped, cancelled,
stale or unreadable evidence is a typed `QUALIFY_RED` outcome, never a pass.

Only the inventory (`.github/release-qualification.json`) decides what blocks: the
evaluator loads it, the steward and metrics import its loader, and this page does not
restate the list. One failed-job rerun with `gh run rerun --failed` is eligible only
after a first attempt whose every failing blocker is classified `tests`; collection,
missing, zero, harness and second-attempt failures are never rerun-eligible. The retry
carries unchanged successful executions forward by job ID and needs new evidence for
every rerun job. Advisory jobs stay visible in the observation but can never veto the
verdict.

The rehearse-only `probe_core_version` input tests an older core without resealing the
manifest: the tested version is recorded next to the intended one, and a probe run stays
red even when the evaluator would otherwise pass. Probes are refused outside `rehearse`
mode.

## Publish and confirm

The `publish` job depends on the `qualify` verdict and `exercise`, never on the
`qualify-ci` aggregate, so its status condition passes through required verdicts even
when an advisory ancestor failed. It runs the promotion predicate
(`tools/release_candidate evaluate`) over the generation's `qualification` and
`exercise` observations — workflow artifacts in `rehearse` mode, draft-release assets in
`release` and `resume` modes — and refuses on any red clause, so a red exercise leg
withholds publication. In `resume` mode it additionally refuses without passing evidence
for the generation; it never rebuilds or reruns qualification.

Before any upload it re-verifies every staged digest against the sealed manifest, then
runs `tools/release_candidate publish-plan` against the PyPI file list for the version:

- an identical file already on PyPI is skipped as `already-present`;
- a missing file is planned as `upload`;
- an existing filename with a different digest refuses with `PUBLISH_CONFLICT`;
- a PyPI file that is not in the manifest refuses with `PUBLISH_CONFLICT`;
- a missing stashed asset refuses with `PUBLISH_MISSING_ASSET`.

Only the planned `upload` subset is published with
`pypa/gh-action-pypi-publish@release/v1` and `skip-existing: false`, keeping the default
attestations on. An interrupted upload resumes by re-dispatching with `mode: resume` at
the same tag: identical files are skipped and the rest are uploaded. Two concurrent
resumes for one tag serialize through the `publish-<ref>` concurrency group. A
`publication` observation records each file as uploaded or already present. In
`rehearse` mode `publish` runs the predicate and the plan only, with no environment and
no upload — a rehearsal at `master` whose version equals the last release must report
`PUBLISH_CONFLICT` for every file, which is the live proof of the different-hash
refusal.

The `confirm-install` matrix installs `sase==<version>` from public PyPI into isolated
tool directories on Linux and macOS, then requires `sase version -j` to report the
manifest's core and `sase core health --json` to pass. The `confirm` finalizer polls the
PyPI JSON with a bounded wait for CDN lag until every manifest file is listed with a
matching SHA-256 and nothing extra: a missing file is `PUBLISH_PARTIAL` and retries,
while a mismatch or an extra file is `PUBLISH_CONFLICT` and refuses at once. It then
runs the family canary with the exact rule
(`tools/check_family_install --mode exact --expect sase==<version>`), un-drafts with
`gh release edit v<version> --draft=false --latest`, and records a `confirmation`
observation. Un-drafting happens only after every check passes; `confirm` never runs in
`rehearse` mode.

## Tag-frozen workflow rule

A workflow dispatched at a tag runs that tag's own workflow files. A tag cut before
`release.yml` existed can never run it, and a `release.yml` fix reaches only later tags.
Rehearse at `master`. A candidate broken by its own `release.yml` is burned, never
patched in place.

## Promotion predicate

One implementation, `tools/release_candidate evaluate`, used by the `publish` job and
the steward:

```text
publishable(candidate) =
    source_and_version_identity_match
    AND exact_expected_files_retained_and_hashed
    AND every_required_check_has_acceptable_evidence_for_this_candidate
    AND public_dependency_contract_satisfied
    AND no_confirmed_release_veto
```

Missing evidence is red. Skipped, cancelled, missing, stale, zero-collected or
unreadable evidence never satisfies a gate.

## Inspecting the release steward

`tools/release_watch` reads GitHub and PyPI facts, asks the Rust core for a decision,
and reports its state, evidence, proposed train action, and escalation. Run it from the
repository's Python environment with `sase_core_rs` built from `sase-core-revision.txt`
and authenticated `gh` access:

```bash
.venv/bin/python tools/release_watch --once
.venv/bin/python tools/release_watch --tick --json
.venv/bin/python tools/release_watch --until-released --poll 5m --deadline 12h
```

| Mode                         | Behavior                                                                        |
| ---------------------------- | ------------------------------------------------------------------------------- |
| `--once` (default)           | One read-only decision                                                          |
| `--tick`                     | One decision, with proposed actions reported but not executed                   |
| `--tick --live`              | Permit the proposed train action and escalation after their precondition checks |
| `--until-released [VERSION]` | Repeat read-only snapshots until the selected version is confirmed              |

Without an explicit version, the wait selects the single in-flight release, or a newly
confirmed version if there is no single in-flight release to select. Once selected, the
target stays fixed. A version already confirmed when this automatic wait starts does not
satisfy it; an explicitly named version can return immediately if already confirmed.
Polling defaults to five minutes with a twelve-hour deadline. The poll and deadline
options apply only to this waiting mode. Waiting observes the train; it does not execute
the actions needed to advance it.

The scheduled `release-steward.yml` workflow runs every fifteen minutes, live: each tick
executes the proposed train action and escalation after their precondition checks. A
manual dispatch stays observe-only unless its `live` input is explicitly true. Merge
authority is separately controlled by `RELEASE_STEWARD_MERGE_ENABLED`: only the literal
value `true` enables it. The workflow builds or restores the core wheel for the exact
`sase-core-revision.txt` pin before running the decision.

A well-formed blocked state exits `0`; read the reported state to assess release
readiness. `watcher_broken` and an expired wait deadline exit `1`; invalid arguments
exit `2`. With `--json`, the final report goes to stdout and diagnostics go to stderr.
Waiting prints progress to stderr and emits one final report when it stops. GitHub
Actions also receives a step summary.

## The steward

One stateless steward decides release merges and the core cut. Each tick reads GitHub
and PyPI facts, asks the Rust core for one typed decision, and executes at most one
train action plus the escalation. The decision names a primary state, the evidence
behind it, the proposed or executed action, and the escalation:

| State                    | Meaning                                                               |
| ------------------------ | --------------------------------------------------------------------- |
| `nothing_to_release`     | no release PR and no in-flight train                                  |
| `waiting`                | held for metadata refresh, cadence, or another precondition           |
| `releasable`             | the release PR is eligible; the merge waits on merge authority        |
| `released`               | the train confirmed and un-drafted the version                        |
| `gate_red`               | the Master gate or a required check is red at the candidate SHA       |
| `qualify_red`            | qualification failed against the published core                       |
| `exercise_red`           | the Linux or macOS exercise leg failed                                |
| `core_lag`               | no complete published core contains the source pin yet; the steward   |
|                          | dispatches at most one core cut per UTC day, only with merge          |
|                          | authority on                                                          |
| `core_cut_red`           | the newest completed merge-capable sase-core cut failed (push and     |
|                          | heal runs never merge the release PR, so they are not cuts)           |
| `core_ci_red`            | the core side is red                                                  |
| `core_incompatible`      | the published core does not satisfy the dependency contract           |
| `install_broken`         | the family install canary is red (never blocks a qualified candidate) |
| `publish_partial`        | some sealed files are already on PyPI; resume finishes the rest       |
| `publish_conflict`       | PyPI holds files the manifest did not seal; a human untangles it      |
| `dependency_unpublished` | a required file is missing from PyPI                                  |
| `vetoed`                 | a human veto stands against the candidate                             |
| `ambiguous_trains`       | more than one in-flight train; a human picks one                      |
| `watcher_broken`         | facts, policy, or execution failed; the remedy names the fix          |

A blocked state names its typed reason and its owner action in the mirrored issue: rerun
the named check, cut the named core, resume the named tag with
`release.yml -f mode=resume`, or yank and fix forward per
[release safety](release-safety.md). The steward never merges when
`RELEASE_STEWARD_MERGE_ENABLED` is anything but the literal `true`: a releasable release
PR is then reported with its merge action suppressed until a human flips the switch.
ci_watch never merges a `sase` release PR; the steward is the single decider.

Cadence is daily: at most one release merge per UTC day, after the daily core cut, and a
burned candidate frees the slot. Actions and escalation run on the schedule; only merges
wait on the authority switch.

## Release evidence and metrics

`tools/release_metrics` reports read-only release history over a default 28-day window.
Each metric includes its numerator, denominator, and window; empty samples appear as
`n/a (0 of 0)`. Blocking checks come from `.github/release-qualification.json`, the same
inventory used by release qualification.

```bash
.venv/bin/python tools/release_metrics
.venv/bin/python tools/release_metrics --window 28 --json
.venv/bin/python tools/release_metrics green <full-commit-sha>
```

The `green` subcommand emits JSON for one exact SHA, including `release_green`, the
Master gate and Full CI evidence, blocking-job evidence, and missing evidence. Inspect
the JSON verdict: a successfully generated report exits `0` even when its verdict is
false. This inspection does not publish or promote a candidate.

The steward's report carries a fresh metrics block once a day: the 09:00 UTC ticks run
`tools/release_metrics` and append its Markdown under a `Release metrics` heading in the
same step summary. The block is informational only; it never gates the train.

## Related

- [Release safety and recovery](release-safety.md) — broken releases and installation
  checks.
- [Rust backend](rust-backend.md) — the core dependency and source pin.
