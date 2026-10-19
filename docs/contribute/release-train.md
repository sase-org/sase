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
