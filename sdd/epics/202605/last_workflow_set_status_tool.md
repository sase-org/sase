---
create_time: 2026-05-11 20:59:30
status: done
prompt: sdd/prompts/202605/last_workflow_set_status_tool.md
bead_id: sase-2z
tier: epic
---
# Plan: Last GitHub Workflow Set Status Tool

## Goal

Implement an executable script in `tools/` that answers:

> What is the newest fully completed set of GitHub Actions workflow runs on the repository default branch, did every
> workflow in that set pass, and if not, which workflows failed with useful failure detail?

The implementation should follow the research in `sdd/research/202605/last_workflow_set_status_script.md`, stay scoped
to a local developer/agent utility, and avoid changing SASE core backend behavior. This is a repo-local tool, not shared
domain logic for the Rust core.

## Proposed User Interface

Create `tools/last_workflow_set_status` as an executable Python script with no third-party runtime dependencies beyond
the standard library and the installed `gh` CLI.

Suggested CLI:

```bash
tools/last_workflow_set_status [--repo OWNER/REPO] [--branch BRANCH] [--limit N] [--tail N]
                               [--require NAME[,NAME...]] [--event EVENT ...]
                               [--json]
```

Defaults:

- `--branch`: detected with `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`.
- `--limit`: `50`.
- `--tail`: `50`.
- `--event`: `push`.
- `--require`: empty, meaning use the discovered workflows for the selected SHA.
- `--json`: off, meaning human-readable terminal output.

Exit codes:

- `0`: a complete set was found and all selected runs passed.
- `1`: a complete set was found and at least one selected run did not pass.
- `2`: user/configuration problem such as bad arguments, missing `gh`, unauthenticated `gh`, or invalid JSON from `gh`.
- `3`: no fully completed set was found inside the requested fetch window.

Pass conclusions should be `success`, `skipped`, and `neutral`. All other terminal conclusions should be reported as not
passed.

## Important Repo Constraints

- New file target: `tools/last_workflow_set_status`.
- Because `tools/pyscripts-260314` requires scripts under `tools/` to be referenced from elsewhere in the repo, add a
  stable in-repo reference. Prefer a short `Justfile` recipe such as:

  ```just
  workflow-status *args:
      tools/last_workflow_set_status "$@"
  ```

  If the implementing agent chooses a different reference point, it must still satisfy `just _lint-pyscripts`.

- The tool should be directly executable and keep the `#!/usr/bin/env python3` style used by nearby scripts.
- Tests should not make live GitHub calls by default. Use subprocess/runner fakes and JSON fixtures.
- After code changes, run `just install` if the workspace has not been bootstrapped, then run targeted tests and
  ultimately `just check`.

## Technical Design

Use a small layered script:

- CLI layer: `argparse`, exit-code mapping, human and JSON output selection.
- GitHub command layer: one function/class responsible for invoking `gh`, capturing stdout/stderr, decoding JSON, and
  turning failures into clear user-facing errors.
- Domain layer: dataclasses for workflow runs, jobs, steps, annotations, and selected run-set result.
- Selection algorithm:
  - Fetch runs with `gh run list --branch <branch> --event <event> --limit <limit> --json ...`.
  - Sort by `createdAt` descending in Python.
  - Deduplicate by `(workflowDatabaseId, headSha)`, keeping the highest `attempt`, then newest `updatedAt` as a tie
    breaker.
  - Group by `headSha` in newest-first order.
  - Skip groups containing non-terminal statuses such as `queued`, `in_progress`, `waiting`, `requested`, or `pending`.
  - If `--require` is present, skip groups missing any required workflow names.
  - Select the first remaining group.
- Failure-detail algorithm:
  - For each failed run, fetch `gh run view <run-id> --json jobs` to summarize failing jobs/steps.
  - Try check-run annotations with `gh api /repos/{owner}/{repo}/commits/{sha}/check-runs` followed by
    `/repos/{owner}/{repo}/check-runs/{id}/annotations` for failed check-runs associated with the selected SHA.
  - Fall back to `gh run view <run-id> --log-failed` and print only the last `--tail` lines when annotations are absent.
  - Keep parallel fetching optional and isolated; serial implementation is acceptable until behavior is well tested.

Do not implement branch-protection required-check discovery in the first end-to-end slice unless the phase agent has
extra time. It is useful, but it maps job/check contexts rather than workflow names and would complicate the v1 surface.

## Phase 1: Skeleton, CLI, and `gh` Boundary

Owner: first implementation agent.

Files owned:

- `tools/last_workflow_set_status`
- `tests/tools/test_last_workflow_set_status_cli.py` or equivalent test file
- `Justfile` only for the minimal recipe/reference needed by `pyscripts`

Deliverables:

