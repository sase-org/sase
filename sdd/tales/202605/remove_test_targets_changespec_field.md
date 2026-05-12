---
create_time: 2026-05-12 15:44:00
status: done
prompt: sdd/prompts/202605/remove_test_targets_changespec_field.md
---
# Remove Obsolete ChangeSpec TEST TARGETS Field

## Goal

Remove the obsolete ChangeSpec `TEST TARGETS` field and its `test_targets` data model/wire representation. Test targets
should continue to exist only as HOOKS commands, through the existing `bb_rabbit_test` / shorthand hook helpers.

## Scope

- Remove ChangeSpec `TEST TARGETS:` parsing, display, formatting, search, clipboard, docs, fixtures, and tests.
- Remove the `test_targets` attribute from Python `ChangeSpec` and `ChangeSpecWire`.
- Remove the `test_targets` wire/parser field from the sibling Rust core repo (`../sase-core`) so the Python facade and
  Rust backend remain contract-compatible.
- Keep live HOOKS behavior for test targets intact:
  - `src/sase/ace/hooks/test_targets.py`
  - hook shorthand expansion/contraction
  - `changed_test_targets` discovery that creates HOOKS entries
  - failed-hook target selection UX

## Implementation Plan

1. Update schema and parser contracts.
   - Remove `test_targets` from Python `ChangeSpec` and `ChangeSpecWire`.
   - Remove Python parser state and `TEST TARGETS:` section parsing.
   - Remove Rust parser state, `TEST TARGETS:` section parsing, and Rust wire field.
   - Update schema/version handling if needed after checking how the package treats wire compatibility.

2. Update ChangeSpec formatting and field-boundary logic.
   - Remove display of the `TEST TARGETS` field in terminal and TUI detail views.
   - Remove clipboard/search output for `cs.test_targets`.
   - Remove `TEST TARGETS:` from section/header boundary tuples used by COMMITS/description/deltas/status helpers.
   - Keep `HOOKS:` as the canonical place where generated test commands live.

3. Update creation and mutation paths.
   - Ensure new ChangeSpecs never emit `TEST TARGETS:`.
   - Preserve initial hook generation from `changed_test_targets` and default hooks.
   - Ensure commit/proposal insertion and renumbering still locate section boundaries without relying on the old field.

4. Update tests and fixtures.
   - Remove `test_targets=` constructor arguments from tests and helpers.
   - Update golden fixtures and parity expected JSON so `test_targets` disappears.
   - Replace parser tests for `TEST TARGETS` with coverage that old `TEST TARGETS:` lines are ignored or treated as
     non-canonical content, depending on the chosen backward-compatibility behavior.
   - Keep tests for test-target hooks and shorthand because those are still active HOOKS behavior.

5. Update documentation and generated guidance.
   - Rewrite ChangeSpec docs and project spec docs to omit `TEST TARGETS`.
   - Update the `sase_changespecs` skill text and relevant blog/docs examples.
   - Leave historical SDD prompt/tale artifacts alone unless they are active guidance, because they record past work.

6. Verify.
   - Run focused Python tests around parsing/wire/clipboard/status field updates/hooks.
   - Run focused Rust core parser/wire/parity tests.
   - Run `just install` and `just check` in `sase_101`.
   - Run the appropriate check command in `../sase-core` after modifying it.

## Risks and Decisions

- Backward compatibility: existing project files may still contain `TEST TARGETS:`. The safest behavior is to stop
  surfacing or serializing the field while ensuring such legacy lines do not corrupt nearby sections. If migration is
  needed later, it should convert old targets into HOOKS commands explicitly.
- Terminology: references to "test target hooks" are not obsolete; they describe HOOKS commands and should remain.
- Cross-repo contract: removing `test_targets` from only Python or only Rust would break parser parity, so both repos
  need to move together.
