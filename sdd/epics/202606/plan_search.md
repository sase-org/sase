---
create_time: 2026-06-18 21:29:20
bead_id: sase-4x
tier: epic
status: done
prompt: sdd/prompts/202606/plan_search.md
---
# Plan: `sase plan search` — Search SDD & Local Plans

## Goal

Add a new `sase plan search` command that finds **plans** the way `sase bead search` finds beads, but tuned for markdown
plan artifacts. It searches two sources:

1. **Repo `sdd/` plans** (prioritized): `sdd/{tales,epics,legends,myths,research}/YYYYMM/*.md`.
2. **Machine-local plans**: `~/.sase/plans/` (both flat files and `YYYYMM/` shards).

It must support every output format `sase bead search` supports (`compact`, `full`, `json`) with equal-or-higher
quality, add a `markdown` format for agents, support date filtering plus several other useful filters, and produce
output that is intuitive, reliable, and genuinely beautiful (colored, grouped, snippet-highlighted).

## Product Context

`sase bead search` already gives a great answer to "which tracked issues mention X?". But the durable _reasoning_ — the
actual implementation plans, epics, legends, and research — lives in markdown under `sdd/` and in the local
`~/.sase/plans/` archive. Today there is no good way to ask "which plans discussed auth token refresh?" or "show me
every WIP epic touched this month." `sase sdd list` only enumerates files; it does not search content or rank results.

This command closes that gap. A user (or an agent) mid-task can instantly recall prior plans, find the legend that
spawned an epic, or browse recent WIP tales — across both the committed repo plans and the personal local archive, with
the repo plans surfaced first.

## Key Design Decisions (I am leading the design here)

### 1. Backend lives in the Rust core (like `sase bead search`)

`sase bead search` is implemented in `../sase-core/crates/sase_core/src/bead/search.rs` and exposed through PyO3. The
`rust_core_backend_boundary` memory is explicit: behavior a web app, CLI, editor, or TUI would all need to match belongs
in the Rust core. Plan search is exactly that (a TUI "Plans" view or editor integration would want identical results),
so the scan + parse + filter + rank logic goes in `sase_core`, with Python owning only the CLI surface and rendering.
The core already depends on `serde_yaml` (used by the editor frontmatter module) and `chrono`, so frontmatter and date
handling are already available — no new heavy dependencies.

**Considered alternative — Python-only** (reuse `sase.sdd.links`/`parse_frontmatter`): faster to build and fewer moving
parts, but it violates the boundary rule, diverges from the bead-search architecture, would re-scan thousands of
markdown files in Python on every call, and a future TUI/web plan search would have to reimplement it. We choose the
Rust core for consistency, speed (the repo alone has ~1,600 tales and the local archive holds thousands of files), and
reliability. The Python↔Rust contract is a thin wire boundary mirroring `bead_search`.

### 2. Two sources, repo prioritized

Python resolves the source directories (repo `sdd/` root via `sase.sdd.links.resolve_sdd_root`, local via
`~/.sase/plans/`) and passes them to Rust — exactly as bead search passes a `beads_dir`. Rust scans both. Repo plans are
_prioritized_: in the default sort they outrank local plans on ties, and the default compact view groups them under a
**REPO** section above a **LOCAL** section. `--source {all,repo,local}` selects which to scan (default `all`).

### 3. Plan "kinds" (repo): tale, epic, legend, myth, research

These five `sdd/` kinds are the searchable plan corpus. `prompts/` are inputs, not plans, and are excluded by default
(out of scope; can be a future opt-in). Local plans have no kind directory; they surface under a synthetic `local` kind
for display. `--kind` narrows the _repo_ corpus; local plans are governed by `--source`.

### 4. Query is optional → search _or_ browse

Unlike `sase bead search` (which requires a non-empty query), the plan query is **optional**. With a query it does
case-insensitive substring matching (bead-parity) and ranks by relevance. Without a query it becomes a filter/browse
tool — `sase plan search --kind epic --since 14d --status wip` lists matching plans sorted by recency. This is a
deliberate UX improvement over bead search.

### 5. Ranking — where we exceed bead search

`bead search` returns results in storage order (no ranking). Plan search **ranks**:

- **Field weighting**: a hit in the title/H1 outranks a hit in frontmatter, which outranks a hit in the body.
- **Repo boost**: repo plans rank above local plans on otherwise-equal scores.
- **Recency boost**: newer plans get a mild lift so stale duplicates sink.
- `matched_fields` (and a numeric `score`) are returned per result, like bead search's `matched_fields`.

`--sort {relevance,recent,title}` overrides the default (relevance when a query is present, recency when it is not).

### 6. Output: match bead's three formats + a bonus, and make them beautiful

