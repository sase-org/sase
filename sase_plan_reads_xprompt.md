# Plan: Create `#reads` xprompt YAML workflow

## Goal

Create a new xprompt workflow at `.xprompts/reads.yml` that:

1. Runs three agents (Gemini, Claude, Codex) **in parallel**, each searching for recent articles/papers relevant to sase
   development
2. A final Claude agent **consolidates** the results — de-duplicating and recommending a single "best next read"

## File to create

**Path**: `/home/bryan/projects/github/sase-org/sase_100/.xprompts/reads.yml`

## Key design decisions

- **Model selection via `%model` directive**: Each agent step uses `%model:provider/model` to target a specific LLM
  provider. The `%model` directive is placed at the top of the agent prompt text.
- **Parallel execution**: The three search agents run inside a `parallel:` block with `join: object` (the default for
  parallel), so the consolidation step can reference each agent's output by name.
- **Output schema**: Each search agent outputs a `text` field called `articles` containing its findings. The
  consolidation agent outputs `consolidated` (the de-duplicated list) and `recommendation` (the single best next read).
- **Provider/model mapping** (from `src/sase/llm_provider/registry.py`):
  - `gemini/gemini-2.5-pro` → Gemini provider
  - `claude/sonnet` → Claude provider (sonnet is a good balance of speed/quality for search)
  - `codex/o3` → Codex/OpenAI provider
  - `claude/opus` → Claude provider (opus for the final consolidation — highest quality)

## Implementation

Create the file `.xprompts/reads.yml` with the following exact content:

```yaml
name: reads
steps:
  - name: search
    parallel:
      - name: gemini_search
        agent: |
          %model:gemini/gemini-2.5-pro
          You are a research assistant. Search for recent, medium-to-long articles or research papers
          that will help with the continued development of "sase" (Structured Agentic Software Engineering),
          a Python toolkit for building and orchestrating AI agents.

          Focus areas include:
          - AI agent architectures and orchestration patterns
          - LLM tool use and function calling
          - Multi-agent systems and collaboration
          - Prompt engineering techniques and workflows
          - Developer tooling for AI-assisted software engineering
          - Code generation and automated programming research

          For each article/paper, provide:
          - Title
          - Author(s)
          - URL or DOI (if available)
          - Publication date (approximate is fine)
          - A 2-3 sentence summary of why it's relevant

          List at least 5 articles/papers, prioritizing recency and relevance.
        output: { articles: text }

      - name: claude_search
        agent: |
          %model:claude/sonnet
          You are a research assistant. Search for recent, medium-to-long articles or research papers
          that will help with the continued development of "sase" (Structured Agentic Software Engineering),
          a Python toolkit for building and orchestrating AI agents.

          Focus areas include:
          - AI agent architectures and orchestration patterns
          - LLM tool use and function calling
          - Multi-agent systems and collaboration
          - Prompt engineering techniques and workflows
          - Developer tooling for AI-assisted software engineering
          - Code generation and automated programming research

          For each article/paper, provide:
          - Title
          - Author(s)
          - URL or DOI (if available)
          - Publication date (approximate is fine)
          - A 2-3 sentence summary of why it's relevant

          List at least 5 articles/papers, prioritizing recency and relevance.
        output: { articles: text }

      - name: codex_search
        agent: |
          %model:codex/o3
          You are a research assistant. Search for recent, medium-to-long articles or research papers
          that will help with the continued development of "sase" (Structured Agentic Software Engineering),
          a Python toolkit for building and orchestrating AI agents.

          Focus areas include:
          - AI agent architectures and orchestration patterns
          - LLM tool use and function calling
          - Multi-agent systems and collaboration
          - Prompt engineering techniques and workflows
          - Developer tooling for AI-assisted software engineering
          - Code generation and automated programming research

          For each article/paper, provide:
          - Title
          - Author(s)
          - URL or DOI (if available)
          - Publication date (approximate is fine)
          - A 2-3 sentence summary of why it's relevant

          List at least 5 articles/papers, prioritizing recency and relevance.
        output: { articles: text }

  - name: consolidate
    agent: |
      %model:claude/opus
      You are a research curator. Below are three lists of article/paper recommendations from different
      sources, all focused on resources for developing an AI agent orchestration toolkit called "sase"
      (Structured Agentic Software Engineering).

      ## Gemini's recommendations
      {{ search.gemini_search.articles }}

      ## Claude's recommendations
      {{ search.claude_search.articles }}

      ## Codex's recommendations
      {{ search.codex_search.articles }}

      Your tasks:
      1. **De-duplicate**: Merge the three lists, removing any articles/papers that appear in multiple lists.
         When duplicates exist, keep the entry with the most complete metadata.
      2. **Rank**: Order the consolidated list by relevance to building AI agent orchestration tools,
         with the most relevant and recent items first.
      3. **Recommend**: Choose the single BEST article/paper to read next and explain why in 2-3 sentences.

      Format your response as:

      ## Consolidated Reading List
      (Numbered list of all unique articles/papers with title, author, URL/DOI, date, and summary)

      ## Best Next Read
      **[Title]** by [Author]
      (Your 2-3 sentence recommendation explaining why this should be read first)
    output: { consolidated: text, recommendation: text }
```

## How it works

1. **Step `search`** is a `parallel:` step containing three nested agent steps. These run concurrently via
   `ThreadPoolExecutor`.
2. Each nested agent (`gemini_search`, `claude_search`, `codex_search`) uses `%model:provider/model` to target a
   different LLM provider.
3. The default `join: object` mode for parallel merges results into: `search.gemini_search.articles`,
   `search.claude_search.articles`, `search.codex_search.articles`.
4. **Step `consolidate`** is a sequential agent step that runs after `search` completes. It uses Jinja2 templates to
   inject all three result sets and produces the final curated list.

## Verification

After creating the file, verify the workflow is loadable:

```bash
.venv/bin/sase xprompt show reads
```

This should display the parsed workflow structure without errors.
