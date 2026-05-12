---
create_time: 2026-05-11 22:00:29
status: done
prompt: sdd/prompts/202605/github_actions_recovery.md
bead_id: sase-31
tier: epic
---
# GitHub Actions Recovery Plan

## Goal

Bring the `sase-org/sase` `master` GitHub Actions workflow set back to green, while using
`tools/last_workflow_set_status` as the primary triage tool and independently validating every status read with `gh`
native commands/API calls. Fix any defects found in the status script along the way.

## Current Baseline

As of the investigation for this plan on 2026-05-12, the newest `master` push `f80ac22e0ab0225bc0d285987e87d26eadf2c885`
was still running. The latest fully completed workflow set selected by
`tools/last_workflow_set_status --repo sase-org/sase --branch master --limit 20 --tail 80` was
`8b270b12391e97152d799c75fd4b91804618b141`; both `Deploy Docs` and `CI` failed.

Independent checks using `gh run list`, `gh run view --json jobs`, `gh run view --log-failed`, and
`gh api repos/sase-org/sase/commits/<sha>/check-runs` agreed with the script on the failing workflows and jobs.

Observed failures:

- `Deploy Docs / Build and deploy docs / Build docs PDF`: `tools/validate_docs_pdf` reports
  `PDF is 22.9 MiB, above the 22 MiB limit`.
- `CI / docs-build / Build docs`: same docs/PDF path is expected to fail until the PDF issue is fixed.
- `CI / lint / Pylimit`: local `just pylimit` reproduces this; `src/sase/ace/tui/widgets/axe_dashboard.py` has 1175
  lines with a 1000-line limit.
- `CI / visual-test / Run visual tests` and `CI / test (3.12) / Run tests`: 12 ACE PNG snapshot mismatches under
  `tests/ace/tui/visual/test_ace_png_snapshots.py`.
- `CI / test (3.13)` and `CI / test (3.14)`: canceled after the 3.12 matrix leg failed; treat them as dependent unless
  later status checks show independent failures.

Status script issue found during triage:

- The script prefers annotations over logs. In these runs, annotations mostly contain generic GitHub messages such as
  `Process completed with exit code 1`, so the script hides the useful `gh run view --log-failed` tail. This should be
  fixed before relying on the tool for later phases.

## Cross-Phase Rules

- Each phase starts by refreshing workflow status with both:
  - `just workflow-status --repo sase-org/sase --branch master --limit 30 --tail 120`
  - `gh run list --repo sase-org/sase --branch master --limit 20 --json databaseId,workflowName,status,conclusion,headSha,displayTitle,createdAt,updatedAt,url`
- For any failed completed set, cross-check details with:
  - `gh run view <run-id> --repo sase-org/sase --json databaseId,workflowName,status,conclusion,headSha,jobs,url`
  - `gh run view <run-id> --repo sase-org/sase --log-failed`
  - `gh api repos/sase-org/sase/commits/<sha>/check-runs`
- Do not treat canceled matrix legs as root causes until the non-canceled failing leg is clean.
- Run `just install` before broad local checks if the workspace has not already been prepared.
- Use `just check` before finishing any phase that changes source/test files, unless the phase changes only SDD/bead
  metadata.
- Do not update memory files without explicit approval.

## Phase 1: Harden Workflow-Status Diagnostics

Owner: agent 1.

Purpose: make the new script reliable enough for the rest of this recovery.

Scope:

- Update `tools/last_workflow_set_status` so failed-run diagnostics can include both matching check-run annotations and
  a failed-log tail. Annotations should no longer suppress logs when the log contains the actual failure.
- Keep existing job/step summaries.
- Preserve JSON output, adding log-tail data without breaking existing consumers if possible.
- Add tests in `tests/test_last_workflow_set_status_cli.py` for:
  - annotations plus logs both rendering in human output;
  - generic annotations not blocking log collection;
  - log fetch errors still degrading cleanly;
  - JSON diagnostics containing both annotations and log tail.

Validation:

- Targeted status-script tests.
- `just workflow-status --repo sase-org/sase --branch master --limit 30 --tail 120`.
- Independent `gh run view --log-failed` check against the same run IDs to confirm the script now surfaces equivalent
  root-cause text.

