---
title: "sase completion"
description: "Generate native shell-completion scripts from the live sase argparse tree, install them where the shell will actually load them, and inspect the structural…"
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase completion

Generate and inspect shell completion for the sase CLI

Reference for `sase completion`. Run `sase completion --help` for the exact output on this checkout.

```text
usage: sase completion [-h]
                       {bash,candidates,deploy-chezmoi,ensure,fish,install,list,loader,refresh,spec,zsh} ...
```

Generate native shell-completion scripts from the live sase argparse tree, install them where the shell will actually load them, and inspect the structural spec those scripts are built from. With no subcommand, `sase completion` defaults to `sase completion list`. Write generated scripts to a file. Do not `eval "$(sase completion zsh)"` — that would pay a full sase startup on every new shell.

Bare `sase completion` defaults to `sase completion list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand                       | Summary                                                       |
| -------------------------------- | ------------------------------------------------------------- |
| `sase completion bash`           | Emit a bash completion script                                 |
| `sase completion candidates`     | Print live completion candidates for one value kind           |
| `sase completion deploy-chezmoi` | Render portable completion loaders into a chezmoi source tree |
| `sase completion ensure`         | Print a current runtime grammar cache path                    |
| `sase completion fish`           | Emit a fish completion script                                 |
| `sase completion install`        | Write, zcompile, verify, and stamp a completion script        |
| `sase completion list`           | Show which shells have a generator and their install status   |
| `sase completion loader`         | Emit a portable shell-completion loader                       |
| `sase completion refresh`        | Regenerate existing stamped completion installs               |
| `sase completion spec`           | Print the structural completion spec as JSON                  |
| `sase completion zsh`            | Emit a native zsh compsys completion script                   |

## `sase completion bash`

```text
usage: sase completion bash [-h] [-o FILE]
```

Print a bash completion script registered with `complete -o default -F _sase sase`. Source it from bash-completion's completions directory, or write it with -o/--output. Kinded value slots call `__sase_candidates` (filled in later). Do not eval the output on every shell start.

Options:

| Option                     | Description                                | Default |
| -------------------------- | ------------------------------------------ | ------- |
| `-h`, `--help`             | show this help message and exit            | —       |
| `-o FILE`, `--output FILE` | Write the script to FILE instead of stdout | —       |

## `sase completion candidates`

```text
usage: sase completion candidates [-h] [-l N] [-p NAME] [-S SELECTOR]
                                  KIND [PREFIX]
```

Print `value<TAB>description` candidate lines for one value kind, optionally filtered by a prefix. A pre-argparse fast path in entry.py handles this command ahead of argparse for every normal invocation; reaching this parser means the fast path deferred, which happens only for `--help` and argv shapes it does not recognize.

Options:

| Option                               | Description                                                                                    | Default |
| ------------------------------------ | ---------------------------------------------------------------------------------------------- | ------- |
| `-h`, `--help`                       | show this help message and exit                                                                | —       |
| `-l N`, `--limit N`                  | Print at most N candidates (default: 200)                                                      | `200`   |
| `-p NAME`, `--project NAME`          | Scope candidates to project NAME                                                               | —       |
| `-S SELECTOR`, `--selector SELECTOR` | Scope plan_decision candidates to one pending proposal (name, path, or notification ID prefix) | —       |

Arguments:

| Argument | Description                                            |
| -------- | ------------------------------------------------------ |
| `kind`   | Value kind to list candidates for (e.g. project, bead) |
| `prefix` | Only print candidates whose value starts with PREFIX   |

## `sase completion deploy-chezmoi`

```text
usage: sase completion deploy-chezmoi [-h] [-a] [-c] [-d] [-n] [-s DIR]
```

Render bash, fish, and zsh portable completion loaders into the configured chezmoi source tree, remove legacy generated completion stamp sources, then optionally commit, push, and apply those changes.

Options:

| Option                   | Description                                                          | Default |
| ------------------------ | -------------------------------------------------------------------- | ------- |
| `-d`, `--dry-run`        | Print planned source files without touching the filesystem           | `false` |
| `-h`, `--help`           | show this help message and exit                                      | —       |
| `-a`, `--no-apply`       | Commit and push source changes but skip 'chezmoi apply'              | `false` |
| `-c`, `--no-commit`      | Write source files but skip the git commit, push, and apply sequence | `false` |
| `-n`, `--no-push`        | Commit source changes but skip pull, push, and apply                 | `false` |
| `-s DIR`, `--source DIR` | Chezmoi source home to write (default: ~/.local/share/chezmoi/home)  | —       |

## `sase completion ensure`

```text
usage: sase completion ensure [-h] [-f] [-p FILE] [-O {chezmoi,local}]
                              [-t DIR]
                              {bash,fish,zsh}
