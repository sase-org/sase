---
create_time: 2026-04-26 03:29:58
status: done
bead_id: sase-v
prompt: sdd/prompts/202604/agents_tab_query_filters.md
---
# Agents Tab — Structured Query Filters

## Goal

Upgrade the Agents-tab filter from a case-insensitive substring search to a structured query language that parallels the
existing ChangeSpec query system at `src/sase/ace/query/`. After this work, users editing the agents-tab filter (the
`QueryEditModal` reached from the agents tab) can write queries like:

```
status:failed
status:running
needs:input
source:axe
source:manual
project:foo
cl:bar
model:opus
type:workflow
pinned:true
hidden:true
age>2h
attention:true
text:"database migration"
```

Queries combine with boolean operators (`AND`, `OR`, `NOT`, juxtaposition = AND, parentheses) just like the ChangeSpec
query language. Bare/quoted strings without a `key:` prefix continue to do a case-insensitive substring search across
the existing haystack (cl_name, display_name, agent_name, status, prompt, reply) so the current "just type a word" UX
keeps working.

## Background

- **Current filter** lives in `src/sase/ace/tui/actions/agents/_loading.py:440-472` inside `_finalize_agent_list()`. The
  predicate `_matches()` does case-insensitive substring search across metadata fields and content cached by
  `AgentContentSearchCache`. Hierarchy is preserved: a matching parent keeps its (non-matching) children visible.
- **Filter editor** is the generic `QueryEditModal` at `src/sase/ace/tui/modals/query_edit_modal.py` — plain text input
  with Apply/Cancel; no validation today.
- **ChangeSpec query system** at `src/sase/ace/query/` is the model to fork. It ships:
  - `types.py` — `StringMatch`, `PropertyMatch`, `NotExpr`, `AndExpr`, `OrExpr`, `to_canonical_string()`.
  - `tokenizer.py` (~420 LOC) — bare words, quoted `"..."`, case-sensitive `c"..."`, property prefixes (`status:`,
    `project:`, `name:`, `ancestor:`, `sibling:`), shorthand sigils (`%d %m %r %s %w %y` and `!!!`, `@@@`, `$$$`, `!!`,
    `!@`, `!$`, `!@$`).
  - `parser.py` (~308 LOC) — recursive-descent with NOT > AND > OR precedence; juxtaposition = AND.
  - `evaluator.py` (~523 LOC) — builds a per-changespec haystack, evaluates the AST recursively, supports an
    `all_changespecs` context for ancestor lookups.
  - `highlighting.py` — `QUERY_TOKEN_STYLES` for syntax highlighting in the query editor.
  - Tests under `tests/test_query_*.py` (tokenizer, parser, evaluator, property filters, canonicalization).
- **Agent data model** (`src/sase/ace/tui/models/agent.py:221-411`) already has the fields we need for most filters:
  `cl_name`, `agent_name`, `status`, `start_time`, `agent_type` (RUNNING/WORKFLOW), `project_file`, `model`, `hidden`,
  `tag`, `workflow`, `step_type`, `error_message`, `retry_status`. **Pinning is already implemented as
  `tag == "pinned"`** (see `_tagging.py:14` `DEFAULT_PINNED_TAG`), so `pinned:true` is sugar for `tag:pinned` — no new
  agent field or persistence is required.
- **Attention** is already defined in `src/sase/ace/tui/models/agent_groups.py:93-95` as `_NEEDS_ATTENTION_STATUSES`;
  reuse that set verbatim so the BY_STATUS bucket and the `attention:true` filter stay in lockstep.

## Design Decisions

- **Fork, don't refactor.** Copy-and-adapt `src/sase/ace/query/{types,tokenizer,parser,evaluator,highlighting}.py` into
  a new `src/sase/ace/agent_query/` package. Extracting a shared core would mean retrofitting the changespec query
  system mid-flight; not worth the churn for two consumers. The two languages will diverge over time anyway (different
  property keys, different shorthand sigils, different comparison operators).
