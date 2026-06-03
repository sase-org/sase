---
create_time: 2026-06-03 15:55:36
status: done
prompt: sdd/prompts/202606/bob_dataview_reads.md
bead_id: sase-4b
tier: epic
---
# Plan: Dataview-Backed `#!sase/reads`

## Goal

Let `#!sase/reads` take an Obsidian Dataview TABLE query instead of a literal list of reference-note files. The research
agents should use a generated `/bob_dataview` skill to run `bob dataview`, read the returned title/URL table, and treat
those rows as the exclusion list before searching the web.

This plan is split for separate agent instances. Each phase should be independently verifiable before the next starts.

## Current Findings

- `xprompts/reads.md` currently has a `notes` text input whose default is a literal list of five files:
  `~/bob/agent_ref.md`, `~/bob/ai_ref.md`, `~/bob/claude_code_ref.md`, `~/bob/gemini_cli_ref.md`, and
  `~/bob/xprompt_ref.md`.
- The checked-in reads xprompt already uses a frontmatter-local `_article_search_agent` helper, and tests already cover
  local helper expansion in `tests/test_multi_agent_xprompt_local_helpers.py`.
- `docs/development.md` documents the project-local workflow as `#!sase/reads`; from this checkout, top-level
  `xprompts/` entries are namespaced as `sase/<name>`.
- `bob dataview` exists and supports:
  - `--query <DQL>` or `--query-file <PATH>`
  - `--format markdown` for DQL output
  - `--engine obsidian` by default, which is the exact Dataview runtime
- The current AI reference notes are mostly Zorg-migrated aggregate pages. Each article is a list item with inline
  fields such as `ID::`, `status::`, `title::`, and `url::`.
- A Dataview probe can read aggregate list-item `url` values with `FLATTEN file.lists AS L`, but titles are inconsistent
  and not suitable for a simple page-level `TABLE title, url` query.
- A page-per-reference migration is therefore necessary if `#!sase/reads` is to use a simple TABLE query over note
  files.
- Candidate AI reference aggregate pages found so far:
  - `ai_ref.md`: 36 entries
  - `agent_ref.md`: 112 entries
  - `claude_code_ref.md`: 63 entries
  - `gemini_cli_ref.md`: 26 entries
  - `xprompt_ref.md`: 24 entries
  - `langgraph_ref.md`: 10 entries
  - `mcp_ref.md`: 11 entries
  - `memory_ref.md`: currently no matching entries
- The Bob vault already has uncommitted changes. A migration agent must inspect and preserve those changes; do not reset
  or rewrite unrelated vault state.
- Generated SASE skills are source-controlled under `src/sase/xprompts/skills/`. The active deploy command in this
  checkout is `sase skills init --force`; `sase init skills` is a compatibility alias. The older `sase init-skills`
  spelling is not accepted here.

## Phase 1: Migrate AI Reference Records to Individual Obsidian Notes

### Objective

Create one Obsidian note per AI reference record so Dataview can answer a simple page-level `TABLE title, url` query.

### Scope

Work in `~/bob`, not the SASE repo, except for any short migration notes an agent chooses to leave in the SASE plan
closeout. Follow the Obsidian memory rule: new Markdown notes under `~/bob` need a `parent` frontmatter field linking to
another note.

### Design

- Start by recording the existing vault state:
  - `git -C ~/bob status --short`
  - relevant diffs for already-modified AI reference aggregate files
- Treat the migration as additive and idempotent.
  - Do not delete the aggregate `*_ref.md` pages in this phase.
  - Do not rewrite existing block IDs like `^z-...`; many notes link to those anchors.
  - If aggregate pages need backlinks to the new notes, add them only after confirming they do not disturb existing
    block references.
- Use a stable target layout, for example:
  - `~/bob/ref/ai/ai_ref/<id>.md`
  - `~/bob/ref/ai/agent_ref/<id>.md`
  - `~/bob/ref/ai/claude_code_ref/<id>.md`
  - source subdirectories avoid filename collisions across aggregate pages.
- Parse each aggregate record into structured fields:
  - source page, source block ID, source line span
  - `ID::` value
  - status
  - title, if present
  - URL or URL list
  - file attachment links
  - related links
  - visible tags from the bullet line, such as `#dev` or `#sase`
  - any literature/fleeting notes body that belongs to that record
