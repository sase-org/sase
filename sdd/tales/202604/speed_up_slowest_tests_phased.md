---
create_time: 2026-04-24 10:27:36
status: wip
prompt: sdd/prompts/202604/speed_up_slowest_tests_phased.md
---
# Speed Up Slowest Tests (Phased Multi-Agent Plan)

## Objective

Reduce end-to-end test wall time by targeting the current slowest tests first, while preserving behavioral coverage and
minimizing flakiness. Work is split into independent phases so each phase can be executed by a separate agent instance.

Current baseline provided by user:

- Slowest single test: `11.07s`
- Suite runtime: `55.57s` (`4491 passed, 6 skipped`)

## Strategy

Group the slow tests by shared bottlenecks, then optimize where a single change accelerates many tests:

1. Commit workflow tests repeatedly execute expensive workflow side paths.
2. Ace/Textual tests repeatedly pay full app boot and background loader costs.
3. One integration test performs real PDF generation.
4. Final pass validates aggregate gains and prevents regression.

## Phase 1: Baseline + Profiling Harness (Measurement Foundation)

### Goal

Create stable, repeatable measurement artifacts so subsequent phases can prove net wins and avoid noisy regressions.

### Scope

- Add a lightweight profiling workflow for the known-slowest tests and their nearby files.
- Capture per-test timings for:
  - `tests/test_commit_workflow_changespec.py`
  - `tests/test_commit_workflow_checkpointing.py`
  - `tests/test_commit_workflow_dispatch.py`
  - `tests/test_pr_tags.py`
  - `tests/test_project_pr_prefix.py`
  - `tests/test_ace_tui_app.py`
  - `tests/test_ace_tui_widgets.py`
  - `tests/test_keymaps_e2e.py`
  - `tests/test_ace_testing.py`
  - `tests/test_xprompt_catalog.py`

### Deliverables

- A checked-in perf notes artifact under `sdd/research/` documenting:
  - command(s) used,
  - baseline timings,
  - variance caveats,
  - target thresholds per phase.
- Optional helper command in `Justfile` for repeat runs (if project conventions allow).

### Verification

- Re-run the same command twice; ensure slow-test ranking is directionally stable.
- Confirm artifact is sufficient for next agents to compare before/after numbers.

### Exit Criteria

- Baseline measurements are available and reproducible enough for phase-by-phase comparison.

## Phase 2: Commit Workflow Test Acceleration (Unit/Integration Isolation)

### Goal

Cut runtime of slow commit-workflow tests by eliminating unnecessary real workflow work inside tests that are asserting
narrow behavior.

### Targeted tests

- `tests/test_commit_workflow_changespec.py`
- `tests/test_commit_workflow_checkpointing.py`
- `tests/test_commit_workflow_dispatch.py`
- `tests/test_pr_tags.py`
- `tests/test_project_pr_prefix.py`

### Hypothesized bottlenecks

- Tests call `CommitWorkflow.run()` and still execute expensive non-essential paths (bead handling, plan handling,
  precommit, provider lookup side effects, PR-body/build helpers, diff capture/checkpoint churn).
- Many tests assert only one postcondition but pay for full workflow plumbing.

### Planned changes

- Introduce shared test fixtures/helpers to stub expensive steps by default for this family.
- Narrow each test to only the behavior under test; opt-in to real side path only where explicitly needed.
- Prefer patching workflow internals at the highest safe boundary to avoid repeated setup in each test.
- Keep at least one representative “fuller path” test per feature area to preserve integration confidence.

### Verification

- Run only targeted files; compare before/after durations and ensure all pass.
- Confirm no behavior regressions in commit-workflow artifact tests (`tests/test_commit_workflow_artifacts.py` and
  related workflow tests).

### Exit Criteria

- Meaningful reduction in the top commit-workflow timings.
- No semantic test coverage loss (assertions remain equivalent or stronger).

## Phase 3: Ace/Textual Test Harness Optimization (Shared UI Boot Cost)

### Goal

Reduce repeated per-test startup overhead in AcePage/Textual tests without weakening behavioral checks.

