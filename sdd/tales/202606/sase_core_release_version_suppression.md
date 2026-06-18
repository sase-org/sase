---
create_time: 2026-06-18 10:42:24
status: done
prompt: sdd/prompts/202606/sase_core_release_version_suppression.md
---
# Plan: Fix sase-core release `0.1.3`-instead-of-`0.2.0` versioning defect

## TL;DR

PR #10 on `sase-core` released **`0.1.3`** even though the release range contains a real **breaking change**
(`feat(core)!: remove the episode module and PyO3 bindings`, commit `a86e5b7`), which should have produced **`0.2.0`**
under Cargo's 0.x SemVer rules.

The root cause is **not** a bug in release-plz, `next_version`, the `release-plz.toml` config, or the CI workflow. It is
an **author/agent mistake**: the feature commit `bc5835d` (`feat(beads): add core bead search CLI (sase-4w.2)`)
**manually bumped the workspace version `0.1.2 → 0.1.3`** in `Cargo.toml`. release-plz manages versions itself; once the
in-repo manifest version (`0.1.3`) was already _ahead_ of the last released tag (`0.1.2`), release-plz stopped deriving
the version from conventional commits and just kept `0.1.3` — silently masking the breaking-change minor bump to
`0.2.0`.

This plan covers (1) a one-time correction of the mis-versioned, already-published release and (2) a guard + docs to
prevent recurrence.

> Scope note: all code/CI/doc changes are in the sibling **`sase-core`** repo. When implementing, open it with
> `sase workspace open -p sase-core 12`. This plan file lives in the primary `sase` workspace only so it can be proposed
> with `sase plan propose`.

---

## 1. What happened (evidence)

The version was computed correctly until the manual bump landed. Per-commit release-plz CI runs on `master` (job
_"Release-plz PR"_, release-plz `v0.3.159`):

| master commit (push time)                                 | release-plz computed next version |
| --------------------------------------------------------- | --------------------------------- |
| `a86e5b7` breaking change lands (Jun 16)                  | **0.2.0** ✓                       |
| `075..`/`77..`/`f9..` intermediate (Jun 16–18)            | **0.2.0** ✓                       |
| `077f4aa` (Jun 18 12:37) — manifest still `0.1.2`         | **0.2.0** ✓                       |
| **`bc5835d`** (Jun 18 13:02) — manifest bumped to `0.1.3` | **0.1.3** ✗ ← the flip            |
| merge of PR #10 → tag `v0.1.3`                            | released **0.1.3**                |

The only delta between the last `0.2.0` run and the first `0.1.3` run is `bc5835d`, whose diff is:

```
[workspace.package]
-version = "0.1.2"
+version = "0.1.3"
...
-sase_core = { path = "crates/sase_core", version = "0.1.2" }
+sase_core = { path = "crates/sase_core", version = "0.1.3" }
```

and whose commit body literally says _"Bump the core workspace version to 0.1.3 for the additive binding."_ (Note: it
was even bumped as a **patch** by an author who only saw the _additive_ binding and was unaware of the unreleased
`feat(core)!` breaking change still queued in the same release.)

### Confirmed mechanism

- release-plz **did** detect the breaking change — PR #10's changelog renders
  `*(core)* [**breaking**] remove the episode module and PyO3 bindings`.
- `next_version 0.3.2` (the calculator release-plz `0.3.159` pins) is correct: feeding it the exact commit yields
  `0.1.2 → 0.2.0` (verified in isolation).
- The suppression happens in `release_plz_core` (`command/update/updater.rs`): when the local manifest version is
  greater than the last released version, it takes the _"only update the changelog, don't bump the version"_ path. A
  local reproduction with release-plz `0.3.159` at commit `bc5835d` reproduced `0.1.3` exactly and logged:

  ```
  INFO sase_core:    local version (0.1.3) > registry version (0.1.2). Only changelog will be updated.
  INFO sase_core_py: local version (0.1.3) > registry version (0.1.2). Only changelog will be updated.
  ```

This is intentional release-plz behavior (it lets you pin/override versions by hand). The team's workflow simply must
never hand-edit versions, because doing so overrides automatic SemVer.

## 2. Impact (why this is a real issue)

- **`sase-core-rs 0.1.3` is published on PyPI** and contains breaking API removals (the `episode` module + its six PyO3
  bindings). Under SemVer/Cargo 0.x rules, `0.1.3` advertises compatibility with `0.1.2`, but it is **not** compatible.
  (cargo crate publish is disabled — `publish = false` — so PyPI is the only consumer surface; `0.2.0` is absent from
  PyPI.)
