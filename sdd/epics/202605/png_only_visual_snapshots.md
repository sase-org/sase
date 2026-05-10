---
title: PNG-only ACE visual snapshots
bead_id: sase-2p
tier: epic
create_time: 2026-05-10 01:05:51
status: done
prompt: sdd/prompts/202605/png_only_visual_snapshots.md
---

# PNG-only ACE visual snapshots

## Goal

Remove ACE SVG snapshot support and leave PNG snapshots as the only supported visual regression golden format. Add a
small but useful PNG snapshot suite, targeting 3-5 deterministic ACE TUI states.

This is test infrastructure and presentation-layer work only. Per the Rust boundary memory, it belongs in this Python
repo; no behavior should move into `../sase-core`.

## Current Context

- Visual snapshot code is concentrated under `tests/ace/tui/visual/`.
- SVG support currently consists of:
  - `tests/ace/tui/visual/svg_snapshot.py`
  - `tests/ace/tui/visual/test_svg_snapshot.py`
  - `tests/ace/tui/visual/test_ace_svg_snapshots.py`
  - `tests/ace/tui/visual/snapshots/svg/*.svg`
  - the `ace_visual` fixture in `tests/ace/tui/visual/conftest.py`
- PNG support already exists in:
  - `tests/ace/tui/visual/png_diff.py`
  - `tests/ace/tui/visual/test_png_diff.py`
  - the `ace_png_visual` fixture in `tests/ace/tui/visual/conftest.py`
  - empty committed snapshot root `tests/ace/tui/visual/snapshots/png/`
- `just test-visual` already installs the `visual` extra, runs tests marked `visual`, and CI has a dedicated Ubuntu
  visual-test job that pins DejaVu fonts and uploads `.pytest_cache/sase-visual` artifacts.
- The PNG helper currently rasterizes Textual's SVG export into PNG. That is acceptable as an implementation detail, but
  committed goldens and test-facing APIs should be PNG-oriented only. Keeping the source SVG as a failure artifact is
  useful debugging output, not SVG snapshot support.

## Phase 1: Make The PNG Fixture The Only Public Visual Snapshot API

Agent ownership:

- `tests/ace/tui/visual/png_diff.py`
- `tests/ace/tui/visual/conftest.py`
- `tests/ace/tui/visual/test_png_diff.py`

Implementation:

- Treat `AcePngSnapshotFixture` as the sole visual snapshot fixture.
- Remove the `AceSvgSnapshotFixture` import and `ace_visual` fixture from `tests/ace/tui/visual/conftest.py`.
- Keep `ace_png_visual` as the canonical fixture name, or rename it to `ace_visual` only if all visual tests are updated
  in the same phase. Avoid supporting both names long-term.
- Consider adding a PNG-oriented convenience method name such as `assert_page_png(...)` while preserving the existing
  `assert_svg_png(...)` only if needed during the transition. The final test code should read as PNG snapshot
  assertions, not SVG snapshot assertions.
- Keep `source_svg` in PNG failure artifacts if it remains helpful for debugging rasterization failures.
- Strengthen `test_png_diff.py` if needed so it covers:
  - update mode writes PNG goldens;
  - matching PNG passes;
  - missing golden writes actual PNG and summary artifacts;
  - mismatch writes expected, actual, diff, and summary artifacts;
  - unsafe snapshot names are rejected;
  - page capture rasterizes through the renderer.

Validation:

- Run focused PNG helper tests:
  - `just test-visual tests/ace/tui/visual/test_png_diff.py`
- Run `rg -n "AceSvgSnapshotFixture|ace_visual|assert_svg\\(" tests/ace/tui/visual` and confirm any remaining hits are
  in files assigned to later phases.

Handoff criteria:

- New visual tests have a clear PNG-only fixture path.
- There is no public pytest fixture encouraging SVG golden snapshots.

## Phase 2: Convert The Existing Full-screen ACE Visual Cases To PNG

Agent ownership:

- `tests/ace/tui/visual/test_ace_svg_snapshots.py` or its replacement
- `tests/ace/tui/visual/snapshots/png/`
- Any shared deterministic fixture helpers colocated with the visual tests

Implementation:

- Replace `test_ace_svg_snapshots.py` with PNG snapshot coverage. A direct rename to `test_ace_png_snapshots.py` is
  preferred for clarity.
- Reuse the existing deterministic fixtures in that file:
  - static `make_changespec(...)` data;
  - hand-built `Agent` objects;
  - mocked startup loaders and notification snapshot;
  - fixed `AcePage` size.
- Convert the existing high-value states into PNG assertions. The recommended 4 tests are:
  - initial changespec list at `120x40`;
  - selected changespec row after pressing `j`;
  - query edit modal after pressing `slash`;
  - agents list with representative DONE, FAILED, and PLAN DONE agents.
- Store committed PNG goldens in `tests/ace/tui/visual/snapshots/png/` using stable names such as:
  - `changespec_initial_120x40.png`
  - `changespec_selected_row_120x40.png`
  - `query_edit_modal_120x40.png`
  - `agents_list_120x40.png`
- Use strict pixel matching initially (`max_diff_pixels=0`, `max_diff_ratio=0.0`) unless the agent observes a real,
  documented renderer instability. Do not add tolerance preemptively.
