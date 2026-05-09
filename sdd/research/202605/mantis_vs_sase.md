# Mantis vs. SASE Research

Research date: 2026-05-09

## Scope

This note compares SASE with Project Mantis, scoped to the public terminal-agent project at
`miladyxx333-lab/Mantis` and its landing page at `agentmantis.xyz`. There is another "Mantis" AI research project
associated with MIT CSAIL and embeddings/visualization; that project is not directly comparable to SASE's agentic
software engineering workflow layer, so it is only treated as an out-of-scope naming collision.

## Executive Summary

Mantis and SASE overlap around local AI agent operation, terminal control, memory, web access, file analysis, command
execution, and remote control. Their center of gravity is very different.

Mantis is a single-agent, Gemini-oriented terminal assistant with a strong "sovereign local agent" product story. Its
implementation is small and experimental: a TypeScript monorepo with a CLI, a core agent class, local JSON vector memory,
Puppeteer web search/page reading, image/spreadsheet/PDF/docx helpers, Docker-wrapped shell execution, a Telegram bot,
and a simple audit log. Its best ideas for SASE are product-facing: obvious commands, local memory that feels automatic,
multimodal local-file affordances, remote mobile/chat control, hostile-content delimiters for web input, and a visible
security persona around command execution.

SASE is much broader and more mature as a software-engineering orchestration system. It coordinates many providers and
many agents through ChangeSpecs, ACE, AXE, XPrompts, Beads, SDD, mentors, workspace claims, artifacts, telemetry, and
mobile gateway APIs. SASE's weakness relative to Mantis is not capability depth; it is that some high-value capabilities
are spread across powerful but less instantly legible surfaces.

The main lesson is to borrow Mantis's directness without borrowing its risky shortcuts. SASE should productize a few
fixed, memorable operations around memory, web/document ingestion, multimodal files, remote control, audit, and optional
execution sandboxing while preserving SASE's stronger workflow state, least-privilege mobile boundary, provider
abstraction, and review/commit lifecycle.

## Source Map

Primary Mantis sources:

- Mantis landing page: https://www.agentmantis.xyz/
- Mantis GitHub README at inspected commit
  `72f544904544acb14f5b4a77f84e651f6acbf02f`:
  https://github.com/miladyxx333-lab/Mantis/blob/72f544904544acb14f5b4a77f84e651f6acbf02f/README.md
- Core agent command router:
  https://github.com/miladyxx333-lab/Mantis/blob/72f544904544acb14f5b4a77f84e651f6acbf02f/packages/core/src/mantis.ts
- Cortex memory:
  https://github.com/miladyxx333-lab/Mantis/blob/72f544904544acb14f5b4a77f84e651f6acbf02f/packages/core/src/modules/cortex/index.ts
- Remus command execution:
  https://github.com/miladyxx333-lab/Mantis/blob/72f544904544acb14f5b4a77f84e651f6acbf02f/packages/core/src/modules/remus/index.ts
- DeepBrowser web access:
  https://github.com/miladyxx333-lab/Mantis/blob/72f544904544acb14f5b4a77f84e651f6acbf02f/packages/core/src/modules/browser/index.ts
- Telegram uplink:
  https://github.com/miladyxx333-lab/Mantis/blob/72f544904544acb14f5b4a77f84e651f6acbf02f/packages/core/src/modules/uplink/index.ts
- Security workflow note:
  https://github.com/miladyxx333-lab/Mantis/blob/72f544904544acb14f5b4a77f84e651f6acbf02f/.agent/workflows/security.md

Local SASE sources:

- [README.md](../../../README.md)
- [docs/sdd.md](../../../docs/sdd.md)
- [docs/axe.md](../../../docs/axe.md)
- [docs/mobile_gateway.md](../../../docs/mobile_gateway.md)
- [docs/xprompt.md](../../../docs/xprompt.md)
- [docs/beads.md](../../../docs/beads.md)
- [docs/agent_images.md](../../../docs/agent_images.md)
- [docs/notifications.md](../../../docs/notifications.md)

## What Mantis Is

