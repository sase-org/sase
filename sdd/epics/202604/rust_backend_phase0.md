---
create_time: 2026-04-28 23:51:28
status: done
bead_id: sase-14
prompt: sdd/prompts/202604/rust_backend_phase0.md
---
# Rust Backend Migration Phase 0 Plan

## Context

`sdd/research/202604/rust_backend_migration.md` defines Phase 0 as the Python-only seam for a later Rust backend. The repo
already has important Phase 0-style optimizations:

- `ChangeSpecSnapshotCache` in `src/sase/ace/changespec/cache.py`.
- `QueryEvaluationContext` and `evaluate_query_with_context()` in `src/sase/ace/query/evaluator.py`.
- `ChangeSpecGraphIndex` in `src/sase/ace/tui/models/changespec_graph_index.py`.
- `src/sase/core/` exists, but it is currently utility-focused rather than a backend facade.

The missing foundation is a stable wire contract, env-driven backend dispatch, dual-run mismatch logging, and routing
hot public APIs through `sase.core` without changing TUI behavior.

`../sase-core` already exists but only as a repo shell. Phase 0 should not add Rust code there; it should leave a
contract that a later agent can implement against.

## Agent Phase Split

### Phase 0A: Python Core Facade and Wire Contract

Goal: create the stable Python seam that later Rust bindings can replace.

Scope:

- Add `sase.core` backend selection helpers for `SASE_CORE_BACKEND={python,rust}` with default `python`.
- Add `SASE_CORE_DUAL_RUN=1` helpers that record JSONL comparison records under `~/.sase/perf/core_dual_run.jsonl`.
- Add typed/dataclass wire records for:
  - `SourceSpanWire`
  - `RawChangeSpecWire`
  - `SectionWire`
  - `CommitWire`
  - `HookWire`
  - `CommentWire`
  - `MentorWire`
  - `TimestampWire`
  - `DeltaWire`
  - `ChangeSpecWire`
  - `ParseErrorWire`
- Add conversion helpers from current Python `ChangeSpec` dataclasses to wire records and JSON-safe dicts.
- Add `sase.core` facades for:
  - ChangeSpec project parsing and wire parsing.
  - Query parsing/evaluation/context construction.
  - ChangeSpec graph index construction.
  - Status transition entry points and pure status field helpers.
- Keep the Rust backend optional and unavailable in Phase 0A. `SASE_CORE_BACKEND=rust` should fail clearly instead of
  silently changing behavior.

Exit criteria:

- `pytest -k core` covers the new seam.
- Existing public Python behavior remains unchanged under the default backend.
- Dual-run has a documented and tested JSONL record shape before Rust exists.

### Phase 0B: Public API Routing

Goal: move existing public entry points onto the facade without a broad call-site churn.

Scope:

- Route public functions in existing modules through `sase.core` wrappers:
  - `sase.ace.changespec.parser.parse_project_file`
  - `sase.ace.query.parser.parse_query`
  - `sase.ace.query.evaluator.build_query_context`
  - `sase.ace.query.evaluator.evaluate_query`
  - `sase.ace.query.evaluator.evaluate_query_with_context`
  - `sase.ace.tui.models.changespec_graph_index.build_changespec_graph_index`
  - `sase.status_state_machine.transitions.transition_changespec_status`
  - selected pure helpers in `sase.status_state_machine.field_updates`
- Preserve private Python implementations with `_python` names so the facade has a stable default backend and tests can
  bypass dispatch where needed.
- Do not convert every import site manually. Keeping existing public APIs as thin facade shims gives the TUI and CLI the
  seam without a noisy repository-wide edit.

Exit criteria:

- Representative existing tests for parser, query, graph index, and status transitions still pass.
- Existing monkeypatch paths used by tests continue to work.

### Phase 0C: Golden Contract Tests

Goal: establish diff-friendly examples that a Rust implementation must match.

Scope:

- Add a sanitized in-test `.gp` corpus covering:
  - headered and direct `NAME:` specs
  - parent, CL/PR, BUG, status, description, test targets, kickstart
  - commits with drawers, hooks/status lines, comments, mentors, timestamps, deltas
  - archive/terminal statuses and sibling suffixes
- Add inline-snapshot assertions for:
  - `ChangeSpecWire` JSON-safe output
  - query canonical parse output
  - query evaluation results over the corpus
  - graph index summary output
  - status field read/update helpers
- Add tests for backend selection and dual-run logging using fake Rust callables, not a real Rust extension.

Exit criteria:

- Golden tests are stable and self-contained.
- No test touches the user's real `~/.sase` state.

### Phase 0D: Verification and Documentation

