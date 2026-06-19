---
name: sase_plan_search
description:
  Reference for the `sase plan search` command (search or browse SDD and machine-local markdown plans). Use when finding
  or browsing implementation plans, epics, legends, myths, or research.
skill: true
---

Quick reference for the `sase plan search` CLI. Use `sase plan search` (not `.venv/bin/sase plan search`) for all plan
searches. This finds **plans** the way `sase bead search` finds beads, but tuned for markdown plan artifacts.

It searches two sources, with repo plans prioritized:

1. **Repo `sdd/` plans** (surfaced first): `sdd/{tales,epics,legends,myths,research}/YYYYMM/*.md`.
2. **Machine-local plans**: the `~/.sase/plans/` archive (flat files and `YYYYMM/` shards), shown under a synthetic
   `local` kind.

The query is **optional**: pass a query to search and rank by relevance, or omit it to browse/filter sorted by recency.

## Quick start

```bash
# Search both corpora for a literal substring (repo plans ranked first)
sase plan search auth

# Browse without a query: list recent WIP epics from the last two weeks
sase plan search --kind epic --status wip --since 14d

# Machine-readable envelope for agents
sase plan search auth --format json

# Agent-friendly grouped markdown
sase plan search auth --format markdown

# Only the repo corpus, newest first, capped at five results
sase plan search auth --source repo --sort recent --limit 5
```

## Flags

All long options have short aliases; choices are validated by the parser.

| Flag                 | Values                                                | Default                        | Purpose                                            |
| -------------------- | ----------------------------------------------------- | ------------------------------ | -------------------------------------------------- |
| `query` (positional) | text                                                  | _(optional)_                   | Literal case-insensitive substring; omit to browse |
| `-c, --color`        | `auto`/`always`/`never`                               | `auto`                         | Color output (honors `NO_COLOR` and TTY)           |
| `-f, --format`       | `compact`/`full`/`json`/`markdown`                    | `compact`                      | Output format                                      |
| `-k, --kind`         | `tale`/`epic`/`legend`/`myth`/`research` (repeatable) | all                            | Filter repo plans by kind                          |
| `-n, --limit`        | int (`0` = unlimited)                                 | `20`                           | Max results                                        |
| `-o, --source`       | `all`/`repo`/`local`                                  | `all`                          | Which corpus to scan (repo prioritized)            |
| `-r, --sort`         | `relevance`/`recent`/`title`                          | relevance if query else recent | Sort order                                         |
| `-s, --status`       | `wip`/`done` (repeatable)                             | all                            | Filter by frontmatter status                       |
| `-A, --since`        | DATE                                                  | —                              | Only plans created on/after DATE                   |
| `-B, --until`        | DATE                                                  | —                              | Only plans created on/before DATE                  |

**DATE** accepts `YYYY-MM-DD`, `YYYY-MM`/`YYYYMM`, or a relative `Nd`/`Nw`/`Nm` offset (e.g. `14d`, `2w`, `3m`). A plan's
date is its frontmatter `create_time`, falling back to the file mtime. (`-A`/`-B` echo `grep`'s after/before mnemonic,
adapted to dates.)

## Output formats

- `compact` (default) — colored, grouped listing with a **REPO** section above a **LOCAL** section, status icons (`◐`
  wip, `✓` done, `○` none/unknown), a kind label, the plan title, and a highlighted matched-line snippet.
- `full` — a `rich` panel per plan: frontmatter table, body excerpt, and path.
- `json` — a stable `{query, count, results:[{plan, matched_fields, score}]}` envelope for agents and scripts.
- `markdown` — grouped headings plus a results table; ideal to paste into agent context.

## Filters & sources

```bash
# Filter repo plans by kind (repeatable) and frontmatter status (repeatable)
sase plan search refactor --kind tale --kind epic --status wip

# Scope which corpus to scan; repo plans always rank above local on ties
sase plan search auth --source local
sase plan search auth --source repo

# Bound the create date range; combine with browse mode to audit a window
sase plan search --since 2026-01-01 --until 2026-03
```

## Notes

- Matching is a case-insensitive literal substring across title, name, status, kind, path, frontmatter values, and body;
  `matched_fields` reports which fields a query hit.
- Repo plans are boosted above local plans, and newer plans get a mild recency lift, so the most relevant, freshest
  plans surface first.
- `--limit 0` (or `-n 0`) returns every match; the default cap is `20`.
- `sase plan search` is read-only — it never modifies plans.
