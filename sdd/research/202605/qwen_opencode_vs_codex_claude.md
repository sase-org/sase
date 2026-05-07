# Qwen and OpenCode Versus Codex and Claude

Research date: 2026-05-07 (updated 2026-05-07 with second-pass benchmarks, open-weights findings,
parallel-agent economics, regional access, and risks of supporting these in SASE)

## Question

Why would a SASE user ever choose OpenCode or Qwen Code over Codex CLI or Claude Code?

## Short Answer

Use Codex or Claude as the default premium path. Use OpenCode or Qwen when the goal is not "best single agent" but
**runtime optionality**: cheaper parallel agents, model/vendor fallback, local or custom provider routing, open-weight
self-hosting, and a harness that SASE can automate through structured headless output.

The strongest reason to support both is strategic, not emotional: SASE should not make Claude and Codex the only
credible execution backends. OpenCode and Qwen give SASE an escape hatch when first-party agents are too expensive,
rate-limited, regionally unavailable, blocked by vendor policy, or simply not the right model for a given repository.

A second reason has emerged in 2026: **the gap between open-weight coding models and frontier closed models has
narrowed enough that "use Qwen" is no longer obviously a quality regression.** Qwen3.6-27B is reported to land within
~4 points of Claude Opus 4.6 on SWE-bench Verified, at a fraction of the active parameter count and under Apache-2.0
open weights. Even with normal benchmark caution, the trajectory is what matters for a multi-runtime tool like SASE.

## Bottom Line

| Runtime | Best reason to use it over Codex/Claude | Not a good reason |
| --- | --- | --- |
| OpenCode | Provider-agnostic agent harness: one CLI routes to Claude, OpenAI, Gemini, Qwen, OpenRouter, Fireworks, Ollama, LM Studio, or internal OpenAI-compatible endpoints — built on Vercel AI SDK + Models.dev (75+ providers). | Assuming it is automatically smarter than Claude Code or Codex on hard tasks. |
| Qwen Code | Coding-tuned open-source harness (Apache-2.0) with structured headless mode and an open-weight model story (Qwen3-Coder, Qwen3-Coder-Next, Qwen3.6 series) competitive with frontier closed models on SWE-bench. | Assuming the old free OAuth tier still exists; it ended 2026-04-15. |
| Codex | Best first-party path for OpenAI models, strong sandbox/approval model, ChatGPT subscription integration, local/cloud/IDE surfaces. | Provider diversity. |
| Claude Code | Best first-party path for Anthropic models, mature terminal workflow, MCP, custom agents, broad surfaces, strong coding ergonomics. | Avoiding Anthropic account/API dependency, or running offline/air-gapped. |

For the broader CLI-harness landscape (Goose, Cline, Crush, Cursor, Auggie, Amp, Copilot CLI, gptme, etc.) and SASE-fit
notes per harness, see the peer research: `sdd/research/202605/cli_agent_harnesses_for_sase.md`. This document is the
"why"; that one is the "what/how."

## OpenCode Case

OpenCode is useful because it is a model router plus agent harness, not because it replaces Claude or Codex as a model.
Its docs confirm OpenCode uses Vercel AI SDK and Models.dev to support 75+ LLM providers, including local models. The
CLI exposes the SASE-friendly surfaces the epic needs: `opencode run`, `--format json`, `--model provider/model`,
`--dir`, `--dangerously-skip-permissions`, plus `opencode serve` and `opencode acp` for future protocol-based
integration.

Practical reasons to use OpenCode over Codex/Claude:

- A SASE user can try `anthropic/claude-*`, `openai/gpt-*`, `google/gemini-*`, Qwen, OpenRouter, Fireworks, Ollama,
  LM Studio, or a company-internal OpenAI-compatible endpoint without SASE learning every provider's native CLI.
- If Claude or Codex has a bad week for a particular task class, SASE can reroute background agents through the same
  local orchestration model.
- For high-volume exploratory agents, OpenCode can route smaller/cheaper models while preserving the same SASE
  metadata, chat artifacts, hooks, and commit workflow.
- The client/server architecture (`opencode serve`/`--attach`) is especially relevant to SASE mobile/remote-control
  ideas: the agent can run on the developer machine while another client drives it.
- OpenCode is in the ACP Registry (Jan 2026 launch), which makes it a natural target for any future SASE ACP-backed
  provider.

A note on the repo: the project was originally at `sst/opencode` (SST team), and ownership has been transferred to a
new company, **Anomaly** — the canonical repo is now `anomalyco/opencode`, and `github.com/sst/opencode` redirects
there. There is also a separate community fork at `opencode-ai/opencode` with diverged history; SASE should target the
Anomaly-maintained repo, since it is the one tied to the documented CLI surface, ACP registry entry, and current
opencode.ai docs. The peer harness research file still uses the old `sst/opencode` URL — both resolve, but new
documentation should reference `anomalyco/opencode` directly so search and link rot stay manageable.