Mantis presents itself as a tactical terminal agent with local sovereignty, vision, memory, web search, command
execution, spreadsheet analysis, document generation, and Telegram remote control. The README describes a monorepo with
`@mantis/core` and `@mantis/cli`, powered by Gemini, configured with `GEMINI_API_KEY` and optional
`TELEGRAM_BOT_TOKEN`.

The current implementation is compact:

- `Mantis.send()` routes string prefixes such as `look at`, `scan sheet`, `search`, `browse`, `read`, `write doc`,
  `create report`, `run`, and `exec`.
- `Cortex` stores interaction summaries and embeddings in `.mantis_memory.json`, then recalls the top matches above a
  cosine-similarity threshold before ordinary chat.
- `DeepBrowser` uses Puppeteer with stealth plugin to perform search and page extraction, then injects content inside
  explicit untrusted-content delimiters.
- `VisionModule`, `SpreadsheetTactician`, and `DocsModule` directly read local image, spreadsheet, PDF, and docx-related
  data.
- `RemusExecutor` blocklists selected destructive commands and sensitive-path strings, logs outcomes, and runs shell
  commands through `docker run --rm --network none alpine sh -c ...`.
- `TelegramUplink` bridges Telegram text messages into the same `Mantis.send()` path. Tool use is restricted to
  `ADMIN_CHAT_ID` when configured; if `ADMIN_CHAT_ID` is absent, the code explicitly treats every sender as admin.
- `.agent/workflows/security.md` defines a Spanish "BluePastel" hardening note requiring grounding before edits,
  explicit confirmation before destructive operations, and aborting on project-structure conflicts.

Important caveats:

- Mantis is early-stage. The public GitHub page showed 12 commits, no releases, no stars/forks, and the root
  `package.json` test script exits with "no test specified" at the time of inspection.
- Its "no cloud dependency lock-in" claim is partly product positioning. The implementation requires Google Gemini API
  access for the core model and embeddings.
- The Docker command sandbox does not mount the project working tree, so many local shell commands will not operate on
  the user's files. That is safer than direct host execution, but it also makes the command surface less useful unless
  deliberately extended.
- The command blocklist is only a heuristic. It is useful as defense-in-depth, not a sufficient security boundary.
- Telegram tool authorization is fail-open if `ADMIN_CHAT_ID` is not set.

## What SASE Is

SASE is an orchestration layer for agent-driven software engineering rather than a single assistant. Its main unit is
not "one chat"; it is the tracked lifecycle of work across agents, workspaces, prompts, reviews, commits, artifacts, and
planning records.

Relevant SASE strengths:

- ChangeSpecs track work status, metadata, parents, commits, hooks, comments, mentors, deltas, and lifecycle state.
- ACE provides a TUI to inspect ChangeSpecs, running agents, artifacts, notifications, prompts, diffs, and review state.
- AXE runs scheduled background automation through lumberjacks/chops for hooks, mentors, waits, checks, comments, and
  housekeeping.
- XPrompts provide typed prompt templates, references, workflows, graph/explain/catalog commands, dynamic memory, LSP
  support, and multi-agent fan-out.
- SDD persists expanded prompts, tales, epics, legends, myths, research, and beads in predictable `YYYYMM`
  directories.
- Beads provide dependency-aware git-native issue tracking for plan/epic/legend tiers and multi-agent phase execution.
- The mobile gateway is workstation-hosted, paired, token-authenticated, SSE-based, and intentionally exposes fixed
  product-shaped APIs rather than generic shell/filesystem/RPC access.
- Provider plugins decouple LLMs, VCS backends, workspaces, notifications, and editor/chat integrations.

## Comparison