- Derive `title` conservatively:
  - Prefer an explicit `title::` field.
  - Otherwise use the `ID::` value transformed into a readable title.
  - Do not fetch the web for titles in this phase unless the user explicitly approves broad title enrichment.
- Write frontmatter suitable for Dataview:
  - `parent: "[[ai_ref]]"` or the closest existing parent such as `[[agent_ref]]` when that is more useful.
  - `tags: [ai/reference]` plus any useful topic tags.
  - `status: <normalized-status>`
  - `title: <title>`
  - `url: <string or list>`
  - `source_note: "[[agent_ref]]"` or equivalent.
  - `source_block: "^z-..."`
  - `source_id: <ID>`
- Preserve source content in the body so no information is lost. A simple body can include:
  - a backlink to the original block
  - attachment links
  - related links
  - copied notes from the aggregate record
- Handle special cases explicitly:
  - `url:: NONE`: omit `url` or set an empty value so the default reads query filters it out.
  - local vault links such as `[[lib/chat/...]]`: preserve them, but consider excluding them from the default web URL
    query.
  - multiple `url::` fields or multiline URL lists: store a YAML list.
  - duplicate URLs across source pages: keep notes but emit an audit report so later phases can decide whether to
    deduplicate.

### Verification

- Count generated notes and compare against parsed source records. The current expected scale is roughly 282 records
  across the seven nonempty aggregate pages above.
- Run a Dataview smoke query:

  ```dataview
  TABLE WITHOUT ID title AS Title, url AS URL
  FROM #ai/reference
  WHERE url
  SORT title ASC
  ```

- Execute it with:

  ```bash
  bob dataview --format markdown --query-file <query-file>
  ```

- Confirm the output contains only title and URL columns and includes representative records from each migrated source
  page.
- Inspect `git -C ~/bob diff --stat` and ensure unrelated pre-existing vault changes were not reverted or overwritten.

### Deliverable

Individual AI reference notes in `~/bob/ref/ai/**` plus a short migration audit in the phase closeout: parsed count,
generated count, skipped count, duplicate URL count, and the exact Dataview query that passed.

## Phase 2: Add Generated `/bob_dataview` Skill

### Objective

Make a `/bob_dataview` skill available to all SASE-supported runtimes so reads agents know how to run Dataview queries
against the Bob vault.

### Scope

Work in the SASE repo.

### Design

- Add `src/sase/xprompts/skills/bob_dataview.md` with generated-skill frontmatter:
  - `name: bob_dataview`
  - a concise description
  - `skill: true`
- The skill should instruct agents to:
  - use `bob dataview` for read-only Dataview access to `~/bob`
  - prefer `--query-file -` or a temporary query file for multiline DQL
  - default to `--format markdown` when the result is going into a prompt or human-readable answer
  - use `--format paths` only for source expressions or path-only needs
  - include `--bob-dir <path>` only when the user asks for a nondefault vault
  - treat command failures as actionable diagnostics, not as permission to parse the whole vault ad hoc
  - avoid modifying Bob vault files
- Include a small command example using the reads query:

  ```bash
  bob dataview --format markdown --query-file /path/to/query.dql
  ```

- Keep the instructions provider-neutral; do not branch for Claude/Gemini/Codex/Qwen/OpenCode.

### Verification

- Run a dry generation first:

  ```bash
  sase skills init --dry-run --force
  ```

- Deploy generated skill files:

  ```bash
  sase skills init --force
  ```

- Use `sase skills list` to confirm `bob_dataview` appears and generated targets are current.
- Add or update tests only if the existing generated-skill source tests do not automatically cover the new skill source.
- Run focused init-skills/source tests, then `just install` if needed and `just check` before finishing because this
  phase changes SASE repo files.

### Deliverable

`/bob_dataview` is available in generated skill directories for all configured providers, and the source skill file is
tracked in the SASE repo.

## Phase 3: Refactor `xprompts/reads.md` to Use Dataview

### Objective

Change the reads xprompt contract from a list of note files to an Obsidian Dataview query, and instruct the research
agents to use `/bob_dataview` before searching.

