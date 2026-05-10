---
create_time: 2026-05-09 21:10:25
status: done
prompt: sdd/prompts/202605/tui_screenshot_diff_testing.md
bead_id: sase-2m
tier: epic
---
# TUI Screenshot Diff Testing Plan

## Goal

Add screenshot-based visual regression testing for SASE's ACE TUI in a way that is useful in normal development,
reviewable in pull requests, and stable enough for CI.

The implementation should follow the research in `sdd/research/202605/tui_pixel_snapshot_testing.md`: start with
Textual-native SVG screenshots from `AceApp.run_test()`, then layer true PNG pixel diffs on top of the SVG path, and
treat real terminal-emulator screenshots as optional smoke/debug coverage rather than the default gate.

## Current Repo Context

- `src/sase/ace/tui/app.py` defines `AceApp`, a Textual app.
- `src/sase/ace/testing.py` defines `AcePage`, the existing Playwright-inspired async TUI test harness around
  `AceApp.run_test(size=...)`.
- The installed Textual API supports `app.export_screenshot(title=..., simplify=...)`.
- Existing TUI tests assert state, plain rendered text, and widget behavior, but there are no committed ACE visual
  snapshot goldens today.
- `pyproject.toml` already includes `pillow`, `textual[syntax]`, `pytest`, `pytest-asyncio`, `pytest-xdist`, and
  `inline-snapshot`.
- `pytest` is configured with `--strict-markers`, so any new visual marker must be registered.
- CI runs tests on Python 3.12, 3.13, and 3.14. Pixel baselines should not be introduced into that whole matrix until
  their renderer and font inputs are pinned.

This is presentation/test infrastructure only. Do not move behavior into `../sase-core`; the Rust boundary memory says
presentation-only Textual state, layout, widgets, rendering, and Python glue belong in this repo.

## Guiding Decisions

1. Prefer a SASE-owned fixture over adopting `pytest-textual-snapshot` immediately. This costs a little more code, but
   it keeps update flags, artifact paths, fixture ergonomics, and future PNG diff behavior under SASE's control.

2. Commit SVG goldens first. SVG snapshots are deterministic enough to gate normal TUI visual regressions without native
   Cairo, browser, terminal, PTY, font, or desktop-display dependencies.

3. Add PNG pixel diff as an opt-in `visual` test layer. PNG tests require a renderer and font policy. They should be
   marked and runnable through a dedicated command before they gate the default `just test` matrix.

4. Keep snapshot inputs narrow and deterministic. Every visual test should fix terminal size, use deterministic
   changespec/agent fixtures, set `refresh_interval=0`, avoid live artifact scans unless explicitly mocked, and settle
   the app before capture.

5. Make updates explicit. Snapshot updates should require a flag such as `--sase-update-visual-snapshots`; normal test
   runs should never mutate goldens.

## Phase 1: SVG Snapshot Foundation

Agent ownership:

- `src/sase/ace/testing.py`
- `tests/ace/tui/visual/`
- `tests/conftest.py` or a visual-specific `conftest.py`
- `pyproject.toml` pytest marker entries

Implementation:

- Add an `AcePage.export_svg(title: str | None = None, simplify: bool = True) -> str` helper that calls
  `self.app.export_screenshot(title=title, simplify=simplify)`.
- Add a small in-repo visual snapshot fixture, for example `ace_visual.assert_svg(page, name, title=None)`.
- Store SVG goldens under `tests/ace/tui/visual/snapshots/svg/`.
- Add a pytest option `--sase-update-visual-snapshots` for accepting intentional SVG golden changes.
- Add a pytest option or deterministic default for failure artifact output. The failure output should include:
  - expected SVG, when one exists;
  - actual SVG;
  - a short HTML report that renders expected and actual side by side when possible;
  - a clear assertion message pointing to those files.
- Register a `visual` marker in `pyproject.toml`.
- Keep these tests out of the default fast test path at first by marking them `visual` and `slow`, or by making the
  first phase test the fixture without committing broad visual cases yet.

Validation:

- Add unit tests for the helper/fixture behavior:
  - missing golden fails unless the update flag is passed;
  - update mode writes a golden;
  - matching SVG passes;
  - mismatched SVG writes failure artifacts.
- Run a focused pytest command for the new fixture tests.
- Run `just check` after the phase's file changes.

Phase handoff criteria:

- A future visual test can be written as an `AcePage` flow plus one `ace_visual.assert_svg(...)` call.
- The snapshot update workflow is explicit and documented in the assertion failure text.

## Phase 2: First ACE SVG Goldens

Agent ownership:

- `tests/ace/tui/visual/test_ace_svg_snapshots.py`
- `tests/ace/tui/visual/snapshots/svg/`
- Test-only fixture helpers near the visual tests

Implementation:

- Add the first small set of committed SVG goldens. Start with high-value, stable surfaces:
  - initial changespec list layout at `(120, 40)`;
  - selected-row/focus styling after a deterministic `j` navigation;
  - query edit modal after pressing `slash`;
  - command palette or another modal only if it can be opened deterministically without live state;
  - agent list with hand-built representative `Agent` objects or fully mocked loader output.
- Build deterministic fixture data rather than relying on real `~/.sase` artifacts or live background processes.
- Normalize only proven volatile SVG fields. Do not add broad regex cleanup until a failing test demonstrates the need.
- Keep snapshot names stable and descriptive, e.g. `changespec_initial_120x40.svg`.

Validation:

