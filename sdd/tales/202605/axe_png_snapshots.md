---
create_time: 2026-05-11 18:31:40
status: done
prompt: sdd/prompts/202605/axe_png_snapshots.md
---
# Plan — Expand AXE Tab PNG Snapshot Coverage

## Goal

Add a small, focused set of PNG snapshot tests to `tests/ace/tui/visual/test_ace_png_snapshots.py` that meaningfully
extend the existing AXE tab coverage. Each new snapshot should exercise a distinct visual state that the current two AXE
snapshots do not.

## Context

The AXE tab currently has two PNG snapshots:

1. `axe_selected_row_120x40.png` — bgcmd-only fixture, second bgcmd row selected, info panel rendering bgcmd details for
   that row.
2. `axe_lumberjack_tree_120x40.png` — 2 lumberjacks (`hooks` running with `fast_lint` + `slow_typecheck`; `checks`
   stopped with `smoke`), one chop success + one chop failure, one bgcmd row. Default row selection is index 0
   (`hooks`), so this snapshot also implicitly captures the info panel rendering for a selected **lumberjack**.

Together these two existing snapshots already cover:

- Lumberjack-row info panel content (via the default `hooks` selection in the tree snapshot).
- Bgcmd-row info panel content (via the bgcmd selected-row snapshot).
- Chop tree expansion with mixed success/failure chop runs.

That means the originally proposed snapshots **D (info panel on lumberjack)** and **E (info panel on bgcmd)** are
redundant with existing coverage and are dropped from this plan.

The remaining gaps worth filling are:

- **Empty AXE state** — no lumberjacks, no bgcmds. No current snapshot exercises the empty-state placeholder.
- **AXE process running with status/metrics/output** — `axe_running=True` + populated `axe_status`/`axe_metrics`/
  `axe_output` is not exercised by either existing snapshot, so the `AxeDashboard` widget's rendered content is entirely
  uncovered.
- **Info panel on a chop run** — selecting a chop row drives a different info panel renderer (`update_chop_status`) that
  shows the chop run's `output_tail`, exit code, and duration. This content is invisible in the current tree snapshot
  because the default selection is on a lumberjack row, not a chop row.
- **Errored lumberjack** — `LumberjackStatus.status="error"` with `errors_encountered > 0` exercises warning/red styling
  in both the tree row and the info panel that no current snapshot reaches.

## Verified facts

- AXE tree selection is moved with `j`/`k` via the Textual Pilot (`AcePage.press`); pressing `j` from the default
  index-0 selection walks down through visible rows (lumberjacks first, then expanded chops, then bgcmds).
- `AceApp._apply_axe_status_data` (in `src/sase/ace/tui/actions/axe_display/_loaders.py`) is the entry point that
  consumes an `AxeCollectedData` fixture: it sets `axe_running`, `_axe_status`, `_axe_metrics`, `_axe_output`, applies
  lumberjack/bgcmd/chop caches, rebuilds items, and refreshes the AXE display. The existing fixture pipeline already
  calls this via the patched `_run_axe_startup_init`, so populating these fields on `AxeCollectedData` is sufficient to
  drive the dashboard.
- `LumberjackStatus.status: Literal["running", "stopped", "error"]` (not `"errored"`).
- `ChopRunEntry.status: Literal["success", "failure", "timeout", "missing_script", "agent_launched"]`.
- Info panel routing (`src/sase/ace/tui/widgets/axe_info_panel.py`): `update_lumberjack_status`, `update_chop_status`,
  `update_bgcmd_status` — driven by the focused row in the underlying `BgCmdList`/tree widget.

## Non-goals

- No changes to the rendering pipeline, `png_diff.py`, or the visual test fixture.
- No new helpers outside `tests/ace/tui/visual/test_ace_png_snapshots.py`. Reuse `_axe_collected_data`,
  `_make_lumberjack_status`, `_make_chop_run`, `_patch_startup_loaders`, `_wait_for_startup`.