Why OpenCode rather than just "use OpenRouter through Codex"? Codex/Claude lock the harness to one vendor's agent loop,
prompt format, tool-use schema, and approval model. OpenCode replaces the *harness*, not just the model behind it —
which is the only way to compare agent loops fairly while holding the SASE wrapper constant.

Recommended SASE posture: support OpenCode as an opt-in built-in provider after Qwen, with conservative defaults and
explicit model strings. Do not make it the default over Claude or Codex. Its value is breadth, not guaranteed peak
model quality.

## Qwen Code Case

Qwen Code is useful when the desired axis is cost, control, regional reach, or open-model capability. The Qwen Code
README confirms Apache-2.0 license, says the project is based on Google Gemini CLI with parser-level adaptations for
Qwen-Coder models, and supports API keys from Alibaba Cloud Model Studio plus OpenAI/Anthropic/Gemini-compatible
providers. The headless docs expose `qwen -p`, `--output-format json|stream-json`, `--yolo`, `--approval-mode`, and
resume flags — close to ideal for SASE subprocess integration.

The model side has shifted in 2026 enough to matter. Reported figures from Alibaba's Qwen team:

- **Qwen3-Coder** flagship (480B MoE, 35B active, 256K native / 1M extended context): trained for agentic coding and
  tool use.
- **Qwen3-Coder-Next** (~80B-class hybrid open-weight, ~3B active during inference, Apache-2.0): >70% SWE-Bench
  Verified using the SWE-Agent scaffold; 70.6% SWE Bench Resolved and 44.3% SWE Bench Pro per the team's reporting,
  comparable to models with 10×–20× more active parameters.
- **Qwen3.6-27B** (released 2026-04-22, dense, Apache-2.0): reported 77.2% SWE-bench Verified, ~3.7 points behind
  Claude Opus 4.6 (80.8%) at a fraction of the active parameter footprint.

These deltas are vendor-reported and should be taken with normal benchmark caution, but the direction is what matters
for SASE: open-weight coding models are now in the same conversation as frontier closed models for many tasks SASE
agents do — planning, exploration, code review, scaffolding, refactor, test writing. Premium Codex/Claude is still
the right choice for the hardest end-to-end implementation runs; Qwen is increasingly defensible for everything else.

Practical reasons to use Qwen over Codex/Claude:

- Run cheaper background exploration, code review, documentation, and phase-agent work where premium Claude/Codex
  spend is not justified — exactly the SASE multi-phase epic-work pattern.
- Use open-weight or self-hosted coding models when privacy, geography, cost, or availability make first-party vendors
  a poor fit.
- Keep a coding-agent path available for users who cannot or will not use OpenAI or Anthropic accounts (corporate
  policy, regional access, or personal preference).
- Evaluate Qwen models behind the same SASE hooks, skills, prompt handling, workspaces, telemetry, and commit workflow
  instead of asking users to leave SASE.
- The 256K-native / 1M-extended context envelope of Qwen3-Coder is appealing for larger monorepo tasks where Claude's
  context window or Codex's effective working set is a real constraint.

The caveat is important: the old Qwen OAuth free tier ended 2026-04-15. The current path is API keys, Alibaba Cloud
Coding Plan, OpenRouter, Fireworks, or compatible providers. Qwen is a cost/control option, not a free lunch.

Recommended SASE posture: implement Qwen first because the headless `stream-json` contract is closer to the existing
Claude-style parser (Qwen Code is built on Gemini CLI with Qwen-coder parser tweaks) and the model story is
differentiated. Keep autodetection below Claude/Codex or opt-in until real runtime validation proves it is smooth.

## Open Weights and Self-Hosting

This is the axis where Codex and Claude have no answer at all. Closed-weight models cannot be:

- Served from on-prem GPUs for privacy/regulated workloads.
- Run from a laptop on a flight without internet.
- Frozen at a specific version while a vendor deprecates older snapshots underneath you.
- Audited at the weights/training-data level.
- Run inside an air-gapped corporate environment.

Qwen3-Coder-Next and Qwen3.6-27B ship under Apache-2.0 with full weights on Hugging Face. Pairing those with OpenCode's
Ollama / LM Studio / custom-OpenAI-compatible support gives SASE users a credible fully-local agent path, which is
impossible with Codex or Claude Code. For SASE's ambitions around mobile/remote-control, multi-machine sync, and varied
user environments, that "no first-party vendor required" path is structurally important even if most users never use
it.

## Cost and Parallel-Agent Economics

SASE's epic-work automation routinely launches multiple phase agents per epic, plus optional reviewer agents. The cost
ratio between premium and budget tiers compounds quickly:

- Premium Codex/Claude per-token rates dominate when each phase agent does long context-laden tool-use loops.
- Qwen via Alibaba Coding Plan, OpenRouter, Fireworks, or a self-host generally lands at a meaningful discount per
  million tokens and per agent-hour, for code-comparable but not strictly equal quality.
- OpenCode lets SASE pin a "frontier" model for the *land* phase (final integration) and a budget Qwen / local model
  for the per-phase exploration and lint-fix passes.

The right framing is not "Qwen replaces Claude" but **"SASE should be able to spend like a portfolio."** A 5-phase
epic that costs $X on pure Claude can plausibly cost a small fraction of $X on Qwen-for-phases plus Claude-for-land,
with most of the quality preserved on the only step that has to be perfect. The same logic applies to mentor /
reviewer / explorer agents: cheap models are fine for the breadth-first work, and SASE benefits exactly the moment it
stops paying premium rates for low-stakes runs.

## Geographic and Regulatory Access

- Anthropic's API and Claude Code are not equally available in every region, and some enterprise environments block
  them.
- OpenAI's API/ChatGPT have similar variability and regional rate-limit behavior.
- Qwen via Alibaba Cloud is the dominant option in mainland China and broadly available elsewhere through OpenRouter
  and Fireworks.
- Self-hosted Qwen via Ollama / vLLM / a private inference endpoint works regardless of vendor regional policy.

For SASE users in those situations, "Codex or Claude" is not actually a choice. Qwen + OpenCode is the only path that
lets them run SASE at all without forcing them into a non-supported workflow.

## When I Would Actually Pick These

I would pick **OpenCode** over Codex/Claude when:

- I want to compare models while keeping one agent harness constant.
- I need a model/provider not supported cleanly by Codex or Claude.
- I want local models or internal API gateways in the same workflow.
- I want to run many low-cost SASE agents in parallel and reserve Claude/Codex for final implementation or review.
- I want to experiment with a long-running server/remote-control architecture (`opencode serve`, ACP) later.

I would pick **Qwen** over Codex/Claude when:

- I want a Qwen coding model specifically — Qwen3-Coder for huge-context monorepos, Qwen3-Coder-Next for self-hosted
  agentic coding, Qwen3.6-27B for "near-frontier on Apache-2.0 weights."
- I need an open-weight fallback path for coding agents (privacy, air-gap, audit).
- I want a headless, structured CLI that SASE can wrap without inventing a custom model client.
- I am doing exploratory or batch work where "good enough and cheap" beats "best available and expensive."
- My region or corporate policy makes OpenAI/Anthropic awkward or unavailable.

I would stay with **Codex/Claude** when:

- The task is high-value and I care most about first-attempt quality on the hardest implementation pass.
- The user already pays for ChatGPT/Claude and wants the native experience.
- The workflow depends on the first-party agent's own cloud, IDE, app, permissions, or enterprise features.
- The organization wants fewer auth/config surfaces.

## Risks and Costs of Supporting These in SASE

Adding Qwen and OpenCode is not free. Honest tradeoffs the previous draft did not cover:

- **More parser shapes.** Qwen `stream-json`, OpenCode `--format json`, Claude/Codex stream-JSON variants, and
  Gemini's events all differ. Each carries a maintenance tail.
- **More auth surfaces.** Qwen API keys, Alibaba Coding Plan, OpenRouter keys, Fireworks keys, OpenCode's `auth.json`,
  Models.dev refresh, plus the closed-vendor flows. Setup-docs surface area roughly doubles.
