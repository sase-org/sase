# SASE Tools (executable scripts)

Any script in this directory that has a suffix of the form `-YYmmdd` (ex: `pyvision-260227`) was vendored into this repo
from my chezmoi dotfile repo (the ../lib/bugyi-260221.sh file was also vendored using `pyvendor`). If you are asked to
modify any of these files, you should NOT. Instead make the change in the original source file in my dotfiles repo, use
your commit skill (NOT `git commit`) to commit the change in that repo, and then re-vendor it here using `pyvendor`.

## `pyvision-260227`

This linter will fail if any public symbol is unused by other (non-test) files, if any private symbol is used by other
files, or if any private symbol is NOT used in the file it is defined in.

### How do I whitelist a symbol for `pyvision-260227`? When am I allowed to do so?

This linter should normally be obeye since it does a good job of preventing unused code from accumulating. With that
said, there are a few exceptions:

- When working an epic (a bead that has been broken down into phases), it may be necessary to ignore one or more symbols
  (that will be used by later phases). You can accomplish this by adding the
  `--epic-symbol <epic_bead_id>(<symbol_name>)` option to the `pyvision` command in Justfile for every symbol that needs
  to be ignored.
- When a symbol is used by a file outside of the src/ directory (only by an xprompts/ YAML file, for example), it can be
  ignored by adding the `# pyvision: <path_with_reference>` pragma comment on the line above the symbol definition. The
  `<path_with_reference>` should be the path to the file that references the symbol, relative to the root of the
  repository. For example, if a symbol is used by `xprompts/foo.yaml`, the pragma comment would be
  `# pyvision: xprompts/foo.yaml`.
- When all functions/classes decorated with a specific decorator should be excluded from analysis, use the
  `--exclude-decorator <name>` option. This can be repeated for multiple decorator names. The decorator is matched by
  its simple name (e.g. `--exclude-decorator hook` matches `@hook`, `@hook(...)`, and `@hook.sub`).

## `sase_core_stop_hook`

Quality-check stop hook for the sase repo only. Runs auto-formatting (`just fmt-py`, `just fmt-md`), linting
(`just lint`), testing (`just test`), pyvision, and pylimit. Blocks the agent if any checks fail.

## `sase_commit_stop_hook`

Commit-orchestration stop hook. Detects uncommitted changes and instructs the agent to use the appropriate
`/sase_git_commit` or `/sase_hg_commit` skill. Also checks sibling repos for uncommitted changes. Blocks only once per
session via a marker file.

## `sase_bead`

Thin wrapper that delegates to `sase bead`. Exists for compatibility with tools (like `pyvision`) that expect
`BD_COMMAND` to be a single executable. Always use `sase bead` instead of `bd` directly.
