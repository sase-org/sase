---
create_time: 2026-04-29 00:52:11
status: done
bead_id: sase-16
prompt: sdd/prompts/202604/rust_backend_phase1.md
---
# Rust Backend Migration Phase 1 Plan

## Context

`sdd/research/202604/rust_backend_migration.md` defines Phase 1 as the first real Rust backend target: a ChangeSpec parser
that can parse a full project/archive `.gp` file from bytes into the stable `ChangeSpecWire` contract.

Phase 0 is already complete in this checkout:

- `src/sase/core/wire.py` defines the Python wire records and JSON-safe projection helpers.
- `src/sase/core/parser_facade.py` exposes `parse_project_file()` and `parse_project_bytes()`.
- `src/sase/core/backend.py` supports `SASE_CORE_BACKEND={python,rust}` and dual-run dispatch.
- `src/sase/core/dual_run.py` writes `~/.sase/perf/core_dual_run.jsonl` comparison records.
- `tests/core_golden/` and `tests/test_core_golden.py` pin the current Python behavior.

The sibling `../sase-core` repository already exists but is effectively empty. Phase 1 should build the Rust parser
there, then integrate it into this Python repo as an optional accelerator. The Python backend remains the default until
parity and end-to-end performance are proven.

## Phase Split for Distinct Agent Instances

Each subphase below is intended for one separate `claude` / `gemini` / `codex` agent instance. Later agents should read
this whole plan, but they should only own their listed write scope.

### Phase 1A: Rust Workspace and Wire Types

Goal: create the Rust project structure and typed wire model without touching Python behavior.

Write scope:

- `../sase-core/`
- Documentation or metadata files needed inside that repo

Work:

- Initialize a Cargo workspace in `../sase-core`.
- Add a pure Rust crate for core logic. Use a crate name that can later support bindings cleanly, such as `sase_core`.
- Add a separate PyO3 binding crate placeholder, such as `sase_core_py`, but do not publish or integrate it yet.
- Add `rust-toolchain.toml`, committed `Cargo.lock`, basic README instructions, and CI-friendly commands.
- Model the Phase 0 wire contract in Rust using owned data only:
  - `SourceSpanWire`
  - `CommitWire`
  - `HookStatusLineWire`
  - `HookWire`
  - `CommentWire`
  - `MentorStatusLineWire`
  - `MentorWire`
  - `TimestampWire`
  - `DeltaWire`
  - `ChangeSpecWire`
  - `ParseErrorWire`
- Derive `serde::Serialize`, `serde::Deserialize`, `Debug`, `Clone`, and `PartialEq` where appropriate.
- Add JSON serialization tests that compare representative Rust JSON against the Python wire shape from
  `src/sase/core/wire.py`.

Dependencies and design constraints:

- Prefer stable, low-risk crates: `serde`, `serde_json`, `thiserror`, and a parser helper only when the parser phase
  needs it.
- Keep the pure Rust crate free of PyO3 types.
- Do not read global config, discover projects, or call plugins from Rust.

Exit criteria:

- `cargo fmt --all` passes.
- `cargo test --workspace` passes.
- The Rust repo documents how to build and test locally.
- No changes are made to `sase_100` production code in this phase.

### Phase 1B: Minimal Full-File Parser Skeleton

Goal: implement the project-file scanning contract in Rust, starting with fields and source spans.

Write scope:

- `../sase-core/` parser implementation and tests
- Optional fixture copies under `../sase-core/tests/fixtures/`

Work:

- Implement `parse_project_bytes(path: &str, data: &[u8]) -> Result<Vec<ChangeSpecWire>, ParseErrorWire>`.
- Match the Python parser's ChangeSpec boundaries:
  - `## ChangeSpec` headers are skipped and the following lines belong to the spec.
  - A direct `NAME: ` line can start a spec without a header.
  - The next `## ChangeSpec`, a second blank line, or a new `NAME: ` in the same parse window ends the current spec.
  - Incomplete records without both `NAME` and `STATUS` are ignored, matching current Python behavior.
- Parse the core scalar fields first:
  - `NAME`
  - `DESCRIPTION`
  - `PARENT`
  - `CL` / `PR` into `cl_or_pr`
  - `BUG`
  - `STATUS`
  - `TEST TARGETS`
  - `KICKSTART`