- **More skill-deploy paths and shadow-home decisions.** Both providers may need shadow-home isolation if they mutate
  global config during headless runs (the epic's Phase 1/2 explicitly leaves this open until inspection).
- **More upstream-churn exposure.** OpenCode just transferred from SST to Anomaly. Qwen Code rebases on Gemini CLI
  changes. Both move faster than Claude Code or Codex CLI.
- **Quality regressions are real and silent.** A user who ran the same prompt on Claude yesterday and on Qwen today
  through the same SASE wrapper may attribute Qwen output to "SASE got worse." Defaults and docs need to make the
  model choice explicit and visible (provider suffix in agent names, ACE display, telemetry labels).

The mitigations are the principles the epic already states: keep providers thin, prefer structured output, do not
autodetect Qwen/OpenCode above Claude/Codex, and document caveats in `docs/llms.md`.

## SASE Product Implication

The epic should frame Qwen and OpenCode as **provider expansion**, not a challenge to Codex/Claude. The user-facing
pitch should be:

> "Claude and Codex remain the premium defaults. Qwen and OpenCode let SASE run the same workflow on cheaper, open,
> local, or alternate-provider models when that tradeoff is better — including fully-local self-hosted runs that no
> closed vendor can offer."

That is a good reason to build this. It makes SASE less brittle, more cost-aware, regionally accessible, and useful
for users who want agent orchestration rather than loyalty to a single model vendor.

## Implementation Notes for the Current Epic

- Keep both providers thin and use the existing `LLMProvider` hooks.
- Prefer structured output: Qwen `stream-json`, OpenCode `--format json`.
- Do not add runtime-specific SASE behavior beyond command construction, parsing, binary overrides, model aliases, and
  auth/config documentation.
- Do not autodetect OpenCode above Claude/Codex. OpenCode's value is explicit model choice.
- Treat nested OpenCode model IDs (`opencode/<provider/model>`) as a first-class test case.
- Document Qwen's OAuth-free-tier removal (2026-04-15) in `docs/llms.md` and setup docs.
- Document the OpenCode `sst/opencode` → `anomalyco/opencode` repo transfer so users searching old links land on the
  right project.
- Use fake CLI fixtures for CI, then record manual smoke results with `qwen --version` and `opencode --version`.
- Cross-reference `cli_agent_harnesses_for_sase.md` for the broader CLI-harness landscape.

## Sources

- OpenCode docs landing page (overview, open-source positioning), checked 2026-05-07: <https://opencode.ai/docs/>
- OpenCode CLI docs, checked 2026-05-07: `opencode run`, `--format json`, `--model provider/model`, `--dir`,
  `--dangerously-skip-permissions`, `serve`, and `acp`: <https://opencode.ai/docs/cli/>
- OpenCode providers docs, checked 2026-05-07: AI SDK, Models.dev, 75+ providers, local models, and auth path:
  <https://opencode.ai/docs/providers/>
- OpenCode repository: `https://github.com/sst/opencode` redirects to <https://github.com/anomalyco/opencode> after the
  transfer to Anomaly. Separate community fork (diverged history): <https://github.com/opencode-ai/opencode>.
- OpenCode configuration / providers references on DeepWiki, checked 2026-05-07:
  <https://deepwiki.com/sst/opencode/3-configuration-system>,
  <https://deepwiki.com/sst/opencode/4.4-supported-providers>
- Models.dev (open model/provider database used by OpenCode), checked 2026-05-07: <https://models.dev/>
- Qwen Code repo (Apache-2.0, Gemini-CLI lineage, OAuth-free-tier removal, auth options, OpenAI/Anthropic/Gemini-
  compatible protocol support, `~/.qwen/settings.json`), checked 2026-05-07: <https://github.com/QwenLM/qwen-code>
- Qwen Code headless docs (`qwen -p`, JSON/stream-JSON output, `--yolo`, approval mode, stdin, resume flags), checked
  2026-05-07: <https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/>
- Qwen3-Coder announcement (model size, context, agentic coding/tool-use claims, Qwen Code relationship), checked
  2026-05-07: <https://qwenlm.github.io/blog/qwen3-coder/>
- Qwen3-Coder-Next blog (open-weight ~80B-class hybrid for coding agents, SWE-bench numbers), checked 2026-05-07:
  <https://qwen.ai/blog?id=qwen3-coder-next>
- Qwen3-Coder-Next technical report (arxiv, submitted 2026-02-28), checked 2026-05-07:
  <https://arxiv.org/abs/2603.00729>
- Qwen3-Coder-Next Hugging Face model card (Apache-2.0 open weights), checked 2026-05-07:
  <https://huggingface.co/Qwen/Qwen3-Coder-Next>
- Qwen3.6-27B blog (2026-04-22 release, 77.2% SWE-bench Verified, Apache-2.0), checked 2026-05-07:
  <https://qwen.ai/blog?id=qwen3.6-27b>
- Qwen3.6-27B Hugging Face model card, checked 2026-05-07: <https://huggingface.co/Qwen/Qwen3.6-27B>
- OpenAI Codex CLI help, checked 2026-05-07: local coding agent, approval modes, model defaults, ChatGPT/API access:
  <https://help.openai.com/en/articles/11096431-openai-codex-ci-getting-started>
- OpenAI Codex in ChatGPT help, checked 2026-05-07: Codex surfaces and plan availability:
  <https://help.openai.com/en/articles/11369540-codex-in-chatgpt>
- Claude Code overview, checked 2026-05-07: terminal/IDE/cloud surfaces, MCP, custom agents, broader workflow support:
  <https://code.claude.com/docs/en/overview>
- Claude Code headless docs, checked 2026-05-07: `--print`, structured output, stream-json automation:
  <https://docs.claude.com/en/docs/claude-code/sdk/sdk-headless>
- Peer SASE research on the broader CLI-agent harness landscape (OpenCode, Qwen, Goose, Cline, Crush, Cursor, Auggie,
  Amp, Copilot CLI, gptme, etc.): `sdd/research/202605/cli_agent_harnesses_for_sase.md`
