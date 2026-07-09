---
type: long
parent: AGENTS.md
description:
  Read before fixing pyvision lint failures, including unused symbols, private misuse, pragmas, and epic whitelists.
keywords: pyvision, unused symbol, pragma, epic-symbol, external repo, lint
---

# Fixing pyvision Errors

`pyvision` (`tools/pyvision-260708`) is the unused/misused-symbol linter. It scans `src/` and runs as the `pyvision`
stage of `just lint` / `just check`, or alone via `just _lint-pyvision` / `just pyvision`.

**Test references never count.** A path with a `test` / `tests` / `testing` component (or a `test_*.py` file) only
satisfies the private-symbol "imported from a non-test file" guard -- it can NOT keep a public symbol alive. Defs under
`testing/` are ignored entirely.

**Never edit the vendored tool.** `tools/pyvision-260708` (any `tools/*-YYmmdd` file) is vendored from dotfiles. Fix
your _code_, not the linter. If the tool is genuinely wrong, change the dotfiles source, commit it there with the commit
skill, and re-vendor with `pyvendor` (see `tools/CLAUDE.md`).

## Error -> fix

- `Unused public functions/classes...` -- a public symbol has no non-test consumer; fix by the hierarchy below.
- `Private functions/classes should not be imported...` -- a `_name` is used across files. Stop importing it across
  files, or (only if a real non-test file needs it) make it public -- which then needs a real consumer.
- `Private functions/classes must be used in the file where they are defined:` -- a dead private symbol. Delete it, or
  wire up its intended in-file caller.
- `Error: pyvision pragma in <file>:<line>: ...` -- a pragma problem (see Pragmas).
- `Error: --epic-symbol '<...>': ...` -- a stale/invalid epic whitelist (see Epic symbols).

## Unused public symbol -- decision hierarchy

Whitelisting is the last resort, and a symbol exercised _only_ by tests is not "used". In order:

1. **Delete it** if genuinely dead (no consumer anywhere, including linked repos) -- and delete its tests.
2. **Make it private** (`_`-prefix) if only used within its own file; update in-file callers.
3. **Add a non-test pragma** only if a real consumer exists that pyvision can't see (non-Python file, config, another
   repo).
4. **Add `--epic-symbol`** only when a later phase of an in-progress epic will consume it.

When deleting, remove only what actually died: drop the symbol plus its now-dead private helpers and its tests, but keep
sibling symbols that still have live consumers and re-check each independently.

## Pragmas

A `# pyvision: <ref>` comment directly above a public def marks a consumer pyvision can't discover.

- Public symbols only (`pragma cannot be applied to private symbol`).
- `<ref>` is a repo-root-relative path to the referencing file, or an external repo URI. It must NOT be a test/testing
  path (`referenced test-support path ... is forbidden`) or a markdown path
  (`referenced markdown path ... is forbidden`). A local path must exist and actually reference the symbol.
- `symbol '<name>' is already imported by other Python files. Remove this unnecessary pragma` -> the pragma is stale;
  delete it.
- Cross-repo consumer -> URI pragma, e.g. `# pyvision: https://github.com/sase-org/sase-telegram.git`. Only for real
  external consumers, never as a broad whitelist.
- `--exclude-decorator <name>` excludes every def carrying that decorator (matched by simple name) -- use it for a whole
  decorator-marked family (e.g. `@hook`) instead of per-symbol pragmas.

### URI pragmas fail differently in CI

Local `just _lint-pyvision` can PASS while CI FAILS (`external repository '<url>' does not reference symbol '<name>'`),
because pyvision resolves a URI pragma against a stale local checkout while CI clones the linked repo's current `main`.

- Reproduce CI: `PYVISION_EXTERNAL_REPO_PATHS=<current-linked-checkout> just _lint-pyvision`.
- Open the linked repo the sanctioned way and use the printed path -- never guess it:
  `sase workspace open -p <linked_repo> -r "<reason>" <workspace_num>`.
- Decide from what the _current_ linked repo references: still references it -> keep the symbol and its pragma; no
  longer references it -> the pragma is stale, so remove the symbol, its dead helpers, its tests, and the pragma (or
  retarget the pragma to the real consumer).

## Epic symbols

`--epic-symbol <bead_id>(<symbol>)` lives in the pyvision invocation in the `Justfile`. Entries are self-cleaning:
pyvision tells you to drop one when the bead is missing/closed, the symbol is now properly used, or the symbol no longer
exists as a public def. Remove the matching entry once its epic phase lands and the symbol gains a real consumer (or the
bead closes).

## Verify

Ephemeral `sase_<N>` workspaces may have drifted deps, so run `just install` first. Re-run the exact failing path
(`just _lint-pyvision`, plus the `PYVISION_EXTERNAL_REPO_PATHS=...` form for URI pragmas), then `just check` as the repo
requires after any code change.
