# Phase 7D Handoff: Documentation And Research Narrative

Bead: `sase-1e.4`. Plan: `plans/202604/rust_backend_phase7.md`. Phase 7D folds the Phase 7B microbench summaries and the
Phase 7C end-to-end captures into a coherent user-facing performance story plus a research-side gate-vs-realised
record, so Phase 7E (CI regression floor) and Phase 7F (close-out) have a single citation point and Phase 8 (Python
implementation removal) has documented sequencing constraints.

## What landed

- `docs/rust_backend.md` — added a new top-level `Performance` section between `Benchmarking` and
  `Verifying The Backend`. The section covers:
  - workstation profile (Linux x86_64, CPython 3.14.3, sase_core_rs from `../sase-core/` editable build, `SASE_CORE_BACKEND` semantics);
  - core-operation median table (Phase 7B; one row per shipped operation, derived from the `*_summary.json` artifacts);
  - end-to-end TUI / CLI median table (Phase 7C; cold-subprocess `sase ace`, `sase agents status -j`, and `sase run`
    startup, each with per-row sample counts);
  - "Where Rust helps, where Rust does not help yet" prose covering the three wins
    (`scan_agent_artifacts` end-to-end, `parse_project_bytes`, `parse_query` direct) and the four honest negatives
    (`evaluate_query_many`, `sase ace` cold open, status / Git normalizers, `sase run` startup);
  - **Phase 7 support note** — the four-bullet checklist requested by the migration doc: confirm backend with
    `sase core health`, read `~/.sase/perf/core_dual_run.jsonl` via `parity-artifacts/`, recognise a
    `RustBackendUnavailableError` / health-exit-1 wheel-load failure, and use `SASE_CORE_BACKEND=python` as the
    Phase 7-only escape hatch.
- `docs/rust_backend.md` — updated the Roadmap entry for Phase 7 from `(open)` to `(in progress)` with a per-subphase
  status line so future readers see which subphases are still in flight.
- `sdd/research/202604/rust_backend_phase7_performance.md` — new research record. Captures the gate-vs-realised table for
  every Phase 0 measurement candidate, calls out the `evaluate_query_many` regression as a Phase 8 sequencing
  constraint, records the workload-size sensitivity for `parse_project_bytes`, and documents the implications for
  Phase 7E's anchor set.
- `sdd/research/202604/rust_backend_migration.md` — added a measurement-update bullet in the 2026-04-29 status block
  (linking the new performance research file and the headline outcomes) and a `Status (2026-04-29)` paragraph at the
  top of the Phase 7 section so the existing forward plan is read as "measurements taken" for 7A–7D and "still open"
  for 7E/7F.

Out of scope for Phase 7D and explicitly not done:

- No new artifacts under `plans/202604/perf_artifacts/`. Phase 7B/7C own the artifact production; Phase 7D consumes
  them.
- No CI integration / regression-floor wiring. Phase 7E owns the floor; the recommended anchor set is restated under
  "Implications for Phase 7E" in the new research file but is not codified here.
- No code changes under `src/sase/` or `tests/`. The new research file does not import any sase code; it is a
  documentation file.
- No edits to `Justfile`, `pyproject.toml`, `.github/workflows/`, or other infrastructure.

## How to read the new content together

`docs/rust_backend.md > Performance` is the user-facing answer to "what does default-Rust actually buy me, and what
should I expect when I run the same harnesses?" The tables there carry medians, sample counts, and a verdict for each
row. `sdd/research/202604/rust_backend_phase7_performance.md` is the research-side companion — same numbers, but framed
against the Phase 0 go-gates and with the per-operation Phase 8 sequencing implications spelled out. The migration doc
keeps its forward plan and now points at both.

## Headline outcomes (for quick citation)

These match what `docs/rust_backend.md` and the new research record agree on; they are the single source of truth for
any agent or PR that needs to cite a Phase 7 number:

- **Wins users feel.** `sase agents status -j` cold subprocess is **2.59×** faster on synthetic 8×25 (298.5 ms vs
  774.5 ms) and **2.03×** on this workstation's real home tree (885.8 ms vs 1799.7 ms; `local_only/` artifact).
  `parse_project_bytes` is 2.4× / 1.4× on golden_myproj / synthetic_200_specs. `parse_query` direct parse is 2.1× on
  the parse-only workload.
- **Routed regression.** `evaluate_query_many` is **0.05×–0.08×** under default Rust on synthetic 1k / 10k specs;
  per-call wire conversion dominates evaluation. Phase 8 sequencing **must hold the Python half** until this is
  amortised or the comparison is rerun against the optimized Python path.
