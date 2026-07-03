---
create_time: 2026-07-03 14:06:54
status: wip
prompt: sdd/prompts/202607/fix_models_panel_visual_goldens.md
---
# Fix the 3 Models-Panel PNG Snapshot Failures in CI (Corrupted macOS-Rendered Goldens)

## Problem

Every `master` CI run since `8b0ff2c9f` (`feat!: unify model alias config`) fails the `visual-test` job on exactly three
PNG snapshot tests, all in the Models panel:

- `tests/ace/tui/visual/test_ace_png_snapshots_models_panel.py::test_models_panel_default_png_snapshot` (13.00% changed
  pixels)
- `tests/ace/tui/visual/test_ace_png_snapshots_models_panel.py::test_models_panel_overrides_png_snapshot` (13.18%)
- `tests/ace/tui/visual/test_ace_png_snapshots_models_panel_edit.py::test_models_panel_edit_preview_png_snapshot`
  (10.82%)

All three exceed the explicit 3% CI renderer-drift tolerance (`BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03`). The other 130
visual tests pass in CI.

## Root Cause (verified, not speculative)

**The three committed goldens are corrupted renders; CI's "actual" output is correct.**

Evidence gathered:

1. **CI timeline pins the regression to the golden regeneration commit.** `3be27dbe7` (the parent of `8b0ff2c9f`) passed
   CI. `8b0ff2c9f` — the commit that regenerated exactly these three goldens — is the first failure, and every master CI
   run since fails with only these three visual tests (confirmed by downloading the `ace-visual-artifacts` bundle from
   the failed run for `80eb745fd`: it contains failure directories for exactly these three tests).

2. **The goldens were regenerated on a host that cannot produce canonical renders.** `8b0ff2c9f` was authored on
   `Kellys-MacBook-Pro.local` (per its `SASE_MACHINE` trailer). The visual suite pins rasterization by building a
   hermetic fontconfig (`tests/ace/tui/visual/conftest.py`: `_hermetic_fontconfig`, exported via `FONTCONFIG_FILE`) that
   resolves every family to the bundled Fira Code (`tests/ace/tui/visual/fonts/`). That pin works for the cairosvg →
   cairo → pango → fontconfig stack on Linux (CI installs `fonts-dejavu-core` and renders via fontconfig), but on macOS
   cairo resolves fonts through the Quartz/CoreText backend and **silently ignores `FONTCONFIG_FILE`**, falling back to
   system fonts.

3. **Visual inspection confirms glyph-level corruption, not a content change.** Side-by-side comparison of the committed
   goldens (`expected.png`) against CI's `actual.png` from the failure artifacts shows:
   - Goldens: body text in a proportional fallback font; box-drawing characters (modal borders, separators) and the `→`
     arrow (e.g. `implicit → @default`) rendered as tofu `□` squares.
   - CI actuals: proper monospaced Fira Code, continuous box-drawing lines, correct arrows.
   - Content is otherwise identical in both (same alias rows, kind badges, `PROVIDER(model)` badges, state column, and
     the post-`8b0ff2c9f` footer without the removed `d=Describe` hint). The intended UI change from `8b0ff2c9f` is
     present in both; only the rasterization differs.

4. **The golden corpus is CI-canonical.** 130/133 goldens pass in CI, while a full local run of the visual suite on a
   macOS host shows mass failures (~112) — macOS hosts cannot reproduce the goldens and must not regenerate them. Two
   different Macs do not even agree with each other (different system fallback fonts).

So: `8b0ff2c9f` legitimately changed the Models panel and correctly wanted new goldens, but the regeneration ran on a
host whose renderer ignores the font pin, committing fallback-font/tofu PNGs that differ from CI's correct render by
10–13%, blowing the 3% tolerance.

## Design

### Step 1 — Adopt CI's renders as the new goldens (the fix)

Download the `ace-visual-artifacts` artifact from the **newest completed failing master CI run** (e.g.
`gh run list --branch master --workflow CI` to pick it; `gh run download <run-id> --name ace-visual-artifacts`). Copy
each test's `actual.png` over the corresponding golden:

- `.../test_models_panel_default_png_snapshot/models_panel_default_120x40/actual.png` →
  `tests/ace/tui/visual/snapshots/png/models_panel_default_120x40.png`
- `.../test_models_panel_overrides_png_snapshot/models_panel_overrides_120x40/actual.png` →
  `tests/ace/tui/visual/snapshots/png/models_panel_overrides_120x40.png`
- `.../test_models_panel_edit_preview_png_snapshot/models_panel_edit_preview_120x40/actual.png` →
  `tests/ace/tui/visual/snapshots/png/models_panel_edit_preview_120x40.png`

Acceptance for this step:

