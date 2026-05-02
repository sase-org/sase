# Migrating the SASE TUI Back End to Rust (Gradual, Multi-Frontend)

**Goal:** move the slow, non-UI logic underneath `sase ace` (the Textual TUI) into a
Rust core that can be shared with future SASE web and mobile front ends, without a
big-bang rewrite. The TUI keeps working at every step.

This research is grounded in the existing performance analyses
(`sase_perf_research.md`, `sase_perf_v2_research.md`,
`tui_profiling_strategies.md`) and a code map of the current Python modules.

**2026-04-29 update:** Phases 0–8 of this plan have shipped. Rust is the
only implementation of every shipped `sase.core` operation: there is no
`SASE_CORE_BACKEND` env var, no `sase.core.backend` dispatcher, no
`SASE_CORE_DUAL_RUN` parity logging, and no Python fallback for ported
operations. `sase-core-rs` is a hard runtime dependency of `sase` and ships
as a prebuilt PyPI wheel. The migration foundation, the per-operation Rust
ports (parser, query, agent scan, status state machine, Git query parsers),
the default-backend flip, the post-flip measurement pass, and the dispatcher
removal are all in place:

- `src/sase/core/` is the documented Python facade — wire records, the
  strict `sase.core.rust` Rust loader, golden-corpus tests. See
  `docs/rust_backend.md` for the user-facing surface.
- A sibling `../sase-core/` Cargo workspace ships `sase_core_rs` (PyO3 wheel
  built via `just rust-install` / `maturin develop --release` from
  `../sase-core/crates/sase_core_py/`).
- `parse_project_bytes` (Phase 1), `parse_query` (Phase 2),
  `scan_agent_artifacts` (Phase 3), the status helpers
  `read_status_from_lines` / `apply_status_update` / `plan_status_transition`
  (Phase 4), and the Git query parsers `parse_git_name_status_z` /
  `parse_git_branch_name` / `derive_git_workspace_name` /
  `parse_git_conflicted_files` / `parse_git_local_changes` (Phase 5) call
  `sase_core_rs` directly through the strict loader in
  :mod:`sase.core.rust`. Each has a Rust implementation in `sase-core`,
  golden-corpus tests under `tests/test_core_*`, and a Rust-side parity
  test in `../sase-core/.../tests/`. `evaluate_query_many` (Phase 2) was
  reclassified as deferred in Phase 8B and stays Python-only host logic
  (the prototype Rust path was 6-9× slower because PyO3 had to rebuild
  `ChangeSpecWire` from a fresh dict on every call).
- `find_named_agent`, `is_workflow_complete`, `list_running_agents`,
  `list_all_agents`, and the TUI Agents-tab refresh consume the agent-scan
  snapshot facade rather than walking project directories directly.
- `GitQueryOpsMixin` (`vcs_diff_name_status`, `vcs_get_branch_name`,
  `vcs_get_workspace_name`, `vcs_get_conflicted_files`,
  `vcs_has_local_changes`) consumes `sase.core.git_query_facade` for all
  parsing/normalization; subprocess invocation, timeouts, and mutating sync
  paths stay on Python by design.
- **Rust is the only backend.** Phase 6F flipped the default to Rust;
  Phase 8 deleted the `sase.core.backend` dispatcher, the
  `SASE_CORE_BACKEND` env var, and the Python halves of every ported
  operation. There is no escape hatch and no silent fallback — a missing
  or stale `sase_core_rs` raises `ImportError` / `AttributeError` from
  the strict loader. See
  `plans/202604/rust_backend_phase8_phase8{a..g}_handoff.md`.
- **Packaging:** `sase-core-rs` is a separate PyPI distribution built from
  `../sase-core/crates/sase_core_py` (maturin, `abi3-py312`). The Phase 6
  release matrix ships wheels for CPython 3.12+ on Linux x86_64, Linux
  aarch64, macOS universal2, and Windows x86_64; free-threaded CPython
  (`3.13t` / `3.14t`) is intentionally out of scope for this release. `sase`
  declares `sase-core-rs>=0.1.0,<0.2.0` as a runtime dependency, so a normal
  `pip install sase` or `uv tool install sase` resolves the prebuilt wheel —
  no local Rust toolchain required. Source contributors with a sibling
  `../sase-core` checkout can use `just rust-install` (or the auto-run
  embedded in `just install`) to satisfy the dependency from local Rust.
  See `plans/202604/rust_backend_phase6_phase6a_handoff.md` and
  `plans/202604/rust_backend_phase6_phase6b_handoff.md`.
- **`is_workflow_complete` regression resolved.** Phase 6E pinned the
  predicate to a targeted Python traversal of
  `~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json` regardless of
  `SASE_CORE_BACKEND`; the Phase 6E micro-benchmark
  (`tests/perf/bench_workflow_complete.py`, 6×200 synthetic, 10 workflows,
  target `wf_0`) records 34 ms under both Python and Rust modes vs.
  102 / 88 / 188 ms for the previous snapshot-backed path under
  python / rust / dual_run respectively. A Rust early-exit binding was
  considered and rejected — the targeted Python path already eliminates the
  regression and the predicate runs against trees too small to motivate a
  PyO3 boundary crossing. `find_named_agent` continues to consume the
  snapshot facade because its access pattern is broader. See
  `plans/202604/rust_backend_phase6_phase6e_handoff.md`.
- **CI.** Phase 8F deleted the dual-backend matrix and the
  `parity-gate` job. `.github/workflows/ci.yml` now runs the full pytest
  suite under CPython 3.12 / 3.13 / 3.14 against the only supported
  backend; the `phase7-perf-floor` job runs the Rust regression-floor
  checker on every PR. The publish workflow's `install-smoke` job
  installs the built `sase` wheel into a fresh venv, runs `sase core
  health`, and emits a failure-mode diagnostic (pip list, Python/platform
  info, `sase_core_rs.__file__` / `__version__`). See
  `plans/202604/rust_backend_phase8_phase8f_handoff.md`.
- **Backend health and operation disposition.** `sase core health`
  (`-j` / `--json` for scripts) imports `sase_core_rs`, calls a cheap
  shipped binding (`parse_query("status:Ready")`), and exits non-zero
  whenever the report is `status="error"`. The post-Phase-8 operation
  disposition is: 11 ported operations call `sase_core_rs` directly via
  the strict loader (`parse_project_bytes`, `parse_query`,
  `scan_agent_artifacts`, `read_status_from_lines`, `apply_status_update`,
  `plan_status_transition`, `parse_git_name_status_z`, and the four other
  Git query parsers); 6 surfaces are Python-owned host logic
  (`parse_project_file`, `build_query_context`, `evaluate_query`,
  `evaluate_query_with_context`, `evaluate_query_many`,
  `build_changespec_graph_index`, `transition_changespec_status`). See
  `plans/202604/rust_backend_phase8_phase8a_handoff.md` for the
  inventory and `plans/202604/rust_backend_phase8_phase8b_handoff.md`
  for the `evaluate_query_many` deferral.