- **Small-input dispatch tax (not a routed-op regression).** `sase ace` cold-open is 0.84× under default Rust on the
  synthetic 100×50 Pilot harness because the harness mocks `find_all_changespecs`; what remains is constructor / PyO3
  dispatch cost. The fix is fixture-shaped (exercise the scan/parse hot paths), not Rust-shaped.
- **Backend-neutral surface.** `sase run` startup is 1.01× — interpreter-startup-dominated; not a backend gate.
- **Status helpers and Git normalizers.** Routed for shared-core hygiene; 13–55 % slower at sub-10-µs absolute cost,
  invisible against the orchestrator / subprocess. Phase 4 / 5 close-outs already framed this; Phase 7D folds the
  framing into the user-facing `docs/rust_backend.md`.

## Sources used

- Phase 7A handoff: `plans/202604/rust_backend_phase7_phase7a_handoff.md` — locks the metadata schema.
- Phase 7B handoff: `plans/202604/rust_backend_phase7_phase7b_handoff.md` — full per-operation median table and
  per-operation verdicts. Phase 7D's core-ops table and "Where Rust helps / does not help" prose are derived from this
  document; nothing in the user-facing tables is freshly captured.
- Phase 7C handoff: `plans/202604/rust_backend_phase7_phase7c_handoff.md` — end-to-end medians, the
  `sase_run_startup` boundary rationale, and the home-tree `local_only/` policy. Phase 7D's e2e table and the
  small-input dispatch-tax framing for `sase ace` cold open are derived from this document.
- Plan: `plans/202604/rust_backend_phase7.md` (sections "Phase 7D" and "Verification Baseline For Every Agent").

No new measurements were taken; no benchmark file was edited. If a Phase 7E reader wants to re-derive any number in
this handoff, the artifact path is in the per-row metadata of every committed JSON under
`plans/202604/perf_artifacts/`.

## Verification commands run

- `just install` — workspace was newly cloned; the editable install ran clean against the existing `../sase-core/`
  checkout.
- `just check` — full repo check (fmt, lint, mypy, pyscripts, pyvision, fast tests). Result attached to the commit.

`just phase7-perf-check` was **not** rerun by Phase 7D — the Phase 7A handoff already pinned the helper smoke and
Phase 7D added zero code under `tests/`. Phase 7F should rerun the helper smoke as part of close-out.

## Open questions / nudges for later phases

- **Phase 7E (regression floor).** The recommended anchor set is restated in
  `sdd/research/202604/rust_backend_phase7_performance.md` under "Implications for Phase 7E and Phase 8":
  `parse_project_bytes.golden_myproj.facade`, `parse_project_bytes.synthetic_200_specs.facade`,
  `parse_query.parse_only.direct`, `scan_agent_artifacts.synthetic_6p_200pp.scan_facade`, and
  `sase_agents_status_listing.synthetic_8_projects_25_agents` for the hard PR floor;
  `sase_run_startup.import_run_query_cold` as a soft import-bloat sentinel; everything else (small Git / status
  normalizers, `sase_ace_cold_open`, `home_tree`) in `workflow_dispatch` only. Phase 7E should also decide whether
  `just phase7-perf-check` keeps wrapping the Phase 7A helper smoke or shells into the regression checker directly;
  Phase 7D did not change either path.
- **Phase 7F (close-out).** When 7F validates "all Phase 7 artifacts are committed and docs link to the actual file
  names", the new docs surface to walk is: `docs/rust_backend.md > Performance` → links into
  `plans/202604/perf_artifacts/rust_backend_phase7_*.json`; the new research record →
  `sdd/research/202604/rust_backend_phase7_performance.md`; and the migration doc's 2026-04-29 update bullet now references
  the performance research file. 7F should also re-run the home-tree `local_only/` artifacts on the maintainer's box
  and compare against the medians in the Phase 7C handoff rather than re-recording into CI.
- **Phase 8 (Python implementation removal).** The new research file is explicit on sequencing:
  `parse_project_bytes`, `parse_query`, and `scan_agent_artifacts` Python halves can be removed first;
  `evaluate_query_many_python` **must be held** until the wire-conversion regression is fixed (per-call
  `changespec_to_wire` + `to_json_dict` is the root cause); status helpers and Git normalizers are safe whenever the
  rest of the cleanup wants them. Phase 8 commit messages should lead with the user-perceived wins (the
  `sase agents status -j` 2.59× number) rather than uniformly "Rust everywhere is faster", which the Phase 7B
  microbench data does not support.
- **Future ports.** The `scan_agent_artifacts` end-to-end vs. microbench gap (2.59× user-visible vs. 1.21× microbench)
  is the strongest argument for re-measuring future ports against an end-to-end surface before deciding the gate is
  unmet. The Phase 3H rollout decision used the operation microbench reading; Phase 7C's data shows that reading was
  conservative.
