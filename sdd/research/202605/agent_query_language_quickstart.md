# Agent Query Language Quickstart

Research date: 2026-05-12 (revised)

## Question

How does the new agent query language work, especially after the `sase-37` agent archive epic, and what should a new
user understand first?

Short answer: SASE has one agent query grammar with two scopes. Live-agent queries filter hydrated rows in the ACE
Agents tab. Archive queries reuse the same parser but plan against the dismissed-agent SQLite/FTS index, so historical
agents can be searched, counted, previewed, revived, purged, scrubbed, or exported without loading every archived
bundle. The parser/tokenizer is shared; differences are entirely in what each scope knows how to evaluate.

## Mental Model

It is a small boolean filter language:

```text
status:failed project:sase
status:failed AND project:sase
status:failed OR needs:input
NOT (status:done OR hidden:true)
text:"database migration" model:gpt
age>=2h
```

Adjacent terms mean `AND`, so `status:failed project:sase` is the same as `status:failed AND project:sase`.

Operator precedence (tightest to loosest):

1. `NOT` / `!` — fully interchangeable.
2. `AND` / juxtaposition.
3. `OR`.

Parentheses override precedence. `AND` / `OR` / `NOT` are case-insensitive keywords. `&&` and `||` are **not**
supported — use the word forms.

## Strings

Bare words and quoted strings perform case-insensitive substring matching against agent metadata plus, when a content
cache is available (the live TUI), cached prompt/reply text:

```text
login
"database migration"
```

Use quoted strings when the value contains spaces or punctuation. `c"..."` is a case-sensitive variant; it searches
metadata fields only because the live content cache stores lowercased text:

```text
c"FAILED"
```

Escapes inside quoted strings: `\\`, `\"`, `\n`, `\r`, `\t`. Any other `\X` is a tokenizer error.

There is no regex. Bare strings are substring matches. `text:` is a substring match on live agents and a combined
metadata-LIKE + FTS5 phrase match on archive queries.

## Property Values and Bare Words

Bare words (left-hand strings, AND/OR/NOT keywords) accept `[A-Za-z0-9_-]` and must start with a letter or `_`.
Property values (after `:`) additionally accept `.`, which is why dotted values parse unquoted:

```text
tag:sase-42.3
project:sase.core
```

Anything outside that set must be quoted.

## Comparators

Comparison operators are `<`, `<=`, `>`, `>=`, `=`, and `:`. They are only valid immediately after a comparable key —
a free-floating `>5` is a tokenizer error.

`:` is sugar but the meaning depends on the key:

- **Duration keys** (`age`): `:` is sugar for `>=`. `age:2h` ≡ `age>=2h` ("at least 2 hours old").
- **Numeric keys** (`step_index`, `retry_attempt`, `cost`, `cost_usd_micros`, `input_tokens`, `output_tokens`,
  `tokens`): `:` is sugar for `=`. `step_index:3` ≡ `step_index=3` (exact equality).

For substring/enum/bool keys, `:` is the normal `key:value` separator and has no comparator meaning.

## Durations

Duration literals are `<int><unit>` where unit is `s`, `m`, `h`, or `d`. Whole-unit, single-token only — fractional
(`1.5h`) and composite (`1h30m`, `5d2h`) literals raise:

```text
Composite durations (e.g. 1h30m) are not supported; use 'age>=1h AND age<90m'
```

Express compound durations as a conjunction:

```text
age>=1h AND age<90m
```

Live agents without a `start_time` always fail `age` comparisons (the predicate returns false).

## Live-Agent Keys

These keys are useful in the ACE Agents tab query box. All substring matches are case-insensitive.

| Key | Meaning | Notes |
| --- | --- | --- |
| `status:VAL` | Substring on `agent.status` | |
| `cl:VAL` | Substring on CL / changespec name | |
| `project:VAL` | Substring on project basename | Uses the parent directory of `project_file` |
| `name:VAL` | Substring on `agent_name`, falling back to `display_name` | |
| `model:VAL` | Substring on `model` | |
| `provider:VAL` | Substring on `llm_provider` | |
| `runtime:VAL` | Aliased to `llm_provider` on live rows | Archive uses a separate `runtime` column |
| `type:VAL` | Enum: `workflow`, `run`, `running` (run/running both mean RUNNING) | |
| `source:VAL` | Enum: `axe`, `manual` | |
| `needs:input` | Status is in the needs-input bucket | Only value accepted is `input` |
| `attention:true|false` | Status is in the stopped/needs-attention bucket | Boolean |
| `pinned:true|false` | Pinned flag | Boolean |
| `hidden:true|false` | Hidden flag | Boolean |
| `tag:VAL` | Exact tag match, case-insensitive | |
| `tag:` | Any tagged agent (non-empty value form) | The only key with an empty-value form |
| `text:VAL` | Same metadata + content haystack as bare strings | |
| `step_type:VAL` | Substring on workflow step type | |
| `retry_of:VAL` | Substring on retry parent timestamp | |
| `parent:VAL` | Substring on parent agent timestamp | |
| `error:VAL` | Substring on `error_message` | |
| `age<op><dur>` | `now - start_time` vs duration; `s/m/h/d`; `age:2h` ≡ `age>=2h` | False when `start_time` is missing |
| `step_index<op><int>` | Workflow step index comparison | `:` means `=` |
| `retry_attempt<op><int>` | Retry attempt comparison | `:` means `=` |