- Preserve Python whitespace semantics:
  - Inline description/kickstart content after the header is stripped.
  - Two-space continuation lines remove the first two spaces and preserve internal text.
  - Blank lines inside description/kickstart are preserved before final trim.
  - Test targets use stripped two-space continuation content.
- Fill `project_basename` the same way Python `ChangeSpec.project_basename` does.
- Fill `source_span.start_line` and `source_span.end_line` as inclusive 1-based lines. Rust should improve on Phase 0's
  Python placeholder end line.

Exit criteria:

- Rust unit tests cover headered specs, direct `NAME:` specs, ignored incomplete specs, multi-line description, inline
  fields, and span boundaries.
- `cargo test --workspace` passes.
- The parser output for scalar-only fixtures matches the equivalent Python `ChangeSpecWire` JSON except for the intended
  improved `source_span.end_line`.

### Phase 1C: Section Parser Parity

Goal: complete the Rust parser so it matches Python section semantics for the current wire contract.

Write scope:

- `../sase-core/` parser implementation and tests
- Optional additional Rust fixtures

Work:

- Port the section behavior from:
  - `src/sase/ace/changespec/parser.py`
  - `src/sase/ace/changespec/section_parsers.py`
  - `src/sase/ace/changespec/suffix_utils.py`
- Implement section parsing for:
  - `COMMITS`
  - `HOOKS`
  - `COMMENTS`
  - `MENTORS`
  - `TIMESTAMPS`
  - `DELTAS`
- Preserve suffix parsing exactly enough for the golden corpus and known suffix types:
  - error markers such as `!:`
  - running agent markers such as `@:`
  - killed/rejected markers already accepted by Python
  - mentor entry-ref suffixes
  - hook summary compound suffixes split on the first `|`
- Preserve commit body semantics:
  - `(N)` and `(Na)` entries.
  - `| CHAT:`, `| DIFF:`, and `| PLAN:` drawers.
  - Six-space body continuation lines.
  - A body line containing `.` becomes an empty string.
- Preserve DELTAS glyph mapping: `+ -> A`, `~ -> M`, `- -> D`.
- Add a Rust golden test using the exact `sase_100/tests/core_golden/*.gp` files or copied sanitized fixtures.

Exit criteria:

- The Rust parser can produce JSON matching the Python golden corpus, with a documented normalization for end-line spans
  if the Python snapshot still uses placeholder end lines.
- `cargo test --workspace` passes.
- Any intentional incompatibility is written down in `../sase-core/README.md` before integration starts.

### Phase 1D: PyO3 Binding and Local Python Adapter

Goal: expose the Rust parser to Python without changing the default backend.

Write scope:

- `../sase-core/` PyO3 crate
- `sase_100/src/sase/core/backend.py`
- `sase_100/src/sase/core/parser_facade.py`
- focused tests under `sase_100/tests/`
- build/dev docs in either repo as needed

Work:

- Implement a PyO3 module importable from Python as `sase_core_rs`.
- Expose a stateless function:
  - `parse_project_bytes(path: str, data: bytes) -> list[dict]`
- Convert Rust wire records to Python-native dict/list/string/bool/int/None values at the boundary. Avoid PyO3 classes
  in Phase 1.
- Update `sase.core.backend.is_rust_available()` to probe `sase_core_rs`.
- Update `sase.core.parser_facade.parse_project_bytes()` to pass a `rust_impl` to `dispatch()`.
- Keep `parse_project_file()` on the Python backend for now unless the adapter can parse bytes after reading the file
  without bypassing dual-run logging.
- Add conversion helpers from Rust dict output to Python `ChangeSpecWire` dataclasses if the facade's public return type
  remains `list[ChangeSpecWire]`.
- Add tests for:
  - Rust module unavailable: current clear failure behavior remains.
  - Rust module available via monkeypatch/fake module: `SASE_CORE_BACKEND=rust` calls the Rust implementation.
  - `SASE_CORE_DUAL_RUN=1` compares Python and Rust-shaped results and returns Python output.

Exit criteria:

- `SASE_CORE_BACKEND=python` behavior is unchanged.
- `SASE_CORE_BACKEND=rust` works for `parse_project_bytes()` when `sase_core_rs` is installed.
- Dual-run logs parity records for `parse_project_bytes()`.
- Focused Python tests pass.