| Dimension | Mantis | SASE |
| --- | --- | --- |
| Product shape | Single terminal assistant with direct commands and Telegram bot. | Workflow/orchestration toolkit with CLI, ACE TUI, AXE daemon, mobile gateway, plugins, and docs. |
| Primary unit | One conversational agent session plus local helper commands. | ChangeSpec, SDD artifact, bead, agent run, workflow, workspace claim. |
| Agent model | Hardwired around Google Gemini SDK in the core implementation. | Provider-agnostic: Claude, Gemini, Codex, Qwen, OpenCode, and plugin providers. |
| Prompt/workflow model | Prefix-command router inside `Mantis.send()`. | XPrompt templates and YAML workflows with typed inputs, references, fan-out, explain/graph/catalog. |
| Memory | Automatic local vector memory over previous interactions in one JSON file. | Tiered memory, AGENTS.md, dynamic keyword memories, xprompts, chats, SDD, beads, artifacts. |
| Web/document ingestion | First-class direct commands for search, page read, PDF read, docx generation. | Available through agents, artifacts, xprompts, attachments, and provider tools, but less unified as fixed user commands. |
| Multimodal local files | Image and spreadsheet commands are explicit and memorable. | Strong artifact/image viewing exists, but user-facing "inspect this local image/sheet/PDF" workflows are more diffuse. |
| Shell execution | Docker-wrapped `run`/`exec` with simple blocklist and audit log. | Local agent runtimes operate in managed workspaces; no general first-class sandbox boundary yet. |
| Remote control | Telegram bot forwards chat and tools; admin guard is optional and fail-open. | Mobile gateway uses pairing, bearer tokens, fixed APIs, SSE, and avoids generic shell/filesystem exposure. |
| Audit/observability | Security events append to `mantis_security.log`. | Richer agent artifacts, notifications, telemetry, logs, ChangeSpec/Bead state, and mobile audit boundaries. |
| Engineering workflow | Minimal. No VCS lifecycle, no multi-agent plan graph, no review/commit model. | Core purpose: multi-agent software engineering coordination, review, and commit lifecycle. |
| Maturity | Small experimental repo, no releases, no tests configured. | Larger working system with docs, tests, CI conventions, Rust core boundary, and substantial SDD corpus. |

## Where Mantis Is Stronger

### 1. Immediate Command Affordances

Mantis's strongest UX move is making common high-value operations obvious:

- `look at path`
- `scan sheet path`
- `search query`
- `browse url`
- `read file.pdf`
- `write doc instructions`
- `run command`

SASE can do richer work, but the surface area is split across xprompts, agent prompts, CLI commands, artifacts, and
provider tools. Mantis shows how much value there is in a small command vocabulary that users remember without opening
docs.

### 2. Automatic Semantic Recall

Cortex is simple: embed interaction summaries, write them to a JSON file, and recall relevant fragments before normal
chat. This is not enough for serious engineering state, but it creates an immediate feeling that the agent remembers.

SASE's memory model is more correct for engineering work because SDD, beads, chats, prompts, and artifacts preserve the
source of truth. What SASE lacks is a lightweight "ambient recall" layer that searches those durable sources
semantically and injects scoped context without requiring the user to know the exact file, prompt, or bead path.

### 3. Multimodal Local File Handling

Mantis makes local images, spreadsheets, PDFs, and generated Word reports first-class helper modules. These are not
software-engineering primitives in the narrow sense, but they are common in real work: screenshots, diagrams, CSV
exports, spreadsheets, product PDFs, logs, planning docs, and generated handoff reports.

SASE has strong artifact viewing and image/PDF support, but there is room for a user-facing "file intelligence" layer
that turns local file references into consistent agent context and persisted artifacts.

### 4. Simple Remote Control Story

Mantis's Telegram uplink is easy to understand: start the daemon, message the bot, receive answers, use tools remotely.
The security model needs work, but the product value is clear.

SASE's mobile gateway is architecturally stronger and safer, but its value could be explained and exposed with the same
clarity: inspect notifications, approve plans, answer questions, launch fixed workflows, and monitor agents from a
phone.

### 5. Visible Security Persona

Remus is not a complete security system, but the "security twin" framing makes command risk visible to users. It also
creates one named place for command filtering, execution, and audit logging.

SASE has stronger operational controls in practice, but the mental model is spread across workspace claims, provider
permissions, mobile bridge boundaries, hooks, AXE, and commit workflow constraints. Mantis suggests the benefit of a
single user-facing "execution guard" concept.

## Where SASE Is Stronger

### 1. Long-Lived Engineering State