Caveats for the live scope:

- `revived:true|false` parses (it is a valid bool key tokenizer-side) but the live evaluator does not implement it, so
  it currently filters everything out. Treat it as archive-only in practice.
- `cost`, `cost_usd_micros`, `input_tokens`, `output_tokens`, and `tokens` likewise parse but the live evaluator only
  implements `step_index` and `retry_attempt`. Other numeric keys silently return false on live rows. Use them in
  archive queries.

Enum keys reject unknown values at tokenize time with the allowed set in the error message. Boolean keys reject
anything other than `true`/`false`.

## Archive Keys

Archive queries are used by the revive modal and by these CLI commands (all share the same planner):

```bash
sase agents archive search 'status:failed project:sase'
sase agents archive stats --query 'runtime:codex' --by status,runtime
sase agents archive show --suffix 20260512120000
sase agents archive revive --query 'name:my_agent'
sase agents archive purge --query 'status:failed' --dry-run
sase agents archive scrub --query 'project:sase'
sase agents archive export --query 'model:gpt' --out archive.tar.gz
```

Archive-supported keys:

| Key | Archive behavior |
| --- | --- |
| `status:VAL` | `LIKE %val%` on `s.status` |
| `cl:VAL` | LIKE on `cl_name` OR `meta_changespec` |
| `project:VAL` | LIKE on `project_name` OR `project_file` |
| `name:VAL` | LIKE on `agent_name`, `cl_name`, OR `workflow` |
| `model:VAL` | LIKE on `model` |
| `provider:VAL` | LIKE on `llm_provider` |
| `runtime:VAL` | LIKE on the dedicated `runtime` column |
| `type:VAL` | Exact match (`running` is normalized to `run`) |
| `source:axe` | `workflow IS NOT NULL OR step_type IS NOT NULL` |
| `source:manual` | `workflow IS NULL AND step_type IS NULL` |
| `text:VAL` | Metadata LIKE on key string columns OR FTS5 phrase match on the search projection |
| `archived_before:DATE` | `dismissed_at < ?` |
| `archived_after:DATE` | `dismissed_at >= ?` |
| `revived:true` | `revived_at IS NOT NULL` |
| `revived:false` | `revived_at IS NULL` |
| `step_type:VAL` | LIKE on `step_type` |
| `step_index<op><int>` | Numeric on `step_index` |
| `retry_attempt<op><int>` | Numeric on `retry_attempt` |
| `retry_of:VAL` | LIKE on `retry_of_timestamp` |
| `parent:VAL` | LIKE on `parent_timestamp` |
| `error:true` / `error:false` | `error_message_excerpt IS [NOT] NULL` |
| `error:VAL` | LIKE on `error_message_excerpt` (any value other than `true`/`false`) |
| `cost<op><int>` | Numeric on `cost_usd_micros` |
| `cost_usd_micros<op><int>` | Same column as `cost` |
| `input_tokens<op><int>` | Numeric on `input_tokens` |
| `output_tokens<op><int>` | Numeric on `output_tokens` |
| `tokens<op><int>` | Numeric on `COALESCE(input_tokens,0) + COALESCE(output_tokens,0)` |

Archive rejects these live-only keys with `ArchiveQueryError`:

```text
hidden:true
attention:true
needs:input
pinned:true
tag:foo
```

Archive also rejects `age` comparisons:

```text
Archive queries do not support age comparisons; use archived_before: or archived_after: instead
```

### Date format for `archived_before` / `archived_after`

The value is passed straight through to SQLite as a parameter compared to the `dismissed_at` column with `<` or `>=`.
The parser does not validate the format. To get reliable lexicographic comparison against the stored ISO timestamps,
use ISO 8601 strings:

```text
archived_before:2026-05-01
archived_after:2026-05-01T00:00:00
```

Dates are treated as opaque strings, so timezone behavior matches whatever was written into `dismissed_at` (UTC ISO
timestamps in the standard archive pipeline).

### FTS behavior

`text:VAL` and bare strings on archive queries compile to `(metadata LIKE %val% OR FTS phrase match)`. The FTS side
uses SQLite FTS5 with the value wrapped as a quoted phrase, so it matches contiguous tokens, not prefixes. The
`archive_search_text` projection (built by `archive_search_text.py`) is the only field indexed by FTS — it is a
bounded, scrubbed projection of prompt/reply/chat content. Quotes inside the value are escaped by doubling (`"` →
`""`).

## Empty Queries

The two scopes disagree on empty input:

- **Live**: the parser raises `AgentQueryParseError("Empty query", 0)` on empty/whitespace input. The TUI input box
  treats an empty filter as "show everything" before ever calling the parser, so most users never see this.
