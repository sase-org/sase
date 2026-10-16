---
title: Core and identity configuration
description: Repository ownership, identity, and machine-wide configuration switches.
---

<!-- generated, do not edit; source: src/sase/config/sase.schema.json and src/sase/default_config.yml (tools/render_config; run just fix to regenerate) -->

# Core and identity configuration

Repository ownership, identity, and machine-wide configuration switches.

Defaults come from the schema when declared, otherwise from the bundled YAML. An object
with listed children is expanded below; `{…}` and `[…]` summarize compound defaults. A
dash means the schema has no finite allowed-value list.

## `default_linked_repos`

| Config key                                              | Type    | Default | Allowed values | Description                                                                                                                                |
| ------------------------------------------------------- | ------- | ------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| <a id="default_linked_repos"></a>`default_linked_repos` | boolean | `true`  | —              | Inject the default plans and beads sidecar repositories plus the intrinsically hidden agents sidecar repository for SASE-managed projects. |

## `github_orgs`

| Config key                                   | Type            | Default | Allowed values | Description                                                                                                                                                                           |
| -------------------------------------------- | --------------- | ------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| <a id="github_orgs"></a>`github_orgs`        | array \| string | not set | —              | GitHub organization/user names the user has push access to. Seeds owner completion and gates PR submission; does not choose SSH vs HTTPS (cloning always tries SSH first, then HTTPS) |
| <a id="github_orgs-item"></a>`github_orgs[]` | string          | not set | —              | —                                                                                                                                                                                     |

## `id`

| Config key                                    | Type   | Default | Allowed values | Description                                                                                                                                                      |
| --------------------------------------------- | ------ | ------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| <a id="id"></a>`id`                           | object | not set | —              | Explicit owner identity. This object is authoritative only in the machine overlay selected by ~/.sase/machine_name; run sase config init to create or repair it. |
| <a id="id-username"></a>`id.username`         | string | not set | —              | Stable, globally unique SASE username shared by all machines owned by the same user; normally the user's GitHub username.                                        |
| <a id="id-machine_name"></a>`id.machine_name` | string | not set | —              | Stable name unique among this user's machines. In a selected machine overlay it must match the ~/.sase/machine_name selector.                                    |

## `is_sase_managed`

| Config key                                    | Type    | Default | Allowed values | Description                                                                                                                                                                              |
| --------------------------------------------- | ------- | ------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| <a id="is_sase_managed"></a>`is_sase_managed` | boolean | `false` | —              | Explicitly authorize SASE to manage repository resources, including project memory, root AGENTS.md, and SDD initialization. Only the target repository's own sase/sase.yml is consulted. |

## `machine_name`

| Config key                              | Type   | Default | Allowed values | Description                                                                                                                                                        |
| --------------------------------------- | ------ | ------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| <a id="machine_name"></a>`machine_name` | string | not set | —              | Deprecated migration input for legacy machine overlays. Run sase config init to move it to id.machine_name; new configuration must use the nested identity object. |

## `timezone`

| Config key                      | Type   | Default | Allowed values | Description                                                                                                                                                             |
| ------------------------------- | ------ | ------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| <a id="timezone"></a>`timezone` | string | `""`    | —              | IANA timezone name governing all SASE wall-clock display and timestamp generation (e.g., 'America/New_York', 'US/Pacific'). Defaults to the system timezone when unset. |

## `use_chezmoi`

| Config key                            | Type    | Default | Allowed values | Description                                                                              |
| ------------------------------------- | ------- | ------- | -------------- | ---------------------------------------------------------------------------------------- |
| <a id="use_chezmoi"></a>`use_chezmoi` | boolean | `false` | —              | Remap home macro paths to chezmoi-managed equivalents under ~/.local/share/chezmoi/home/ |

## Related

- [Configuration reference](index.md) — all key families.
