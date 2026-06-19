---
create_time: 2026-06-18 21:24:36
status: wip
prompt: sdd/prompts/202606/prompt_search_command.md
---
# Plan: `sase prompt search` — unified full-text search over SDD + local prompts

## Purpose

Add a new `sase prompt search <query>` command, modeled on `sase bead search`, that finds **any prompt whose text (or
metadata) contains the query**, across two stores at once:

1. **Repo SDD prompts** — the committed `sdd/prompts/**/*.md` snapshots (plus the legacy root `prompts/` and local
   `.sase/sdd/prompts/` layouts). These are curated, repo-relevant, and **ranked first**.
2. **Local prompt history** — the machine-wide `~/.sase/prompt_history.json` store that the rest of the `sase prompt`
   family already owns (every prompt ever submitted on this machine, across all repos).

It joins the `sase prompt` command group as a first-class sibling of `list`/`show`/`stats`, offering the same three
output formats as `sase bead search` — `compact`, `json`, `full` — with **higher-quality output** (source grouping,
match highlighting, "why it matched", and bounded-by-default results). It answers "I remember a prompt about X — find
it, whether I snapshotted it into this repo or just ran it once last month."

Today there is no way to search across these two stores. `sase prompt list -q` does a substring filter over **local
history only** and never sees the repo `sdd/prompts/` snapshots; nothing searches the SDD prompts at all. `search` fills
that gap and unifies the two.

## Product design

### Command surface

```
sase prompt search <query> [-f|--format compact|json|full]
                           [-s|--source sdd|local|all]
                           [-a|--after  DATE]
                           [-b|--before DATE]
                           [-t|--tag TAG ...]
                           [-x|--cancelled]
                           [-n|--limit N]
                           [-c|--color auto|always|never]
```

The flag set is deliberately a **parallel of `sase bead search`** so muscle memory transfers: `-f/--format`,
`-n/--limit`, `-c/--color` are identical; `-s/--source` plays the role bead's `-s/--status` plays (the primary scope
filter); `-t/--tag` parallels bead's `-t/--type`. Date range (`-a/--after`, `-b/--before`) and `-x/--cancelled` are
prompt-specific. Subcommands and options are listed alphabetically in help; every public long option has a short alias
(per `cli_rules`).

