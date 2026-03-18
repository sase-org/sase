# Provider-Agnostic Agent Skills

Research into defining agent skills in a way that works across Claude, Gemini, Codex, and other LLM providers.

## The Emerging Industry Stack

The industry is converging on a three-layer architecture, all governed under the **Agentic AI Foundation (AAIF)** at the
Linux Foundation (founded Dec 2025 by Anthropic, OpenAI, Google, Microsoft, AWS, and others):

| Layer                | Protocol                         | Purpose                                                   |
| -------------------- | -------------------------------- | --------------------------------------------------------- |
| Tool connectivity    | **MCP** (Model Context Protocol) | Server-side tool definitions, provider-agnostic by design |
| Capability packaging | **Agent Skills** (SKILL.md)      | Portable prompt-based instructions + scripts              |
| Agent coordination   | **A2A** (Agent2Agent Protocol)   | Multi-agent orchestration across providers                |

## 1. Agent Skills Open Standard (agentskills.io)

Released December 2025 by Anthropic. Adopted by Claude Code, OpenAI Codex, Gemini CLI, GitHub Copilot, Cursor, VS Code,
and 20+ other platforms.

### How It Works

Skills are directories containing a `SKILL.md` file plus optional supporting directories:

```
my-skill/
  SKILL.md          # YAML frontmatter + markdown instructions
  scripts/          # Optional helper scripts
  references/       # Optional reference files
  assets/           # Optional assets
```

Frontmatter fields:

```yaml
---
name: my-skill # required, 1-64 chars, lowercase+hyphens
description: Does X # required, max 1024 chars
license: MIT # optional
compatibility: # optional
  - claude-code
  - codex
  - gemini-cli
metadata: # optional
  tags: [testing, ci]
allowed-tools: # optional
  - Bash
  - Read
---
Markdown instructions for the agent go here...
```

### Progressive Disclosure

Skills use three tiers to minimize context window usage:

1. **Startup**: Only frontmatter metadata loaded (~100 tokens)
2. **Activation**: Full SKILL.md instructions injected when skill is triggered (<5000 tokens recommended)
3. **On-demand**: Reference files loaded only when the agent needs them

### How Agents Execute Skills

The host application has a single `Skill` tool whose description is dynamically generated from all available skill
frontmatter. When the agent invokes the Skill tool, the system injects the full SKILL.md instructions into the
conversation context. The skill then modifies execution context (allowed tools, model override, etc.) for its duration.

### Pros

- Truly portable (just text files, no API dependency)
- Version-controllable, composable
- Easy to author (markdown + YAML)
- Already adopted by all major coding agents

### Cons

- Skills are instructions, not executable tool definitions -- they tell the agent _how_ to do something rather than
  defining a callable API
- Depends on the agent's built-in tools for actual execution
- No formal type system for inputs/outputs
- Skill selection is LLM-driven (no algorithmic routing)
- Higher token overhead per invocation (~1500+ tokens vs ~100 tokens for API tool definitions)

### References