- Run the new visual SVG tests normally and verify they pass without updating goldens.
- Run the same tests with a deliberately changed local golden or captured output to verify failures are understandable.
- Run `just check`.

Phase handoff criteria:

- The repo has a useful initial visual regression suite that can catch layout/style regressions before PNG pixels exist.
- Reviewers can inspect committed SVG changes directly in PRs.

## Phase 3: PNG Pixel Diff Layer

Agent ownership:

- `pyproject.toml`
- `uv.lock`, if dependency resolution is changed
- `tests/ace/tui/visual/`
- Possible new test helper module such as `tests/ace/tui/visual/png_diff.py`

Implementation:

- Add an opt-in visual dependency path. Preferred shape:
  - `[project.optional-dependencies].visual = ["cairosvg", "pixelmatch"]`, or use only `cairosvg` plus Pillow exact
    diffs for the first cut.
  - Do not put native/raster dependencies into the default `dev` extra unless the team explicitly wants every developer
    and CI test job to install them.
- Add `render_svg_to_png(svg: str) -> bytes` using the pinned renderer.
- Add `assert_png_matches(name, png_bytes, max_diff_pixels=0, max_diff_ratio=0.0)` with failure artifacts:
  - expected PNG;
  - actual PNG;
  - diff PNG;
  - source SVG used to create actual PNG;
  - numeric summary of changed pixels and changed ratio.
- Decide whether to commit PNG goldens immediately or generate PNGs only as failure artifacts from SVG goldens.
  Recommendation: commit PNG goldens only for the few tests that genuinely need pixel-level assertions.
- Add tests for the PNG comparator with tiny in-memory Pillow images before wiring it to full ACE screenshots.

Validation:

- Install visual extras locally for the phase's test run.
- Run focused PNG comparator tests.
- Run the visual SVG-to-PNG tests in a Linux environment if the renderer depends on platform font behavior.
- Run `just check` after dependency and fixture changes.

Phase handoff criteria:

- A marked test can capture ACE SVG, rasterize it, compare pixels, and emit diff artifacts without affecting default
  non-visual test runs.

## Phase 4: Developer Commands, Docs, And CI Policy

Agent ownership:

- `Justfile`
- `.github/workflows/ci.yml`
- docs or SDD docs near the testing guidance, if there is an established place
- `pyproject.toml` pytest marker/addopts, if needed

Implementation:

- Add a focused command such as `just test-visual` that installs or assumes visual extras and runs only visual tests.
- Keep visual tests out of the default `just test` initially unless Phase 1/2 SVG-only tests prove fast and stable.
- If CI should run visual tests, add a dedicated job on Ubuntu only:
  - install Python 3.12;
  - install `.[dev,visual]`;
  - pin any renderer/font environment needed by Phase 3;
  - run `just test-visual`;
  - upload visual failure artifacts on `always()`.
- Document the update workflow:
  - run visual tests normally;
  - inspect artifacts;
  - rerun with `--sase-update-visual-snapshots` only for intentional changes;
  - review SVG/PNG changes as test data.
- Document when to add a visual test versus a plain state/widget test.

Validation:

- Run `just test-visual`.
- Run `just check`.
- If CI workflow changes are made, validate YAML formatting and keep-sorted checks.

Phase handoff criteria:

- Developers have a clear command for visual tests and a safe update workflow.
- CI has an explicit policy rather than accidental visual coverage hidden in the broad matrix.

## Phase 5: Optional Real-Terminal Smoke Coverage

Agent ownership:

- New optional slow/integration test path only
- CI workflow only if the team wants a dedicated terminal smoke job
- No changes to the default ACE visual fixture unless a real-terminal result proves a reusable need

Implementation:

- Re-evaluate after SVG and PNG-in-process coverage are working.
- If still needed, add one small slow smoke path using one of:
  - `vhs` for scripted release/debug screenshots;
  - `pexpect` plus `pyte` for subprocess ANSI-grid assertions;
  - Microsoft `tui-test` only if the project is comfortable adding Node/TypeScript test infrastructure.
- Pin terminal size, locale, `TERM`, font, and OS/container image.
- Keep this suite small and nonblocking until it has proven stable.

Validation:

- Run only in a dedicated slow command or CI job.
- Verify process cleanup and timeouts.

Phase handoff criteria:

- SASE has a path for "what a real terminal sees" debugging without making everyday visual regression tests flaky.

## Cross-Phase Risks

- Textual SVG markup may change across Textual versions. Keep Textual pinned through the lockfile and review snapshot
  churn when dependencies are updated.
- PNG rendering is font-sensitive. Do not gate broad CI pixels until renderer and font inputs are pinned.
- Visual snapshots can become noisy if too broad. Prefer a few representative full-screen states plus narrower state or
  widget tests for behavior.
- Snapshot update flags are dangerous if hidden in broad commands. Keep them explicit and never part of `just fmt`,
  `just check`, or default CI.
- Existing tests isolate `~/.sase`; visual fixtures should preserve that isolation and avoid reading real user state.

## Recommended Agent Split

1. Agent 1 implements Phase 1 only.
2. Agent 2 implements Phase 2 only, using the fixture APIs from Phase 1.
3. Agent 3 implements Phase 3 only, with visual extras and PNG comparator tests.
4. Agent 4 implements Phase 4 only, after the exact test commands and markers from earlier phases are known.
5. Agent 5 handles Phase 5 only if the team still wants terminal-emulator smoke coverage after reviewing the in-process
   results.

This sequencing keeps each agent's write set small and avoids parallel agents editing the same fixture and CI files at
the same time.
