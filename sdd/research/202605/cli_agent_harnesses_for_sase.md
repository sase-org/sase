# CLI Agent Harnesses to Consider for SASE

Research date: 2026-05-07 (updated 2026-05-06 with second-pass corrections and gap fills)

## Question

SASE already has first-class agent runtime support for Claude Code, Codex CLI, Gemini CLI, and plugin-provided external provider.
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
| OpenCode | `opencode run --format json`, `opencode serve`, `--dangerously-skip-permissions` | Open-source SST-team terminal agent with non-interactive and server modes; ~75+ providers. | High |
| Qwen Code | `qwen -p`, `--output-format json/stream-json`, `--yolo` | Gemini-derived open-source harness optimized for Qwen models and OpenAI-compatible providers. | High |
| Goose | `goose run`, `--output-format json/stream-json`, `goose acp` | Open-source local agent from Block with provider/model flags, MCP, recipes, and ACP. | High |
| Cline CLI 2.0 | `cline ... --json --yolo`, native subagents, ACP support | Open-source agent (5M+ IDE installs); CLI 2.0 launched Feb 2026 with explicit headless/CI/CD mode. | High |
| Crush | `crush run --json --model {provider}/{model}` | Charm Go agent; non-interactive mode landed in recent releases with JSON output and provider/model flag. | Medium-high |
| Cursor Agent CLI | `cursor-agent -p`, `--output-format json/stream-json`, `--force` | Commercial but very scriptable and broadly adopted by Cursor users. | Medium-high |
| Auggie CLI | `auggie --print`, JSON output, `--acp`, `--mcp` | Commercial Augment harness with explicit automation and protocol surfaces. | Medium-high |
| Amp | `amp --execute --stream-json`, `--dangerously-allow-all` | Commercial Sourcegraph harness with documented streaming JSON, threads, and bypass flag. | Medium |
| Neovate Code | `neovate` interactive plus headless mode, plugin hooks, MCP | Ant Group open-source agent with explicit plugin system and headless automation. | Medium |
| gptme | `gptme --non-interactive`, JSON output, broad provider/local-model support | Open-source personal-agent CLI built for SSH/CI/headless environments. | Medium |
| GitHub Copilot CLI | interactive CLI plus public-preview ACP server | Deep GitHub-native agent, custom agents, skills, AGENTS.md support. | Medium via ACP |
| Aider | `aider --message`, repo map, broad model support | Mature open-source terminal pair programmer; less agent-protocol-friendly. | Medium-low |
| Amazon Q Developer CLI | `q` terminal agent with MCP and AWS integration | Useful for AWS-heavy users, less general as a SASE default runtime. | Medium-low |
| OpenHands | CLI/SDK/cloud/self-hosted agent platform | More of an alternate execution platform than a thin CLI harness. | Low for first pass |
| Coro Code | Rust CLI agent (Trae Agent Rust lineage), terminal UI | Rust-based open-source agent with multi-provider config; verify headless surface. | Watchlist |
| Codebuff | `@codebuff/sdk` JS SDK, multi-agent | SDK-first design rather than subprocess CLI; integrate via SDK shell-out if added. | Watchlist |
| Plandex | `plandex` with JSON model config | Winding down as of 2025-10-03; not accepting new users. | Skip |

## Candidate Notes

### OpenCode

OpenCode (by the SST team, repo `sst/opencode`) is one of the best first targets. Its CLI docs explicitly support
programmatic use:

- `opencode run "..."` runs non-interactively.
- `opencode run --format json` emits raw JSON events. (`default` is the only other documented value.)
- `opencode run --continue` (`-c`) and `--session` (`-s`) cover session resume; `--fork` forks on continue.
- `--dangerously-skip-permissions` auto-approves non-denied permissions for headless use.
- `--model` (`-m`) uses `provider/model`, which maps cleanly to SASE's model override concept.
- `--agent` selects a custom agent definition; `--attach` connects to a running server.
- `opencode serve` starts a headless HTTP server so repeated runs can avoid cold-start costs.
- `opencode session list --format json` and `models --refresh` are useful for SASE bookkeeping.

