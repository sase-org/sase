---
title: "sase skill"
description: "Inspect, initialize, and audit generated SASE skills."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase skill

Inspect and initialize generated SASE skills

Reference for `sase skill`. Run `sase skill --help` for the exact output on this checkout.

```text
usage: sase skill [-h] {init,list,log,use} ...
```

Inspect, initialize, and audit generated SASE skills. With no subcommand, defaults to `sase skill list`.

Bare `sase skill` defaults to `sase skill list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand        | Summary                                                            |
| ----------------- | ------------------------------------------------------------------ |
| `sase skill init` | Generate and deploy agent skill files from canonical skill sources |
| `sase skill list` | Show generated skill source and target status                      |
| `sase skill log`  | Summarize or inspect auditable skill-use events                    |
| `sase skill use`  | Record that the current agent is using a skill                     |

## `sase skill init`

```text
usage: sase skill init [-h] [-D] [-c] [-d] [-n] [-f] [-A] [-C] [-P]
                       [-p PROVIDER] [-y]
```

Generate and deploy agent skill files from canonical skill sources (Markdown files in a skills/ directory that declare a truthy `skill:` value). Commit source changes and land them on the canonical branch before deploying: a chezmoi deploy is refused when the sources are uncommitted, when HEAD is not an ancestor of the canonical branch, or when it would move the destination off the source commit recorded in the provenance manifest. Preview with --diff or --dry-run while iterating. The manifest also records SASE-owned generated skill files, so a full deployment removes retired managed skills after the source change is committed and pushed. `sase init skills` is a compatibility alias for `sase skill init`.

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

## `sase skill list`

```text
usage: sase skill list [-h]
```

Show generated SASE skill sources, provider targets, and target drift without writing files, plus any source that declares `skill:` outside a canonical skills/ directory.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

## `sase skill log`

```text
usage: sase skill log [-h] [-a AGENT_NAME] [-i USE_ID] [-j] [-R RUNTIME]
                      [-s SKILL_NAME]
```

Summarize auditable skill-use events recorded by `sase skill use`, or inspect matching events with --skill, --agent, --runtime, or --id.

Options:

| Option                                | Description                                             | Default |
| ------------------------------------- | ------------------------------------------------------- | ------- |
| `-a AGENT_NAME`, `--agent AGENT_NAME` | Only include uses by the given agent                    | —       |
| `-h`, `--help`                        | show this help message and exit                         | —       |
| `-i USE_ID`, `--id USE_ID`            | Show one skill-use event by id or unambiguous id prefix | —       |
| `-j`, `--json`                        | Emit deterministic machine-readable JSON                | `false` |
| `-R RUNTIME`, `--runtime RUNTIME`     | Only include uses recorded under the given runtime      | —       |
| `-s SKILL_NAME`, `--skill SKILL_NAME` | Only include uses of the given skill                    | —       |

## `sase skill use`

```text
usage: sase skill use [-h] skill-name -r REASON
```

Append an attributable skill-use audit event for the current SASE agent. This is primarily called from generated SKILL.md files before a skill's instructions are followed.

Options:

| Option                         | Description                                           | Default |
| ------------------------------ | ----------------------------------------------------- | ------- |
| `-h`, `--help`                 | show this help message and exit                       | —       |
| `-r REASON`, `--reason REASON` | Non-empty reason for the audited skill use (required) | —       |

Arguments:

| Argument | Description                                           |
| -------- | ----------------------------------------------------- |
| `name`   | Generated skill name to record, for example sase_plan |

Related: [CLI command groups](index.md).