`compact`, `full`, `json` (bead parity) **plus** `markdown` (agent-friendly, mirroring the existing
`sase changespec search --format markdown`). Color is actually wired (bead's `--color` flag is defined but unused in its
renderer): `-c/--color {auto,always,never}`, honoring `NO_COLOR` and TTY detection, using `rich` like the rest of the
CLI.

## UX Sketch

```
$ sase plan search auth

REPO  ▸ sdd/                                                    3 plans
  ◐ tale    202606/auth_token_refresh     Refresh auth tokens on 401
            …retry the request once after refreshing the auth token…
  ✓ epic    202605/unified_auth           Unified auth across providers
  ○ legend  202605/auth_strategy          Long-term auth strategy

LOCAL ▸ ~/.sase/plans/                                          1 plan
  ✓ plan    202604/auth_login_fix         Fix login auth race
            …guard the auth session write behind a lock…

4 plans · 3 repo · 1 local · sorted by relevance
```

- Status icons reuse the bead vocabulary: `◐` wip, `✓` done, `○` none/unknown (colored).
- Kind is a colored label; the matched line is shown as a highlighted snippet (port bead's `_single_line_snippet`
  truncation/centering logic).
- `full` renders a `rich` panel per plan (frontmatter table + body excerpt + path). `json` returns a stable
  `{query, count, results:[{plan, matched_fields, score}]}` envelope. `markdown` emits grouped headings + a table.

## Filters & Flags

All long options have short aliases; help lists them alphabetically (per `cli_rules`).

| Flag                 | Values                                                | Default                        | Purpose                                            |
| -------------------- | ----------------------------------------------------- | ------------------------------ | -------------------------------------------------- |
| `query` (positional) | text                                                  | _(optional)_                   | Literal case-insensitive substring; omit to browse |
| `-c, --color`        | `auto`/`always`/`never`                               | `auto`                         | Color output (honors `NO_COLOR`, TTY)              |
| `-f, --format`       | `compact`/`full`/`json`/`markdown`                    | `compact`                      | Output format                                      |
| `-k, --kind`         | `tale`/`epic`/`legend`/`myth`/`research` (repeatable) | all                            | Filter repo plans by kind                          |
| `-n, --limit`        | int (`0` = unlimited)                                 | `20`                           | Max results                                        |
| `-o, --source`       | `all`/`repo`/`local`                                  | `all`                          | Which corpus to scan (repo prioritized)            |
| `-r, --sort`         | `relevance`/`recent`/`title`                          | relevance if query else recent | Sort order                                         |
| `-s, --status`       | `wip`/`done` (repeatable)                             | all                            | Filter by frontmatter status                       |
| `-A, --since`        | DATE                                                  | —                              | Created on/after DATE                              |
| `-B, --until`        | DATE                                                  | —                              | Created on/before DATE                             |

**DATE** accepts `YYYY-MM-DD`, `YYYY-MM`/`YYYYMM`, or relative `Nd`/`Nw`/`Nm` (e.g. `14d`, `2w`, `3m`). A plan's date is
its frontmatter `create_time`, falling back to file mtime. (`-A`/`-B` echo `grep`'s after/before mnemonic, adapted to
dates.)

## Phasing

Six phases, each completed by a distinct agent. Every phase is independently testable and builds on the prior. Rust
phases run in the `sase-core` sibling (open it with `sase workspace open -p sase-core <N>`); Python phases run in this
repo. After Phase 3 the binding is callable from Python; after Phase 4 `--format json` works end-to-end; after Phase 5
all formats are beautiful.

### Phase 1 — Rust core: plan model + discovery (read layer)

Create `crates/sase_core/src/plan/{mod.rs,wire.rs,read.rs}`:

- `PlanWire { source, kind, path, relpath, name, title, status, created_at, prompt_link, summary, body, frontmatter }`.
- `read_plans(repo_sdd_root: Option<&Path>, local_plans_dir: Option<&Path>, kinds: Option<&[String]>) -> Result<Vec<PlanWire>>`:
  scan repo `sdd/{tale,epic,legend,myth,research}/*/*.md` and local plans (flat + `YYYYMM/*.md`), parse YAML frontmatter
  with `serde_yaml` (reuse the editor module's approach), derive `title` (first markdown H1 → humanized name fallback),
  `status`, `created_at` (frontmatter `create_time` → file mtime), `summary`/`body`.
- Register the module in `lib.rs`.
- **Tests** (inline, mirroring `bead/search.rs` density): discovery across all kinds; flat + sharded local layout;
  frontmatter parse; title/created_at derivation; resilience to missing/malformed frontmatter. `cargo test` green.

### Phase 2 — Rust core: search + filters + ranking

Create `crates/sase_core/src/plan/search.rs`:

- `PlanSearchMatchWire { plan: PlanWire, matched_fields: Vec<String>, score: f64 }`.
- `search_plans(repo_sdd_root, local_plans_dir, query: Option<&str>, kinds, statuses, sources, since, until, sort, limit)`.
- Case-insensitive substring across title, name, status, kind, path, frontmatter values, and body; track
  `matched_fields` (bead parity).
- Filters: kind, status, source, and date range (parse `since`/`until` in all DATE forms above). Empty query =
  browse-all.
- Ranking: field weights (title > frontmatter > body) + repo boost + recency boost; `relevance`/`recent`/`title` sort
  modes; stable, deterministic tie-breaks; limit (`0` = unlimited).
- **Tests**: every field matches; filter composition; date-range filtering and DATE parsing; ranking/order incl.
  repo-prioritization; empty-query browse; limit/unlimited. Match the thoroughness of `bead/search.rs` tests.

### Phase 3 — PyO3 binding + Python facade + parity

- Expose `py_plan_search` in `crates/sase_core_py/src/lib.rs` (signature + `m.add_function(...)` registration + JSON
  wire conversion, following `py_bead_search`).
- In this repo, add a `sase.plan_search` package: `model.py` (`Plan`, `PlanSearchMatch` dataclasses), `wire.py`
  (dict→model), `facade.py` (`require_rust_binding("plan_search")`; resolve repo `sdd/` root via
  `sase.sdd.links.resolve_sdd_root`, local dir via `~/.sase/plans/`; map `--source` to which dirs are passed; pass
  filters through).
- **Tests**: a wire-parity test (Rust JSON shape ↔ Python dataclass), facade resolution tests. Rebuild the binding
  (`maturin develop`); `just install` then targeted tests green.

### Phase 4 — CLI parser + handler + dispatch + JSON format (thin end-to-end slice)

- Add the `search` subparser inside `register_plan_parser` (`src/sase/main/parser_commands.py`), placed alphabetically
  among `approve`/`list`/`propose`/`search`, with complete help/epilog/examples, every flag above (short + long,
  choices, repeatable, `_nonnegative_int`, a DATE-validating type). Update the group description to mention search.
- Route `plan_subcommand == "search"` in `src/sase/main/plan_command_handler.py` to a new `plan_search_handler.py` that
  validates args (dates, limit), calls the facade, and renders **JSON** (so the slice is end-to-end testable now; the
  rich formats land in Phase 5).
- **Tests** (mirror `tests/test_bead/test_cli_search.py`): flag parsing, repeatable accumulation, invalid limit/date
  rejection (exit 2), dispatch routing, JSON envelope shape, no-match success.

### Phase 5 — Beautiful rendering: compact / full / markdown + color + snippets

- Implement `compact`, `full`, and `markdown` renderers (a `plan_search_render.py`): `rich`-colored compact with source
  grouping (REPO first), kind + status icons, title, and a highlighted matched-line snippet (port bead's
  `_single_line_snippet`); `full` = `rich` panel (frontmatter table + body excerpt + path); `markdown` = grouped
  headings + table (mirroring `search_handler.py`).
- Implement `-c/--color` (auto/always/never; honor `NO_COLOR` + `isatty`).
- **Tests**: renderer unit tests for each format incl. grouping, icons, snippet truncation, empty results; add a text or
  PNG snapshot if it fits the existing visual-snapshot harness.

### Phase 6 — Generated skills, docs, integration, final check

- Regenerate/extend generated skills per the `generated_skills` pipeline so the CLI↔skill contract covers
  `sase plan search` (the `sase_beads` skill is the model for a search-command skill reference).
- Update docs: `sdd/README.md` "Commands" list, `sase plan` group help examples, and any user-facing help/AGENTS
  references.
- Add an end-to-end integration test (`sase plan search` over a temp repo `sdd/` + temp local dir across formats).
- Run `just check` (after `just install`) in this repo and `cargo test`/the core's checks in `sase-core`; ensure
  everything is green.

## Risks & Mitigations

- **Cross-repo coordination (Rust core + bindings).** Phases 1–3 touch `sase-core`; the rest touch this repo. Each phase
  opens the correct workspace and ends green, so the seams are clean. Mitigation: explicit per-phase repo callouts
  above.
- **Scale / performance.** Thousands of markdown files. The Rust scan + substring match is fast; we also cap output with
  a default `--limit 20`. If needed later, an on-disk index is a future optimization (out of scope now).
- **Local archive heterogeneity.** Older `~/.sase/plans/` files may lack frontmatter. The read layer degrades gracefully
  (mtime for date, humanized filename for title).
- **Flag ergonomics.** Date short flags `-A/-B` are documented with the grep-style mnemonic; all flags are sorted and
  short-aliased per `cli_rules`.

## Out of Scope / Future

- Searching `sdd/prompts/` (inputs, not plans) — could be a future `--include-prompts`.
- A dedicated `sase plan show <name>` (the `full` format covers detailed viewing for now).
- A TUI "Plans" search view and editor integration — enabled by, but not part of, this work (the Rust backend makes them
  straightforward later).
- Fuzzy/semantic search and a persistent search index.