- [Agent Skills Specification](https://agentskills.io/specification)
- [Agent Skills GitHub](https://github.com/agentskills/agentskills)

## 2. Model Context Protocol (MCP)

Open protocol by Anthropic (Nov 2024) using JSON-RPC 2.0 over stdio/HTTP+SSE/WebSocket. Donated to AAIF in Dec 2025.

### Architecture

- **Hosts**: LLM applications (Claude Desktop, IDE, etc.)
- **Clients**: Connectors inside hosts
- **Servers**: Tool/data providers (run as separate processes)

### Tool Definition Format

```json
{
  "name": "calculate_sum",
  "description": "Add two numbers",
  "inputSchema": {
    "type": "object",
    "properties": {
      "a": { "type": "number" },
      "b": { "type": "number" }
    },
    "required": ["a", "b"]
  }
}
```

Server primitives beyond tools: **Resources** (data/context) and **Prompts** (templated messages).

### Provider Support

| Provider                 | Status                       |
| ------------------------ | ---------------------------- |
| Claude (Anthropic)       | Native (creator)             |
| OpenAI (ChatGPT, Codex)  | Native (adopted March 2025)  |
| Google (Gemini CLI, ADK) | Native                       |
| Microsoft (Copilot)      | Native (via Semantic Kernel) |
| Cursor, VS Code          | Native                       |

### How It Achieves Provider-Agnosticism

MCP defines tools **server-side**. The MCP client (in the host application) translates from MCP's `inputSchema` into
whatever the LLM provider expects. The server author never needs to know which LLM provider the host uses.

### Pros

- True industry standard with broad adoption
- Model-agnostic by design
- Growing ecosystem of pre-built servers
- Separates tool definition from tool invocation

### Cons

- Heavier than function calling for basic use cases (requires running a server process)
- Protocol encompasses more than just tools (resources, prompts, sampling)

### References

- [MCP Specification](https://modelcontextprotocol.io/specification/2025-11-25)
- [Wikipedia - MCP](https://en.wikipedia.org/wiki/Model_Context_Protocol)

## 3. Provider Tool Format Differences

All three major providers use JSON Schema underneath, but the wrapping differs:

### Claude

```json
{
  "name": "get_weather",
  "description": "Get weather for a location",
  "input_schema": {
    "type": "object",
    "properties": {
      "location": { "type": "string" }
    },
    "required": ["location"]
  }
}
```

### OpenAI

```json
{
  "type": "function",
  "function": {
    "name": "get_weather",
    "description": "Get weather for a location",
    "parameters": {
      "type": "object",
      "properties": {
        "location": { "type": "string" }
      },
      "required": ["location"],
      "additionalProperties": false
    },
    "strict": true
  }
}
```

### Gemini

```json
{
  "name": "get_weather",
  "description": "Get weather for a location",
  "parameters": {
    "type": "OBJECT",
    "properties": {
      "location": { "type": "STRING" }
    },
    "required": ["location"]
  }
}
```

### Key Differences Summary

| Aspect                | Claude                      | OpenAI                                            | Gemini                        |
| --------------------- | --------------------------- | ------------------------------------------------- | ----------------------------- |
| Schema field name     | `input_schema`              | `parameters` (nested under `function`)            | `parameters`                  |
| Type case             | lowercase                   | lowercase                                         | UPPERCASE                     |
| Wrapper               | flat                        | wrapped in `{"type":"function","function":{...}}` | flat                          |
| Arguments in response | parsed object               | JSON string (must parse)                          | parsed object                 |
| Result format         | `tool_result` content block | `tool` role message                               | function response part        |
| Stop signal           | `stop_reason: "tool_use"`   | `finish_reason: "tool_calls"`                     | check for `functionCall` part |

## 4. Multi-Provider Frameworks

### LangChain / LangGraph

Tools are Python functions with type annotations. Auto-generates schemas from signatures. Same tool works with OpenAI,
Claude, Gemini, and open-source models. LangGraph adds graph-based multi-agent orchestration.

### LlamaIndex

`FunctionTool` wraps Python functions with automatic schema generation. Clean `Tool` interface (name, description,
schema, callable). Primarily focused on retrieval-augmented workflows.

### Microsoft Semantic Kernel / Agent Framework

Uses "Plugins" with `Microsoft.Extensions.AI` as the abstraction layer. Supports OpenAI, Claude, Gemini, Llama, Mistral.
Combined with AutoGen in 2025.

### OpenAI Agents SDK

`FunctionTool` with automatic schema generation and Pydantic validation. Documents paths for non-OpenAI models. MCP
integration built in.

### Google Agent Development Kit (ADK)

Supports function tools, OpenAPI specs, MCP tools, and LangChain tools. Model-agnostic, deployment-agnostic.

### Spring AI (Java)

Implements Agent Skills open standard in Java. Define once, use with any supported model.

## 5. Prior Art

### OpenAPI / Swagger

OpenAPI specs can be auto-converted into LLM tool definitions. Gemini's function schema is explicitly based on OpenAPI
3.0. Tools like `openapi-llm` and Gentoro convert OpenAPI specs into MCP servers. Massive existing ecosystem but
designed for HTTP APIs, not arbitrary tool execution.

### Language Server Protocol (LSP)

Direct architectural inspiration for MCP. Both use JSON-RPC 2.0, capability negotiation, and client-server model. LSP
standardized IDE-language server interaction; MCP standardizes LLM-tool interaction.

### ToolRegistry (Academic)

2025 research paper proposing a four-layer architecture: protocol adapters, registry management, execution engine, API
compatibility layer. Demonstrates 60-80% code reduction. Uses adapter pattern to normalize MCP, OpenAPI, LangChain, and
native Python tools into a unified `Tool` abstraction.

- [ToolRegistry paper (arXiv 2508.02979)](https://arxiv.org/abs/2508.02979)

## 6. Relevance to sase

### Current State

sase already has a skill system (**xprompts**) with two flavors:

- **XPrompt parts** (`.md` files): Single-step prompt templates with YAML frontmatter
- **XPrompt workflows** (`.yml` files): Multi-step orchestrations with agent/bash/python/prompt_part steps, control
  flow, parallel execution, HITL checkpoints, typed inputs, and output validation

sase also has a provider abstraction (`LLMProvider` ABC) with Claude, Codex, and Gemini implementations, plus a `%model`
directive system for runtime provider selection.

### Gaps

1. **No skill composition API** -- skills defined in YAML, loaded from files only
2. **No dynamic skill registration** -- skills must exist on disk or in plugins
3. **Limited input typing** -- simple types (word, line, text, path, int, bool, float)
4. **No skill provider abstraction** -- xprompts don't separate "what the skill does" from "how the agent executes it"
5. **No standard format interop** -- can't consume Agent Skills (SKILL.md) or MCP tools

### Potential Approaches

**Option A: Adopt Agent Skills (SKILL.md) as a supported xprompt source**

Map SKILL.md files to xprompt parts. The sase loader would discover SKILL.md files and convert their frontmatter +
content into `XPrompt` objects. This gives immediate cross-platform compatibility since the same skill files work in
Claude Code, Codex, Gemini CLI, etc.

Mapping:

- `name` -> xprompt name
- `description` -> xprompt description
- `allowed-tools` -> could influence workflow step types
- Body content -> prompt_part content

**Option B: Add MCP client support**

Let xprompt workflows call MCP tools. Add an `mcp` step type to workflows that connects to an MCP server and invokes
tools. This makes sase workflows composable with the broader MCP ecosystem without changing the xprompt format itself.

```yaml
steps:
  - name: search_codebase
    mcp:
      server: filesystem
      tool: search_files
      args:
        pattern: "*.py"
        path: "{{ project_dir }}"
```

**Option C: Define a canonical tool schema with provider adapters**

Create a sase-native tool definition format (JSON Schema-based, like MCP's `inputSchema`) and write thin adapters that
convert it to Claude/OpenAI/Gemini formats. This is essentially what the ToolRegistry paper proposes.

```yaml
tools:
  - name: run_tests
    description: Run the project test suite
    input_schema:
      type: object
      properties:
        path:
          type: string
          description: Test file or directory
        verbose:
          type: boolean
          default: false
    execute:
      bash: "pytest {{ path }} {% if verbose %}-v{% endif %}"
```

**Option D: Hybrid (recommended)**

- Support SKILL.md discovery alongside `.md`/`.yml` xprompts (Option A) for maximum portability
- Add MCP client integration (Option B) so workflows can call any MCP tool
- Keep the xprompt workflow format as the "full power" orchestration layer since it already has features (control flow,
  parallel execution, HITL, output validation) that neither SKILL.md nor MCP provide
- Use sase's existing provider adapter layer to handle the API-level format translation
