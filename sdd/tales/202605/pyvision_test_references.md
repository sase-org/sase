---
create_time: 2026-05-12 18:15:12
status: done
prompt: sdd/prompts/202605/pyvision_test_references.md
---
# Pyvision: Exclude Test Files From Public Symbol Reference Detection

## Goal

Make `pyvision` treat references to a public symbol from Python test files as **insufficient** to consider that symbol
"used." If a public symbol is referenced **only** by test files, pyvision should flag it as unused (the same way it
would if the symbol had no references at all).

The intent is to keep test-only symbols out of the production codebase: tests should exercise code that exists for a
non-test reason, not be the only justification for a symbol's existence.

## Current Behavior

Pyvision scans tracked Python files outside `src/` (which includes the `tests/` tree) as legitimate **usage** sources.
Today's flow in `tools/pyvision-260608`:

- `_find_python_files(args.directory)` — collects **definition** files inside the analyzed tree, with `tests/` excluded
  (line 760).
- `_find_usage_only_python_files(...)` — collects tracked Python files **outside** the analyzed tree (line 798). This is
  what brings the `tests/` tree back in _as a usage source_.
- `main()` builds `usage_file_infos = file_infos + usage_only_file_infos` (line 978) — this set includes test files.
- `imported_symbols = _batch_search_usage(all_symbols_to_check, usage_file_infos, …)` (line 1022) — uses the
  test-inclusive set, so a symbol imported only from a test file is considered "imported."
- A separate `non_test_usage_file_infos` (line 979) **already exists** but is only consulted for the private-symbol
  "improperly imported from non-test" check at line 1141.

Consequence: a public symbol used only by `tests/test_foo.py` passes pyvision today.

External-repo URI pragmas already follow the desired behavior: `_external_repo_references_symbol` (line 589) explicitly
filters out test files before searching. The intra-repo behavior is the inconsistent one we want to fix.

## Proposed Behavior

Treat test files as **not contributing** to the "is this public symbol used?" decision, intra-repo. Specifically:

1. **Public symbols**: A public symbol is "used" only if it is imported, or used via a tracked module alias, from a
   **non-test** Python file inside the repo (or from a documentation/code pragma target, or from an external repo URI
   pragma — both unchanged).
2. **Private symbols**: Already use the non-test path for the "imported from non-test" guard — _no change needed for
   that check._ The "private symbol must be used in its own file" check is also unaffected (private symbols can only
   live in non-test files because `_find_python_files` excludes tests).
3. **Pragma "stale" check**: A pragma is "stale" only when its symbol is already imported from a **non-test** Python
   file. (Today's check at line 678–686 of `_validate_pragmas` uses `imported_symbols`; after the change that set will
   already be non-test-only, so the check naturally tightens correctly.)
4. **`--epic-symbol` "already used" check**: Same as above — this check piggybacks on `imported_symbols`, which becomes
   non-test-only.
5. **Test-file pragmas (`# pyvision: tests/...`)**: Remain forbidden. The rationale changes from "test references are
   detected automatically" to "test references are not sufficient to keep a symbol alive." Update the error message
   accordingly so it doesn't lie.

### What counts as a "test file"

Reuse the existing `_is_test_file_path` helper (line 753), which considers any path with a `test`/`tests` component, or
a `.py` file whose name starts with `test_`. This is consistent with how external-repo scanning and the existing
private-symbol guard already classify tests.

Note: `conftest.py` files placed under a `tests/` directory will be excluded naturally. A `conftest.py` placed at the
repo root would _not_ be excluded by the current helper. We will accept that quirk — there is no `conftest.py` at the
repo root today, and adopting a stricter rule (e.g. exclude `conftest.py` anywhere) would be a separate decision. Flag
it in the plan but don't expand scope.

## Edge Cases & Risks

- **Hidden cascade in sase_104**: Any public symbol currently kept alive only by a test reference will start failing
  pyvision once the vendored script lands. We need to audit and remediate before (or in the same change as)
  re-vendoring. Remediation options per symbol:
  - Delete it (preferred when truly only test-exercised dead code).
  - Make it `private` and call it from a public path (when the test is exercising real production behavior through an
    internal helper).
  - Add a `# pyvision: <non-test path>` pragma when a legitimate non-Python consumer exists.
  - Add `--epic-symbol` if it's tied to a pending epic.