Note: there is a separate community repo `opencode-ai/opencode` with different commit history; SASE should target the
SST repo, since it is the one tied to the documented CLI surface and ACP registry entry.

Implementation shape: add a standalone provider plugin that shells out to
`opencode run --format json --dangerously-skip-permissions --model <provider>/<model> ...`. The JSON output is event
oriented; parse incremental events like Codex/Cursor and capture the final assistant text and usage. Use `serve` +
`--attach` later as an optimization.

Sources: OpenCode CLI docs document `opencode run`, session flags, JSON format, `serve` mode, and
`--dangerously-skip-permissions`: <https://opencode.ai/docs/cli/>. Repo:
<https://github.com/sst/opencode>.

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

### Cline CLI 2.0

Cline shipped a major CLI rework in February 2026 that elevates Cline from "popular IDE extension" to a credible SASE
runtime target:

- `cline ... --json` streams structured output for programmatic consumption (jq-friendly NDJSON).
- `--yolo` (`-y`) plus `--json` puts Cline into headless mode designed for automation, scripting, and CI/CD.
- Headless mode also activates implicitly when stdin is not a TTY — useful for piping prompts.
- Native subagents: IDE Cline can call the Cline CLI to delegate tasks with a fresh context window. SASE should
  consider this mostly orthogonal — SASE already orchestrates agents — but the subagent contract may simplify
  multi-agent xprompt patterns.
- ACP server support is documented as "for any editor", which makes Cline both a direct subprocess target and an ACP
  target.
- Open source (Apache 2.0), 5M+ IDE installs across VS Code, Cursor, JetBrains, Zed, and Neovim.

Implementation shape: shell out to `cline ... --json --yolo` for the first cut. Reuse SASE's standard structured-event
parser. Treat Cline's IDE subagent feature as a non-goal for the SASE provider; SASE will spawn its own children.

Sources: Cline CLI overview and headless docs:
<https://docs.cline.bot/cline-cli/getting-started>,
<https://github.com/cline/cline/blob/main/docs/cline-cli/overview.mdx>. CLI 2.0 launch post:
<https://cline.bot/blog/introducing-cline-cli-2-0>.

### Amp

Amp is interesting mostly because its CLI has a documented streaming JSON mode and team-oriented thread model:

- `amp --execute "..." --stream-json` runs a prompt in execute mode with NDJSON output.
- `amp threads continue --execute ... --stream-json` can continue existing threads.
- `AMP_API_KEY` enables non-interactive use in scripts and CI.
- Its manual documents `AGENTS.md` file mentions and CLI/IDE integration.

The main risk is closed-source/vendor coupling.

`--dangerously-allow-all` is now confirmed by the Amp manual and Sourcegraph's own examples and SDK docs (the Elixir
SDK communicates with Amp exclusively through `--execute --stream-json`, and Amp's official examples show
`amp --dangerously-allow-all -x "..."`). This removes the prior uncertainty about how to disable approval prompts in
SASE-managed runs. Be aware: a 2025 prompt-injection issue exposed how powerful the bypass flag is — SASE should
default to approvals on and only enable bypass inside isolated workspaces.

Implementation shape: a provider with `AMP_API_KEY` auth, `--execute`, and `--stream-json`. Default approval policy is
SASE's normal sandboxed approval; opt-in `--dangerously-allow-all` only when the workspace policy explicitly allows it.

Sources: Amp manual: <https://ampcode.com/manual>. Amp appendix (flags):
<https://ampcode.com/manual/appendix>. Examples and guides:
<https://github.com/sourcegraph/amp-examples-and-guides/blob/main/guides/cli/README.md>. Prompt-injection writeup
documenting the bypass-flag risk surface:
<https://embracethered.com/blog/posts/2025/amp-agents-that-modify-system-configuration-and-escape/>.

### Neovate Code

Neovate Code is Ant Group's open-source coding agent. It is interesting to SASE because the project explicitly
markets a plugin-first design that resembles SASE's own `LLMProvider` boundary:

