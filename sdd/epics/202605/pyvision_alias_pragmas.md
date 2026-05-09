---
create_time: 2026-05-01 02:12:31
bead_id: sase-1q
status: done
prompt: sdd/prompts/202605/pyvision_alias_pragmas.md
---
# Pyvision Alias Usage and Test-Pragma Ban Plan

## Goal

Fix `pyvision` at its source in the chezmoi repo, vendor the fixed script back into this SASE repo, and remove the
current need for `# pyvision: tests/...` pragmas. After the work lands, pyvision should automatically count real Python
usage from test files and other tracked Python files outside the analyzed source tree, including usage through module
aliases such as:

```python
from sase.core import notification_store_facade as facade

facade.NotificationStoreRecord(...)
```

Pragmas should remain available for legitimate non-Python references such as `xprompts/*.yml` and the legacy public API
whitelist, but pyvision should reject pragmas that reference test files.

## Current Context

- Source script: `/home/bryan/.local/share/chezmoi/home/bin/executable_pyvision`
- Vendored SASE copy: `tools/pyvision-260225`
- SASE pyvision invocation: `BD_COMMAND=tools/sase_bead .venv/bin/python tools/pyvision-260225 src/sase`
- Current test-target pragmas: `rg "# pyvision: tests/" src/sase` reports 77 matches.
- Current total SASE pragmas under `src/sase`: 92 matches.
- Non-test pragmas currently point at the legacy public API whitelist and `xprompts/pylimit_split.yml`; those should not be
  removed as part of this work unless pyvision can prove those usages another way.
- `tools/AGENTS.md` says dated scripts under `tools/` must be changed in the source dotfiles repo, committed there with
  the SASE commit workflow, and then re-vendored with `pyvendor`.
- Chezmoi memory says to run `just check` in `~/.local/share/chezmoi` after modifying that repo. After committing
  chezmoi changes, run `chezmoi apply --force`.
- SASE memory says to run `just install` before checks in this workspace if needed, and run `just check` after modifying
  this repo.

## Design Direction

Replace pyvision's line-regex import heuristic with an AST-backed usage collector while preserving existing behavior as
much as possible.

The collector should keep the current distinction between "definition files" and "usage-only files":

- Definition files are the Python files under the CLI directory argument, excluding test/venv directories as today.
- Usage-only files should include tracked Python files from the git repo outside the definition tree, especially
  `tests/**/*.py`. These files should contribute references but should not contribute public/private definitions to
  lint.
- If pyvision is run outside a git repo and no pragmas are present, fall back to the current directory-only behavior
  rather than making git mandatory for all usage.

The AST collector should recognize at least these usage forms:

- Direct imports: `from module import Symbol`, including `from module import Symbol as Alias`.
- Multi-line direct imports.
- Module imports: `import package.module as mod`; `mod.Symbol` marks `Symbol` as used.
- From-imported modules: `from package import module as mod`; `mod.Symbol` marks `Symbol` as used when `package.module`
  resolves to a tracked Python module.
- Existing same-file/private checks should continue to work.

Keep pyvision's existing global symbol-name semantics unless a phase finds a low-risk way to make the result
definition-specific. The immediate bug is missed alias/attribute usage, not name collision precision.

Add an explicit pragma validation rule:

- Reject any pragma whose referenced path is a test file or lives under a test directory.
- Treat at least `tests/`, `test/`, and Python filenames beginning with `test_` as test references.
- Error text should say test-file pragmas are forbidden because Python test references are detected automatically.

## Phase 1: Fix Pyvision in Chezmoi

Owner: one agent working only in `/home/bryan/.local/share/chezmoi`.

Tasks:

1. Modify `home/bin/executable_pyvision`.
2. Implement AST-based import and attribute usage collection.
3. Add usage-only scanning for tracked Python files outside the target directory, using git root when available.
4. Add the test-file pragma ban.
5. Add regression tests. Since pyvision is an executable script rather than a package, bashunit tests under
   `tests/bash/` are the lowest-friction fit:
   - Create temporary git repos.
   - Create minimal `src/pkg/...` and `tests/test_...py` files.
   - Run `home/bin/executable_pyvision src/pkg`.
   - Assert module alias usage from tests passes without pragmas.
   - Assert `from pkg.module import Symbol as Alias` direct alias usage passes.
   - Assert `# pyvision: tests/test_foo.py` fails with the new clear error.
   - Assert a non-test pragma target still works.
6. Run focused tests for the new bashunit file, then `just check` in the chezmoi repo.
7. Commit the chezmoi change using the SASE git commit skill, not raw `git commit`.
8. Run `chezmoi apply --force` after the commit.

Acceptance criteria:

