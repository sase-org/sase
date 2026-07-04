---
create_time: 2026-07-04 07:11:11
status: wip
prompt: sdd/prompts/202607/fix_visual_ci_not_uv_tool.md
---
# Fix master CI: deterministic `not_uv_tool` visual snapshot (unmocked `gh api` + stale golden)

## Problem

GitHub Actions has been red on `sase-org/sase` master. After commit `d638d9898` (regen rebased goldens + 1% CI drift
tolerance), exactly one test still fails in both the `visual-test` lane and the `test (3.14)` lane (via
`just test-cov`):

```
tests/ace/tui/visual/test_ace_png_snapshots_config_center_plugin_actions.py::
    test_config_center_plugins_not_uv_tool_png_snapshot
AssertionError: ACE PNG snapshot mismatch:
    tests/ace/tui/visual/snapshots/png/config_center_plugins_not_uv_tool_120x40.png
Changed pixels: 25787/1520532 (1.695920%); allowed: 1.000000% ($SASE_VISUAL_PNG_MAX_DIFF_RATIO)
```

The pixel count is byte-identical across runs and lanes, i.e. CI renders deterministically — the committed golden simply
shows different _content_ than what CI renders. This is not resvg anti-alias drift.

## Root cause (proven via the CI `ace-visual-artifacts` expected/actual/diff PNGs)

Two compounding content divergences between the golden and CI's render:

1. **Unmocked `gh api` subprocess in the test.** The sibling snapshot tests in the same file stub the plugin detail
   pane's incoming-commits fetch via the shared helper `_patch_plugins_catalog()` (which monkeypatches
   `pbp._fetch_incoming_commits` to a deterministic `IncomingCommits` value).
   `test_config_center_plugins_not_uv_tool_png_snapshot` instead hand-rolls its own
   `pbp._PluginsLoadResult(... uv_tool=_not_uv_tool() ...)` and only patches `_load_plugins_catalog` +
   `_collect_installed_core_versions` — so when the pane highlights the `github` row,
   `PluginsBrowserIncomingCommitsMixin` spawns a real worker that shells out to `gh api`:
   - On CI: `gh` fails instantly (exit 4, `GH_TOKEN` unset in Actions), and the pane renders
     `incoming commits unavailable ('gh api' failed (exit 4): gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN environment variable...)`
     — pushing the Installed/Latest/Repository rows down.
   - On the golden host: the real network call is slow, so the golden captured the transient
     `↑ checking incoming commits ...` loading state instead. The snapshot content therefore depends on the host's `gh`
     auth state and network timing — an environment-dependent, race-prone render.

2. **Stale golden w.r.t. the PID→version title change.** The golden header reads `sase ace (PID: 12345)`; the visual
   conftest now pins the title to `sase ace (v0.7.1)` (via `initial_app_version`/`resolved_app_version` patches added
   with the "show sase version instead of PID in the TUI title" feature). This golden was generated on the pre-rebase
   base and was the one golden _missed_ by the `d638d9898` regen sweep — locally the title-only diff (~0.2%) hides under
   the 1% tolerance band (and the gh-pane region matches because the local render also shows the loading state), so the
   test passes on the golden host while CI's combined diff (title + gh error pane) lands at 1.696% > 1%.

## Fix

All changes are test-only; no product code changes.

### 1. Make the test deterministic (primary fix)

In `tests/ace/tui/visual/test_ace_png_snapshots_config_center_plugin_actions.py`:

- Extend the shared helper `_patch_plugins_catalog()` in
  `tests/ace/tui/visual/_ace_config_center_png_snapshot_helpers.py` with an optional `uv_tool` passthrough parameter
  (defaults to `None`, matching the `PluginsLoadResult.uv_tool` dataclass default), forwarded into the
  `_PluginsLoadResult` it builds.
- Replace the failing test's hand-rolled `_PluginsLoadResult` + two `monkeypatch.setattr` calls with
  `_patch_plugins_catalog(monkeypatch, uv_tool=_not_uv_tool())`, so the test gets the exact same deterministic
  `_fetch_incoming_commits` stub as every sibling test.
- Before the snapshot assertion, add an explicit settle wait for the incoming-commits worker so the pane can never be
  captured in the transient "checking incoming commits..." state (e.g.
  `await page.wait_for(lambda _s: pane._incoming_commit_cache and not pane._incoming_commit_loading)` alongside the
  existing `_wait_for_plugins_detail`).

### 2. Regenerate the one affected golden

Regenerate `tests/ace/tui/visual/snapshots/png/config_center_plugins_not_uv_tool_120x40.png` on the golden host (the
same macOS machine that produced the other goldens):

```bash
just test-visual -- -k test_config_center_plugins_not_uv_tool_png_snapshot \
    --sase-update-visual-snapshots
```

Then visually inspect the new golden to confirm it shows:

- header title `sase ace (v0.7.1)` (pinned version, no PID),
- the deterministic stubbed incoming-commits section (not a loading spinner, not a `gh` error),
- the unchanged "install unavailable" banner content this test exists to cover.

No other goldens change (siblings already render the stubbed content).

### 3. Hardening: forbid real `gh`/network calls in all visual snapshots

Add an autouse fixture to `tests/ace/tui/visual/conftest.py` (same pattern as the existing `_stub_projects_loader` and
version-pinning fixtures) that patches `plugins_browser_pane._fetch_incoming_commits` to the deterministic visual stub
by default. Per-test `_patch_plugins_catalog()` calls still apply on top. This guarantees no future visual test can
silently depend on `gh` auth, network availability, or fetch timing — the class of bug that caused this incident.

## Verification

1. `just install` (fresh workspace), then run the fixed test _without_ the update flag — it must pass with exact pixel
   equality locally.
2. Run the full visual suite (`just test-visual`) to confirm no other golden is perturbed by the conftest hardening.
3. `just check` for lint/type/test gates.
4. After merge to master, confirm the `CI` workflow goes green (both `visual-test` and `test (3.x)` lanes) — CI renders
   the stubbed pane content identically since no subprocess/network is involved anymore, and the remaining cross-host
   delta returns to the sub-1% resvg anti-alias band.

## Explicit non-goals

- No change to the 1% `SASE_VISUAL_PNG_MAX_DIFF_RATIO` tolerance: raising it to paper over this failure would mask real
  regressions; the correct fix is removing the content-level nondeterminism.
- No change to the incoming-commits product code (`sase.updates.incoming_commits`, `plugins_browser_incoming.py`) — its
  CI-unavailable error rendering is correct behavior for real users without `gh` auth.
