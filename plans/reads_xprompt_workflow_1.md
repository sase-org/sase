# Plan: Add `#reads` Workflow in `.xprompts/reads.yml`

## Goal

Create a new xprompt workflow `#reads` (YAML file in `.xprompts/reads.yml`) that:

1. Runs Gemini, Claude, and Codex agents in parallel with the same research prompt.
2. Collects recent, medium-to-long articles or research papers relevant to continuing `sase` development.
3. Runs a final Claude step to consolidate and de-duplicate the combined list.
4. Produces one explicit "best next read" recommendation.

## Scope and Constraints

- Keep implementation to a single new file: `.xprompts/reads.yml`.
- Use workflow-native `parallel:` semantics (top-level parent + 3 nested named substeps).
- Use identical prompt body in all three parallel agent steps; only model directive differs.
- Ensure final step consumes outputs from all parallel steps by name.
- Keep outputs robust to formatting variance (avoid brittle parsing in early version).

## Implementation Plan

### 1. Add `.xprompts/reads.yml` workflow

- Define `steps:` with two top-level steps:
  - `research` (`parallel:` block with 3 nested agent steps)
  - `consolidate` (single Claude agent step)

### 2. Implement parallel research fan-out

- In `research.parallel`, add these nested steps:
  - `gemini_search` with `%model:#pro`
  - `claude_search` with `%model:opus`
  - `codex_search` with `%model:#codex`
- Keep the same core prompt text in each nested step:
  - Find recent (favor 2024-2026), medium-to-long articles/papers.
  - Prioritize relevance to agent frameworks, orchestration, eval/reliability, developer workflows, and tooling.
  - Return consistent fields per item: title, authors, URL, date, approximate length, and why it helps `sase`.
- Rely on default `join: object` for `parallel:` so outputs are addressable as:
  - `{{ research.gemini_search }}`
  - `{{ research.claude_search }}`
  - `{{ research.codex_search }}`

### 3. Implement final Claude consolidation step

- Add `consolidate` agent step with `%model:opus`.
- Feed all three parallel outputs into the prompt template.
- Instruct consolidation logic to:
  - Merge and normalize candidate lists.
  - De-duplicate by URL and near-duplicate title/author matches.
  - Rank by `sase` relevance, quality, and recency.
  - Emit:
    - A de-duplicated ranked shortlist.
    - A single `Best Next Read` recommendation with concise justification.
    - Source-attribution note showing which upstream agent(s) suggested each retained item.

## Validation Plan

1. Parse/shape validation:

- Run `.venv/bin/sase xprompt explain reads` and confirm:
  - Two top-level steps.
  - First step is `parallel` with 3 nested agent steps.
  - Second step is a single agent step.

2. Execution smoke test:

- Invoke `#reads` in the normal flow and verify:
  - Gemini/Claude/Codex nested steps execute in parallel.
  - `consolidate` runs after all three complete.
  - Output includes de-duplicated list plus one explicit best-next-read pick.

3. Quality checks:

- Confirm returned links are not stale/off-topic.
- Confirm medium-to-long reading bias is present.
- Confirm duplicates across agents are collapsed.

## Risks and Mitigations

- Model alias mismatch (`#pro`, `#codex`) in some environments:
  - Mitigation: swap to explicit model identifiers only if aliases fail.
- Inconsistent structure from parallel agents:
  - Mitigation: enforce explicit per-item fields in prompt and keep consolidator tolerant.
- Over-constrained parser expectations:
  - Mitigation: keep agent outputs as text-first in v1; add strict `output:` schema only after stability.
