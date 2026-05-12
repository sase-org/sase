# Agent Query Language Quickstart

Research date: 2026-05-12

## Question

How does the new agent query language work, especially after the `sase-37` agent archive epic, and what should a new
user understand first?

Short answer: SASE now has one agent query grammar with two scopes. Live-agent queries filter hydrated rows in the ACE
Agents tab. Archive queries reuse the same parser but plan against dismissed-agent SQLite/FTS indexes, so historical
agents can be searched, counted, previewed, revived, purged, scrubbed, or exported without loading every archived bundle.

## Mental Model

The language is a small boolean filter language:

```text
status:failed project:sase
status:failed AND project:sase
status:failed OR needs:input
NOT (status:done OR hidden:true)
text:"database migration" model:gpt
age>=2h
```

Adjacent terms mean `AND`, so `status:failed project:sase` is the same as
`status:failed AND project:sase`.

Operator precedence is:

1. `NOT` / `!`
2. `AND` / adjacent terms
3. `OR`

Parentheses override precedence.

## Strings

Bare words and quoted strings perform case-insensitive substring matching:

```text
login
"database migration"
```

Use quoted strings when the value contains spaces or punctuation. Use `c"..."` for a case-sensitive match:

```text
c"FAILED"
```

Escapes inside quoted strings: `\\`, `\"`, `\n`, `\r`, `\t`.

This language is not regex. User text is substring matching, and `text:` archive search is compiled into an FTS phrase
match.

## Live-Agent Keys

These keys are useful in the ACE Agents tab query box:

| Key | Meaning |
| --- | --- |
| `status:VAL` | Substring match on the agent status |
| `cl:VAL` | Substring match on CL / changespec name |
| `project:VAL` | Substring match on project basename |
| `name:VAL` | Substring match on agent name, falling back to display name |
| `model:VAL` | Substring match on model |
| `provider:VAL` | Substring match on LLM provider |
| `runtime:VAL` | Live rows currently alias this to provider-like runtime data |
| `type:workflow` | Workflow parent rows |
| `type:run` / `type:running` | Normal running-agent rows |
| `source:axe` | Agent came from an axe/workflow source |
| `source:manual` | Manually launched agent |
| `needs:input` | Agent is waiting for user input or approval |
| `attention:true` | Agent status is in the stopped/needs-attention bucket |
| `pinned:true` | Agent is pinned |
| `hidden:true` | Agent is hidden |
| `tag:VAL` | Exact tag match, case-insensitive |
| `tag:` | Any tagged agent |
| `text:VAL` | Search the same metadata/content haystack as bare text |
| `age>=2h` | Compare `now - start_time` using `s`, `m`, `h`, or `d` |
| `step_index:2` | Exact workflow step index |
| `retry_attempt>=1` | Retry attempt comparison |

`age:2h` is shorthand for `age>=2h`.

Boolean keys accept only `true` or `false`. Enum keys reject unknown values:

```text
pinned:true
hidden:false
type:workflow
source:manual
needs:input
```

## Archive Keys

Archive queries are used by the revive modal and by:

```bash
sase agents archive search 'status:failed project:sase'
sase agents archive stats --query 'runtime:codex' --by status,runtime
sase agents archive show --suffix 20260512120000
sase agents archive revive --query 'name:my_agent'
sase agents archive purge --query 'status:failed' --dry-run
sase agents archive scrub --query 'project:sase'
sase agents archive export --query 'model:gpt' --out archive.tar.gz
```

Archive-supported keys include most durable metadata keys plus archive-specific lifecycle fields:

| Key | Archive behavior |
| --- | --- |
| `status:VAL` | SQLite summary status substring |
| `cl:VAL` | `cl_name` or metadata changespec substring |
| `project:VAL` | `project_name` or project file substring |
| `name:VAL` | Agent name, CL name, or workflow substring |
| `model:VAL` | Model substring |
| `provider:VAL` | LLM provider substring |
| `runtime:VAL` | Runtime column substring |
| `type:workflow` / `type:run` / `type:running` | Archived agent type |
| `source:axe` / `source:manual` | Derived from workflow / step metadata |
| `text:VAL` | FTS search over archived prompt/reply/chat projection |
| `archived_before:DATE` | `dismissed_at < DATE` |
| `archived_after:DATE` | `dismissed_at >= DATE` |
| `revived:true` | Bundle has been revived at least once |
| `revived:false` | Bundle has not been revived |
| `step_type:VAL` | Workflow step type substring |
| `step_index:2` | Step index comparison |
| `retry_attempt>=1` | Retry attempt comparison |
| `retry_of:VAL` | Retry parent timestamp substring |
| `parent:VAL` | Parent timestamp substring |
| `error:true` | Has an error excerpt |
| `error:false` | No error excerpt |
| `error:timeout` | Error excerpt substring |
| `cost>1000` | Cost micros comparison |
| `input_tokens>1000` | Input token comparison |
| `output_tokens>1000` | Output token comparison |
| `tokens>1000` | Input plus output token comparison |