- Generate/accept PNG goldens with:
  - `just test-visual tests/ace/tui/visual/test_ace_png_snapshots.py --sase-update-visual-snapshots`
- Re-run without the update flag to prove the checked-in PNG goldens pass.

Validation:

- Run:
  - `just test-visual tests/ace/tui/visual/test_ace_png_snapshots.py`
  - `file tests/ace/tui/visual/snapshots/png/*.png`
- Inspect `.pytest_cache/sase-visual/` only if a visual test fails.

Handoff criteria:

- The repo has 3-5 committed PNG ACE visual goldens.
- The old full-screen SVG snapshot tests no longer exist.

## Phase 3: Remove The SVG Snapshot Implementation And Goldens

Agent ownership:

- `tests/ace/tui/visual/svg_snapshot.py`
- `tests/ace/tui/visual/test_svg_snapshot.py`
- `tests/ace/tui/visual/snapshots/svg/`
- References to SVG snapshots in test docs or comments

Implementation:

- Delete `tests/ace/tui/visual/svg_snapshot.py`.
- Delete `tests/ace/tui/visual/test_svg_snapshot.py`.
- Delete `tests/ace/tui/visual/snapshots/svg/`, including SVG goldens and placeholder files.
- Search the repo for SVG snapshot API references and remove or rewrite them:
  - `rg -n "svg_snapshot|AceSvgSnapshotFixture|assert_svg\\(|snapshots/svg|ACE SVG snapshot|SVG visual snapshot"`
- Do not remove generic `export_svg` or rasterization internals from the PNG helper unless there is a replacement path.
  Textual's screenshot API is still SVG-based, and the PNG helper may need that as an implementation detail.
- Update assertion/error wording in remaining visual helpers so the user-facing workflow says PNG snapshots, not SVG
  snapshots.

Validation:

- Run:
  - `rg -n "svg_snapshot|AceSvgSnapshotFixture|assert_svg\\(|snapshots/svg|ACE SVG snapshot" tests src README.md .github`
  - `just test-visual tests/ace/tui/visual`

Handoff criteria:

- No SVG snapshot helper, fixture, test, or committed SVG golden remains.
- Any remaining `svg` terms are implementation details for Textual export or PNG rasterization, not supported snapshot
  storage.

## Phase 4: Update Commands, Docs, And CI Wording For PNG-only Visual Tests

Agent ownership:

- `README.md`
- `Justfile`
- `.github/workflows/ci.yml`
- `pyproject.toml`, only if marker or dependency wording needs adjustment
- `uv.lock`, only if dependency resolution changes unexpectedly

Implementation:

- Keep `just test-visual` as the visual test command; it already installs `.[dev,visual]` and runs `-m visual`.
- Update nearby comments/docs to call these PNG visual regression snapshots rather than generic SVG/screenshot snapshots
  where the distinction matters.
- Keep the `visual` extra with `cairosvg>=2.7,<3`; it is still needed to rasterize Textual output to PNG.
- Keep CI's dedicated visual-test job and font pinning. Update step labels only if they mention SVG or are unclear.
- Ensure README update instructions remain explicit:
  - run `just test-visual`;
  - inspect `.pytest_cache/sase-visual/` on failure;
  - rerun with `--sase-update-visual-snapshots` only for intentional PNG golden changes.

Validation:

- Run:
  - `just test-visual tests/ace/tui/visual`
  - `just check`

Handoff criteria:

- Developer-facing docs and CI labels match the PNG-only support policy.
- The default non-visual test lane remains unchanged.

## Phase 5: Final Sweep And Integration

Agent ownership:

- Whole repo search and verification only; avoid broad refactors.

Implementation:

- Run final repo-wide searches:
  - `rg -n "SVG snapshot|svg snapshot|AceSvgSnapshotFixture|svg_snapshot|snapshots/svg|assert_svg\\(" .`
  - `rg -n "PNG snapshot|AcePngSnapshotFixture|assert_svg_png|assert_page_png|snapshots/png" tests/ace/tui/visual README.md Justfile .github`
- Confirm the only remaining SVG references are acceptable implementation details:
  - `render_svg_to_png(...)`
  - `source_svg` failure artifacts
  - Textual page export protocol naming, if not renamed
- Run full visual tests and the normal project check:
  - `just test-visual`
  - `just check`
- If any generated PNGs are unexpectedly unstable, document the exact instability in the test or plan notes before
  adding tolerance.

Handoff criteria:

- `just test-visual` passes with PNG goldens only.
- `just check` passes.
- The repository no longer exposes SVG snapshots as a supported test feature.

## Risks And Guardrails

- PNG goldens are more sensitive to renderer and font changes than SVG goldens. Keep the dedicated Ubuntu visual CI job
  and pinned fonts.
- Do not add broad pixel-diff tolerances unless a concrete, reproduced instability demands it.
- Do not remove `cairosvg` just because SVG goldens are gone; PNG snapshots still need a rasterizer unless a new capture
  backend is introduced.
- Do not run snapshot update flags in default checks or CI.
- Keep the PNG suite small. Four representative full-screen states should catch broad layout regressions without making
  every UI change noisy.
