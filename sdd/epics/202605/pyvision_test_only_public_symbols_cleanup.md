---
create_time: 2026-05-12 18:35:00
status: done
bead_id: sase-3a
tier: epic
---
# Pyvision: Clean Up Public Symbols Newly-Unused After Test-Reference Exclusion

## Goal

Resolve the ~95 public symbols flagged by pyvision after the chezmoi change `26cd5d7d` made test-file references
insufficient to keep a public symbol "used." See `sdd/tales/202605/pyvision_test_references_1.md` for context.

The audit list of `(symbol, file)` pairs is captured as a SASE artifact attached to this bead. While this bead is open,
those symbols are suppressed in `_lint-pyvision` via `--epic-symbol <this-bead>(<symbol>)` entries in the `Justfile`.

## Per-Symbol Remediation

For each symbol in the artifact, choose one of:

- **Delete** — when truly only test-exercised dead code (preferred).
- **Make private + call from a public path** — when the test exercises real production behavior through an internal
  helper.
- **Add a `# pyvision: <non-test path>` pragma** — when a legitimate non-Python consumer exists.

When a symbol is remediated, drop its `--epic-symbol` line from the `Justfile`. When the list is empty, close this bead.

## Out of Scope

- Re-introducing test-file references as a usage source (the chezmoi change is intentional and unconditional).
- Any cleanup not represented in the captured artifact.
