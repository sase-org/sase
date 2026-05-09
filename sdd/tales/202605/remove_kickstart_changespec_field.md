---
create_time: 2026-05-09 01:53:06
status: done
prompt: sdd/prompts/202605/remove_kickstart_changespec_field.md
---
# Remove the KICKSTART ChangeSpec field

## Goal

Remove `KICKSTART` as a supported ChangeSpec field everywhere it is modeled, parsed, serialized, displayed, searched,
documented, or tested. After this change, `KICKSTART:` should not be a recognized ChangeSpec section, should not appear
in Python or Rust wire records, and should not be emitted by CLI/TUI/clipboard/search renderers.

## Current Shape

The field is currently first-class in both the Python app repo and the sibling Rust core repo:

- Python domain model: `src/sase/ace/changespec/models.py` has `ChangeSpec.kickstart`.
- Python parser: `src/sase/ace/changespec/parser.py` recognizes `KICKSTART:` and continuation lines.
- Python wire: `src/sase/core/wire.py` and `src/sase/core/wire_conversion.py` include `kickstart`.
- Rust wire/parser/query: `../sase-core/crates/sase_core/src/wire.rs`, `parser.rs`, and `query/searchable.rs` include
  `kickstart`.
- Output surfaces: `src/sase/main/search_handler.py`, `src/sase/ace/display.py`,
  `src/sase/ace/tui/widgets/changespec_detail.py`, and clipboard helpers emit it.
- Section-order and mutation guards include `KICKSTART:` as a known header in status, hooks, deltas, accept, and commit
  utilities.
- Docs and query docs list the field.
- Fixtures and golden snapshots include `KICKSTART:` or `"kickstart"`.
- Many tests instantiate `ChangeSpec(..., kickstart=None)` and will need mechanical cleanup.

## Implementation Plan

1. Remove the field from the Python ChangeSpec model and parser.
   - Delete `kickstart` from `ChangeSpec`.
   - Remove parser state for `kickstart_lines` / `in_kickstart`.
   - Remove `KICKSTART:` recognition and continuation handling.
   - Keep parser behavior tolerant of legacy project files by treating `KICKSTART:` as unrecognized content rather than
     failing.

2. Remove the field from the Python wire contract.
   - Delete `kickstart` from `ChangeSpecWire`.
   - Remove `record.get("kickstart")` and `cs.kickstart` conversion paths.
   - Update wire tests and snapshots so `"kickstart"` is absent, not `null`.

3. Remove the field from the Rust core contract and parser.
   - Delete `kickstart` from `ChangeSpecWire`.
   - Remove parser state and `KICKSTART:` handling.
   - Remove query searchable-text contribution.
   - Update Rust tests, parity fixtures, snapshots, and README references.
   - Watch field-order and JSON parity tests carefully because this is a schema shape change.

4. Remove downstream behavior in Python.
   - Delete KICKSTART rendering from CLI search output and markdown search output.
   - Delete KICKSTART rendering from rich/TUI ChangeSpec detail views.
   - Delete KICKSTART emission from clipboard formatting.
   - Remove KICKSTART from searchable text and query docs.
   - Remove KICKSTART from section/header ordering lists used by status updates, hooks, deltas, accept, commit tracking,
     and commit utilities.

5. Update tests, helpers, and fixtures.
   - Mechanically remove `kickstart=` arguments from `ChangeSpec(...)` constructors and helper factories.
   - Delete tests whose only purpose is verifying KICKSTART output/search.
   - Update golden `.gp` fixtures by removing KICKSTART sections.
   - Update Python and Rust JSON snapshots so the field is absent everywhere.
   - Keep unrelated ChangeSpec fields and ordering stable.

6. Sweep for leftovers.
   - Run `rg -n --hidden -S "KICKSTART|Kickstart|kickstart"` in this repo excluding generated SDD history only if needed
     for signal, then run it across `../sase-core`.
   - Remaining hits should be only historical SDD prompt/tale content or unrelated prose; live code, docs, tests,
     fixtures, and contracts should have no references.

7. Verify.
   - Run `just install` in this workspace before checks, per repo instructions.
   - Run targeted Python tests around parsing, wire conversion, search/clipboard/display, status mutations, and core
     golden snapshots.
   - Run relevant Rust core tests from `../sase-core`, especially parser, wire, query, and parity tests.
   - Run `just check` in this repo before finishing because code files changed.

## Risks and Decisions

- This is a breaking wire-shape change. The implementation should remove the key entirely rather than serializing
  `"kickstart": null`, because the user asked to remove the field.
- Existing project files that still contain `KICKSTART:` should not crash parsing. They will simply no longer produce
  any modeled data or rendered output.
- SDD history files may preserve old prompts that mention KICKSTART. I will treat those as archival unless they are live
  docs, fixtures, or executable tests.