- **Documentation and rollback.** `docs/rust_backend.md` is the
  user-facing contract: post-Phase-8 steady-state voice, no env vars, no
  Python fallback. Rollback is wheel/package-fix only — pin a
  known-good `sase-core-rs`, file a bug in `../sase-core` if the wheel
  itself is broken on a platform, and revert the relevant Phase 8 PR(s)
  to redo verification when a regression must restore Python halves. The
  Phase 8G close-out record lives in
  `plans/202604/rust_backend_phase8_phase8g_handoff.md`.
- **Phase 7 complete.** `tests/perf/phase7/` locked the artifact contract;
  Phase 7B captured per-operation microbenchmarks for every shipped Rust
  core op (`plans/202604/perf_artifacts/rust_backend_phase7_<op>_summary.json`);
  Phase 7C captured `sase ace`, `sase agents status`, and `sase run`
  startup under both backends. The user-facing tables, methodology, and
  support-note live in `docs/rust_backend.md` under `Performance`; the
  research-side gate-vs-realised analysis lives in
  `sdd/research/202604/rust_backend_phase7_performance.md`. Headline outcomes:
  `sase agents status -j` is **2.59× / 2.03×** faster on synthetic 8×25 /
  home tree as a cold subprocess; `parse_project_bytes` is 2.4× / 1.4× on
  golden / synthetic_200; `parse_query` direct parse is 2.1×;
  `evaluate_query_many` is **0.05×–0.08× on the routed path** (per-call
  wire conversion regression — Phase 8 should not delete the Python half
  until amortised); `sase ace` cold open is 0.84× on a Pilot harness that
  mocks the Rust scan/parse hot paths (small-input dispatch tax, not a
  routed-op regression). Phase 7E wired the CI regression floor
  (`tests/perf/baselines/phase7_regression_floor.json` + the
  `phase7-perf-floor` GitHub Actions job invoking `just phase7-perf-check`);
  Phase 7F re-ran the full verification matrix (`just phase7-perf-check`,
  `just parity-check`, `just check`, `SASE_CORE_BACKEND=python just test`,
  `just rust-check`, and `sase core health --json` under both backends) and
  recorded the close-out in
  `plans/202604/rust_backend_phase7_phase7f_handoff.md`. Phase 8 (Python
  implementation removal) now has a clean starting point.

The remainder of this document is the forward plan: Phase 7 measurement, the
Phase 8 removal of the Python implementations of ported operations, deferred
ports, and the longer-horizon server surface for web/mobile.

---

## 1. Why this is achievable

Two things matter for this migration:

1. **The slow logic is mostly already separated from Textual.** A code-map sweep
   found the following non-UI subsystems with effectively zero Textual/Rich
   coupling:

   | Subsystem | Path | LOC | Verdict |
   |---|---|---|---|
   | ChangeSpec parser, models, sections, validation, archive | `src/sase/ace/changespec/` | ~2,600 | Pure parsing — top candidate |
   | Query language (lexer, parser, evaluator, highlighter) | `src/sase/ace/query/` | ~1,950 | Pure logic + regex — top candidate |
   | Status state machine (transitions, suffixes, field updates) | `src/sase/status_state_machine/` | ~1,450 | Pure state — top candidate |
   | Agent name lookup / claim / running enumeration | `src/sase/agent/names/`, `src/sase/agent/running.py` | ~1,300 | Heavy fs+JSON IO — strong candidate |
   | Git query ops (log/blame/branch parsing) | `src/sase/vcs_provider/plugins/_git_query_ops.py` | ~390 | Subprocess + parse — moderate |
   | Memory / xprompt keyword matching | `src/sase/memory/` | ~330 | Small, low ROI |
   | Config (YAML merge layers) | `src/sase/config/` | ~960 | Already cached, low ROI |
   | History / telemetry (JSONL) | `src/sase/history/`, `src/sase/telemetry/` | mixed | Low ROI |

2. **The CLI dispatch is already a clean seam.** `src/sase/main/entry.py`
   argparse-dispatches to handlers; `ace_handler.py` only then constructs
   `AceApp`. Anything below the handler layer can be replaced with a Rust call
   without touching argparse, Textual, or the `sase_llm` / `sase_vcs` /
   `sase_workspace` plugin entry points.

The TUI itself stays in Python/Textual. Rust replaces what the TUI *calls
into*, not the rendering layer.

---

## 2. Strategic shape: one Rust core, three thin shells

```
                    ┌─────────────────────────────────────┐
                    │         sase-core (Rust crate)      │
                    │  changespec · query · state machine │
                    │  agent scan · git ops · memory      │
                    │   pure data types · no IO leaks     │
                    └────────────┬───────────┬────────────┘
                                 │           │
                  ┌──────────────┘           └─────────────┐
                  │                                        │
            PyO3 bindings                          uniffi / wasm-bindgen
                  │                                        │
        ┌─────────▼─────────┐                  ┌───────────▼───────────┐
        │  Python `sase`    │                  │  sase-server (axum)   │
        │  Textual TUI      │                  │  → web app (Next/SPA) │
        │  argparse CLI     │                  │  → mobile (Swift/Kt)  │
        └───────────────────┘                  └───────────────────────┘
```

**One Rust crate, multiple binding layers.** This is the only shape that lets
the TUI, web app, and mobile app share back-end code without three
re-implementations.

- **PyO3 (`pyo3` + `maturin`)** for the TUI. Compiled extension distributed
  alongside the wheel. Calls look like normal Python calls.
- **UniFFI (Mozilla)** for mobile. Generates Swift and Kotlin bindings from a
  `.udl` file describing the same types. iOS / Android apps consume a static
  library.
- **`wasm-bindgen` + `wasm-pack`** for the web. Compile a subset (parsers,
  query evaluator) to WebAssembly. Heavier subsystems (agent scan, git) move
  behind a small **`sase-server`** (axum/tonic) that the web app talks to over
  HTTP/JSON or gRPC. Mobile can use the same server when offline isn't
  required.

The same Rust types serialize to both PyO3 and JSON, so contracts stay aligned
across front ends.

---

## 3. Contract decisions to make before Rust

These are the gaps most likely to derail a gradual migration if they stay
implicit.

### Define a stable wire model

The Rust crate should not expose the current Python dataclasses directly as a
binding contract. Those dataclasses can keep changing to serve the TUI. Instead,
add explicit wire records:

```text
ChangeSpecWire
  schema_version: u32
  name: string
  project_basename: string
  file_path: string
  source_span: {start_line, end_line}
  status: string
  parent: string | null
  cl_or_pr: string | null
  description: string
  sections: list<SectionWire>
  commits: list<CommitWire>
  hooks: list<HookWire>
  comments: list<CommentWire>
  mentors: list<MentorWire>
  raw: {header_lines, section_lines}
```

