# Open Source SASE Competitors - Consolidated GitHub Audit

Date: 2026-06-07

## Question

Which open-source projects compete directly with SASE, and what do they imply for SASE positioning?

This consolidates the two independent research passes:

- `sdd/research/202606/open_source_sase_competitor_audit.md`
- `sdd/research/202606/open_source_direct_competitors_audit.md`

Those files were read and deduplicated. Their strongest findings are preserved here, conflicts are resolved, and the two
intermediate files are superseded by this one.

## Scope

SASE is not a coding-agent runtime. The local README says SASE "orchestrates coding agents into tracked, repeatable
engineering workflows" and gives runs "a durable operating layer: isolated workspaces, reusable prompts, scheduling,
status, review state, and commit flow."

So this audit treats direct competitors as projects that try to own the operating layer:

- multi-agent or parallel-agent orchestration
- isolated workspaces, worktrees, containers, or sandboxes
- issue/ticket to PR execution
- reusable prompt/workflow definitions
- plan, review, CI, commit, PR, merge, and feedback loops
- durable engineering state beyond a single chat
- spec/task/issue layers that overlap SASE SDD, ChangeSpecs, Beads, or XPrompt

Terminal/IDE coding agents such as OpenCode, Claude Code, Codex, Gemini CLI, Qwen Code, Goose, Cline, and Aider are
mostly complementary. SASE can wrap them. They compete for daily user attention, but they are not the main direct peer
set unless they add a durable fleet/workflow layer.

## Method And Verification

- Read both prior agent transcripts and both generated research files.
- Verified SASE baseline against `README.md`.
- Rechecked headline GitHub metadata with `gh repo view` on 2026-06-07: stars, forks, pushed date, license key, archive
  status, descriptions.
- Rechecked feature claims against project READMEs/sites for the strongest candidates.
- Ran an additional web search for newer "parallel coding agent worktree orchestrator" and "spec-driven development AI
  coding" projects. This found several newer direct peers the prior files missed: Bernstein, Fusion, Arbor, Verun, and
  source-available Codemux.

Star counts are volatile and should be treated as market signal, not quality signal.

## Consolidated Bottom Line

The direct category is real and crowded. The closest projects are no longer only OpenHands and Gas Town; there is now a
large cluster of fleet UIs, worktree orchestrators, async ticket-to-PR systems, and spec/task layers.

No single clean open-source project matches all of SASE's combined pillars: ACE, workspace isolation, AXE, ChangeSpecs,
XPrompt, SDD/Beads, memory, commit finalization, plugins, and shared Rust core. The moat is integration across those
layers, not any one primitive.

The first intermediate file was strongest on high-signal profiles for Optio, Archon, Open SWE, Emdash, OpenADE, and
Agent Smith. The second was stronger on the broader fleet-orchestrator and spec/task landscape. This final version uses
the second file's taxonomy, promotes Agent Orchestrator as the closest architecture twin, keeps Optio as the strongest
Kubernetes/team-platform peer, and adds the missed newer projects.

One important correction: AXE-style background automation is rare, but not totally absent. Gas Town has Deacon/Witness
health loops and a scheduler, Bernstein has a deterministic scheduler and audit log, and Optio has reconciliation
workers. SASE still has a stronger named scheduling/automation pillar than most peers, but "nobody else has scheduling"
would now be too strong.

## Ranked Direct Shortlist

