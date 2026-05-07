# Qwen and OpenCode Versus Codex and Claude

Research date: 2026-05-07

## Question

Why would a SASE user ever choose OpenCode or Qwen Code over Codex CLI or Claude Code?

## Short Answer

Use Codex or Claude for the default premium path. Use OpenCode or Qwen when the goal is not "best single agent" but
runtime optionality: cheaper parallel agents, model/vendor fallback, local or custom provider routing, and a harness that
SASE can automate through structured headless output.

The strongest reason to support both is strategic rather than emotional: SASE should not make Claude and Codex the only
credible execution backends. OpenCode and Qwen give SASE an escape hatch when first-party agents are too expensive,
rate-limited, unavailable for a user, blocked by vendor policy, or simply not the right model for a given repository.

## Bottom Line

| Runtime | Best reason to use it over Codex/Claude | Not a good reason |
| --- | --- | --- |
| OpenCode | Provider-agnostic agent harness: one CLI can route to Claude, OpenAI, Gemini, Qwen, local models, and custom OpenAI-compatible endpoints. | Assuming it is automatically smarter than Claude Code or Codex on hard tasks. |
| Qwen Code | Qwen-optimized open-source coding harness with structured headless mode, strong open/open-weight coding model story, and lower-cost/self-hostable paths. | Assuming the old free OAuth tier still exists; it ended on 2026-04-15. |
| Codex | Best first-party path for OpenAI models, strong sandbox/approval model, ChatGPT subscription integration, and local/cloud/IDE surfaces. | Provider diversity. |
| Claude Code | Best first-party path for Anthropic models, mature terminal workflow, MCP, custom agents, broad surfaces, and strong coding ergonomics. | Avoiding Anthropic account/API dependency. |

## OpenCode Case

OpenCode is useful because it is a model router plus agent harness, not because it replaces Claude or Codex as a model.
Its docs say OpenCode uses AI SDK and Models.dev for 75+ LLM providers and supports local models. Its CLI also exposes
the exact SASE-friendly surfaces the epic needs: `opencode run`, `--format json`, `--model provider/model`, `--dir`, and
`--dangerously-skip-permissions`. It also has `opencode serve` and `opencode acp`, which create future paths for lower
cold-start overhead and protocol-based integration.

The practical reason to use OpenCode over Codex/Claude is provider portability:

- A SASE user can try `anthropic/claude-*`, `openai/gpt-*`, `google/gemini-*`, Qwen, OpenRouter, Fireworks, Ollama,
  LM Studio, or a company-internal OpenAI-compatible endpoint without SASE learning every provider's native CLI.
- If Claude or Codex has a bad week for a particular task class, SASE can reroute background agents through the same
  local orchestration model.
- For high-volume exploratory agents, OpenCode can route smaller/cheaper models while preserving the same SASE metadata,
  chat artifacts, hooks, and commit workflow.
- The client/server architecture is especially relevant to SASE mobile/remote-control ideas: the agent can run on the
  developer machine while another client drives it.

Recommended SASE posture: support OpenCode as an opt-in built-in provider after Qwen, with conservative defaults and
explicit model strings. Do not make it the default over Claude or Codex. Its value is breadth, not guaranteed peak model
quality.

## Qwen Code Case

Qwen Code is useful when the desired axis is cost/control/open-model capability. The Qwen Code README says it supports
API keys from Alibaba Cloud Model Studio or supported providers, including OpenAI-compatible endpoints, Anthropic, and
Google GenAI protocols. The headless docs expose `qwen -p`, `--output-format json|stream-json`, `--yolo`,
`--approval-mode`, and resume flags, which are close to ideal for SASE subprocess integration.

The model-side reason is stronger than "another wrapper." Qwen's own Qwen3-Coder announcement describes the flagship
480B MoE coding model with 35B active parameters, 256K native context, 1M extended context, and agentic coding/tool-use
training. The 2026 Qwen3-Coder-Next technical report describes an open-weight 80B model activating 3B parameters during
inference, specialized for coding agents, and competitive relative to its active parameter count. That matters for SASE
because many SASE workflows want lots of agents, not one expensive perfect agent.

The practical reason to use Qwen over Codex/Claude:

- Run cheaper background exploration, code review, documentation, and phase-agent work where premium Claude/Codex spend
  is not justified.
- Use open-weight or self-hosted coding models when privacy, geography, cost, or availability make first-party vendors a
  poor fit.
- Keep a coding-agent path available for users who cannot or will not use OpenAI or Anthropic accounts.
- Evaluate Qwen models behind the same SASE hooks, skills, prompt handling, workspaces, telemetry, and commit workflow
  instead of asking users to leave SASE.

The caveat is important: the old Qwen OAuth free tier is gone as of 2026-04-15. The current path is API keys, Alibaba
Cloud Coding Plan, OpenRouter, Fireworks, or compatible providers. That makes Qwen a cost/control option, not a free
lunch.

