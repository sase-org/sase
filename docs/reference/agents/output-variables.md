---
title: Agent output variables
description: Publish and consume typed values from agent runs.
---

# Agent output variables

## `sase var`

`sase var` inspects and publishes SASE agent output variables. Agents publish values
with `sase var set`, which merges named JSON-shaped values into the current run's
`agent_meta.json["output_variables"]`. `sase artifact create` also publishes the
SASE-managed `artifacts` list there. The stored values appear in sase's TUI Agents-tab
`OUTPUT VARIABLES` metadata panel, Telegram agent-completion messages, indexed agent
history, and downstream `%wait` prompt contexts. Later agents that wait on a producer
load that producer's stored values when they start and can render them through the
`agents` Jinja dictionary in prompts and macro workflows.

With no subcommand, `sase var` prints a delegation notice and runs `sase var list`.

## Command forms

| Form                                 | Purpose                                                            |
| ------------------------------------ | ------------------------------------------------------------------ |
| `sase var get`                       | Read the current agent's live snapshot.                            |
| `sase var get '<AGENT_NAME>'`        | Read the newest exact-name historical snapshot.                    |
| `sase var get SELECTOR [...]`        | Resolve values with exact, wildcard, hood, or JSON-path selectors. |
| `sase var list`                      | Discover keys and typed values across indexed history.             |
| `sase var set KEY=VALUE [...]`       | Store strings, splitting each assignment at its first `=`.         |
| `sase var set KEY --value TEXT`      | Store one string verbatim, including whitespace.                   |
| `sase var set KEY --value-file PATH` | Read one string from a UTF-8 file or standard input.               |

The generated [CLI reference](../cli/var.md) owns flags and exact option spellings.
Snapshot reads accept `--format pretty` or `json`; selectors also accept `raw` and
`jsonl`; list output accepts `pretty`, `json`, or `jsonl`.

