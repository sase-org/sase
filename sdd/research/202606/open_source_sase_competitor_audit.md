# Open Source SASE Competitor GitHub Audit

Research date: 2026-06-07

## Question

What open-source projects compete directly with SASE as an agentic software engineering control plane?

## SASE Baseline

SASE is not just a coding agent runtime. Per the local README, it orchestrates coding agents into tracked, repeatable
engineering workflows with isolated workspaces, reusable prompts, scheduling, status, review state, commit flow,
ChangeSpecs, XPrompts, Beads, mentors, memory, notifications, plugins, and ACE/AXE.

That means the most direct competitors are projects that try to own one or more of these layers:

- ticket/issue to PR execution
- multi-agent or parallel-agent orchestration
- worktree/sandbox isolation
- reusable workflow definitions
- plan/review/commit/merge feedback loops
- developer cockpit, dashboard, or ADE over multiple agent runs
- persistent engineering state beyond a single chat

Terminal coding agents such as OpenCode, Cline, Goose, Aider, Qwen Code, Gemini CLI, and Codex CLI are important, but
they are partly SASE inputs rather than direct replacements. They compete for daily user attention; projects like Optio,
Open SWE, Gas Town, Archon, OpenHands, Emdash, and OpenADE compete more directly with SASE's control-plane layer.

## Method

- GitHub metadata was collected with `gh repo view ... --json` on 2026-06-07.
- Feature claims were checked against project READMEs, docs, or landing pages.
- Existing SASE research was reviewed first to avoid duplicating prior OpenHands, Gas Town, Hermes, Mantis, Codex, and
  CLI-runtime notes.

GitHub stars are directional only. The 2026 agent-tools market has abrupt launches, repo renames, social amplification,
and fast-moving docs, so directness and architecture matter more than stars alone.

## Executive Summary

The closest direct competitors are:

1. **Optio** - self-hosted Kubernetes control plane that drives tickets to merged PRs, including CI/review feedback and
   auto-merge.
2. **Gas Town** - multi-agent workspace manager with a coordinator-agent model, Beads/Dolt state, tmux sessions, and a
   merge/refinery pipeline.
3. **Archon** - deterministic YAML workflow engine for AI coding agents, with worktree isolation, validation gates, PR
   creation, web UI, and project-portable workflows.
4. **Open SWE** - LangChain's open-source internal coding-agent pattern: Slack/Linear/GitHub triggers, cloud sandboxes,
   subagents, middleware, and automatic PR creation.
5. **OpenHands** - the largest open-source agentic development platform: SDK, CLI, local GUI, Cloud, Enterprise,
   sandbox/runtime model, integrations, and an agent platform story.
6. **Emdash** - local-first desktop ADE for running many coding-agent CLIs in isolated git worktrees, with tickets,
   diffs, PRs, CI checks, and remote SSH projects.
7. **OpenADE** - local desktop ADE around Claude Code and Codex with Plan -> Revise -> Execute, multi-agent planning,
   worktrees, snapshots, diff/file/terminal panels, and comments on agent output.
8. **Agent Smith** - small but architecturally direct ticket-to-PR system with per-repo sandboxes, plan/result/decision
   logs, tracker integrations, multi-role pipelines, and cost accounting.

The main pattern: "AI coding agent" is splitting into two layers. The lower layer is the runtime/harness (OpenCode,
Cline, Goose, Aider, Qwen Code, mini-SWE-agent). The upper layer is the workflow control plane (Optio, Open SWE,
Archon, Emdash, OpenADE, Gas Town). SASE lives in the upper layer.

## Direct Competitor Table