```

Ensure runtime-cached completion grammar exists for SHELL and print exactly one absolute grammar-file path on success. Cache hits avoid building the argparse tree; diagnostics are written to stderr.

Options:

| Option                          | Description                                                                                 | Default |
| ------------------------------- | ------------------------------------------------------------------------------------------- | ------- |
| `-f`, `--force`                 | Regenerate the grammar even when the cache is current                                       | `false` |
| `-h`, `--help`                  | show this help message and exit                                                             | —       |
| `-p FILE`, `--loader-path FILE` | Installed loader file path to record with the cache manifest                                | —       |
| `-O OWNER`, `--owner OWNER`     | Ownership metadata to record when a loader target is supplied (choices: `chezmoi`, `local`) | —       |
| `-t DIR`, `--target DIR`        | Installed loader directory to record with the cache manifest                                | —       |

Arguments:

| Argument | Description              |
| -------- | ------------------------ |
| `shell`  | Shell grammar to resolve |

## `sase completion fish`

```text
usage: sase completion fish [-h] [-o FILE]
```

Print fish `complete -c sase` directives conditioned on a `__sase_cmd` helper that resolves the current command path. Descriptions are passed with `-d`. Write the file to `~/.config/fish/completions/sase.fish` with -o/--output. Do not eval the output on every shell start.

Options:

| Option                     | Description                                | Default |
| -------------------------- | ------------------------------------------ | ------- |
| `-h`, `--help`             | show this help message and exit            | —       |
| `-o FILE`, `--output FILE` | Write the script to FILE instead of stdout | —       |

## `sase completion install`

```text
usage: sase completion install [-h] [-d] [-f] [-t DIR] [{bash,fish,zsh}]
```

Install native shell completion for sase. Detects the shell from $SHELL and the parent process when SHELL is omitted, picks a directory the shell actually scans, writes the script atomically, zcompiles it (zsh), verifies `_comps[sase]` registration, and stamps the install. Never edits ~/.zshrc. If registration fails, the exact `fpath=(...)` line to add before compinit is printed. Do not `eval "$(sase completion zsh)"`.

Options:

| Option                   | Description                                            | Default |
| ------------------------ | ------------------------------------------------------ | ------- |
| `-d`, `--dry-run`        | Print the install plan without touching the filesystem | `false` |
| `-f`, `--force`          | Overwrite a completion file sase did not write         | `false` |
| `-h`, `--help`           | show this help message and exit                        | —       |
| `-t DIR`, `--target DIR` | Directory to write the script into                     | —       |

Arguments:

| Argument | Description                                                               |
| -------- | ------------------------------------------------------------------------- |
| `shell`  | Shell to install for (default: detect from $SHELL and the parent process) |

## `sase completion list`

```text
usage: sase completion list [-h] [-j]
```

List every supported shell, whether sase can generate a completion script for it, the installed path, `.zwc` freshness, stamp version, and the resolved install status.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

## `sase completion loader`

```text
usage: sase completion loader [-h] [-O {chezmoi,local}] [-o FILE]
                              {bash,fish,zsh}
```

Print a small shell-native loader that resolves the active sase executable at runtime, asks `sase completion ensure SHELL` for the current cached grammar, and sources that grammar once.

Options:

| Option                      | Description                                                                  | Default |
| --------------------------- | ---------------------------------------------------------------------------- | ------- |
| `-h`, `--help`              | show this help message and exit                                              | —       |
| `-o FILE`, `--output FILE`  | Write the loader to FILE instead of stdout                                   | —       |
| `-O OWNER`, `--owner OWNER` | Ownership metadata the loader passes to ensure (choices: `chezmoi`, `local`) | —       |

Arguments:

| Argument | Description          |
| -------- | -------------------- |
| `shell`  | Shell loader to emit |

## `sase completion refresh`

```text
usage: sase completion refresh [-h] [-d] [-j] [{bash,fish,zsh}]
```

Refresh stamped completion installs from the running sase CLI. With no SHELL, refreshes every stamped supported shell. Chezmoi-owned applied targets are refreshed in place; migrate the managed source separately to prevent later rollback.

Options:

| Option            | Description                                                          | Default |
| ----------------- | -------------------------------------------------------------------- | ------- |
| `-d`, `--dry-run` | Print the refresh plan without touching scripts, stamps, or bytecode | `false` |
| `-h`, `--help`    | show this help message and exit                                      | —       |
| `-j`, `--json`    | Emit machine-readable JSON                                           | `false` |

Arguments:

| Argument | Description                                     |
| -------- | ----------------------------------------------- |
| `shell`  | Shell to refresh (default: every stamped shell) |

## `sase completion spec`

```text
usage: sase completion spec [-h] [-d] [-j] [-o FILE]
```

Print the completion spec as JSON. By default this is the structural view — the same JSON artifact the checked-in snapshot gate compares against, with descriptions replaced by per-command digests so wording churn is a one-line diff. Pass -d to keep the real command, option, and positional summaries instead of digests; the Command Line spec cache builds from that full view. Use this as a stable integration point for other tools.

Options:

| Option                     | Description                                        | Default |
| -------------------------- | -------------------------------------------------- | ------- |
| `-d`, `--descriptions`     | Keep real summaries instead of per-command digests | `false` |
| `-h`, `--help`             | show this help message and exit                    | —       |
| `-j`, `--json`             | Emit machine-readable JSON                         | `false` |
| `-o FILE`, `--output FILE` | Write the spec to FILE instead of stdout           | —       |

## `sase completion zsh`

```text
usage: sase completion zsh [-h] [-o FILE]
```

Print a `#compdef sase` compsys script with `_arguments -C -s -S`, option descriptions, exclusion lists, mutex groups, and remainder handling. Place the file on `fpath` as `_sase` before `compinit` and `zcompile` it. Do not eval the output.

Options:

| Option                     | Description                                | Default |
| -------------------------- | ------------------------------------------ | ------- |
| `-h`, `--help`             | show this help message and exit            | —       |
| `-o FILE`, `--output FILE` | Write the script to FILE instead of stdout | —       |

Related: [CLI command groups](index.md).