SASE's ChangeSpecs, Beads, SDD artifacts, commits, mentors, hooks, and agent artifacts solve the real coordination
problem in agentic software engineering: work must survive across sessions, agents, branches, reviews, commits, and
days of iteration.

Mantis has memory, but not a lifecycle model for software changes.

### 2. Multi-Agent Coordination

SASE supports parallel and scheduled agent work through workspaces, ACE, AXE, multi-prompt fan-out, bead work waves,
wait dependencies, retry chains, named agents, tagging, and artifact indexing.

Mantis is a single-agent assistant with helper modules. It does not attempt multi-agent work scheduling.

### 3. Provider and VCS Portability

SASE is intentionally above the agent layer. It can route workflows through different LLM runtimes and VCS/workspace
providers. Mantis is tightly coupled to Gemini APIs and a local TypeScript command router.

### 4. Safer Remote Bridge

SASE's mobile gateway has the correct shape for remote operation: local pairing, bearer token storage, fixed
product-shaped endpoints, SSE events, hint-only push payloads, and no generic shell/filesystem bridge.

Mantis's Telegram bot is convenient, but tool access becomes unrestricted if `ADMIN_CHAT_ID` is missing. That is a
clear anti-pattern for SASE.

### 5. Review, Commit, and Audit Trail

SASE ties agent work back to plans, changes, diffs, mentors, comments, artifacts, and commit metadata. Mantis can log
command execution, but it has no equivalent chain from intent to implementation to review to commit.

## Lessons and Improvements for SASE

### 1. Add a Small "Local Intelligence" Command Layer

Create a compact set of fixed commands or xprompt tags for common local context ingestion:

- `inspect image <path>`
- `inspect sheet <path>`
- `inspect pdf <path>`
- `read page <url>`
- `search web <query>`
- `make report <artifact|agent|changespec|bead>`

These should route through existing SASE primitives: xprompts, artifacts, SDD research/tales, notification attachments,
and agent launch metadata. The value is not new model capability; it is making the capability obvious and repeatable.

### 2. Build Scoped Semantic Recall Over SASE's Durable Corpus

Borrow the Cortex user experience, not its storage model. SASE already has better raw memory sources:

- SDD prompts, tales, epics, legends, myths, and research.
- Bead titles, descriptions, dependencies, status, and phase metadata.
- Agent chat summaries and final responses.
- ChangeSpec names, descriptions, deltas, comments, mentors, and commits.

Add an opt-in semantic recall index that can answer "what context should this agent see?" with explicit provenance and
scope controls. Keep source paths in the injection so the agent and user can audit where the memory came from.

### 3. Introduce an Optional Execution Sandbox Provider

Mantis's Remus shows that users want a named boundary around command execution. SASE should make that boundary real:

- `local-process`: current behavior for speed and compatibility.
- `docker`: mounted workspace with configurable read/write paths, network policy, env allowlist, and resource limits.
- `remote`: future provider hook for a remote executor.

This should live beside, but not be confused with, workspace providers. Workspaces decide "where is the code"; execution
sandboxes decide "what can the agent process touch."

### 4. Keep Remote Control Product-Shaped and Fail-Closed

Mantis validates the demand for chat/mobile remote control, but its Telegram authorization default is dangerous. SASE
should keep its mobile gateway principles:

- Pair before use.
- Use bearer tokens or platform-secure credentials.
- Expose fixed operations, not arbitrary shell.
- Make unsafe operations opt-in and audited.
- Fail closed when auth configuration is missing.

If SASE adds or expands Telegram/chat bridges, they should reuse mobile gateway semantics rather than forwarding freeform
tool access.

### 5. Add Prompt-Injection Guardrails to Web and Document Ingestion

Mantis wraps browser/page content in explicit untrusted-content delimiters and tells the model not to follow
instructions found inside. This is not sufficient by itself, but it is a good baseline.

SASE should standardize a helper for external content injection that:

- Delimits untrusted content consistently.
- Records source URL/path and retrieval time.
- Caps or summarizes content deterministically.
- Persists the retrieved content as an artifact when used for meaningful work.
- Makes prompt-injection guidance part of the generated prompt, not ad hoc prose.

