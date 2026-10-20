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
`uv.lock`, and `core-suffixes` parses the completeness set from sase-core's
`release-plz.yml`.

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
restate the list. A failed blocking job may be retried once with
`gh run rerun --failed`; the retry carries unchanged successful executions forward by
job ID and needs new evidence for every rerun job. Advisory jobs stay visible in the
observation but can never veto the verdict.

The rehearse-only `probe_core_version` input tests an older core without resealing the
manifest: the tested version is recorded next to the intended one, and a probe run stays
red even when the evaluator would otherwise pass. Probes are refused outside `rehearse`
mode.

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
