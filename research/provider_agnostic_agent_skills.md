# Research: Provider-Agnostic Agent Skills (Claude, Gemini, Codex)

Date: March 18, 2026

## Goal

Find a practical way to define one skill once and use it across Claude, Gemini, and Codex with minimal provider-specific
rewrites.

## Executive Summary

The strongest prior art points to a two-layer design:

1. Use **JSON Schema / OpenAPI-shaped tool contracts** as the canonical tool interface.
2. Use **MCP (Model Context Protocol)** as the canonical runtime transport for tools/resources/prompts where possible.

A single provider-agnostic skill format is realistic if you:

- keep a **portable schema subset**,
- separate **skill intent/instructions** from **provider bindings**,
- and compile to provider-specific configurations at build/load time.

## Prior Art

### 1. Protocol-level standards

#### MCP (Model Context Protocol)

- MCP defines a standard client/server protocol for tools, prompts, and resources over JSON-RPC.
- MCP tool definitions use `inputSchema` (JSON Schema), optional `outputSchema`, and tool discovery/invocation
  (`tools/list`, `tools/call`).
- Security model strongly emphasizes explicit consent and caution with untrusted tool metadata.

Why this matters:

- It is the clearest cross-vendor interoperability layer today for agent capabilities.
- It supports both local and remote tool hosting patterns.

### 2. Provider-native tool/function systems

#### OpenAI

- Function calling uses JSON Schema-defined tools and `tool_choice` controls (`auto`, `required`, forced, allowed
  subset).
- Structured outputs support a JSON Schema subset with strict validation behavior.
- OpenAI now supports remote MCP servers in Responses API tooling.

Portability signal:

- Strong alignment to schema-first tool definitions plus MCP connectivity.

#### Anthropic (Claude)

- Tool use requires `name`, `description`, and `input_schema` (JSON Schema).
- Supports parallel tool use controls and both client and server tool patterns.
- Claude API has an MCP connector for remote MCP servers (currently with explicit beta versioning/limitations).

Portability signal:

- Same schema-first pattern; MCP convergence is explicit.

#### Google Gemini

- Function declarations are defined with a subset of OpenAPI schema.
- Function calling modes (`AUTO`, `ANY`, `NONE`, preview `VALIDATED`) provide behavior control similar in spirit to
  tool-choice policies.
- Structured outputs also use JSON Schema subset semantics.
- Current docs/examples also show MCP bridging in SDK flows (`mcpToTool`).

Portability signal:

- Also schema-first; MCP interoperability is emerging in official examples.

### 3. Agent UX packaging prior art (skill/instruction layer)

#### Codex skills

- Skills are directory-based (`SKILL.md` + optional scripts/references) with progressive disclosure.
- Codex also uses `AGENTS.md` for layered instructions and supports MCP configuration.

#### Claude Code

- Reusable agent behavior is commonly packaged as subagents (`.claude/agents/*.md`) and custom slash commands
  (`.claude/commands/*.md`).
- MCP is first-class in Claude Code.

Observation:

- Instruction packaging is still vendor-specific, but tool contracts are converging around schema + MCP.

### 4. Framework-level prior art

- LangChain explicitly exposes standard model interfaces across providers and increasingly references MCP endpoints.
- PydanticAI positions itself as model-agnostic and supports multiple providers + MCP integration modes.

Observation:

- The ecosystem trend is consistent: abstract provider differences behind adapters while keeping tool contracts typed.

## Key Portability Frictions

1. Schema dialect mismatches

- OpenAI: JSON Schema subset in structured outputs.
- Gemini: subset of OpenAPI / JSON Schema behavior.
- Anthropic: JSON Schema input schemas with its own message/tool loop conventions.

2. Different tool loop/message semantics

- Tool response wiring differs (role/content block styles, call IDs, multi-call handling).

3. Instruction packaging differences

- Codex `SKILL.md` vs Claude subagent/command markdown structures vs Gemini project guidance conventions.

4. Runtime trust/security differences

- MCP server trust, approval flows, and data handling vary by client/provider.

## Potential Solutions

## Option A: MCP-first skills (recommended)

Define skills as:

- provider-agnostic instructions,
- MCP tool references (or local tool specs compiled to MCP),
- explicit policy and approval metadata.

Then adaptors map the same skill to:

- Codex: skill + AGENTS + MCP config
- Claude: subagent/command + MCP config
- Gemini: function/tool config or MCP bridge where available

Pros:

- Best long-term interoperability.
- Native fit for multi-tool, cross-client ecosystems.

Cons:

- Not every environment has equivalent MCP maturity/features yet.

## Option B: Canonical JSON-Schema tool manifest + per-provider adapters

Define one local `skill.yaml` format with strict portable schema subset and compile into:

- OpenAI tool definitions
- Anthropic tools
- Gemini function declarations

Pros:

- Immediate control and deterministic builds.

Cons:

- You maintain adapter code and edge-case handling.

## Option C: Instruction-only portability + provider-native tools

Keep shared markdown guidance identical, but implement tools separately per provider.

Pros:

- Fastest to start.

Cons:

- Duplicates high-value logic and drifts quickly.