- **`query`** (positional, required): a whitespace-only query is a usage error (exit `2`), matching `bead search`.
- **`-s|--source`** (default `all`): `sdd` searches only repo SDD snapshots, `local` only the machine history, `all`
  both. In `all`, SDD hits always rank above local hits (the user's "prioritize repo-specific prompts" requirement).
- **`-a|--after` / `-b|--before`** (date filters): keep prompts whose date is on/after `--after` and on/before
  `--before`. Accepted forms (intuitive, generous): `YYYY-MM-DD`, `YYYYMM`, `YYmmdd`, SASE `YYmmdd_HHMMSS`, and relative
  offsets `Nd`/`Nw`/`Nm`/`Ny` (e.g. `--after 30d` = last 30 days). Reuses and extends the existing `parse_prune_date`
  logic; an unparseable date is a usage error (exit `2`) with examples.
- **`-t|--tag`** (repeatable): keep prompts carrying a matching tag — SDD `prompt_tags` frontmatter and the parsed
  `#xprompt` chips / directive tokens embedded in the prompt body. ANDs across repeats are unnecessary; repeats OR (a
  prompt matches if it carries _any_ listed tag), which is the intuitive reading of "tagged review **or** auth".
- **`-x|--cancelled`**: restrict **local** results to cancelled prompts (default searches both launched and cancelled —
  when you search you want to find things, including abandoned prompts). No effect on SDD snapshots (they have no
  cancelled state); documented as such.
- **`-n|--limit`** (default `20`, `0` = unlimited): caps **shown** results after ranking. Unlike `bead search`
  (unlimited, because bead stores are tiny), the local history is large (tens of thousands of entries), so a bounded
  default keeps the default experience fast and beautiful. Truncation is **never silent**: every format reports total
  matches vs shown (e.g. `showing 20 of 137`).
- **`-c|--color`** (default `auto`): `auto` colorizes when stdout is a TTY and `NO_COLOR` is unset; `always`/`never`
  force it. `json` is **never** colored.

### What counts as a "prompt", and the date used for each

A unified `PromptHit` represents one result from either store:

| Field         | SDD snapshot                                                                      | Local history entry                 |
| ------------- | --------------------------------------------------------------------------------- | ----------------------------------- |
| `source`      | `sdd`                                                                             | `local`                             |
| locator / id  | repo-relative path stem (e.g. `kitty_image_panel_fix`)                            | `ph_<sha256[:12]>` content ID       |
| `path`        | `sdd/prompts/202604/kitty_image_panel_fix.md`                                     | — (the store is a single JSON file) |
| `title`       | filename slug → first non-empty body line                                         | cleaned one-line preview            |
| `text`        | body (frontmatter stripped)                                                       | exact prompt text                   |
| `date`        | frontmatter `last_used`→`timestamp`; else `YYYYMM` from the path; else file mtime | `last_used`                         |
| `plan`        | frontmatter `plan:` link (the tale/epic it produced)                              | —                                   |
| `tags`        | `prompt_tags` + parsed `#xprompt`/directive chips                                 | parsed `#xprompt`/directive chips   |
| `cancelled`   | — (always shown)                                                                  | the entry's cancelled flag          |
| `text_sha256` | recorded frontmatter `sha256` if present, else computed                           | the entry's content digest          |

The **date precedence** for SDD snapshots is explicit and documented (frontmatter timestamps win because
`prompt export --sdd` records them; the `YYYYMM` path segment is the reliable fallback; mtime is last resort). This is
the date `--after`/`--before` filter against, and the date shown in output.

### Matching semantics (the "reliable" contract)

- **Case-insensitive Unicode substring match** of the literal query — no regex, glob, or tokenization. Same predictable
  posture as `bead search` (regex / term-AND / fuzzy are noted as future work).
- **"Anywhere" = every human-readable field**, matched per-field so we can tell the user _why_ a hit matched and
  highlight it: `title`, `body`, locator/`id`, `path` (SDD), `plan` link (SDD), and `tags`/chips. `matched_fields` is
  recorded on each hit.
- **Default scope is wide**: both sources, all dates, launched **and** cancelled. Filters narrow.
- **Deterministic ranking** (the "higher quality than bead" part — bead uses raw store order):
  1. **Source priority** — SDD before local when `--source all`.
  2. **Match tier** within a source — a hit in `title`/locator/`path` outranks a body-only hit.
  3. **Recency** — newer `date` first.
  4. **Stable tiebreak** — locator/path, so output is byte-stable across runs.
- **De-duplication**: when `--source all`, an SDD snapshot and a local entry with the **same `text_sha256`** are the
  same prompt (snapshots are made _from_ history). They collapse into the single SDD hit (prioritized), annotated
  `also in local history`. Best-effort: relies on the recorded/`computed` digest; never hides a hit it isn't certain is
  a duplicate.

### Output formats

1. **`compact`** (default) — grouped, scannable, one entry per hit:
   - A dim group header per source: `── SDD prompts (3) ──`, `── Local history (17) ──`.
   - Line 1: `{source-badge} {locator}  {dim date}  {dim path-or-status}` with the matched substring highlighted in the
     title/locator.
   - Line 2 (dim, indented): a single-line body snippet centered on the match, highlighted; if the match was **not** in
     title/body, show the field instead, e.g. `plan: "…tales/202604/kitty_image_panel_fix.md"` or `tag: "review"`, so
     the user always sees why it matched.
   - Footer: `27 matches (3 SDD · 24 local) · showing 20`. Rich-based, restrained palette consistent with
     `sase prompt list` (cyan ids, dim metadata, magenta/dim for cancelled, highlight on the matched term).
2. **`json`** — a self-describing, never-colored envelope (`indent=2`, stable key order):
   ```json
   {
     "query": "auth",
     "count": 20,
     "total": 27,
     "counts": { "sdd": 3, "local": 24 },
     "results": [
       {
         "source": "sdd",
         "id": "rotate_auth_tokens",
         "path": "sdd/prompts/202605/rotate_auth_tokens.md",
         "title": "Rotate auth tokens on…",
         "date": "2026-05-12",
         "matched_fields": ["title", "body"],
         "tags": ["review"],
         "plan": "sdd/tales/202605/rotate_auth_tokens.md",
         "cancelled": null,
         "text_sha256": "…",
         "text_chars": 412,
         "text": "…full prompt body…"
       }
     ]
   }
   ```
   Carries full `text` (parity with `bead search` json and `prompt show -f json`) so downstream tooling is
   self-sufficient; `count`/`total`/`counts` make truncation explicit.
3. **`full`** — for each hit, the complete prompt rendering, separated by a divider, with a per-hit header
   (`{badge} {locator} · {date}`):
   - **local** hits reuse the existing `sase prompt show` Markdown rendering verbatim (no second renderer to drift).
   - **SDD** hits render the file as it reads on disk: a compact metadata header (path, date, `plan` link, tags) plus
     the body, with the matched term highlighted.

### Empty-result and error behavior

- **No matches**: not an error (exit `0`). `compact`/`full` print `No prompts match "<query>".`; `json` prints the
  envelope with `count: 0`, `total: 0`, `results: []`.
- **Empty/whitespace query**: usage error, exit `2` (mirrors `bead search`).
- **Unparseable `--after`/`--before`**: usage error, exit `2`, with accepted-format examples.
- **Not in a repo / no `sdd/prompts/`**: the SDD source is simply empty; `local` still works. A corrupt or unreadable
  `prompt_history.json` is tolerated read-only (the store is never written — `search` takes no locks) and reported.

### Out of scope (and why)

- **TUI integration / a prompt-history search box** — this is a CLI request; the unified engine here is the right
  foundation for a later TUI feature (forward-compatible, not forward-built).
- **Rust-core migration** — the entire `sase prompt` family is intentionally Python over the JSON store
  (`sase_plan_prompt_command.md` explicitly defers SQLite/Rust "until the command contract is stable or another frontend
  needs the same richer backend API"). `search` honors that decision; see _Technical design_ for the boundary
  justification.
- **Regex / term-AND / fuzzy matching, relevance scoring beyond the tier+recency model, `--field` scoping** — natural
  follow-ons the per-field match model leaves room for; v1 ships the predictable substring core.
- **Editing/replaying from `search`** — `search` is read-only and discovery-only; the locator it prints (`ph_…` for
  local) feeds directly into `sase prompt show/run/edit/copy`, so reuse flows through the existing commands.

## Technical design

### Where the code lives (architecture)

Implement in **Python under `src/sase/prompt/`**, consistent with the existing `sase prompt` family and its deferral of
Rust core. Boundary check against `rust_core_backend_boundary`: bead _read commands already dispatch and render in Rust
core_, so `bead search` belonged there; the prompt family has **no** Rust-core surface and **no** other frontend that
must match a TUI today. `search` is a read-only join over two file stores plus presentation. If a future frontend needs
the same engine, migrate then — the module boundary below is built to make that lift clean (pure data layer + engine,
separable from rendering). This is called out as a deliberate, documented choice, not an oversight.

`search` is read-only: it never writes either store and needs no lock (unlike the mutating `prompt` subcommands).

### Module layout

- `src/sase/prompt/search/model.py` — `PromptSource` enum (`SDD`, `LOCAL`), `PromptHit` dataclass, `PromptSearchMatch`
  (`hit` + `matched_fields`), `PromptSearchResult` envelope (`matches`, `total`, per-source `counts`).
- `src/sase/prompt/search/sources.py` — `load_sdd_prompt_hits(base_dir)` (discovers via
  `sdd._paths.sdd_kind_roots(..., "prompts")` so canonical `sdd/prompts/`, legacy root `prompts/`, and local
  `.sase/sdd/prompts/` are all covered; parses frontmatter, body, date, tags, `plan` link), `load_local_prompt_hits()`
  (thin adapter over `history.prompt.list_prompt_records` → `PromptHit`), and `collect_prompt_hits(sources, base_dir)`
  (unify + dedup).
- `src/sase/prompt/search/dates.py` — `parse_search_date(text)` extending `parse_prune_date` with `YYYYMM` and relative
  `Nd/Nw/Nm/Ny`; `hit_date(hit)` precedence helper.
- `src/sase/prompt/search/engine.py` —
  `search_prompts(query, hits, *, sources, after, before, tags, cancelled_only, limit) -> PromptSearchResult`: matching
  (records `matched_fields`), filtering (source/date/tag/cancelled), ranking, and limit. Pure, render-free.
- `src/sase/prompt/cli_search.py` — `handle_prompt_search` + the `compact`/`json`/`full` renderers.
- `src/sase/prompt/render.py` — extend with a match-highlight helper, source badge, and date formatter (reuse
  `format_timestamp`).
- `src/sase/main/parser_prompt.py` — register the alphabetically-placed `search` subparser.
- `src/sase/main/prompt_handler.py` — dispatch `search` → `handle_prompt_search`.

### Phase 1 — Data layer: unified sources, model, dates (sase)

Pure data, no CLI, no rendering.

- `PromptSource`, `PromptHit`, `PromptSearchMatch`, `PromptSearchResult`.
- SDD loader: discover across canonical/legacy/local roots; parse frontmatter (reuse the repo's existing YAML
  frontmatter handling), strip it from `text`, derive `title`, `tags` (`prompt_tags` + parsed chips), `plan`, and the
  documented `date` precedence; tolerate malformed frontmatter per-file without failing the scan.
- Local adapter over `list_prompt_records` → `PromptHit` (id, text, last_used, cancelled, parsed chips).
- `collect_prompt_hits` unifier + sha-based de-dup (prefer SDD).
- `parse_search_date` (extends `parse_prune_date`: `YYYY-MM-DD`, `YYYYMM`, `YYmmdd`, `YYmmdd_HHMMSS`, relative
  `Nd/Nw/Nm/Ny`) and `hit_date` precedence.
- **Tests**: SDD discovery across all three layouts; frontmatter parse + body strip; date precedence (frontmatter vs
  path vs mtime); tag extraction; local adapter shape; dedup-prefers-SDD; every date form + relative offsets + rejection
  of garbage.

**Deliverable:** a tested unified prompt corpus + date parsing. **Depends on:** nothing.

### Phase 2 — Search engine: match, filter, rank, limit (sase)

- Matching predicate (case-insensitive Unicode substring across the field set) recording `matched_fields`.
- Filters (AND): `source`, `after`/`before` vs `hit_date`, `tags` (OR across repeats), `cancelled_only` (local only).
- Ranking: source priority → match tier → recency → stable tiebreak.
- Limit applied after ranking; `PromptSearchResult` records `total` and per-source `counts` so truncation is reportable.
- **Tests**: match in each field; case-insensitivity; both sources found; SDD-before-local ordering; match-tier
  ordering; date-range, tag, cancelled, source filters AND correctly; limit + total/counts; empty/whitespace query;
  no-match; determinism.

**Deliverable:** a tested, deterministic engine returning ranked matches + counts. **Depends on:** Phase 1.

### Phase 3 — CLI surface + `compact` renderer (sase)

- `parser_prompt.py`: register `search` with the full flag set (alphabetical, short aliases, excellent help, accepted
  date forms documented in help). `prompt_handler.py`: dispatch.
- `handle_prompt_search`: argument validation (empty-query / bad-date → exit `2`), resolve `--color`, call the engine,
  render.
- `compact` renderer: source group headers, per-hit line + highlighted snippet, "why it matched" for non-body hits,
  footer counts; Rich palette consistent with `prompt list`; color gated on the resolved decision; `NO_COLOR` honored.
- **Tests**: parser/help coverage incl. the short-alias assertion (extend `tests/prompt_command/test_parser.py`);
  compact output for hits across both sources, highlight, non-body match line, footer; `--color never/always`; no-match
  (exit 0) and empty-query (exit 2); `--source`/date/`--tag`/`--cancelled`/`--limit` behavior end-to-end.

**Deliverable:** `sase prompt search` works with the default `compact` format. **Depends on:** Phases 1–2.

### Phase 4 — `json` + `full` renderers (sase)

- `json`: the stable envelope (`query`, `count`, `total`, `counts`, `results[]` with full `text`); never colored.
- `full`: per-hit header + divider; **local** reuses `sase prompt show` Markdown; **SDD** renders metadata header + body
  with highlighting. Keep local output consistent with `sase prompt show <id>` (no drift).
- **Tests**: json schema/shape, stable keys, `count` vs `total` vs `counts`, no-color, full-text presence; full-format
  rendering for an SDD hit and a local hit, divider, header, highlight; local `full` matches `prompt show` output.

**Deliverable:** all three formats at parity-or-better with `bead search`. **Depends on:** Phase 3.

### Phase 5 — Docs, polish, integration (sase)

- `docs/prompt.md`: add a `search` row to the command inventory and a focused **Search** section (cross-store search,
  the two sources + SDD prioritization, the three formats, date/tag/source/cancelled filters, examples per format);
  confirm `mkdocs.yml` needs no new entry. No generated skill exists for `sase prompt` (only `sase_beads.md`), so **no
  `sase skill init`/`chezmoi` step is required** — docs are the single source of truth here.
- Audit `sase prompt search --help` and the group help; ensure the bare-`sase prompt` → `list` default convention and
  command tables stay correct (`tests/main/test_parser_command_defaults.py`).
- Add a large-history fixture test asserting `compact`/`json`/`full` stay **bounded** under the default limit and never
  dump the whole store, and that totals/counts are accurate.
- `just install` then `just check` (and `just test-visual` only if any snapshot is touched — none expected) green.

**Deliverable:** shipped, documented, bounded-output-tested. **Depends on:** Phase 4.

## Risks & mitigations

- **Local history is large (33MB+).** A linear scan over exact text is still fast, but unbounded output isn't beautiful
  → bounded default `--limit 20` with explicit `showing X of Y`, and the large-history test in Phase 5 guards against
  accidental full dumps or full-text leakage in `compact`.
- **Two `full` renderers drifting** (local vs SDD) → local reuses the existing `prompt show` renderer verbatim; only the
  SDD file rendering is new, and it mirrors the on-disk layout.
- **Date ambiguity across sources** → one documented precedence (frontmatter → path `YYYYMM` → mtime for SDD;
  `last_used` for local), unit-tested, and surfaced in output so the filtered date is never a mystery.
- **De-dup false positives/negatives** → strictly sha-based and conservative (collapse only on digest equality, prefer
  SDD, annotate); never hides a hit it can't prove is a duplicate.
- **Corrupt/missing stores** → read-only tolerance: missing `sdd/prompts/` ⇒ empty SDD source; unreadable history ⇒
  reported, never rewritten (search takes no lock).

## Validation

- `just check` (parser/help + short aliases, engine, both sources, all three formats, filters, exit codes, large-history
  bounds).
- Manual smoke on this repo's real `sdd/prompts/` + local history: `search tui` (compact), `--source sdd`,
  `--source local -x`, `--after 30d`, `--before 2026-05-01`, `--tag review`, `--format json | jq`, `--format full`,
  `--limit 0`, `--color never|always`, a no-match query, an empty-query usage error, and an unparseable date.

## Phase summary

| Phase | Scope                                                                                    | Depends on |
| ----- | ---------------------------------------------------------------------------------------- | ---------- |
| 1     | Unified `PromptHit` model, SDD + local sources, dedup, date parsing — data layer + tests | —          |
| 2     | Search engine: match (`matched_fields`), filters, ranking, limit, counts — + tests       | 1          |
| 3     | `search` parser/dispatch + `compact` renderer (color, highlight, grouping) — + tests     | 1, 2       |
| 4     | `json` + `full` renderers (full-text json; reuse `prompt show` for local) — + tests      | 3          |
| 5     | Docs (`docs/prompt.md`), help audit, large-history bounds test, `just check`             | 4          |