<a id="cli-options-35"></a> Moved to [sase var](output-variables.md#sase-var).

<a id="command-behavior-22"></a> Moved to
[Agent output variables](output-variables.md#command-behavior-22).

## Command behavior {#command-behavior-22}

`sase var get` has three modes. With no target, it reads the current agent's artifact
directory directly so recent writes are visible before the agent completes; this form
requires `SASE_ARTIFACTS_DIR`. With exactly one quoted `<AGENT_NAME>`, it searches
indexed history and returns the newest exact-name artifact. Quote the wrappers so the
shell keeps them intact, for example `sase var get '<build>' --format json`. Use
`--project PROJECT` to disambiguate repeated names across projects, where `PROJECT` may
be a display name or alias and may be repeated. `--hidden` includes hidden indexed
agents. An agent with no variables is an empty success; an unknown name is an error.
`--format pretty` renders the same readable block form used in sase's TUI, while
`--format json` emits the variable map as compact machine-readable JSON. Snapshot mode
rejects selector-only `--format raw` / `jsonl` and an explicit `--limit`.

`sase var list` is historical discovery. It groups indexed output variables by key,
orders keys by most-recent occurrence, and shows each key's distinct typed values plus
the contributing agent names. Repeated filters in one dimension are ORed; different
dimensions are ANDed. Major filters are:

- `--agent GLOB` / `-a`: filter by agent-name glob. `hood.*` includes the hood root.
- `--key GLOB` / `-k`: filter by case-sensitive variable-key glob.
- `--project PROJECT` / `-p`: filter by project display name or alias; repeatable.
- `--hidden` / `-H`: include hidden indexed agents; visible history is the default.
- `--since DATE` / `-s` and `--until DATE` / `-u`: filter by launch time using the same
  date grammar as bead history filters.
- `--value TEXT` / `-v`: case-insensitive substring match over scalar text and canonical
  JSON.
- `--value-json JSON` / `-V`: exact typed JSON value match after output-variable
  normalization. It is mutually exclusive with `--value`.
- `--limit KEYS[:VALUES]` / `-n`: cap returned keys and distinct values per key. The
  default is `20:5`; `0` means unlimited for that dimension; a single number changes
  only the key limit.
- `--reverse` / `-r`: invert the normal recent-first key and value order.

`sase var list --format pretty` prints readable grouped blocks. `--format json` emits a
stable envelope with `schema_version`, the normalized query, limit metadata, and grouped
values. `--format jsonl` emits one compact JSON object per returned distinct value.

With one or more ordinary targets, `sase var get` retrieves exact values from indexed
history with selectors:

```text
[SCOPE.]KEY[PATH ...]
```

`KEY` is a variable name or `*`. `SCOPE` may be an exact agent name, `*` for every
agent, or `HOOD.*` for a hood. Unscoped keys choose the newest matching occurrence.
Exact-agent selectors choose that name's newest artifact. Global and hood wildcard
selectors collapse repeated runs to the newest value per agent name. JSON paths follow
the selected value with `[INDEX]` for lists or `["KEY"]` for map keys; dotted map
traversal is not accepted. `sase var get build.*` remains selector mode and is distinct
from snapshot-mode `sase var get '<build>'`.

Examples:

```bash
sase var get
sase var get --format json
sase var get '<build>' --format json
sase var get status
sase var get build.status --format raw
sase var get '*.status' --format json
sase var get 'research.*.report["summary"]'
sase var get results[0]
```

Selector `--format pretty` prints each match with attribution. `--format raw` prints one
value only and fails unless the selector resolves to exactly one untruncated match;
strings print as text, and structured values print as compact JSON. `--format json`
emits a stable envelope with `schema_version`, query, limit metadata, and matches.
`--format jsonl` emits one compact JSON object per match. Wildcard expansion defaults to
20 matches; `--limit 0` is unlimited. `--project` is repeatable, and `--hidden` includes
hidden indexed agents. `--limit` applies only to selector wildcard expansion.

`sase var set` is the mutation command. It is agent-scoped and requires `SASE_AGENT=1`
and `SASE_ARTIFACTS_DIR`. Successful writes print the current agent name when known, the
stored keys, and the artifact directory.

Keys must be valid Jinja attribute identifiers (`[A-Za-z_][A-Za-z0-9_]*`). Values may
contain spaces, blank lines, newlines, and additional equals signs. The `KEY=VALUE` form
splits only on the first `=` and preserves everything after it; quote the whole
assignment when the shell would otherwise split it. `--value` likewise preserves exactly
the text supplied by the shell, including any trailing newlines. `--value-file` reads a
file or stdin and removes at most one trailing newline after normalizing line endings,
which makes files, pipes, and heredocs convenient without discarding an intentional
trailing blank line. With `--json`, JSON whitespace is ignored by the decoder and no
trailing newline is removed before parsing:

```bash
sase var set 'suites=["unit","integration"]' --json
sase var set cfg --json --value '{"retries":3,"enabled":true}'
sase var set report --json --value-file report.json
sase var set findings --json --value-file - <<'JSON'
[{"file":"src/a.py","severity":"high"}]
JSON
```

A value may be any JSON string, number, boolean, null, list, or map. Nested map keys may
be any non-empty NUL-free string. Map keys are normalized into sorted order for
deterministic storage and display; list order is always preserved. Structured values
reach Jinja as real containers, so consumers can use attribute/subscript access and
loops. Rendering an entire container with `{{ agents["build"].cfg }}` yields compact
JSON, while `| tojson` remains available for explicit JSON formatting.

An agent may store at most 256 variables. Each string leaf and nested map key is limited
to 8,192 UTF-8 bytes; each variable is limited to depth 8, 1,024 total
container-plus-leaf nodes, and 65,536 compact encoded JSON bytes. Numbers must be finite
and integers must fit the signed 64-bit range. Every string converts CRLF and lone CR
line endings to LF and rejects NUL characters. Invalid or oversized values fail visibly
instead of disappearing during publication.

Multiple calls merge into the same variable map; later writes for the same key replace
earlier values. The command does not update prompts that have already started rendering,
so write variables before the producing agent completes and before dependent agents
unblock. Downstream prompts read each producer's variables from the single `agents`
dictionary keyed by the producer's stable agent name, e.g.
`{{ agents["build"].report_path }}` (or `{{ agents.build.report_path }}` for
identifier-safe names). Do not store secrets; output variables are persisted in
`agent_meta.json` and shown in sase's TUI and Telegram completion messages.

`STOP` is a reserved output variable. `sase var set` stays generic and stores it like
any other key, but repeat orchestration interprets it: setting `STOP` (e.g.
`sase var set STOP=1`) inside a `%repeat` / `%r` iteration stops the remaining repeat
slots, which finalize as successful skipped slots. `null`, `false`, numeric zero, empty
strings, empty lists, and empty maps are not-stop; string values `0`, `false`, `no`, and
`off` are also not-stop case-insensitively after trimming. Any other value stops the
chain. `STOP` affects only repeat-chain continuation; ordinary `%wait` consumers read it
as a normal variable. See
[Repeat Directive](../macros/directive-composition.md#repeat-directive) in the macro
reference for the full cascade semantics.