| Rank | Project | Verified GitHub signal | License | Why it competes with SASE |
| ---: | --- | --- | --- | --- |
| 1 | [Agent Orchestrator](https://github.com/AgentWrapper/agent-orchestrator) | 7,438 stars / 1,013 forks; pushed 2026-06-01 | MIT | Closest architecture twin: agent-agnostic and runtime-agnostic fleet over git worktrees, dashboard, PRs, CI failure routing, review-comment routing, Linear/GitHub plugins. Lacks SASE's ChangeSpecs, SDD/Beads, XPrompt, memory, AXE breadth, and Rust core. |
| 2 | [Gas Town](https://github.com/gastownhall/gastown) | 15,768 / 1,473; pushed 2026-06-06 | MIT | Closest philosophical peer: multi-agent SWE workspace, Mayor coordinator, Beads/Dolt state, worktree hooks, Witness/Deacon health loops, Scheduler, Refinery merge queue, `gt feed` TUI. More ambitious in agent society/merge automation; SASE is cleaner on ChangeSpecs, XPrompt, ACE, plugins, and Rust core. |
| 3 | [OpenHands](https://github.com/OpenHands/OpenHands) | 76,082 / 9,656; pushed 2026-06-07 | MIT except `enterprise/` | Largest open agentic development platform: SDK, CLI, local GUI, cloud, enterprise, sandbox/runtime model, integrations. Stronger packaging and platform reach; weaker as a local-first multi-runtime wrapper with durable PR/CL state. |
| 4 | [Archon](https://github.com/coleam00/Archon) | 22,225 / 3,358; pushed 2026-06-07 | MIT | Direct XPrompt competitor. YAML workflows for AI coding with phases, validation gates, worktrees, human approvals, PR creation, web dashboard, and workflow builder. Messaging is crisp: "GitHub Actions for AI coding workflows." |
| 5 | [claude-squad](https://github.com/smtg-ai/claude-squad) | 7,740 / 553; pushed 2026-05-18 | AGPL-3.0 | Canonical OSS ACE analog: terminal UI managing multiple local coding agents in separate workspaces via tmux and git worktrees. Strong on simple fleet UX; lacks structured workflow state. |
| 6 | [cmux](https://github.com/manaflow-ai/cmux) | 21,334 / 1,616; pushed 2026-06-07 | GPL-3.0-or-later plus commercial | Native macOS terminal/ADE with vertical tabs, notifications, browser panes, branch/PR status, SSH, and scriptability. Strong ACE/UX pressure, but not a full SDD/ChangeSpec/XPrompt system. |
| 7 | [Emdash](https://github.com/generalaction/emdash) | 4,779 / 490; pushed 2026-06-07 | Apache-2.0 | Desktop ADE for many coding agents in git worktrees, with ticket intake, diffs, PR creation, CI checks, merge, and SSH/SFTP. Very direct cockpit competition for ACE users who prefer GUI surfaces. |
| 8 | [Open SWE](https://github.com/langchain-ai/open-swe) | 9,929 / 1,126; pushed 2026-06-07 | MIT | LangChain/LangGraph async coding agent: Slack/Linear/GitHub triggers, persistent sandboxes, parallel tasks, subagents, middleware, commit and PR updates. Strong internal-platform narrative. |
| 9 | [Optio](https://github.com/jonwiggins/optio) | 975 / 110; pushed 2026-05-07 | MIT | Strongest Kubernetes/team-platform version: self-hosted ticket-to-merged-PR system with Fastify, Next.js, BullMQ, Postgres, Redis, Kubernetes pods, Helm, review service, and CI watcher. Operationally heavier than SASE. |
| 10 | [GitHub Spec Kit](https://github.com/github/spec-kit) | 109,778 / 9,703; pushed 2026-06-06 | MIT | Category-defining spec-driven development toolkit: Specify CLI, templates, slash commands, agent integrations. It competes with SASE SDD/XPrompt mindshare, not ACE/AXE orchestration. |
| 11 | [OpenSpec](https://github.com/Fission-AI/OpenSpec) | 53,276 / 3,732; pushed 2026-06-03 | MIT | Lightweight SDD/change-proposal workflow with `proposal.md`, specs, design, tasks, apply/archive, dashboard, and many assistant integrations. Overlaps SDD and ChangeSpec concepts, but not PR lifecycle/fleet orchestration. |
| 12 | [Beads](https://github.com/gastownhall/beads) | 24,390 / 1,627; pushed 2026-06-07 | MIT | Direct competitor to SASE's Beads layer, including the same name. Git-native/dependency-aware issue graph for agent memory and long-horizon tasks. Issue tracker only, but strategically important because of naming and Gas Town integration. |
| 13 | [vibe-kanban](https://github.com/BloopAI/vibe-kanban) | 26,830 / 2,833; pushed 2026-04-24 | Apache-2.0 | Kanban-first agent manager: issues, workspaces, agent branches/terminals/dev servers, diffs, inline comments, PR creation and merge, many runtime integrations. README says Vibe Kanban is sunsetting, so track continuity. |
| 14 | [Bernstein](https://github.com/sipyourdrink-ltd/bernstein) | 555 / 46; pushed 2026-06-07 | Apache-2.0 | Newly found direct peer: deterministic Python scheduler for many CLI coding agents in parallel git worktrees, HMAC audit chain, lineage, merge queue, tests/review gates, on-prem posture. Smaller, but directly overlaps SASE's orchestration and auditability story. |
| 15 | [Fusion](https://github.com/Runfusion/Fusion) | 685 / 80; pushed 2026-06-06 | MIT | Newly found early-preview peer: multi-node agent orchestrator with board state, specs, worktrees, plan/review/execute/review gates, auto-merge, conflict resolution, and distributed nodes. Early but highly direct. |

## Additional OSS Projects To Track

These are direct or near-direct, but lower priority than the shortlist.

### Fleet UI / Worktree Managers

| Project | Signal | Why it matters |
| --- | --- | --- |
| [coder/mux](https://github.com/coder/mux) | 1,817 stars; AGPL-3.0; pushed 2026-06-07 | Desktop app for isolated parallel agentic development; Coder-backed. |
| [stravu/crystal](https://github.com/stravu/crystal) | 3,076; MIT; pushed 2026-02-26 | GUI for Codex/Claude sessions in worktrees; rebranded to Nimbalyst; strong compare/merge UX. |
| [penso/arbor](https://github.com/penso/arbor) | 749; MIT; pushed 2026-05-08 | Newly found native app for Git worktrees, terminals, diffs, and agentic coding workflows. |
| [SoftwareSavants/verun](https://github.com/SoftwareSavants/verun) | 6; AGPL-3.0; pushed 2026-06-03 | Newly found and tiny, but directly shaped like SASE's cockpit/worktree layer. |
| [kbwo/ccmanager](https://github.com/kbwo/ccmanager) | 1,142; MIT; pushed 2026-05-31 | TUI session manager across Claude, Gemini, Codex, Cursor, Copilot, Cline, OpenCode, Kimi. |
| [coollabsio/jean](https://github.com/coollabsio/jean) | 1,028; Apache-2.0; pushed 2026-06-06 | Desktop/web app for Claude/Codex/OpenCode across projects and worktrees. |
| [johannesjo/parallel-code](https://github.com/johannesjo/parallel-code) | 704; MIT; pushed 2026-06-05 | Desktop side-by-side Claude/Codex/Gemini sessions in worktrees, diff and merge. |
| [standardagents/dmux](https://github.com/standardagents/dmux) | 1,624; MIT; pushed 2026-05-25 | CLI multiplexer over worktrees; less dashboard/state. |
| [raine/workmux](https://github.com/raine/workmux) | 1,595; MIT; pushed 2026-06-06 | Worktrees plus tmux windows, one agent per feature. |
| [andyrewlee/amux](https://github.com/andyrewlee/amux) | 122; MIT; pushed 2026-06-07 | Small TUI for parallel agents; author also maintains a useful orchestrator index. |

### Ticket / PR Automation And Sandboxes

| Project | Signal | Why it matters |
| --- | --- | --- |
| [holgerleichsenring/agent-smith](https://github.com/holgerleichsenring/agent-smith) | 17; MIT; pushed 2026-06-06 | Tiny but architecturally direct: self-hosted ticket-to-code-to-PR, tracker integrations, `.agentsmith/runs/{run-id}/plan.md`, `result.md`, `decisions.md`, cost accounting. |
| [sortie-ai/sortie](https://github.com/sortie-ai/sortie) | 73; Apache-2.0; pushed 2026-06-03 | Turns tracker tickets into autonomous agent sessions; Go + SQLite. |
| [madarco/agentbox](https://github.com/madarco/agentbox) | 48; MIT; pushed 2026-06-07 | Runs parallel agents in sandboxed boxes, local Docker or cloud VMs. |
| [dagger/container-use](https://github.com/dagger/container-use) | 3,813; Apache-2.0; pushed 2026-02-23 | More primitive than competitor: per-agent dev environments SASE could integrate for sandboxing. |

### Spec / Task / Method Layers

| Project | Signal | Why it matters |
| --- | --- | --- |
| [bmad-code-org/BMAD-METHOD](https://github.com/bmad-code-org/BMAD-METHOD) | 48,707; MIT; pushed 2026-06-07 | Role-based agentic agile method: Analyst/PM/Architect/SM/Dev, PRD, architecture, stories. Methodology competitor to SASE SDD, not a full control plane. |
| [MrLesk/Backlog.md](https://github.com/MrLesk/Backlog.md) | 5,696; MIT; pushed 2026-05-30 | Markdown/git task and kanban tool for human+AI collaboration; Beads-lite. |
| [Pimzino/spec-workflow-mcp](https://github.com/Pimzino/spec-workflow-mcp) | 4,217; GPL-3.0; pushed 2026-05-05 | MCP server for requirements/design/tasks plus live dashboard and VS Code extension. |
| [buildermethods/agent-os](https://github.com/buildermethods/agent-os) | 4,784; MIT; pushed 2026-05-05 | Standards/spec-generation prompt scaffolding; context engineering more than tracked workflow. |
| [potpie-ai/potpie](https://github.com/potpie-ai/potpie) | 5,418; Apache-2.0; pushed 2026-06-07 | Spec-driven development for large codebases via code knowledge graph agents. |
| [Priivacy-ai/spec-kitty](https://github.com/Priivacy-ai/spec-kitty) | 1,302; MIT; pushed 2026-06-07 | SDD + kanban dashboard + git worktrees + auto-merge; small but spans several SASE-like layers. |

## Source-Available, Restricted, Or Closed Projects To Keep Separate

These compete conceptually, but should not be counted as clean OSS competitors.

| Project | Status | Why it still matters |
| --- | --- | --- |
| [Zeus-Deus/codemux](https://github.com/Zeus-Deus/codemux) | Elastic License 2.0; 7 stars; pushed 2026-06-06 | Newly found Linux ADE: worktrees, terminals, browser, multi-agent delegation. Very direct, but source-available rather than OSI open source. |
| [eyaltoledano/claude-task-master](https://github.com/eyaltoledano/claude-task-master) | MIT plus Commons Clause; 27,344 stars | Huge PRD-to-tasks engine that competes with Beads/SDD mindshare, but the Commons Clause restricts resale/hosted-service use. |
| [bearlyai/OpenADE](https://github.com/bearlyai/OpenADE) | No GitHub API license file found; 308 stars | Direct local ADE around Claude Code/Codex: Plan -> Revise -> Execute, snapshots, worktrees, comments. License ambiguity means do not treat as clean OSS without rechecking. |
| `superset-sh/superset` | Elastic License 2.0 | Source-available editor for the agent era; direct UX peer but not OSS. |
| Conductor | Closed source | Prominent macOS parallel-agent product with isolated workspaces and PR/merge flow. |
| Kiro | Proprietary | AWS spec-driven agentic IDE; direct SDD concept peer. |
| Tessl | Proprietary | Spec-as-source platform; direct spec-layer competition. |
| Sculptor | Source-available/other | Container-first desktop agent workspace; conceptually direct. |

## SASE Pillar Map

| SASE pillar | Competitive status | Read |
| --- | --- | --- |
| ACE live TUI/fleet view | Heavily contested | claude-squad, ccmanager, amux, cmux, Emdash, mux, Vibe Kanban, Arbor, and many small projects prove fleet/worktree UI is table stakes. |
| Workspace isolation | Heavily contested | Worktrees are now default; containers/sandboxes are increasingly expected for security. SASE's numbered workspace clones are concurrency isolation, not hostile-code containment. |
| Multi-runtime wrapping | Partly contested | Agent Orchestrator, Vibe Kanban, ccmanager, Emdash, Bernstein, and Fusion all wrap multiple runtimes. SASE should not rely on this alone. |
| AXE scheduling/automation | Rare but not unique | Gas Town, Bernstein, Optio, and a few board tools have schedulers/reconcilers/health loops. SASE's advantage is AXE as a named local automation daemon tied into hooks, mentors, ChangeSpecs, and workflows. |
| ChangeSpecs | Strong wedge | Many tools open PRs; few track durable PR/CL lifecycle state with comments, mentors, hooks, status, commits, and review metadata as a first-class artifact. |
| XPrompt | Strong but threatened | Archon has the crispest competing workflow story. Spec Kit/OpenSpec/command packs compete with XPrompt's template side. SASE should explain typed inputs, output-variable handoffs, and multi-step workflows more plainly. |
| SDD + Beads | Contested in pieces | Spec Kit/OpenSpec own spec mindshare; Beads/Task Master own task graph mindshare. SASE's wedge is integration with orchestration and PR lifecycle. |
| Memory / audit trail | Moderate wedge | Gas Town Beads, Bernstein audit/lineage, and Agent Smith run artifacts show the market values durable "why" trails. SASE has richer artifacts but should package them more explicitly per run. |
| Shared Rust core | Structural wedge | I found no peer with SASE's explicit cross-frontend core/backend boundary, though several use Rust for performance/UI. |

## Strategic Implications

1. Name the category around the operating layer. "Local-first agentic SWE control plane" or "agentic SWE operating
   layer" is more accurate than "coding agent."
2. Compare publicly against Agent Orchestrator, Gas Town, claude-squad, Archon, Spec Kit, and Beads, not primarily
   against Claude Code/OpenCode/Codex.
3. Ship a canonical issue-to-PR workflow: create/update ChangeSpec and Beads, allocate workspace, run agent, run checks
   and mentors, open/update PR, resume on CI/review feedback, and record artifacts.
4. Make XPrompt externally legible: reusable workflow DAGs for coding agents, with gates, loops, approvals, typed
   parameters, artifacts, and provider-neutral execution.
5. Treat the Beads name collision as a product decision. Either differentiate sharply from `gastownhall/beads`, support
   interop, or rename SASE's layer before confusion hardens.
6. Add a sandbox provider story. Workspaces are not the same as security sandboxes; competitors increasingly claim
   worktree plus Docker/VM/Kubernetes boundaries.
7. Package the per-run decision trail. Agent Smith's `plan.md`, `result.md`, and `decisions.md` is simple and memorable;
   SASE has richer raw material but should expose a standard per-run bundle.
8. Watch GUI/ADE expectations. ACE is strong for power users, but cmux, Emdash, Vibe Kanban, OpenHands GUI, Arbor, and
   Codemux show the market expects diff review, PR/CI state, comments, browser/dev-server previews, and notifications.
9. Re-run this audit quarterly. The community index and search results show new worktree/fleet orchestrators appearing
   quickly.

## Best Follow-Up Deep Dives

1. Agent Orchestrator vs SASE - closest architecture twin.
2. Gas Town refresh - prior local research exists, but Gas Town now has more explicit scheduler/refinery/health-loop
   features.
3. Archon vs XPrompt - best threat to SASE's workflow-language positioning.
4. Beads naming and interop decision - high urgency because of the exact name collision.
5. Emdash/cmux/Vibe Kanban vs ACE - graphical cockpit expectations.
6. Bernstein/Fusion watch pass - smaller but newly discovered and highly direct.

## Sources

Local:

- `README.md`
- `memory/short/sase.md`
- `memory/short/glossary.md`
- `sdd/research/202605/sase_vs_gastown.md`
- `sdd/research/202605/openhands_vs_sase.md`
- `sdd/research/202605/cli_agent_harnesses_for_sase.md`
- `sdd/research/202605/memory_system_prior_art.md`

Primary project sources and live GitHub metadata:

- https://github.com/AgentWrapper/agent-orchestrator
- https://github.com/gastownhall/gastown
- https://github.com/OpenHands/OpenHands
- https://github.com/coleam00/Archon
- https://github.com/smtg-ai/claude-squad
- https://github.com/manaflow-ai/cmux
- https://github.com/generalaction/emdash
- https://github.com/langchain-ai/open-swe
- https://github.com/jonwiggins/optio
- https://github.com/github/spec-kit
- https://github.com/Fission-AI/OpenSpec
- https://github.com/gastownhall/beads
- https://github.com/BloopAI/vibe-kanban
- https://github.com/sipyourdrink-ltd/bernstein
- https://github.com/Runfusion/Fusion
- https://github.com/penso/arbor
- https://github.com/SoftwareSavants/verun
- https://github.com/andyrewlee/awesome-agent-orchestrators

Additional project pages checked:

- https://optio.host/
- https://archon.diy/
- https://emdash.sh/
- https://bernstein.run/
- https://runfusion.ai/
- https://codemux.org/
- https://www.verun.dev/
