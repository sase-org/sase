---
title: Configuration migration notes
description:
  Migration steps for configuration keys, file hooks, repositories, and SDD storage.
---

# Configuration migration notes

This page collects user-facing configuration migrations. The
[configuration reference](../config/index.md) lists current keys, types, and defaults.

## Machine identity

Machine identity belongs under `id`:

```yaml
id:
  username: alice
  machine_name: athena
```

Top-level `machine_name` is accepted only as migration input. Run `sase config init` to
move it under `id` and add or confirm `id.username`. The initializer preserves unrelated
YAML and comments in the selected overlay. Run `sase doctor` to inspect identity issues.

## Managed instruction templates

Use `memory.h1_title` instead of the unsupported `amd_h1_title` key. Template paths
belong under `memory.*`; the top-level `amd_agents_template`,
`amd_agents_minimal_template`, `memory_sase_template`, and `memory_readme_template` keys
are accepted aliases, with the nested key winning when both are set.

## File hook filters

Place hook matching fields under `filters`:

```yaml
file_hooks:
  - name: research-highlights
    command: bob highlights create
    filters:
      path_globs: ["20*/**/*.md"]
```

The accepted fields are `projects`, `sidecars`, `path_globs`, `agent_name_globs`, `ops`,
`causes`, and `producers`. Use `path_globs`; `globs` and top-level filter fields are
ignored.

## Project-local command review

The local-command trust CLI records a digest-pinned review for project config:

```bash
sase config trust status [PATH] --json
sase config trust allow [PATH]
sase config trust revoke [PATH]
```

`allow` prints the exact normalized command-bearing projection before asking for the
literal `allow` response in a foreground terminal. `revoke` asks for `revoke`. Agents,
monitors, and non-interactive calls cannot make either change. `status` reads the
machine-local store without creating it; a missing, malformed, unsupported, or unsafe
store is reported as untrusted.

The digest binds executable local config to the logical config file selected by SASE.
Changing between `sase/sase.yml` and the root `sase.yml` compatibility fallback requires
a new review. Registered projects use their host record and canonical primary checkout;
managed workspaces share that identity only when the workspace registry confirms their
membership. Other checkouts are isolated by canonical checkout path.

The digest covers config values, not the contents of referenced scripts, binaries, or
standalone macro files. Review edits to those files separately. Hook enforcement runs
under the `local_config_command_trust` sunset flag (default on): untrusted local hooks
are omitted before merging and from file-hook loading, with a skip warning naming
`sase config trust allow PATH`. With the flag off, local commands run in compatibility
mode marked in `status`, and no trust records are created.

## Repository configuration

`repos.sidecar` is a mapping with `builtin` and `custom` buckets. Each bucket maps a
role name to its options; a list of entries with a `name` field is ignored. Run
`sase doctor` to identify entries and place them in the right bucket. `linked_repos` and
`sibling_repos` remain aliases for `repos.linked`; write new configuration with
`repos.linked`.

## SDD storage

Remove `sdd.storage` and `sdd.version_controlled`; they do not select storage. SASE
chooses SDD storage from the workspace provider and repository configuration. Run
`sase doctor` to find the unsupported keys. See
[SDD configuration behavior](../config/automation-behavior.md#sdd) for the current
storage layout.

## Related

- [Configuration behavior](../config/index.md) — current config behavior.
- [Content layout migration](content-layout.md) — project and home file paths.
- [Macro migration notes](macros.md) — macro names, prompt fields, and launch syntax.