- **Module-alias usage from tests**: The existing chezmoi tests `test_module_alias_usage_from_tracked_tests` and
  `test_from_import_alias_usage_from_tracked_tests` assert the _opposite_ of the new contract. They must be
  **rewritten** to assert failure (and we'll add positive coverage where the same import comes from a non-test file).
- **Mixed-references test fixture**: A public symbol referenced from both a test file and a non-test file must continue
  to pass. New test coverage.
- **Pragma + test-only reference**: A symbol with a doc/repo pragma but _additionally_ imported only from a test file
  should NOT be reported as "stale pragma" — the pragma is still load-bearing. New test coverage.
- **Vendored script policy**: Per `tools/AGENTS.md`, the canonical source is
  `~/.local/share/chezmoi/home/bin/executable_pyvision`. We must edit there, commit there (using the sase commit skill),
  then re-vendor via `pyvendor`. We do **not** edit the `tools/pyvision-260608` copy directly.

## Implementation Steps

### 1. Modify the chezmoi source

`~/.local/share/chezmoi/home/bin/executable_pyvision`:

- In `main()` (around lines 1014–1024), compute `imported_symbols` against `non_test_usage_file_infos` rather than
  `usage_file_infos`. `usage_file_infos` itself can be removed if it has no remaining consumers — confirm via grep
  before deleting.
- In `_validate_pragmas` (around lines 663–675), update the test-file-pragma error message so it no longer claims
  "Python test references are detected automatically." Replace with wording such as: _"references from test files are
  not sufficient to keep a public symbol used; delete the symbol, make it private and call it from a non-test path, or
  use a non-test pragma target."_
- Update the module docstring at the top of the file (line 3) only if it makes a claim about test references (it
  currently doesn't — verify before editing).

### 2. Update chezmoi tests

`~/.local/share/chezmoi/tests/bash/pyvision_test.sh`:

- **Rewrite** `test_module_alias_usage_from_tracked_tests` (line 42) and
  `test_from_import_alias_usage_from_tracked_tests` (line 67) to assert that pyvision now **fails** with the symbol
  reported as unused.
- **Rewrite or extend** `test_pyvision_allows_private_imports_from_tracked_tests` (line 119): `build_widget` is
  currently kept alive only by a test import, which will start failing. Either:
  - drop the `build_widget` import from the test fixture and keep the focus on private-symbol import behavior, or
  - give `build_widget` a non-test consumer in the fixture.
- **Update** `test_pyvision_rejects_test_file_pragmas` (line 92) to match the new error message text.
- **Add** `test_pyvision_fails_when_public_symbol_only_used_in_tests` — a public function defined in `src/pkg/` with the
  _only_ import from `tests/test_foo.py`. Expect exit 1 and the standard "Unused public functions/classes" error.
- **Add** `test_pyvision_passes_when_symbol_used_in_both_tests_and_non_tests` — same definition, imports from both
  `tests/` and a non-test consumer (e.g. a sibling module in `src/pkg/`, or an `app.py` outside `src/`). Expect exit 0.
- **Add** `test_pyvision_pragma_not_stale_when_only_test_imports_exist` — a symbol with `# pyvision: docs/foo.md` and a
  test-only Python import. Expect exit 0 (pragma still needed, no "stale pragma" error).

Run `just check` (or whichever test runner chezmoi uses for `tests/bash/*.sh`) in the chezmoi repo before committing.

### 3. Commit the chezmoi change

Use the `sase_git_commit` skill (per the user's "ONLY way you should ever commit" rule) to commit in
`~/.local/share/chezmoi`. Then run `chezmoi apply --force` per the chezmoi memory note.

### 4. Re-vendor into sase_104

Run `pyvendor` to refresh `tools/pyvision-260608`. (If the date suffix rolls forward to today's date, update
`Justfile` references and any documentation/agent-memory references to the old filename. Grep for
`pyvision-260608` first to enumerate the touch points — at minimum: `Justfile` lines 112 and 262.)

### 5. Audit sase_104 for newly-unused public symbols

Run `just _lint-pyvision` after the re-vendor. For every symbol now reported:

- Inspect callers (`grep -rn '\bSYMBOL\b' src tests docs`).
- Apply the appropriate remediation from the "Risks" section above.

This audit work must land in the **same change/PR** as the vendored script update, otherwise CI breaks on `master`. If
the audit list is unexpectedly large, pause and surface it to the user before mass-deleting.

### 6. Update documentation

- `tools/AGENTS.md` `pyvision-260608` section currently says: _"It scans tracked Python usage outside `src/`,
  including tests, so Python test references do not need pragmas."_ Rewrite to state the new contract: tests are scanned
  only for the private-symbol guard; public symbols require at least one non-test consumer.
- Update the "How do I whitelist a symbol" bullet that mentions _"Pragmas must not point at test files; Python test
  references are detected automatically"_ to reflect the new rationale.

### 7. Final verification

- `just check` inside `sase_104`.
- `just check` inside `~/.local/share/chezmoi`.
- Confirm no sibling repo touched (per `sase_sibling_commit_stop_hook` rules).

## Out of Scope

- Changing how external-repo URI pragmas treat test files (already correct).
- Broadening the "test file" definition beyond `_is_test_file_path` (e.g. root `conftest.py`). Note as a follow-up only.
- Any new pyvision flag to opt back into the old behavior. The new contract is unconditional.
