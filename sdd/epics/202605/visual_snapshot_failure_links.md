---
create_time: 2026-05-11 22:08:30
status: done
prompt: sdd/prompts/202605/visual_snapshot_failure_links.md
bead_id: sase-32
tier: epic
---
# Plan: PNG Snapshot Failure Links In GitHub Actions

## Goal

Make ACE PNG snapshot failures in GitHub Actions easy to triage from the failed check. A maintainer should be able to
open the visual-test job summary and click through to the expected golden, the actual output, and the visual diff for
each failing snapshot without manually downloading and mapping a raw artifact bundle.

This implements the v1 recommendation from `sdd/research/202605/github_actions_png_snapshot_failure_links.md`:
structured failure metadata, a self-contained HTML report artifact, GitHub job-summary links, and source-anchored
annotations. Direct per-PNG artifact URLs, GitHub Pages, PR comments, and hosted visual-regression services stay out of
scope for this first pass.

## Current State

- `.github/workflows/ci.yml` has a dedicated `visual-test` job that installs visual dependencies, runs
  `just test-visual`, and uploads `.pytest_cache/sase-visual` with `actions/upload-artifact@v4`.
- `tests/ace/tui/visual/png_diff.py` already writes `actual.png`, `expected.png`, `diff.png`, `actual.svg`, and
  `summary.txt` beneath `.pytest_cache/sase-visual/<node>/<snapshot>/`.
- The assertion message only prints runner-local paths. Those are useful locally but poor in Actions.
- Visual tests run through `tools/run_pytest` with `pytest-xdist`, so multiple workers can fail at once. A single shared
  `manifest.jsonl` append from pytest workers would be brittle; the implementation should use per-failure sidecar JSON
  as the durable write format and aggregate later.

## Phase 1: Failure Metadata Contract

Owner: one agent focused only on pytest-side artifact generation.

Add structured metadata next to each failed PNG snapshot without changing CI yet.

Implementation shape:

- Extend `AcePngSnapshotFixture` in `tests/ace/tui/visual/png_diff.py` to carry source-location metadata in addition to
  `node_id`: `test_file` and `test_line`.
- Update `tests/ace/tui/visual/conftest.py` to populate that metadata from `request.node.location`.
- Extend `_write_failure_artifacts()` to write a sidecar JSON file inside each failure directory, for example
  `failure.json`.
- Include at least:
  - `node_id`
  - `snapshot`
  - `kind`: `mismatch` or `missing_golden`
  - `expected_repo_path`
  - `actual_path`
  - `expected_path` when present
  - `diff_path` when present
  - `source_svg_path` when present
  - `summary_path`
  - `test_file`
  - `test_line`
  - `expected_size`, `actual_size`, `changed_pixels`, `total_pixels`, and `changed_ratio` when a diff exists
- Prefer repo-relative path strings in JSON so CI summaries are stable and local tests are deterministic.
- Keep the existing human-readable `summary.txt` and assertion messages.

Tests:

- Extend `tests/ace/tui/visual/test_png_diff.py` to assert sidecar JSON for mismatch and missing-golden cases.
- Add coverage that snapshot names and node IDs still produce stable artifact directories.
- Run `just test-visual -- tests/ace/tui/visual/test_png_diff.py`.

Deliverable:

- A standalone patch that only changes pytest visual-test helpers and their tests.

## Phase 2: Report Renderer

Owner: one agent focused on deterministic report generation and local tests.

Add a reusable renderer that consumes the failure metadata from Phase 1 and produces the files GitHub Actions will
publish.

Implementation shape:

- Add an executable script such as `tools/render_visual_snapshot_failure_report`.
- The script should discover `failure.json` records under `.pytest_cache/sase-visual` by default.
- Support explicit flags so tests and CI can run it predictably:
  - `--artifact-root`
  - `--output-dir`
  - `--repo`
  - `--sha`
  - `--report-url`
- Produce:
  - `.pytest_cache/sase-visual-report/visual-failure-report.html`
  - `.pytest_cache/sase-visual-report/summary.md`
  - `.pytest_cache/sase-visual-report/annotations.sh`
  - optionally `.pytest_cache/sase-visual-report/manifest.jsonl` as the aggregate view
- Embed PNG and SVG content directly into the HTML report using data URIs or escaped text, so the report is a single
  file suitable for `actions/upload-artifact@v7` with `archive: false`.
- Do not embed data URI images in `summary.md`; GitHub job summaries sanitize them. The summary should contain a compact
  table with links.
- Expected links should point to the immutable committed golden:
  `https://github.com/${repo}/blob/${sha}/${expected_repo_path}`.
- Actual and diff links should point to `${report_url}#<stable-anchor>` when a report URL is available. Before upload,
  generate usable placeholder/local anchor text so the script can be run in a build-only mode.
- `annotations.sh` should emit escaped workflow-command annotations, for example:
  `::error file=...,line=...,title=ACE PNG snapshot mismatch::...`.
- Handle no-record cases by exiting 0 and either writing no files or writing a short empty report, so failure-only CI
  steps are safe.