- Interactive plus headless mode for CI/CD and scripts.
- Plugin system with documented hooks for swapping models, tools, slash commands, and integrations.
- Multi-provider support (OpenAI, Anthropic, Google) and MCP integration.
- Companies including Ant Group and Kuaishou have used Neovate as a base to build their own internal agents — useful
  signal that the plugin surface is real, not aspirational.

The risk is that the project is younger than OpenCode/Goose/Qwen and the headless-output schema may still be evolving;
verify the JSON event schema before committing to a wire-format-coupled provider.

Implementation shape: defer until SASE's open-source candidate list (OpenCode/Qwen/Goose/Cline) is integrated, then
revisit. Neovate's plugin system is mostly relevant *inside* a Neovate run; SASE itself should still call it as a
subprocess provider.

Sources: Neovate repo and overview docs:
<https://github.com/neovateai/neovate-code>,
<https://neovateai.dev/en/docs/overview>.

### gptme

`gptme` (by Erik Bjäre, repo `gptme/gptme`) is a personal-agent CLI explicitly designed for SSH, tmux, and headless
servers, which makes it an unusually good cultural fit for SASE workspaces:

- Provider-agnostic (Anthropic, OpenAI, Google, xAI, DeepSeek, OpenRouter, llama.cpp local models).
- Documented JSON output mode for automation.
- RFC 8628 device-flow auth works in non-interactive shells.
- Ships shell, Python, web, and vision tools out of the box.

The risks are smaller-scale governance (single primary maintainer) and a tool surface skewed toward general personal
agents rather than coding-specific workflows.

Implementation shape: optional plugin-grade provider for users who want a low-overhead provider-agnostic local agent.
Wire `gptme --non-interactive` (or whatever the latest stable headless flag is) plus the JSON output flag.

Sources: gptme CLI reference:
<https://gptme.org/docs/cli.html>. Repo and getting started:
<https://github.com/ErikBjare/gptme>.

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

### Coro Code, Codebuff, Plandex (watchlist and skip list)

- **Coro Code** (formerly Trae Agent Rust) is a Rust-based open-source CLI agent with a rich terminal UI and
  multi-provider config. Worth tracking for users who want a Rust runtime, but verify the headless surface (JSON
  events, approval flags, session model) before integrating. Repo:
  <https://github.com/Blushyes/coro-code>.
- **Codebuff** is multi-agent and provides a JS SDK (`@codebuff/sdk`) rather than a thin subprocess CLI. If SASE later
  supports SDK-shaped providers (rather than only `subprocess.Popen` runtimes), Codebuff is a natural candidate. Until
  then it does not match the current `LLMProvider` boundary cleanly. Docs:
  <https://www.codebuff.com/docs/help>. Repo: <https://github.com/CodebuffAI/codebuff>.
- **Plandex** announced wind-down on 2025-10-03 and is no longer accepting new users. Skip for new SASE work; only
  worth referencing as prior art for JSON-based model config. Repo:
  <https://github.com/plandex-ai/plandex>.

### Crush

Crush is an open-source terminal agent from Charm. Recent releases shipped an explicit non-interactive mode, so it
moves from watchlist to a real candidate:

- `crush run "..."` is the documented non-interactive entry point and the focus of recent releases.
- `crush run --json` produces structured output for automation; an additional `--output-format` proposal (text/json/
  stream-json/yaml/xml) is in flight but not yet shipped.
- `--model "{provider}/{model}"` selects model and provider, matching SASE's model-override pattern (e.g.
  `--model "openai/gpt-5.2-codex"`).
- LSP-enhanced context, MCP extensions, sessions, and cross-platform packaging are already in place.
- A `CRUSH_CLIENT_SERVER` mode exists for streaming events from a remote server, mirroring OpenCode's `serve`/`attach`
  pattern.

Implementation shape: shell out to `crush run --json --model <provider>/<model> ...` and parse JSON. Watch the
`--output-format` proposal so SASE can switch to `stream-json` once it lands. Treat session/state mutation
conservatively (Crush stores sessions on disk by default).

Sources: Crush repo and CLI usage docs:
<https://github.com/charmbracelet/crush>,
<https://deepwiki.com/charmbracelet/crush/2.2-cli-usage>. Output-format proposal:
<https://github.com/charmbracelet/crush/issues/1034>.

