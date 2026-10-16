---
title: Memory and instructions configuration
description:
  Project memory, generated instruction templates, and their compatibility aliases.
covers: config
---

<!-- generated, do not edit; source: src/sase/config/sase.schema.json and src/sase/default_config.yml (tools/render_config; run just fix to regenerate) -->

# Memory and instructions configuration

Project memory, generated instruction templates, and their compatibility aliases.

Defaults come from the schema when declared, otherwise from the bundled YAML. An object
with listed children is expanded below; `{…}` and `[…]` summarize compound defaults. A
dash means the schema has no finite allowed-value list.

## `amd_agents_template`

| Config key                                            | Type           | Default | Allowed values | Description                                                                                                                                                                                        |
| ----------------------------------------------------- | -------------- | ------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| <a id="amd_agents_template"></a>`amd_agents_template` | string \| null | `null`  | —              | Deprecated top-level alias for memory.agents_template. Optional root-relative path to the Jinja2 template used for AMD-managed AGENTS.md files. New configuration must use memory.agents_template. |

## `amd_agents_minimal_template`

| Config key                                                            | Type           | Default | Allowed values | Description                                                                                                                                                                                                                      |
| --------------------------------------------------------------------- | -------------- | ------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| <a id="amd_agents_minimal_template"></a>`amd_agents_minimal_template` | string \| null | `null`  | —              | Deprecated top-level alias for memory.agents_minimal_template. Optional root-relative path to the Jinja2 template used for create-if-missing minimal AGENTS.md files. New configuration must use memory.agents_minimal_template. |

## `memory`

| Config key                                                                  | Type           | Default                    | Allowed values | Description                                                                                                                       |
| --------------------------------------------------------------------------- | -------------- | -------------------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| <a id="memory"></a>`memory`                                                 | object         | {…} (5 keys; values below) | —              | Configuration for agent memory and generated agent-instruction files (AGENTS.md and its provider shims).                          |
| <a id="memory-h1_title"></a>`memory.h1_title`                               | string \| null | `null`                     | —              | Optional H1 title used by generated AMD-managed AGENTS.md. SASE-managed projects derive a stable project title when this is null. |
| <a id="memory-agents_template"></a>`memory.agents_template`                 | string \| null | `null`                     | —              | Optional root-relative path to the Jinja2 template used for AMD-managed AGENTS.md files.                                          |
| <a id="memory-agents_minimal_template"></a>`memory.agents_minimal_template` | string \| null | `null`                     | —              | Optional root-relative path to the Jinja2 template used for create-if-missing minimal AGENTS.md files.                            |
| <a id="memory-sase_template"></a>`memory.sase_template`                     | string \| null | `null`                     | —              | Optional root-relative path to the Jinja2 template used for generated sase/memory/sase.md files.                                  |
| <a id="memory-readme_template"></a>`memory.readme_template`                 | string \| null | `null`                     | —              | Optional root-relative path to the Jinja2 template used for generated sase/memory/README.md files.                                |

## `memory_readme_template`

| Config key                                                  | Type           | Default | Allowed values | Description                                                                                                                                                                                                  |
| ----------------------------------------------------------- | -------------- | ------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| <a id="memory_readme_template"></a>`memory_readme_template` | string \| null | `null`  | —              | Deprecated top-level alias for memory.readme_template. Optional root-relative path to the Jinja2 template used for generated sase/memory/README.md files. New configuration must use memory.readme_template. |

## `memory_sase_template`

| Config key                                              | Type           | Default | Allowed values | Description                                                                                                                                                                                            |
| ------------------------------------------------------- | -------------- | ------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| <a id="memory_sase_template"></a>`memory_sase_template` | string \| null | `null`  | —              | Deprecated top-level alias for memory.sase_template. Optional root-relative path to the Jinja2 template used for generated sase/memory/sase.md files. New configuration must use memory.sase_template. |

## Related

- [Configuration reference](index.md) — all key families.