Archive queries intentionally reject live-only keys with a clear error:

```text
hidden:true
attention:true
needs:input
pinned:true
tag:foo
```

Archive queries also reject `age` comparisons. Use `archived_before:` or `archived_after:` instead.

## Syntax Details

Property values can be bare words or quoted strings:

```text
status:failed
text:"searchable phrase"
```

Bare property values may contain letters, digits, `_`, `-`, and `.`. That is why dotted tags and bead-like values parse:

```text
tag:sase-42.3
```

Numeric fields accept `<`, `<=`, `>`, `>=`, `=`, or `:`. For numeric fields, `:` means equality:

```text
step_index:3
tokens>=1000
```

Duration fields accept a single whole-unit literal only:

```text
age>30m
age<=2h
age>=1d
```

Composite durations are rejected:

```text
age>1h30m
```

Write that as two comparisons if needed:

```text
age>=1h AND age<90m
```

## What Changed With `sase-37`

The `sase-37` epic turned dismissed agents from an in-memory/free-text revive list into an indexed archive query surface:

- Revive no longer consumes archive bundles. It marks bundles with `revived_at` / `times_revived` while preserving them.
- Bundles now carry versioned archive metadata and a bounded, scrubbed `archive_search_text` projection.
- The archive index stores query-facing summary columns such as `agent_id`, `runtime`, token counts, costs, error
  excerpts, dismissal/revival timestamps, parent/retry fields, and workflow step fields.
- `text:` and bare archive strings can use an FTS-backed projection rather than hydrating every JSON bundle.
- The revive modal accepts structured archive queries, pages results, keeps the last valid result set on parse errors,
  and hydrates the highlighted bundle lazily for preview.
- The CLI exposes search/show/stats/revive/purge/scrub/export around the same planner.
- A Rust archive facade can execute the SQL-backed query/facet/revive operations, with Python remaining the UI/CLI
  adapter.

## New User Cheat Sheet

Start with these patterns:

```text
status:failed
project:sase status:failed
needs:input OR attention:true
source:axe type:workflow
name:planner text:"index schema"
model:gpt age>=2h
```

For historical dismissed agents:

```text
status:failed archived_after:2026-05-01
runtime:codex revived:false
text:"searchable phrase"
step_type:bash retry_attempt>=1 error:true
tokens>1000 project:sase
```

Common mistakes:

- Do not use ChangeSpec query shorthand here. Agent queries do not support `%d`, `+project`, `^ancestor`, `~sibling`,
  `&name`, `@@@`, `$$$`, or `*`.
- Do not assume `!` means an error suffix. In agent queries, `!` means `NOT`.
- Do not use `age` in archive queries.
- Do not use `hidden`, `attention`, `needs`, `pinned`, or `tag` in archive queries.
- Do not write regexes; write substrings and property filters.

## Source Pointers

- Epic context: `sdd/epics/202605/agent_archive_query.md`
- Live parser/tokenizer/types/evaluator: `src/sase/ace/agent_query/{parser,tokenizer,types,evaluator}.py`
- Archive planner: `src/sase/ace/agent_query/archive_planner.py`
- Archive CLI: `src/sase/agents/cli_archive.py` and `src/sase/main/parser_agents.py`
- Revive modal query flow: `src/sase/ace/tui/modals/revive_agent_modal.py`
- Archive search projection: `src/sase/ace/archive_search_text.py`
- Rust archive facade wire: `src/sase/core/agent_archive_wire.py`
- Key tests: `tests/test_agent_query_tokenizer.py`, `tests/test_agent_query_parser.py`,
  `tests/test_agent_query_evaluator.py`, `tests/test_agent_query_archive_planner.py`,
  `tests/test_agents_archive_cli.py`
