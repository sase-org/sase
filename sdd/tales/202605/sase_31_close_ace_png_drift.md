---
create_time: 2026-05-12 00:22:52
status: done
prompt: sdd/prompts/202605/sase_31_close_ace_png_drift.md
---
# sase-31 Closure: Resolve ACE PNG Snapshot CI-vs-Local Render Drift

## Goal

Close the parent epic `sase-31` ("GitHub Actions Recovery Plan") by eliminating the only residual failure on `master`
CI: the 15 ACE PNG snapshot mismatches in `CI / visual-test` and `CI / test (3.14)`. Phases 1-5 are already verified
green on the latest master SHA; this plan is the missing closure work that the Phase 6 report flagged as a
recommended-but-unfiled follow-up.

The new work belongs to a single new child bead `sase-31.7` ("Phase 7: Eliminate ACE PNG Snapshot Render Drift") and
ends with `sase bead close sase-31`.

## Background

- Phase 4 bundled Fira Code 6.2 under `tests/ace/tui/visual/fonts/` and pinned `FONTCONFIG_FILE` in
  `tests/ace/tui/visual/conftest.py` so cairosvg/pango/fontconfig resolve `monospace` to Fira Code on every host. PNG
  goldens were regenerated from a developer machine against that hermetic font.
- On `master` SHA `6e79f32eef3c17539029357cb4a7997e8dffdb64`, CI nonetheless fails on all 15 ACE PNG snapshots with
  ~7,200-7,800 changed pixels per 120×40 capture (~0.49%) and ~7,758 changed pixels per 60×30 capture (~1.32%). The diff
  shape (constant per-glyph delta, identical layout/colors) matches FreeType/cairo sub-pixel anti-aliasing/LCD-filter
  drift between hosts, not a real UI regression.
- `just test-visual` passes locally on the current workspace (this dev host happens to match the host that regenerated
  goldens for Phase 4). The CI ubuntu-latest runner produces slightly different PNGs.
- The CI workflow `.github/workflows/ci.yml::visual-test` already uploads `.pytest_cache/sase-visual` as the
  `ace-visual-artifacts` artifact on failure. Each subdir contains the CI-rendered `actual.png` for one snapshot key.
- The artifact zip from run `25712696707` has been downloaded to `/tmp/sase31_artifacts/`; each
  `tests_ace_..._test_<name>_png_snapshot/<key>/actual.png` corresponds 1:1 with the committed golden at
  `tests/ace/tui/visual/snapshots/png/<key>.png`. All 15 golden keys are accounted for.

## Approach: Hybrid (Option A primary + Option C trim)

We adopt the **CI artifacts as the new goldens** (Option A from the Phase 6 report) AND **add a small absolute pixel
tolerance** to `tests/ace/tui/visual/png_diff.py` defaults (Option C from the Phase 6 report). Option B (pinning
FreeType/cairo/pango env) is rejected because it requires invasive per-host setup that we cannot fully verify ahead of
pushing.

Rationale:

- **Why CI as source of truth**: CI runs on a controlled, reproducible image and is the gate that blocks merges. Goldens
  regenerated from a CI run are guaranteed to make the gate green. The current state (goldens from one dev host) is
  fragile by construction — any dev whose cairo/pango/FreeType differs sees the same drift.
- **Why a tolerance trim on top**: Replacing goldens with CI artifacts will make the _current local_ host drift in the
  opposite direction (~7K px against the new goldens). The current default `max_diff_pixels=0, max_diff_ratio=0.0` would
  then fail locally even though the renders are visually identical. A small absolute+ratio tolerance absorbs sub-pixel
  hinting drift on developer machines and across future GitHub Actions image refreshes (minor FreeType version bumps)
  without weakening the contract enough to mask real regressions: a misplaced widget or wrong color changes tens of
  thousands of pixels in a localized region, well above the threshold.
- **Tolerance choice**: `max_diff_pixels=15000` and `max_diff_ratio=0.015` (1.5%). The 60×30 axe-empty case (586,500 px)
  sees ~7,758 changed; 1.5% of that is ~8,797, leaving ~13% safety headroom. On the 120×40 captures (1,520,532 px),
  15,000 px is ~0.99%, ~2× the observed 0.49% drift. Both bounds are far below the scale of any meaningful UI regression
  in these snapshots.

The change is **defaults-only** — individual `assert_page_png(...)` call sites do not pass overrides, so we do not need
to touch the 15 call sites in `tests/ace/tui/visual/test_ace_png_snapshots*.py`. The
`AcePngSnapshotFixture.assert_page_png` / `assert_png` signatures keep their existing `max_diff_pixels`/`max_diff_ratio`
keywords so future tests can still tighten on a per-snapshot basis.

## Scope (single phase `sase-31.7`)

### 1. Open the child bead

- `sase bead create --parent sase-31 --type phase --title "Phase 7: Eliminate ACE PNG Snapshot Render Drift"` (or the
  equivalent via the documented bead workflow). Description should reference this plan and the Phase 6 report's Option 1
  recommendation.

### 2. Adopt CI-rendered PNGs as goldens

- For each of the 15 subdirectories under `/tmp/sase31_artifacts/`, copy the inner `actual.png` over the matching
  committed golden under `tests/ace/tui/visual/snapshots/png/<key>.png`. Mapping rule: the parent subdir's first
  component matches `<key>.png`'s stem.
- Verify the file count is exactly 15 before and after, and that no goldens are added or removed (only overwritten).
- Do not modify `tests/ace/tui/visual/conftest.py` or `tests/ace/tui/visual/fonts/`. The bundled font and fontconfig
  pinning from Phase 4 are still required — they remove the worst-case (wrong-font-family) drift and we keep them.