- Chezmoi `just check` passes.
- New tests fail on the old implementation and pass on the new implementation.
- `home/bin/executable_pyvision` can detect `alias.Symbol` usage from tracked test files without a pragma.
- Test-file pragmas are rejected.
- Chezmoi repo is clean after commit/apply.

## Phase 2: Vendor and Clean SASE Pragmas

Owner: a separate agent working in `/home/bryan/projects/github/sase-org/sase_102`.

Prerequisite: Phase 1 committed and applied in chezmoi.

Tasks:

1. Re-vendor pyvision into this repo:

   ```bash
   pyvendor /home/bryan/.local/share/chezmoi/home/bin/executable_pyvision /home/bryan/projects/github/sase-org/sase_102
   ```

   This should replace `tools/pyvision-260225` with a date-stamped current copy and update references such as
   `Justfile`.

2. Review the pyvendor changes. Ensure the new vendored filename is the one referenced by `Justfile`.
3. Remove every `# pyvision: tests/...` pragma from `src/sase`.
4. Keep legitimate non-test pragmas, including the legacy public API whitelist and `xprompts/pylimit_split.yml`, unless
   pyvision now proves a specific one stale.
5. Update `tools/AGENTS.md` so the pyvision section reflects the new dated filename and policy:
   - pyvision scans tracked Python usage outside `src/`.
   - pragmas are for non-Python or otherwise non-discoverable references.
   - pragmas must not point at test files.
6. Run:

   ```bash
   rg "# pyvision: tests/" src/sase
   just pyvision
   just check
   ```

Acceptance criteria:

- `rg "# pyvision: tests/" src/sase` returns no matches.
- `just pyvision` passes with the vendored pyvision.
- `just check` passes.
- SASE repo only contains expected vendoring, pragma cleanup, and documentation changes.

## Phase 3: Hardening Sweep and Edge Cases

Owner: a separate verification agent after Phase 2.

Tasks:

1. Re-run `rg "# pyvision:" src/sase` and classify remaining pragmas. Confirm none reference tests.
2. Exercise pyvision's new rule with an intentional temporary fixture outside tracked source, without leaving repo files
   behind:
   - Verify a test-file pragma is rejected.
   - Verify a non-test pragma still validates file existence and symbol text.
3. Run `just pyvision` and `just check` again in SASE.
4. Check `git status --short` in both SASE and chezmoi and report any unrelated pre-existing dirt separately.
5. If any alias pattern still requires a test pragma, do not reintroduce the pragma. Either extend pyvision coverage or
   document the blocker and leave the repo failing for the next implementation phase.

Acceptance criteria:

- End-to-end policy is enforced by the vendored script, not by convention.
- No test-target pyvision pragmas remain.
- Both repos are in expected states.

## Risks and Mitigations

- Risk: Scanning all tracked Python files may pick up generated or perf code and create false positives. Mitigation:
  usage-only files should contribute references only; they should never add definitions to lint. Continue honoring
  existing target-directory exclusions for definitions.
- Risk: AST relative import resolution can become broad. Mitigation: implement the common absolute and package-child
  alias cases first. Add relative import support only where it is straightforward from the current file's module path.
- Risk: The current pyvision model keys usage by symbol name only, so alias attribute usage can still be imprecise when
  two modules export the same public name. Mitigation: preserve current semantics for this change. If collisions become
  a practical problem, make definition- qualified usage a separate future project.
- Risk: Vendoring creates a new date-stamped filename and touches references broadly. Mitigation: inspect pyvendor
  output before cleanup, and keep SASE edits limited to the vendored tool, Justfile reference updates, test pragma
  deletion, and docs.

## Suggested Agent Prompts

Phase 1 prompt:

> Implement Phase 1 from `sase_plan_pyvision_alias_pragmas.md`: fix
> `/home/bryan/.local/share/chezmoi/home/bin/executable_pyvision` to detect Python usage from tracked files outside the
> analyzed source tree, including module-alias attribute usage, and reject pragmas that reference test files. Add
> regression tests in chezmoi, run `just check`, commit with the SASE commit skill, and run `chezmoi apply --force`.

Phase 2 prompt:

> Implement Phase 2 from `sase_plan_pyvision_alias_pragmas.md`: vendor the fixed chezmoi pyvision into this SASE repo,
> remove all `# pyvision: tests/...` pragmas, update pyvision docs in `tools/AGENTS.md`, and run
> `rg "# pyvision: tests/" src/sase`, `just pyvision`, and `just check`.

Phase 3 prompt:

> Implement Phase 3 from `sase_plan_pyvision_alias_pragmas.md`: verify the vendored pyvision policy end to end, classify
> remaining pragmas, run the final checks in SASE, and report repo status for SASE and chezmoi.