### Targeted tests

- `tests/test_ace_tui_app.py`
- `tests/test_ace_tui_widgets.py`
- `tests/test_keymaps_e2e.py`
- `tests/test_ace_testing.py`

### Hypothesized bottlenecks

- `AcePage()` startup triggers background agent/axe loading and disk scans that are irrelevant for most keypress/state
  assertions.
- Repeated app boot cost dominates short interaction tests.

### Planned changes

- Make `AcePage` test helper default to a “fast test mode” startup that suppresses irrelevant async/background loaders
  (agents/axe) unless explicitly requested.
- Add explicit opt-in flags for tests that need real loader behavior.
- Tune polling defaults in `AcePage` expectations only if safe (avoid introducing flakiness).
- Consolidate repeated patch patterns into helper utilities/fixtures for keymap and modal tests.

### Verification

- Run targeted Ace/Textual files repeatedly to ensure both speed and stability.
- Run nearby UI test groups that also use `AcePage` to catch unintended side effects.

### Exit Criteria

- Largest Ace-related slow tests fall substantially.
- No increase in flaky failures across repeated runs.

## Phase 4: XPrompt Catalog Integration Test Optimization (External Tool Boundary)

### Goal

Speed up the PDF integration test while preserving confidence that the output pipeline still works.

### Targeted test

- `tests/test_xprompt_catalog.py::test_build_integration_produces_pdf`

### Hypothesized bottlenecks

- Real PDF engine invocation (`wkhtmltopdf`/`pandoc`) is expensive and environment-dependent.

### Planned changes

- Keep one minimal integration assertion for “real PDF engine path works,” but reduce work performed (smaller input/data
  path).
- Split heavy end-to-end concerns from deterministic unit-level assertions already covered in this file.
- If needed, add a narrower smoke marker/path so heavy integration can be excluded from routine fast runs while still
  executed in full checks/CI policy.

### Verification

- Validate PDF test still verifies `%PDF` header and artifact creation.
- Ensure failure mode tests (`no engine`, `no xprompts`) remain intact.

### Exit Criteria

- Integration coverage preserved with lower runtime and stable pass behavior.

## Phase 5: Consolidation, Guardrails, and Final Timing Report

### Goal

Validate aggregate gains, harden against regressions, and provide final quantitative outcome.

### Scope

- Re-run the same profiling command from Phase 1.
- Compare before/after top durations and total runtime.
- Add a short contributor note (if appropriate) documenting fast-test patterns introduced (especially for `AcePage` and
  commit-workflow test scaffolding).

### Verification

- `just check` passes.
- Updated slowest-test list shows clear improvement versus baseline.

### Exit Criteria

- Final report committed to `sdd/research/` with:
  - baseline vs final durations,
  - per-phase impact summary,
  - remaining hotspots and next candidates.

## Recommended Agent Sequencing

1. Phase 1 (measurement foundation)
2. Phase 2 (commit-workflow family)
3. Phase 3 (Ace/Textual family)
4. Phase 4 (xprompt PDF integration)
5. Phase 5 (consolidation + guardrails)

Rationale: phases 2 and 3 attack the biggest repeated costs; phase 4 is isolated and can proceed in parallel only after
phase 1 baseline exists; phase 5 must run last.

## Success Targets

- Reduce max single-test duration from ~11s to <5s.
- Reduce cumulative runtime of listed slow tests by at least 40%.
- Reduce full-suite runtime from ~55.6s to <=45s (stretch: <=40s), subject to environment variance.
- Zero net increase in flaky tests across repeated targeted runs.

## Risks and Mitigations

- Risk: Over-mocking hides real regressions.  
  Mitigation: retain representative integration-path tests and run related suites after each phase.

- Risk: UI timing tweaks create flakiness.  
  Mitigation: favor startup-path elimination over tighter timeouts; run repeated loops on affected files.

- Risk: Environment-dependent PDF timing remains variable.  
  Mitigation: keep the integration assertion minimal and rely on unit tests for detail coverage.