### 3. Loosen `png_diff.py` defaults

- In `tests/ace/tui/visual/png_diff.py`:
  - Change `assert_page_png` default to `max_diff_pixels=15000, max_diff_ratio=0.015`.
  - Change `assert_png` default to `max_diff_pixels=15000, max_diff_ratio=0.015`.
  - Change top-level `assert_png_matches` default to `max_diff_pixels=15000, max_diff_ratio=0.015`.
- Update the inline docstring on `assert_page_png` to note that the defaults absorb sub-pixel rasterization drift across
  hosts and that callers should tighten via the kwargs for snapshots where pixel-exactness matters.
- No new module-level constants; per-call overrides remain the API for tightening.

### 4. Local validation (mandatory before push)

- `just install` (workspaces may have stale deps per `memory/short/workspaces.md`).
- `just test-visual` — must pass against the new goldens + new defaults. Expected outcome: ~7K-pixel drift on this host
  against the CI-rendered goldens, comfortably within the new 15K/1.5% bounds.
- `just lint` and `just check` — the only source change is `png_diff.py`; defaults change should not affect type
  checking or other suites.

### 5. Commit + push

- One commit on `master` (this repo's workflow is direct-to-master per recent commit history). Message must reference
  the new bead:
  `fix(ace/visual): adopt CI-rendered PNG goldens and absorb sub-pixel render drift (Phase 7 of sase-31) (sase-31.7)`.
- Body: explain that goldens were copied from CI run `25712696707` (SHA `6e79f32e`), and that defaults in `png_diff.py`
  were bumped to absorb sub-pixel anti-aliasing/hinting drift across hosts.
- `sase commit` per the standard sase commit workflow (no `git commit` direct, no `--no-verify`).

### 6. Live CI verification

- After push, use `tools/last_workflow_set_status` (the Phase 1 script) plus independent `gh` checks:
  - `just workflow-status --repo sase-org/sase --branch master --limit 10 --tail 80`
  - `gh run list --repo sase-org/sase --branch master --limit 5 --json databaseId,workflowName,status,conclusion,headSha`
  - `gh api repos/sase-org/sase/commits/<new-sha>/check-runs`
- Wait for the new `CI` and `Deploy Docs` workflow set on the pushed SHA to finish. Required outcome:
  `tools/last_workflow_set_status` reports `PASS`; `visual-test`, `test (3.12)`, `test (3.13)`, and `test (3.14)` are
  all `success`.
- If CI is red again with a _different_ failure shape, do not paper over it inside this phase — file a new follow-up
  bead.
- If CI is red again with the _same_ shape (still drifting), the renderer drift is larger than the chosen tolerance;
  reopen this phase and either (a) raise tolerance once more and re-push, or (b) escalate to Option B (containerized
  renderer).

### 7. Close `sase-31.7`

- Once CI is green, `sase bead close sase-31.7` with a short note containing the green SHA and the
  `tools/last_workflow_set_status` summary line.

### 8. Sweep for residual dead code

- `just pyvision` from the workspace root. The Phase 2 (`axe_dashboard.py` split into `_axe_dashboard_render.py`) and
  Phase 5 (test-file splits with new `_..._helpers.py` modules) refactors may have left unused private helpers behind
  that were previously allowed while sase-31 was open.
- If `just pyvision` reports new unused symbols, remove them in a small follow-up commit referencing `sase-31` (still
  child of the epic; the bead is still open at this point) before the final close.
- If `just pyvision` is clean, proceed.

### 9. Mark plan file done

- Edit the frontmatter of `sdd/epics/202605/github_actions_recovery.md`:
  - Change `status: wip` to `status: done`.
- Commit (still allowed while parent bead is open): `chore: mark github_actions_recovery plan done (sase-31)`.

### 10. Close `sase-31`

- `sase bead close sase-31` with a closure note that points to the Phase 6 report
  (`sdd/epics/202605/github_actions_recovery_phase6_report.md`) and this Phase 7 commit/SHA, summarizing that all six
  original phases shipped plus the Phase 7 drift fix, and that the latest master workflow set is green per
  `tools/last_workflow_set_status`.

## Validation Gates Recap

- `just install` clean.
- `just test-visual` passes locally against new CI-sourced goldens.
- `just check` passes.
- `just pylimit` still passes (no source files changed enough to regress it — only `png_diff.py` is touched in
  `src/`-adjacent code; this is under `tests/`, so unaffected by pylimit).
- `tools/last_workflow_set_status --repo sase-org/sase --branch master` reports `PASS` on the new SHA.
- `gh api repos/sase-org/sase/commits/<sha>/check-runs` shows no failed required check-runs.
- `just pyvision` reports no new unused symbols (or those have been removed).
- `sdd/epics/202605/github_actions_recovery.md` frontmatter has `status: done`.
- `sase bead show sase-31` shows `[CLOSED]`.

## Deliverables

- New child bead `sase-31.7` opened and closed.
- One main commit replacing 15 goldens and bumping `png_diff.py` tolerances (and optionally a small `just pyvision`
  cleanup commit).
- One frontmatter-only commit marking the plan done.
- Final close of `sase-31`.

## Out Of Scope

- Containerized renderer pinning (Option B from the Phase 6 report). If the chosen tolerance later proves insufficient
  (e.g. GitHub Actions image refresh moves FreeType more than 1.5% worth of pixels), that upgrade becomes a separate
  plan.
- Any source/UI changes to ACE TUI widgets — the snapshot diffs are confirmed sub-pixel-only.
- Any changes to the visual-test CI workflow itself — it already uploads artifacts and runs the right recipe.
- Modifying memory files (`memory/short/*`, `memory/long/*`) — requires explicit approval per AGENTS.md.
