# OpenHands vs. SASE Research

Research date: 2026-05-09

## Executive Summary

OpenHands and SASE overlap in the broad category of agentic software engineering, but their center of gravity is
different.

OpenHands is becoming a full agent platform: cloud/local GUI, CLI, headless mode, SDK, sandbox providers, hosted
automations, repository integrations, MCP, skills, hooks, and an enterprise control-plane story. Its strongest ideas for
SASE are the surfaces and safety boundaries around the agent: reproducible sandboxes, web review UI, embedded app/browser
preview, GitHub/GitLab/Bitbucket issue triggers, event-driven automations, structured JSONL event streams, and a
typed/stateless SDK core.

SASE is more opinionated about the long-lived engineering workflow: ChangeSpecs, ACE, AXE, xprompts, Beads, mentor
reviews, workspace claims, provider plugins, and SDD artifacts. SASE is better positioned for persistent local
coordination across many agents and changes, especially when the desired source of truth is git-native project state
rather than a hosted conversation product.

The highest-value inspiration from OpenHands is not to replace SASE's local-first model, but to add cleaner execution
boundaries, richer review/preview surfaces, and event/API interfaces around SASE's existing workflow state.

## Source Map

Primary OpenHands sources:

- OpenHands docs: [sandbox providers](https://docs.openhands.dev/openhands/usage/sandboxes/overview) describe Docker,
  process, and remote sandbox options.
- OpenHands docs: [skills overview](https://docs.openhands.dev/overview/skills) describes AGENTS.md, AgentSkills,
  keyword-triggered skills, organization/global skills, and skill loading precedence.
- OpenHands docs: [CLI headless mode](https://docs.openhands.dev/openhands/usage/cli/headless) describes no-UI execution
  and JSONL event output for automation.
- OpenHands docs: [terminal CLI](https://docs.openhands.dev/openhands/usage/cli/terminal) describes live status,
  command palette, confirmation modes, LLM approval, and conversation resume.
- OpenHands docs: [Cloud UI](https://docs.openhands.dev/openhands/usage/cloud/cloud-ui) describes repository selection,
  suggested tasks, recent conversations, settings, budget, secrets, API keys, and MCP.
- OpenHands docs: [key features](https://docs.openhands.dev/openhands/usage/key-features) describes chat, changes, VS
  Code, terminal, app, and browser tabs.
- OpenHands docs: [GitHub integration](https://docs.openhands.dev/openhands/usage/cloud/github-installation) describes
  repository access, short-lived tokens, issue labels/mentions, PR comments, and PR creation.
- OpenHands docs: [automations overview](https://docs.openhands.dev/openhands/usage/automations/overview) describes
  scheduled Cloud/Enterprise automations that run full conversations in fresh sandboxes.
- OpenHands docs: [event-based automations](https://docs.openhands.dev/openhands/usage/automations/event-automations)
  describes GitHub-event and custom-webhook triggers.
- OpenHands docs: [repository customization](https://docs.openhands.dev/openhands/usage/customization/repository)
  describes `.openhands/setup.sh`, hooks, and pre-commit scripts.
- OpenHands docs: [hooks](https://docs.openhands.dev/openhands/usage/customization/hooks) describes lifecycle hooks,
  blocking decisions, JSON stdin/stdout, Claude Code compatibility, and tool usage auditing.
- OpenHands docs: [MCP](https://docs.openhands.dev/overview/model-context-protocol) describes MCP support across CLI,
  SDK, local GUI, and Cloud.
- OpenHands SDK docs: [architecture overview](https://docs.openhands.dev/sdk/arch/overview) describes the SDK as source
  of truth for agents, LLMs, conversations, tools, workspaces, events, and security policies.
- OpenHands SDK docs: [design principles](https://docs.openhands.dev/sdk/arch/design) describes optional isolation,
  stateless/default state, strict application/core boundaries, and composable typed components.
- OpenHands blog: [March 2026 product update](https://www.openhands.dev/blog/openhands-product-update---march-2026)
  describes Planning Mode and GUI slash menu.
- OpenHands blog: [Enterprise control plane announcement](https://www.openhands.dev/blog/openhands-enterprise-agent-control-plane)
  describes sandboxed execution, auditability, policies, event triggers, and scale/governance framing.

Local SASE sources:

- [docs/index.md](../../../docs/index.md) for the SASE overview: ACE, AXE, XPrompts, ChangeSpecs, Beads, and provider
  plugins.
- [docs/ace.md](../../../docs/ace.md) for the ACE TUI, agents tab, ChangeSpec workflows, mentors, hooks, and navigation.
- [docs/workspace.md](../../../docs/workspace.md) for workspace provider abstractions, VCS/workspace plugin boundaries,
  `#cd`, `#git`, and known-project fallback.
- [docs/xprompt.md](../../../docs/xprompt.md) for xprompt discovery, typed inputs, workflows, LSP, dynamic memory, and
  multi-agent prompt fan-out.
- [docs/beads.md](../../../docs/beads.md) for Beads, SDD plan tiers, phase dependencies, SQLite/JSONL storage, and
  `sase bead work`.
- [docs/change_spec.md](../../../docs/change_spec.md) for ChangeSpec lifecycle and tracked work metadata.

## Product Shape

| Dimension | OpenHands | SASE |
| --- | --- | --- |
| Primary product | Coding-agent platform with local CLI, local GUI, Cloud, SDK, Cloud API, and Enterprise control plane. | Local-first workflow/orchestration toolkit around ACE TUI, AXE daemon, ChangeSpecs, Beads, xprompts, and plugins. |
| Main unit of work | Conversation/task, often attached to a repo, issue, PR/MR, automation, or webhook event. | ChangeSpec, agent run, SDD plan/epic/phase bead, prompt workflow. |
| Persistence model | Conversation history, cloud/local settings, repository customization, SDK conversation state. | Git-native workflow artifacts: `.gp` ChangeSpecs, SDD markdown, bead JSONL, agent artifacts, xprompt files. |
| Execution | Docker/process/remote sandboxes; Cloud and Enterprise use managed/remote execution. | Local process execution in cloned workspaces with workspace claims and provider-specific setup. |
| UI surfaces | Web GUI, embedded VS Code, terminal, app preview, browser tab, Cloud UI, CLI, headless JSONL, API. | Terminal TUI, CLI, Telegram/plugin surfaces, editor/LSP integrations, docs/catalog outputs. |
| Integrations | GitHub/GitLab/Bitbucket, Slack, Jira Cloud, MCP, Cloud API, custom webhooks, skill registry. | Pluggable VCS/workspace/LLM/notification integrations; GitHub, Mercurial/Google, bare git, Telegram, Chezmoi via plugins. |
| Workflow governance | Sandboxes, short-lived tokens, hooks, LLM approval, secrets, budgets, audit logs, enterprise policies. | ChangeSpec lifecycle, mentor profiles, AXE hooks, Bead dependencies, workspace claims, local observability. |

## Where SASE Is Stronger

### Persistent Engineering State

SASE has a richer model for long-lived software work. ChangeSpecs preserve status, parents, commits, deltas, hooks,
comments, mentors, and timestamps. Beads add plan/epic/legend tiers, dependencies, and phase execution. This makes SASE
stronger for coordinating a stream of related changes over days or weeks.

OpenHands is more conversation-oriented. It can attach to issues and PRs, but the source of truth is usually the hosted
conversation plus external provider objects, not a first-class local ChangeSpec/Bead graph.

### Local-First, Git-Native Operation

SASE's workflow can live inside the repo and the user's filesystem. Beads export JSONL for git portability, SDD artifacts
are markdown, and xprompts can be project-local. That is a major advantage for teams that want their process state to be
reviewable, branchable, and independent of a hosted service.

OpenHands has local modes, but many of its strongest workflow features are Cloud/Enterprise-first.

### Provider and VCS Abstraction

SASE's plugin boundary separates LLM, VCS, workspace, notification, and integration concerns. It can route work across
Claude, Gemini, Codex, GitHub, Mercurial, bare git, and local directories without tying the workflow model to one vendor.

OpenHands is also model-agnostic and supports multiple VCS hosts, but its best-integrated path is clearly its own
platform surfaces and hosted workflows.

### Prompt Workflow Composition

XPrompts are more compositional than OpenHands skills. SASE supports typed inputs, Jinja, discovery priority, inline
expansion, standalone workflows, graph/explain/catalog commands, LSP completion, dynamic memory, and multi-agent fan-out.

OpenHands skills are more productized and discoverable, but SASE's prompt system is more expressive as a workflow
language.

## What OpenHands Does Better

### 1. Execution Isolation and Permission Boundaries

OpenHands has a first-class sandbox model: Docker for stronger isolation, process mode for speed, and remote sandboxes
for managed deployments. It also layers confirmation modes, LLM approval, hooks that can block operations, short-lived
GitHub tokens in Cloud, secrets, and enterprise policy/audit framing.

SASE currently relies on local workspace isolation, PID/workspace claims, and workflow discipline. That is pragmatic and
fast, but it does not give users a crisp security boundary between the agent and the host.

Inspiration for SASE:

- Add an optional sandbox provider interface parallel to workspace providers: `local-process`, `docker`, `remote`.
- Treat permissions as explicit launch metadata visible in ACE: network, filesystem roots, secrets, VCS token scope.
- Make dangerous-command gates and stop hooks visible as first-class run policy, not just background workflow behavior.
- Consider short-lived scoped credentials for GitHub/GitLab plugins instead of ambient CLI auth where possible.

### 2. Full-Fidelity Review and Preview Surface

OpenHands' GUI has a chat panel, changes tab, embedded VS Code, terminal tab, app preview tab, and browser tab. This gives
the user a single place to inspect diffs, browse files, run commands, and interact with the app the agent is building.

ACE is powerful for ChangeSpec and agent navigation, but it remains text-first. For frontend/mobile/web work, the gap is
visible: SASE can orchestrate the agent, but the user still leaves the TUI for visual review and app interaction.

Inspiration for SASE:

- Add a web companion to ACE for agent artifacts, diffs, screenshots, running dev servers, and app previews.
- Keep ACE as the command surface, but let it open a browser-backed "review room" for a selected agent or ChangeSpec.
- Add a changes-focused panel that supports file-by-file diff review, inline comments, and hunk-level accept/reject.
- Surface generated images, screenshots, PDFs, and app previews as primary artifacts rather than secondary files.

### 3. Cloud/Remote Task Entry Points

OpenHands Cloud can start from GitHub issues, GitHub PR comments, GitLab issues/MRs, Bitbucket repositories, Slack, Jira
Cloud, Cloud API calls, scheduled automations, and event-based automations. It is designed so work can begin where the
signal appears.

SASE has Telegram and plugin hooks, but its strongest entry point is still a local user operating ACE/CLI.

Inspiration for SASE:

- Build a generic event ingress layer for "external task created" events: GitHub issue label, PR comment, Slack mention,
  webhook payload, schedule, CLI/API.
- Normalize all ingress into SDD/Bead/ChangeSpec-backed work items instead of ad hoc agent launches.
- Let users define xprompt-backed event automations in repo-local files, with event filters and permissions.
- Make external comments/status updates a standard notification provider capability.

### 4. Structured Machine-Readable Event Streams

OpenHands headless mode can stream JSONL action/observation events. This is small but important: it makes the agent
runtime easy to embed in CI/CD, logging pipelines, dashboards, and external automation.

SASE has rich local state and telemetry, but agent activity is not exposed as a simple stable stream that another process
can consume without understanding SASE internals.

Inspiration for SASE:

- Add `sase run --json` or `sase events tail --jsonl` for normalized agent lifecycle events.
- Include event types such as `agent.started`, `tool.requested`, `tool.completed`, `file.changed`, `plan.updated`,
  `mentor.comment`, `agent.blocked`, `agent.completed`, and `changespec.updated`.
- Use the same event schema for ACE, AXE, mobile/web clients, Telegram, and observability exporters.
- Make event replay a debugging primitive: given an agent timestamp, replay the high-level event stream.

### 5. SDK as the Agent Core Source of Truth

OpenHands V1 explicitly separates SDK, tools, workspace, agent server, and applications. Its SDK docs emphasize immutable
typed components, one mutable conversation state, deterministic replay, and applications consuming SDK APIs rather than
embedding application-specific agent conditionals.

SASE is moving core logic into Rust, and that boundary is healthy. The OpenHands lesson is to make the boundary a
product-grade SDK/API story, not only an internal performance and correctness story.

Inspiration for SASE:

- Define a stable SASE core API around agents, workspaces, prompts, events, ChangeSpecs, Beads, hooks, and notifications.
- Keep ACE, CLI, Telegram, mobile, and future web clients as consumers of that API.
- Make state replay/restoration an explicit invariant for agent runs and ChangeSpec transitions.
- Prefer typed schemas for hooks, events, and workflow state over shell/text conventions where practical.

### 6. Productized Skills and Discovery

SASE xprompts are powerful, but OpenHands makes skills more approachable: `AGENTS.md` for permanent context, AgentSkills
for progressive disclosure, keyword-triggered skills, organization/global skills, a managed skill library, GUI slash menu,
and UI visibility into loaded skills/hooks/MCP servers.

SASE has dynamic memory, xprompt LSP, catalog PDFs, snippets, and skills generated from xprompts, but discovery still
feels more engineer-facing.

Inspiration for SASE:

- Add an ACE skills/xprompt browser with search, tags, preview, provenance, trigger words, and argument hints.
- Show "loaded context" for a launch: AGENTS.md files, dynamic memories, xprompts, skills, hooks, MCP/tools.
- Consider adopting `.agents/skills/SKILL.md` as a first-class import/export format while preserving xprompt workflows.
- Add organization/team skill registries through existing plugin/config mechanisms.

### 7. Hooks Compatibility and UX

OpenHands hooks are simple, visible, and compatible with Claude Code hook structure. They support lifecycle events such
as PreToolUse, PostToolUse, UserPromptSubmit, Stop, SessionStart, and SessionEnd, with JSON stdin/stdout and a blocking
exit-code convention.

SASE already has hooks, mentors, AXE, and stop/commit workflows, but OpenHands' hook UX is easier to explain and share
across tools.

Inspiration for SASE:

- Expose a compatibility layer for `.openhands/hooks.json` / Claude-style hooks.
- Standardize hook payloads and decisions as JSON schemas.
- Show active hooks and their last decisions in ACE per agent/ChangeSpec.
- Add a hook dry-run/test command that pipes fixture JSON into hook scripts.

### 8. MCP Support Across All Surfaces

OpenHands documents MCP support across CLI, SDK, local GUI, and Cloud, with configuration and status visibility. This
positions external tools as part of the normal product, not an advanced escape hatch.

SASE's plugin system covers many similar needs, but MCP is becoming the lingua franca for external tool access.

Inspiration for SASE:

- Treat MCP servers as another provider type with explicit status in ACE.
- Add xprompt access to MCP tool availability and schemas.
- Support per-project MCP config in SDD or repo-local config, with secrets handled separately.
- Include MCP connection and tool-call events in the normalized event stream.

### 9. Hosted Collaboration, Sharing, and Budget Controls

OpenHands Cloud includes recent conversations, shareable conversation context, API keys, secrets, budget per
conversation, notifications, and settings in a product UI. Even if SASE remains local-first, these are useful control
patterns.

SASE has strong local artifacts, but a new user has to understand multiple files and commands before they feel in
control.

Inspiration for SASE:

- Add per-agent budget/limit metadata in ACE and config: max tool calls, max tokens/cost, max wall time, max file count.
- Add share/export views for a completed agent: prompt, dynamic context, events, diff, tests, artifacts, final answer.
- Add a "recent work" dashboard that merges ChangeSpecs, beads, agents, and notifications around user intent.

### 10. Onboarding and Default Experience

OpenHands offers Cloud as the fastest path, a local CLI, a Docker-backed local GUI, headless mode, and explicit quick
starts. The user can get a useful visual loop before learning internals.

SASE is more powerful once configured, but the first-run path has more concepts: ACE, AXE, ChangeSpecs, Beads, xprompts,
providers, workspaces, agents, and SDD tiers.

Inspiration for SASE:

- Create a guided first-run command that initializes a repo, explains available xprompts, starts ACE, and launches a safe
  sample task.
- Add a "what can I do here?" panel in ACE based on detected repo/provider state.
- Build small vertical demos: local repo task, GitHub issue task, SDD epic task, mentor review task.
- Keep advanced concepts visible but progressively disclosed.

## Priority Recommendations for SASE

### P0: Normalized Agent Event Stream

This is the best leverage point because it supports UI, integrations, observability, mobile, web, debugging, and external
automation.

Proposed artifact:

- `sase events tail --jsonl [--agent TIMESTAMP] [--project NAME]`
- `sase run --json` for headless consumers
- Versioned event schema in docs
- ACE/AXE emit and consume the same events internally over time

OpenHands inspiration: headless JSONL action/observation output.

### P1: Optional Sandboxed Execution Provider

Add a provider boundary that can run agents in local process mode by default and Docker/remote mode when configured.

Proposed scope:

- Start with Docker for `#cd` or bare-git workspaces.
- Mount only the selected workspace plus a controlled temp/artifact directory.
- Expose sandbox policy in agent metadata.
- Add preflight diagnostics in ACE.

OpenHands inspiration: Docker/process/remote sandbox providers and Enterprise execution-boundary framing.

### P1: ACE Review/Preview Companion

Keep ACE terminal-native, but add a browser companion focused on visual review.

Proposed scope:

- Agent artifact browser
- Diff viewer with inline notes
- Screenshot/PDF/image rendering
- Dev-server/app preview links
- Shareable static export for completed work

OpenHands inspiration: Changes, VS Code, Terminal, App, and Browser tabs.

### P1: Event Ingress for Repo/Chat/Webhook Tasks

SASE should map external events into durable SASE workflow objects.

Proposed scope:

- `sase ingress` daemon/API receives GitHub labels/comments, Slack/Telegram messages, custom webhooks, and schedules.
- Event filters map to xprompts/workflows.
- Each accepted event creates or updates a Bead/ChangeSpec and launches an agent with explicit provenance.

OpenHands inspiration: GitHub/GitLab issue and PR mentions, scheduled automations, event-based automations, custom
webhooks.

### P2: Skills/XPrompt Discovery UX

Make SASE's stronger prompt system easier to inspect and use.

Proposed scope:

- ACE xprompt/skill catalog tab or modal
- Slash-style completion in prompt inputs
- Launch preview showing loaded context, dynamic memories, skills, hooks, and MCP/tool servers
- Optional import/export compatibility with AgentSkills `SKILL.md`

OpenHands inspiration: skill registry, GUI slash menu, loaded skills visibility.

### P2: Hook Schema and Compatibility Layer

Standardize the user-facing hook format.

Proposed scope:

- JSON stdin/stdout schema for SASE hook lifecycle events
- Compatibility parser for `.openhands/hooks.json` and Claude-style event names
- ACE hook status and history
- `sase hook test` command

OpenHands inspiration: simple lifecycle hooks with blocking decisions and Claude Code compatibility.

## Suggested SASE Design Principle

OpenHands' strongest strategic lesson is that agent platforms need a narrow, stable execution kernel and many surfaces
around it. SASE already has the workflow model; the next step is to make the execution/events/policy boundary just as
explicit as ChangeSpecs and Beads.

Put differently:

- ChangeSpecs and Beads should remain the durable workflow source of truth.
- Agents should emit typed events into that workflow graph.
- Execution should happen under an explicit local/sandbox/remote policy.
- Every UI or integration should consume the same state and event APIs.

That would let SASE keep its local-first, git-native advantages while taking the best of OpenHands' platform ergonomics.
