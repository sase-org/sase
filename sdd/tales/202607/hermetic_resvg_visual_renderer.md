---
create_time: 2026-07-03 14:39:00
status: wip
prompt: sdd/prompts/202607/hermetic_resvg_visual_renderer.md
---
# Unify Visual Snapshot Rendering Across CI and Local Machines (Hermetic resvg Renderer)

## Problem

The ACE PNG snapshot suite renders Textual SVG exports to PNG via `cairosvg` → the **host's** cairo/pango/fontconfig
libraries (`tests/ace/tui/visual/png_diff.py::render_svg_to_png`). Only the font-resolution layer is pinned (a hermetic
`FONTCONFIG_FILE` pointing at the bundled Fira Code), and on macOS not even that — Quartz-backed cairo silently ignores
fontconfig. The consequences are structural, not incidental:

1. **Goldens are CI-canonical only.** macOS hosts can neither reproduce the committed goldens (~112/133 visual tests
   fail locally with font-fallback drift) nor regenerate them (the font-pin guard added by
   `fix_models_panel_visual_goldens` deliberately refuses). Golden updates from a Mac require the documented CI-artifact
   adoption ritual (push → wait for CI → `gh run download` → copy `actual.png` files).
2. **Even CI needs drift tolerances.** `ubuntu-latest`'s apt cairo/pango drift over time, so the suite carries a layered
   tolerance stack: per-test `BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03` kwargs in ~30 test modules, an implicit 1%
   GitHub-Actions default in `png_diff.py`, and a `SASE_VISUAL_PNG_MAX_DIFF_RATIO=0.001` broad-lane default set by
   `tools/run_pytest` for `just test` / `just test-cov`. Every tolerance is regression-detection surface given away.
3. **`just check` is degraded on macOS.** The visual portion of the default test lane mass-fails for environmental
   reasons, training people to ignore it.

The fix is to pin the **entire rasterizer**, not just the fonts: replace cairosvg with resvg — a pure-Rust SVG renderer
(rustybuzz text shaping + tiny-skia rasterization) that carries its own font database and touches no platform text or
graphics stack. Then every machine produces byte-identical PNGs, goldens become regenerable anywhere, exact pixel
equality becomes the norm everywhere, and the entire compensation machinery (hermetic fontconfig, font-pin guard,
CI-artifact adoption workflow, tolerance stack, CI apt font install) can be deleted.

## Verified Feasibility (spike results, not speculation)

A spike was run against `resvg_py==0.3.3` (PyPI bindings for resvg) in a throwaway venv, rendering a **real** Textual
SVG export from the suite's failure artifacts with `skip_system_fonts=True` and
`font_dirs=[tests/ace/tui/visual/fonts]`:

- **API fits exactly.**
  `resvg_py.svg_to_bytes(svg_string=..., skip_system_fonts=True, font_dirs=[...], font_family=..., monospace_family=..., sans_serif_family=..., serif_family=...)`
  → PNG bytes. Generic-family overrides let every family (including the `font-family: arial` title style Textual emits)
  resolve to bundled Fira Code with zero system-font participation.
- **Textual's SVG dialect renders faithfully.** The export uses class-based CSS in a `<style>` block, `textLength` (~447
  uses per screen), and `clip-path` (~448 uses) — all handled. The spike render of a full Config Center screen produced
  correct Fira Code monospace, continuous box-drawing borders, correct `→` arrows, correct colors, and correct bold, at
  exactly the golden's dimensions (1482×1026 RGBA).