- No bead tracking — this is a small follow-up to the closed sase-2w epic and does not warrant a new bead.

## Scope of new tests

All new tests:

- live in `tests/ace/tui/visual/test_ace_png_snapshots.py`
- carry `pytestmark = pytest.mark.visual` via the existing module-level mark
- use the 120x40 grid (default)
- use deterministic timestamps (`2026-05-09T10:00:00` style), fixed pids, fixed durations
- reach the AXE tab via two `await page.press("tab")` calls after `_wait_for_startup(page)`
- emit a single PNG via `ace_png_visual.assert_page_png(page, name, title=...)`

### New snapshot 1 — `axe_empty_120x40.png`

**Test:** `test_axe_empty_png_snapshot`

**Fixture:** `_axe_collected_data()` with no kwargs (all collections empty, `axe_running=False`).

**Navigation:** Just switch to the AXE tab; no extra key presses.

**Why it's valuable:** The empty AXE state has no current coverage. Catches regressions in the placeholder / "nothing to
display" rendering and the unselected info panel.

### New snapshot 2 — `axe_running_dashboard_120x40.png`

**Test:** `test_axe_running_dashboard_png_snapshot`

**Fixture:** `_axe_lumberjack_tree_fixture()` extended (via a new small helper or inline) with:

- `axe_running=True`
- `axe_status`: a deterministic `AxeStatus`-shaped object (or the actual type from `sase.axe.state`) with fixed start
  time, pid, uptime, and any required scalar fields.
- `axe_metrics`: deterministic counters (cycles, lumberjacks_active, errors).
- `axe_output`: a short fixed multi-line tail (e.g. `"axe: cycle 12 ok\naxe: scheduling next cycle"`).

**Navigation:** Switch to the AXE tab; no extra key presses.

**Why it's valuable:** Exercises the `AxeDashboard` widget (status section + output section), which is entirely
unrendered in the two existing snapshots because both set `axe_running=False`.

**Note for implementation:** Before adding this test, the implementation step should briefly read
`src/sase/axe/state.py` to find the concrete dataclasses for `AxeStatus`/`AxeMetrics` (or the equivalent types that
`_axe_status` / `_axe_metrics` accept) and the dashboard widget at `src/sase/ace/tui/widgets/axe_dashboard.py` to
confirm which fields are rendered, so the fixture exercises the visible content. If `axe_status`/`axe_metrics` turn out
to require optional types this fixture can't easily construct, drop this snapshot rather than fabricating shapes.

### New snapshot 3 — `axe_chop_run_info_panel_120x40.png`

**Test:** `test_axe_chop_run_info_panel_png_snapshot`

**Fixture:** Reuse `_axe_lumberjack_tree_fixture()` unchanged. The `hooks/slow_typecheck` chop already has a
failure-status run with a deterministic `output_log` and `output_tail` — that's exactly the kind of detail worth
snapshotting.

**Navigation:** Switch to the AXE tab, then press `j` enough times to land on a specific chop row. The exact press count
depends on the rendered row order; the implementation step should:

1. Run the test once with `--sase-update-visual-snapshots` and a temporary assertion of `page.app.current_idx` (or
   equivalent) to learn the index of the target chop row (`hooks/slow_typecheck`).
2. Hard-code the resulting fixed number of `j` presses (or, preferably, walk forward until a state predicate matches —
   e.g. `await page.expect_state(<some chop-selection state>)` — if such a predicate exists; if not, a fixed `j` count
   is acceptable since the fixture is fully deterministic).
3. Add a single sanity assertion after navigation (e.g. `assert page.app.current_idx == EXPECTED`) so a later refactor
   that changes row ordering fails loudly instead of silently snapshotting the wrong row.

**Why it's valuable:** No current snapshot captures `update_chop_status` info-panel output. This exercises the chop-run
details renderer including `output_tail`, exit code, and duration — content important to users debugging a failed chop
run.