### Phase 1E: Dev Workflow, Benchmarks, and Packaging Decision

Goal: make Phase 1 usable by agents and contributors without making Rust mandatory.

Write scope:

- `sase_100/Justfile`
- `sase_100/pyproject.toml` if optional dev/build dependencies are needed
- `sase_100/tests/` for benchmark/parity smoke tests
- `../sase-core/` benchmark files and docs
- CI files only if the workflow is ready and low-risk

Work:

- Add local development commands that do not break Python-only installs:
  - install/build the PyO3 module from `../sase-core`
  - run Rust tests
  - run Rust fmt/clippy when the sibling repo is present
- Add a Python benchmark that measures:
  - Python direct parse
  - Python facade parse
  - Rust via PyO3 parse
  - optional dual-run overhead
- Add a Rust benchmark for direct parser cost over the golden corpus and at least one larger synthetic project file.
- Decide whether `sase` depends on a separately built wheel or only detects `sase_core_rs` opportunistically for now.
  Keep pure-Python install working either way.
- Do not add a mandatory CI Rust build until the local workflow is stable. If CI is added, it must not make Python-only
  test jobs depend on Rust packaging availability.

Exit criteria:

- `just install` still works without Rust installed.
- A contributor with Rust installed can build the extension locally and run dual-run parity.
- Benchmarks report end-to-end PyO3 conversion cost, not only internal Rust parser time.

### Phase 1F: Cross-Repo Parity Gate and Handoff

Goal: finish Phase 1 with a reliable adoption gate and clear next-step evidence.

Write scope:

- `sase_100/tests/`
- `sase_100/sdd/research/` or `sase_100/plans/202604/` for result notes
- `../sase-core/` docs if needed

Work:

- Add or document a parity command that runs the golden corpus through both backends.
- Compare JSON output byte-for-byte after agreed normalization. If Rust now reports real end lines, either:
  - update the Python golden expectations and conversion helpers to calculate end lines too, or
  - normalize end lines only inside the parity test and record the follow-up work explicitly.
- Run targeted verification:
  - `cargo test --workspace` in `../sase-core`
  - focused Python core tests in `sase_100`
  - parser-related tests in `sase_100`
  - `just check` in `sase_100` if any files in this repo changed
- Record benchmark results and the go/no-go decision for making Rust a default candidate later.

Exit criteria:

- Phase 1 is complete when `parse_project_bytes()` can run through Rust from Python under an explicit backend flag and
  the golden corpus parity story is documented.
- The default backend remains Python.
- The Python fallback remains tested.
- The handoff states whether Phase 2 should proceed to query evaluation or whether parser/span parity debt must be paid
  first.

## Recommended Execution Order

Run phases strictly in order. Phase 1D should not start until Phase 1C's Rust parser has section parity in direct Rust
tests, because binding an incomplete parser into Python will create noisy dual-run mismatches. Phase 1E can overlap only
after 1D exposes a stable local build command, but it should still be a separate agent instance to avoid mixing parser
semantics with packaging choices.

## Non-Goals for Phase 1

- Do not port query parsing/evaluation.
- Do not port graph indexing.
- Do not port status transitions.
- Do not add server, UniFFI, or WASM crates beyond harmless workspace placeholders.
- Do not remove or degrade the Python parser.
- Do not flip `SASE_CORE_BACKEND` default away from `python`.
- Do not require Rust for normal `pip install -e ".[dev]"` or `just install`.

## Risk Notes

- The current Python `changespec_to_wire()` uses `source_span.end_line == start_line` because the Python parser does not
  track end lines. Rust should track real end lines, but parity tests must decide whether to normalize that difference
  or first improve the Python facade.
- The Python `parse_project_bytes()` implementation writes bytes to a temporary file and reparses from disk. Rust should
  parse bytes directly, so benchmark comparisons must include Python facade overhead separately from Python direct
  parse.
- PyO3 calls should be coarse-grained. Do not expose a per-line or per-section Python API.
- Keep the pure Rust crate independent from PyO3 so later UniFFI/WASM/server work can reuse the same logic.
- The sibling repo is separate git state. Agents must check and report both repos' `git status` before handoff.