- **Archive**: an empty/whitespace query compiles to `WHERE 1 = 1`, matching all rows. CLI commands like
  `sase agents archive search ''` therefore return everything.

## Errors and Where Users See Them

- **Tokenizer errors** carry a position and message — for example
  `Unknown property key: foo (valid keys: age, archived_after, ...)` or
  `pinned: only accepts true/false (got 'yes')`.
- **Parser errors** report `Unexpected token: <value>` or `Expected RPAREN, got EOF`.
- **Archive planner errors** (`ArchiveQueryError`) surface live-only key rejections, `age`-on-archive, and SQL errors.

Surfaces:

- The revive modal shows the latest error in its hints footer and keeps the last valid result set visible, so you can
  fix the query without losing context.
- The Agents tab live filter rejects bad queries by leaving the previous result set up and showing the parser error.
- CLI commands print the exception message and exit non-zero.

## Syntax Highlighting

`sase.ace.agent_query.highlighting` exposes `tokenize_agent_query_for_display()` and an `AGENT_QUERY_TOKEN_STYLES` Rich
style table. The TUI uses it to colour live-tab and revive-modal filter inputs (keys, comparators, values, booleans,
durations, parens, and AND/OR/NOT each get their own style). The highlighter is tolerant of partial input, so it keeps
working while you type.

## What Changed With `sase-37`

The `sase-37` epic turned dismissed agents from an in-memory/free-text revive list into an indexed archive query
surface:

- Revive no longer consumes archive bundles. It marks bundles with `revived_at` / `times_revived` while preserving
  them.
- Bundles now carry versioned archive metadata and a bounded, scrubbed `archive_search_text` projection.
- The archive index stores query-facing summary columns such as `agent_id`, `runtime`, token counts, costs, error
  excerpts, dismissal/revival timestamps, parent/retry fields, and workflow step fields.
- `text:` and bare archive strings can use the FTS projection rather than hydrating every JSON bundle.
- The revive modal accepts structured archive queries, pages results, keeps the last valid result set on parse errors,
  and hydrates the highlighted bundle lazily for preview.
- The CLI exposes search/show/stats/revive/purge/scrub/export around the same planner.
- A Rust archive facade can execute the SQL-backed query/facet/revive operations, with Python remaining the UI/CLI
  adapter.

## New User Cheat Sheet

Live (Agents tab):

```text
status:failed
project:sase status:failed
needs:input OR attention:true
source:axe type:workflow
name:planner text:"index schema"
model:gpt age>=2h
NOT (status:done OR hidden:true)
error:timeout retry_attempt>=1
```

Archive (revive modal or `sase agents archive ...`):

```text
status:failed archived_after:2026-05-01
runtime:codex revived:false
text:"searchable phrase"
step_type:bash retry_attempt>=1 error:true
tokens>1000 project:sase
cost>5000 model:opus
```

Common mistakes:

- Do not use ChangeSpec query shorthand here. Agent queries do not support `%d`, `+project`, `^ancestor`, `~sibling`,
  `&name`, `@@@`, `$$$`, or `*`.
- `!` means `NOT`, not "error suffix".
- `&&` and `||` are not aliases for `AND`/`OR`.
- Do not use `age`, `hidden`, `attention`, `needs`, `pinned`, or `tag` in archive queries — they all raise.
- Do not use `cost`/`tokens`/`cost_usd_micros` on live agents — they parse but never match.
- `revived:` works in archive queries; on live agents it currently filters everything out.
- `archive_before:` is not a key — use `archived_before:` / `archived_after:` (past tense).
- `c"..."` is case-sensitive but searches metadata only (it cannot reach cached prompt/reply content).

## Source Pointers

- Epic context: `sdd/epics/202605/agent_archive_query.md`
- Tokenizer (key allowlist, comparators, durations, escapes): `src/sase/ace/agent_query/tokenizer.py`
- Parser/grammar: `src/sase/ace/agent_query/parser.py`
- AST types: `src/sase/ace/agent_query/types.py`
- Live evaluator (which keys actually match on live rows): `src/sase/ace/agent_query/evaluator.py`
- Archive planner (SQL/FTS compilation, live-only rejection, date passthrough):
  `src/sase/ace/agent_query/archive_planner.py`
- Display-time syntax highlighting: `src/sase/ace/agent_query/highlighting.py`
- Archive CLI surface: `src/sase/agents/cli_archive.py`, `src/sase/main/parser_agents.py`
- Revive modal query flow: `src/sase/ace/tui/modals/revive_agent_modal.py`
- Archive search projection: `src/sase/ace/archive_search_text.py`
- Rust archive facade wire: `src/sase/core/agent_archive_wire.py`
- Key tests: `tests/test_agent_query_tokenizer.py`, `tests/test_agent_query_parser.py`,
  `tests/test_agent_query_evaluator.py`, `tests/test_agent_query_archive_planner.py`,
  `tests/test_agents_archive_cli.py`
