---
create_time: 2026-05-10
status: research
---

# ACE TUI Pixel Snapshot Testing

## Question

What are the practical options for taking snapshots of what SASE's ACE TUI looks like and performing pixel diffs in
tests?

## Recommendation

Use a layered visual-regression path:

1. Add a SASE-owned `AcePage`/pytest helper that captures Textual's native SVG screenshot from `AceApp.run_test()`.
2. Commit SVG goldens for the first version, either through `pytest-textual-snapshot` or a small in-repo fixture.
3. Add PNG pixel diffs as a second layer by rasterizing the SVG with one pinned renderer in CI, then comparing PNGs with
   Pillow or `pytest-regressions`.
4. Treat real terminal-emulator screenshots as an optional smoke/debug path, not the default CI gate.

This gives SASE deterministic, in-process coverage for "what Textual is trying to draw" while still making room for
true pixel diffs when needed. It avoids making the everyday TUI test suite depend on a PTY, terminal emulator, browser,
desktop display, or native Cairo stack until the specific test needs that fidelity.

## Current SASE Context

ACE is already in the right shape for in-process visual snapshots:

- `src/sase/ace/tui/app.py` defines `AceApp`.
- `src/sase/ace/testing.py` defines `AcePage`, which wraps `AceApp.run_test(size=...)`, `Pilot.press()`, `Pilot.click()`,
  structured state extraction, and plain-text screen capture.
- `tests/test_ace_testing.py` already proves the repo is comfortable testing ACE through `AcePage`.
- Existing TUI tests mostly assert state, widget behavior, or rendered text. There are no committed visual snapshot
  goldens for ACE today.
- `pyproject.toml` currently includes `textual[syntax]>=0.45.0`, `pillow`, `pytest`, `pytest-asyncio`, `pytest-xdist`,
  and `inline-snapshot`. It does not include `pytest-textual-snapshot`, `syrupy`, `cairosvg`, `pytest-regressions`,
  `playwright`, `pixelmatch`, or `pyte`.
- The `inline-snapshot` dep is relevant: it can already store small expected strings (or normalized SVG fragments)
  literally inside the test source and updated with `pytest --inline-snapshot=fix`. This gives SASE a zero-extra-deps
  option for very small visual assertions before committing to a full snapshot tree.
- Prior research in `sdd/research/202605/tui_agent_screenshot_automation.md` recommends Textual-native screenshot
  capture for agent automation. This research extends that direction for pytest visual regression and pixel diffs.

The practical implication: the cheapest useful first implementation is to extend `AcePage`, not to launch `sase ace` in
a subprocess.

## Two Different "Looks Like" Targets

There are two valid interpretations of "what the TUI really looks like":

| Target | What it tests | Stability | Best use |
| --- | --- | --- | --- |
| Textual render snapshot | Textual's screen model after CSS/layout/rendering, exported as SVG | High | CI visual regression for SASE-owned widgets and layouts |
| Terminal-emulator raster screenshot | What a specific terminal emulator paints with a specific font, DPI, antialiasing, and color profile | Low to medium | Manual debugging, release screenshots, smoke tests for terminal integration |

For ACE, Textual render snapshots should be the default. Terminal-emulator pixel snapshots sound more "real", but they
also bake in font metrics, glyph rasterization, OS behavior, terminal settings, and GPU/display differences. That makes
them a poor default for routine CI.

## Option A: Official Textual SVG Snapshots