| Project | GitHub signal on 2026-06-07 | Last push | License | Why it competes with SASE |
| --- | ---: | --- | --- | --- |
| [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands) | 76,082 stars / 9,656 forks | 2026-06-07 | MIT except `enterprise/` | Full agentic development platform: SDK, CLI, local GUI, Cloud, Enterprise, integrations, sandbox/runtime architecture, and task/conversation execution. |
| [coleam00/Archon](https://github.com/coleam00/Archon) | 22,225 / 3,358 | 2026-06-07 | MIT | YAML workflow engine for AI coding agents: plan, implement, validate, review, approve, PR; isolated worktrees; CLI and web dashboard. |
| [gastownhall/gastown](https://github.com/gastownhall/gastown) | 15,768 / 1,473 | 2026-06-06 | MIT | Multi-agent SWE workspace manager around Beads, tmux, Dolt, "Mayor"/worker roles, health monitors, and merge/refinery ideas. |
| [langchain-ai/open-swe](https://github.com/langchain-ai/open-swe) | 9,928 / 1,126 | 2026-06-07 | MIT | Internal-coding-agent framework: Slack, Linear, GitHub triggers; sandbox providers; subagents; middleware; automatic PRs. |
| [generalaction/emdash](https://github.com/generalaction/emdash) | 4,779 / 490 | 2026-06-07 | Apache-2.0 | Desktop ADE for parallel coding agents in git worktrees, ticket intake, diff review, PR creation, CI checks, merge, and SSH remote projects. |
| [jonwiggins/optio](https://github.com/jonwiggins/optio) | 975 / 110 | 2026-05-07 | MIT | Self-hosted AI engineering platform: ticket to merged PR, reusable jobs, persistent agents, K8s pods, review agent, CI feedback loop, auto-merge. |
| [bearlyai/OpenADE](https://github.com/bearlyai/OpenADE) | 308 / 21 | 2026-06-02 | README says MIT; GitHub API license null | Local ADE for Claude Code/Codex: plan/revise/execute, HyperPlan, comments, MCP connectors, snapshots, worktrees, diff/file/terminal/process UI. |
| [holgerleichsenring/agent-smith](https://github.com/holgerleichsenring/agent-smith) | 17 / 3 | 2026-06-06 | MIT | Ticket-to-PR pipeline with tracker integrations, sandboxed repo clones, role skills, cost accounting, and persistent plan/result/decisions artifacts. |

## High-Signal Profiles

### Optio

Source: [GitHub](https://github.com/jonwiggins/optio), [site](https://optio.host/)

Optio is the most direct "SASE for teams/platforms" competitor found in this pass. Its README positions it as a
self-hosted AI engineering platform with three tiers:

- **Tasks**: tickets to merged PRs, including agent execution, PR creation, CI watching, code review, automatic fixes,
  squash-merge, and issue closeout.
- **Jobs**: reusable parameterized agent work without repo checkout.
- **Persistent Agents**: long-lived named agents with inboxes, trigger sources, and inter-agent HTTP APIs.
- **Connections**: external services and MCP-compatible servers injected into agent pods.

The architecture is much heavier than SASE's local-first filesystem model: Fastify API, Next.js dashboard, BullMQ,
Postgres, Redis, Kubernetes repo pods, and Helm. The strategic threat is not single-developer ergonomics. It is the
enterprise story SASE does not yet tell crisply: a self-hosted control plane with ticket intake, CI/review feedback,
auto-merge, cost tracking, and auditable state in one dashboard.

SASE advantages:

- richer local ChangeSpec/Bead/SDD model for one developer supervising many changes
- provider/VCS/workspace plugin boundaries already proven across local workflows
- lower operational burden than K8s/Postgres/Redis

SASE gaps exposed:

- no one-command "issue to merged PR" product path
- no first-class CI/review feedback loop that automatically resumes agents and merges
- no web dashboard equivalent for platform teams

### Gas Town

Source: [GitHub](https://github.com/gastownhall/gastown), existing local research
[sase_vs_gastown.md](../202605/sase_vs_gastown.md)

Gas Town is already covered in prior SASE research, but it remains one of the clearest direct competitors because it is
also a multi-agent SWE orchestration layer over existing coding agents.

The notable competitive ideas are:

- a permanent coordinator agent ("Mayor") the user talks to about the worker agents
- tmux-managed worker sessions instead of SASE's subprocess/workspace model
- Dolt/SQL as canonical state rather than mostly human-editable files plus SQLite indexes
- Bead-driven work units and a landing/refinery pipeline
- health-monitoring roles such as Witness/Deacon/Boot

SASE advantages:

- ChangeSpec is a stronger PR/review narrative artifact than Gas Town's bead-centered model
- XPrompts are a more expressive workflow language than role templates
- workspace clones are cleaner than tmux keystroke injection for local repo work

SASE gaps exposed:

- no always-on coordinator agent
- no first-class agent health subsystem
- no merge/refinery queue for many agent-produced PRs

### Archon

Source: [GitHub](https://github.com/coleam00/Archon), [docs](https://archon.diy)

Archon is a deterministic workflow layer for AI coding agents. The README's core claim is that development processes
should be encoded as YAML workflows with phases, validation gates, and artifacts; AI is used at selected nodes rather
than driving the entire process ad hoc.

The overlap with SASE is strong:

- project-portable workflow definitions in `.archon/workflows/`
- worktree isolation for parallel runs
- AI and deterministic nodes in the same DAG
- loops until tasks/tests/approval conditions are met
- human approval gates
- PR creation
- web dashboard and workflow builder

Archon is closer to SASE XPrompts than most projects on this list. Its differentiator is messaging and packaging: "like
GitHub Actions for AI coding workflows" is immediately legible. SASE has many of the primitives, but XPrompts do not yet
have that crisp external category.

SASE advantages:

- deeper work-state model across ChangeSpecs, Beads, mentors, memory, AXE, and ACE
- more mature multi-provider local orchestration
- SDD artifacts give SASE a stronger long-horizon planning trail

SASE gaps exposed:

- XPrompts need simpler marketing, examples, and workflow-builder-style discoverability
- SASE should make loop/gate/worktree/PR patterns obvious in the first-run experience

### Open SWE

Source: [GitHub](https://github.com/langchain-ai/open-swe), [announcement](https://www.langchain.com/blog/introducing-open-swe-an-open-source-asynchronous-coding-agent)

Open SWE is explicitly positioned as the open-source version of internal coding agents built by elite engineering orgs.
The README frames the pattern as Slackbots, CLIs, and web apps connected to internal systems, with the right context,
permissioning, and safety boundaries.

Key overlap:

- cloud sandboxes per task, with pluggable providers such as Modal, Daytona, Runloop, and LangSmith
- Slack, Linear, and GitHub invocation
- deterministic thread IDs for follow-ups
- AGENTS.md context injection
- subagent support via Deep Agents
- middleware around the agent loop
- automatic commit, draft PR creation/update, and source-channel replies

This competes with SASE's future team/internal-agent story more than today's single-user ACE workflow. The sharpest
lesson is the internal-platform narrative: SASE has the local artifacts and workflow vocabulary, but Open SWE presents a
clear organizational architecture.

SASE advantages:

- local-first state and SDD/ChangeSpec/Bead source of truth
- ACE/AXE give a mature single-developer cockpit and scheduler
- provider-neutral wrappers around existing coding CLIs

SASE gaps exposed:

- no pluggable sandbox provider boundary
- no Slack/Linear-first async task path in the core product
- no middleware/event-loop abstraction comparable to LangGraph/Deep Agents

### OpenHands

Source: [GitHub](https://github.com/OpenHands/OpenHands), existing local research
[openhands_vs_sase.md](../202605/openhands_vs_sase.md)

OpenHands remains the largest open-source project in this space by GitHub adoption. Its README now describes several
surfaces:

- Software Agent SDK
- CLI
- Local GUI
- Cloud
- Enterprise
- evaluation infrastructure and adjacent tools

It is broader than SASE and more platform-shaped. SASE is deeper in local engineering workflow state; OpenHands is
stronger in sandboxes, GUI/cloud surfaces, SDK/product packaging, and enterprise integrations.

SASE advantages:

- ChangeSpecs, Beads, mentors, xprompts, and SDD are a richer local workflow model than conversations alone
- local-first and git-native artifacts are stronger for users who want process state inside their repos

SASE gaps exposed:

- no official local GUI or web cockpit comparable to OpenHands Local GUI
- weaker execution isolation story
- no SDK/event substrate that all frontends consume

### Emdash

Source: [GitHub](https://github.com/generalaction/emdash), [docs/site](https://emdash.sh)

Emdash is a desktop app for running multiple coding agents in parallel. Each task gets a git worktree and branch; the
app supports ticket intake from Linear, GitHub, Jira, GitLab, Asana, Featurebase, Monday.com, Forgejo, or Plain; it can
review diffs, create PRs, inspect CI checks, merge, and work over SSH/SFTP.

This is a direct UX competitor to ACE for users who want a graphical cockpit over agent work. It does not appear as
workflow/SDD-heavy as SASE, but it has a very clear product shape: "run multiple coding agents at once without juggling
terminals."

SASE advantages:

- richer workflow model and local artifacts
- stronger prompt/workflow/memory/Bead ecosystem

SASE gaps exposed:

- no desktop diff/PR/CI cockpit
- remote project support is less productized
- ticket intake breadth is narrower

### OpenADE

Source: [GitHub](https://github.com/bearlyai/OpenADE), [site](https://openade.ai/)

OpenADE is a local desktop ADE around Claude Code and Codex. Its workflow is Plan -> Revise -> Execute. Users refine
plans with comments before letting the agent execute linearly. It also advertises HyperPlan multi-agent planning,
comment-on-anything, MCP connectors, local/offline operation, file/diff/terminal/process UI, git snapshots, worktrees,
notifications, and usage stats.

OpenADE is small by GitHub signal but very direct in product framing. It competes for the "agent cockpit" layer and
for SASE's plan-first workflow story.

SASE advantages:

- deeper durable work model than a desktop planning UI
- multi-runtime provider/plugin architecture beyond Claude Code/Codex
- SDD and ChangeSpec artifacts are better for long-running project history

SASE gaps exposed:

- SASE plan review is powerful but less visually immediate
- no "comment on anything" review surface across files/diffs/agent output
- git snapshots/rollback are a user-facing affordance SASE could package better

### Agent Smith

Source: [GitHub](https://github.com/holgerleichsenring/agent-smith), [docs](https://docs.agent-smith.org/)

Agent Smith is small but architecturally relevant. It is a self-hosted ticket-to-PR pipeline that supports Azure DevOps,
Jira, GitHub Issues, GitLab Issues, several LLM providers, CLI/Docker/Kubernetes hosting, and role skills in a separate
repo. Each run writes `plan.md`, `result.md`, and `decisions.md` under `.agentsmith/runs/{run-id}/`.

Its strongest overlap with SASE is the insistence on a paper trail for "why" the agent made decisions. SASE has richer
SDD, research, Bead, and ChangeSpec artifacts, but Agent Smith presents the idea with very little ceremony.

SASE advantages:

- broader multi-agent and local cockpit model
- provider/runtime wrappers rather than direct provider APIs only
- richer planning tiers and git-portable Beads

SASE gaps exposed:

- SASE could make per-run plan/result/decision artifacts more obvious and standardized
- ticket-to-PR path should be a named workflow, not assembled from separate primitives

## Important Adjacent Projects

These are not all direct control-plane competitors, but they shape the ecosystem SASE has to position around.

| Project | GitHub signal on 2026-06-07 | Last push | Role |
| --- | ---: | --- | --- |
| [anomalyco/opencode](https://github.com/anomalyco/opencode) | 171,018 stars / 20,492 forks | 2026-06-07 | Open-source terminal coding agent. SASE can wrap it, but it competes for default terminal-agent usage. |
| [cline/cline](https://github.com/cline/cline) | 62,869 / 6,627 | 2026-06-07 | IDE/CLI/SDK autonomous coding agent. More runtime than control plane, but with its own workflow surface. |
| [ruvnet/ruflo](https://github.com/ruvnet/ruflo) | 58,300 / 6,686 | 2026-06-07 | Claude Code/Codex meta-harness with swarms, memory, plugins, background workers, and federation. Very broad; direct in orchestration vocabulary. |
| [Aider-AI/aider](https://github.com/Aider-AI/aider) | 45,850 / 4,557 | 2026-05-22 | Mature terminal pair-programmer. Not a SASE replacement, but a high-adoption baseline for terminal coding ergonomics. |
| [aaif-goose/goose](https://github.com/aaif-goose/goose) | 47,134 / 4,966 | 2026-06-06 | Open-source local agent runtime with MCP/ACP and headless surfaces. Potential SASE provider and competing daily driver. |
| [QwenLM/qwen-code](https://github.com/QwenLM/qwen-code) | 24,986 / 2,472 | 2026-06-07 | Terminal coding agent. SASE already supports it as a runtime family. |
| [SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent) | 19,444 / 2,118 | 2026-06-06 | Research/benchmark lineage for autonomous issue fixing; README now recommends mini-SWE-agent for most users. |
| [SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | 4,988 / 680 | 2026-06-06 | Minimal issue-solving agent and benchmark baseline; more runtime/research than workflow control plane. |
| [plandex-ai/plandex](https://github.com/plandex-ai/plandex) | 15,441 / 1,141 | 2025-10-03 | Terminal planning/execution agent for large code tasks; Plandex Cloud is winding down, but local/self-hosted remains relevant. |
| [The-PR-Agent/pr-agent](https://github.com/The-PR-Agent/pr-agent) | 11,520 / 1,556 | 2026-06-06 | PR review automation. Competes with SASE mentors/review surfaces, not agent execution. |
| [modu-ai/moai-adk](https://github.com/modu-ai/moai-adk) | 1,058 / 195 | 2026-06-07 | Spec-first agentic development kit for Claude Code with many agents, skills, TDD/DDD gates. Adjacent to XPrompts/skills. |
| [kevinelliott/agentpipe](https://github.com/kevinelliott/agentpipe) | 132 / 21 | 2026-03-30 | TUI/CLI for multi-agent conversations between coding CLIs. Adjacent to SASE multi-agent orchestration, but not PR-lifecycle-heavy. |
| [ItsWendell/palot](https://github.com/ItsWendell/palot) | 116 / 15 | 2026-05-18 | Desktop GUI for OpenCode multi-agent sessions, diffs, commits, pushes, PRs. Small but directionally similar to ACE-as-cockpit. |
| [akemmanuel/OpenGUI](https://github.com/akemmanuel/OpenGUI) | 64 / 6 | 2026-06-06 | Desktop/web command center for multiple coding-agent backends. Small, but same cockpit theme. |
| [openkaiden/kaiden](https://github.com/openkaiden/kaiden) | 76 / 30 | 2026-06-05 | Open agentic workspace/ADE with governed isolated agents. Early/small. |
| [griffinwork40/agent-afk](https://github.com/griffinwork40/agent-afk) | 9 / 1 | 2026-06-07 | Local-first CLI for supervising/resuming coding agents across terminal/chat. Too new for conclusions, but directly SASE-shaped. |

## Older Or Less Direct Projects

These are worth knowing but should not dominate SASE positioning:

- [stitionai/devika](https://github.com/stitionai/devika): strong "open-source Devin alternative" historical signal
  (19,510 stars), but last push found was 2025-09-25 and the product shape is older single-agent/autonomous-engineer.
- [Pythagora-io/gpt-pilot](https://github.com/Pythagora-io/gpt-pilot): 33,748 stars, "AI developer" lineage, useful for
  app-generation history, but less direct for SASE's ongoing multi-change repo workflow.
- [AntonOsika/gpt-engineer](https://github.com/AntonOsika/gpt-engineer): 55,202 stars but archived; now mostly a
  historical predecessor to Lovable-style app generation.
- Generic agent frameworks such as Dapr Agents, AgentScope, AutoGen/CrewAI-like systems, and LangGraph are infrastructure
  rather than SASE replacements unless packaged into a coding-agent workflow product.

## Competitive Axes

### 1. Ticket To Merged PR Is Becoming The Core Category

Optio, Open SWE, Agent Smith, OpenHands Cloud, and Emdash all present some version of:

1. ingest issue/ticket/comment
2. provision isolated workspace or sandbox
3. run one or more agents
4. run tests/checks/reviews
5. open or update PR
6. handle review/CI feedback
7. merge or close the loop

SASE has pieces of this across ChangeSpecs, VCS plugins, mentors, hooks, commit finalizer, Beads, and AXE, but the
workflow is not yet packaged as a single obvious product path.

### 2. Worktrees/Sandboxes Are Table Stakes

Every serious competitor advertises isolation:

- SASE: numbered workspace clones with claims
- Emdash/OpenADE/Archon/Optio: git worktrees
- OpenHands/Open SWE/Agent Smith/Optio: Docker/cloud/K8s sandboxes
- mini-SWE-agent: local, Docker/Podman, Singularity/Apptainer, bubblewrap, and other environment choices

SASE's workspace isolation is ergonomic, but it is not a security sandbox. Competitors are increasingly saying
"isolate first, then give full permissions inside the boundary." SASE should either add an optional sandbox provider or
be explicit that its isolation is concurrency-oriented, not host-security-oriented.

### 3. Workflow Languages Are Becoming Productized

Archon is the strongest warning here. SASE XPrompts are powerful, but Archon says "YAML workflows for AI coding, like
GitHub Actions." Optio says "Tasks, Jobs, Persistent Agents." Open SWE says "internal coding-agent architecture."

SASE should make XPrompts more legible as:

- reusable workflow DAGs
- deterministic plus agentic steps
- gates, loops, approvals, and artifacts
- provider-neutral execution

### 4. Cockpits Are Moving Beyond Terminal TUIs

ACE is a strong terminal cockpit, but Emdash/OpenADE/OpenHands/OpenGUI/Palot show the market pulling toward desktop/web
surfaces with:

- diff review
- comments on generated work
- PR/CI state
- worktree switching
- agent logs and live streams
- usage/cost stats
- notifications

SASE can keep ACE for power users, but should expect users to compare it against graphical ADEs.

### 5. Persistent Coordinator Agents Are Reappearing

Gas Town's Mayor, Optio Persistent Agents, ADE's "CTO" framing, Ruflo swarms, and AgentPipe rooms all point at the same
idea: users want an agent-facing control plane, not only a human-operated dashboard.

SASE has AXE and ACE, but not an always-on conversational coordinator over SASE state.

### 6. Decision Trails Are A Differentiator

Agent Smith's `.agentsmith/runs/{run-id}/plan.md`, `result.md`, and `decisions.md` is simple and compelling. SASE has a
richer SDD corpus, plans, research, tales, Beads, ChangeSpecs, and agent artifacts, but the per-run "why trail" could be
made more explicit.

## SASE Positioning Recommendations

1. **Name the category:** "local-first agentic SWE control plane" is more precise than "coding agent." SASE should
   distance itself from runtime-only projects and compete with Optio/Open SWE/Archon/Gas Town/OpenHands.
2. **Ship a canonical issue-to-PR workflow:** one command/xprompt that creates/updates a ChangeSpec, provisions a
   workspace, runs an agent, runs mentors/checks, creates/updates PR, and records artifacts.
3. **Make XPrompts externally legible:** document them as workflow DAGs for coding agents, with examples that mirror
   Archon's plan/implement/test/review/approve/PR path.
4. **Package the SDD/decision trail:** standardize per-run `plan`, `result`, `decisions`, `tests`, and `review`
   artifacts even when the work is launched outside a full SDD epic.
5. **Clarify workspace vs sandbox:** either add a `sandbox_provider` boundary or state clearly that SASE workspaces are
   for concurrency/reproducibility, not hostile-code containment.
6. **Add or prototype a coordinator agent:** a named always-on agent that can query SASE state, summarize active work,
   launch xprompts, and answer "what should I do next?"
7. **Prioritize feedback-loop automation:** auto-resume on CI failure, review comments, merge conflicts, mentor
   findings, and stale branches. This is where Optio and Open SWE are crisp.
8. **Watch the ADE layer:** Emdash/OpenADE are small compared with OpenHands, but their UX claims map directly to ACE's
   future competition: diffs, comments, worktrees, PRs, and notifications in one place.

## Best Follow-Up Research Targets

The existing corpus already has deep notes for OpenHands and Gas Town. The highest-value next deep dives are:

1. **Optio vs SASE** - because it is the clearest self-hosted ticket-to-merged-PR control-plane competitor.
2. **Archon vs SASE XPrompts** - because it competes directly with SASE's workflow language and packaging.
3. **Open SWE vs SASE** - because it captures the internal-agent/platform-team pattern SASE may want to claim.
4. **Emdash/OpenADE vs ACE** - because they are shaping user expectations for the graphical agent cockpit.

## Source Index

- SASE README: ../../../README.md
- SASE vs Gas Town local research: ../202605/sase_vs_gastown.md
- OpenHands local research: ../202605/openhands_vs_sase.md
- OpenHands: https://github.com/OpenHands/OpenHands
- Optio: https://github.com/jonwiggins/optio and https://optio.host/
- Gas Town: https://github.com/gastownhall/gastown
- Archon: https://github.com/coleam00/Archon and https://archon.diy
- Open SWE: https://github.com/langchain-ai/open-swe and
  https://www.langchain.com/blog/introducing-open-swe-an-open-source-asynchronous-coding-agent
- Emdash: https://github.com/generalaction/emdash and https://emdash.sh
- OpenADE: https://github.com/bearlyai/OpenADE and https://openade.ai/
- Agent Smith: https://github.com/holgerleichsenring/agent-smith and https://docs.agent-smith.org/
- SWE-agent: https://github.com/SWE-agent/SWE-agent
- mini-SWE-agent: https://github.com/SWE-agent/mini-swe-agent
- Plandex: https://github.com/plandex-ai/plandex
- Ruflo: https://github.com/ruvnet/ruflo
- OpenCode: https://github.com/anomalyco/opencode
- Cline: https://github.com/cline/cline
- Aider: https://github.com/Aider-AI/aider
- Goose: https://github.com/aaif-goose/goose
- Qwen Code: https://github.com/QwenLM/qwen-code
- PR Agent: https://github.com/The-PR-Agent/pr-agent
- MoAI ADK: https://github.com/modu-ai/moai-adk
- AgentPipe: https://github.com/kevinelliott/agentpipe and https://agentpipe.ai/
- Palot: https://github.com/ItsWendell/palot
- OpenGUI: https://github.com/akemmanuel/OpenGUI
- Kaiden: https://github.com/openkaiden/kaiden
- agent-afk: https://github.com/griffinwork40/agent-afk
- Devika: https://github.com/stitionai/devika
- GPT Pilot: https://github.com/Pythagora-io/gpt-pilot
- GPT Engineer: https://github.com/AntonOsika/gpt-engineer
