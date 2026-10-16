---
title: Content layout
description: Canonical paths for project and home SASE content.
---

# Content layout

This page describes the canonical paths for project and home SASE content.

SASE-owned project and home content lives under a visible `sase/` namespace. The layout
keeps source-controlled configuration, reusable prompts, memory, and workspace-scoped
repository checkouts together without moving global configuration or runtime state.

| Scope                          | Canonical path            |
| ------------------------------ | ------------------------- |
| Project configuration          | `<project>/sase/sase.yml` |
| Project macros and workflows   | `<project>/sase/macros/`  |
| Project skills                 | `<project>/sase/skills/`  |
| Project memory                 | `<project>/sase/memory/`  |
| Workspace repository checkouts | `<project>/sase/repos/`   |
| Home macros and workflows      | `~/sase/macros/`          |
| Home skills                    | `~/sase/skills/`          |
| Home memory                    | `~/sase/memory/`          |

The root `AGENTS.md` and provider instruction files remain at the project or home root
because agent providers discover them there. Their generated memory references use
`sase/memory/...`.

## Paths That Did Not Move

The namespace migration is intentionally narrow:

- Global configuration remains `~/.config/sase/sase.yml`, with overlays at
  `~/.config/sase/sase_*.yml`.
- Runtime state remains under `~/.sase/` and the platform workspace state root.
- Package resources remain under `src/sase/macros/`, `src/sase/default_macros/`,
  `src/sase/macros/skills/`, `src/sase/skills/`, and `src/sase/memory/`. The
  `src/sase/skills/` package contains Python helpers for `sase skill`; bundled skill
  Markdown lives under `src/sase/macros/skills/`.
- Plugin macro resources remain in each plugin's package-level `macros/` directory, and
  skills in a sibling `skills/` resource directory.
- SDD storage remains provider-owned; split sidecars are checked out under
  `sase/repos/`.

When `use_chezmoi: true`, the managed sources for home macros, skills, and memory are
`home/sase/macros/`, `home/sase/skills/`, and `home/sase/memory/`. The global config
source remains `home/dot_config/sase/sase.yml`.

## Skill Order

Skills have their own first-wins order and no legacy paths — a skill source outside a
canonical `skills/` directory is rejected rather than read:

1. `<project>/sase/skills/`
2. `~/sase/skills/`
3. `~/sase/skills/<project>/`
4. Plugin `skills/` resources
5. Package `src/sase/macros/skills/`

Scopes 1 and 3 namespace the macro reference with the project, so a source named `foo`
is expanded as `#<project>/skill/foo` there and `#skill/foo` elsewhere. The provider
skill name stays `foo` in every scope. See [Skill Field](macros/fields.md#skill-field)
for the full contract.

## Related

- [Macros](macros/index.md) — source order for macros and workflows.
- [Upgrading](upgrading/index.md) — migration and compatibility notes.