Deliverable: a script/test change that improves diagnostics without changing run-set selection semantics.

## Phase 2: Fix Pylimit Without Behavioral Changes

Owner: agent 2.

Purpose: clear the deterministic lint failure.

Scope:

- Split `src/sase/ace/tui/widgets/axe_dashboard.py` below 1000 lines.
- Prefer extracting cohesive helpers/rendering utilities into new module(s) under the same ACE TUI widget package.
- Keep public widget behavior and imports stable.
- Avoid unrelated UI or visual changes in this phase.

Validation:

- `just pylimit`
- `just lint`
- focused ACE TUI tests touching `axe_dashboard.py`
- `just check` if the focused tests pass

Deliverable: line-count compliant code with no intended behavior change.

## Phase 3: Fix Docs PDF Build Size

Owner: agent 3.

Purpose: clear both the deploy-docs PDF failure and the CI docs-build failure.

Scope:

- Reproduce with `just docs-pdf-check`.
- Inspect why the aggregate PDF is 22.9 MiB. Likely candidates are PDF inclusion of heavy non-nav image critique/prompt
  pages, recent blog/docs additions, or image-heavy pages.
- Prefer reducing PDF content/asset weight over simply raising `MAX_SIZE_BYTES`.
- Preserve required handbook validation sentinels in `tools/validate_docs_pdf`.
- If excluding docs from the PDF, do it explicitly in MkDocs/PDF configuration or page metadata so the website remains
  intact.

Validation:

- `just docs-check`
- `just docs-pdf-check`
- confirm `site/downloads/sase-handbook.pdf` exists, starts with `%PDF`, and is below the configured limit
- `just check` if source/test files changed beyond docs configuration

Deliverable: docs and deploy PDF checks pass locally.

## Phase 4: Resolve ACE PNG Snapshot Failures

Owner: agent 4.

Purpose: clear the `visual-test` job and the visual failures inside the 3.12 coverage job.

Scope:

- Run `just test-visual` locally and inspect generated `.pytest_cache/sase-visual` artifacts.
- Determine whether the 12 mismatches are intentional UI changes, environment/font drift, or actual regressions.
- If the UI output is correct, update committed PNG goldens with the repository-supported
  `--sase-update-visual-snapshots` flow.
- If output is wrong, fix the ACE TUI rendering code instead of accepting snapshots.
- Keep this phase independent from the `axe_dashboard.py` refactor except for resolving any real conflicts from phase 2.

Validation:

- `just test-visual`
- `just test-cov` on Python 3.12 if feasible
- `just check`

Deliverable: visual snapshot suite passes locally and committed goldens/code reflect the intended UI.

## Phase 5: Full Local Integration

Owner: agent 5.

Purpose: catch interactions between the prior fixes before pushing/rerunning CI.

Scope:

- Start from the merged results of phases 1-4.
- Run the complete local gate:
  - `just install`
  - `just check`
  - `just pylimit`
  - `just docs-check`
  - `just docs-pdf-check`
  - targeted `tests/test_last_workflow_set_status_cli.py`
- Re-run `just workflow-status` and the `gh` alternatives to ensure the live failure surface has not changed.

Validation:

- All local gates above pass, or failures are clearly classified as unrelated/new with evidence.

Deliverable: integration fixups only; no broad refactors.

## Phase 6: Live CI Verification And Residual Failures

Owner: agent 6.

Purpose: verify GitHub Actions are green after the fixes land and handle any CI-only residue.

Scope:

- After changes are pushed, monitor the newest `master` workflow set with the status script.
- Independently verify with `gh run list`, `gh run view --json jobs`, `gh run view --log-failed`, and check-runs API.
- If any workflow still fails, create a new small follow-up plan for only the remaining root cause rather than mixing it
  into already-validated work.
- Confirm Deploy Docs reaches the deploy/smoke steps after the PDF build fix.

Validation:

- Latest fully completed workflow set on `master` is `PASS` in `tools/last_workflow_set_status`.
- `gh run list` shows all required workflows completed successfully for the same head SHA.
- `gh api repos/sase-org/sase/commits/<sha>/check-runs` shows no failed required check-runs.

Deliverable: final status report with the passing SHA, workflow URLs, and any residual non-blocking warnings such as
GitHub Actions Node deprecation/cache warnings.
