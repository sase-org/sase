---
create_time: 2026-06-02 06:41:50
status: done
prompt: sdd/prompts/202606/remove_pyvision_epic_symbols.md
---
# Plan: Remove Closed Pyvision Epic Symbol Overrides

## Context

The `Justfile` `pyvision` recipe still passes three `--epic-symbol` overrides tied to `sase-49`:

- `apply_project_lifecycle_update`
- `list_project_records`
- `project_lifecycle_wire_to_json_dict`

`sase-49` is now closed, so pyvision rejects these overrides. Running `just pyvision` currently fails with three
closed-bead errors. Running the same linter path without overrides via `just _lint-pyvision` succeeds, which indicates
the stale overrides are the direct failure rather than currently unused public symbols.

## Findings

The three symbols are not unused public leftovers:

- `apply_project_lifecycle_update` is a Rust-backed Python facade used by non-test CLI code in
  `src/sase/main/project_handler.py`.
- `list_project_records` is a Rust-backed Python facade used by multiple non-test Python modules, including project
  discovery, xprompt loading, mobile helper code, TUI project management, and CLI project handling.
- `project_lifecycle_wire_to_json_dict` is used by non-test CLI code in `src/sase/main/project_handler.py`.

GitHub code search for `sase-org` found these Python facade symbols used in `sase` itself; `sase-core` only contains the
backing Rust/PyO3 symbols. No separate GitHub repository appears to be consuming these Python facade names, so an
external-repository `# pyvision:` pragma is not appropriate. A local sibling workspace scan was attempted through
`sase workspace open -p ... 10`, but the configured sibling project files currently have no `WORKSPACE_DIR`.

Because pyvision already sees non-test Python imports for these symbols, adding local pragmas would be unnecessary and
would itself be rejected by the tool as stale.

## Implementation

1. Edit only the `Justfile` `pyvision` recipe to remove the three stale `--epic-symbol` arguments.
2. Preserve the existing `pyvision *args` recipe shape so manual invocations still run
   `tools/pyvision-260608 src/sase {{ args }}` through the configured virtualenv and `BD_COMMAND` wrapper.
3. Leave the three Python symbols public because they are consumed by non-test in-repo Python code.
4. Do not add `# pyvision:` pragmas and do not rename/delete these symbols unless post-edit verification reveals a new
   classification issue.

## Verification

1. Run `just pyvision` to confirm the user-facing recipe no longer fails on the closed epic.
2. Run `just install` and `just check` as required after file changes in this repo.
3. Inspect `git diff` and `git status --short` to confirm the implementation diff is limited to the intended Justfile
   cleanup plus this submitted plan artifact.
