# Migrating the SASE TUI Back End to Rust (Gradual, Multi-Frontend)

**Goal:** move the slow, non-UI logic underneath `sase ace` (the Textual TUI) into a
Rust core that can be shared with future SASE web and mobile front ends, without a
big-bang rewrite. The TUI keeps working at every step.

This research is grounded in the existing performance analyses
(`sase_perf_research.md`, `sase_perf_v2_research.md`,
`tui_profiling_strategies.md`) and a code map of the current Python modules.

**2026-04 update:** some Phase 0-style Python optimization work has already
landed since this note was first drafted:

- `src/sase/ace/changespec/cache.py` has an in-process
  `ChangeSpecSnapshotCache` keyed by `(path, mtime_ns, size)`.
- `src/sase/ace/query/evaluator.py` has `QueryEvaluationContext` and
  `evaluate_query_with_context()`, so the query path no longer has to rebuild
  all maps per row.
- `src/sase/ace/tui/models/changespec_graph_index.py` has
  `ChangeSpecGraphIndex` for ancestor / child / sibling lookups.
- `src/sase/core/` exists, but today it is mostly shared utility code rather
  than the full parser/query/state-machine facade that a Rust backend should
  replace.

That changes the immediate next step: do not re-land generic cache work. The
missing foundation is now a stable **wire contract** and a backend selection
facade that can dual-run Python and Rust implementations.

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

---

## 4. Migration order (lowest risk → highest leverage)

### Phase 0 — Establish the seam in Python (no Rust yet)

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

**Exit criterion:** TUI is unaffected; `pytest -k core` covers the seam end to
end; `SASE_CORE_DUAL_RUN=1` has a JSONL mismatch log format before any Rust is
merged.

### Phase 1 — ChangeSpec parser in Rust (highest single-file ROI)

The parser remains the best first Rust target, but the current in-process
`ChangeSpecSnapshotCache` means the win must be measured on cold loads,
changed-file refreshes, and commands that bypass the TUI cache. It is still
mostly pure: bytes in, wire struct out, no global IO.

- Create `rust/sase-core/` cargo workspace.
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
- Ship as a separate wheel (`sase-core-rs`) that `sase` depends on but works
  without (Python fallback stays).
- Add a Rust-side benchmark with `criterion` for a realistic project/archive
  corpus and a Python benchmark that includes FFI conversion cost. The FFI
  number is the one that matters to the TUI.

**Why first:** smallest blast radius, biggest perf win, builds the build
infrastructure (maturin, cibuildwheel matrix for linux/macOS/windows × x86_64
/ arm64) you'll reuse for everything else.

**Do not flip the default** unless the measured end-to-end speedup is meaningful
after cache hits are accounted for. A parser that is 10x faster internally but
only saves 5 ms on warm TUI refreshes is not the next bottleneck.

### Phase 2 — Query evaluator + tokenizer

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

### Phase 3 — Agent / artifact filesystem scan

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

### Phase 4 — Status state machine

Pure state, ~1,450 LOC. Translate transitions and suffix classification to
Rust enums + match arms. Worth doing because:

- It's frequently called during artifact replays.
- An enum-based encoding makes the transition table machine-checkable
  (`assert!(matches!(...))`) — bugs that currently slip through Python tests
  become compile errors.

Lower urgency than Phases 1–3 because it's not the bottleneck; do it once the
build pipeline is mature.

Port the transition table before porting file mutation helpers. The Rust
function should answer "is this transition valid and what field updates should
exist?" and Python should continue doing atomic `.gp` writes until the parser
and source-span contract are proven.

### Phase 5 — Git query ops

Three options, in increasing scope:

- **A.** Keep shelling out to `git`, but parse the output in Rust (`gix`'s
  parsers, or hand-rolled). Cheapest.
- **B.** Use `gix` directly, eliminating the `git` subprocess. Faster, no
  fork overhead, but `gix` doesn't yet support every operation `_git_query_ops.py`
  uses — audit first.
- **C.** Skip. Subprocess overhead is dwarfed by `git`'s own work for log/blame.

Recommend **A** unless profiling shows fork dominance.

### Phase 6 — Server surface for web/mobile

By Phase 6, the Rust crate is the source of truth for parsing, querying, and
scanning. To unlock the web app:

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
  active venv. Add to `just install` so contributors don't have to know.
- **`cibuildwheel`** (or maturin's GH Actions) for the wheel matrix. Target
  cp312+ × {linux x86_64, linux aarch64, macOS universal2, windows x86_64}.
  Skip musllinux unless someone asks.
- **Pure-Python fallback stays installable.** The Rust extension is an
  optional accelerator selected at import time. If the wheel for a platform
  isn't available, `pip install sase` still works; perf is just Python-speed.
  Codify this with a smoke test that runs the suite under
  `SASE_CORE_BACKEND=python`.
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
- **Cargo workspace layout:**
  ```
  rust/
    Cargo.toml          # workspace
    sase-core/          # pure logic, no IO except files
    sase-core-py/       # PyO3 bindings
    sase-core-ffi/      # uniffi bindings (mobile)
    sase-core-wasm/     # wasm-bindgen subset
    sase-server/        # axum binary
  ```

Keep `sase-core` `no_std`-friendly where possible (it isn't really, given
filesystem code, but the parsers can be). That makes the WASM build trivial.

Practical `Justfile` additions once Rust lands:

```make
rust-test:
    cargo test --workspace

rust-fmt:
    cargo fmt --all

rust-check:
    cargo clippy --workspace --all-targets -- -D warnings

core-rs-develop:
    uv run maturin develop -m rust/sase-core-py/Cargo.toml
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

---

## 8. Recommended first concrete action

1. Land **Phase 0.5** as a small PR: formal `ChangeSpecWire` /
   `ParseErrorWire` schema, `sase.core` parser facade, JSON serialization
   tests, and `SASE_CORE_BACKEND` / `SASE_CORE_DUAL_RUN` plumbing. No Rust yet.
2. Build a sanitized golden corpus from real `.gp` files and query strings.
   Include malformed specs, archive files, suffix cases, comments, mentors,
   hooks, commits drawers, missing trailing newlines, and non-ASCII paths /
   descriptions.
3. Spike **Phase 1** in a branch: `rust/sase-core/` with
   `parse_project_bytes` and PyO3 bindings, hand-built locally with
   `maturin develop`. Run the golden corpus against it. If parity holds, wire
   wheel builds and merge gated behind the env var (default still `python`).
   Flip default to `rust` only after a full release cycle of dual-running.
4. Use the perf measurements from `sase_perf_research.md` (the
   `SASE_TUI_TRACE=1` plan) to **prove** the win on real `~/.sase/` data
   before continuing. Skip phases that don't show wins; reorder by what
   actually hurts.

The discipline that makes this work: **never port ahead of measurement, and
never delete the Python implementation until two release cycles after the
Rust one is the default.** That's how you get a gradual migration that
doesn't take the TUI down.

---

## References

- `research/202604/sase_perf_research.md` — TUI hot-path analysis, refresh
  paths, j/k navigation cost.
- `research/202604/sase_perf_v2_research.md` — kill/dismiss/launch I/O
  audit; identifies remaining synchronous notification I/O.
- `research/202604/tui_profiling_strategies.md` — proposed
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
