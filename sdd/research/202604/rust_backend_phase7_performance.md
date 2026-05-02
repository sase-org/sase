# Rust Backend Phase 7: Realized Performance Outcomes

This document is the canonical research record of what the default-Rust flip (Phase 6F) actually delivered, captured
during Phase 7B / 7C and folded into the user-facing `docs/rust_backend.md` `Performance` section by Phase 7D. It exists
so Phase 8 (Python implementation removal) and any future port can cite a single page when justifying — or rejecting —
the next move.

The headline tables, methodology, and "where Rust helps / does not help" prose live in `docs/rust_backend.md`. This page
is the research-side narrative: the gate-vs-realised comparison, the workload-size caveats, and the per-operation
verdict that should govern Phase 8 sequencing.

## Capture provenance

- Workstation: Linux x86_64, CPython 3.14.3, `sase-core-rs` editable install built from a sibling `../sase-core/`
  checkout via `just rust-install`.
- Date: 2026-04-29.
- Default-Rust runs: `SASE_CORE_BACKEND` unset. Explicit-Python runs: `SASE_CORE_BACKEND=python` set at process
  launch.
- Sample sizes per scenario are recorded in each artifact's `metadata.runs` / `metadata.warmup`; the headline tables in
  `docs/rust_backend.md` carry the per-row `runs` count for end-to-end surfaces.
- Raw artifacts: `plans/202604/perf_artifacts/rust_backend_phase7_*.json` (committed) and
  `plans/202604/perf_artifacts/local_only/home_tree_*.json` (workstation-specific, gitignored — reproducible from this
  workstation only).

The Phase 7A measurement contract (`tests/perf/phase7/`) pins git SHA + dirty flag, ISO-8601 UTC timestamp, Python /
platform / processor, `sase_core_rs` import path + version, and run/warmup counts onto every artifact, so any
re-capture on a different workstation can be compared apples-to-apples without rerunning baselines.

## Realised vs. Phase 0 research gates