- Executable Python script with argparse options, documented defaults, and stable exit-code constants.
- `GhClient` or equivalent boundary with methods for `run_json(...)`, `run_text(...)`, and friendly error handling for
  missing `gh`, nonzero `gh`, and invalid JSON.
- Default branch detection through `gh repo view`.
- Human-readable placeholder flow that can parse arguments and report configuration errors, even if selection is not
  fully implemented yet.
- Unit tests for argument parsing, default branch lookup invocation, `--repo` propagation, missing `gh`, nonzero `gh`,
  and invalid JSON.

Validation:

- Run the new targeted tests.
- Run `just _lint-pyscripts` to confirm the new tool is referenced correctly.

Handoff notes:

- Keep the script importable from tests despite having no `.py` suffix; use `importlib.machinery.SourceFileLoader` in
  tests if needed.
- Leave domain logic hooks clean for Phase 2 rather than embedding all behavior in `main()`.

## Phase 2: Run-Set Selection and Pass/Fail Reporting

Owner: second implementation agent.

Files owned:

- `tools/last_workflow_set_status`
- tests focused on run parsing, deduplication, grouping, required workflows, and output/exit codes

Deliverables:

- Parse `gh run list` rows into typed run objects.
- Implement sorting, latest-attempt deduplication, SHA grouping, terminal-status filtering, and `--require` filtering.
- Produce useful human output for the passing and failing-summary cases:
  - branch, short SHA, title if available, run-set size
  - per-workflow conclusion and URL
  - "all passed" or "N of M workflows did not pass"
- Implement `--json` output for the selected set and summary result.
- Return exit code `0`, `1`, or `3` as appropriate.

Validation:

- Fixture-based tests for:
  - newest complete SHA wins
  - newest SHA still running is skipped
  - rerun attempt wins over older attempt
  - `success`/`skipped`/`neutral` pass
  - `failure`/`cancelled`/`timed_out` fail
  - missing `--require` workflow skips a group
  - no complete set returns exit code `3`

Handoff notes:

- Do not fetch failure details in this phase beyond naming failed workflows; Phase 3 owns diagnostic enrichment.

## Phase 3: Failure Diagnostics

Owner: third implementation agent.

Files owned:

- `tools/last_workflow_set_status`
- tests focused on job/step summaries, annotations, log tails, and fallback order

Deliverables:

- Fetch failing jobs and steps with `gh run view <id> --json jobs`.
- Fetch check-run annotations through `gh api` using the selected run's `headSha`; print compact annotation lines when
  present.
- Fall back to `gh run view <id> --log-failed` and tail the result when annotations are empty or unavailable.
- Handle empty/unavailable logs without crashing.
- Keep diagnostic fetching limited to failed runs.
- If adding parallelism, isolate it behind a small helper and make tests deterministic.

Validation:

- Fixture-based tests for:
  - annotations are preferred over logs
  - logs are tailed to the requested number of lines
  - failed job/step summaries appear when logs are empty
  - cancelled runs do not attempt unavailable log paths endlessly
  - multiple failed workflows are reported independently

Handoff notes:

- The annotations endpoint returns check runs for the whole SHA, so filter or label carefully to avoid attaching
  unrelated check output to the wrong workflow when possible. If exact workflow mapping is not available in v1, prefer
  clearly saying "annotations for failed check-runs on this SHA" rather than implying a perfect one-to-one mapping.

## Phase 4: Hardening, Docs, and Live Smoke

Owner: fourth implementation agent.

Files owned:

- `tools/last_workflow_set_status`
- `Justfile` if the recipe needs final polish
- `sdd/research/202605/last_workflow_set_status_script.md` only if documenting deviations from the research is useful
- optional short user-facing docs in an existing appropriate README, if needed for discoverability

Deliverables:

- Polish terminal formatting and error messages.
- Confirm executable bit is set.
- Confirm all command examples use current option names.
- Run an opt-in live smoke against `sase-org/sase` if `gh auth status` is healthy:

  ```bash
  tools/last_workflow_set_status --repo sase-org/sase --branch master --limit 50 --tail 20
  ```

- Run the full required repo check.

Validation:

- `just install` if needed.
- targeted tests for the tool.
- `just check`.

Handoff notes:

- Do not require live network access in normal tests.
- If `just check` fails for unrelated dirty-worktree reasons, capture the exact failing command and reason in the final
  handoff.

## Deferred Enhancements

- Branch-protection/ruleset required-check discovery. This is a good Phase 5 if the tool becomes part of an automated
  release workflow, but it requires mapping check-run contexts back to workflow runs and should not block v1.
- `--event merge_group` defaults for repos that use GitHub merge queue.
- Time-window selection via `--created`.
- Richer machine-readable output schema intended for future `sase ace` integration.
- Caching or rate-limit-aware batching for very large repositories.
