---
title: Macro discovery
description: How SASE finds macros, workflows, skills, and memory references.
---

# Macro discovery

This page describes how SASE finds macros, workflows, skills, and memory references.

## Discovery Order

Markdown macros and YAML workflows are loaded from multiple locations. When two
locations define a macro or workflow with the same name, the higher-priority source wins
(first-wins).

The exact file-backed paths and their first-wins order are generated from the Rust
content-layout contract in the
[Macro discovery order reference](discovery-order.md).

Skills are discovered separately, from canonical `skills/` directories only, and take
`skills/`-namespaced reference names. See
[Canonical Skill Sources](fields.md#canonical-skill-sources) for that order; the file sources
listed in the generated reference cannot define a skill.

Memory notes are also discovered separately from `sase/memory/` directories and take
`memory/`-namespaced reference names. See
[Memory Field](fields.md#memory-field) and
[Memory Order](../upgrading/content-layout.md#memory-order); the file sources
listed in the generated reference cannot define a memory macro.

Project config is exclusive: if the canonical and compatibility project config
locations both exist, SASE reports a collision instead of merging them. All save,
create, copy-on-edit, export, and workflow-editor destinations use writable canonical
sources. See
[Canonical SASE Content Layout](../content-layout.md) for before/after paths and
the compatibility timeline.

For file-based macros, the macro name defaults to the filename stem (e.g.,
`summarize.md` defines the macro `summarize`). The name can be overridden via the `name`
field in the YAML front matter.

Project-specific home macros are namespaced: a file `bar.md` in the `foo` project
directory becomes `foo/bar`. Inline-capable project macros are referenced as `#foo/bar`;
standalone project workflows are referenced as `#!foo/bar`.

When a project is detected (via the workspace provider), project macros from the
canonical and compatibility file directories and local config macros are auto-namespaced
with
the `{project}/` prefix. For example, if the project is `myapp` and
`sase/macros/deploy.md` exists, it becomes `myapp/deploy` and is referenced as
`#myapp/deploy`. A project workflow with no `prompt_part` would instead be launched as
`#!myapp/deploy`. This prevents name collisions between project-local macros and global
or built-in ones.

An explicit namespaced reference also works when the caller is outside that project's
checkout. For an enabled registered project, `#myapp/deploy` resolves checkout-backed
files and local config from the project's primary workspace. Write the literal reference
with the configured project name shown by the macro catalog or completion. Loader-facing
project selection accepts the directory key or an alias too, but catalog entries are
still exposed under the configured name; those alternate identifiers are not literal
macro namespaces. If the caller is already inside another checkout of that same project,
the current checkout wins over the registry copy so local edits are visible. Disabled
projects are not loaded through this registry fallback. When one inline prompt mentions
registered project namespaces, the first such namespace selects the checkout-backed
project catalog for that prompt.

## Config-defined macros and trust

Config entries under `macros:` can be prompt-only strings or structured prompt
definitions, or executable definitions with `bash`, `python`, or workflow `steps`.
Executable entries load as workflows. A local override is classified after composition
with lower config layers: changing only an input default or description on an inherited
executable macro still requires
[project-local command trust](../config/files-and-merging.md#project-local-command-trust).
Approved overrides preserve inherited commands and normal config merge rules, including
list concatenation.

With trust enforcement enabled, unapproved executable local entries are omitted from
both ordinary and project-namespaced catalogs. Prompt-only local entries remain
available. Explicitly requesting a blocked name reports a trust error and identifies the
config to review; it does not silently use a lower-priority namesake. A higher-priority
file definition still wins through normal discovery. Standalone macro files are outside
the local-config digest.

Local workflows retain their source's trust information through embedded workflows and
parallel steps. Each bash or Python step checks it again before starting. A revoked or
changed approval stops further local script execution; an already-running command is
not terminated.

## Related

- [Generated discovery order](discovery-order.md)
- [Macro reference](index.md)
