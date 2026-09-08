# Structured Development Docs

This SDD root keeps durable planning context close to the code it describes. It stores
approved plans, roadmap material, and bead state in predictable paths so humans and
agents can reference the same artifacts over time. Canonical committed run prompts live
in the project's agents sidecar under `prompts/<YYYYMM>/`, with prompt-linked artifact
bytes under sibling `artifacts/<YYYYMM>/`. The SDD root may be the checkout's `sdd/`
directory or a separate `.sase/sdd/` store; run `sase repo path plans` or read
`SASE_SDD_PLANS_DIR` from agent environments to locate its plan storage.

![SDD directory map](assets/sdd-directory-map.png)

## Directory Layout

- `plans/` stores implementation plans. Plan files require a non-empty frontmatter
  `title` plus `tier: tale` for focused task plans or `tier: epic` for larger
  multi-phase plans. New plan `PROMPT` links point to the agents sidecar's
  `prompts/<YYYYMM>/` archive.
- `research/` stores exploratory findings, prior art, options, critiques, and
  recommendations that inform later work.
- `beads/` stores bead issue data for SDD-backed work tracking.

Plan and research files are normally organized under a `YYYYMM/` month directory
relative to this root. For example, `plans/202605/example.md` pairs with the canonical
prompt archive entry `prompts/202605/example.md` in the agents sidecar, while research
lives at `research/202605/example.md`. Archived prompt files link to their generated
plan-like artifact with a top-of-body bullet such as
`- **PLAN:** [202605/example.md](https://github.com/<org>/<repo>--plans/blob/main/202605/example.md)`;
the plan-like artifact links back with
`- **PROMPT:** [prompts/202605/example.md](https://github.com/<org>/<repo>--agents/blob/main/prompts/202605/example.md)`.
The visible label keeps a stable cross-repository reference, while the href is hosted
when the sidecar remote is known. YAML frontmatter, when present, still opens at byte
zero; the bullet is the first Markdown body element and has exactly one blank line after
it.

A plan's `PROMPT` bullet opens its **header block**: the fixed-order run of `PROMPT`,
`PARENT`, `BEAD`, `AGENTS`, `ARTIFACTS`, and `COMMITS` bullets that records the plan's
parent plan, bead, agents that worked it, prompt-linked artifacts, and the commits it
produced. SASE derives `PARENT`, `AGENTS`, and `COMMITS` from durable state rather than
accumulating them, omits sections with nothing to show, and links each entry to GitHub
when the store has a hosted remote.

## Commands

- `sase plan search` searches or browses SDD markdown artifacts.
- `sase repo path plans` and `sase repo path research` print the effective storage
  directories for those repositories.
- `sase agent prompts list`, `show`, and `validate` inspect the canonical prompt archive
  in the agents sidecar.
- `sase plan links validate` checks plan header links, including cross-repository prompt
  links.
- `sase plan links repair` previews canonical bullet migration; add `--write` to update
  unambiguous pairs.
- `sase plan links refresh` previews plan header-block reconciliation; add `--write` to
  apply it.
- `sase plan search` searches these `sdd/` plans and the machine-local `~/.sase/plans/`
  archive by content.
- `sase bead` manages SDD bead issues and epic work.

## Compatibility

The canonical top-level directories are `plans/`, `research/`, and `beads/`. Prompt
archive files live under the agents sidecar at `prompts/<YYYYMM>/`. Historical
`plans/<YYYYMM>/prompts/` files plus top-level `prompts/` and `specs/` aliases remain
readable during migration, but committed run prompts are written to the agents sidecar
archive. Historical plain-path and inline-Markdown `prompt` and `plan` frontmatter
values remain readable and valid; ordinary reads, search, validation, initialization,
and upgrades do not rewrite them. Conflicting canonical and legacy representations are
errors. Use `sase plan links repair --write` for the explicit one-time migration to
canonical bullets.
