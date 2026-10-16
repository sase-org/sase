---
title: Content layout migration
description: Migration steps and compatibility behavior for SASE content paths.
---

# Content layout migration

This page describes migration steps and compatibility behavior for the canonical SASE
content layout.

## Migrating A Project

Move source files without changing their contents:

```text
Before                         After
./sase.yml                  -> ./sase/sase.yml
./.macros/ or ./macros/ -> ./sase/macros/
./memory/                   -> ./sase/memory/
```

Then run the read-only checks before applying generated changes:

```bash
sase doctor
sase init --check --diff
sase memory init --check --diff
```

`sase memory init` can plan and apply a safe legacy-memory move while regenerating
`AGENTS.md`, provider copies, and `sase/memory/README.md`. `sase repo init` can plan the
project-config move. Both commands refuse unsafe split state; use their check and diff
modes first when the old and new locations may coexist. Move macro directories
explicitly so the source-control rename remains reviewable.

For a chezmoi-managed home, make the corresponding source-tree moves and apply them
through chezmoi:

```text
home/dot_macros/ -> home/sase/macros/
home/memory/       -> home/sase/memory/
```

Do not move `home/dot_config/sase/`, provider skill targets, or other dotfiles as part
of this migration.

## Compatibility And Collisions

All normal creation, save, edit, initialization, and proposal-approval flows write only
canonical paths.

- A legacy-only project config (`<project>/sase.yml`) remains readable. If the canonical
  and legacy config both exist, SASE reports a collision instead of merging them.
- A legacy-only project or home memory tree remains readable to migration and
  instruction tooling. Non-identical canonical and legacy trees are an error. Identical
  trees can be deduplicated by memory initialization.
- Legacy project macro directories (`.macros/`, `macros/`), legacy home directories
  (`~/.macros/`, `~/macros/`), and `~/.config/sase/macros/<project>/` remain
  read-compatible. Macros use first-wins resolution: the canonical source wins and a
  lower-priority duplicate is shadowed rather than merged.

The compatibility window opened with the 0.10 release line and is still active. No
removal release is assigned. Legacy reads will not be removed without a separately
announced deprecation and updated migration guidance; new content should nevertheless be
moved now because every writer already targets the canonical layout.

## Macro Compatibility Order

The complete first-wins order is:

1. `<project>/sase/macros/`
2. `<project>/.macros/` (legacy)
3. `<project>/macros/` (legacy)
4. `~/sase/macros/`
5. `~/.macros/` (legacy)
6. `~/macros/` (legacy)
7. `~/sase/macros/<project>/`
8. `~/.config/sase/macros/<project>/` (legacy)
9. Project `sase/sase.yml`, with root `sase.yml` as an exclusive legacy fallback
10. User overlays `~/.config/sase/sase_*.yml` in reverse lexical winner order
11. User base config `~/.config/sase/sase.yml`
12. Plugin config, then package default config
13. Plugin macro resources
14. Package `default_macros/`, then package `macros/`

Markdown macros, YAML workflows, and shared `steps/` follow the same filesystem order
where the source supports that format. See [Macros](../../macros.md#discovery-order) and
the [workflow specification](../../workflow_spec.md#search-paths) for format-specific
details.

## Memory Order

Memory has its own first-wins order, shared by the memory-note reader and the
`#memory/<stem>` macro catalog:

1. `<project>/sase/memory/`
2. `~/sase/memory/`

Each scope's canonical and legacy (`<project>/memory/`, `~/memory/`) trees remain
exclusive: a non-identical legacy tree next to its canonical counterpart is a collision
that blocks reads instead of merging them. There is no project-specific home memory
scope and no plugin or package memory source. A selected project's notes shadow
same-stem home notes rather than aggregating with them. See
[Memory Field](../../macros.md#memory-field) for the reference-naming contract and
[Memory](../memory/memory.md) for note types, memory webs, and the audited-read
workflow.

## Related

- [Content layout](../content-layout.md) — canonical project and home paths.
- [Upgrading](index.md) — all upgrade and history notes.