Textual documents `App.run_test()` as a headless test context that returns a `Pilot`, and `App.export_screenshot()` /
`App.save_screenshot()` as SVG screenshot APIs. Textual also documents `pytest-textual-snapshot` as its official pytest
snapshot plugin for visual regression testing. Internally, `pytest-textual-snapshot` is implemented on top of
[`syrupy`](https://github.com/syrupy-project/syrupy), so adopting it transitively brings in the syrupy snapshot
framework and CLI conventions (`--snapshot-update`, `--snapshot-warn-unused`, etc.). Textual itself uses this exact
plugin to gate every release — see `tests/snapshot_tests/test_snapshots.py` in the Textual repo — which is the strongest
signal of upstream support.

How it would look in SASE:

```python
async def test_ace_initial_layout_svg(snapshot_compare):
    app = AceApp(query='"feature"', refresh_interval=0, auto_start_axe=False)
    assert snapshot_compare(app, terminal_size=(120, 40))
```

Or, with SASE's existing test DSL:

```python
async def test_ace_initial_layout_svg(ace_snapshot):
    async with AcePage(size=(120, 40)) as page:
        ace_snapshot.assert_svg(page, "ace_initial_layout")
```

Pros:

- Lowest implementation cost.
- Best aligned with Textual's native rendering model.
- No new native system dependencies.
- Supports deterministic terminal sizes.
- Supports key presses before capture through `Pilot.press()` or `pytest-textual-snapshot`'s `press` / `run_before`
  hooks.
- Produces an inspectable artifact that is more meaningful than plain text.

Cons:

- It is not a true pixel diff unless rasterized later.
- SVG text/layout can still be noisy if Textual changes its screenshot markup between versions.
- The official plugin updates all accepted snapshots through `pytest --snapshot-update`, so SASE should document a
  review workflow before accepting changes.

Prior art worth copying: Harlequin (a Textual-based SQL IDE) exposes an `app_snapshot` fixture and produces a
`snapshot_report.html` browser report with side-by-side before/after and a "Show Difference" toggle. That report is the
single biggest UX improvement over a raw text diff and should be the bar for whichever route SASE picks.

Best fit: first milestone.

## Option B: SASE-Owned SVG Fixture

Instead of adopting `pytest-textual-snapshot`, SASE can add a small fixture around `AcePage.app.export_screenshot()` or
`save_screenshot()`:

```python
async def test_ace_initial_layout_svg(ace_visual):
    async with AcePage(size=(120, 40)) as page:
        await page.press("tab")
        ace_visual.assert_svg(page, "ace_after_tab")
```

The fixture would:

- capture SVG from `page.app.export_screenshot(simplify=True)`;
- normalize volatile fields if needed;
- compare against `tests/ace/tui/snapshots/*.svg`;
- write `actual`, `expected`, and `diff.html` artifacts on failure;
- update goldens only behind an explicit flag such as `--sase-update-visual-snapshots`.

Pros:

- Full control over filenames, update policy, normalization, reports, and SASE-specific fixtures.
- Easy to integrate with `AcePage` custom changespec fixtures.
- Avoids adding a pytest plugin dependency.

Cons:

- More code to maintain.
- Need to build reporting/update ergonomics that the official plugin already provides.
- Still not a pixel diff without rasterization.

A SASE fixture can also lean on the already-installed `inline-snapshot` for the very smallest assertions — for
example, snapshotting a single rendered status line or an extracted SVG region directly inside the test source. This is
not a substitute for full-page goldens but is useful for small targeted regressions where a separate file would be
overkill.

Best fit: if SASE wants tighter control than the official plugin, especially around deterministic fixtures and artifact
paths.

## Option C: SVG To PNG Plus Pillow Pixel Diff

This is the smallest true pixel-diff layer on top of Textual snapshots:

1. Capture SVG through Textual.
2. Rasterize the SVG to PNG with one fixed renderer.
3. Compare PNGs with Pillow.
4. Emit a diff image and numeric summary.

Basic comparison shape:

```python
from PIL import Image, ImageChops

expected = Image.open(expected_png).convert("RGBA")
actual = Image.open(actual_png).convert("RGBA")
diff = ImageChops.difference(expected, actual)
changed_bbox = diff.getbbox()
assert changed_bbox is None
```

A more useful helper would count changed pixels, allow `max_diff_pixels`, and save a red-overlay diff image on failure.

Rasterizer choices:

| Rasterizer | Pros | Cons |
| --- | --- | --- |
| CairoSVG | Python API and CLI, built for SVG to PNG, integrates with Pillow for embedded images | LGPLv3; native Cairo/libffi dependencies; output may vary with installed fonts |
| Headless Chromium via Playwright | Strong browser SVG rendering, easy PNG screenshot capture, can use JS visual-diff tooling | Heavy dependency; browser install in CI; indirect for a terminal app |
| `rsvg-convert` / librsvg | Common system CLI, good SVG renderer | System package dependency, less Python-native |

Pros:

- Produces real pixel comparisons.
- Keeps ACE boot/navigation in-process.
- Uses SASE's existing Pillow dependency for the comparison step.
- Can layer on top of either official Textual snapshots or SASE-owned SVG fixtures.

Cons:

- Adds renderer dependency and font-control questions.
- Pixel goldens are larger and harder to review than SVG goldens.
- Rasterizing Textual SVG tests Textual's render model plus the SVG renderer, not an actual terminal emulator.

Best fit: second milestone for critical layouts where "one character moved" or color regressions matter.

## Option D: `pytest-regressions` Image Fixture

`pytest-regressions` has an `image_regression` fixture that accepts image bytes or a Pillow image and compares it to a
stored reference with a percentage diff threshold.

How it could fit:

```python
async def test_ace_initial_layout_png(image_regression):
    async with AcePage(size=(120, 40)) as page:
        png = render_svg_to_png_bytes(page.app.export_screenshot())
    image_regression.check(png, diff_threshold=0.0)
```

Pros:

- Avoids writing SASE's own baseline/update mechanics for image files.
- Supports thresholded comparisons.
- Accepts Pillow images directly.

Cons:

- Still requires separate SVG rasterization.
- Its baseline layout/update ergonomics may not match SASE's existing test organization.
- It is general-purpose, not Textual-aware.

Best fit: if SASE wants true image baselines without inventing a PNG comparison fixture.

## Option E: In-Process VT Emulator With `pyte`

[`pyte`](https://github.com/selectel/pyte) is a pure-Python, in-memory VT100/VT220 terminal emulator. It accepts a
stream of bytes/escape sequences (the same ones Textual writes to stdout) and exposes a 2D grid of `Char` cells with
attributes (fg, bg, bold, reverse, underline). It is what most "scrape a TUI without a real PTY" projects use and sits
between Option A (Textual's own render model) and Option F (a real terminal emulator).

Two ways it could plug into SASE:

1. **Drive Textual's renderer through pyte.** Wire Textual's output stream into a `pyte.Screen` + `pyte.ByteStream`,
   run the app via `Pilot`, and snapshot the resulting grid as text-with-attributes (or as an in-house "ANSI grid"
   serialization). This catches escape-sequence bugs that the SVG screenshot bypasses, while still being deterministic
   and font-free.
2. **Render the pyte grid to PNG.** Use Pillow with a single bundled monospace font (e.g. DejaVu Sans Mono shipped in
   the test extras) to draw each cell. This produces a PNG without depending on a real terminal, browser, or Cairo.

Pros:

- No native deps beyond pure Python.
- Captures actual ANSI byte stream, so it tests Textual's compositor and color/attribute output, not just its SVG
  exporter.
- `pyte.HistoryScreen` supports scrollback, useful for log-heavy panels.
- Deterministic: no real PTY, no fonts (in mode 1), no GPU.

Cons:

- pyte's VT support is broad but not exhaustive; some less-common Textual sequences may render slightly differently
  than a real emulator.
- Mode 2 still has font-determinism considerations, just narrower than Option F.
- One more abstraction to maintain on top of Textual's already-tested `Pilot` machinery.

Best fit: a useful middle layer when SASE wants more "real terminal" coverage than SVG but doesn't want a PTY-bound
suite. Could become a dedicated assertion type in `AcePage`, e.g. `page.assert_cell(row, col, char="X", bold=True)`.

## Option F: Browser-Based Screenshot And Pixelmatch

Playwright's JavaScript test runner has first-class screenshot comparison via `toHaveScreenshot()` and uses
`pixelmatch` under the hood. Playwright Python can capture screenshots, including screenshot bytes, but its Python docs
focus on capture rather than the same built-in visual assertion API.

For SASE, the browser path would likely mean:

- render the Textual SVG in a local HTML page and screenshot it with Chromium; or
- expose ACE through a Textual web surface and screenshot the browser page.

Pros:

- Mature screenshot/reporting ecosystem.
- Pixelmatch thresholds and diff artifacts are well understood.
- Browser SVG rendering is consistent in a pinned Chromium environment.

Cons:

- Heavy for a Python TUI project.
- Adds Node or Playwright browser management to a test suite that does not otherwise need it.
- Still does not test terminal-emulator pixels unless a terminal is rendered inside the browser.

A lighter sibling of this option is to drop Playwright and use the [`pixelmatch`](https://pypi.org/project/pixelmatch/)
Python port (a direct port of Mapbox's JS library, which is what Playwright's `toHaveScreenshot()` uses under the hood)
plus Pillow. That gives the same pixel-comparison algorithm — anti-aliasing-aware, configurable threshold, diff PNG
output — without booting a browser. It composes well with Option C (rasterize Textual SVG, then run pixelmatch).
`pixelmatch-fast` provides a Numba-accelerated variant if comparison speed matters.

Best fit: not recommended for the first SASE implementation. Consider only if SASE later has a browser-rendered ACE
surface or wants richer HTML visual-diff reports than Python fixtures provide. Use the standalone `pixelmatch` PyPI
package if you only want its diff algorithm, not the browser.

## Option G: PTY Or Real Terminal Capture

Tools in this family launch the TUI in a pseudo-terminal or terminal emulator, drive keyboard input, and capture either
the terminal buffer or a raster screenshot. The notable concrete options here:

- **Microsoft `tui-test`** (<https://github.com/microsoft/tui-test>) — a Playwright-style E2E framework written in
  TypeScript, specifically for CLI/TUI apps. It runs each test in an isolated worker with its own terminal context,
  exposes a Playwright-like assertion API including `toMatchSnapshot()` for terminal screenshots, color and visibility
  assertions, and ships a tracing/replay system. It is cross-platform (Windows/macOS/Linux) and currently the closest
  thing to a "Playwright for terminals". Cost: Node toolchain in CI, TypeScript test code separate from SASE's pytest
  suite.
- **Charm `vhs`** (<https://github.com/charmbracelet/vhs>) — a Go tool that runs a `.tape` script (deterministic
  keystroke timeline) inside a headless terminal and emits GIF/MP4/PNG/`.txt`/`.ascii` artifacts. The `Screenshot`
  tape command captures a single PNG; `.txt`/`.ascii` outputs are well-suited to golden-file integration testing
  because the exact same tape produces byte-identical text output across runs. VHS is also useful purely as a
  documentation generator for ACE (animated demos in the docs).
- **`asciinema` + `agg`** — record an interactive ACE session into a `.cast` file with `asciinema rec`, then convert
  to GIF or PNG with `agg`. Lower-fidelity than VHS for golden testing but higher fidelity for human review and
  debugging artifacts.
- **Generic PTY automation** — `pexpect`/`ptyprocess` to spawn `sase ace`, send keystrokes, and capture stdout, then
  feed into `pyte` (Option E) for a rendered grid. This is what SASE would build if it wanted "real subprocess, real
  terminal sequences, no real terminal emulator."

Pros:

- Closest to "what a user sees in a terminal".
- Can catch bugs caused by terminal control sequences, alternate-screen behavior, or terminal integration.
- Works for non-Textual TUIs too.

Cons:

- Much higher flake risk because fonts, dimensions, antialiasing, terminal theme, and OS rendering all matter.
- Loses direct access to Textual widget state unless paired with a test-only backchannel.
- Slower and harder to debug in CI.
- More process cleanup and timeout handling.

Best fit: a small optional integration suite, marked `slow` or run in a dedicated CI job with a pinned container image.
It should not replace Textual-native snapshots for ACE layout regression coverage.

## Image Comparison Algorithms

Once SASE has PNGs to compare, the choice of comparison algorithm matters as much as the choice of renderer:

| Algorithm | What it catches | What it misses | Best for |
| --- | --- | --- | --- |
| Exact pixel diff (`ImageChops.difference`, `getbbox()`) | Any single-pixel change | Nothing — too strict for AA/font drift | SVG-rasterized goldens with a frozen renderer and font |
| `pixelmatch` (anti-aliasing-aware) | Layout/color changes, ignores common AA noise | Subtle font hinting differences if threshold tuned loose | Cross-platform PNG goldens; matches Playwright's algorithm |
| SSIM (`scikit-image.metrics.structural_similarity`) | Structural shifts, layout drift | Color-only or single-pixel changes | "Did the layout move?" rather than "does it match exactly?" |
| Perceptual hash (`imagehash`) | Gross structural changes | Color, fine layout, text content | Fast pre-filter to skip pages that obviously did not change |

The SASE-recommended starting point is exact pixel diff for SVG-rasterized goldens (Option C) and `pixelmatch` for any
goldens captured from a real terminal or browser (Options F/G). SSIM and pHash are useful as secondary signals on top
of those, not as the primary gate.

## Font And Environment Determinism

Font rendering is the single biggest source of flake in pixel tests. SVG-only tests (Option A/B) avoid this entirely.
Any path that produces a PNG (Options C, E mode 2, F, G) needs explicit font control:

- Pin one font that ships with the test extras, e.g. DejaVu Sans Mono. Do not rely on the system font cache.
- For CairoSVG, set `fonts-conf` / `FONTCONFIG_PATH` to a directory holding only the pinned font, and disable
  fontconfig caches in CI.
- For Playwright/Chromium, mount a font directory and disable subpixel rendering (`--disable-lcd-text`) for
  deterministic AA.
- For VHS, use `Set FontFamily "DejaVu Sans Mono"` and `Set FontSize` in every tape; pin VHS version in CI.
- Run pixel tests in a single Linux container image (e.g. a slim Debian with the pinned font installed). Do not gate
  on macOS/Windows pixels.
- Lock locale (`LC_ALL=C.UTF-8`) and `TERM` so terminfo capability lookup does not vary.

Even with all of this, pixel goldens should allow a small `max_diff_pixels` budget to absorb the remaining noise.

## Determinism Requirements

Regardless of option, visual tests need strict control over inputs:

- fixed `run_test(size=(width, height))`;
- `refresh_interval=0`;
- `auto_start_axe=False`;
- deterministic changespec and agent fixtures;
- notifications disabled unless the test is specifically about notifications;
- fixed Textual theme and CSS;
- animations disabled or settled with `pilot.pause()`;
- no wall-clock strings, durations, process IDs, temp paths, random names, or live artifact scans in visual goldens;
- stable font and rasterizer in CI for PNG tests.

Pixel tests should start narrow. Prefer one snapshot per intentionally visual surface, not a giant snapshot for every
TUI state. Good first cases:

- initial changespec list layout;
- focused/selected row styling;
- query edit modal;
- command palette modal;
- agent list with representative statuses;
- image/attachment preview surface if the test can use fixed local fixtures.

## Suggested SASE Implementation Shape

### Milestone 1: SVG Snapshot Helper

Add an `AcePage` visual helper:

```python
class AcePage:
    def export_svg(self, *, title: str | None = None) -> str:
        return self.app.export_screenshot(title=title, simplify=True)
```

Then choose either:

- add `pytest-textual-snapshot` to dev dependencies and use `snap_compare`, or
- add a SASE fixture such as `ace_visual.assert_svg(page, name)`.

Given SASE already has a custom `AcePage` fixture layer and deterministic changespec patching, a SASE-owned fixture is
slightly more work but likely a better long-term fit. The official plugin is still the fastest way to prove value.

### Milestone 2: PNG Pixel Diff

Add an optional visual extra, for example:

```toml
[project.optional-dependencies]
visual = [
    "cairosvg",
    "pytest-regressions",
]
```

Then provide:

- `render_textual_svg_to_png(svg: str) -> bytes`;
- `assert_png_matches(name, png_bytes, max_diff_pixels=0, max_diff_ratio=0.0)`;
- failure artifacts under pytest's temp/output directory: expected PNG, actual PNG, diff PNG, and the source SVG.

Keep this outside the default fast test path at first, possibly behind a `visual` marker.

### Milestone 3: Optional Real-Terminal Smoke

If SASE needs terminal-emulator fidelity, create a separate slow test job that pins:

- OS/container image;
- terminal emulator or PTY stack;
- font package;
- terminal size;
- theme;
- locale;
- Textual version.

Use it for a few smoke screenshots, not as the main visual regression mechanism.

## Prior Art In Textual-Based Projects

Concrete patterns worth borrowing from real Textual apps already in production:

- **Textual itself** uses `pytest-textual-snapshot` in `tests/snapshot_tests/test_snapshots.py` to gate every release.
  This is the reference implementation for the official plugin.
- **Harlequin** (terminal SQL IDE) uses an `app_snapshot` fixture that drives the app via `Pilot` and supports multiple
  assertions per test. Failures emit a `snapshot_report.html` with side-by-side before/after and a "Show Difference"
  toggle. Worth replicating in any SASE-owned fixture.
- **Posting** (terminal HTTP client) and **Dolphie** (MySQL TUI) both rely on `pytest-textual-snapshot` with SVG
  goldens checked in next to tests. These are good references for what a "real" snapshot tree looks like at scale and
  for review-PR ergonomics.
- The Textual blog ("A year of building for the terminal") describes the rationale for SVG snapshots over plain-text
  capture, which is useful framing when justifying the approach internally.

## Recommended File Layout

One possible structure:

```text
tests/ace/tui/visual/
  test_ace_visual_snapshots.py
  snapshots/
    ace_initial.svg
    ace_query_modal.svg
    ace_agent_list.svg
  snapshots_png/
    ace_initial.png
    ace_query_modal.png
```

If PNGs are generated from SVG goldens, consider committing only SVGs initially and producing PNG diff artifacts on
failure. Commit PNG goldens only for tests that explicitly need pixel thresholds.

Storage notes:

- A typical Textual SVG screenshot at 120x40 is ~30-80 KB. Several hundred SVG goldens stay well under 50 MB total —
  comfortable for plain git, no LFS needed.
- A 120x40 PNG rasterized from that SVG is typically 20-60 KB. Pixel goldens for the same set of surfaces are still
  manageable in plain git unless every interactive state gets a snapshot.
- Once the snapshot tree exceeds ~100 MB or PNG diffs dominate PR sizes, switch the `snapshots_png/` tree to git LFS
  rather than letting binary churn balloon the repo.
- Avoid checking in MP4/GIF artifacts from VHS or asciinema; those are documentation, not test fixtures, and belong in
  a separate path or generated on demand.

## Update Workflow

Visual snapshot updates should be explicit and reviewable:

1. Run visual tests normally and inspect failure artifacts.
2. Confirm the current rendering is intentional.
3. Re-run with an update flag, such as `pytest --snapshot-update` for the official plugin or
   `pytest --sase-update-visual-snapshots` for a SASE fixture.
4. Review SVG/PNG changes in the PR as test data, not incidental churn.

Do not update visual snapshots as part of `just fmt` or default `just check`.

## Open Questions

- Should SASE prefer the official `pytest-textual-snapshot` plugin for speed of adoption, or a small SASE fixture for
  tighter update/reporting control?
- Should PNG tests be committed immediately, or should SASE begin with SVG snapshots and generate PNG diff artifacts only
  on failure?
- Which CI environment should own pixel baselines if local developer environments differ?
- Are visual tests intended to gate every PR, or should they run only for TUI-tagged paths or a separate `visual` marker?

## Sources

- Textual testing guide: <https://textual.textualize.io/guide/testing/>
- Textual `App` API (`run_test`, `export_screenshot`, `save_screenshot`):
  <https://textual.textualize.io/api/app/>
- Textual upstream snapshot tests:
  <https://github.com/Textualize/textual/blob/main/tests/snapshot_tests/test_snapshots.py>
- `pytest-textual-snapshot` PyPI page: <https://pypi.org/project/pytest-textual-snapshot/>
- `pytest-textual-snapshot` GitHub README: <https://github.com/Textualize/pytest-textual-snapshot>
- `syrupy` (the snapshot framework `pytest-textual-snapshot` builds on): <https://github.com/syrupy-project/syrupy>
- `inline-snapshot`: <https://github.com/15r10nk/inline-snapshot>
- `pyte` VT100 terminal emulator: <https://github.com/selectel/pyte>
- CairoSVG documentation: <https://cairosvg.org/documentation/index.html>
- Playwright visual comparisons: <https://playwright.dev/docs/next/test-snapshots>
- Playwright Python screenshots: <https://playwright.dev/python/docs/screenshots>
- `pixelmatch` Python port: <https://pypi.org/project/pixelmatch/> and
  <https://github.com/whtsky/pixelmatch-py>
- `pixelmatch-fast` (Numba-accelerated): <https://pypi.org/project/pixelmatch-fast/>
- `pytest-regressions` image fixture API:
  <https://pytest-regressions.readthedocs.io/en/latest/api.html#image-regression>
- Microsoft `tui-test`: <https://github.com/microsoft/tui-test>
- Charm `vhs` (terminal recordings + screenshots from `.tape` scripts):
  <https://github.com/charmbracelet/vhs>
- Asciinema recording format and tooling: <https://docs.asciinema.org/>
- Harlequin testing discussion (`app_snapshot` fixture, `snapshot_report.html`):
  <https://github.com/tconbeer/harlequin/discussions/551>
- Textual blog "A year of building for the terminal" (rationale for SVG snapshots):
  <https://textual.textualize.io/blog/2022/12/20/a-year-of-building-for-the-terminal/>
- Waleed Khan, "Testing terminal user interface apps":
  <https://blog.waleedkhan.name/testing-tui-apps/>
- Max Rossmannek, "Testing TUI applications in Python":
  <https://mrossinek.gitlab.io/programming/testing-tui-applications-in-python/>
- Related SASE research: `sdd/research/202605/tui_agent_screenshot_automation.md`
- Earlier SASE TUI E2E research: `sdd/research/202604/tui_e2e_testing.md`