### 6. Productize an "Execution Guard" Concept

SASE has several operational controls, but they do not yet form one memorable user-facing model. A named execution guard
could own:

- Dangerous command policy.
- Sensitive file/env access policy.
- Sandbox selection.
- Audit events.
- Human approval requirements.
- Remote-client restrictions.

This does not need Mantis's personality-heavy style. It just needs one clear place in docs, config, UI, and logs.

### 7. Make Audit Logs More User-Visible

Mantis's `mantis_security.log` is crude but easy to reason about. SASE has richer telemetry and artifacts, but security
and approval events could be easier to inspect as a single trail:

- command or tool invocation
- agent identity
- workspace
- source surface: CLI, ACE, mobile, Telegram/plugin
- approval decision
- sandbox/network mode
- result summary

This could integrate with notifications, ACE activity views, and mobile gateway audit state.

### 8. Improve First-Run Story Around "One Agent in One Terminal"

Mantis is easy to start conceptually: install, set API key, run terminal. SASE's value is bigger, but new users face a
larger conceptual set.

SASE could add a quick path that demonstrates the core loop in under five minutes:

- initialize SDD/beads
- run one named agent against a small task
- view it in ACE
- inspect artifact/chat/diff
- approve or commit through the workflow

The lesson is not to make SASE small. It is to let the first experience be small.

### 9. Turn Multimodal Outputs Into SDD-Linked Artifacts

Mantis can generate docx reports directly. SASE should prefer markdown/PDF and SDD-linked artifacts, but the product
need is real: users want polished handoff outputs from agent work.

Potential improvements:

- "Create research summary PDF from these sources."
- "Create review packet for this ChangeSpec."
- "Create epic handoff report from bead graph."
- "Create mobile-readable artifact bundle for this agent."

This builds on SASE's existing Markdown PDF and artifact viewer work.

### 10. Avoid Mantis's Hardcoded Command Router as a Long-Term Architecture

Mantis's prefix-command router is effective for a small assistant. SASE should not copy the architecture directly.
Hardcoded string prefixes will not scale across providers, plugins, permissions, mobile clients, and workflows.

The SASE-native version is:

- xprompt tags for user-visible operations
- typed command metadata for CLI/TUI/mobile completion
- fixed bridge endpoints for remote clients
- plugin extension points for file analyzers, search providers, and sandbox executors
- SDD/artifact persistence by default

## Recommended SASE Roadmap Items

1. **Local intelligence xprompts**: add built-in xprompts for image, spreadsheet, PDF, URL, and web-search ingestion;
   expose them in CLI, ACE prompt completion, mobile helpers, and docs.
2. **Semantic SDD/chats/beads recall prototype**: index local SASE corpus with source-path provenance and offer an
   explicit `#recall(...)` or dynamic-memory backend.
3. **Execution sandbox provider design**: write an epic for `local-process` vs `docker` execution boundaries, including
   mount/network/env policy and audit events.
4. **Remote bridge hardening contract**: codify that Telegram/chat plugins must use fail-closed auth and fixed
   operations, borrowing mobile gateway pairing/token concepts where possible.
5. **External content injection helper**: centralize untrusted-content delimiters, source metadata, content caps, and
   artifact persistence for web/PDF/page ingestion.
6. **Security/audit panel**: add a queryable view over sensitive actions, command/tool executions, approvals, and remote
   client operations.
7. **First-run single-agent demo**: create a narrow onboarding flow that shows SASE's full lifecycle without forcing the
   user to learn every subsystem first.

## Bottom Line

Mantis is not a serious competitor to SASE as an agentic software engineering workflow system today. It is too small,
too single-agent, too Gemini-specific, and too immature in tests/release/process. But it is useful prior art for how a
local agent can feel immediate: simple commands, local memory, web/file tools, remote chat control, command audit, and a
named execution safety boundary.

SASE should absorb those UX lessons while staying disciplined about the architecture. The SASE version of Mantis's best
ideas should be provider-neutral, permissioned, artifact-backed, SDD-linked, and visible in ACE/mobile rather than
implemented as another ad hoc assistant command router.