Python owns the conversion from `ChangeSpecWire` into the existing
`ChangeSpec` model. Rust owns parsing and validation of the wire form. Web and
mobile consume the same wire records via JSON / UniFFI types. This keeps the
FFI boundary boring: owned strings, arrays, maps, booleans, and explicit error
records only.

### Preserve the source-span contract

Many operations eventually rewrite `.gp` files. A Rust parser that only returns
semantic fields is not enough. It must also return line spans for the original
ChangeSpec and each mutable section so Python can keep using atomic field
updates without a full formatter rewrite. Treat `(file_path, start_line,
end_line)` as part of the parser's public API.

### Separate "pure core" from "host services"

The future shared core should not read global config, import plugins, or call
Textual. Put these behind host-provided services:

| Need | Rust core API shape | Host implementation |
|---|---|---|
| Read project files | `parse_project_bytes(path, bytes)` | Python TUI / server fs layer |
| Resolve config | Plain config struct argument | Python config loader today |
| VCS operations | Trait / command adapter | Existing Python plugin entry points |
| Notifications / history | Event returned from Rust | Python persists side effects |
| Web/mobile auth | Outside `sase-core` | `sase-server` / app shell |

This is the boundary that keeps mobile and web viable. Anything that requires
Python entry points or local process control is not portable core logic.

### Use dual-run tests, not just backend toggles

`SASE_CORE_BACKEND={python,rust}` is necessary but not sufficient. Add a
`SASE_CORE_DUAL_RUN=1` mode for the TUI and CLI that calls both implementations
on selected hot operations, uses the Python result, and logs Rust mismatches to
`~/.sase/perf/core_dual_run.jsonl`. That catches real-data drift before the Rust
backend becomes the default.

Each record should include:

```text
operation
source_path
input_hash
python_duration_ms
rust_duration_ms
match: bool
first_diff_path
error_class
```

Once Rust becomes the default, keep the same discipline for one release cycle
but invert the purpose: dual-run is now a release-candidate safety rail, not a
normal production mode. Capture aggregate mismatch counts in CI logs and in the
rollout handoff; do not require every local TUI launch to pay the dual-run cost.

---

## 4. Migration order (lowest risk → highest leverage)

### Phase 0 — Establish the seam in Python (no Rust yet) ✅ complete

Before introducing Rust, codify the boundary that Rust will replace. This makes
every later step a 1-file swap instead of a refactor.

1. Expand the existing `src/sase/core/` package into a facade for the current
   pure-logic functions: ChangeSpec parsing, query parse/eval, graph indexing,
   and status transitions. Keep the existing utility functions there.
2. Add a thin **schema layer**: use `TypedDict` or small dataclasses for the
   wire records. Avoid a hard runtime dependency on pydantic unless validation
   cost and dependency weight are justified.
3. Write **golden tests**: capture a sanitized corpus of real `.gp` files, real
   query strings, and parser/query outputs. These become the contract Rust must
   match. Use `inline-snapshot` (already a dev dep) for diff-friendly review.
4. Add `SASE_CORE_BACKEND={python,rust}` and `SASE_CORE_DUAL_RUN=1` dispatch
   inside the new facade. Default to `python`.
5. Move current TUI and CLI callers onto the facade only after the facade has
   tests. Do not make every `src/sase/ace/*` import jump to Rust directly.

**Outcome:** `src/sase/core/` (`backend.py`, `dual_run.py`, `wire.py`,
`parser_facade.py`, `query_facade.py`, `status_facade.py`,
`graph_index_facade.py`) shipped with golden tests under `tests/`. Boundary
documented in `docs/rust_backend.md`. Plan: `plans/202604/rust_backend_phase0.md`.

### Phase 1 — ChangeSpec parser in Rust (highest single-file ROI) ✅ complete

The parser remains the best first Rust target, but the current in-process
`ChangeSpecSnapshotCache` means the win must be measured on cold loads,
changed-file refreshes, and commands that bypass the TUI cache. It is still
mostly pure: bytes in, wire struct out, no global IO.

- Create the Rust Cargo workspace. The original plan assumed
  `rust/sase-core/` in-tree; the implementation landed as sibling repo
  `../sase-core/`.
- Implement `parse_changespec(&[u8]) -> ChangeSpec` matching
  `section_parsers.py` semantics. Lean on `winnow` or `nom` for the section
  state machine; `serde` for downstream serialization.
- Implement `parse_project_bytes(path, bytes) -> Vec<ChangeSpecWire>` rather
  than only single-spec parsing, because `parse_project_file()` currently owns
  multi-spec scanning and malformed-entry recovery.
- Expose via PyO3:
  ```rust
  #[pyfunction]
  fn parse_project_bytes(path: &str, data: &[u8]) -> PyResult<PyObject> { ... }
  ```
- Behind the `SASE_CORE_BACKEND=rust` flag, route Python calls to the
  extension. Run the golden tests against both backends in CI to prove
  equivalence.
- Ship as a separate extension distribution (`sase_core_rs`) that `sase` can
  use when present while the Python fallback stays available during rollout.
- Add a Rust-side benchmark with `criterion` for a realistic project/archive
  corpus and a Python benchmark that includes FFI conversion cost. The FFI
  number is the one that matters to the TUI.

**Why first:** smallest blast radius, biggest perf win, builds the build
infrastructure (maturin, cibuildwheel matrix for linux/macOS/windows × x86_64
/ arm64) you'll reuse for everything else.

**Do not flip the default** unless the measured end-to-end speedup is meaningful
after cache hits are accounted for. A parser that is 10x faster internally but
only saves 5 ms on warm TUI refreshes is not the next bottleneck.

**Outcome:** `parse_project_bytes` routes through `sase_core_rs` when
`SASE_CORE_BACKEND=rust`. Cross-repo parity gate runs the golden corpus through
both backends. Bench harness landed as `tests/perf/bench_core_parse.py` /
`just bench-core`. The landed workspace is the sibling repo
`../sase-core/` rather than an in-tree `rust/` directory. See
`plans/202604/rust_backend_phase1.md` and
`plans/202604/rust_backend_phase1_handoff.md`.

### Phase 2 — Query evaluator + tokenizer ✅ complete

Same shape as Phase 1: pure logic, well-defined IO. The evaluator's hot path is
regex compilation and AST eval against thousands of ChangeSpecs — Rust's
`regex` crate (Rust-native, no PCRE backtracking) is dramatically faster, and
reusing compiled regexes across calls is straightforward.

Watch out for two things:
- Highlighting needs span offsets that match Python's. Emit `(start, end)`
  byte offsets and let the TUI translate to character offsets if needed.
- Some queries use Python `re` features. Inventory before porting; reject
  unsupported patterns at parse time rather than diverging at eval time.
- The Python `QueryEvaluationContext` already fixed the worst O(N^2) behavior.
  Measure `parse_query + filter N specs` with and without the current context
  before assuming Rust is the next win.
- Prefer a compiled-query handle for repeated evaluation:
  `compile_query(query) -> QueryProgram`, then `evaluate_many(program,
  specs_wire)`. Calling Rust once per row will waste much of the speedup at the
  FFI boundary.