- `sha256` of each committed golden equals the CI `actual.png` it was copied from.
- Visual inspection of each new golden confirms: Fira Code monospace rendering, continuous box-drawing borders, correct
  `→` glyphs, alias rows matching the pinned `AliasView` fixtures in the tests, and no `Describe` footer hint (i.e. the
  intended post-`8b0ff2c9f` content).

This is the same content the tests pin today, re-rasterized by the canonical renderer, so CI's diff becomes ~0% (any
residual run-to-run runner jitter is absorbed by the existing 3% tolerance, exactly as for the other 130 goldens). No
tolerance changes are needed or wanted.

### Step 2 — Guard `--sase-update-visual-snapshots` against font-pin-ignoring hosts (prevent recurrence)

This failure mode is silent and will recur the next time anyone regenerates goldens on macOS. Add a functional guard in
`tests/ace/tui/visual/conftest.py`, checked lazily (once per session) the first time a test would _write_ a golden
because `--sase-update-visual-snapshots` was passed:

- Rasterize a tiny probe SVG (a short string including a box-drawing glyph such as `─` and a letterform that is visually
  distinctive in Fira Code) through the same cairosvg path twice: once under the existing hermetic `fonts.conf`, and
  once under a second hermetic `fonts.conf` whose `<dir>` points at an **empty** directory.
- If the two rasterizations are byte-identical, the renderer is ignoring fontconfig (the macOS/Quartz case): fail the
  update attempt with an actionable error explaining that this host cannot produce canonical goldens and pointing at the
  documented CI-artifact adoption workflow (Step 3). Normal comparison runs (no update flag) are unaffected.
- If they differ, the pin is honored and updates proceed as today (Linux/CI-like hosts keep the existing workflow).

A functional probe is preferred over a `sys.platform == "darwin"` gate: it also catches misconfigured Linux hosts, and
automatically un-blocks macOS if a future cairo honors fontconfig there.

### Step 3 — Document the CI-canonical golden workflow

Update the "Visual Snapshot Workflow" section of `docs/development.md`:

- State explicitly that committed goldens are canonical to the CI (Linux/fontconfig) renderer.
- Scope the existing "local runs require exact pixel equality" guidance to hosts that honor the font pin, and note that
  hosts failing the new probe (macOS today) cannot regenerate or exactly reproduce goldens.
- Document the adoption workflow for such hosts: run the change through CI, then
  `gh run download <run-id> --name ace-visual-artifacts` and copy the relevant `actual.png` files over the goldens after
  inspecting them (this mirrors what this plan does in Step 1).
- Mention the new guard and its error message so the failure is discoverable.

## Tests

- **Guard unit test** (new, non-visual; no golden PNGs involved): exercise the probe decision logic — when the two probe
  renders are identical the update path raises the actionable error; when they differ, updates are permitted. Structure
  the probe as a small pure-ish helper (e.g. "render probe under config A and B, compare") so the decision can be tested
  by stubbing the two render results, without needing a real Quartz host in CI.
- **The three snapshot tests themselves** validate Step 1 in CI — they must pass on the CI run for this change.

## Validation

- `just install`, then `just check`. Lint/mypy/fmt must be clean. Note: on this macOS host the visual suite has known
  pre-existing environmental failures (the mass local drift described above, plus unrelated local XDG/LSP failures) —
  the pass/fail signal for the golden swap itself is CI, not the local run.
- Byte-level check: `sha256` of each new committed golden matches the CI artifact it came from.
- After the change lands on master: watch the CI run (`gh run watch` / `gh run list --branch master`) and confirm the
  `visual-test` job is green — the first green master CI since `8b0ff2c9f`. This is the authoritative validation.

## Explicitly Out of Scope

- Making macOS rasterization byte-match CI (Quartz vs fontconfig parity). The guard + docs make the limitation explicit
  and safe instead of chasing cross-platform pixel parity.
- The unrelated pre-existing local test failures on this host (XDG state root, missing xprompt LSP binary, axe
  orchestrator stops) — environmental, unaffected by this change.
- Any change to `png_diff.py` tolerances or the CI workflow's visual job — the 3% ratio tolerance is appropriate and the
  failure was golden corruption, not tolerance mis-tuning.
- The other ~130 goldens: they are already CI-canonical and passing; nothing to regenerate.

## Risk Summary

- Step 1 is test-data only (three PNG byte swaps) — zero runtime surface. Worst case is a residual >3% CI diff, which
  would only mean the artifacts were taken from a stale run; re-adopting from the newest failing run fixes it.
- Step 2 touches only the explicit `--sase-update-visual-snapshots` path in test fixtures; normal test runs and CI
  comparisons are untouched.
- Step 3 is documentation.
