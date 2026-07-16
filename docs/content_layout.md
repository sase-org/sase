# Canonical SASE Content Layout

SASE-owned project and home content lives under a visible `sase/` namespace. The layout keeps source-controlled
configuration, reusable prompts, memory, and workspace-scoped repository checkouts together without moving global
configuration or runtime state.

| Scope                          | Canonical path             |
| ------------------------------ | -------------------------- |
| Project configuration          | `<project>/sase/sase.yml`  |
| Project xprompts and workflows | `<project>/sase/xprompts/` |
| Project memory                 | `<project>/sase/memory/`   |
| Workspace repository checkouts | `<project>/sase/repos/`    |
| Home xprompts and workflows    | `~/sase/xprompts/`         |
| Home memory                    | `~/sase/memory/`           |

The root `AGENTS.md` and provider instruction files remain at the project or home root because agent providers discover
them there. Their generated memory references use `sase/memory/...`.

## Paths That Did Not Move

The namespace migration is intentionally narrow:

- Global configuration remains `~/.config/sase/sase.yml`, with overlays at `~/.config/sase/sase_*.yml`.
- Runtime state remains under `~/.sase/` and the platform workspace state root.
- Package resources remain under `src/sase/xprompts/`, `src/sase/default_xprompts/`, and `src/sase/memory/`.
- Plugin xprompt resources remain in each plugin's package-level `xprompts/` directory.
- SDD storage remains provider-owned; split sidecars are checked out under `sase/repos/`.

When `use_chezmoi: true`, the managed sources for home xprompts and memory are `home/sase/xprompts/` and
`home/sase/memory/`. The global config source remains `home/dot_config/sase/sase.yml`.

## Migrating A Project

Move source files without changing their contents:

```text
Before                         After
./sase.yml                  -> ./sase/sase.yml
./.xprompts/ or ./xprompts/ -> ./sase/xprompts/
./memory/                   -> ./sase/memory/
```

Then run the read-only checks before applying generated changes:

```bash
sase doctor
sase init --check --diff
sase memory init --check --diff
```

`sase memory init` can plan and apply a safe legacy-memory move while regenerating `AGENTS.md`, provider copies, and
`sase/memory/README.md`. `sase repo init` can plan the project-config move. Both commands refuse unsafe split state; use
their check and diff modes first when the old and new locations may coexist. Move xprompt directories explicitly so the
source-control rename remains reviewable.

For a chezmoi-managed home, make the corresponding source-tree moves and apply them through chezmoi:

```text
home/dot_xprompts/ -> home/sase/xprompts/
home/memory/       -> home/sase/memory/
```

Do not move `home/dot_config/sase/`, provider skill targets, or other dotfiles as part of this migration.

## Compatibility And Collisions

All normal creation, save, edit, initialization, and proposal-approval flows write only canonical paths.

- A legacy-only project config (`<project>/sase.yml`) remains readable. If the canonical and legacy config both exist,
  SASE reports a collision instead of merging them.
- A legacy-only project or home memory tree remains readable to migration and instruction tooling. Non-identical
  canonical and legacy trees are an error. Identical trees can be deduplicated by memory initialization.
- Legacy project xprompt directories (`.xprompts/`, `xprompts/`), legacy home directories (`~/.xprompts/`,
  `~/xprompts/`), and `~/.config/sase/xprompts/<project>/` remain read-compatible. Xprompts use first-wins resolution:
  the canonical source wins and a lower-priority duplicate is shadowed rather than merged.

The compatibility window is active for the 0.10 release line. No removal release is assigned. Legacy reads will not be
removed without a separately announced deprecation and updated migration guidance; new content should nevertheless be
moved now because every writer already targets the canonical layout.

## XPrompt Compatibility Order

The complete first-wins order is:

1. `<project>/sase/xprompts/`
2. `<project>/.xprompts/` (legacy)
3. `<project>/xprompts/` (legacy)
4. `~/sase/xprompts/`
5. `~/.xprompts/` (legacy)
6. `~/xprompts/` (legacy)
7. `~/sase/xprompts/<project>/`
8. `~/.config/sase/xprompts/<project>/` (legacy)
9. Project `sase/sase.yml`, with root `sase.yml` as an exclusive legacy fallback
10. User overlays `~/.config/sase/sase_*.yml` in reverse lexical winner order
11. User base config `~/.config/sase/sase.yml`
12. Plugin config, then package default config
13. Plugin xprompt resources
14. Package `default_xprompts/`, then package `xprompts/`

Markdown xprompts, YAML workflows, and shared `steps/` follow the same filesystem order where the source supports that
format. See [XPrompts](xprompt.md#discovery-order) and the [workflow specification](workflow_spec.md#search-paths) for
format-specific details.
