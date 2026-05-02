---
create_time: 2026-04-24 10:30:48
status: done
---
# Plan: `just check` runs `just test` (coverage reserved for CI)

## Goal

Make the local `just check` dev-loop command run `just test` (fast, no coverage) instead of `just test-cov`. Coverage —
with the 50% gate, term/html/xml reports — remains enforced only in GitHub Actions CI.

## Motivation

`just check` is the pre-reply gate agents and humans run before finishing a task. It currently invokes `just test-cov`,
which adds coverage instrumentation and report generation on top of every local run. That's useful in CI (where the gate
actually protects master) but is pure tax for a pre-reply smoke test. CI already calls `just test-cov` directly in
`.github/workflows/ci.yml`, so gating `just check` on coverage is redundant with CI and just makes the local loop slower
and noisier.

## Current wiring (what's actually there)

- `Justfile:127` — the `check` recipe's final line: `@tools/run_silent "test" just test-cov`.
- `Justfile:93` — comment above `test` recipe:
  `Fast parallel test run, no coverage (use test-cov to enforce coverage gate)`.
- `Justfile:98` — comment above `test-cov` recipe:
  `Parallel test run with coverage reports + 50% gate (used by check and CI)`.
- `.github/workflows/ci.yml:76` — the CI `test` job calls `just test-cov` directly (not via `just check`). **No CI
  change needed** — this is already correct.
- `memory/short/build_and_run.md:8` — documents `just test-cov` as "used by just check / CI".
- `README.md:345` and `CONTRIBUTING.md:18` — document `just check` as "All checks (fmt-check + lint + test-cov)".

## Design

Single-line functional change in `Justfile`; the rest is aligning stale docs/comments so future readers aren't misled.

### Functional change

- `Justfile:127` — swap `just test-cov` → `just test` in the `check` recipe's last step. Keep the `run_silent "test"`
  label — the user-facing step name is still "test".

### Comment & doc alignment (non-functional)

- `Justfile:98` — `test-cov` docstring: drop "used by check and CI" → "used by CI" (check no longer uses it).
- `Justfile:93` — `test` docstring already says "no coverage (use test-cov to enforce coverage gate)"; leave as-is. It
  remains accurate and nudges contributors toward `test-cov` when they want the gate.
- `memory/short/build_and_run.md:8` — change "used by just check / CI" → "used by CI".
- `README.md:345` — change "(fmt-check + lint + test-cov)" → "(fmt-check + lint + test)".
- `CONTRIBUTING.md:18` — same change as README.

### Intentionally out of scope

- **No CI workflow edits.** `.github/workflows/ci.yml` already calls `just test-cov` directly. The whole point of this
  change is that CI's invocation path is the _only_ thing that should ever run `test-cov`.
- **No change to `test-cov` itself.** Recipe body (flags, gate, reports) is unchanged.
- **No change to `pyproject.toml` `addopts` / coverage config** — `test-cov` already carries the `--cov*` flags, so
  `just test` is correctly coverage-free today.
- **No historical plan/research docs rewritten** (`plans/`, `sdd/research/`, `sdd/beads/issues.jsonl`). Those are dated
  records of past decisions — mutating them would be dishonest about history. The speedup plan in
  `plans/202604/test_suite_speedup.md` explicitly chose the old wiring; that's fine, this plan supersedes it.

## Risks & mitigations

- **Agents stop noticing coverage regressions locally.** That's the deliberate trade — CI is the authoritative gate.
  Contributors who want the gate locally can still run `just test-cov` on demand (the recipe isn't removed), and the
  comment on `just test` continues to point them at it.
- **Someone greps "just check" looking for the coverage gate and gets confused.** The doc updates in README /
  CONTRIBUTING / `build_and_run.md` make the new contract explicit so this shouldn't happen.

## Verification

1. `just check` runs and reports PASS for the `test` step, with no coverage output (no `htmlcov/`, no `coverage.xml`, no
   "TOTAL ... %" line).
2. `just test-cov` run directly still produces the coverage reports and enforces the 50% gate.
3. `.github/workflows/ci.yml` is unchanged; CI's `test` job still runs `just test-cov` and uploads `coverage.xml` to
   Codecov on 3.12.
4. Grep confirms no remaining doc claims that `just check` runs coverage.
