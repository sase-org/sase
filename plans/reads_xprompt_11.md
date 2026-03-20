# Plan: `#reads` XPrompt Workflow

## Goal

Create a new `#reads` xprompt YAML workflow at `.xprompts/reads.yml` that runs three AI agents in parallel (Gemini,
Claude, Codex) to find relevant articles/papers for sase development, then consolidates results with a final Claude
agent.

## Design

The workflow has two steps:

1. **`research` (parallel step)** — Three nested agent steps run concurrently, each with the same research prompt but
   using a different LLM provider via the `%model:` directive:
   - `gemini_research` — uses `%model:gemini`
   - `claude_research` — uses `%model:claude` (default provider, but explicit for clarity)
   - `codex_research` — uses `%model:codex`

   Each agent receives the prompt: _Find recent, medium-to-long articles or research papers that will help me continue
   developing sase._ The prompt will include context about what sase is (pulled from project description) so the agents
   can make relevant recommendations.

   The parallel step uses default `join: object` so results are accessible as `research.gemini_research`,
   `research.claude_research`, `research.codex_research`.

   Each nested step produces `output: { articles: text }` — a free-form text list of articles/papers found.

2. **`consolidate` (agent step)** — A Claude agent that receives all three research outputs via Jinja2 template
   references (`{{ research.gemini_research.articles }}`, etc.), de-duplicates them, and produces a single consolidated
   list with a "best next read" recommendation.

## Implementation

### File: `.xprompts/reads.yml`

```yaml
steps:
  - name: research
    parallel:
      - name: gemini_research
        agent: |
          %model:gemini
          Find recent, medium-to-long articles or research papers that will help me continue
          developing sase (Structured Agentic Software Engineering) — a Python toolkit for building
          and orchestrating AI agents. sase features a TUI, xprompt workflow system, multi-provider
          LLM integration (Claude, Gemini, Codex), and a bead-based task management system.

          Focus on topics like: AI agent orchestration, LLM tool use, agentic coding workflows,
          multi-agent coordination, developer tooling for AI, and structured software engineering
          with AI.

          For each article/paper, provide: title, author(s), URL or DOI, publication date, and a
          brief note on why it's relevant.
        output: { articles: text }

      - name: claude_research
        agent: |
          %model:claude
          Find recent, medium-to-long articles or research papers that will help me continue
          developing sase (Structured Agentic Software Engineering) — a Python toolkit for building
          and orchestrating AI agents. sase features a TUI, xprompt workflow system, multi-provider
          LLM integration (Claude, Gemini, Codex), and a bead-based task management system.

          Focus on topics like: AI agent orchestration, LLM tool use, agentic coding workflows,
          multi-agent coordination, developer tooling for AI, and structured software engineering
          with AI.

          For each article/paper, provide: title, author(s), URL or DOI, publication date, and a
          brief note on why it's relevant.
        output: { articles: text }

      - name: codex_research
        agent: |
          %model:codex
          Find recent, medium-to-long articles or research papers that will help me continue
          developing sase (Structured Agentic Software Engineering) — a Python toolkit for building
          and orchestrating AI agents. sase features a TUI, xprompt workflow system, multi-provider
          LLM integration (Claude, Gemini, Codex), and a bead-based task management system.

          Focus on topics like: AI agent orchestration, LLM tool use, agentic coding workflows,
          multi-agent coordination, developer tooling for AI, and structured software engineering
          with AI.

          For each article/paper, provide: title, author(s), URL or DOI, publication date, and a
          brief note on why it's relevant.
        output: { articles: text }

  - name: consolidate
    agent: |
      Below are three independently-generated lists of recommended articles and research papers
      for continuing development of sase (Structured Agentic Software Engineering).

      ## Gemini's recommendations
      {{ research.gemini_research.articles }}

      ## Claude's recommendations
      {{ research.claude_research.articles }}

      ## Codex's recommendations
      {{ research.codex_research.articles }}

      Please:
      1. Merge and de-duplicate these lists (same article found by multiple agents should appear once).
      2. Provide a single consolidated list, ordered by relevance. For each entry include: title,
         author(s), URL/DOI, date, and why it's relevant to sase development.
      3. At the end, give a single **"Best Next Read"** recommendation — the one article or paper
         that would be most valuable to read first, with a brief justification.
```

### Key decisions

- **No `input:` section** — the workflow is self-contained with a fixed research prompt. No user parameters needed.
- **`output: { articles: text }`** on each parallel step — uses `text` type since the research results are free-form
  prose, not structured data. This keeps things simple and avoids forcing the research agents into a rigid schema.
- **Default `join: object`** on the parallel step — allows the consolidate step to reference each agent's output by
  name, which is clearer than array indexing.
- **No `output:` on the final step** — the consolidation result is displayed directly to the user as the workflow's
  final output, no downstream step needs to reference it.
- **Shared prompt via copy** rather than workflow-local xprompts — the research prompt is short enough that duplicating
  it across three steps is clearer than adding a `_research_prompt` local xprompt. This avoids an extra indirection
  layer for a one-off workflow.
