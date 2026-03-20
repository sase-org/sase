# Plan: `#reads` XPrompt Workflow

## Goal

Create `.xprompts/reads.yml` — a workflow that fans out to three AI providers in parallel to find articles/papers
relevant to sase development, then consolidates the results with a final Claude agent.

## Design

### Workflow Structure

```
parallel (fan-out)
  ├── gemini agent  →  list of articles/papers
  ├── claude agent  →  list of articles/papers
  └── codex agent   →  list of articles/papers
        ↓
consolidate (claude agent)  →  de-duplicated list + "best next read" recommendation
```

### Step 1: `research` (parallel fan-out)

A `parallel:` step containing three `agent:` sub-steps, each targeting a different provider via the
`%model:provider/model` directive syntax:

- **`gemini_research`** — `%model:gemini/gemini-2.5-pro`
- **`claude_research`** — `%model:claude/sonnet` (explicit for clarity)
- **`codex_research`** — `%model:codex/o3`

Each agent gets the same prompt asking it to find recent, medium-to-long articles or research papers that will help
continue developing sase. The prompt includes context about what sase is (a Python toolkit for building and
orchestrating AI agents) so the agents can make relevant recommendations.

Each agent returns raw text output (no structured `output:` schema) since the results are free-form article lists. The
`_raw` field captures the full response.

**Join mode:** `object` (default) — so the consolidation step can reference each sub-step by name.

### Step 2: `consolidate` (final Claude agent)

A single `agent:` step (using the default Claude provider) that receives the three research outputs via Jinja2 template
references:

- `{{ research.gemini_research._raw }}`
- `{{ research.claude_research._raw }}`
- `{{ research.codex_research._raw }}`

This agent's prompt instructs it to:

1. Merge and de-duplicate the three lists
2. Provide a consolidated, annotated list of articles/papers
3. Select a single "best next read" recommendation with justification

## Implementation

Single file to create: `.xprompts/reads.yml`

```yaml
steps:
  - name: research
    parallel:
      - name: gemini_research
        agent: |
          %model:gemini/gemini-2.5-pro
          %name:gemini-reads

          Find recent (2024-2026), medium-to-long articles or research papers that will help me
          continue developing **sase** (Structured Agentic Software Engineering) — a Python toolkit
          for building and orchestrating AI agents.

          Relevant topics include: AI agent orchestration, tool-use patterns, multi-agent systems,
          LLM workflow engines, prompt engineering for agents, structured output from LLMs, and
          developer tooling for AI-assisted software engineering.

          For each recommendation, provide: title, author(s), date, URL (if available), and a brief
          explanation of why it's relevant to sase development.

      - name: claude_research
        agent: |
          %model:claude/sonnet
          %name:claude-reads

          Find recent (2024-2026), medium-to-long articles or research papers that will help me
          continue developing **sase** (Structured Agentic Software Engineering) — a Python toolkit
          for building and orchestrating AI agents.

          Relevant topics include: AI agent orchestration, tool-use patterns, multi-agent systems,
          LLM workflow engines, prompt engineering for agents, structured output from LLMs, and
          developer tooling for AI-assisted software engineering.

          For each recommendation, provide: title, author(s), date, URL (if available), and a brief
          explanation of why it's relevant to sase development.

      - name: codex_research
        agent: |
          %model:codex/o3
          %name:codex-reads

          Find recent (2024-2026), medium-to-long articles or research papers that will help me
          continue developing **sase** (Structured Agentic Software Engineering) — a Python toolkit
          for building and orchestrating AI agents.

          Relevant topics include: AI agent orchestration, tool-use patterns, multi-agent systems,
          LLM workflow engines, prompt engineering for agents, structured output from LLMs, and
          developer tooling for AI-assisted software engineering.

          For each recommendation, provide: title, author(s), date, URL (if available), and a brief
          explanation of why it's relevant to sase development.

  - name: consolidate
    agent: |
      %name:reads-consolidator

      You are consolidating research reading recommendations from three AI agents. Each searched for
      recent articles and papers relevant to developing **sase** — a Python toolkit for building and
      orchestrating AI agents.

      ## Gemini's recommendations
      {{ research.gemini_research._raw }}

      ## Claude's recommendations
      {{ research.claude_research._raw }}

      ## Codex's recommendations
      {{ research.codex_research._raw }}

      ## Your task
      1. Merge and de-duplicate the lists above (same article from multiple agents = one entry)
      2. Produce a single consolidated list, ordered by relevance to sase development
      3. For each entry: title, author(s), date, URL, and a one-line relevance note
      4. At the end, select **one "best next read"** and explain why it should be read first
```

## Notes

- The `parallel:` step ensures all three research agents run concurrently, not sequentially.
- Using `_raw` to pass unstructured text between steps avoids needing a rigid output schema for free-form article lists.
- The `%name:` directives give each agent a descriptive name visible in the TUI.
- No `input:` block needed — this workflow is self-contained with no user parameters.
- The provider/model syntax (`gemini/gemini-2.5-pro`, `codex/o3`) follows the pattern in
  `src/sase/llm_provider/registry.py` where `_PROVIDER_MODEL_RE` parses `provider/model` strings.
