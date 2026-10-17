---
title: "sase agent-cli"
description: "Inspect the coding-agent CLIs supported by SASE and install or update installs whose management method can be identified safely."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase agent-cli

Inspect and safely update supported coding-agent CLIs

Reference for `sase agent-cli`. Run `sase agent-cli --help` for the exact output on this checkout.

```text
usage: sase agent-cli [-h] {install,list,update} ...
```

Inspect the coding-agent CLIs supported by SASE and install or update installs whose management method can be identified safely. SASE automates npm-managed installs, provider-declared self-update commands, and provider-declared install scripts; ambiguous installs are left untouched with an exact manual command when available and a canonical documentation URL. SASE never runs sudo without a reviewed request, never uses a shell, never guesses an update command, and never edits your shell startup files. With no subcommand, `sase agent-cli` defaults to `sase agent-cli list`.

Bare `sase agent-cli` defaults to `sase agent-cli list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand               | Summary                                                          |
| ------------------------ | ---------------------------------------------------------------- |
| `sase agent-cli install` | Install agent CLIs that declare an install script or npm package |
| `sase agent-cli list`    | List supported agent CLIs, versions, and install methods         |
| `sase agent-cli update`  | Update selected agent CLIs (or every safe candidate with --all)  |

## `sase agent-cli install`

```text
usage: sase agent-cli install [-h] [<name> ...] [-f] [-j] [-n] [-o] [-r] [-y]
```

Install one or more supported coding-agent CLIs from the install script or npm package their provider declares. For a script CLI, SASE downloads the script itself, shows the URL, its SHA-256 digest, the exact command, and the target directory, and only then runs it without a shell. For an npm CLI, SASE runs the exact `npm install -g <package>` command and names the global bin directory it targets. CLIs that declare neither are reported as explicit skips with the manual command to run instead. Running an installer always needs confirmation: pass `-y|--yes` or answer the interactive prompt. Use `-n|--dry-run` to see the plan, digest included, without executing anything. After a successful install SASE reports where the binary landed and whether that directory is on PATH, printing the exact export line to add when it is not. SASE never edits your shell startup files.

Options:

| Option            | Description                                                        | Default |
| ----------------- | ------------------------------------------------------------------ | ------- |
| `-n`, `--dry-run` | Show the URL, digest, command, and target without running anything | `false` |
| `-f`, `--force`   | Reinstall even when the CLI is already installed                   | `false` |
| `-h`, `--help`    | show this help message and exit                                    | —       |
| `-j`, `--json`    | Emit a stable, machine-readable JSON envelope                      | `false` |
| `-o`, `--offline` | Use cached latest versions only; never contact the npm registry    | `false` |
| `-r`, `--refresh` | Bypass cached latest versions and query the npm registry           | `false` |
| `-y`, `--yes`     | Run the install script without an interactive confirmation         | `false` |

Arguments:

| Argument | Description                                              |
| -------- | -------------------------------------------------------- |
| `names`  | CLI names to install (provider, binary, or display name) |

## `sase agent-cli list`

```text
usage: sase agent-cli list [-h] [-j] [-o] [-r] [-v]
```

List every supported coding-agent CLI with its resolved binary, installed and latest versions, install method, and an `↑` marker when an update is available. Missing CLIs show their install hint. Use `-v|--verbose` to include resolved executable paths and canonical documentation URLs.

Options:

| Option            | Description                                                           | Default |
| ----------------- | --------------------------------------------------------------------- | ------- |
| `-h`, `--help`    | show this help message and exit                                       | —       |
| `-j`, `--json`    | Emit a stable, machine-readable JSON envelope                         | `false` |
| `-o`, `--offline` | Use cached latest versions only; never contact the npm registry       | `false` |
| `-r`, `--refresh` | Bypass cached latest versions and query the npm registry              | `false` |
| `-v`, `--verbose` | Show resolved executable paths, canonical docs URLs, and probe errors | `false` |

## `sase agent-cli update`

```text
usage: sase agent-cli update [-h] [<name> ...] [-a] [-j] [-n] [-o] [-r]
```

Update one or more supported coding-agent CLIs through the shared safe update planner. Pass `-a|--all` to select every installed CLI. Each command runs sequentially without a shell; unsupported, ambiguous, missing, bundled, and already-current CLIs are reported as explicit skips. Use `-n|--dry-run` to print every exact command and skip reason without changing anything. A bare invocation without names or `-a|--all` is a usage error.

Options:

| Option            | Description                                                     | Default |
| ----------------- | --------------------------------------------------------------- | ------- |
| `-a`, `--all`     | Select every supported installed agent CLI                      | `false` |
| `-n`, `--dry-run` | Show exact commands and skip reasons without running anything   | `false` |
| `-h`, `--help`    | show this help message and exit                                 | —       |
| `-j`, `--json`    | Emit a stable, machine-readable JSON envelope                   | `false` |
| `-o`, `--offline` | Use cached latest versions only; never contact the npm registry | `false` |
| `-r`, `--refresh` | Bypass cached latest versions and query the npm registry        | `false` |

Arguments:

| Argument | Description                                                              |
| -------- | ------------------------------------------------------------------------ |
| `names`  | CLI names to update (provider, binary, or display name); omit with --all |

Related: [CLI command groups](index.md).
