---
title: "sase init"
description: "Check and initialize SASE-managed resources."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase init

Initialize SASE-managed resources

Reference for `sase init`. Run `sase init --help` for the exact output on this checkout.

```text
usage: sase init [-h] [-a] [-c] [-d] [-j] [-M] [-p NAME] [-y]
                 {config,machine,memory,repo,service,skills} ...
```

Check and initialize SASE-managed resources. With no subcommand, runs the onboarding coordinator for config, machine, memory, repositories, and skills.

Options:

| Option                          | Description                                                                                                                  | Default |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-a`, `--all`                   | Attempt every known enabled main SASE project                                                                                | `false` |
| `-c`, `--check`                 | Report initialization drift without writing files or running initializers                                                    | `false` |
| `-d`, `--diff`                  | Show full file diffs for planned changes                                                                                     | `false` |
| `-M`, `--enable-project-memory` | Create or update sase/sase.yml with is_sase_managed: true, enabling managed project memory (cannot be combined with --check) | `false` |
| `-h`, `--help`                  | show this help message and exit                                                                                              | —       |
| `-j`, `--json`                  | With --check, emit one JSON document instead of human-readable output                                                        | `false` |
| `-p NAME`, `--project NAME`     | Check or initialize one enabled project by name, display name, or alias; repeatable                                          | —       |
| `-y`, `--yes`                   | Run every needed initializer without generic prompts; cannot authorize creation of a missing provider sidecar repository     | `false` |

Subcommands:

| Subcommand          | Summary                       |
| ------------------- | ----------------------------- |
| `sase init config`  | Alias for `sase config init`  |
| `sase init machine` | Alias for `sase machine init` |
| `sase init memory`  | Alias for `sase memory init`  |
| `sase init repo`    | Alias for `sase repo init`    |
| `sase init service` | Alias for `sase service init` |
| `sase init skills`  | Alias for `sase skill init`   |

## `sase init config`

```text
usage: sase init config [-h] [-c]
```

Compatibility alias for `sase config init`, which interactively creates, selects, or migrates the explicit SASE owner identity.

Options:

| Option          | Description                                                         | Default |
| --------------- | ------------------------------------------------------------------- | ------- |
| `-c`, `--check` | Report whether owner identity initialization or migration is needed | —       |
| `-h`, `--help`  | show this help message and exit                                     | —       |

## `sase init machine`

```text
usage: sase init machine [-h] [-B PATH] [-c] [-j] [-t SECONDS]
```

Compatibility alias for `sase machine init`, which discovers, enrolls, and activates remote machines. Check mode is read-only and performs no discovery.

Options:

| Option                             | Description                                                                    | Default |
| ---------------------------------- | ------------------------------------------------------------------------------ | ------- |
| `-B PATH`, `--bootstrap-file PATH` | Read the enrollment bundle from PATH instead of prompting                      | —       |
| `-c`, `--check`                    | Report whether remote-machine enrollment can be offered; performs no discovery | —       |
| `-h`, `--help`                     | show this help message and exit                                                | —       |
| `-j`, `--json`                     | Emit a schema-versioned JSON result                                            | —       |
| `-t SECONDS`, `--timeout SECONDS`  | Per-request gateway timeout in seconds                                         | —       |

## `sase init memory`

```text
usage: sase init memory [-h] [-c] [-d] [-M] [-m MESSAGE] [-C]
```

Compatibility alias for `sase memory init`, which creates or refreshes SASE memory files, managed AGENTS.md, and provider instruction shims.

Options:

| Option                            | Description                                                                                                                  | Default |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-c`, `--check`                   | Report memory initialization drift without writing files                                                                     | —       |
| `-d`, `--diff`                    | Show full file diffs for planned memory changes                                                                              | —       |
| `-M`, `--enable-project-memory`   | Create or update sase/sase.yml with is_sase_managed: true, enabling managed project memory (cannot be combined with --check) | `false` |
| `-h`, `--help`                    | show this help message and exit                                                                                              | —       |
| `-m MESSAGE`, `--message MESSAGE` | Commit subject for folding eligible memory and generated-change source edits; a `docs(memory):` tag is added if omitted      | —       |
| `-C`, `--no-commit`               | Skip the project git commit/push sequence                                                                                    | `false` |

## `sase init repo`

```text
usage: sase init repo [-h] [-c] [-d] [-C]
```

Alias for `sase repo init`, which initializes configured sidecars, declares the plans sidecar, and maintains the project ignore rule. Creating a missing provider repository always requires an interactive, default-no y/yes confirmation.

Options:

| Option              | Description                                                         | Default |
| ------------------- | ------------------------------------------------------------------- | ------- |
| `-c`, `--check`     | Report sidecar, config, and ignore-rule work without writing files  | —       |
| `-d`, `--diff`      | Show full file diffs for planned repository changes                 | —       |
| `-h`, `--help`      | show this help message and exit                                     | —       |
| `-C`, `--no-commit` | Write project config and ignore rules without committing or pushing | `false` |

## `sase init service`

```text
usage: sase init service [-h] [-a] [-c] [-d] [-f]
```

Compatibility alias for `sase service init`, which installs or checks the machine-scoped native service-host unit.

Options:

| Option                    | Description                                                                            | Default |
| ------------------------- | -------------------------------------------------------------------------------------- | ------- |
| `-a`, `--allow-agent-env` | Capture this shell's environment even from a SASE agent process or ephemeral workspace | —       |
| `-c`, `--check`           | Report service-platform drift without writing files                                    | —       |
| `-d`, `--diff`            | Show native-unit and redacted service-environment diffs                                | —       |
| `-f`, `--force`           | Allow installation for a non-default SASE_HOME using a home-scoped unit identity       | `false` |
| `-h`, `--help`            | show this help message and exit                                                        | —       |

## `sase init skills`

```text
usage: sase init skills [-h] [-D] [-c] [-d] [-n] [-f] [-A] [-C] [-P]
                        [-p PROVIDER] [-y]
```

Compatibility alias for `sase skill init`, which generates and deploys agent skill files from canonical skill sources.

Options:

| Option                               | Description                                                                                                                                                                            | Default |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `-D`, `--allow-dirty`                | Allow a chezmoi deploy from dirty or unmerged skill sources (dangerous: can revert other agents' deployments)                                                                          | `false` |
| `-c`, `--check`                      | Report generated skill-file drift without writing files                                                                                                                                | —       |
| `-d`, `--diff`                       | Show full generated skill-file diffs without writing files                                                                                                                             | —       |
| `-n`, `--dry-run`                    | Show what would be written without writing                                                                                                                                             | `false` |
| `-f`, `--force`                      | Overwrite existing files without confirmation, and deploy even when the recorded provenance manifest names a different source commit (dangerous: can revert other agents' deployments) | `false` |
| `-h`, `--help`                       | show this help message and exit                                                                                                                                                        | —       |
| `-A`, `--no-apply`                   | With use_chezmoi: skip running 'chezmoi apply' after pushing                                                                                                                           | `false` |
| `-C`, `--no-commit`                  | With use_chezmoi: skip the entire git commit/push/apply sequence                                                                                                                       | `false` |
| `-P`, `--no-push`                    | With use_chezmoi: commit but skip 'git pull --rebase && git push' and 'chezmoi apply'                                                                                                  | `false` |
| `-p PROVIDER`, `--provider PROVIDER` | Only deploy for a registered provider (default: all)                                                                                                                                   | —       |
| `-y`, `--yes`                        | Answer the overwrite confirmation for existing generated targets with yes; unlike --force this does not override source-integrity or provenance-manifest guards                        | `false` |

Related: [CLI command groups](index.md).
