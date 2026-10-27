---
title: "Footprint"
description: "How Footprint feature IDs and the generated catalog work."
---

# Footprint: feature IDs and the catalog

Footprint is a local usage census: a generated **catalog** of every sase surface joined
with per-day aggregate counts, so a review can find surfaces with no recorded use. The
catalog is the denominator; without it, "never used" is indistinguishable from "never
measured."

## How IDs are formed

A feature ID has the form `<ns>:<path>` and matches `^[a-z]+:[a-z0-9_.~#-]+$`. The
namespaces are `cli`, `tui`, `view`, `macro`, `skill`, `config`, `auto`, and `plugin`.
Real registry names that predate the scheme are sanitized through
`sase.footprint.ids.sanitize` (lowercased, disallowed characters become `_`), so
`sase bead +1` is `cli:bead._1` and the `ref:plan` artifact reference is
`tui:artifacts.ref_plan`. Both the recorder and the generator sanitize through that one
helper, so IDs cannot drift between them.

| ns       | Example                      | Source of truth                                 |
| -------- | ---------------------------- | ----------------------------------------------- |
| `cli`    | `cli:bead.list`, `cli:_root` | Full argparse tree; options use `dest` names    |
| `tui`    | `tui:app.zoom_panel`         | Palette catalog, keymap scopes, built-in modes  |
| `view`   | `view:tab.agents`            | Tabs, subtabs, center tabs, stats views, modals |
| `macro`  | `macro:research`             | Bundled macros in `src/sase/macros/`            |
| `skill`  | `skill:sase_repo`            | Generated skill sources                         |
| `config` | `config:ace.page_size`       | `default_config.yml` leaf paths                 |
| `auto`   | `auto:axe.housekeeping.jobs` | AXE routine and job names                       |
| `plugin` | `plugin:listen`              | First-party plugin command words                |

Rules:

- **Allowlist, never denylist.** An unrecognized value collapses to `<ns>:~other`.
  User-defined names (custom macros, custom modes, saved-query contents) become
  `~custom`. `tui:saved_query.<n>` slot numbers are fine.
- **Aliases share one ID.** Legacy CLI words (`changespec`, `task`, `vcs`,
  `artifact-file`) resolve to their canonical command through `ids.CLI_ALIASES`. The key
  binding and the palette entry for one action are one feature reached two ways (`via`).
- **Navigation chrome is neither counted nor catalogued.** Cursor movement, scroll, and
  focus/tab cycling live in `ids.NAVIGATION_ACTIONS`. A catalogued action that is never
  recorded would look like a false deletion candidate.
- The generator uses **bundled defaults only**: it never reads the user's config, keymap
  overrides, saved queries, or custom modes, and it keeps only built-in TUI IDs
  (provider-discovered artifact tabs are resolved at record time against their
  `view:tab.*` entries instead).

## How to regenerate

The catalog lives at `src/sase/footprint/catalog.jsonl` (plus a header line with the
schema, entry count, and `rev`). Regenerate it with `just fix` (runs
`just sync-footprint-catalog`); `just lint` fails when the checked-in file drifts from
the registries. A PR that adds a parser leaf, option, binding, macro, skill, view,
modal, or config leaf fails lint until the catalog is regenerated, so surface changes
stay visible in diffs.

`src/sase/footprint/catalog.py` loads the catalog and the overlay off the hot path; hot
paths import only `ids` and `paths`.

## What the overlay is for

`src/sase/footprint/overlay.yml` holds curated human knowledge, reviewed in PRs:
`protected` classes (`recovery`, `safety`, `bootstrap`, `infra`) for rare-by-design
surfaces with a `why`, `keep` reasons (`rare_by_design`, `safety`, `agent_facing`,
`api_contract`, `other`), and `retire_with` siblings a cut should remove together. Every
key is an exact ID or a trailing-`*` glob, and every key must match at least one catalog
ID. The generator test fails otherwise.
