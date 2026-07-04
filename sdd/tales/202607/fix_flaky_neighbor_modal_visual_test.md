---
create_time: 2026-07-04 08:38:15
status: wip
prompt: sdd/prompts/202607/fix_flaky_neighbor_modal_visual_test.md
---
# Fix Flaky CI Visual Test: `test_agent_neighbor_modal_dismissed_descendant_png_snapshot`

## Problem

The `CI` workflow on `master` is failing. In the latest run (28705101382, commit `8abfb4139`), the `test (3.13)` job
failed at the "Run tests" step with:

```
FAILED tests/ace/tui/visual/test_ace_png_snapshots_agents_interactions.py::test_agent_neighbor_modal_dismissed_descendant_png_snapshot
  - AssertionError: wait_for() timed out after 5.0s — predicate never returned True
```

Evidence that this is a timing flake, not a regression:

- The failing commit (`8abfb4139`) only added files under `sdd/` (SDD prompt/plan) — no product or test code changed.
- In the very same CI run, the `test (3.14)` and `visual-test` jobs ran this test and passed.
- The test passed in the immediately preceding master run (`3c1cacb3e`).
- (The long streak of red master runs before `3c1cacb3e` was a _different_ visual test,
  `test_config_center_plugins_not_uv_tool_png_snapshot`, already fixed by `3c1cacb3e`. This plan addresses the new,
  unrelated flake.)

## Root Cause (confirmed by deterministic local reproduction)

The test (`tests/ace/tui/visual/test_ace_png_snapshots_agents_interactions.py:157`) does:

1. `press("shift+tab")` → switch to the Agents tab. This schedules the **agent-detail debouncer**
   (`DetailPanelDebouncer`, 0.15s delay) whose callback `_fire_debounced_detail_update` → `_apply_agent_footer_update`
   repaints the keybinding footer. That first footer update also schedules a **background artifact-discovery task**
   (`asyncio.to_thread` in `src/sase/ace/tui/actions/agents/_panel_artifacts.py`) whose completion callback calls
   `_refresh_agent_footer_bindings_only()` — a second footer repaint.
2. Injects dismissed-agent state directly into private app state (`_dismissed_agent_objects`, `_dismissed_agents`,
   `_dismiss_revive_epoch += 1`).
3. Opens the neighbor modal via `action_start_sibling_mode()`.
4. Polls the exported SVG (5s cap) until the footer shows `neighbors (2)` — the count that includes the injected
   dismissed descendant.

Nothing in step 2 or 3 repaints the footer. The `neighbors (2)` label can only appear if one of the two asynchronous
footer repaints from step 1 happens to land **after** the state injection:

- **Normal (passing) interleave:** the test reaches step 2 within a few event-loop ticks (both `expect_state` calls
  return without pausing), well inside the 0.15s debounce window. The debounced repaint then fires after the injection,
  recomputes the neighbor index (the epoch bump invalidated its cache in
  `src/sase/ace/tui/actions/agents/_neighbors.py`), and paints `neighbors (2)`.
- **Loaded-runner (failing) interleave:** on a slow, heavily parallel CI runner (the failing 3.13 job took 34 minutes),
  more than 0.15s of wall-clock time elapses inside `press("shift+tab")` / the surrounding pauses. Both the debounced
  repaint _and_ the artifact-discovery repaint fire **before** the injection, computing a neighbor count of 1
  (`neighbor` label). After that, no footer-repaint trigger remains, the footer stays stale forever, and the 5s
  `wait_for` times out.

The test's own comment acknowledges the count is "recomputed asynchronously" — but the recompute is only _triggered_ by
those two racy events, so the poll is not guaranteed to ever see the new value.

This was reproduced deterministically (no repo file changes; via a temporary pytest plugin passed with `-p`): pumping
the event loop for ~0.5s of real time right before the injection — simulating the loaded runner — makes the test fail
with the exact CI error every time.

Product code is not at fault: real dismiss/revive flows go through actions that both invalidate the neighbor-index cache
and refresh the display. Only this test mutates the private state directly, so it must trigger the footer repaint
itself.

## Fix

One-line test change in `tests/ace/tui/visual/test_ace_png_snapshots_agents_interactions.py`
(`test_agent_neighbor_modal_dismissed_descendant_png_snapshot`): after `await page.expect_modal("AgentNeighborModal")`,
deterministically repaint the footer:

```python
page.app._refresh_agent_footer_bindings_only()
```

- This recomputes the neighbor count (2, including the dismissed descendant) and updates the footer immediately.
  `App.query_one` in the pinned Textual (8.2.7) resolves against the _default screen_, so the footer widgets are found
  even while the modal is open.
- Idempotent against the racy repaints: whenever the debounced/discovery repaints fire (before or after), any
  post-injection repaint computes the same count of 2 and identical footer content (the fake agents have no artifacts,
  so `has_agent_artifacts` stays False), so the PNG snapshot is stable and the golden is unchanged.
- Keep the existing `wait_for("neighbors (2)")` poll as a cheap guard; it now succeeds on the first poll. Update the
  preceding comment to reflect the explicit refresh.

No golden regeneration, no product-code change, and no timeout tuning needed.

Verified locally with the slow-runner simulation applied: with the explicit refresh the test passes (including the PNG
golden comparison); without it, the simulation reproduces the exact CI timeout.

## Scope Check: Other Tests Using the Same Pattern

`_dismiss_revive_epoch` is mutated directly in only two other tests (`tests/ace/tui/test_agent_neighbor_navigation.py`,
`tests/ace/tui/test_agent_neighbor_index_cache.py`); both are unit tests on fake app objects that query the neighbor
index synchronously — no rendered footer, no race. No other visual test injects dismissed-agent state. This is the only
affected test.

## Steps

1. Edit `test_agent_neighbor_modal_dismissed_descendant_png_snapshot`: add
   `page.app._refresh_agent_footer_bindings_only()` after `expect_modal("AgentNeighborModal")` and adjust the comment
   above the `wait_for` to describe the deterministic refresh.
2. Run the test through the visual lane
   (`just test-visual tests/ace/tui/visual/test_ace_png_snapshots_agents_interactions.py`) — all tests in the file must
   pass with the unchanged goldens.
3. Re-verify determinism: run the single test with a temporary slow-runner simulation plugin (pump the event loop ~0.5s
   after the `agent_count` expectation via a `-p` plugin outside the repo) and confirm it passes; confirm the unfixed
   test fails under the same plugin.
4. Run `just check` before finishing.

## Risks

- Minimal: test-only change; calls an existing private refresh helper the app already uses for the same purpose
  (post-artifact-discovery footer repaints). If the helper is ever renamed, the test fails loudly at the call site.
