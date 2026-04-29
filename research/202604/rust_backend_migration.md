# Migrating the SASE TUI Back End to Rust (Gradual, Multi-Frontend)

**Goal:** move the slow, non-UI logic underneath `sase ace` (the Textual TUI) into a
Rust core that can be shared with future SASE web and mobile front ends, without a
big-bang rewrite. The TUI keeps working at every step.

This research is grounded in the existing performance analyses
(`sase_perf_research.md`, `sase_perf_v2_research.md`,
`tui_profiling_strategies.md`) and a code map of the current Python modules.

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

## 3. Migration order (lowest risk → highest leverage)

### Phase 0 — Establish the seam in Python (no Rust yet)

Before introducing Rust, codify the boundary that Rust will replace. This makes
every later step a 1-file swap instead of a refactor.

1. Create `src/sase/core/` as a Python package re-exporting the *current*
   pure-logic functions (changespec parsing, query eval, state machine). The
   TUI imports only from `sase.core`.
2. Add a thin **schema layer**: dataclasses become `pydantic`-style models or
   plain `TypedDict`s with explicit JSON shapes. No behavior changes — just
   names, fields, and serialization tests.
3. Write **golden tests**: capture a corpus of real `.gp` files, real query
   strings, and the parser's output. These become the contract Rust must
   match. Use `inline-snapshot` (already a dev dep) for diff-friendly review.
4. Add a `SASE_CORE_BACKEND={python,rust}` env-var dispatch in
   `sase.core.__init__`. Default `python`. This is the toggle for all later
   phases.

**Exit criterion:** TUI is unaffected; `pytest -k core` covers the seam end to
end.

### Phase 1 — ChangeSpec parser in Rust (highest single-file ROI)

The parser is the single hottest module: every TUI refresh, every `sase ace`
startup, every agent scan re-parses `.gp` files. It's also pure: bytes in,
struct out, no IO.

- Create `rust/sase-core/` cargo workspace.
- Implement `parse_changespec(&[u8]) -> ChangeSpec` matching
  `section_parsers.py` semantics. Lean on `winnow` or `nom` for the section
  state machine; `serde` for downstream serialization.
- Expose via PyO3:
  ```rust
  #[pyfunction]
  fn parse_changespec(data: &[u8]) -> PyResult<PyObject> { ... }
  ```
- Behind the `SASE_CORE_BACKEND=rust` flag, route Python calls to the
  extension. Run the golden tests against both backends in CI to prove
  equivalence.
- Ship as a separate wheel (`sase-core-rs`) that `sase` depends on but works
  without (Python fallback stays).

**Why first:** smallest blast radius, biggest perf win, builds the build
infrastructure (maturin, cibuildwheel matrix for linux/macOS/windows × x86_64
/ arm64) you'll reuse for everything else.

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

### Phase 3 — Agent / artifact filesystem scan

This is the one most users will *feel*. `_lookup.py` walks
`~/.sase/projects/*/artifacts/ace-run/*/agent_meta.json` synchronously and
parses each. In Rust:

- Use `walkdir` + `rayon` for parallel directory walking.
- Use `simd-json` or `sonic-rs` for JSON parsing.
- Expose a **streaming** iterator (`fn scan_agents() -> impl Iterator<Item = Agent>`)
  rather than returning a giant list. The TUI can render the first frame as
  results arrive — this is a UX win independent of raw speed.
- On the PyO3 side, the function returns an async generator (`pyo3-async-runtimes`)
  that the existing `_load_agents_async` can consume from `asyncio.to_thread`.

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

---

## 4. Build, packaging, and distribution

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

---

## 5. Risks and gotchas

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
- **Datetime / path encoding.** Python `pathlib.Path` and `datetime.datetime`
  have to round-trip through Rust losslessly. Standardize on UTC ISO-8601
  strings and bytes-not-str for paths at the FFI boundary.
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

---

## 6. Recommended first concrete action

1. Land **Phase 0** as a single PR: `src/sase/core/` package + golden tests +
   `SASE_CORE_BACKEND` toggle. No Rust. Reviewable in an hour.
2. Spike **Phase 1** in a branch: `rust/sase-core/` with `parse_changespec`
   and PyO3 bindings, hand-built locally with `maturin develop`. Run the
   golden corpus against it. If parity holds, wire `cibuildwheel` and
   merge gated behind the env var (default still `python`). Flip default to
   `rust` only after a full release cycle of dual-running.
3. Use the perf measurements from `sase_perf_research.md` (the
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
- maturin: <https://www.maturin.rs>
- UniFFI: <https://mozilla.github.io/uniffi-rs/>
- `gix` (pure-Rust git): <https://github.com/Byron/gitoxide>
