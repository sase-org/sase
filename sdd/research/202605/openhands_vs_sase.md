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
- OpenHands docs: [microagents overview](https://docs.openhands.dev/openhands/usage/microagents/microagents-overview)
  describes KnowledgeMicroagent vs RepoMicroagent, frontmatter, and `.openhands/microagents/` loading order.
- OpenHands docs: [context condenser](https://docs.openhands.dev/sdk/guides/context-condenser) describes
  LLM-based summarization of older events to keep long sessions bounded.
- OpenHands docs: [agent delegation](https://docs.openhands.dev/sdk/guides/agent-delegation) describes
  `AgentDelegateAction`, sub-agent spawning, and `BrowsingAgent` as a delegation target.
- OpenHands [SDK V1 paper (arXiv 2511.03690)](https://arxiv.org/html/2511.03690v1) describes the composable
  event-loop kernel, condenser, persistence, and tool architecture.
- OpenHands [ICLR 2025 platform paper](https://arxiv.org/pdf/2407.16741v2) defines the original CodeAct/Action–
  Observation framing and BrowsingAgent results.
- [OpenHands Index, Jan 2026](https://www.openhands.dev/blog/openhands-index) reports SWE-bench Verified results
  for OpenHands+CodeAct paired with current frontier models.
- OpenHands GitHub: [Resolver action](https://docs.openhands.dev/openhands/usage/run-openhands/github-action)
  describes the `fix-me` label and `@openhands-agent` mention triggers and PyPI-based workflow.
- OpenHands [LICENSE](https://github.com/All-Hands-AI/OpenHands/blob/main/LICENSE) — MIT, except the
  `enterprise/` directory; community is ~65K+ GitHub stars and 180+ contributors.
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

## Architectural Foundations of OpenHands

Several OpenHands ideas don't fit neatly into a feature comparison but shape every surface above. They are worth
calling out because SASE's analogous primitives are differently positioned.

### CodeAct: Code as the Action Space

OpenHands' default agent (`CodeActAgent`) does not use a per-tool JSON-schema interface. Instead, every action is
expressed as code in one of three modalities — bash, Python, or a browser DSL — executed inside the runtime
sandbox. The original ICLR 2025 paper argues this generalizes better than schema-bound tool calls and dramatically
reduces parsing errors on long-horizon tasks. Specialized tools (file editor, task tracker, MCP servers) layer on
top, but the core "what can the agent do?" answer is "run code."

SASE in contrast leans on xprompts and skills as the composable surface; the underlying tool calls are normal
provider tool calls. The CodeAct lesson is not "switch SASE to code-actions" — it is that the *action interface*
between agent and runtime is itself a design choice with measurable empirical consequences, and SASE has not made
that choice explicit.

### Event–Action–Observation Loop

OpenHands models agent execution as a pure function from event history to next event, run in a loop. Every
interaction with the world is either an `Action` (decided by the agent) or an `Observation` (returned by the
runtime). Both are typed Pydantic models and persisted to an event log. State, replay, condensation, delegation,
and UI are all downstream of this single shape. SASE has rich agent state (artifacts dir, claims, status files,
ChangeSpec deltas) but no single equivalent typed-event substrate that all surfaces consume.

### Runtime as Execution Boundary

The Runtime is the explicit, swappable component that turns Actions into Observations — Docker, process, or remote
backends. This is what makes the sandbox story credible: the agent code path doesn't change when you swap
isolation modes. SASE's workspace abstraction is similar in spirit but stops short of being a full execution
boundary; tool calls escape directly to the host.

### Condenser: Bounded Context Without Forgetting

OpenHands ships an LLM-based condenser that, when the event log exceeds a threshold, drops older events and
replaces them with `CondensationEvent` summaries focused on user goals, progress, and outstanding work. Recent
events stay verbatim. The full event log is preserved on disk so condensation is purely a view-time transform,
not lossy persistence. OpenHands reports ~50% API-cost reduction and linear (vs quadratic) token growth on long
sessions. SASE has resume/handoff and dynamic memory but does not yet have a comparable in-conversation context
compaction primitive.

### Event Storage and Trajectory Replay

Because every action and observation is logged, OpenHands supports trajectory replay: a finished or interrupted
session can be re-driven from the event store for debugging, evaluation, or session restoration. This is also
what makes the SDK "stateless by default" — state is the event log; the agent function is pure. SASE captures
artifacts and chat transcripts but does not expose a stable replayable event trajectory.

### Agent Delegation and Sub-Agents

`AgentDelegateAction` lets the main agent spawn a specialist (e.g., `BrowsingAgent`) with its own conversation
context and consume only the result. This is structurally distinct from SASE's multi-agent xprompt fan-out:
fan-out launches sibling agents at *the user's* direction, while delegation is a tool the *agent* invokes
mid-task. SASE's `bead work` waves are the closest equivalent, but they are scheduled rather than agent-driven.

### Microagents (vs Skills/XPrompts)

OpenHands distinguishes two repo-local artifact types under `.openhands/microagents/`:

- **`RepoMicroagent`** — always-on, repo-specific instructions (e.g. `repo.md`); equivalent to SASE's
  always-loaded short memory plus AGENTS.md.
- **`KnowledgeMicroagent`** — keyword-triggered snippets with frontmatter declaring trigger words; equivalent to
  SASE's dynamic memory keyword matching.

Loading order is global (`skills/`) → user (`~/.openhands/microagents/`) → workspace (repo). Files use markdown
with optional YAML frontmatter. The newer `AgentSkills` standard adds per-skill directories with `SKILL.md` and
progressive disclosure. SASE has equivalent capabilities (short/long/dynamic memory tiers, xprompts, generated
skills), but the artifact taxonomy is more fragmented and less portable across projects.

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

### 11. In-Conversation Context Condensation

Long agent runs hit context limits. OpenHands' Condenser keeps recent turns intact and replaces older spans with
LLM-generated summaries describing user goals, progress, and remaining work, while retaining the full event log
on disk. Reported effect: ~50% API-cost reduction and linear (rather than quadratic) token growth across long
sessions.

SASE handles long sessions by re-launching with `#resume:` and curated handoff prompts. That works for explicit
boundaries (planner → coder) but does nothing for a single agent that simply runs long.

Inspiration for SASE:

- Add a condensation hook that runs at configurable token thresholds inside an in-progress agent.
- Persist a `CondensationEvent`-equivalent in the artifacts dir so the original transcript is recoverable.
- Make the condenser pluggable: identity (no-op), recent-N-turns, LLM-summarizer, or xprompt-driven.
- Surface condensation status in ACE so the user can see when context was compacted and what was preserved.

### 12. Sub-Agent Delegation as a Tool

OpenHands' `AgentDelegateAction` lets a generalist agent hand a sub-task to a specialist (`BrowsingAgent`,
research agents, etc.) and consume only the result. The delegated agent runs with its own conversation, returns
a summary, and the parent continues. This is fundamentally different from launching parallel siblings.

SASE has multi-agent xprompt fan-out and `bead work` phase scheduling, but both are user- or scheduler-driven.
The *agent itself* cannot decide mid-task to spawn a scoped sub-agent and resume.

Inspiration for SASE:

- Add a `delegate` tool/xprompt-action exposing the spawn-on-retry plumbing in a forward direction (parent waits
  for child, then ingests result instead of being replaced).
- Constrain delegated agents to a smaller context budget, restricted xprompts, and bounded wall time.
- Treat delegation as a normal event in the trajectory so it appears in ACE's agent tree.
- Use it for browsing, doc-lookup, and isolated-test-run subtasks where the parent doesn't need the full child
  transcript.

### 13. Persistent Trajectory and Replay

Because OpenHands persists every action and observation as typed events, sessions can be replayed deterministically
for debugging, evaluation, and recovery. The SDK paper explicitly treats the event log as the durable state and
the agent as a pure function over it.

SASE keeps artifacts dirs, chat transcripts, and `done.json` records, and the retry chain links parents to
children, but there is no single replayable typed trajectory that downstream tools (eval harnesses, ACE
debuggers, regression tests) can consume uniformly.

Inspiration for SASE:

- Make the agent event stream (P0 below) durable and replayable, not just live-streamable.
- Add `sase agent replay <timestamp>` that reconstructs the agent view from the event log without re-running tools.
- Use replay as the substrate for an internal eval harness over historical runs.

### 14. GitHub Resolver as a Drop-In Issue Worker

OpenHands ships a self-contained GitHub action — install the workflow, label an issue `fix-me` (or `@-mention`
`@openhands-agent` in a comment), and the resolver opens a draft PR. It is a published PyPI package, runs in CI,
and reports its own commit-authorship metrics. This is a much shorter onramp than "set up SASE locally, add a
provider plugin, and configure ingress."

SASE's GitHub plugin is more powerful for ongoing local work, but lacks a one-click issue-to-PR action.

Inspiration for SASE:

- Publish a `sase-resolver`-style GitHub Action that wraps `sase run` against an issue/PR comment trigger.
- Standardize the bot identity, label conventions (`sase-fix-me`), and PR template so it works without per-repo
  setup.
- Reuse the event-ingress design (P1 below) as the backend, with the action as the GitHub-specific frontend.

## License, Governance, and Benchmarks

These dimensions don't fit a feature table but matter for strategic positioning.

### License and Community Posture

OpenHands is **MIT-licensed** with the exception of the `enterprise/` directory (separately licensed for the
control-plane offering). The core agent, SDK, and Docker images are fully MIT. The project reports ~65K+ GitHub
stars and 180+ contributors, and is actively co-developed with academic research (ICLR 2025 platform paper,
SDK V1 paper on arXiv 2511.03690). The All-Hands-AI company offers a commercial Cloud and Enterprise tier on
top of the MIT core.

SASE's licensing and community posture should be a deliberate choice rather than a default. If SASE wants to
attract external contribution and integration, an explicitly permissive license, a clear contributor guide,
and a public roadmap will matter as much as the technical surface.

### Benchmark Performance

OpenHands+CodeAct paired with current frontier models reports competitive SWE-bench Verified results (e.g.
~68% with Claude Opus 4.6 in Jan 2026 OpenHands Index reporting). This matters less as an absolute number and
more as evidence that **the scaffold is independently reproducible** — anyone can clone the repo, point it at
their model, and benchmark. Reproducible eval is a credibility primitive.

SASE has no equivalent public benchmark story. That is fine for an internal workflow tool, but if SASE ever
wants to be evaluated head-to-head against OpenHands or Aider as a coding-agent platform, having a documented
SWE-bench-style runner (against the same model) would be the bar.

Inspiration for SASE:

- Build a thin eval harness that runs `sase run` against a fixed task corpus (start with internal beads/SDD
  fixtures, then SWE-bench-lite as a reach goal).
- Publish the harness output alongside model/version metadata so cost-vs-quality tradeoffs are visible.
- Use the trajectory replay primitive (item 13) to support deterministic re-evaluation of past runs against new
  models.

## Priority Recommendations for SASE

### P0: Normalized Agent Event Stream + Replayable Trajectory

This is the best leverage point because it supports UI, integrations, observability, mobile, web, debugging, and external
automation. Persisting the stream durably (not just live-tailing) also unlocks replay, eval, and retry-on-new-model.

Proposed artifact:

- `sase events tail --jsonl [--agent TIMESTAMP] [--project NAME]`
- `sase run --json` for headless consumers
- `sase agent replay <timestamp>` reconstructs view-state from the persisted event log
- Versioned event schema in docs
- ACE/AXE emit and consume the same events internally over time

OpenHands inspiration: headless JSONL action/observation output, persistent event log, deterministic SDK replay.

### P1: Context Condensation for Long Agent Runs

Long single-agent runs hit context limits today; the user mitigates this with `#resume:` between phases, but a
single coder/planner can still run out of room mid-task.

Proposed scope:

- Pluggable condenser interface; default no-op preserves current behavior.
- LLM-summarizer condenser preserves user goals, progress, and outstanding work; keeps last N turns verbatim.
- Persist a `condensation` event so the pre-condensed history is recoverable.
- Surface condensation status and what was preserved in ACE.

OpenHands inspiration: SDK Condenser with bounded context and full event-log preservation.

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