## Recommended Architecture (A + B Hybrid)

Use **MCP as preferred runtime interface**, but keep an internal canonical manifest that can also compile directly to
provider-native tools.

### Canonical skill shape (proposed)

```yaml
id: repo.issue_triage
version: 0.1.0
intent: Triage GitHub issues and propose next actions
instructions:
  style: concise
  escalation: ask_before_destructive_actions
inputs_schema:
  type: object
  properties:
    repo: { type: string }
    issue_number: { type: integer }
  required: [repo, issue_number]
  additionalProperties: false
tools:
  - id: github.get_issue
    transport: mcp
    mcp_server: github
    mcp_tool: get_issue
  - id: github.list_comments
    transport: mcp
    mcp_server: github
    mcp_tool: list_issue_comments
policies:
  approvals:
    required_for:
      - write_actions
  network:
    allow_domains: ["api.github.com"]
outputs_schema:
  type: object
  properties:
    summary: { type: string }
    severity: { type: string, enum: [low, medium, high] }
    proposed_actions:
      type: array
      items: { type: string }
  required: [summary, severity, proposed_actions]
```

### Adapter responsibilities

1. Normalize schemas to a conservative shared subset.
2. Map tool-choice semantics (`auto/required/forced/allowed`) per provider.
3. Translate call/response envelopes and call IDs.
4. Enforce policy gates (approval, allow-lists, sensitive actions) outside model logic.
5. Run conformance tests across providers for each skill version.

## Portable Schema Subset (practical baseline)

Use only:

- `type`: `object`, `array`, `string`, `number`, `integer`, `boolean`, `null`
- `properties`, `required`, `enum`, `description`, `items`
- `additionalProperties: false` for closed objects

Avoid in portable core unless adapter-tested:

- deep combinators (`oneOf`/`allOf` heavy nesting), complex recursion, provider-specific extensions.

## Implementation Plan (incremental)

1. Define `skill.yaml` + JSON Schema validator in SASE.
2. Build three adapters:

- OpenAI tool emitter
- Anthropic tool emitter
- Gemini function declaration emitter

3. Add optional MCP binding resolver:

- if MCP available: prefer MCP path
- else: direct provider tool declarations

4. Add contract tests:

- same input fixture => equivalent tool calls across providers
- same mocked tool outputs => equivalent final structured output

5. Add a drift test in CI for each skill version.

## Risks

- Provider behavior drift over time (modes, schema subset, tool-loop behavior).
- Security regressions if approval policy is left to model-only prompting.
- False portability if advanced schema features silently degrade on one provider.

Mitigations:

- enforce a strict portable subset,
- compile-time + runtime validation,
- provider conformance test matrix.

## Bottom Line

Prior art strongly supports a **schema-first + MCP-aware** approach. The most robust path is to define skills in a
canonical internal format, then compile/adapt to provider-specific tool and instruction surfaces.

---

## Sources

- MCP specification: https://modelcontextprotocol.io/specification/draft
- MCP tools spec: https://modelcontextprotocol.io/specification/draft/server/tools
- MCP introduction: https://modelcontextprotocol.io/docs/getting-started/intro
- OpenAI function calling guide: https://developers.openai.com/api/docs/guides/function-calling
- OpenAI structured outputs guide: https://developers.openai.com/api/docs/guides/structured-outputs
- OpenAI MCP/connectors guide: https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- OpenAI Responses API updates (includes remote MCP note):
  https://openai.com/index/new-tools-and-features-in-the-responses-api/
- OpenAI function calling update note: https://help.openai.com/en/articles/8555517-function-calling-updates
- OpenAI Codex skills: https://developers.openai.com/codex/skills
- OpenAI Codex AGENTS.md guidance: https://developers.openai.com/codex/guides/agents-md
- OpenAI Codex MCP guidance: https://developers.openai.com/codex/mcp
- Anthropic tool use implementation: https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use
- Anthropic tool use overview: https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
- Anthropic MCP connector: https://platform.claude.com/docs/en/agents-and-tools/mcp-connector
- Anthropic agent SDK MCP docs: https://platform.claude.com/docs/en/agent-sdk/mcp
- Anthropic Claude Code subagents: https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Anthropic Claude Code slash commands: https://docs.anthropic.com/en/docs/claude-code/slash-commands
- Gemini function calling: https://ai.google.dev/gemini-api/docs/function-calling
- Gemini tools & agents: https://ai.google.dev/gemini-api/docs/tools
- Gemini structured outputs: https://ai.google.dev/gemini-api/docs/structured-output
- OpenAPI specification (latest): https://spec.openapis.org/oas/latest.html
- JSON Schema 2020-12: https://json-schema.org/draft/2020-12
- LangChain models (standard interfaces): https://docs.langchain.com/oss/javascript/langchain/models
- LangChain MCP endpoint docs: https://docs.langchain.com/langsmith/server-mcp
- PydanticAI model providers: https://ai.pydantic.dev/models/
- PydanticAI MCP overview: https://ai.pydantic.dev/mcp/overview/
- dot-ai (community cross-tool config generation): https://github.com/luisrudge/dot-ai
