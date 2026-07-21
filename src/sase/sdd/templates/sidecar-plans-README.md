# SASE Plans

This public sidecar repository stores the durable planning state for its SASE-managed source repository. SASE
automatically clones it into each workspace and keeps plan files, their original prompt snapshots, and bead state
available to humans and agents.

![Plans directory map](assets/plans-directory-map.png)

## Directory Layout

- `<YYYYMM>/*.md` stores plan files. Every plan declares a non-empty `title` and either `tier: tale` or `tier: epic` in
  YAML frontmatter.
- `<YYYYMM>/prompts/*.md` stores the original prompts or expanded snapshots that produced that month's plans.
- `beads/` stores SASE bead events and compatibility projections. SQLite `beads.db*` files are local-only.
- `assets/` stores generated explanatory media used by this README.

Plans and prompts use clickable top-of-body Markdown bullets with stable labels and file-relative hrefs. For example,
`202607/example.md` links back with
`- **PROMPT:** [202607/prompts/example.md](prompts/example.md)`, while its prompt snapshot uses
`- **PLAN:** [../202607/example.md](../example.md)`. YAML frontmatter, when present, begins at byte zero; the bullet is
the first Markdown body element and has exactly one blank line after it.

## Commands

- `sase plan list` and `sase plan search` inspect plans.
- `sase repo path plans` prints this clone's root.
- `sase plan links validate` checks prompt and plan artifact links.
- `sase plan links repair` previews legacy or stale links; add `--write` for a one-time canonical-bullet migration.
- `sase bead` manages bead work stored under `beads/`.

Historical plain-path and inline-Markdown frontmatter values remain readable and valid. Search, validation,
initialization, and upgrades do not rewrite them automatically; conflicting representations are reported instead of
silently selected. Use `sase plan links repair --write` for explicit migration.