- **Shared lexical conventions.** The new tokenizer keeps the same string syntax (bare / `"quoted"` / `c"case-sens"`)
  and the same boolean keywords (`AND`/`OR`/`NOT` + parens + juxtaposition). This means a sase user who already knows
  the changespec query language reads agent queries with no new vocabulary except the property keys.
- **Drop changespec-specific shorthand.** The `%d %m %r %s %w %y` status sigils, `!!!`, `@@@`, `$$$` and friends are all
  changespec-shaped; do not port them. The agent-side equivalents are already expressible as `status:failed`,
  `status:running`, `attention:true`, etc.
- **Property keys (closed set).** The Phase-1 tokenizer recognizes only this allowlist. Any other `key:value` pair is a
  parse error with a clear message. Closed set keeps the surface area auditable and lets us evolve the language without
  worrying about silent typos:

  | Key         | Type                           | Source field(s) on `Agent`                     | Notes                                                                                                                                                                                           |
  | ----------- | ------------------------------ | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
  | `status`    | substring (case-insensitive)   | `status`                                       | Matches anywhere in the status string, so `status:failed` hits both `FAILED` and `FAILED (RETRIED)`.                                                                                            |
  | `cl`        | substring                      | `cl_name`                                      |                                                                                                                                                                                                 |
  | `project`   | substring                      | `project_file` basename                        | Match on basename, not full path, to mirror changespec `project:` semantics.                                                                                                                    |
  | `name`      | substring                      | `agent_name` then fall back to `display_name`  |                                                                                                                                                                                                 |
  | `model`     | substring                      | `model`                                        |                                                                                                                                                                                                 |
  | `provider`  | substring                      | `llm_provider`                                 | Bonus key — natural pair with `model`; cheap to add.                                                                                                                                            |
  | `type`      | enum                           | `agent_type`                                   | Accepts `workflow`, `run`/`running`.                                                                                                                                                            |
  | `source`    | enum                           | derived                                        | `axe` ⇔ agent has a `workflow` parent OR `step_type is not None`; `manual` ⇔ otherwise. Implement as a single helper `agent_source(agent) -> Literal["axe","manual"]` so the rule has one home. |
  | `tag`       | exact match (case-insensitive) | `tag`                                          | `tag:foo` matches `tag == "foo"`. Bare `tag:` (empty) matches any tagged agent.                                                                                                                 |
  | `pinned`    | bool                           | derived: `tag == "pinned"`                     | `pinned:true` ⇔ `tag:pinned`. `pinned:false` ⇔ `NOT tag:pinned`.                                                                                                                                |
  | `hidden`    | bool                           | `hidden`                                       | `hidden:true` ⇔ agent flagged hidden. By default the agents tab already filters hidden agents _out_; `hidden:true` is the explicit way to surface them.                                         |
  | `attention` | bool                           | derived: `status in _NEEDS_ATTENTION_STATUSES` | Reuse the existing set in `agent_groups.py:93-95`.                                                                                                                                              |
  | `needs`     | enum                           | derived                                        | Only value is `input`: `status` ∈ {`QUESTION`, `WAITING INPUT`, `PLAN APPROVED`}. Codify the mapping as a module-level constant `_NEEDS_INPUT_STATUSES`.                                        |
  | `age`       | duration with comparator       | `start_time`                                   | New syntax — see below.                                                                                                                                                                         |
  | `text`      | substring                      | full haystack                                  | Same fields as the legacy substring search. Equivalent to writing the value bare (no `key:`).                                                                                                   |

- **`age` comparison operators.** The only filter from the user's list with non-`key:value` shape. Tokenizer accepts:
  - `age>2h`, `age<30m`, `age>=1d`, `age<=15s`, `age:2h` (alias for `age>=2h` — "at least N old", since "older than N"
    is the common intent).
  - Duration grammar: `(\d+)(s|m|h|d)`; whole numbers only (no `1.5h`); single unit per literal (no `1h30m` — write
    `age>=1h AND age<90m` if needed).
  - Implementation: a new `DurationCompare(key="age", op, seconds)` AST node distinct from `PropertyMatch`. Evaluator
    computes `now() - agent.start_time` and compares.
  - Agents with `start_time is None` always fail any `age` comparison — they cannot be reasoned about. Document this in
    the help modal.