### New snapshot 4 — `axe_lumberjack_error_120x40.png`

**Test:** `test_axe_lumberjack_error_png_snapshot`

**Fixture:** A new small helper `_axe_lumberjack_error_fixture()` (in the same test file) that builds an
`AxeCollectedData` with a single lumberjack `hooks` whose:

- `status="error"` (using the verified `Literal` value)
- `errors_encountered=3`
- has one chop (`fast_lint`) with a single `ChopRunEntry` of `status="failure"` and `exit_code=1`
- `log_tail` is a short fixed error message, e.g. `"ERROR: hooks crashed at cycle 5"`

No bgcmds in this fixture, to keep the snapshot focused.

**Navigation:** Switch to the AXE tab; default selection (lumberjack `hooks`).

**Why it's valuable:** Catches regressions in error-state styling for both the lumberjack tree row and the lumberjack
info panel (the only existing "stopped" status in the tree snapshot doesn't exercise the error path).

## Implementation order

1. **Read** `src/sase/axe/state.py` for the exact shape of `LumberjackStatus`, `LumberjackMetrics`, `AxeStatus` (if
   present), `AxeMetrics` (if present), and the literal types referenced above. This is the only pre-implementation read
   still required; everything else has already been verified.
2. **Read** `src/sase/ace/tui/widgets/axe_dashboard.py` to confirm what `AxeDashboard` renders from `_axe_status` /
   `_axe_metrics` / `_axe_output`. If the data shapes are awkward to fabricate, drop snapshot 2.
3. **Add** `test_axe_empty_png_snapshot` (snapshot 1). Smallest change; verifies nothing else regressed.
4. **Add** `_axe_lumberjack_error_fixture` and `test_axe_lumberjack_error_png_snapshot` (snapshot 4).
5. **Add** `test_axe_chop_run_info_panel_png_snapshot` (snapshot 3), including the deterministic navigation sanity
   assertion described above.
6. **Add** `test_axe_running_dashboard_png_snapshot` (snapshot 2) — or drop it if step 2 revealed the data shapes are
   infeasible to fabricate.
7. **Generate goldens**:
   ```bash
   just install
   just test-visual -- --sase-update-visual-snapshots -k "axe_empty or axe_lumberjack_error or axe_chop_run_info_panel or axe_running_dashboard"
   ```
8. **Manual eyeball** — open each new PNG in `tests/ace/tui/visual/snapshots/png/` and visually confirm it captures the
   intended state (e.g. the empty-state snapshot really shows the empty-state, the error snapshot shows red/warning
   styling, the chop info panel shows `output_tail` and exit code, the dashboard shows status + output text). If a
   snapshot looks wrong, fix the fixture and re-generate before continuing.
9. **Verify deterministic re-runs**:
   ```bash
   just test-visual -- -k "axe_"
   ```
   Must pass byte-exact without `--sase-update-visual-snapshots`.
10. **`just check`** — must pass cleanly.
11. **Commit** — single commit with all new tests + their PNG goldens. Suggested message:
    `test(ace): expand AXE tab PNG snapshot coverage` with a one-line bullet per new snapshot in the body.

## Risk and rollback

Risk is low — only test files and new PNG assets are added; no production code changes. If any new snapshot is flaky
across machines (e.g. cairosvg/Pillow version drift, font rendering differences), the offending snapshot can be removed
without affecting the rest. The hermetic-fixture protections added in commit `1f22b9a4` already neutralize the known
sources of environment leakage.

## Out of scope / explicitly NOT doing

- Adding visual coverage for tabs other than AXE.
- Touching the SVG-to-PNG pipeline or diff strategy.
- Adding new helper modules outside the existing test file.
- Adding info-panel-on-lumberjack and info-panel-on-bgcmd snapshots (already covered by existing snapshots — proposals D
  and E in the brief).
- Creating a bead — this is a minor follow-up to the closed sase-2w epic.
