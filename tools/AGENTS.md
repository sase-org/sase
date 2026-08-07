# SASE Tools (executable scripts)

Any script in this directory that has a suffix of the form `-YYmmdd` (ex:
`pyscripts-260619`) was vendored into this repo from my chezmoi dotfile repo. If you are
asked to modify any of these files, you should NOT. Instead make the change in the
original source file in my dotfiles repo, use your commit skill (NOT `git commit`) to
commit the change in that repo, and then re-vendor it with `basher vendor` or refresh it
with `basher update` from the `basher` PyPI package.

## Symvision

The published `symvision` linter will fail if any public symbol is unused by other
files, if any private symbol is used by other files, or if any private symbol is NOT
used in the file it is defined in. It scans tracked Python usage outside `src/`, but
references from test-support paths (paths under `test`/`tests`/`testing` components or
`test_*.py`) are **not** sufficient to keep a public symbol "used" — test-support paths
only count toward the private-symbol "imported from non-test" guard. Symbols defined
under `testing/` directories are ignored because they are test utilities. A public
symbol must have at least one non-test consumer (another non-test Python file, a
doc/code pragma target, or an external-repo URI pragma).

### How do I whitelist a symbol for Symvision? When am I allowed to do so?

This linter should normally be obeyed since it does a good job of preventing unused code
from accumulating. With that said, there are a few exceptions:

- When working an epic (a bead that has been broken down into phases), it may be
  necessary to ignore one or more symbols (that will be used by later phases). You can
  accomplish this by adding the `--epic-symbol <epic_bead_id>(<symbol_name>)` option to
  the `symvision` command in Justfile for every symbol that needs to be ignored.
- When a symbol is used by a non-Python file or another reference that Symvision cannot
  discover, it can be ignored by adding the `# symvision: <path_with_reference>` pragma
  comment on the line above the symbol definition. The `<path_with_reference>` should be
  the path to the file that references the symbol, relative to the root of the
  repository. For example, if a symbol is used by `sase/xprompts/foo.yaml`, the pragma
  comment would be `# symvision: sase/xprompts/foo.yaml`. Pragmas must not point at test
  or test-support paths: references from tests and testing utilities are not sufficient
  to keep a public symbol "used." If a symbol is only exercised by tests, delete it,
  make it private and call it from a non-test path, or add a non-test pragma target
  instead.
- When a symbol is consumed by another repository, use a repository URI pragma such as
  `# symvision: https://github.com/sase-org/sase-telegram.git`. Symvision resolves URI
  pragmas by first matching local checkout origins from explicit `--external-repo-path`
  / `SYMVISION_EXTERNAL_REPO_PATHS` values and sibling directories, then falling back to
  a deterministic cache clone. URI pragmas are allowed only for real external consumers;
  do not use them as broad whitelists.
- The former public API whitelist file is obsolete. Do not recreate it or point
  Symvision pragmas at it.
- When all functions/classes decorated with a specific decorator should be excluded from
  analysis, use the `--exclude-decorator <name>` option. This can be repeated for
  multiple decorator names. The decorator is matched by its simple name (e.g.
  `--exclude-decorator hook` matches `@hook`, `@hook(...)`, and `@hook.sub`).

## `sase_bead`

Thin wrapper that delegates to `sase bead`. Exists for compatibility with tools (like
Symvision) that expect `BD_COMMAND` to be a single executable. Always use `sase bead`
instead of `bd` directly.