## ACP as a Strategic Path

The Agent Client Protocol is the most important cross-cutting development. Zed describes ACP as an open standard for
connecting any agent to any editing environment.

The official **ACP Registry** launched in late January 2026 (joint Zed + JetBrains announcement). Listed agents
include Claude Code, Codex CLI, GitHub Copilot CLI, OpenCode, Gemini CLI, Goose, Qwen Code, Augment, Cursor, OpenHands,
Kiro, Kimi, Mistral Vibe, Poolside, and others. The registry requires authentication support (Agent Auth or Terminal
Auth), so a SASE ACP provider would need to handle one of those modes.

There are two practical options:

1. Add SASE providers one by one using each tool's best headless command (faster to debug, finer control).
2. Add an ACP-backed provider once, then support ACP-capable agents through configuration (more strategic, especially
   for Copilot CLI where direct subprocess support is awkward).

The first option is faster for OpenCode/Qwen/Goose/Cursor/Cline/Crush, all of which have good native headless modes.
The second option is more strategic for Copilot, Auggie, Goose, and the long tail of new CLI agents.

Two reference clients are worth studying before SASE writes its own ACP integration:

- **`acpx`** is a headless ACP client with session management, named parallel sessions, one-shot `exec`, approval
  flags, text/JSON output, and built-in wrappers for Codex and Claude. It is the closest existing tool to "what SASE
  needs internally", and may be vendorable.
- **Forge** (`forge-agents/forge`) is a universal CLI for ACP-compatible agents. Each agent runs as a subprocess that
  speaks NDJSON over stdin/stdout. Forge ships `-p, --print` for headless one-shots and a unified conversation history
  across agents. Useful as a reference for SASE's own ACP transport layer.

Sources: ACP Registry: <https://agentclientprotocol.com/get-started/registry>. Registry launch posts:
<https://zed.dev/blog/acp-registry>,
<https://blog.jetbrains.com/ai/2026/01/acp-agent-registry/>. ACP protocol repo:
<https://github.com/agentclientprotocol/agent-client-protocol>. `acpx`:
<https://github.com/openclaw/acpx>. Forge:
<https://github.com/forge-agents/forge>.

## Recommended Roadmap

### Phase 1: Direct JSON Providers

Add providers for the tools with the cleanest subprocess contracts:

1. OpenCode: `opencode run --format json --dangerously-skip-permissions`.
2. Qwen Code: `qwen -p --output-format stream-json --yolo`.
3. Goose: `goose run --output-format stream-json --quiet`.
4. Cline CLI 2.0: `cline ... --json --yolo`.

These four are open-source, have multi-provider support, and expose automation-friendly output. Together they exercise
the full range of provider behavior SASE needs: OpenCode's server/session mode, Qwen's Gemini-like lineage, Goose's
recipe/ACP/MCP ecosystem, and Cline's headless + subagent contract. Crush is a close fifth — defer it until the
`--output-format` proposal lands and SASE has a stream-JSON parser pattern in place.

### Phase 2: Commercial Headless Providers

Add opt-in providers for commercial tools:

1. Cursor: `cursor-agent -p --force --output-format stream-json`.
2. Auggie: `auggie --print --output-format json`.
3. Amp: `amp --execute --stream-json` (with optional `--dangerously-allow-all` gated by SASE workspace policy).

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

The strongest near-term additions are OpenCode, Qwen Code, Goose, and Cline CLI 2.0. They are automation-friendly,
flexible across models, and likely to exercise the right SASE abstractions without immediately coupling SASE to
another paid vendor. Crush follows closely once its `--output-format` work lands.

Cursor, Auggie, and Amp are valuable opt-in commercial plugins after that. GitHub Copilot CLI should probably wait for
an ACP-backed provider, because ACP is the documented automation surface and avoids brittle interactive CLI scraping.

Neovate Code and gptme are credible second-tier additions. Coro Code and Codebuff are watchlist; Plandex is a skip
(winding down 2025-10-03).
