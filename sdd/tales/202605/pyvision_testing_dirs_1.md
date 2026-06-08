---
create_time: 2026-05-12 18:53:23
status: done
prompt: sdd/prompts/202605/pyvision_testing_dirs_1.md
---
# Plan: Ignore Testing Utility Directories in Pyvision

## Context

The recent pyvision tightening made test-file references insufficient to keep public symbols alive. That is still the
right default for production code, but it over-applies to SASE-owned testing utilities: helper APIs that exist
specifically for tests are expected to be imported only from `tests/`.

The pyvision script is vendored into this repo as `tools/pyvision-260608`, but `tools/AGENTS.md` says the
canonical source is `~/.local/share/chezmoi/home/bin/executable_pyvision`. Implementation must happen in chezmoi first,
be tested there, and then be re-vendored into SASE with `pyvendor`.

One important repo-specific nuance: current SASE has `src/sase/ace/testing.py`, not a `src/sase/**/testing/` package
directory. I will not make generic pyvision ignore every file named `testing.py`, because that would be a broader
cross-repo rule than the prompt asks for. Instead, after pyvision learns to ignore `testing/` directories, I will
convert `src/sase/ace/testing.py` into the package file `src/sase/ace/testing/__init__.py`. The public import path
remains `sase.ace.testing`, but the helper symbols live under the explicit ignored directory shape.

## Intended Semantics

Pyvision should treat a path component named exactly `testing` as test-support code, distinct from production code and
equivalent to tests for usage accounting.

1. Definitions under `*/testing/*.py` are not checked for unused public symbols or private-symbol rules.
2. References from `*/testing/*.py` do not keep production public symbols alive.
3. Imports of private production symbols from `*/testing/*.py` are allowed, the same way imports from `tests/` are
   allowed today.
4. Pragmas pointing at `testing/` paths should not keep production symbols alive. They should be rejected with the same
   rationale as test-file pragmas: test-support references are not sufficient evidence of production use.
5. External repository URI pragmas must also ignore `testing/` paths inside the external checkout, just as they already
   ignore `tests/`.

The rule is path-component based: `pkg/testing/helpers.py` is ignored; `pkg/contest_ing/helpers.py` is not.

## Implementation Phases

### 1. Update pyvision in chezmoi

Edit `~/.local/share/chezmoi/home/bin/executable_pyvision`.

- Add a small path classifier for ignored test-support paths. It should cover existing tests (`test`, `tests`,
  `test_*.py`) and the new `testing` directory component without relying on accidental absolute parent directory names.
- Use that classifier anywhere pyvision builds definition-file or usage-file lists:
  - `_find_python_files(...)` for analyzed definition files.
  - `_find_usage_only_python_files(...)` / the non-test usage set used by `imported_symbols`.
  - `_external_repo_references_symbol(...)` before scanning external Python and text files.
- Extend pragma validation so non-external pragmas targeting `testing/` paths are rejected as test-support references.
- Keep the existing public-symbol behavior for normal production modules unchanged.

### 2. Add chezmoi regression coverage

Update `~/.local/share/chezmoi/tests/bash/pyvision_test.sh`.

- Add a fixture where `src/pkg/testing/helpers.py` defines a public helper used only by `tests/`; pyvision should pass
  because that helper is outside analysis.
- Add a fixture where a production symbol is imported only from `src/pkg/testing/helpers.py`; pyvision should still flag
  the production symbol as unused.
- Add coverage that importing a private production helper from `src/pkg/testing/helpers.py` does not trigger the
  private-import guard.
- Add coverage that `# pyvision: src/pkg/testing/helpers.py` is rejected as a test-support pragma target.
- Extend the external-repo test-only fixture or add a sibling case proving an external repo’s `testing/` directory does
  not satisfy a URI pragma.

Run the chezmoi test/check command after these changes. If this touches only pyvision and its bash tests, the focused
bashunit test plus `just check` in chezmoi is the expected verification.

### 3. Apply and re-vendor

After the chezmoi source is green:

- Commit the chezmoi change using the required SASE commit workflow.
- Run `chezmoi apply --force`.
- Re-vendor pyvision into this repo with `pyvendor`.
- If the date suffix changes from `pyvision-260608`, update the `Justfile`, `tools/AGENTS.md`, and any
  current non-historical references that point at the vendored filename.

### 4. Convert the current SASE testing helper module into a package

Move `src/sase/ace/testing.py` to `src/sase/ace/testing/__init__.py`.

This preserves imports like:

```python
from sase.ace.testing import AcePage, PromptPage, make_changespec
```

but places the definitions inside a `testing/` directory so pyvision intentionally ignores them. Existing tests should
be enough to catch import regressions, but I will run focused tests for `tests/test_ace_testing.py`, prompt-page users,
and one visual/helper import path before the full check.

### 5. Update SASE pyvision configuration and docs

- Run `just _lint-pyvision` after the vendored script and package move.
- Remove stale `--epic-symbol` entries for symbols now ignored because they live under `src/sase/ace/testing/`. At
  minimum this likely includes `AcePage` and `PromptPage`; the lint will identify the exact stale entries.
- Do not remove unrelated `sase-3a(...)` entries from the previous audit unless pyvision says they are stale.
- Update `tools/AGENTS.md` to document the refined contract:
  - `tests/` and `testing/` paths do not keep public symbols alive.
  - Symbols defined under `testing/` directories are ignored because they are test utilities.
  - Pragmas must not point at test or test-support paths.

### 6. Verification

In chezmoi:

- Run the focused pyvision bash tests.
- Run `just check`.
- Commit through the SASE commit workflow and run `chezmoi apply --force`.

In `sase_104`:

- Run `just install` first if needed for the ephemeral workspace.
- Run focused tests that import `sase.ace.testing`:
  - `just test tests/test_ace_testing.py`
  - one or two representative prompt/TUI tests that import `PromptPage` or `AcePage`.
- Run `just _lint-pyvision`.
- Run `just check`.
- Spot-check the new behavior with a temporary fixture or focused manual pyvision run:
  - a production symbol used only from a synthetic `testing/` path is still flagged;
  - a symbol defined inside a synthetic `testing/` path is ignored.
- Confirm no sibling repos other than chezmoi were modified.

## Risks and Mitigations

- Moving `sase.ace.testing` from a module to a package can break tooling that assumes a physical `testing.py` file. The
  import path remains identical, and focused import tests plus full `just check` should catch practical regressions.
- Ignoring `testing/` directories could hide real production code if a project misuses that name. That is acceptable for
  this contract because the directory name explicitly marks test-support code; pyvision should treat it like tests.
- Existing `--epic-symbol` entries may become stale once testing helpers are ignored. Pyvision already validates stale
  epic symbols, so the implementation should let the lint output drive exactly which entries to remove.

## Out of Scope

- Ignoring all files named `testing.py` in every project.
- Reopening the broader 94-symbol `sase-3a` cleanup.
- Changing the policy that normal `tests/` references do not keep production public symbols alive.