**Outcome:** `parse_query` and `evaluate_query_many` route through
`sase_core_rs` when `SASE_CORE_BACKEND=rust`; hot call sites use the batched
`evaluate_query_many` shape rather than per-row dispatch. Wire contract +
golden corpus in `src/sase/core/query_wire*.py` and `tests/`. See
`plans/202604/rust_backend_phase2_query.md` and
`sdd/research/202604/rust_backend_phase2_query_handoff.md`.

### Phase 3 — Agent / artifact filesystem scan ✅ complete

This is the one most users will *feel*. `_lookup.py` walks
`~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json` synchronously and
parses each. In Rust:

- Use `walkdir` + `rayon` for parallel directory walking.
- Use `simd-json` or `sonic-rs` for JSON parsing.
- Expose a **streaming** iterator (`fn scan_agents() -> impl Iterator<Item = Agent>`)
  rather than returning a giant list. The TUI can render the first frame as
  results arrive — this is a UX win independent of raw speed.
- On the PyO3 side, start simpler than a true async generator: expose
  `scan_agents_snapshot(root, options) -> Vec<AgentWire>` and call it inside
  the existing `asyncio.to_thread` loader. Move to streaming only once snapshot
  parity is stable.
- If streaming becomes necessary, expose batches over a bounded channel. The
  TUI wants "first rows soon", not one Python callback per file.

This phase also unlocks **mobile/web parity**: the same scan logic, behind a
gRPC streaming endpoint, populates the future web/mobile agent list.

**Outcome:** `scan_agent_artifacts` snapshot facade landed in
`src/sase/core/agent_scan_facade.py`; `sase_core_rs.scan_agent_artifacts`
releases the GIL during the walk and returns a JSON-shaped dict. Streaming
was evaluated and **rejected** (Phase 3G): the bottleneck on the worst real
workload is the Rust filesystem walk itself, which streaming cannot reduce.
End-to-end win 1.25× (synthetic) – 1.55× (home, 6.5k records); did not clear
the original 2× research gate, so default stayed `python` pending the
consolidation track below. See
`plans/202604/rust_backend_phase3_agent_scan.md` and the per-subphase
handoffs (`*_phase3a` … `*_phase3h_handoff.md`).

### Phase 4 — Status state machine *(complete; opt-in, default `python`)*

Pure decision logic ported to `../sase-core/crates/sase_core/src/status/`
behind a structured wire contract (`StatusTransitionRequestWire` /
`StatusTransitionPlanWire`). PyO3 exposes `is_valid_status_transition`,
`remove_workspace_suffix`, `read_status_from_lines`, `apply_status_update`,
and `plan_status_transition` on `sase_core_rs`. Python keeps every side
effect: file lock, atomic write, archive moves, mentor flag mutation,
suffix branch rename, sibling reverts, timestamp recording, and VCS calls.

`transition_changespec_status_python` was refactored into four explicit
stages — in-lock input gathering, pure decision (Rust-routable planner),
in-lock side effects (STATUS line rewrite + mentor flags), and post-lock
side effects (suffix renames, archive moves, timestamp). Under
`SASE_CORE_BACKEND=rust` the planner runs in Rust; side effects always run
in Python exactly once. Under `SASE_CORE_DUAL_RUN=1` the planner facade
compares the two plan dicts before any side effects fire — disk writes are
never duplicated.

The motivation for Phase 4 was shared-core hygiene rather than
user-perceived latency. The Phase 4A benchmark already showed pure
decision cost was sub-microsecond and the orchestrator was dominated by
side effects Phase 4 deliberately leaves on Python. The Phase 4F re-run
(`bench_status_state_machine_phase4f.json`) confirmed the Rust path adds
a small wire round-trip cost (~5–7 % on the synthetic 200-spec
transition workload) and Python remains the sensible default for the
default backend. The end-to-end transition wall clock is dominated by
`parse_project_file`, `find_all_changespecs`, and the locked atomic
write; the planner change is invisible at user-perceived scales.

**Rollout:** default backend stays `python`. The Rust planner is shipped,
parity-tested under the dual-run facade, and opt-in via
`SASE_CORE_BACKEND=rust`. No per-operation default-Rust override is
recommended — the planner is too cheap to motivate the dependency on a
sibling Rust extension at default install. The line helpers
`read_status_from_lines` and `apply_status_update` follow the same
opt-in policy. See
`plans/202604/rust_backend_phase4_status_machine.md` and the
`*_phase4a` … `*_phase4f_handoff.md` series.

### Phase 5 — Git query ops *(complete; opt-in, default `python`)*

Three options were on the table:

- **A.** Keep shelling out to `git`, but parse the output in Rust (hand-rolled
  pure parsers; no `gix`). Cheapest.
- **B.** Use `gix` directly, eliminating the `git` subprocess. Faster, no
  fork overhead, but `gix` doesn't yet support every operation
  `_git_query_ops.py` uses — audit first.
- **C.** Skip. Subprocess overhead is dwarfed by `git`'s own work for log/blame.

Phase 5 went with **A**, narrowly scoped to the deterministic parsers that
sit on the Git query path and excluding all mutating sync/reword/checkout
behavior. Five pure helpers shipped behind `sase.core.git_query_facade` and
the matching `sase_core_rs` PyO3 bindings:

| facade helper                | Rust binding                  | Python source of truth (rollback path)               |
| ---------------------------- | ----------------------------- | ---------------------------------------------------- |
| `parse_git_name_status_z`    | yes                           | `git_query_facade.parse_git_name_status_z_python`    |
| `parse_git_branch_name`      | yes                           | `git_query_facade.parse_git_branch_name_python`      |
| `derive_git_workspace_name`  | yes                           | `git_query_facade.derive_git_workspace_name_python`  |
| `parse_git_conflicted_files` | yes                           | `git_query_facade.parse_git_conflicted_files_python` |
| `parse_git_local_changes`    | yes                           | `git_query_facade.parse_git_local_changes_python`    |

What stayed on Python and why:

- `CommandRunner._run`, timeouts, fetch fallback, filesystem checks, and
  rebase-state introspection — host services that touch the OS.
- All mutating operations: checkout, sync, rebase, branch rename,
  commit/amend, archive/prune, stash/clean, patch application. These were
  never in scope for a pure-parser port and remain the Git provider's
  Python responsibility.
- Pass-through command output (diffs, patches, file contents, commit
  messages). No parsing/normalization happens — Rust would only add a wire
  copy.

`GitQueryOpsMixin` was rewired in Phase 5E to call the facade for the five
helpers above; the public hookimpl shapes (`list[tuple[str, str]]` for name-
status with rename/copy still encoded as `"<old>\t<new>"`, `(True, name|None)`
tuples for branch/local-changes with `(True, None)` reserved for detached
HEAD or clean trees, `[]` on `git diff` failure for conflicted files,
remote-URL-priority workspace-name with root fallback) are byte-identical
across both backends.