Recommended SASE posture: implement Qwen first because the headless `stream-json` contract is closer to the existing
Claude-style parser and the model story is differentiated. Keep autodetection below Claude/Codex or opt-in until real
runtime validation proves it is smooth.

## When I Would Actually Pick These

I would pick OpenCode over Codex/Claude when:

- I want to compare models while keeping one agent harness constant.
- I need a model/provider not supported cleanly by Codex or Claude.
- I want local models or internal API gateways in the same workflow.
- I want to run many low-cost SASE agents in parallel and reserve Claude/Codex for final implementation or review.
- I want to experiment with a long-running server/remote-control architecture later.

I would pick Qwen over Codex/Claude when:

- I want a Qwen coding model specifically, especially for cost-sensitive or self-hostable background work.
- I need an open-weight fallback path for coding agents.
- I want a headless, structured CLI that SASE can wrap without inventing a custom model client.
- I am doing exploratory or batch work where "good enough and cheap" beats "best available and expensive."

I would stay with Codex/Claude when:

- The task is high-value and I care most about first-attempt quality.
- The user already pays for ChatGPT/Claude and wants the native experience.
- The workflow depends on the first-party agent's own cloud, IDE, app, permissions, or enterprise features.
- The organization wants fewer auth/config surfaces.

## SASE Product Implication

The epic should frame Qwen and OpenCode as provider expansion, not as a challenge to Codex/Claude. The user-facing pitch
should be:

"Claude and Codex remain the premium defaults. Qwen and OpenCode let SASE run the same workflow on cheaper, open, local,
or alternate-provider models when that tradeoff is better."

That is a good reason to build this. It makes SASE less brittle, more cost-aware, and more useful for users who want
agent orchestration rather than loyalty to a single model vendor.

## Implementation Notes for the Current Epic

- Keep both providers thin and use the existing `LLMProvider` hooks.
- Prefer structured output: Qwen `stream-json`, OpenCode `--format json`.
- Do not add runtime-specific SASE behavior beyond command construction, parsing, binary overrides, model aliases, and
  auth/config documentation.
- Do not autodetect OpenCode above Claude/Codex. OpenCode's value is explicit model choice.
- Treat nested OpenCode model IDs (`opencode/<provider/model>`) as a first-class test case.
- Document Qwen's OAuth-free-tier removal in `docs/llms.md` and setup docs.
- Use fake CLI fixtures for CI, then record manual smoke results with `qwen --version` and `opencode --version`.

## Sources

- OpenCode CLI docs, checked 2026-05-07: `opencode run`, `--format json`, `--model provider/model`, `--dir`,
  `--dangerously-skip-permissions`, `serve`, and `acp`: <https://dev.opencode.ai/docs/cli/>
- OpenCode providers docs, checked 2026-05-07: AI SDK, Models.dev, 75+ providers, local models, and auth path:
  <https://opencode.ai/docs/providers/>
- OpenCode repository README, checked 2026-05-07: open-source agent, provider-agnostic positioning, client/server notes,
  and current project activity: <https://github.com/anomalyco/opencode>
- Models.dev, checked 2026-05-07: open model/provider database used by OpenCode: <https://models.dev/>
- Qwen Code README, checked 2026-05-07: OAuth free-tier removal, auth options, OpenAI-compatible/Anthropic/Google GenAI
  protocol support, and `~/.qwen/settings.json`: <https://github.com/QwenLM/qwen-code/blob/main/README.md>
- Qwen Code headless docs, checked 2026-05-07: `qwen -p`, JSON/stream-JSON output, `--yolo`, approval mode, stdin, and
  resume flags: <https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/>
- Qwen3-Coder announcement, checked 2026-05-07: model size, context, agentic coding/tool-use claims, and Qwen Code
  relationship: <https://qwenlm.github.io/blog/qwen3-coder/>
- Qwen3-Coder-Next technical report, submitted 2026-02-28, checked 2026-05-07: open-weight coding-agent model and
  active-parameter efficiency: <https://arxiv.org/abs/2603.00729>
- OpenAI Codex CLI help, checked 2026-05-07: local coding agent, approval modes, model defaults, and ChatGPT/API access:
  <https://help.openai.com/en/articles/11096431-openai-codex-ci-getting-started>
- OpenAI Codex in ChatGPT help, checked 2026-05-07: Codex surfaces and plan availability:
  <https://help.openai.com/en/articles/11369540-codex-in-chatgpt>
- Claude Code overview, checked 2026-05-07: terminal/IDE/cloud surfaces, MCP, custom agents, and broader workflow
  support: <https://code.claude.com/docs/en/overview>
- Claude Code headless docs, checked 2026-05-07: `--print`, structured output, and stream-json automation:
  <https://docs.claude.com/en/docs/claude-code/sdk/sdk-headless>
