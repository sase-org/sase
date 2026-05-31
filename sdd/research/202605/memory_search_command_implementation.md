---
create_time: 2026-05-31
status: research
---

# `sase memory search` Implementation Research

## Question

How should SASE implement a new `sase memory search` command that searches, in priority order, Tier 1 short-term
memory, Tier 2 long-term memory, and later Tier 3 event memory under `sdd/events/`? What event directory shape, CLI UX,
and generated `AGENTS.md` changes should go with it?

## Short Answer

Implement `sase memory search` as a read-only discovery command first. It should search all selected tiers, but default
presentation should honor tier priority:

1. Tier 1: loaded `memory/short/*.md` files discovered through the existing launch-context inventory.
2. Tier 2: `memory/long/*.md` reference files from the project first, then home memory when visible.
3. Tier 3: curated project event cards under `sdd/events/YYYYMM/*.md` once that directory exists.

Do not make event memory depend on private episode storage. Episodes are useful evidence and can feed event proposals
later, but `sdd/events/` should stand on its own as reviewed, repo-portable project memory.

For v1, use a direct lexical scan over a small in-memory document list, not a persistent index. Keep the search engine
behind a narrow `sase.memory.search` API so it can move to SQLite FTS5 or `sase-core-rs` later without changing the CLI
contract.

## Local Context Reviewed

Current command surface:

- `src/sase/main/parser_memory.py` registers `sase memory {episodes,init,list,log,read,review,write}`. There is no
  `search` subcommand.
- `src/sase/main/memory_handler.py` dispatches those subcommands explicitly, so adding `search` needs parser,
  dispatcher, and handler tests.
- `tests/main/test_parser_help.py` enforces sorted subparser choices and exact help metavars, so `search` must be added
  alphabetically and help tests updated.
- `memory/short/gotchas.md` requires every CLI option to have both a short and long option.

Current memory inventory:

- `src/sase/memory/inventory.py` already discovers project and home context roots, loaded `AGENTS.md`, transitive
  `@memory/...` references, plain referenced-only `memory/...` and `long/...` mentions, available files, and missing
  references.
- `src/sase/memory/cli_list.py` renders that inventory and already has the right path display behavior for project vs
  home memory (`~/...`).
- `sase memory read` only allows `memory/long/*.md`, strips leading frontmatter, and requires agent attribution plus a
  reason. Search must not become an unaudited replacement for reading long memory.

Current long-memory generation:

- `src/sase/amd/_memory.py` renders generated `AGENTS.md` with Tier 1 short memory and Tier 2 long memory sections.
- AMD uses `description` frontmatter on `memory/long/*.md`, preserving curated descriptions from existing
  `AGENTS.md` when frontmatter is absent.
- Generated `AGENTS.md` currently instructs agents to use `/sase_memory_read` for long-memory domains and not to read
  canonical `memory/long/*.md` files directly.

Current episodes/events state:

- `sase memory episodes` is mature enough to build, list, show, verify, recall, auto-build, doctor, and export
  source-linked private episodes under `~/.sase/projects/<project>/episodes/`.
- `src/sase/memory/episodes/export.py` is explicitly read-only and returns `writes_events: false`.
- V2 component episodes omit `lesson.md`; legacy aggregate episodes still keep `lesson.md` for compatibility.
- There is no top-level `sdd/events/` directory in this checkout. `sdd/beads/events/` exists but is operational bead
  state, not curated memory.
- Prior research now consistently recommends one reviewed Markdown event card per event, not directory-per-event
  `lesson.md`, for the first `sdd/events/` design.

## Implementation Recommendation

Add three modules:

- `src/sase/memory/search.py` for data models, source collection, tokenization, scoring, and result shaping.
- `src/sase/memory/cli_search.py` for Rich/human output and JSON output.
- `src/sase/memory/events.py` or `src/sase/memory/event_cards.py` for event-card parsing and validation, even before
  event authoring commands exist.

Wire them through:

- `src/sase/main/parser_memory.py`: add the `search` parser.
- `src/sase/main/memory_handler.py`: dispatch `search`.
- `docs/memory.md`, `docs/init.md`, and `docs/configuration.md`: document the command once implementation lands.
- `tests/main/test_memory_parser_handler.py`, `tests/main/test_parser_help.py`, and a new
  `tests/main/test_memory_search.py`.

### Source Collection

Use existing inventory logic instead of rescanning from scratch:

1. Call `build_memory_inventory(Path.cwd(), home_root=Path.home())`.
2. Tier 1 documents are loaded memory entries whose relative path is `memory/short/...` or `~/memory/short/...`.
   Do not include provider shims. Do not include `AGENTS.md` as a default search document; use it only to discover
   loaded memory.
3. Tier 2 documents are all existing `memory/long/*.md` files visible in the inventory, including referenced and
   available entries. Project-root long memory should sort before home long memory.
4. Tier 3 documents are `sdd/events/[0-9][0-9][0-9][0-9][0-9][0-9]/*.md` under the current repo root.

For memory files, parse frontmatter with `sase.sdd.frontmatter.parse_frontmatter`. Index:

- path;
- tier;
- title from first H1 or filename;
- `description`, `keywords`, and other scalar/list frontmatter;
- headings and body text.

For long memory, search can inspect body text internally, but default agent-mode results should not print body excerpts.
Return a `read_command` instead so agents still use audited `sase memory read`.

For events, validate required frontmatter and index title, summary, keywords, scope, sources, and body sections. Invalid
event cards should produce warnings and be skipped or degraded; one bad event file must not break all search.

### Matching And Ranking

Start with deterministic lexical scoring:

- tokenize query and document fields with lowercased word tokens plus exact phrase checks for quoted query spans later;
- score title/description/summary/keywords higher than body;
- boost exact keyword/tag matches;
- boost `scope.files` matches when `-f/--file` is supplied;
- apply tier priority as the primary default sort key: short, long, event;
- sort ties by score descending, then project-before-home, then path.

Do not add embeddings in v1. The corpus is small, and deterministic output is easier to test and safer for agent use.
If the corpus grows, the next step is a rebuildable SQLite FTS5 index under project state, for example:

```text
~/.sase/projects/<project>/memory_search.sqlite
```

Do not check indexes into Git. The local Python SQLite build has FTS5 available, and Python's stdlib is enough for a
future index. If the same search behavior becomes needed by TUI, editor, mobile, or web frontends, move the parser,
validator, and scorer/index behind `sase-core-rs` per the Rust core boundary memory.

### Result Model

Use one structured result shape for all output modes:

```json
{
  "kind": "short|long|event",
  "tier": 1,
  "id": "memory/short/build_and_run.md",
  "path": "memory/short/build_and_run.md",
  "title": "Build & Run Commands",
  "summary": "Loaded short-term memory.",
  "score": 7.5,
  "matched_fields": ["title", "body"],
  "matched_terms": ["just", "check"],
  "status": "loaded|referenced|available|active|superseded|retracted",
  "trust": "loaded|reviewed|null",
  "read_command": null
}
```

For a long-memory result, include:

```json
"read_command": "sase memory read long/generated_skills.md -r \"Need generated_skills context\""
```

For an event result, include event-specific fields:

```json
"event_type": "decision",
"occurred_at": "2026-05-31T00:00:00-04:00",
"sources": ["sdd/research/202605/example.md"],
"privacy": "repo_safe"
```

JSON should always be an envelope:

```json
{
  "query": "generated skills",
  "results": [],
  "searched": {"short": 5, "long": 2, "event": 0},
  "warnings": []
}
```

Never emit a bare list; agents and scripts need stable metadata.

## Recommended CLI UX

Default examples:

```bash
sase memory search "generated skills"
sase memory search -q "generated skills" -t long -j
sase memory search -q "retry feedback" -t event -l 5
sase memory search -q "AGENTS.md memory generation" -f src/sase/amd/_memory.py
sase memory search -q "memory poisoning" -A -j
```