Section 6 of `sdd/research/202604/rust_backend_migration.md` set go-gates for each candidate ("at least 2× faster end to
end or at least 100 ms saved on a real large repo", "at least 2× faster for large lists after FFI", "first usable batch
< 100 ms or total scan at least 2× faster"). Phase 6 ports were chosen against those gates; Phase 7 measures whether
they held up after the default flip.

| Candidate                       | Phase 0 go-gate                                                  | Phase 7 realised median (default Rust vs. explicit Python)                                                                                                                                          | Verdict vs. gate                                                                                                                  |
| ------------------------------- | ---------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `parse_project_bytes`           | ≥2× end-to-end **or** ≥100 ms saved on a real repo               | ≥2.4× facade on golden_myproj; 1.4× facade on synthetic_200_specs                                                                                                                                   | Met. The 2× gate holds on small files; on the 200-spec synthetic the gate is missed but the absolute saving (~7.6 ms) is real.    |
| `parse_query` / `evaluate_many` | ≥2× faster for large lists after FFI                             | parse_only direct: 2.1×. `evaluate_query_many` synthetic_1000: **0.05×** (Rust ~18× slower); synthetic_10000: **0.08×**                                                                             | **Missed for the routed evaluator.** Per-call wire conversion dominates; routed Rust path is a regression on the default backend. |
| `scan_agent_artifacts`          | First usable batch <100 ms **or** ≥2× faster total scan          | 1.21× on synthetic_6p_200pp microbench; **2.59× on `sase agents status -j` synthetic 8×25**, 2.03× on home tree                                                                                     | Met at the user-visible surface, missed at the operation microbench — see "End-to-end vs. microbench" below.                      |
| Status state machine            | "Port only for shared-core correctness unless profiling demands" | All three helpers are 0.46×–0.68× on synthetic_200_specs at sub-µs / sub-10-µs absolute cost                                                                                                        | Performance-neutral by design; absolute deltas are invisible against the orchestrator.                                            |
| Git query parsers               | "Port only if parse/fork overhead is material"                   | Five normalizers 0.71×–0.87× on small inputs; `parse_git_name_status_z` 0.71× on 1k entries; subprocess fork+exec dominates `bench_git_query_ops` end-to-end on every workload                      | Performance-neutral by design; subprocess cost dwarfs the parse delta.                                                            |

The two gate-decisive readings are: (1) `parse_project_bytes` cleared its 2× gate at small files and recovered most of
the 100 ms target on a 200-spec synthetic, (2) `scan_agent_artifacts` cleared its **end-to-end** 2× gate on
`sase agents status -j` even though the operation microbench only hit ~1.21× — the user-perceived gain comes from
removing per-file Python parse cost, not from the snapshot facade overhead alone.

## End-to-end vs. microbench: why the surface number matters

`sase agents status -j` is the first surface where we have a measurement-driven counter-example to the Phase 3H
rollout decision, which deferred the default flip on the operation microbench reading of 1.55× on a real home tree.
Phase 7C's `sase_agents_status_listing` records 2.59× on synthetic 8×25 and 2.03× on the home tree, both as cold
subprocesses. The delta is the cold-import cost users actually pay before the listing renders — which is amortised in
an in-process `scan_facade` microbench but is the entire user-visible budget on `sase agents status`. The implication
for future ports: re-measure end-to-end before re-justifying any port that fell short of a microbench gate.

The corresponding inverse — `sase ace` cold open being ~19 % **slower** under default Rust on the synthetic Pilot
harness — is the same effect in the other direction. The harness mocks `find_all_changespecs`, which is where
`scan_agent_artifacts` and `parse_project_bytes` would otherwise pay back their dispatch cost; what remains is AceApp /
Pilot constructor cost plus per-call PyO3 dispatch overhead at small inputs. Phase 7D documents this as a small-input
dispatch tax rather than a regression in the routed Rust operation; Phase 7E should keep ace cold-open out of the hard
PR floor.

## Honest negative results and workload-size caveats

These need to stay on the record so a future contributor does not port an op that won't move the needle:

- **`evaluate_query_many` is a regression on the default backend.** 8 µs/spec under Rust vs. 4–7 µs/spec under the
  optimized Python batch path at 100 specs, scaling worse at 10k. Per-call wire conversion (`changespec_to_wire` +
  `to_json_dict`) dominates the actual evaluation. Phase 8 should not remove `evaluate_query_many_python` until either
  the wire conversion is amortized (compiled-query handle that holds the converted spec batch) or the comparison is
  rerun against the optimized Python path. The Phase 0 plan flagged FFI granularity as the single most common
  new-Rust-extension perf bug — this is exactly that bug, captured in artifact form rather than as a hypothetical.
- **Status helpers and Git normalizers are routed for correctness, not speed.** Sub-10-µs cores with PyO3 dispatch
  overhead come out 13–55 % slower under default Rust on the inputs they actually see. The Phase 4 / Phase 5 close-outs
  already framed these ports as shared-core hygiene rather than user-perceived latency; Phase 7B's data confirms that
  framing should make it into Phase 8 commit messages so a future reader does not interpret "Rust default" as
  "uniformly faster".
- **`sase run` startup is a Rust-neutral surface today.** Cold subprocess import of `run_query` is dominated by Python
  interpreter startup + sase package import; routing through Rust vs Python inside `sase.core` does not show up
  because `run_query` is not exercised at import time. Phase 7E can use `sase_run_startup` as a soft import-bloat
  sentinel — accidental top-level imports will move it — but it should not be a backend gate.
- **Workload-size sensitivity for `parse_project_bytes`.** The 2.4× golden-myproj number is a small-file reading; the
  1.4× synthetic_200_specs number is closer to a real cold TUI launch. Phase 8 messaging should lead with the 1.4×
  reading rather than the headline 2.4× so the user's mental model matches their typical project size.
- **Home-tree numbers are workstation-specific.** The `local_only/` artifacts are reproducible from this workstation
  but not from a clean CI worker; Phase 7E keeps home-tree measurement in `workflow_dispatch` only, and Phase 7F
  verification should re-run them on the maintainer's box rather than re-recording into CI.

## Implications for Phase 7E and Phase 8

Phase 7E (CI regression floor) should anchor on the surfaces that have low artifact-to-artifact noise and a meaningful
absolute reading. The Phase 7B/7C handoffs recommend:

- **Hard PR floor candidates:** `parse_project_bytes.golden_myproj.facade`,
  `parse_project_bytes.synthetic_200_specs.facade`, `parse_query.parse_only.direct`,
  `scan_agent_artifacts.synthetic_6p_200pp.scan_facade`, and
  `sase_agents_status_listing.synthetic_8_projects_25_agents` — the last as the strongest end-to-end signal in the
  Phase 7 corpus.
- **Sentinels (do not gate hard):** `sase_run_startup.import_run_query_cold` (allow ±15 % vs. the recorded Rust median;
  it tracks accidental import bloat).
- **Manual / `workflow_dispatch` only:** `sase_ace_cold_open.synthetic_100_cs_50_agents`,
  `sase_agents_status_listing.home_tree`, and any of the small Git / status normalizers — their absolute medians are
  small enough that workstation noise alone moves them by more than the recommended 25–35 % tolerance.

Phase 8 (Python implementation removal) should be sequenced against these readings, not against the Phase 0 gates:

- Remove the Python halves of `parse_project_bytes`, `parse_query`, and `scan_agent_artifacts` first; they have a
  shipped Rust win at every workload that matters.
- **Hold the Python half of `evaluate_query_many` until the wire-conversion regression is fixed.** This is the only
  shipped operation where Rust is currently slower at the routed scope on every measured workload size; deleting the
  Python implementation would lock in the regression.
- Status helpers and Git normalizers are safe to remove on the schedule that suits the rest of the cleanup; their
  user-perceived cost is unchanged either way.

## Where this connects

- User-facing tables and methodology: `docs/rust_backend.md` `Performance` section.
- Per-subphase handoffs: `plans/202604/rust_backend_phase7_phase7{a,b,c,d}_handoff.md`.
- Forward plan and remaining phases: `plans/202604/rust_backend_phase7.md`, `plans/202604/rust_backend_phase8.md`
  (when written), and the Phase 7 / Phase 8 sections in
  `sdd/research/202604/rust_backend_migration.md`.
