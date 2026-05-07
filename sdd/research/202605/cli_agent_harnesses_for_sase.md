# CLI Agent Harnesses to Consider for SASE

Research date: 2026-05-07

## Question

SASE already has first-class agent runtime support for Claude Code, Codex CLI, Gemini CLI, and plugin-provided Jetski.
What other CLI agent harnesses are worth considering, and which ones look easiest or most strategic to integrate through
SASE's `LLMProvider` plugin boundary?

## SASE Fit Criteria

The most useful SASE runtime candidates have:

1. A non-interactive command suitable for `subprocess.Popen()`.
2. Structured output, preferably JSON or NDJSON with a clear terminal result event.
3. A way to allow edits and shell commands without interactive confirmations inside SASE-managed workspaces.
4. Model/provider selection by CLI flag or environment.
5. Stable session/resume controls or a documented stateless mode.
6. A predictable config/instruction/skill location that SASE can populate or isolate.
7. Reasonable odds of still existing and being maintained a year from now.

## Shortlist

| Candidate | Integration surface | Why it matters | SASE fit |
| --- | --- | --- | --- |
| OpenCode | `opencode run`, `opencode serve`, JSON events | Open-source, multi-provider terminal agent with non-interactive and server modes. | High |
| Qwen Code | `qwen -p`, `--output-format json/stream-json`, `--yolo` | Gemini-derived open-source harness optimized for Qwen models and OpenAI-compatible providers. | High |
| Goose | `goose run`, `--output-format json/stream-json`, `goose acp` | Open-source local agent from Block with provider/model flags, MCP, recipes, and ACP. | High |
| Cursor Agent CLI | `cursor-agent -p`, `--output-format json/stream-json`, `--force` | Commercial but very scriptable and broadly adopted by Cursor users. | Medium-high |
| Auggie CLI | `auggie --print`, JSON output, `--acp`, `--mcp` | Commercial Augment harness with explicit automation and protocol surfaces. | Medium-high |
| Amp | `amp --execute --stream-json`, thread continuation | Commercial Sourcegraph harness with high-quality agent focus and documented streaming JSON. | Medium |
| GitHub Copilot CLI | interactive CLI plus public-preview ACP server | Deep GitHub-native agent, custom agents, skills, AGENTS.md support. | Medium via ACP |
| Aider | `aider --message`, repo map, broad model support | Mature open-source terminal pair programmer; less agent-protocol-friendly. | Medium-low |
| Amazon Q Developer CLI | `q` terminal agent with MCP and AWS integration | Useful for AWS-heavy users, less general as a SASE default runtime. | Medium-low |
| OpenHands | CLI/SDK/cloud/self-hosted agent platform | More of an alternate execution platform than a thin CLI harness. | Low for first pass |
| Crush | terminal-first Go agent with multi-model, LSP, MCP | Promising open-source TUI; defer until headless/JSON surface is confirmed. | Watchlist |

## Candidate Notes

### OpenCode

OpenCode is one of the best first targets. Its CLI docs explicitly support programmatic use:

- `opencode run "..."` runs non-interactively.
- `opencode run --format json` emits raw JSON events.
- `opencode run --continue` and `--session` cover session resume.
- `opencode serve` starts a headless HTTP server so repeated runs can avoid cold-start costs.
- `--model` uses `provider/model`, which maps cleanly to SASE's model override concept.

Implementation shape: add a standalone provider plugin that shells out to `opencode run --format json --model ...`.
If the JSON event schema is stable enough, parse the final event like Codex; otherwise stream tool events into
`live_reply.md` and collect assistant text.

Sources: OpenCode CLI docs document `opencode run`, session flags, JSON format, and `serve` mode:
<https://open-code.ai/en/docs/cli>.

### Qwen Code

Qwen Code looks like the lowest-friction open-source addition because it already resembles Gemini CLI operationally but
has a stronger headless contract:

- `qwen -p` / `qwen --prompt` runs in headless mode.
- `--output-format json` returns buffered structured output.
- `--output-format stream-json` emits line-delimited events.
- `--yolo` and `--approval-mode` control action approval.
- `--continue` and `--resume` provide project-scoped session reuse.
- Config lives under `~/.qwen/settings.json` and project `.qwen/settings.json`.