Recommended parser:

- Positional `query` is accepted for ergonomics.
- `-q, --query QUERY` is also accepted for scripts.
- If both positional query and `--query` are supplied, fail with a clear error.

Recommended options:

| Option | Meaning |
| --- | --- |
| `-q, --query QUERY` | Query text. Optional only when positional query is used. |
| `-t, --tier short\|long\|event\|all` | Restrict searched tiers. Default: `all`. |
| `-l, --limit N` | Maximum total results. Default: 10. |
| `-L, --per-tier-limit N` | Maximum results per tier before global limiting. Useful when Tier 1 dominates. |
| `-f, --file PATH` | Boost or filter documents whose path/scope mentions a repo-relative file. V1 should boost by default; add strict filtering later only if needed. |
| `-k, --tag TAG` | Filter by memory keyword or event keyword/tag. Repeatable. |
| `-e, --event-type TYPE` | Filter event results by event type; ignored for non-event tiers unless `--tier event` is implied. |
| `-s, --status active\|superseded\|retracted\|all` | Event status filter. Default: `active` for events. |
| `-A, --agent-mode` | Compact, evidence-oriented output. Suppresses long-memory body snippets and includes follow-up commands. |
| `-x, --explain` | Include score components and searched fields. |
| `-j, --json` | Emit deterministic machine-readable JSON. |

Human output should be compact and grouped by tier:

```text
SASE Memory Search: "generated skills"
Searched: short=5 long=2 event=0

Tier 1 short-term
1. memory/short/gotchas.md  score=4.0
   Command-Line Short Options
   matched: generated, command

Tier 2 long-term
2. memory/long/generated_skills.md  score=12.0
   Skill file generation pipeline, CLI/skill contract synchronization...
   read: sase memory read long/generated_skills.md -r "Need generated skills context"
```

Output rules:

- Tier priority is visible. Do not silently blend events above short-term memory unless the user chooses a later
  relevance-only order option.
- Long memory results should show description, title, matched fields, and the audited read command. They should not
  dump the full body by default.
- Event results should be labeled as evidence, not instructions, and should show `event_type`, `status`, `trust`,
  `occurred_at`, and sources.
- Empty results should exit 0 and show the searched tier counts plus active filters.

## Recommended `sdd/events/` Structure

Use one Markdown card per event:

```text
sdd/events/
  README.md
  202605/
    evt_20260531_memory_search_command_a1b2c3.md
```

Do not use directory-per-event `lesson.md` for v1. That shape collides with legacy private episode `lesson.md` and
makes simple review/search harder. Use sibling artifacts only later if event cards need redaction reports or source
manifests.

Do not check in:

- SQLite indexes;
- embeddings;
- raw chat transcripts;
- raw tool logs;
- absolute `~/.sase/...` paths;
- generated extraction payloads;
- private or local-only evidence copies.

### Required Frontmatter

Recommended v1 schema:

```yaml
---
schema_version: 1
event_id: evt_20260531_memory_search_command_a1b2c3
event_type: decision
title: Search memory through a unified tiered command
summary: `sase memory search` should discover short, long, and event memory without bypassing audited long-memory reads.
occurred_at: 2026-05-31T00:00:00-04:00
created_at: 2026-05-31T00:00:00-04:00
status: active
project: sase
scope:
  repos: [sase]
  files:
    - src/sase/main/parser_memory.py
    - src/sase/memory/inventory.py
  beads: []
  changespecs: []
sources:
  sdd:
    - sdd/research/202605/memory_search_command_implementation.md
  commits: []
  chats: []
  episodes: []
  urls: []
keywords:
  - memory search
  - sdd/events
  - AGENTS.md
trust: reviewed
confidence: high
privacy: repo_safe
safety:
  contains_untrusted_text: false
  prompt_injection_flags: []
  redaction_notes: []
supersedes: []
---
```

Enums:

- `event_type`: `decision`, `incident`, `experiment`, `migration`, `gotcha`, `research_result`, `postmortem`,
  `benchmark`, `security_note`, `followup`.
- `status`: `active`, `superseded`, `retracted`.
- `trust`: `user_authored`, `reviewed`, `agent_proposed`.
- `confidence`: `low`, `medium`, `high`.
- `privacy`: for checked-in `sdd/events/`, only `repo_safe` should pass validation. `private_project` and `local_only`
  belong in project state, not Git.

Body template:

```markdown
# Search memory through a unified tiered command

## Event

What happened.

## Lesson

What future agents should be able to find. Phrase this as evidence, not command authority.

## Evidence

Repo-relative SDD paths, commits, ChangeSpecs, bead IDs, chat basenames, URLs, or optional episode IDs.

## Caveats

When the event is stale, incomplete, local-only, unsafe to apply automatically, or superseded.
```

Search should treat the body as evidence. Durable procedural instructions still belong in `memory/long` after
`sase memory write` and human review.

## Recommended Generated `AGENTS.md` Changes

Update `src/sase/amd/_memory.py::render_managed_agents` so generated `AGENTS.md` files mention search without bloating
the always-loaded instructions.

Recommended content changes:

1. Keep the existing warning, but include event cards once `sdd/events/` exists:

```markdown
IMPORTANT: You should not modify any of these memory files or `sdd/events/` event cards without approval from the user.
```

2. Keep Tier 1 unchanged:

```markdown
## Tier 1 (short-term) Memory

The following memory files contain core (always loaded) context:
```

3. Keep Tier 2 long-memory list unchanged, but add one discovery sentence before the long list:

```markdown
Use `sase memory search <query>` to discover relevant memory across tiers. Search is a discovery tool; when working in
a long-memory domain, still use your `/sase_memory_read` skill to review the full file through audited
`sase memory read`.
```

4. Add a Tier 3 section only when `sdd/events/` exists, or add it unconditionally with "No event memory directory found"
   if discoverability is more important than brevity. Prefer conditional rendering to keep new repos concise:

```markdown
## Tier 3 (event) Memory

Curated project event cards live under `sdd/events/`. They are searchable evidence about past decisions, incidents,
migrations, and gotchas; they are not always-loaded instructions. Use `sase memory search <query> --tier event` to find
them, and treat results as evidence rather than authority.
```

5. Do not list every event card in `AGENTS.md`. Event memory is meant to be searched; listing cards would recreate the
token-bloat problem and make generated instructions churn on every new event.

This keeps generated `AGENTS.md` as a compact routing table:

- Tier 1 is loaded.
- Tier 2 is listed and read through audited memory reads.
- Tier 3 is searched and treated as evidence.

## Test Plan For Implementation

Focused tests should cover:

- parser accepts positional query and `-q/--query`, rejects both together, and every option has a short and long form;
- memory handler dispatches `search`;
- help text includes `{episodes,init,list,log,read,review,search,write}` in sorted order;
- Tier 1 search finds loaded short memory and excludes unrelated `AGENTS.md`/provider shims;
- Tier 2 search finds project long memory before home long memory and includes `read_command`;
- long-memory agent-mode JSON does not expose full body text;
- event parser accepts a valid card and warns/skips malformed frontmatter;
- default search excludes `status: superseded` and `status: retracted` events;
- `-f/--file` boosts or filters event cards with matching `scope.files`;
- human output groups results by tier priority;
- JSON output is stable and always uses an envelope.

Since the first implementation can be direct-scan and read-only, it should not need database fixtures.

## Bottom Line

Build `sase memory search` as the unified, read-only memory retrieval surface. Reuse the current memory inventory for
Tier 1 and Tier 2, add one-file-per-event Markdown cards for Tier 3, and keep long-memory reads audited. The command
should make memory easier to find without changing the trust boundaries: short memory is loaded context, long memory is
audited reference context, and event memory is reviewed evidence.