**Bench summary (`bench_git_query_ops_phase5e.json`).** On
`parse_git_name_status_z` synthetic_large (~10k entries, ~600 KB), the Rust
binding's median is roughly the same as Python (~9 ms vs ~9 ms); at the
500-entry workload Python parses in ~722 µs and Rust in ~705 µs while the
underlying `git diff --name-status -z` subprocess costs ~10.5 ms. At
`end_to_end_50` the Rust parser shaves ~37 µs vs ~73 µs of parse cost but is
dwarfed by the ~2.7 ms subprocess. Branch-name, workspace-name, conflicted-
file, and local-changes microbenchmarks are sub-microsecond on both
backends. Dual-run roughly doubles parse cost as expected (3460 records
logged across the bench during Phase 5E; mismatches = 0). Phase 5F re-ran
the focused tests under all three backends (default Python, Rust, dual-run);
all 75 pass on this workspace.

**Rollout:** default backend stays `python`. The Rust Git query parsers are
shipped, parity-tested under the dual-run facade, and opt-in via
`SASE_CORE_BACKEND=rust`. No per-operation default-Rust override is
recommended — the parser is too cheap relative to the `git` subprocess to
justify a sibling-extension dependency at default install. The shared-core
hygiene goal is met: the parser logic now lives in the Rust crate and is
exercised by both the Python tests and a `tests/git_query_parity.rs` parity
suite, ready for any future non-Python caller (server, mobile, web). See
`plans/202604/rust_backend_phase5_git_query_ops.md` and the `*_phase5a` …
`*_phase5f_handoff.md` series.

**`gix`?** Not warranted by Phase 5 evidence. Subprocess fork+exec dominates
end-to-end Git query cost on every measured workload, but the gap between
the parse path and the subprocess is small enough that ripping out `git` for
`gix` would only matter on hot loops, and Phase 5A confirmed those loops
don't exist on the Git query surface today. If a future profile shows a
caller invoking these helpers in a tight loop, revisit `gix` as a separate
epic against a concrete workload — do not reopen Phase 5.

### Phase 6 — Switch sase to the Rust backend by default ✅ complete

The shared-core / mobile / web track only pays off when Rust *is* the core.
The Phase 3H rollout decision deliberately deferred this flip because the
end-to-end win at the worst real workload was 1.55× rather than the original
2× gate. This phase is where that decision was revisited and the flip
landed for every operation already ported (parser, query, agent scan,
status state machine, Git query parsers).

**Outcome:** Rust is the production default. The `sase-core-rs` PyPI
distribution ships per-platform wheels for CPython 3.12+ on Linux x86_64,
Linux aarch64, macOS universal2, and Windows x86_64; `sase` declares it as a
runtime dependency. `DEFAULT_BACKEND` is `Backend.RUST` and shipped
operations dispatch through Rust whenever `SASE_CORE_BACKEND` is unset;
`SASE_CORE_BACKEND=python` is the documented escape hatch through Phase 7.
The `is_workflow_complete` regression was resolved by a targeted Python
traversal that runs regardless of backend selection (no Rust early-exit
binding required). CI runs the suite under both backends, plus a
`parity-gate` job and a publish-side `install-smoke`. The full per-subphase
record is in `plans/202604/rust_backend_phase6_*_handoff.md`. See the
**2026-04-29 update** at the top of this document for the consolidated
status snapshot.

**Prerequisites that must hold before flipping:**

1. **The dependency story is explicit.** Decide whether the Phase 6 release
   depends on a separately published `sase_core_rs` distribution, vendors the
   Rust extension into the `sase` wheel, or uses a workspace/submodule release
   job. Do this before changing defaults so packaging failures look like
   release failures, not runtime backend bugs.
2. **Wheels are distributed for every supported platform.** Today
   `sase_core_rs` is built locally via `just rust-install`. Until prebuilt
   wheels ship for `cp312+ × {linux x86_64, linux aarch64, macOS universal2,
   windows x86_64}`, flipping the default would force every contributor to
   install Rust. Stand up `cibuildwheel` or maturin GH Actions and publish
   the matrix; treat the wheel build as part of `sase`'s release pipeline.
3. **A pure-Python install path still produces a working sase.** Either keep
   the Python implementations behind `SASE_CORE_BACKEND=python` for one
   release after the flip, or refuse to start with a clear error if no Rust
   extension is available *and* the user explicitly opts back into Python.
   Pick one and document it; do not silently fall back.
4. **No outstanding parity drift in `core_dual_run.jsonl`.** Run a release
   cycle with `SASE_CORE_DUAL_RUN=1` enabled in CI on the golden corpus and
   on a sanitized home-tree fixture; mismatch count must be zero.
5. **Per-operation fallback policy is explicit.** `SASE_CORE_BACKEND=rust`
   must mean "Rust for shipped operations, Python for intentionally unported
   facades" before a suite-wide default flip. Shipped operations keep strict
   missing-binding failures; unported query context/per-row evaluation,
   graph-index, and status APIs opt into Python fallback. Tests should assert
   both halves of that contract instead of maintaining an unsupported-operation
   bucket for unported facades.
6. **Acknowledged gate change.** The 2× gate was the right bar for "is it
   worth porting?"; for "should the port be the default once it exists?" the
   bar is "measurable user-visible win, no regressions on hot paths." Record
   the new bar in the rollout decision so future ports inherit it.

**Steps:**

- Default `SASE_CORE_BACKEND` to `rust` in `src/sase/core/backend.py`. Keep
  the env var as an escape hatch (`=python`) for the duration of the
  release cycle.
- Special-case the one known regression: `is_workflow_complete` is ~3×
  slower under Rust because the snapshot model removes the Python
  short-circuit. Either keep this single op pinned to Python via per-op
  override, or restructure the snapshot to expose a "first matching
  marker" early-exit. Do **not** flip the default with a known per-op
  regression.
- Update `docs/rust_backend.md`: Rust path is the default, opt-out is
  `SASE_CORE_BACKEND=python`, `just rust-install` is required for
  contributors building from source until prebuilt wheels are published.
- CI must run the test suite under both backends until Phase 8 (removal)
  lands. Add a `SASE_CORE_BACKEND=python` matrix job alongside the existing
  default-backend job.
- Add a cheap backend health check to the CLI startup path used by release
  smoke tests: import `sase_core_rs`, call `parse_query("!!!")`, and fail with
  the package version / platform tag if the extension cannot load. Runtime
  user errors should say "the Rust extension failed to load" rather than
  surfacing a raw `ImportError`.
- Record a rollback plan in the Phase 6 handoff: while the Python backend is
  still present, rollback is a patch release that restores
  `DEFAULT_BACKEND=python`; after Phase 8, rollback is a wheel/package fix
  because there is no Python implementation to fall back to.