- Any consumer with a constraint like `sase-core-rs~=0.1.2` or `>=0.1,<0.2` that upgrades to `0.1.3` breaks at runtime
  (`ImportError` / missing functions) with no SemVer warning.

## 3. What is NOT broken (explicitly out of scope)

- `release-plz.toml`, `release-plz.yml`, `pr-title.yml`, `next_version`, and the breaking-change detection are all
  working correctly. **Do not** "fix" them — changing them would not address the cause and risks regressions.
  `semver_check = false` is fine here (the conventional-commit `!` marker is honored independently).

## 4. Proposed fix

### Part A — Correct the mis-versioned release (recommended: supersede with `0.2.0` + yank `0.1.3`)

The breaking change deserves a SemVer-honest version. Recommended steps (each PyPI/tag action is
**irreversible/outward-facing → requires explicit user go-ahead before execution**):

1. **Cut `0.2.0`.** Because `v0.1.3` is now the latest tag and the breaking commit is already "behind" it, release-plz
   will not re-derive `0.2.0` from new commits. Deliberately set the release target to `0.2.0` — this is the _one
   legitimate_ manual version action — via the release-plz-endorsed path (`release-plz set-version` / a
   `chore(release): set 0.2.0` prep), then let the normal release-plz PR + release flow publish `v0.2.0` and the PyPI
   wheels. `0.2.0` carries the same code as `0.1.3`; it is purely a SemVer-correct relabel of the breaking change.
2. **Yank `sase-core-rs 0.1.3` on PyPI** so resolvers fall back to `0.1.2` for `<0.2` constraints while leaving `0.2.0`
   available for opt-in. (Yank, not delete.)
3. **Annotate the `v0.1.3` GitHub release** noting it inadvertently shipped breaking changes and is superseded by
   `v0.2.0`. Keep the git tag (rewriting public tags is discouraged).

> Lighter alternative (if the user prefers minimal churn): leave `0.1.3` in place and only ensure the next release is
> `≥0.2.0`. This leaves a mislabeled breaking release on PyPI; not recommended, but viable given sase-core is
> early-stage and may have no external consumers yet. **Decision for the user.**

### Part B — Prevent recurrence

1. **CI guard (sase-core):** add a `pull_request` check (extend `.github/workflows/pr-title.yml` or a small new job)
   that **fails any PR which changes a `version` field in `Cargo.toml` / crate manifests unless the PR head branch is a
   release-plz branch** (`release-plz-*`). Emit a message: _"Versions are managed by release-plz; do not edit `version`
   manually. Use a conventional `feat!:`/`BREAKING CHANGE:` commit and release-plz will compute the version."_ Provide a
   documented override (e.g. a `manual-version` PR label) for the rare deliberate case (such as the Part A `0.2.0`
   correction).
2. **Docs (sase-core):** add a short "Releasing / versioning" note (README or `CONTRIBUTING`) stating that release-plz
   owns versions, manual `Cargo.toml` version edits are forbidden, and breaking changes must be marked so the minor
   (0.x) bump is computed automatically. Because the offending bump was made by an agent, mirror this as explicit
   guidance for agents working in sase-core.

## 5. Risks & decisions for the user

- **Decision 1 — correction strategy:** supersede with `0.2.0` **and** yank `0.1.3` (recommended) vs. leave `0.1.3` and
  only go forward.
- **Decision 2 — PyPI yank:** confirm the yank of `sase-core-rs 0.1.3` (affects downstream installs).
- These outward-facing/irreversible actions (PyPI yank, publishing `0.2.0`, editing the GitHub release) will **not** be
  performed until the user explicitly approves them.
- The CI guard must allow-list release-plz's own branches so it does not block legitimate release PRs.

## 6. Verification

- After Part A: `pip index`/PyPI shows `0.1.3` yanked and `0.2.0` available; `git tag` shows `v0.2.0`; the `v0.2.0`
  GitHub release + wheels exist.
- After Part B: open a throwaway PR that edits `[workspace.package].version` from a normal branch → the new check fails;
  the same edit from a `release-plz-*` branch passes. Re-run a local `release-plz update` on a synthetic breaking change
  with a clean manifest → confirms automatic minor bump still works.
- Run `just check` in the sase-core workspace for any code/CI changes there.