Two caveats matter: Qwen OAuth free tier was discontinued on 2026-04-15, so setup should steer users toward API keys,
Alibaba Cloud Coding Plan, OpenRouter, Fireworks, or other compatible providers; and local-model support depends heavily
on the model/tool-call protocol actually producing valid tool calls.

Implementation shape: mirror the Gemini provider at first, but prefer the structured `stream-json` parser instead of
PTY/plain-text output. Add a SASE-managed shadow home if Qwen mutates global settings during startup.

Sources: Qwen README notes the 2026-04-15 OAuth discontinuation and auth alternatives:
<https://github.com/QwenLM/qwen-code/blob/main/README.md>. Qwen headless docs cover `-p`, JSON/stream-JSON,
`--yolo`, approval mode, and resume flags:
<https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/>.

### Goose

Goose is a strong candidate because it exposes a clean automation surface and a native ACP mode:

- `goose run --instructions file.md` or `goose run -t "prompt"` runs and exits.
- `--quiet` prints only model response.
- `--output-format text|json|stream-json` is built for automation.
- `--provider` and `--model` override model selection.
- `--no-session`, `--resume`, and `--name` provide session control.
- `goose acp` runs Goose as an ACP agent server over stdio.
- Recipes provide a SASE-adjacent workflow primitive, but SASE should initially treat them as a user-level feature.

Implementation shape: either add a direct `goose run --output-format stream-json` provider or use ACP once SASE has an
ACP client path. Direct subprocess support is probably faster; ACP is strategically cleaner.

Sources: Goose CLI docs cover run options, structured output, provider/model flags, session controls, and ACP:
<https://goose-docs.ai/docs/guides/goose-cli-commands/>.

### Cursor Agent CLI

Cursor has one of the clearest headless contracts among commercial tools:

- `cursor-agent -p` is print/non-interactive mode.
- `--output-format text|json|stream-json` is documented, with `stream-json` as the default in print mode.
- `--force` allows direct file changes and shell commands unless explicitly denied.
- `--resume`, `--model`, and `CURSOR_API_KEY` cover session/model/auth basics.

This is probably worth supporting if the target SASE users already pay for Cursor. The downside is vendor account/API
dependency and the need to verify whether Cursor's file edit behavior conflicts with SASE's workspace isolation or
project instruction deployment.

Implementation shape: a provider that invokes
`cursor-agent -p --force --output-format stream-json --model <model> <prompt>`, with an env override for the binary path
and conservative parsing that ignores unknown event fields.

Sources: Cursor parameter docs cover `-p`, `--output-format`, `--force`, `--resume`, `--model`, and `CURSOR_API_KEY`:
<https://docs.cursor.com/en/cli/reference/parameters>. Cursor headless docs cover scripting examples:
<https://docs.cursor.com/en/cli/headless>.

### Auggie CLI

Auggie has a good SASE-facing CLI surface:

- `auggie --print "..."` runs one instruction and exits.
- `--quiet`, `--compact`, and credit reporting control output.
- `--output-format json` exists for automation.
- `--queue` can sequence follow-up prompts in one print-mode run.
- `--ask` provides read-only/retrieval mode.
- `--mcp` and `--acp` expose protocol server modes.
- It reuses Claude Code command locations as lower-precedence fallbacks, which may help SASE skill/command rollout.

Implementation shape: direct JSON subprocess provider first. ACP can follow if SASE adopts a general ACP client.

Sources: Auggie CLI reference documents print mode, JSON output, queueing, ask mode, MCP, ACP, and command locations:
<https://docs.augmentcode.com/cli/reference>.

### Amp

Amp is interesting mostly because its CLI has a documented streaming JSON mode and team-oriented thread model:

- `amp --execute "..." --stream-json` runs a prompt in execute mode with NDJSON output.
- `amp threads continue --execute ... --stream-json` can continue existing threads.
- `AMP_API_KEY` enables non-interactive use in scripts and CI.
- Its manual documents `AGENTS.md` file mentions and CLI/IDE integration.

The main risk is closed-source/vendor coupling. Also verify approval flags before shipping: E2B examples use
`--dangerously-allow-all`, but the official Amp manual page I found only confirms execute mode and streaming JSON.