**Exit criterion:** `sase` installed from a release artifact works without a
local Rust toolchain on every supported platform; `SASE_CORE_BACKEND` is
unset in the wild and Rust is in the hot path; no parity mismatches recorded
in `core_dual_run.jsonl` over a release cycle; `is_workflow_complete`
either restored to parity or explicitly pinned with a comment pointing at
the structural cause.

### Phase 7 — Verify and document the end-to-end performance improvement

After the default flip, before the Python path is removed, do one
deliberate measurement pass so the win is documented and any unexpected
regression has time to surface.

**Status (2026-04-29):** Phase 7 complete. Phase 7A–7D landed the
measurement contract, per-operation microbenchmarks, end-to-end captures,
and the user-facing performance documentation. Phase 7E wired the CI
regression floor (`tests/perf/baselines/phase7_regression_floor.json`,
`tests/perf/phase7_check_regression.py`, `just phase7-perf-check`, and the
`phase7-perf-floor` GitHub Actions job that uploads the floor-check JSON
report on every run). Phase 7F re-ran the full verification matrix and
recorded the close-out in
`plans/202604/rust_backend_phase7_phase7f_handoff.md`. The forward plan
below is preserved as historical context; the table of "measurements to
take" should be read as "measurements taken" — see the linked
performance-research record for the realised medians and the implications
for Phase 8 sequencing.

**Measurements to take:**

| Where measured                            | Compare                       |
| ----------------------------------------- | ----------------------------- |
| `tests/perf/bench_core_parse.py`          | `python` vs `rust` facade     |
| `tests/perf/bench_core_query.py` / `just bench-query` | `python` vs `rust` facade |
| `tests/perf/bench_agent_scan.py`          | `python` vs `rust` facade     |
| `SASE_TUI_TRACE=1` cold-open of `sase ace`| Pre-flip baseline vs. post-flip |
| `sase agents` cold listing on home tree   | Pre-flip baseline vs. post-flip |
| `sase run` end-to-end startup             | Pre-flip baseline vs. post-flip |

The TUI / CLI numbers are the ones that matter for the user. Bench
microtimings are evidence, not the headline.

**Deliverables:**

1. **`docs/rust_backend.md` "Performance" section** with a table of medians
   per scenario, sample size, the workstation profile they were taken on,
   and a link to the raw `bench_*.json` artifacts. Include both the
   synthetic and home-tree workloads.
2. **A short before/after entry in `sdd/research/202604/`** (or update this
   file) capturing the actual realized speedup, broken down per operation
   and per workload size. This is what future readers will cite to decide
   whether the migration was worth it.
3. **Updated benchmark gate.** Codify the realized speedup as the new
   regression floor: a CI bench job (or scheduled run) that fails if the
   Rust facade slows down by more than X% relative to the recorded
   numbers. This protects the win from silently eroding once the Python
   backend is gone.
4. **Acknowledged limits.** Record where Rust did *not* help (e.g.
   warm-cache TUI refreshes, small synthetic workloads). Honest negative
   results prevent a future contributor from porting an op that won't
   move the needle.
5. **Rollout telemetry / support note.** Add a small troubleshooting section:
   how to confirm which backend is active, where dual-run logs live during the
   rollout window, what error means "wheel did not load," and which env var to
   set for the temporary Python fallback. This turns performance verification
   into something supportable outside the migration team.

**Exit criterion:** every routed operation has a documented
before/after median on at least one realistic workload; the regression
floor is wired into CI; `docs/rust_backend.md` no longer reads as a
roadmap and starts reading as a user-facing description of how sase is
now built.

### Phase 8 — Remove the Python backend and the dispatch layer ✅ complete

Once the default had been Rust for one release cycle and Phase 7 recorded
clean numbers, Phase 8 retired the Python halves of the ported operations
and deleted the dispatcher. The post-Phase-8 steady state is documented in
`docs/rust_backend.md`; the per-subphase record lives in
`plans/202604/rust_backend_phase8_phase8{a..g}_handoff.md`. Subphase summary:

- **Phase 8A** — Inventory + strict Rust loader. Added `sase.core.rust`
  (`require_rust_extension` / `require_rust_binding`), pinned the
  per-operation disposition (ported / unported / deferred), and inventoried
  every dispatch-related call site.
- **Phase 8B** — `evaluate_query_many` regression. Reproduced the Phase 7
  per-call-wire-conversion regression, prototyped a Rust amortisation, and
  reclassified the operation as deferred/unported when the prototype was
  still 6-9× slower than the optimised Python batch path.
- **Phase 8C** — Unported facades pinned to direct Python; backend
  selection removed from health/UI; `sase core health` rewritten to verify
  the installed Rust extension instead of reporting a backend mode.
- **Phase 8D** — Direct-Rust `parser_facade.parse_project_bytes`,
  `agent_scan_facade.scan_agent_artifacts`, and `query_facade.parse_query`;
  deleted the Python halves of those operations.
- **Phase 8E** — Direct-Rust status helpers (`read_status_from_lines`,
  `apply_status_update`, `plan_status_transition`) and Git query parsers;
  re-measured tiny operations with the dispatcher gone and accepted the
  remaining absolute gap as shared-core hygiene rather than a runtime
  regression.
- **Phase 8F** — Deleted `sase.core.backend`, `sase.core.dual_run`, the
  CI `test-python-backend` and `parity-gate` jobs, the
  `tests/parity/dual_run_parity.py` driver, the `just parity-check`
  recipe, and every `SASE_CORE_BACKEND` / `SASE_CORE_DUAL_RUN` reference
  in production code, tests, and perf harnesses.
- **Phase 8G** — This subphase. Documentation rewrite (this section,
  `docs/rust_backend.md`), facade docstring cleanup, golden-contract
  language, and final close-out.

The subsections below are preserved as the historical plan for context;
the per-subphase handoffs are the authoritative record of what landed.

**What gets removed:**

- The Python implementation halves of dispatched operations: the
  Python-side `parse_project_bytes`, `parse_query` /
  `evaluate_query_many`, and `scan_agent_artifacts`.
- `SASE_CORE_BACKEND` and `SASE_CORE_DUAL_RUN` env vars and every code
  path that reads them for ported operations: `src/sase/core/dual_run.py`,
  the `is_rust_available()` probe, the `RustBackendUnavailableError`
  graceful-failure path, and the backend-selection branch in the parser,
  query, and agent-scan facades.
- The dual-backend CI matrix job added in Phase 6.
- `core_dual_run.jsonl` writer (the file format can stay documented as
  historical, but new runs will not produce it).
- Justfile aliases that exist solely for the dual-backend story
  (`bench-core` becomes the Rust bench, etc.).

**What stays:**

- `sase.core` itself stays as the import surface — but each module now
  delegates straight to `sase_core_rs` for ported operations with no dispatcher
  in between.
  Keep the wire records (`wire.py`, `query_wire.py`,
  `agent_scan_wire.py`) — they are the contract Python callers consume.
- Python implementations of operations that have **not** been ported
  (graph index, anything Phase 6+).
  Those still live in Python until their own port lands. Their facades should
  call Python directly or use a tiny local adapter; they must not import a
  deleted global backend dispatcher.