Tests:

- Add focused tests that create a tiny fake artifact tree with `failure.json` and PNG files, run the renderer, and
  assert that:
  - HTML contains stable anchors and embedded image data.
  - Summary contains expected GitHub blob links and report anchor links.
  - Annotation shell output has escaped `%`, newline, carriage return, colon-sensitive fields, and source location.
  - Missing expected/diff files are represented cleanly for missing-golden failures.
- Run the renderer test file directly, then `just test -- <new test selector>`.

Deliverable:

- A script and tests that can be used locally before any CI wiring changes.

## Phase 3: GitHub Actions Wiring

Owner: one agent focused only on workflow integration.

Wire the existing `visual-test` job to build, upload, and publish the visual failure report.

Implementation shape:

- Keep the `Run visual tests` step as the failure-producing step.
- Add a report build step after tests with `if: failure()`:
  - run `tools/render_visual_snapshot_failure_report`
  - generate the self-contained HTML report before upload
- Add an unzipped report upload step:
  - use `actions/upload-artifact@v7`
  - set `archive: false`
  - upload `.pytest_cache/sase-visual-report/visual-failure-report.html`
  - give the step an `id`, for example `visual_failure_report`
- Add a final publication step after upload with `if: failure()`:
  - pass `VISUAL_REPORT_URL: ${{ steps.visual_failure_report.outputs.artifact-url }}`
  - rerun the renderer with `--report-url "$VISUAL_REPORT_URL"` or a finalize mode
  - append `summary.md` to `$GITHUB_STEP_SUMMARY`
  - run `annotations.sh`
- Change the raw `.pytest_cache/sase-visual` artifact upload from `if: always()` to `if: failure()` and keep
  `if-no-files-found: ignore`.
- Leave the raw artifact upload on `actions/upload-artifact@v4` unless there is a clear reason to move it; only the HTML
  report needs v7 `archive: false`.
- Be careful with workflow ordering: the artifact URL is not available until after the upload step completes.

Tests:

- Run YAML formatting/lint checks that already exist in `just check`.
- If possible, locally run the renderer with a fake `GITHUB_REPOSITORY`, `GITHUB_SHA`, and `VISUAL_REPORT_URL` to verify
  the exact command lines used in the workflow.

Deliverable:

- CI workflow patch only, with no behavioral changes to snapshot comparison itself.

## Phase 4: End-To-End Hardening And Documentation

Owner: one agent focused on validating the full user experience and filling in docs.

Exercise the full path locally and document the failure artifacts enough that future maintainers understand the moving
pieces.

Implementation shape:

- Add a short developer-doc note in `docs/development.md` or the existing visual snapshot section describing:
  - where failure artifacts are written locally
  - how CI turns them into the visual failure report
  - why actual/diff links point at the report artifact rather than public PNG URLs
- Optionally add a small README/comment near the renderer test fixture if the generated files are not self-explanatory.
- Run a local forced-mismatch smoke test without accepting goldens, then run the renderer against the generated
  `.pytest_cache/sase-visual` directory and inspect that HTML, summary, and annotations are coherent.
- Restore any intentionally modified fixture/golden used to force the mismatch; do not leave a failing snapshot change
  behind.

Tests:

- `just test-visual -- tests/ace/tui/visual/test_png_diff.py`
- Renderer-specific tests from Phase 2.
- `just check` before final handoff, after running `just install` if the workspace needs dependency refresh.

Deliverable:

- Documentation and final verification. No new feature scope should be added here unless an earlier phase exposed a
  correctness hole.

## Phase Boundaries And Handoff Notes

- Phase 1 must land before Phase 2 because the renderer should consume the real metadata contract rather than parsing
  assertion text.
- Phase 2 can be developed against synthetic `failure.json` fixtures once Phase 1's schema is known.
- Phase 3 should not rewrite report generation logic; it should only call the tool from Phase 2.
- Phase 4 should treat the implementation as feature-complete and focus on proving the end-to-end debugging path works.
- Each phase should be independently reviewable and should run the narrowest relevant tests first. The final phase is
  responsible for the full `just check`.

## Out Of Scope For V1

- Uploading every PNG as its own single-file artifact.
- Publishing reports to GitHub Pages.
- Posting or updating PR comments.
- Adding Argos CI, reg-suit, or another hosted visual-regression service.
- Changing the snapshot approval workflow or auto-updating goldens.

## Open Decisions For Implementers

- Whether the renderer implementation lives entirely in `tools/render_visual_snapshot_failure_report` or has a small
  importable helper module under `tests/ace/tui/visual/`. Prefer whichever keeps tests straightforward without adding
  product code under `src/sase`.
- Whether to aggregate `failure.json` files into a `manifest.jsonl` in Phase 2. This is useful for debugging and matches
  the research note, but the per-failure JSON files should remain the source of truth to avoid xdist write contention.
- Whether the top of the HTML report should show `diff, expected, actual` or `expected, actual, diff`. The research
  favors diff-first because it answers "what changed?" fastest.