Implementation shape: a provider with `AMP_API_KEY` auth, `--execute`, and `--stream-json`; add approval-mode support
only after confirming official CLI help for the installed version.

Sources: Amp manual covers non-interactive auth and streaming JSON execute mode:
<https://ampcode.com/manual>.

### GitHub Copilot CLI

Copilot CLI is strategically important because of GitHub-native workflows, but direct SASE subprocess support looks less
straightforward than OpenCode/Qwen/Goose/Cursor:

- The command reference primarily documents an interactive `copilot` UI plus management subcommands.
- Copilot CLI supports AGENTS.md, repository instructions, skills, custom agents, hooks, MCP, and OpenTelemetry.
- The ACP server is in public preview and can run over stdio or TCP via `copilot --acp --stdio` or `copilot --acp --port
  3000`.
- GitHub explicitly lists CI/CD, custom frontends, and multi-agent systems as ACP use cases.

Implementation shape: do not start with PTY scraping the interactive UI. Support Copilot through a general ACP provider
or through a small ACP bridge, then map SASE prompts and approvals to ACP sessions.

Sources: Copilot CLI command reference:
<https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference>. Copilot ACP server docs:
<https://docs.github.com/en/copilot/reference/copilot-cli-reference/acp-server>. Copilot CLI AGENTS.md support:
<https://docs.github.com/en/copilot/how-tos/copilot-cli/use-copilot-cli/overview>.

### Aider

Aider is mature and widely used, but it is more "AI pair programmer" than autonomous agent harness:

- Strong repo map and broad model support.
- Useful command-line options, including `--message`, chat history, model selection, file scopes, pretty/stream output,
  and git behavior controls.
- No first-class JSON event stream comparable to Codex/Cursor/Qwen/OpenCode.
- Aider's default git behavior can auto-commit, which conflicts with SASE's own commit workflow unless disabled.

Implementation shape: only support Aider after SASE has a "plain text provider with stricter workspace policy" pattern,
and launch it with auto-commit disabled. It may be more useful as a mentor/reviewer backend than a default coder
runtime.

Sources: Aider docs and option reference:
<https://aider.chat/docs/> and <https://aider.chat/docs/config/options.html>.

### Amazon Q Developer CLI

Amazon Q Developer CLI is credible for AWS-heavy teams:

- AWS describes the CLI agent as able to read/write local files, call AWS APIs, run bash commands, and write code.
- It supports MCP from the CLI, with global MCP config under `~/.aws/amazonq/cli-agents`.
- Its strongest value is AWS/API/IaC context, not general SASE runtime diversity.

Implementation shape: defer until a user specifically wants AWS-oriented agent runs. The provider should probably
preserve AWS profile/env handling and keep Q's MCP config separate from SASE's own MCP deployment.

Sources: AWS product page:
<https://aws.amazon.com/q/developer/build/>. Amazon Q MCP docs:
<https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/qdev-mcp.html>.

### OpenHands

OpenHands is best viewed as an alternate agent platform or backend rather than a thin CLI runtime:

- It has CLI, SDK, cloud, and self-hosted surfaces.
- It is MIT-licensed for core/agent-server Docker images, while enterprise features are source-available.
- It brings heavier concepts such as hosted infrastructure, integrations, and agent server APIs.

Implementation shape: not a first `LLMProvider` target. If SASE later wants remote/containerized workers, OpenHands is
worth revisiting as a workspace/executor integration rather than just another local subprocess.

Sources: OpenHands repo:
<https://github.com/OpenHands/OpenHands>.

### Crush

Crush is a promising open-source terminal agent from Charm:

- Multi-model support, LSP-enhanced context, MCP extensions, sessions, and cross-platform packaging.
- It supports OpenAI/Anthropic-compatible APIs and many provider families.
- I did not find enough official evidence of a stable headless JSON/NDJSON mode during this pass.

Implementation shape: watchlist until the CLI has a documented `run/print` mode with structured output, or until ACP
support becomes the primary SASE integration path.

Sources: Crush README:
<https://github.com/charmbracelet/crush>.

## ACP as a Strategic Path