- The golden corpus and parity tests, repointed to compare
  `sase_core_rs` output against the recorded golden JSON instead of
  comparing two live implementations. Without a Python backend to dual
  against, the golden files become the contract.

**Order of removal (one PR per step where reasonable):**

1. Make `sase_core_rs` a hard install requirement (`pyproject.toml`
   `dependencies` rather than `optional-dependencies`). Verify a fresh
   `pip install sase` on every supported platform pulls the wheel.
2. Split the current `src/sase/core/backend.py` responsibilities before
   deleting it: ported facades get direct Rust imports, while unported facades
   (`status_facade.py`, `graph_index_facade.py`, future Phase 4+) are rewired
   to call their Python implementations directly.
3. Inline the Rust call inside each ported facade. Parser/query/agent-scan
   adapters become thin adapters such as
   `bytes -> sase_core_rs -> wire dataclasses`.
4. Delete the Python implementations of the ported operations.
5. Delete `SASE_CORE_BACKEND` / `SASE_CORE_DUAL_RUN` plumbing, the
   probe, `dual_run.py`, and the `RustBackendUnavailableError` type.
6. Delete the dual-backend CI matrix and the `python`-only test bucket.
7. Update `docs/rust_backend.md` to describe the resulting steady
   state: one implementation, no env vars, golden corpus as contract.

**Exit criterion:** `rg "SASE_CORE_BACKEND|SASE_CORE_DUAL_RUN|is_rust_available"`
returns nothing in `src/`; no facade imports `sase.core.backend`; `pip install
sase` requires no Rust toolchain on supported platforms; the test suite runs to
green with no backend matrix; the wire-record contract is documented as the
seam future ports target. The shared-core / mobile / web work in Phase 9 can
now assume Rust is the only implementation for parser, query, and agent scan.

### Phase 9 — Server surface for web/mobile

By the time Phase 8 lands, the Rust crate is the only implementation of
parsing, querying, and scanning, and Python plays the role of host shell. To
unlock the web app:

- Add a `sase-server` binary (separate crate in the workspace) using
  **axum** + `tower` + **`tonic`** if gRPC is wanted, or plain JSON REST.
- Define API in a single source of truth: either OpenAPI (`utoipa` derives
  from Rust types) or `.proto` for gRPC. Front ends generate clients.
- Mobile clients consume either:
  - the server (online), or
  - a uniffi-bound static lib of `sase-core` (offline, for parsing local
    `.sase/` data on the device).
- For the web app, prefer server-side for anything that touches the user's
  filesystem (most things). Keep the WASM-compiled subset for small things
  like client-side query syntax highlighting in the search box.
- Start with a **local-first server** bound to `127.0.0.1` plus an ephemeral
  bearer token printed / handed to the web app. Do not design hosted
  multi-tenant sync until there is an explicit product requirement; it changes
  auth, secrets, project data residency, and plugin execution semantics.
- Keep mutation endpoints command-shaped and auditable:
  `POST /changespecs/{name}:transition`, `POST /agents/{id}:kill`, etc.
  Avoid generic "write this file" endpoints.

---

## 5. Build, packaging, and distribution

This is the part that bites teams trying incremental Rust migration:

- **`maturin develop`** during local dev — installs the extension into the
  active venv. Today this is `just rust-install`, which is intentionally
  separate because the backend is opt-in. When Phase 6 flips the default,
  either make `just install` install the extension when `../sase-core` exists
  or make the released wheel dependency reliable enough that contributors do
  not need a local Rust build for normal Python work.