- **Boolean values.** `pinned:true|false`, `hidden:true|false`, `attention:true|false`. Case-insensitive. No other
  truthy strings (`yes`/`1`/etc.) — keep the surface narrow. Tokenizer rejects e.g. `pinned:yes` with a clear message.

- **Hierarchy preservation.** A matching agent keeps its ancestors visible (current behavior). When the parser produces
  an empty AST (empty query), `evaluate_agent_query` returns `True` for every agent — equivalent to "no filter applied".
  This matches today's `if not self._agent_search_query: return True` short-circuit.

- **Parse errors are non-fatal.** The TUI catches `AgentQueryParseError` and shows it as a transient error toast /
  status-line message; the prior accepted query stays in effect (no agents disappear silently because of a typo).

- **Saved-query backward compat.** Whatever the user has saved as their current `_agent_search_query` from before this
  feature lands is, by definition, a bare-word substring that the new parser will accept verbatim and route to the
  fallback text search. No migration step needed.

- **Help modal & docs.** Per `src/sase/ace/AGENTS.md`, the `?` help popup must stay in sync with TUI behavior. The
  Phase-3 agent updates the help modal with the agent query syntax cheatsheet.

## Phasing

Three phases, each landed by a distinct fresh agent instance. Phases are sequential — Phase 2 imports Phase 1's parser;
Phase 3 imports Phase 2's evaluator.

### Phase 1 — `agent_query/` skeleton: types, tokenizer, parser

**Scope:** Pure-syntax layer. No semantics, no Agent imports, no TUI touches.

