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
