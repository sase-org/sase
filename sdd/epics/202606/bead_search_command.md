---
create_time: 2026-06-18 08:10:58
bead_id: sase-4w
tier: epic
status: done
prompt: sdd/prompts/202606/bead_search_command.md
---
# Plan: `sase bead search` — full-text search over beads

## Purpose

Add a new `sase bead search <query>` command that finds **any bead whose text contains the query string anywhere**, with
three output formats: machine-readable `json`, a scannable one-line-per-bead `compact` view, and the `full` per-bead
`sase bead show` rendering. The command should feel like a first-class member of the `bead` family — intuitive
(predictable matching, sensible defaults), reliable (deterministic, exit codes that mean something), and beautiful
(colored, highlighted, aligned output).

This is greenfield: there is **no** text-search capability over beads today. Filtering is limited to status / type /
tier enums (`sase bead list`). `search` fills the gap of "I remember a bead mentioned X, find it."

## Product design

### Command surface

```
sase bead search <query> [-f|--format compact|json|full]
                         [-s|--status open|in_progress|closed ...]
                         [-t|--type plan|phase ...]
                         [--tier plan|epic|legend ...]
                         [-n|--limit N]
                         [-c|--color auto|always|never]
```

- **`query`** (positional, required): the text to find. A non-empty, whitespace-only query is a usage error (exit `2`).
- **`-f|--format`** (default `compact`): the three formats the user asked for, named for what they are.
- **Scope filters** (`--status`, `--type`, `--tier`): mirror `sase bead list` **exactly** (same spellings, repeatable)
  so muscle memory transfers. They AND with the text match, letting a user scope a search (e.g.
  `search auth --status open --type phase`).
- **`-n|--limit`**: cap the number of results (absent / `0` = unlimited). Cheap, high-value for `full` output.
- **`-c|--color`** (default `auto`): `auto` colorizes when stdout is a TTY and `NO_COLOR` is unset; `always` / `never`
  force it. `json` is **never** colored.

### Matching semantics (the contract that makes it "reliable")

- **Case-insensitive substring match.** The literal query string is matched as a substring (Unicode-aware lowercasing).
  No regex, no glob, no tokenization — this is the most predictable reading of "contains that text anywhere", and it
  never surprises the user with metacharacters. (Regex / term-AND are noted as future enhancements below.)
- **"Anywhere" = every human-readable field**, matched per-field so we can tell the user _why_ a bead matched and
  highlight the hit: `id`, `title`, `description`, `notes`, `design`, `owner`, `assignee`, `model`, `changespec_name`,
  `changespec_bug_id`, and the rendered `status` / `type` / `tier` values.
- **Default status scope is ALL statuses** (open, in_progress, **and closed**) — unlike `list`, which defaults to
  open+in_progress. When you search you want to find things, including finished work. `--status` narrows.
- **Deterministic ordering**: same order as `sase bead list` (store / id order). Relevance ranking is deliberately out
  of scope for v1 (noted below) to keep results predictable and the engine simple.

### Output formats

1. **`compact`** (default) — "bead name and short description only". One bead per entry:
   - Line 1: `{status-icon} {id} · {title}` (icon + id colored; the matched substring highlighted wherever it appears in
     the title).
   - Line 2 (dimmed, indented): a short single-line description snippet (first line of `description`, truncated), with
     the matched term highlighted. When the match was **not** in title/description, instead show the matching field and
     a snippet, e.g. `notes: "...the auth token rotation..."`, so the user always sees why the bead matched.
2. **`json`** — a self-describing envelope, pretty-printed (`indent=2`, stable key order), never colored:
   ```json
   {
     "query": "auth",
     "count": 2,
     "results": [
       { "issue": { ...full IssueWire fields... }, "matched_fields": ["title", "notes"] }
     ]
   }
   ```
   The `issue` object is the canonical bead serialization (identical shape to the existing wire/`bead_export_jsonl`
   output) so downstream tooling can rely on it; `matched_fields` explains the hit.
3. **`full`** — for each matching bead, the complete `sase bead show` rendering, separated by a divider. This reuses the
   existing Rust `show` renderer verbatim so `full` output is byte-identical to running `sase bead show <id>` on each
   hit (no second rendering to drift).

### Empty-result and error behavior

