# Baseline — j/k key-to-paint latency (Phase 1, bead sase-u.1)

Plan: `sdd/plans/202604/instant_jk_navigation.md`. Phase-1 deliverable is the instrumentation + harness; the numbers
below are the reference point that phases 2-5 must beat (target: p95 < 16 ms on every tab in every scenario).

## How to reproduce

```bash
SASE_TUI_PERF=1 sase ace          # exercise live
pytest -s -m slow tests/ace/tui/bench_tui_jk.py
```

The TUI writes one JSON object per j/k action to `~/.sase/perf/tui_jk.jsonl` (override with `SASE_TUI_PERF_PATH`). The
bench runs Pilot scenarios end-to-end, redirects the JSONL to a tmp path, and prints a p50 / p95 / max table per
scenario.

## Baseline numbers (2026-04-26)

Captured on the bench harness above. `n` is the sample count over the run; `paint_ms` is `t_painted - t_keypress`.

| scenario                             |   n |  p50 |  p95 |   max |
| ------------------------------------ | --: | ---: | ---: | ----: |
| ChangeSpecs tab — `j` (next, 50 CLs) |  18 | 7.90 | 8.44 | 22.96 |
| ChangeSpecs tab — `k` (prev, 50 CLs) |  20 | 8.32 | 9.62 | 31.18 |
| Axe tab — `j` (idle daemon)          |  20 | 7.87 | 9.19 |  9.33 |

All values in ms.

## Coverage gaps to close in later phases

The plan calls out post-action scenarios (approve, kill, dismiss, ChangeSpec sync / accept-proposal) that the harness
does **not** yet drive end-to-end. Reasons + how each phase should backfill:

- **Agents tab post-action.** Agents-tab `j`/`k` go through `_navigate_agents_panel`, which depends on a populated
  `_panel_navigation_stops()` — i.e. real artifacts on disk. Phase 2, while moving `_approve.py`'s `agent_meta.json`
  write off the UI thread, should add a Pilot fixture that materializes a handful of agent artifact dirs under the
  redirected `~/.sase/agents/` and then scripts: `a` (approve) → `j × 20`. The instrumentation will already capture the
  samples; only the fixture is missing.
- **ChangeSpec accept-proposal / sync.** Same shape as above: needs a fixture that produces a CS with a proposal / sync
  target. Phase 4 (universal detail-panel debounce) is a natural place to add it because that phase is what makes those
  scenarios fast.
- **Axe with bgcmd items.** The current axe scenario fires `j` against an empty list, so `current_idx` never mutates and
  the watch hook never fires — the harness samples that path's _no-op_ dispatch only. Phase 3 (selective row updates)
  should seed a `BackgroundCommandInfo` list before pressing `j`.

These are **gaps in the bench**, not in the instrumentation. The `SASE_TUI_PERF=1` flag captures every `j`/`k`
regardless of scenario, so manual exercising of any flow today produces real numbers.

## Format of `tui_jk.jsonl`

One JSON object per line:

```json
{ "action": "next", "tab": "changespecs", "t_keypress": 12345.678, "model_ms": 0.42, "paint_ms": 7.91 }
```

- `action` — `"next"` (j) or `"prev"` (k).
- `tab` — current tab when the keystroke fired.
- `t_keypress` — `time.perf_counter()` at action-handler entry.
- `model_ms` — time from keypress until the in-memory `current_idx` setter ran.
- `paint_ms` — time from keypress until Textual's `call_after_refresh` callback fired (i.e. the next paint cycle).

Phases 2-5 should append their own numbers (with the date and the phase / commit) below the **Baseline** table so the
project carries a single rolling history.
