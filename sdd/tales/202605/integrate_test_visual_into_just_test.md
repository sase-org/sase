---
create_time: 2026-05-11 12:08:50
status: done
prompt: sdd/prompts/202605/integrate_test_visual_into_just_test.md
---
# Plan: Integrate `test-visual` into `just test`

## Goal

Make `just test` run the PNG snapshot suite by default. Today the suite is gated behind a separate `just test-visual`
target, and all 8 of its snapshots are stale. Fix the snapshots first, then wire the target into `just test`.

## Current state

### How visual tests are excluded today

- `pyproject.toml` sets the global pytest default to `addopts = [..., "-m", "not slow and not visual"]`, so plain
  `pytest` and `tools/run_pytest fast` skip everything marked `visual`.
- `tools/run_pytest visual` overrides that with `-m visual` and is invoked by the `just test-visual` recipe
  (Justfile:170-172).
- `just test-visual` depends on `_setup-visual`, which installs the `.[dev,visual]` extras (cairosvg + Pillow). The
  default `_setup` does not.
- CI has a dedicated `visual-test` job in `.github/workflows/ci.yml:143-179` that runs `just test-visual`, installs
  `fonts-dejavu-core`, and uploads `.pytest_cache/sase-visual` artifacts on failure.

### What's broken right now

`just test-visual` reports **8 failed / 8 passed / 1 skipped**. All 8 failures live in
`tests/ace/tui/visual/test_ace_png_snapshots.py`. Diff sizes split into three buckets:

| Bucket           | Tests                                                                                   | Δ pixels |
| ---------------- | --------------------------------------------------------------------------------------- | -------- |
| Tiny (~0.27%)    | `changespec_initial`, `changespec_selected_row`, `query_edit_modal`, `axe_selected_row` | ~4,100   |
| Medium (~3.5–4%) | `agents_list`, `agents_selected_row`                                                    | ~53k–60k |
| Large (~93–94%)  | `agents_tab_unread_badge_off_tab`, `agents_tab_unread_badge_cleared_on_focus`           | ~1.42M   |

### Root causes (visual diff analysis)

1. **Notification badge fixture broken** — every snapshot's upper-right badge reads `3+0` instead of the mocked `1+18`
   that the conftest sets via `_fake_notification_snapshot`. The four "tiny" diffs are entirely accounted for by this
   single mis-mocked badge. Either the badge code no longer reads through
   `sase.notifications.read_notification_snapshot`, or the `NotificationCountsSnapshot` shape grew fields the
   `SimpleNamespace` mock doesn't provide.
2. **New "unread" column on the Agents tab** — header rolled `[1 failed · 2 done]` into
   `[1 failed · 2 unread · 1 done]`; group headers gained a `U<n>` token (e.g. `[F1 U1 D1]`); each agent row gained a
   `?` unread indicator next to its duration. Accounts for the medium-diff cluster.
3. **Detail-pane styling shift** — the two off-tab/cleared-badge snapshots show empty right-side panes with visible
   teal/green borders in the new output where the golden has dim/dark borders. The row-status coloring (FAILED red, DONE
   yellow) is also more saturated in the new render. Combined with cause #2 this drives the 93% pixel delta. Need to
   confirm this is intentional UI evolution and not a regression before refreshing the goldens.

## Approach

### Phase 1 — Repair the notification-badge mock

Grep for where the badge `N+M` text is rendered and confirm what API the live code reads. Update the conftest's
`_patch_startup_loaders` so the mocked counts actually flow through to the badge. This is the highest-leverage fix
because it removes the dominant diff source from 4/8 failures and likely contributes to the agents-tab pair as well.

### Phase 2 — Verify "large diff" deltas are intentional

For `agents_tab_unread_badge_off_tab` and `agents_tab_unread_badge_cleared_on_focus`, compare new vs old PNG
side-by-side. Spot-check that the colored borders + status colors match how the live TUI currently renders these screens
(manual `sase ace` smoke check is enough). If anything looks like a genuine regression (e.g. a pane that should be
hidden is suddenly visible), file/fix that before refreshing.

### Phase 3 — Regenerate the goldens

Run `just test-visual -- --sase-update-visual-snapshots` to overwrite all 8 PNGs under
`tests/ace/tui/visual/snapshots/png/`. Commit them as a refresh, separate from any code changes, so the diff is
self-documenting.

### Phase 4 — Validate

Re-run `just test-visual` once more with no flag to confirm clean.

### Phase 5 — Wire `test-visual` into `just test`

Pick one of these mechanisms (recommend A):

- **(A) Override the pytest marker filter in `tools/run_pytest`.** In `fast` mode pass `-m "not slow"` (drops the
  `not visual` clause from the pyproject default). Same for `cov`. Keeps `visual` mode unchanged. Make the `test` and
  `test-cov` recipes depend on `_setup-visual` instead of `_setup` so cairosvg/Pillow always install. This is one pytest
  run, so parallel scheduling and reporting stay unified.
- **(B) Two pytest invocations.** Keep `fast` mode as-is and have `just test` call both `tools/run_pytest fast` and
  `tools/run_pytest visual` in sequence. Simpler diff but doubles per-recipe boilerplate.
- **(C) Drop `not visual` from `pyproject.toml`'s default `addopts`.** Cleanest, but it also changes plain `pytest`
  invocations from editors/IDEs, which could surprise people who haven't installed the visual extra.

### Phase 6 — Decide CI strategy

Two viable options:

- **Keep the dedicated `visual-test` job** as-is, even though the main test job will also run visual tests. Pro: the
  dedicated job installs `fonts-dejavu-core` and uploads artifacts on failure. Con: visual tests run twice in CI.
- **Fold visual into the main test job.** Move the `fonts-dejavu-core` install and artifact-upload step into the
  existing `test` job and delete the `visual-test` job. Cleaner, but the test job becomes the single point of failure
  for visual regressions.

Recommendation: keep the dedicated job for now (zero risk to CI signal), and if local `just test` proves stable, drop it
in a follow-up.

### Phase 7 — Docs

Update `memory/short/build_and_run.md` so the `just test` line acknowledges visual snapshots, and mention that
`_setup-visual` will pull cairosvg automatically.

## Files to change

- `tests/ace/tui/visual/test_ace_png_snapshots.py` and/or `tests/ace/tui/visual/conftest.py`: fix the notification mock
  so the badge renders `1+18`.
- `tests/ace/tui/visual/snapshots/png/*.png` (all 8): regenerated via `--sase-update-visual-snapshots`.
- `tools/run_pytest`: in `fast` and `cov` modes, prepend `-m "not slow"` to override pyproject.
- `Justfile`: change the `test` and `test-cov` recipes' setup dependency from `_setup` to `_setup-visual`.
- `.github/workflows/ci.yml`: (optional) consolidate the `visual-test` job into the main `test` job if Phase 6 picks
  that option.
- `memory/short/build_and_run.md`: update the description for `just test`.

## Risks / open questions

1. Visual tests add ~24s and are platform-sensitive (font rendering, cairosvg version, GPU/text antialiasing
   differences). Including them in the default `just test` slightly raises the chance of "works on my machine" failures.
2. Auto-installing the visual extra on every `just test` adds a small dependency footprint to the default dev
   environment. Acceptable, but worth flagging.
3. Need confirmation that the colored detail-pane borders and brighter status text in the two large-diff snapshots are
   intended UI evolution before refreshing those goldens — otherwise the refresh would bake in a regression.
