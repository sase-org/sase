---
create_time: 2026-04-29 13:30:00
bead_id: sase-19.2
status: complete
---
# Rust Backend Phase 4B Handoff: Wire Contract and Golden Parity Corpus

## Scope

This phase defines the cross-language contract for the status state machine
**without** routing any production call site to the new Rust planner. Rust
implementation lands in Phase 4C.

## What landed

### Wire records (`src/sase/core/status_wire.py`)

- `StatusTransitionRequestWire` — pre-gathered inputs for one transition
  decision: `changespec_name`, `old_status`, `new_status`, `validate`, plus
  `parent_status`, `blocking_children`, `siblings_with_unreverted_children`,
  and `existing_names`. The host is responsible for I/O — the planner only
  sees primitive wire values.
- `StatusTransitionPlanWire` — what the host should do on success: a
  `status_update_target` to write, a `suffix_action` (`none` / `strip` /
  `append`) with `suffixed_name` / `base_name`, a `mentor_draft_action`
  (`none` / `set_draft` / `clear_draft`), an `archive_action` (`none` /
  `to_archive` / `from_archive`), a `timestamp_event` and
  `timestamp_target_name`, and a `revert_siblings` flag. On failure
  carries `success=False`, `old_status`, and a verbatim `error` string.
- `ChangespecChildWire` — `(name, status)` projection of the few
  ChangeSpec fields the planner consults.
- `StatusFieldReadWire` / `StatusFieldUpdateWire` — structured forms of
  the line-helper inputs so the Phase 4C PyO3 binding can accept dicts.
- `STATUS_WIRE_SCHEMA_VERSION = 1`. Bump this on shape changes.
- `status_wire_to_json_dict` / `status_request_from_dict` /
  `status_plan_from_dict` round-trip the records through plain JSON for
  the future Rust adapter.
- Action-name constants exported as a stable enumeration:
  `SUFFIX_ACTION_*`, `MENTOR_ACTION_*`, `ARCHIVE_ACTION_*`.

### Python planner + converter (`src/sase/core/status_wire_conversion.py`)

- `plan_status_transition_python(request)` is the pure decision engine.
  It mirrors `transition_changespec_status_python` branch-for-branch:
  - `Ready -> Draft`: blocking-children check, validate, suffix append,
    mentor draft set;
  - `WIP -> Draft`: validate-only (no suffix, no mentor);
  - `new_status = Reverted` / `Archived`: own branches, validate-only;
  - generic "ready"-style branch (Mailed, Submitted, Ready): parent
    constraint, validate, sibling-unreverted-children check (when
    suffixed and old in WIP/Draft), suffix strip, mentor clear
    (Draft→Ready only).
- Error strings match the existing Python handlers verbatim so the
  Phase 4C / 4D facade swap doesn't change CLI/TUI output.
- `_classify_archive_action` preserves the literal
  `old_status in ARCHIVE_STATUSES` compare from
  `transition_changespec_status_python` lines 142–167. Workspace-suffixed
  archive statuses are unusual in practice; if a follow-up wants to
  normalise they should change Python and Rust together.
- `build_status_transition_request(project_file, changespec_name,
  old_status, new_status, validate)` performs all Python-only I/O the
  planner needs: parses the in-project ChangeSpec list, looks up the
  parent's base status, and (when relevant) walks `find_all_changespecs()`
  for the cross-project `existing_names`, the Ready→Draft
  `blocking_children`, and the sibling-unreverted-children pre-flight.

### Golden tests

- `tests/test_core_status_wire.py` — 26 tests covering:
  - JSON round-trip for both wire records;
  - schema-version mismatch raises;
  - invalid transitions with `validate=True` rejected, `validate=False`
    allowed (matches the archive-restore escape hatch);
  - workspace suffix stripping;
  - legacy `READY TO MAIL` suffix stripping;
  - WIP→Draft simple branch (no suffix, no mentor);
  - Ready→Draft suffix append + mentor set, lowest-free-suffix selection,
    blocking-children rejection;
  - WIP/Draft→Ready suffix strip, sibling-unreverted-children rejection,
    mentor clear on Draft→Ready;
  - parent constraint blocks Ready→Mailed when parent is WIP/Draft, but
    not when parent is Ready;
  - terminal statuses (Reverted, Archived, Submitted) reject further
    transitions;
  - archive-action classification (`to_archive`, `from_archive`,
    `none` for both same-class cases).
- `tests/test_core_status_lines.py` — 8 tests pinning
  `read_status_from_lines` and `apply_status_update`: workspace suffix
  passthrough, multi-changespec selectivity, missing-name no-op,
  idempotent rewrite when the status already matches.

### Documentation

- `docs/rust_backend.md` — added `status_wire.py` /
  `status_wire_conversion.py` to the facade module table; added a
  Phase 4B roadmap entry summarising the wire surface and the
  Phase 4C/4D handoffs that consume it.

## What did **not** change

- No production caller has been routed to `plan_status_transition_python`.
  `transition_changespec_status` still goes through
  `transition_changespec_status_python` end-to-end.
- `status_facade.py` is unchanged.
- `sase_core_rs` is untouched (Phase 4C work).
- Default backend stays `python`.

## Files added

- `src/sase/core/status_wire.py`
- `src/sase/core/status_wire_conversion.py`
- `tests/test_core_status_wire.py`
- `tests/test_core_status_lines.py`
- `plans/202604/rust_backend_phase4_status_machine_phase4b_handoff.md` (this file)

## Files changed

- `docs/rust_backend.md`

## Commands run

```bash
just install
.venv/bin/pytest tests/test_core_status_wire.py tests/test_core_status_lines.py
just check
```

## Phase 4A note

Phase 4A's profiling handoff was not committed before this phase began.
The plan in `plans/202604/rust_backend_phase4_status_machine.md` lists
the expected operation set, and Phase 4B implements it conservatively:
the wire only encodes operations the existing facade already covers
(`read_status_from_lines`, `apply_status_update`,
`plan_status_transition`). If a later profiling pass shows additional
helpers worth porting, extend the wire and bump
`STATUS_WIRE_SCHEMA_VERSION`.

## Hand-off to Phase 4C

The Rust agent should:

1. Clone the wire structs as serde-compatible types in
   `../sase-core/crates/sase_core/src/status/`. Match field names and
   the action-string enumerations exactly.
2. Implement `plan_status_transition` as a pure function over the
   request, returning a plan with the same field set. Reuse the same
   error strings — the parity tests in `tests/test_core_status_wire.py`
   check substring matches that depend on the exact format.
3. Reproduce `_classify_archive_action`'s literal
   `old_status in ARCHIVE_STATUSES` compare; do not normalise the
   workspace suffix when classifying.
4. Expose PyO3 bindings that take/return plain Python dicts — the
   adapter on the Python side uses
   `status_wire.status_plan_from_dict` to rehydrate the result.
5. Add Rust unit tests mirroring the
   `tests/test_core_status_wire.py` cases.

Phase 4D will register the bindings on the facade. Phase 4E will route
`plan_status_transition` through the facade with side effects still
executed in Python.
