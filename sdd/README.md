# Structured Development Docs

This SDD root keeps durable planning context close to the code it describes. It stores prompts, approved plans, roadmap
material, and bead state in predictable paths so humans and agents can reference the same artifacts over time. The root
may be the checkout's `sdd/` directory or a separate `.sase/sdd/` store; run `sase sdd path` or read `SASE_SDD_DIR` from
agent environments to locate it.

![SDD directory map](assets/sdd-directory-map.png)

## Directory Layout

- `prompts/` stores the original user prompts or expanded prompt snapshots that led to plan-like artifacts.
- `tales/` stores task-level implementation plans and follow-up plans.
- `epics/` stores larger work plans that may be split into phase beads.
- `legends/` stores broad roadmap or strategy artifacts that can spawn epics.
- `myths/` stores long-horizon narrative, strategy, and context artifacts that are broader than active roadmap plans.
- `research/` stores exploratory findings, prior art, options, critiques, and recommendations that inform later work.
- `beads/` stores bead issue data for SDD-backed work tracking.

Prompt, tale, epic, legend, and research files are normally organized under a `YYYYMM/` month directory relative to this
root, for example `prompts/202605/example.md`, `tales/202605/example.md`, and `research/202605/example.md`. Prompt files
should link to their generated plan-like artifact with frontmatter such as `plan: tales/202605/example.md`; the
plan-like artifact should link back with `prompt: prompts/202605/example.md`.

## Commands

- `sase sdd list` lists SDD markdown artifacts.
- `sase sdd path` prints the effective SDD root; pass a kind such as `research` to print that child directory.
- `sase sdd validate` checks frontmatter links between prompts and plan-like artifacts.
- `sase sdd repair-links` infers and repairs missing bidirectional links.
- `sase plan search` searches these `sdd/` plans and the machine-local `~/.sase/plans/` archive by content.
- `sase bead` manages SDD bead issues and epic work.

## Compatibility

The canonical directories are `prompts/`, `tales/`, `epics/`, `legends/`, `myths/`, `research/`, and `beads/`. Older
trees may still contain `specs/` for prompt snapshots or `plans/` for tale-like plans; SDD tooling keeps limited
compatibility for those legacy names, but new artifacts should use `prompts/` and `tales/`.