- **`cibuildwheel`** (or maturin's GH Actions) for the wheel matrix. Target
  cp312+ × {linux x86_64, linux aarch64, macOS universal2, windows x86_64}.
  Skip musllinux unless someone asks.
- **Fallback policy changes by phase.** Through Phase 7, pure-Python fallback
  stays installable: if the Rust wheel is absent, `pip install sase` still
  works and `SASE_CORE_BACKEND=python` is the escape hatch. Phase 8 deliberately
  ends that policy for the ported operations, so the packaging gate must move
  from "fallback exists" to "release artifacts always contain a loadable Rust
  extension."
- **CI parity test:** every PR runs the golden corpus through both backends
  and compares JSON outputs byte-for-byte.
- **Normal CPython vs. free-threaded CPython:** this repo requires Python
  3.12+. For regular CPython wheels, investigate `abi3-py312` to reduce wheel
  count. For free-threaded Python 3.14+, do not assume `abi3` covers it; PyO3's
  guide says the free-threaded build has a distinct ABI and needs
  version-specific wheels.
- **Thread-safety audit:** PyO3 0.28+ defaults modules toward free-threaded
  compatibility, but exposed `#[pyclass]` mutable state still needs explicit
  locking or immutable design. Prefer stateless `#[pyfunction]` APIs returning
  owned wire values for Phase 1.
- **Lockfile and toolchain policy:** add `rust-toolchain.toml` and commit
  `Cargo.lock` for reproducible app builds. Keep Rust MSRV explicit; otherwise
  contributor failures will look like packaging failures.
- **Cargo workspace layout:** the original in-tree target was:
  ```
  rust/
    Cargo.toml          # workspace
    sase-core/          # pure logic, no IO except files
    sase-core-py/       # PyO3 bindings
    sase-core-ffi/      # uniffi bindings (mobile)
    sase-core-wasm/     # wasm-bindgen subset
    sase-server/        # axum binary
  ```
  The implementation that landed lives in the sibling `../sase-core/` repo:
  ```
  ../sase-core/
    Cargo.toml
    crates/sase_core/      # pure Rust core
    crates/sase_core_py/   # PyO3 extension module `sase_core_rs`
  ```
  Future UniFFI / WASM / server crates should be added there unless the project
  deliberately moves Rust into this repo.

Keep `sase-core` `no_std`-friendly where possible (it isn't really, given
filesystem code, but the parsers can be). That makes the WASM build trivial.

Current / practical `Justfile` targets for the sibling Rust repo:

```make
rust-test:
    cd ../sase-core && cargo test --workspace

rust-fmt:
    cd ../sase-core && cargo fmt --all

rust-check:
    cd ../sase-core && cargo clippy --workspace --all-targets -- -D warnings

rust-install:
    cd ../sase-core/crates/sase_core_py && uv run maturin develop --release
```

---

## 6. Measurement plan and go / no-go gates

Use Rust only where it beats the current optimized Python path after conversion
cost, not just in microbenchmarks.

| Candidate | Benchmark | Go gate |
|---|---|---|
| ChangeSpec parse | Cold parse all project/archive `.gp` files; warm cache miss for one edited file | At least 2x faster end to end or at least 100 ms saved on a real large repo |
| Query eval | `parse_query + evaluate_many` over 100, 1k, 10k specs | At least 2x faster for large lists after FFI |
| Agent scan | Scan real `~/.sase/projects/*/artifacts` trees | First usable batch <100 ms or total scan at least 2x faster |
| Status state machine | Transition validation over replay corpus | Port only for shared-core correctness unless profiling shows runtime cost |
| Git ops | Existing command timings with fork/parse split | Port only if parse/fork overhead is material |

Run every benchmark in four modes:

1. Python direct.
2. Python through the new `sase.core` facade.
3. Rust direct (`cargo bench`).
4. Rust through PyO3 from Python.

The fourth number is the one that decides TUI rollout.

---

## 7. Risks and gotchas

- **Behavior drift.** The Python parser has implicit behaviors (whitespace
  handling, trailing-newline semantics, encoding fallbacks). The golden-test
  corpus must include adversarial inputs from real `~/.sase/projects/` data.
- **Error messages.** The TUI surfaces parser errors to users. Mirror message
  text where the user-visible string is a contract; treat internal errors as
  free to differ.
- **GIL contention.** PyO3 functions hold the GIL by default. For
  fan-out scans, release it (`py.allow_threads(|| ...)`) so parallel walking
  actually parallelizes. This is the single most common new-Rust-extension
  perf bug.
- **FFI call granularity.** Calling Rust once per ChangeSpec or once per row can
  erase the win. Design APIs around batches: parse a full file, evaluate a full
  list, scan a full tree or batch stream.
- **Different regex semantics.** Rust `regex` deliberately avoids some features
  Python `re` supports. Inventory current query patterns and either encode the
  supported subset in tests or keep Python regex fallback for unsupported
  patterns.
- **Datetime / path encoding.** Python `pathlib.Path` and `datetime.datetime`
  have to round-trip through Rust losslessly. Standardize on UTC ISO-8601
  strings and bytes-not-str for paths at the FFI boundary.
- **Source spans and formatting.** If Rust reparses but Python rewrites, the
  parser must preserve enough source location and raw section text to avoid
  changing user files unnecessarily.
- **Plugin entry points.** `sase_llm`, `sase_vcs`, `sase_workspace` are
  Python `entry_points`. Don't try to move them to Rust — the plugin model
  *is* a Python-ecosystem feature. Rust core stays "below" plugins.
- **Build time on CI.** First Rust compile on a fresh runner is slow. Cache
  `target/` aggressively (`Swatinem/rust-cache`) and split builds per target.
- **Mobile binary size.** uniffi bundles can balloon. Strip symbols, enable
  `lto = "fat"`, and split features so mobile only pulls parsing + querying.
- **Web app filesystem access.** A web UI cannot scan the user's local
  `~/.sase/` — it has to talk to a `sase-server` running on the user's
  machine, or a hosted multi-tenant service. Decide that product question
  before committing to a web build, because it shapes auth, transport, and
  data residency.
- **Mobile offline scope.** UniFFI is a good fit for parsing/querying local data
  in Swift/Kotlin, but process management, local workspaces, and plugin
  execution are desktop/server responsibilities. Define the mobile app as
  "viewer + limited commands" unless there is a separate local-agent runtime.
- **Error taxonomy.** Use structured errors (`ParseError {kind, message,
  file_path, line, column}`) at the Rust boundary. Python can format them for
  the TUI; web/mobile can render them without scraping strings.
- **Persistent cache invalidation.** If a future Rust parser writes an on-disk
  parse cache, include schema version, parser version, source file signature,
  and platform-independent path identity. Otherwise parser upgrades will produce
  subtle stale reads.
- **Removal order can strand unported facades.** `status_facade.py`,
  `graph_index_facade.py`, and the unported query evaluation helpers currently
  use an explicit Python-fallback dispatch policy. Phase 8 must rewire those
  modules before deleting `backend.py`, or a parser/query/scan cleanup will
  break unrelated Python-only APIs.
- **Operational observability.** During the default flip, users need one clear
  way to answer "am I on Rust?" and maintainers need one clear signal for
  extension load failures. Add a smoke-test command or health log before the
  env-var escape hatch is removed.

---

## 8. What's left

Phases 0–8 are done. Rust is the only implementation of every shipped
`sase.core` operation, there is no `SASE_CORE_BACKEND` env var, and the
golden corpus is the cross-language compatibility seam. The remaining
forward work is the optional consolidation captured below.

1. **Phase 9 — server surface for web/mobile.** The Rust crate is now
   the only implementation of parsing, querying, and scanning, so a
   `sase-server` binary in `../sase-core` plus a uniffi-bound static
   lib for mobile is unblocked when there is product demand. The plan
   sketch is in §4 above; do not start without an explicit product
   requirement, since auth, secrets, and data residency change shape
   under multi-tenant hosting.
2. **`evaluate_query_many` re-port.** Phase 8B reclassified this as
   deferred/unported because the prototype Rust path was 6-9× slower
   than the optimised Python batch path. A future re-attempt should
   either land an amortised Rust API that accepts a reusable corpus or
   a Python-side wire cache keyed by stable identity; do not delete
   `_evaluate_query_many_python` until the new path beats the existing
   batch median on the Phase 7B synthetic workloads.
3. **Future per-operation ports.** Graph index construction, the
   side-effecting status transition, and the query context/per-row
   helpers are still Python-owned host logic. Re-justify any future
   port against fresh Phase 7-style measurements, not the Phase 0
   research — the realised speedup at the user-perceived level may not
   match microbenchmark gains.

The discipline that made this work: **never port ahead of measurement,
and do not delete a Python implementation until its Rust replacement
has cleared the regression floor on a recorded workload.** That's how
the migration got from Phase 0 to Phase 8 without taking the TUI down,
and it's the same discipline that should gate any post-Phase-8 work.

---

## References

- `sdd/research/202604/sase_perf_research.md` — TUI hot-path analysis, refresh
  paths, j/k navigation cost.
- `sdd/research/202604/sase_perf_v2_research.md` — kill/dismiss/launch I/O
  audit; identifies remaining synchronous notification I/O.
- `sdd/research/202604/tui_profiling_strategies.md` — proposed
  `SASE_TUI_TRACE=1` instrumentation; reuse for before/after measurement.
- PyO3: <https://pyo3.rs>
- PyO3 free-threaded Python guide: <https://pyo3.rs/main/free-threading.html>
- maturin: <https://www.maturin.rs>
- maturin README / packaging overview:
  <https://github.com/PyO3/maturin>
- UniFFI: <https://mozilla.github.io/uniffi-rs/>
- UniFFI design principles:
  <https://mozilla.github.io/uniffi-rs/latest/internals/design_principles.html>
- UniFFI Swift bindings:
  <https://mozilla.github.io/uniffi-rs/latest/swift/overview.html>
- UniFFI async overview:
  <https://mozilla.github.io/uniffi-rs/latest/internals/async-overview.html>
- wasm-bindgen guide:
  <https://wasm-bindgen.github.io/wasm-bindgen/>
- wasm-pack:
  <https://wasm-bindgen.github.io/wasm-pack/>
- `gix` (pure-Rust git): <https://github.com/Byron/gitoxide>