The Agent Client Protocol is the most important cross-cutting development. Zed describes ACP as an open standard for
connecting any agent to any editing environment, and the ACP registry already lists many agents relevant to SASE:
Augment, Cursor, Gemini CLI, GitHub Copilot, Goose, OpenCode, OpenHands, Qwen Code, Kiro, Kimi, Mistral Vibe, Poolside,
and others.

There are two practical options:

1. Add SASE providers one by one using each tool's best headless command.
2. Add an ACP-backed provider once, then support ACP-capable agents through configuration.

The first option is faster and easier to debug for OpenCode/Qwen/Goose/Cursor. The second option is more strategic for
Copilot, Auggie, Goose, and the long tail of new CLI agents.

`acpx` is worth studying as a shortcut or reference. It is a headless ACP client with session management, named parallel
sessions, one-shot `exec`, approval flags, text/JSON output, and built-in wrappers for Codex and Claude. `forge` is
another useful ACP reference: it positions itself as a universal terminal interface over ACP and documents the agent
ecosystem and headless `forge <agent> -p` usage.

Sources: ACP agent registry:
<https://agentclientprotocol.com/get-started/agents>. Zed ACP overview:
<https://zed.dev/acp>. `acpx`:
<https://github.com/openclaw/acpx>. Forge:
<https://github.com/forge-agents/forge>.

## Recommended Roadmap

### Phase 1: Direct JSON Providers

Add providers for the tools with the cleanest subprocess contracts:

1. OpenCode: `opencode run --format json`.
2. Qwen Code: `qwen -p --output-format stream-json --yolo`.
3. Goose: `goose run --output-format stream-json --quiet`.

These three are open-source or source-visible, have multi-provider support, and expose automation-friendly output. They
also test three useful variants of provider behavior: OpenCode server/session mode, Qwen's Gemini-like lineage, and
Goose's recipe/ACP/MCP ecosystem.

### Phase 2: Commercial Headless Providers

Add opt-in providers for commercial tools:

1. Cursor: `cursor-agent -p --force --output-format stream-json`.
2. Auggie: `auggie --print --output-format json`.
3. Amp: `amp --execute --stream-json`.

These should be plugins or optional extras, because auth, subscriptions, and terms are external to SASE.

### Phase 3: ACP Provider

Build or vendor a small ACP client path for SASE. Requirements:

- Start an ACP agent server over stdio.
- Create or resume a session scoped to a SASE workspace.
- Send prompt turns and collect assistant text plus tool events.
- Map SASE's approval posture to ACP session modes.
- Preserve SASE artifacts (`live_reply.md`, `done.json`, usage, interrupt handling) around ACP events.

This would make GitHub Copilot CLI viable without scraping the interactive UI and would reduce future runtime additions
to configuration.

## Implementation Notes for SASE

1. Keep each runtime capability-uniform. New providers should support the same hooks, skills, commit workflow, retry,
   and interrupt semantics as Claude/Gemini/Codex.
2. Prefer plugin providers for commercial or fast-moving harnesses. In-tree providers should be reserved for broadly
   useful, stable, low-friction runtimes.
3. Reuse the Codex shadow-home pattern. Several tools write global config or session state; SASE should avoid polluting
   user state during automated runs unless the user opts in.
4. Normalize structured output behind a small internal event adapter. Cursor, Qwen, OpenCode, Goose, Amp, and Codex all
   have different JSON schemas but similar concepts: system start, assistant delta/result, tool start/end, final result.
5. Treat native session resume as an optimization. SASE already has a stateless context reconstruction path for Gemini
   and Codex; native sessions should improve interrupt/follow-up behavior but not become required for correctness.
6. Store provider-specific setup requirements in provider metadata: binary env var, auth env var, skill deploy subpath,
   model aliases, and approval flags.

## Bottom Line

The strongest near-term additions are OpenCode, Qwen Code, and Goose. They are automation-friendly, flexible across
models, and likely to exercise the right SASE abstractions without immediately coupling SASE to another paid vendor.

Cursor, Auggie, and Amp are valuable opt-in commercial plugins after that. GitHub Copilot CLI should probably wait for
an ACP-backed provider, because ACP is the documented automation surface and avoids brittle interactive CLI scraping.