### Scope

Work in the SASE repo.

### Design

- Replace the `notes` input with a query-oriented input, preferably `reference_query`.
- Default it to the Phase 1 query:

  ```dataview
  TABLE WITHOUT ID title AS Title, url AS URL
  FROM #ai/reference
  WHERE url
  SORT title ASC
  ```

- Consider short-term compatibility:
  - If existing call sites pass `notes=...`, either preserve a deprecated optional `notes` input for one release or
    document the intentional breaking change.
  - If keeping both inputs makes the prompt harder for agents to follow, prefer the clean `reference_query` contract.
- Update `_article_search_agent` so each research agent:
  - reads the Dataview query from the prompt
  - uses `/bob_dataview` to run it with `bob dataview`
  - treats every title and URL in the result table as off-limits, including unread entries
  - searches the current web only after building that exclusion set
  - does not manually read the old aggregate note files unless the Dataview command fails
- Update the final consolidation segment:
  - refer to the reference Dataview query instead of "reference notes"
  - keep the `wait_chats` raw Jinja handling unchanged
  - tell the final agent to resolve duplicate uncertainty against the transcript/table data, and to rerun
    `/bob_dataview` only if needed
- Update tests:
  - checked-in reads xprompt still loads and expands
  - the rendered research segments mention `/bob_dataview`
  - the rendered research segments include the Dataview query and no longer contain the old five-file default list
  - the final segment describes the query-based exclusion source
- Update docs/examples if they mention `notes`.

### Verification

- Run focused xprompt tests, especially:

  ```bash
  .venv/bin/pytest tests/test_multi_agent_xprompt_local_helpers.py tests/test_multi_agent_xprompt_expansion.py
  ```

- Run `sase xprompt list` or `sase xprompt explain` from the checkout to confirm the workflow is still visible as
  `#!sase/reads` and the input signature is correct.
- Run `just install` if needed and `just check` before finishing because this phase changes SASE repo files.

### Deliverable

`#!sase/reads` defaults to a Dataview query and instructs all research agents to use `/bob_dataview` for the exclusion
table.

## Phase 4: End-to-End Smoke, Documentation, and Cleanup

### Objective

Verify the vault migration, generated skill, and reads xprompt work together in a real SASE launch path.

### Scope

Work in both SASE and `~/bob` only as needed for verification and documentation.

### Steps

- Re-run the default query through `bob dataview` and save the command/output summary in the phase closeout.
- Confirm generated skill availability from the active runtime environment:
  - `sase skills list`
  - inspect one generated `SKILL.md` target if needed
- Run a dry or low-cost launch-path check for `#!sase/reads`.
  - Prefer an expansion/explain command if available.
  - If a real multi-agent run is needed, use a narrow topic and verify the research-agent prompts tell agents to call
    `/bob_dataview`.
- Update `docs/development.md` or xprompt docs with the new input name and a short invocation example if Phase 3 did not
  already do so.
- Confirm no obsolete references remain in `xprompts/reads.md` or docs to "read these note files first".
- Collect final status:
  - SASE repo `git status --short`
  - Bob vault `git -C ~/bob status --short`
  - tests/checks run
  - any known duplicate or skipped reference records

### Deliverable

An end-to-end closeout proving:

- the default Dataview query returns title/URL rows from individual AI reference notes
- `/bob_dataview` is available to agents
- `#!sase/reads` uses the query-based exclusion workflow
- SASE checks pass
- Bob vault migration state is explicit and auditable

## Risks and Guardrails

- The Bob vault is already dirty. Every phase touching `~/bob` must preserve unrelated user changes.
- Do not delete aggregate reference pages in the migration phase; existing block links depend on them.
- Do not hand-edit deployed generated `SKILL.md` files. Edit only `src/sase/xprompts/skills/bob_dataview.md`, then run
  `sase skills init --force`.
- Keep the Dataview query output simple. `TABLE WITHOUT ID title, url FROM #ai/reference WHERE url` is intentionally
  page-level; avoid returning entire note bodies to the research agents.
- JSON output from `bob dataview` should not be assumed until tested with the target engine. Markdown output is the safe
  default for this workflow.
