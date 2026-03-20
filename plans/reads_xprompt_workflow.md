# Plan: Add `#reads` Workflow XPrompt in `.xprompts/`

## Goal

Create a new YAML workflow xprompt named `reads` in `.xprompts/reads.yml` that:

1. Runs Gemini, Claude, and Codex agents in parallel with the same research prompt.
2. Collects medium-to-long recent article/paper recommendations relevant to developing `sase`.
3. Runs a final Claude agent that consolidates, de-duplicates, and outputs one best-next-read recommendation.

## Constraints and Behavior to Preserve

- Follow current workflow schema (`docs/workflow_spec.md`) and existing `.xprompts/` conventions.
- Use a top-level `parallel:` step (at least 2 nested steps; unique nested names).
- Keep nested `parallel` steps simple (`agent` only; no nested loops/control-flow in substeps).
- Ensure downstream step references parallel results by nested step names (default `join: object`).

## Proposed Workflow Design

### 1. Add `.xprompts/reads.yml`

- Define optional inputs for tuning scope without changing the default intent:
  - `topic`: `text`, default `"developing sase"`
  - `recency_window`: `line`, default like `"last 24 months"`
  - `min_items_per_agent`: `int`, default `5`
- Create a shared literal prompt block (same wording for all 3 agents) that asks for:
  - Recent medium-to-long articles or papers
  - Strong relevance to agent/tooling architecture, orchestration, eval/reliability, or DX
  - Structured output suitable for merge/dedup (title, author(s), year/date, URL, why relevant, est. read time)

### 2. Parallel research step

- Add one top-level step, e.g. `collect_candidates`, using `parallel:` with 3 nested `agent` steps:
  - `gemini_scan`
  - `claude_scan`
  - `codex_scan`
- Each nested step uses the same prompt content, with only model/provider directive changed at the top:
  - `%model:<gemini provider/model>`
  - `%model:<claude provider/model>`
  - `%model:<codex provider/model>`
- Keep outputs parseable and consistent across all 3 substeps (prefer JSON array/object contract in prompt
  instructions).

### 3. Consolidation step (final Claude)

- Add a follow-up `agent` step, e.g. `consolidate_reads`:
  - Force Claude via `%model:<claude provider/model>`.
  - Provide all three outputs via template references:
    - `{{ collect_candidates.gemini_scan }}`
    - `{{ collect_candidates.claude_scan }}`
    - `{{ collect_candidates.codex_scan }}`
  - Instruct it to:
    - Normalize and merge entries
    - Deduplicate by URL/title+author similarity
    - Rank by relevance + novelty + quality + recency
    - Return one explicit `best_next_read` pick plus brief rationale

### 4. Output shape

- For `consolidate_reads`, define an explicit `output` schema so downstream use is reliable:
  - `best_next_read_title`
  - `best_next_read_url`
  - `best_next_read_why`
  - `deduped_list` (text/JSON serialized list)
- Keep schema modest if parser limitations for nested arrays become noisy; prioritize robust execution first.

## Validation Plan

1. Static validation:

- Run `.venv/bin/sase xprompt explain reads` to verify parse/render and step graph.
- Run `.venv/bin/sase xprompt graph reads --format text` to confirm parallel + consolidation topology.

2. Behavioral smoke test:

- Execute expansion/run path used in your workflow (`#reads`) and verify:
  - All 3 research agents launch in parallel.
  - Final Claude step waits for and consumes all 3 results.
  - Deduplicated output and single best-next-read recommendation are produced.

3. Quality checks:

- Confirm recommendations are medium-to-long and recent.
- Confirm obvious duplicates across agents are removed.

## Risks and Mitigations

- Model alias mismatch across environments:
  - Mitigation: use known provider/model strings already configured in this workspace; adjust directives after first
    explain/run.
- Inconsistent output formatting from parallel agents:
  - Mitigation: enforce strict response format in shared prompt; keep consolidation step resilient to minor variance.
- Overly strict output schema causing parse failures:
  - Mitigation: start with simpler text fields, then tighten schema once stable.

## Deliverables

- New file: `.xprompts/reads.yml`
- Verified workflow topology and explain output
- Working `#reads` invocation that produces one consolidated recommendation