- **No matches**: not an error. `compact`/`full` print a friendly `No beads match "<query>".`; `json` prints the
  envelope with `count: 0` and `results: []`. Exit `0` (mirrors `list`'s "No issues found." → exit 0).
- **Empty/whitespace query**: usage error, exit `2`.
- **No bead store / unreadable store**: same error path as the other read commands.

### Out of scope (and why)

- **TUI integration** (a search box in the `sase ace` beads view) — the request is a CLI command; the Rust engine built
  here is the right foundation for a later TUI feature, so it is forward-compatible, not forward-built.
- **Relevance ranking, regex/term-AND matching, field-scoped search (`--field`), fuzzy matching** — all are natural
  follow-ons that the per-field match model leaves room for, but each trades away predictability or adds scope; v1 ships
  the predictable substring core.

## Technical design

### Where the code must live (architecture constraint)

`sase bead` read commands are **dispatched and rendered entirely in the Rust core**. The Python "fast path"
(`src/sase/main/bead_fast_path.py`) intercepts every `sase bead …` invocation and calls the Rust binding
`bead_cli_execute` (`crates/sase_core/src/bead/cli.rs::execute_bead_cli`), which parses argv, runs the query, **and
produces the fully-rendered stdout string**; Python just prints it. The Python handlers in `src/sase/bead/cli_query.py`
are only reached as a fallback (binding unavailable, `-h/--help`, or non-VC mode).

This, plus the `rust_core_backend_boundary` rule (a web/editor frontend would need search to match the TUI/CLI → core
logic), means: **search matching + rendering belong in Rust core**; Python gets a thin parser, a fallback handler, and a
facade. Building search anywhere else would create two divergent implementations.

Build/consume flow: `sase-core-rs` is a version-pinned binding (`pyproject.toml`: `sase-core-rs>=0.1.1,<0.2.0`).
`just rust-install` does an editable build against `../sase-core`; `just rust-check` / `just rust-test` run the Rust
suite. The Python phases require the Rust phases to be built locally via `just rust-install`.

### Phase 1 — Rust core: the search engine (sase-core)

Pure domain logic, no CLI, no binding. In `crates/sase_core/src/bead/` (new `search.rs` module, or extend `read.rs`
alongside `list_issues`/`ready_issues`):

- A `search_issues(beads_dir, query, statuses, types, tiers, limit)` function that loads issues via the existing
  `read_store_issues` and returns matches in list order.
- A `BeadSearchMatchWire { issue: IssueWire, matched_fields: Vec<String> }` result type (serde, in `wire.rs`), so both
  the CLI renderer (Phase 2) and the JSON output carry "why it matched".
- The matching predicate: Unicode case-insensitive substring over the field set defined above, recording which fields
  hit. Centralize the field list so it cannot silently drift from the data model.
- Rust unit tests: matches in each field; case-insensitivity; closed beads found by default; status/type/tier filters
  AND correctly; limit; empty/whitespace query handling; deterministic ordering; no-match.

**Deliverable:** a tested, deterministic search engine. **Depends on:** nothing.

### Phase 2 — Rust core: CLI subcommand, renderers, and binding (sase-core)

- **Dispatch:** add `"search" => handle_search(...)` to the `execute_bead_cli` match in `cli.rs`.
- **Arg parsing:** hand-rolled (consistent with the existing `parse_list_filters` / `parse_update_fields`) for the
  positional query, `-f/--format`, `-s/--status`, `-t/--type`, `--tier`, `-n/--limit`, `-c/--color`.
- **Renderers:** `compact` (icon + id + title + snippet, with match highlighting), `json` (the envelope above, via serde
  — never colored), and `full` (reuse the existing `show` rendering helper per result + a divider). Add small color /
  highlight helpers; gate color on the resolved `--color` decision (`auto` ⇒ `std::io::stdout().is_terminal()` &&
  `NO_COLOR` unset — accurate because Rust shares the process's fd 1).
- **Binding:** add `bead_search` `#[pyfunction]` in `crates/sase_core_py/src/lib.rs` returning the structured matches
  (for the Python facade / fallback path, matching the `bead_list`/`bead_show` pattern).
- **Versioning:** bump the `sase-core-rs` crate version (additive/backward-compatible; stays within sase's `<0.2.0`
  pin).
- **Tests:** Rust CLI golden tests for all three formats with `--color never` (deterministic) plus a `--color always`
  case; filter + limit + no-match cases; a `bead_search` binding test.

**Deliverable:** `bead_cli_execute(["search", …])` works end-to-end in Rust and `bead_search` is exposed. **Depends
on:** Phase 1.

### Phase 3 — Python: CLI surface, fallback handler, facade (sase)

After `just rust-install` picks up Phases 1–2:

- **`src/sase/main/parser_bead.py`:** register the `search` subparser. Excellent, scannable `-h` text; options listed
  alphabetically; every new public long option gets a short alias (`-f`, `-n`, `-c`); scope filters mirror `list`
  exactly. (Note: `list --tier` has no short alias today; `search` mirrors that for cross-command consistency — calling
  out the `cli_rules` short-alias guidance as a deliberate, documented exception rather than diverging the two
  commands.)
- **`src/sase/main/entry.py`:** add `"search"` to `_BEAD_HANDLERS`.
- **`src/sase/bead/cli_query.py`:** `handle_bead_search` fallback handler. Functional (not necessarily byte-identical)
  parity with Rust, consistent with how the existing `list`/`show`/`ready` Python fallbacks work; reuse the existing
  Python `show` rendering for `full`.
- **`src/sase/core/bead_read_facade.py` + `bead_wire.py` + `src/sase/bead/project.py`:** a `search(...)` facade calling
  the `bead_search` binding, a wire converter for `BeadSearchMatch`, and `BeadProject.search(...)`.
- **Tests:** `parse_args` coverage for the new flags; fallback-handler output for each format; a Rust-vs-Python data
  parity test (like `test_read_facade_matches_bead_project_queries`); a fast-path test confirming `search` routes
  through Rust while `-h` defers to argparse.

**Deliverable:** `sase bead search` fully works via the fast path with a working Python fallback. **Depends on:** Phases
1–2.

### Phase 4 — Docs, generated skills, contract sync, verification (sase)

- Document `search` in the skill source `src/sase/xprompts/skills/sase_beads.md` (new `### search` section with examples
  for each format), then regenerate: `sase skill init --force` + `chezmoi apply` (skill `SKILL.md` files are generated,
  never hand-edited).
- Update any CLI help golden tests, user docs / changelog, and confirm the `sase-core-rs` version pin admits the new
  binding.
- Add/refresh a CLI-vs-skill contract test so documented `search` examples stay valid.
- Run `just check` (Python) and `just rust-check` (Rust) green.

**Deliverable:** shipped, documented, contract-tested. **Depends on:** Phase 3.

## Risks & mitigations

- **Two renderers drifting** (Rust primary vs. Python fallback): mitigated by reusing the existing `show` renderer for
  `full` on both sides and by the parity test; the Python fallback is intentionally lean and documented as
  functional-parity-only (the same posture the codebase already takes for `list`/`show`/`ready`).
- **Color in captured output**: Rust renders to a string that Python prints; `auto` TTY detection is accurate because it
  is the same process fd 1, and `--color never/always` is the deterministic escape hatch used by tests.
- **Cross-repo release coordination**: the new binding is additive; local dev uses the editable build, and the version
  pin check in Phase 4 guards the published-wheel path.
- **Performance**: bead stores are small; a linear scan with substring matching is more than adequate — no index needed.

## Validation

- Rust: `just rust-test` (engine unit tests + CLI golden tests + binding test) and `just rust-check`.
- Python: `just check` (parser, fallback handler, parity, fast-path routing tests).
- Manual smoke across a seeded store: `search <term>` (compact), `--format json | jq`, `--format full`, a closed-bead
  match, `--status`/`--type`/`--tier` scoping, `--limit`, `--color never|always`, a no-match query, and an empty-query
  usage error.

## Phase summary

| Phase | Repo      | Scope                                                                          | Depends on |
| ----- | --------- | ------------------------------------------------------------------------------ | ---------- |
| 1     | sase-core | Search engine + match result type + unit tests                                 | —          |
| 2     | sase-core | `search` CLI dispatch, 3 renderers, color, `bead_search` binding, golden tests | 1          |
| 3     | sase      | argparse parser, `_BEAD_HANDLERS`, fallback handler, facade, Python tests      | 1, 2       |
| 4     | sase      | Skill docs + regen, contract sync, `just check` / `just rust-check`            | 3          |
