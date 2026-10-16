---
title: "sase flag"
description: "Inspect the code-owned SASE feature-flag registry, persist a machine-local enable or disable choice, and scaffold a new flag plus its dedicated removal bead."
---

<!-- generated, do not edit; source: argparse tree (tools/render_cli; run just fix to regenerate) -->

# sase flag

Inspect, persist, and scaffold SASE feature flags

Reference for `sase flag`. Run `sase flag --help` for the exact output on this checkout.

```text
usage: sase flag [-h] {disable,enable,list,new,show} ...
```

Inspect the code-owned SASE feature-flag registry, persist a machine-local enable or disable choice, and scaffold a new flag plus its dedicated removal bead. With no subcommand, `sase flag` defaults to `sase flag list`. `sase flag new` only runs in a SASE-managed checkout (is_sase_managed: true in sase/sase.yml). The registry lives in the SASE source tree; scaffolding a flag from another project has nowhere to paste the entry. `list`, `show`, `enable`, and `disable` work in any project: they report this process's resolved flags or persist a machine-local preference. The choice is stored in the SASE-owned machine-state file `feature_flags.json` under SASE_HOME (normally ~/.sase/feature_flags.json). It is not written to ~/.config/sase/sase.yml, overlays, or project-local sase.yml. Saved machine preferences outrank registry defaults, user config, and overlay config. Inherited SASE_FEATURE_FLAGS and root -f/--enable-feature or -F/--disable-feature still win for this process.

Bare `sase flag` defaults to `sase flag list`.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |

Subcommands:

| Subcommand          | Summary                                                   |
| ------------------- | --------------------------------------------------------- |
| `sase flag disable` | Persistently disable a registered feature flag            |
| `sase flag enable`  | Persistently enable a registered feature flag             |
| `sase flag list`    | List every registered feature flag and its resolved value |
| `sase flag new`     | Create a flag bead and print the registry entry to paste  |
| `sase flag show`    | Show one feature flag's provenance, bead, and call sites  |

## `sase flag disable`

```text
usage: sase flag disable [-h] [-j] <key>
```

Persistently disable a registered feature flag on this machine. The choice is stored in the SASE-owned machine-state file `feature_flags.json` under SASE_HOME (normally ~/.sase/feature_flags.json). It is not written to ~/.config/sase/sase.yml, overlays, or project-local sase.yml. Saved machine preferences outrank registry defaults, user config, and overlay config. Inherited SASE_FEATURE_FLAGS and root -f/--enable-feature or -F/--disable-feature still win for this process. On success, the scheduler is restarted when it is already running so new processes see the saved value. A stopped scheduler is left stopped. Any separately running sase's TUI session must be restarted in its own terminal. Repeating an already-saved enable or disable still retries that scheduler restart. A restart failure does not roll back the saved preference.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

Arguments:

| Argument   | Description                            |
| ---------- | -------------------------------------- |
| `flag_key` | Registered feature-flag key to persist |

## `sase flag enable`

```text
usage: sase flag enable [-h] [-j] <key>
```

Persistently enable a registered feature flag on this machine. The choice is stored in the SASE-owned machine-state file `feature_flags.json` under SASE_HOME (normally ~/.sase/feature_flags.json). It is not written to ~/.config/sase/sase.yml, overlays, or project-local sase.yml. Saved machine preferences outrank registry defaults, user config, and overlay config. Inherited SASE_FEATURE_FLAGS and root -f/--enable-feature or -F/--disable-feature still win for this process. On success, the scheduler is restarted when it is already running so new processes see the saved value. A stopped scheduler is left stopped. Any separately running sase's TUI session must be restarted in its own terminal. Repeating an already-saved enable or disable still retries that scheduler restart. A restart failure does not roll back the saved preference.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

Arguments:

| Argument   | Description                            |
| ---------- | -------------------------------------- |
| `flag_key` | Registered feature-flag key to persist |

## `sase flag list`

```text
usage: sase flag list [-h] [-j]
```

List every registered feature flag: the key chip, kind, default, effective value, source layer, bead id and status, and the removal countdown. Inherited SASE_FEATURE_FLAGS values are marked ENV so a long-running detached process cannot hide an override. A non-empty listing ends with a compact statistics footer: how many flags were rendered and which kinds they use, how many resolve on versus off, how many decisions came from a layer above the registry default, and whether any loaded removal bead is soon or due. Homogeneous kind or on/off values fold into the count head. For example: 3 flags · 2 beta 1 sunset · 2 on 1 off · 1 overridden · ⧗ 1 soon ⧗ 1 due `--json` keeps the versioned machine contract and does not include this footer.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

## `sase flag new`

```text
usage: sase flag new [-h] [-d DESCRIPTION] [-k {beta,sunset}]
                     --when-enabled WHEN_ENABLED --when-disabled WHEN_DISABLED
                     --remove-when REMOVE_WHEN [-r DATE/RELEASE]
                     [-z {xsmall,small,medium,large,xlarge}]
                     <key>
```

Scaffold a new feature flag. Creates the dedicated `flag` removal task bead with remove_by_date = today + 90 days and remove_by_release = the current minor plus two, then prints the registry entry to paste and a both-states test checklist. --when-enabled, --when-disabled, and --remove-when are required and each accepts `@<path>` to read the value from a file. Requires is_sase_managed: true in this checkout's sase/sase.yml.

Options:

| Option                                        | Description                                                                                                | Default |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------- |
| `-d DESCRIPTION`, `--description DESCRIPTION` | Registry scaffold description (default: --when-enabled)                                                    | —       |
| `-h`, `--help`                                | show this help message and exit                                                                            | —       |
| `-k KIND`, `--kind KIND`                      | Flag kind (default: beta) (choices: `beta`, `sunset`)                                                      | —       |
| `-r DATE/RELEASE`, `--remove-by DATE/RELEASE` | Override both thresholds, e.g. 2026-12-01/0.19.0                                                           | —       |
| `--remove-when REMOVE_WHEN`                   | What must be true before the disabled branch is deleted; accepts @<path> (required)                        | —       |
| `-z SIZE`, `--size SIZE`                      | Size for the created flag bead (default: small) (choices: `large`, `medium`, `small`, `xlarge`, `xsmall`)  | `small` |
| `--when-disabled WHEN_DISABLED`               | What the code does with this flag disabled, i.e. the branch deleted at removal; accepts @<path> (required) | —       |
| `--when-enabled WHEN_ENABLED`                 | What the code does with this flag enabled; accepts @<path> (required)                                      | —       |

Arguments:

| Argument   | Description                              |
| ---------- | ---------------------------------------- |
| `flag_key` | Snake_case registry key for the new flag |

## `sase flag show`

```text
usage: sase flag show [-h] [-j] <key>
```

Show the full FeatureFlagDecision for one key: per-layer provenance, the dedicated flag bead and both removal thresholds, and the flag's call sites in the installed SASE package.

Options:

| Option         | Description                     | Default |
| -------------- | ------------------------------- | ------- |
| `-h`, `--help` | show this help message and exit | —       |
| `-j`, `--json` | Emit machine-readable JSON      | `false` |

Arguments:

| Argument   | Description                            |
| ---------- | -------------------------------------- |
| `flag_key` | Registered feature-flag key to inspect |

Related: [CLI command groups](index.md).