- Create `src/sase/ace/agent_query/__init__.py` re-exporting `parse_agent_query`, `AgentQueryParseError`, AST nodes.
- Create `src/sase/ace/agent_query/types.py`:
  - Copy `StringMatch`, `NotExpr`, `AndExpr`, `OrExpr` from `query/types.py` unchanged (they're language-independent).
  - Drop the changespec-specific markers (`ERROR_SUFFIX_QUERY`, `RUNNING_AGENT_QUERY`, `RUNNING_PROCESS_QUERY` and the
    related `is_*` flags on `StringMatch`).
  - Replace `PropertyMatch` with two sibling node types:
    - `PropertyMatch(key, value)` — for substring/enum/bool keys.
    - `DurationCompare(key, op, seconds)` — for `age` comparisons. `op ∈ {"<","<=",">",">=","="}`.
  - `to_canonical_string()` updated to render both node types.
- Create `src/sase/ace/agent_query/tokenizer.py` by copy-and-adapt from `query/tokenizer.py`:
  - Keep: bare-word/quoted/`c"..."` string parsing, `AND`/`OR`/`NOT`/parens, whitespace handling.
  - Remove: `%d %m %r %s %w %y` shorthand, `!!!`/`@@@`/`$$$` and friends, ChangeSpec property keys.
  - Add the closed property-key allowlist exactly as the table above. Unknown `key:` → parse error.
  - Add comparison-operator scanning specifically scoped to the `age` key. Encountering `<`, `>`, `<=`, `>=` outside an
    `age...` context is a parse error (we don't want global comparison operators).
  - Add a duration-literal sub-lexer: `(\d+)(s|m|h|d)`, returning total seconds.
  - Add boolean-literal recognition for `pinned`/`hidden`/`attention` values: only `true`/`false` accepted
    (case-insensitive).
- Create `src/sase/ace/agent_query/parser.py` by copy-and-adapt from `query/parser.py`:
  - Same recursive-descent skeleton; same precedence (NOT > AND > OR; juxtaposition = AND).
  - Primary expression accepts: `StringMatch`, `PropertyMatch`, `DurationCompare`, parenthesized expression.
  - Parser uses `AgentQueryParseError` (new, mirrors `QueryParseError`) with helpful messages including the offending
    span.
- Tests (under `tests/`):
  - `test_agent_query_tokenizer.py` — every property key, every shorthand rejection, duration literals, boolean
    literals, comparison operators, error messages.
  - `test_agent_query_parser.py` — precedence, juxtaposition, parens, NOT, mixed property + bare-word queries.
  - `test_agent_query_canonicalization.py` — round-trip `parse → to_canonical_string → parse` for a representative
    corpus.
- **Deliverable:** Parser is importable and tested but no consumer wires it in yet. `just check` is green.

**Out of scope:** evaluator, Agent imports, any TUI/keymap/modal change.

### Phase 2 — Evaluator + agent-side helpers

**Scope:** Semantics. Lift the parser's AST into a predicate over `Agent`. Add the small derivation helpers the
evaluator needs.

- Create `src/sase/ace/agent_query/evaluator.py`:
  - Public entry point
    `evaluate_agent_query(expr: QueryExpr, agent: Agent, *, now: datetime, content_cache: AgentContentSearchCache | None) -> bool`.
  - Builds a per-agent haystack equivalent to today's `_matches()` body for `StringMatch` evaluation (cl_name,
    display_name, agent_name, status, plus content from `content_cache` when supplied).
  - `PropertyMatch` dispatches on `key` to a small private function per key (one function per row of the property
    table). Substring matches are case-insensitive; `tag` is exact-match (case-insensitive).
  - `DurationCompare` computes `(now - agent.start_time).total_seconds()` and applies `op`. Returns `False` when
    `start_time is None` (cannot reason about age).
  - Pure function — no I/O, no global state. Caller supplies `now` and the content cache.
- Add helpers (kept close to the data they describe, not in the evaluator):
  - `agent_source(agent) -> Literal["axe","manual"]` in `src/sase/ace/tui/models/agent.py` (or a sibling helpers module
    if `agent.py` is full). Rule: axe ⇔ `workflow is not None or step_type is not None`; manual otherwise.
  - `_NEEDS_INPUT_STATUSES: frozenset[str]` next to `_NEEDS_ATTENTION_STATUSES` in `agent_groups.py`. Initial mapping:
    `{"QUESTION", "WAITING INPUT", "PLAN APPROVED"}`. Phase-2 agent: leave a
    `# TODO(@user): confirm needs:input mapping` comment so I can review before it's canonized.
  - `is_pinned(agent) -> bool` colocated with `DEFAULT_PINNED_TAG` in `_tagging.py` (or a small `agent_pin.py` if
    importing `_tagging.py` would create cycles into the TUI from the evaluator). Returns
    `agent.tag == DEFAULT_PINNED_TAG`.
- Tests (`tests/test_agent_query_evaluator.py`):
  - One test per property key against a synthetic `Agent` fixture factory. Cover the boolean dimensions (true vs. false,
    present vs. absent).
  - `age` comparator coverage with frozen `now`: `>`, `<`, `>=`, `<=`, `=`, `:` alias, missing `start_time`.
  - Boolean composition (`status:failed AND attention:true`, `NOT (project:foo OR cl:bar)`).
  - Bare-word + property combination (`"database migration" status:failed`).
  - Hierarchy concerns are NOT tested here — that's Phase 3's integration concern. Evaluator is per-agent only.
- **Deliverable:** `evaluate_agent_query()` is importable, tested in isolation, and ready to be wired into the TUI.

**Out of scope:** `_loading.py` / TUI integration, modal changes, help modal, persisted-query migration.

### Phase 3 — TUI integration, modal, help modal, error surfacing

**Scope:** User-visible. Replace the inline `_matches()` predicate in `_finalize_agent_list()` with a call to the new
evaluator; surface parse errors; teach the modal and help popup the new syntax.

- `src/sase/ace/tui/actions/agents/_loading.py`:
  - At the top of `_finalize_agent_list()`, parse `self._agent_search_query` once via `parse_agent_query()`. Cache the
    parsed AST on `self` keyed by the raw query string so re-renders don't re-parse.
  - Replace the inline `_matches()` body (lines 440-472) with
    `evaluate_agent_query(parsed_ast, agent, now=..., content_cache=self._agent_content_search_cache)`.
  - Preserve the existing hierarchy-preservation logic (matching parents keep children visible) — wrap the per-agent
    evaluator call in the same parent-child traversal that exists today; do not change that logic.
  - On `AgentQueryParseError`: log + show a transient toast (`self.notify("Bad query: <msg>", severity="warning")`),
    fall back to "no filter" for this render so agents stay visible. Store the error message on `self` so the modal can
    show it next time the user opens it.
- `src/sase/ace/tui/modals/query_edit_modal.py`:
  - The agents-tab call site (only) passes a hint footer string like `"status:foo  cl:bar  age>2h  attention:true …"` so
    the modal isn't bare. Keep the modal generic — pass the hint as a constructor arg with a sensible default.
  - On Apply, run `parse_agent_query()` immediately; if it raises, keep the modal open and render the error in red
    underneath the input. Dismiss only on a clean parse.
- `src/sase/ace/tui/modals/help_modal/` (per `src/sase/ace/AGENTS.md` "Help Popup Maintenance"):
  - Add an "Agent Query Syntax" section listing the property keys, the boolean operators, the `age` comparator grammar,
    and 3-4 example queries from the user's list. Respect the 57-char box width.
- `src/sase/ace/agent_query/highlighting.py` (optional but polished):
  - Mirror `query/highlighting.py` so the modal's input highlights tokens the same way the changespec query editor does.
    If this ends up >100 LOC it can defer to a follow-up.
- Tests:
  - `tests/test_agents_tab_query_integration.py` — drive `_finalize_agent_list()` (or the smallest seam that exercises
    it) with synthetic agent lists and a handful of representative queries; verify (a) hierarchy preservation, (b)
    parse-error fallback, (c) cached-AST reuse across re-renders.
  - Snapshot test for the modal's error display.
- **Deliverable:** Feature is user-visible end-to-end. Existing bare-word users see no behavior change. Power users can
  write structured queries.

**Out of scope:** any saved-query persistence beyond what already exists; per-panel queries; cross-tab application of
the same parser to ChangeSpec.

## Notable Risks / Open Questions

- **`needs:input` mapping is a judgment call.** Phase 2 agent should land the proposed set
  `{QUESTION, WAITING INPUT, PLAN APPROVED}` with a `# TODO(@user)` and tag me. The set is small enough to revise later
  without breaking anyone's saved queries.
- **`source:axe` heuristic.** The proposed rule (`workflow is not None or step_type is not None`) covers
  workflow-spawned agents and bgcmd children. Manually-launched root-of-workflow agents would be classified as `manual`
  _until_ a workflow attaches — which is correct. Phase 2 agent should add a docstring on `agent_source()` calling out
  this edge case.
- **Status string formatting.** `status:failed` matching as substring intentionally hits both `FAILED` and
  `FAILED (RETRIED)`. If a user wants only the bare `FAILED`, they can write `c"FAILED"` or `status:"FAILED "` (with the
  trailing space) — document this in the help modal.
- **Property allowlist in tokenizer is a forward-compat hazard.** If a future plan adds a new property key, the
  tokenizer change must land _before_ anyone tries to use it — or the parser will reject the new key. Acceptable cost
  for the safety the allowlist buys.
- **Performance.** Today's `_matches()` already touches the same content cache. Parsing once per query (cached on
  `self`) is strictly cheaper than re-parsing per agent. No new perf concerns expected; Phase 3 agent should
  sanity-check on a several-hundred-agent list.
- **Cycles between `agent_query/` and `tui/`.** Keep the evaluator's `Agent` import a `TYPE_CHECKING`-only import, and
  let the caller pass the `AgentContentSearchCache`. This keeps `agent_query/` re-usable from a future
  `sase agents search` CLI without dragging in the TUI.
- **Future `sase agents search` CLI.** Not in scope, but the Phase 1/2 modules should be import-clean from a CLI context
  (no TUI imports at module top level) so a follow-up plan can add `sase agents search "<query>"` cheaply.