- **Glyph coverage is at parity with today's CI goldens.** The spike render shows tofu `□` at exactly the same three
  glyph positions as the committed CI-canonical golden (symbols missing from both Fira Code and CI's DejaVu fallback).
  No fidelity regression vs. the current corpus.
- **Deterministic.** Back-to-back renders are byte-identical (sha256-equal).
- **Style probe results.** Bold (FiraCode-Bold selected for weight 700), `text-decoration: underline` and `line-through`
  (used 17× / 7× in the corpus) all render correctly. One accepted fidelity change: `font-style: italic` (72 uses in the
  corpus) renders **upright** — Fira Code ships no italic face and resvg does not synthesize oblique the way
  fontconfig/cairo does. This is uniform across all screens and all machines; see Out of Scope for the follow-up option.
- **Wheel coverage.** `resvg_py 0.3.3` ships wheels for macOS arm64/x86_64 (cp311+), manylinux x86_64/aarch64,
  musllinux, and Windows; requires Python ≥3.10. The repo pins Python 3.12 — covered on every host class we care about.

The one property a single machine cannot prove is **cross-platform** byte-identity (macOS arm64 vs. CI's Linux x86_64).
Confidence is high — resvg's upstream test suite asserts pixel-exact renders across OSes — but the rollout below gates
on a PR CI run before anything merges, so the claim is verified empirically before it can affect master.

## Design

### Step 1 — Swap the renderer in `render_svg_to_png`

`tests/ace/tui/visual/png_diff.py::render_svg_to_png` becomes a call to `resvg_py.svg_to_bytes` with:

- `svg_string=svg`
- `skip_system_fonts=True` — nothing outside the repo participates in rendering
- `font_dirs=[str(<visual tests dir>/fonts)]` — the bundled FiraCode-Regular/Bold
- `font_family="Fira Code"` plus `monospace_family` / `sans_serif_family` / `serif_family` all set to `"Fira Code"`

Wrap the result in `bytes(...)` (defensive against the binding returning a byte list). Keep the lazy import and the
actionable `RuntimeError` for a missing `[visual]` extra, with updated wording.

Packaging:

- `pyproject.toml` `[project.optional-dependencies].visual`: replace `cairosvg>=2.7,<3` with `resvg_py==0.3.3` (**exact
  pin** — the renderer version _defines_ the golden corpus; any bump is an intentional regeneration event).
- Add `resvg_py` to the mypy ignore-missing-imports override list if the binding ships no type stubs.
- `tools/validate_dependency_group` picks the new requirement up automatically from pyproject; `just _setup-visual`,
  `just install-visual`, and CI need no dependency-side changes.

### Step 2 — Delete the non-hermetic-renderer compensation machinery

With rendering hermetic, all of the following exists only to cope with the old renderer and is removed:

- **Hermetic fontconfig**: the `_hermetic_fontconfig` session fixture and the `FONTCONFIG_FILE` monkeypatch in
  `tests/ace/tui/visual/conftest.py` (the rest of `_force_color_for_visual_snapshots` — NO_COLOR, PID pin — stays).
- **Font-pin guard**: `tests/ace/tui/visual/_font_pin_guard.py`, its unit test
  `tests/ace/tui/visual/test_font_pin_guard.py`, and the `_visual_snapshot_update_guard` fixture wiring in `conftest.py`
  / `ace_png_visual`. (This supersedes the guard half of `fix_models_panel_visual_goldens` — expected; that change made
  the corpus safe, this one removes the asymmetry it guarded.)
- **CI font install**: the "Pin visual renderer fonts" `apt-get install fonts-dejavu-core` step in
  `.github/workflows/ci.yml`'s `visual-test` job.
- **The tolerance stack** — exact pixel equality becomes the default everywhere:
  - Delete the per-test `BROAD_SCREENSHOT_MAX_DIFF_RATIO` constants and every `max_diff_ratio=...` kwarg that uses them
    (~30 test modules plus the shared `_ace_agents_png_snapshot_helpers.py` and
    `_ace_config_center_png_snapshot_helpers.py` definitions). Mechanical sweep.
  - `png_diff.py`: delete `GITHUB_ACTIONS_MAX_DIFF_RATIO` and `_running_in_github_actions_workflow()`; the resolver
    falls through to exact equality (0 pixels / 0.0 ratio) unless explicitly overridden.
  - `tools/run_pytest`: delete `BROAD_TEST_VISUAL_PNG_MAX_DIFF_RATIO` and the fast/cov-lane
    `SASE_VISUAL_PNG_MAX_DIFF_RATIO=0.001` default (update its test in `tests/test_run_pytest_tool.py`).
  - **Keep** the `max_diff_pixels`/`max_diff_ratio` kwargs and the `SASE_VISUAL_PNG_MAX_DIFF_RATIO` env override as an
    explicit, documented triage escape hatch (e.g. assessing drift scale during a future renderer bump). They are inert
    by default and already unit-tested.
- **Unit-test updates in `test_png_diff.py`**: the real-render test switches `pytest.importorskip("cairosvg")` →
  `"resvg_py"`; tests asserting the GitHub-Actions implicit tolerance are removed/adjusted to assert exact-by-default.

### Step 3 — Regenerate the golden corpus (117 PNGs) locally

Now possible on any machine — which is the point:

1. `just test-visual -- --sase-update-visual-snapshots` regenerates all goldens through resvg.
2. `just test-visual` immediately after must pass **with exact equality** (0 changed pixels) on the local host.
3. Run the suite a second time (fresh processes) to confirm run-to-run byte-stability of the new corpus.
4. **Corpus review before committing**: spot-check a representative sample of regenerated goldens against their
   predecessors — the Models panel trio, an italic-heavy screen, screens with emoji/symbol badges, an axe screen, and a
   couple of modals. Expected differences: antialiasing/hinting character, upright italics, cleaner box-drawing joins.
   Content (text, layout, colors, glyph coverage) must be identical; any _content_ difference is a stop signal.
5. Golden count must remain exactly 117 (regeneration overwrites in place; no orphans, no additions).

### Step 4 — Documentation and memory-comment updates

- **`docs/development.md` "Visual Snapshot Workflow"**: rewrite the middle of the section. Goldens are now canonical to
  the pinned resvg version, byte-identical on every host; regeneration is a local one-liner on any machine; exact pixel
  equality applies in every lane (local, broad `just test`, CI). Delete the font-pin/guard prose, the CI-artifact
  adoption workflow, and the tolerance-gating explanation. Document: the renderer pin (`resvg_py==0.3.3`) and that
  bumping it is a deliberate regenerate-and-review event; the env-var escape hatch for triage; the upright-italic
  caveat. The Visual Failure Report subsection stays as-is.
- **`tests/ace/tui/visual/fonts/README.md`**: update the rendering-stack description (cairosvg/fontconfig → resvg
  fontdb; `skip_system_fonts` means only this directory participates).
- **Memory files** (explicit approval requested via this plan, since agent instructions forbid unapproved memory edits):
  `memory/build_and_run.md` and its generated mirrors (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `QWEN.md`, `OPENCODE.md`)
  contain the comment "(cairosvg/Pillow auto-installed via `_setup-visual`)" — update to name resvg instead. Same
  one-line change in each file.

## Tests

- The visual suite itself is the primary test: 133 tests / 117 goldens at exact equality, twice locally (determinism),
  then on CI (cross-platform identity).
- `test_png_diff.py` keeps unit coverage of the diff/tolerance/artifact logic, updated for exact-by-default and the
  resvg import; the real-render smoke test now exercises resvg end-to-end.
- `test_run_pytest_tool.py` updated for the removed broad-lane tolerance default.
- Deleted: `test_font_pin_guard.py` (guard no longer exists).

## Validation and Rollout

1. `just install` then `just check` locally. For the first time on this macOS host class, the visual suite must
   genuinely pass — that local green (at exact equality) is itself a headline acceptance criterion.
2. **Cross-platform gate — validate on a PR before merge.** `ci.yml` runs `visual-test` on `pull_request`, so open this
   change as a PR and require the visual job green there (Linux x86_64 rendering vs. macOS-arm64-generated goldens,
   exact equality) before it reaches master. This empirically proves cross-platform byte-identity — the one spike-
   unverifiable claim — with zero risk to master.
3. If (unexpectedly) the PR run shows drift: the failure report gives per-test changed-pixel ratios. Fallback ladder, in
   order: (a) if drift is a genuine resvg platform bug, file upstream and temporarily keep a minimal CI-only ratio
   tolerance while goldens stay locally-regenerable; (b) worst case, regenerate goldens from the CI run's artifacts —
   never worse than today's status quo, and still renderer-version-pinned.
4. After merge: watch the master CI run green.

## Explicitly Out of Scope

- **True italics.** Fira Code has no italic face, so italic styling flattens to upright (uniformly, everywhere).
  Restoring visible italics would mean switching the bundled family (e.g. JetBrains Mono, which ships real italics) — a
  full-corpus cosmetic change best taken as its own follow-up if italic regression-sensitivity matters.
- **Bundling a symbol-fallback font (e.g. DejaVu).** The spike showed glyph-coverage parity with today's goldens
  (identical tofu positions). Revisit only if the Step 3 corpus review surfaces a screen where coverage regresses.
- **Rust-core changes.** This is test-only rendering infrastructure in this repo; the shared-backend boundary rule does
  not apply. No linked-repo changes.
- **Historical documents.** `sdd/` tales/research files that describe the cairosvg era remain untouched as records.
- **The `pillow` main dependency** — still used for PNG comparison and diff-image generation; unaffected.

## Risk Summary

- **Cross-platform render divergence** (x86 vs. ARM float/AA paths): low likelihood (resvg's upstream corpus is
  cross-platform pixel-exact); fully de-risked by the PR CI gate before merge, with a defined fallback ladder.
- **resvg SVG-text edge cases on unspiked screens**: regeneration exercises all 133 screens; any parse/render failure or
  content anomaly surfaces during Step 3's exact-equality double-run and corpus review, before commit.
- **Binding maintenance risk** (`resvg_py` is a third-party wrapper): mitigated by the exact version pin and by the fact
  that regeneration is now cheap — swapping to another resvg binding or a CLI later is a contained change.
- **Corpus churn**: a one-time ~117-file binary diff. Reviewable via the Step 3 sampling procedure; expected and
  intentional.
- **Reduced italic sensitivity**: italic-vs-regular regressions become invisible to the corpus until the follow-up font
  decision; accepted and documented.
