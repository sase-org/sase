---
create_time: 2026-05-12 10:51:02
status: done
prompt: sdd/prompts/202605/phase7_agent_scan_perf_failure.md
---
# Phase 7 Agent Scan Perf Failure Plan

## Context

GitHub Actions is failing `just phase7-perf-check` on one anchor:

`scan_agent_artifacts.synthetic_6p_200pp.scan_facade`

The reported CI median is `174449.33us`, above the stored absolute ceiling of `167984.20us`. The ceiling is derived from
the historical Phase 7B Rust median `119988.71us` multiplied by the global slowdown factor `1.40`.

This anchor no longer has a live Python comparison (`must_beat_python=false`), so the failure is strictly an absolute
historical floor failure. Local focused measurement after rebuilding `sase_core_rs` shows the same anchor can still pass
on this machine at roughly `156ms` median, but its upper samples are already near or above the stored ceiling. Recent
history shows `pending_question.json` support was added to the agent scan wire and Rust scanner after the original Phase
7 baseline, expanding the default scan result shape and adding work to the facade path.

## Diagnosis Plan

1. Reproduce the failing surface locally with the same Phase 7E agent-scan configuration: six projects, 200 artifacts
   per project, 25% workflow markers, eight measured runs, and two warmups.

2. Break down the current cost using the existing benchmark rows: `scan_rust_to_dict`, `scan_rust_dict_to_wire`, and
   `scan_rust_facade`. This separates Rust filesystem/JSON/PyO3 cost from Python wire hydration.

3. Compare the failure against recent agent-scan changes, especially `pending_question.json` support in both `sase-core`
   and the Python wire. The key question is whether the floor is catching a real unintended regression or an intentional
   wire-shape expansion whose baseline was never refreshed.

4. Inspect whether the scanner has low-risk waste on the hot path, such as duplicate sorting or avoidable per-artifact
   filesystem checks. Prefer an implementation fix over loosening the floor when the extra work is not behaviorally
   required.

## Implementation Plan

1. If a small scanner optimization is available, make it in `../sase-core` and keep the Python facade contract
   unchanged. Add or update Rust-side parity tests only when behavior could change.

2. If the cost is confirmed to be intentional and no safe optimization brings the median comfortably below the ceiling,
   update `tests/perf/baselines/phase7_regression_floor.json` with a narrowly scoped per-anchor slowdown override or
   refreshed baseline rationale for `scan_agent_artifacts.synthetic_6p_200pp.scan_facade`. Do not change the global
   `1.40x` factor.

3. Avoid deleting or weakening the anchor. It still protects the default full-facade scan used by user-facing agent
   loading.

4. Keep generated perf reports out of committed source unless they are already intended artifacts.

## Verification Plan

1. Rebuild the editable Rust binding with `just install` after any Rust changes.

2. Run the focused agent-scan benchmark to verify the failing anchor:
   `.venv/bin/python - <<'PY' ... _bench_agent_scan(...) ... PY`

3. Run `just phase7-perf-check` to verify the full CI floor.

4. Run `just check` before finishing because this repo's short-term memory requires it after source changes.