Goal: make the seam discoverable for future Rust agents.

Scope:

- Add short module docstrings explaining the backend boundary and why Rust is optional.
- Verify with:
  - `just install`
  - focused `pytest -k core`
  - focused existing parser/query/status tests
  - `just check` before handoff
- Update this plan or final handoff with the exact files and tests changed.

Exit criteria:

- Full repo check passes or any failures are documented with concrete causes.
- The next agent can start Phase 1 in `../sase-core` by implementing the wire contract instead of rediscovering Python
  behavior.

## Phase 1 Handoff Shape

After Phase 0 lands, a distinct agent should start Rust work in `../sase-core`:

- Create the Rust workspace layout.
- Implement `parse_project_bytes(path, bytes) -> Vec<ChangeSpecWire>` first.
- Expose PyO3 bindings as an optional `sase_core_rs` module.
- Run the Phase 0 golden corpus against both Python and Rust via `SASE_CORE_BACKEND=rust` and `SASE_CORE_DUAL_RUN=1`.
- Do not flip the default backend until measured end-to-end wins exist.

## Phase 0D Handoff (this phase)

Documentation-only changes plus verification. No production behavior changed.

### Files touched

- `src/sase/core/__init__.py` — expanded the package docstring with explicit
  "backend boundary" and "why Rust is optional" sections, and pointed at
  this plan from the docstring.
- `src/sase/core/parser_facade.py` — replaced the Phase 0A/0B-bound docstring
  with one that describes the seam itself and how a Rust impl plugs in.
- `src/sase/core/query_facade.py` — same treatment; called out the
  ``*_python`` aliasing pattern that lets tests bypass dispatch.
- `src/sase/core/graph_index_facade.py` — same treatment.
- `src/sase/core/status_facade.py` — clarified pure helpers vs. the
  IO-bearing transition and the recommended Rust adoption order.

### Where the seam lives

| Public API still in use today                                                                | Facade entry point                                            |
| -------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `sase.ace.changespec.parser.parse_project_file`                                              | `sase.core.parser_facade.parse_project_file` (+ `_bytes`)     |
| `sase.ace.query.parser.parse_query`                                                          | `sase.core.query_facade.parse_query`                          |
| `sase.ace.query.evaluator.build_query_context`                                               | `sase.core.query_facade.build_query_context`                  |
| `sase.ace.query.evaluator.evaluate_query`                                                    | `sase.core.query_facade.evaluate_query`                       |
| `sase.ace.query.evaluator.evaluate_query_with_context`                                       | `sase.core.query_facade.evaluate_query_with_context`          |
| `sase.ace.tui.models.changespec_graph_index.build_changespec_graph_index`                    | `sase.core.graph_index_facade.build_changespec_graph_index`   |
| `sase.status_state_machine.transitions.transition_changespec_status`                         | `sase.core.status_facade.transition_changespec_status`        |
| `sase.status_state_machine.field_updates.read_status_from_lines` / `apply_status_update`     | `sase.core.status_facade.read_status_from_lines` / `apply_status_update` |

The Python implementations remain importable under both their original
public paths and the facade's ``_python_*`` aliases. Phase 1 should call
through the facade entry points and register `rust_impl` arguments via
`sase.core.backend.dispatch` rather than monkeypatching the originals.

### Verification

- `just install` — succeeded (editable install, dev extras).
- Focused core tests — `pytest tests/test_core_backend.py
  tests/test_core_dual_run.py tests/test_core_facade.py
  tests/test_core_wire.py tests/test_core_golden.py` — **65 passed**.
- Focused parser/query/graph/status tests — `pytest tests/test_query_parser.py
  tests/test_query_evaluator.py tests/test_query_evaluator_extra.py
  tests/test_query_canonicalization.py tests/test_query_property_filters.py
  tests/test_query_selection.py
  tests/test_status_state_machine_transitions.py
  tests/test_status_state_machine_field_updates.py
  tests/test_commit_parsing.py tests/test_commits_multiline_body.py
  tests/test_deltas_parsing.py tests/test_hooks_core.py tests/test_mentors.py
  tests/test_ancestors_children_panel.py` — **141 passed**.
- `just check` — see commit message for the post-handoff result.

### Next agent

Phase 1 starts from `../sase-core` and the wire contract in
`src/sase/core/wire.py`. The golden corpus under `tests/core_golden/` plus
`tests/test_core_golden.py` is the cross-implementation acceptance test:
running it with `SASE_CORE_BACKEND=rust` and `SASE_CORE_DUAL_RUN=1` once a
Rust `parse_project_bytes` exists is the agreed proof of contract parity.
