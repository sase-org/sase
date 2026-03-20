# Plan: Create `#reads` xprompt workflow

## Summary

Create `.xprompts/reads.yml` — a workflow that fans out to three parallel agents (Gemini, Claude, Codex) to find
relevant articles/papers for sase development, then consolidates results via a final Claude agent.

## Context

A previous version of this workflow was implemented and reverted (commit `59a2e0b`). This plan improves on that version.

## Implementation

### Single file: `.xprompts/reads.yml`

**Step 1 — `research` (parallel)**

Three nested agent steps run concurrently, each with the same core prompt but using different model directives:

| Sub-step        | Model directive | Provider     |
| --------------- | --------------- | ------------ |
| `gemini_search` | `%model:#pro`   | Gemini       |
| `claude_search` | `%model:opus`   | Claude       |
| `codex_search`  | `%model:#codex` | Codex/OpenAI |

Shared prompt asks each agent to find recent (2024–2026), medium-to-long articles or research papers relevant to
developing an AI agent orchestration toolkit (sase). Each should return: title, author(s), URL, publication date,
estimated reading time, and a relevance summary.

Default `join: object` so the consolidation step can reference results by name.

**Step 2 — `consolidate` (agent)**

A single Claude Opus agent receives all three recommendation sets via template variables
(`{{ research.gemini_search }}`, `{{ research.claude_search }}`, `{{ research.codex_search }}`). It:

1. De-duplicates articles found by multiple agents
2. Ranks by relevance to sase development
3. Notes which agent(s) recommended each article
4. Selects a single "Best Next Read" with justification

### Design decisions

- **No `output:` spec on agent steps**: Agent responses are free-form text (article lists), not structured key=value.
  Omitting `output` avoids unnecessary parsing failures.
- **No `input:` block**: The workflow is self-contained with no user-configurable parameters.
- **Opus for consolidation**: The synthesis/ranking task benefits from the strongest reasoning model.
- **`#pro` and `#codex` model refs**: These use xprompt model aliases (defined in sase config) rather than raw model
  IDs, so they stay current as models are updated.
