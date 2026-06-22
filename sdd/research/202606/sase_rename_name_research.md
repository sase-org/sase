# SASE Rename Research

Date: 2026-06-22

## Question

What name would better fit the project currently called `sase`, reduce avoidable collision risk, and help a new user
understand the product before reading the acronym expansion?

## Current Product Shape

The local README positions SASE as a provider-neutral operating layer for coding agents, not as another coding agent.
It "orchestrates coding agents into tracked, repeatable engineering workflows" and gives runs durable state: isolated
workspaces, reusable prompts, scheduling, status, review state, and commit flow. The feature surface is broader than
"run several agents": ACE, AXE, XPrompt, ChangeSpecs, Memory, SDD/Beads, commit finalization, plugins, editor
integration, and a Rust core boundary all point to a controlled software-change system.

Naming implication: the new name should hold the whole workflow/control-plane idea. Names that only say "prompt",
"agent", "kanban", or "worktree" understate the product.

Local sources:

- [`README.md`](../../../README.md)
- [`open_source_sase_competitors_consolidated.md`](open_source_sase_competitors_consolidated.md)
- [`sase_blog_launch_strategy_consolidated.md`](sase_blog_launch_strategy_consolidated.md)

## Why Rename

The current name has one very large external collision: public "SASE" means Secure Access Service Edge. Gartner Peer
Insights defines SASE platforms as converged network and security-as-a-service offerings, and Cisco describes SASE as
cloud-delivered network/security functions such as SD-WAN, secure web gateways, cloud access security brokers,
firewall-as-a-service, and zero-trust network access.

That collision is not a small acronym overlap. It is a mature enterprise security category with established vendors,
analyst pages, review pages, and SEO gravity. A developer searching for `sase`, `sase platform`, or `sase orchestration`
will often land in networking/security before they get to coding-agent workflow orchestration.

The current expansion, "Structured Agentic Software Engineering", is accurate but academic. It explains the project
after a user already cares. It does not create a memorable product handle, and the acronym itself does not carry
meaning in the coding-agent market.

External sources:

- [Gartner Peer Insights: SASE Platforms](https://www.gartner.com/reviews/market/single-vendor-sase)
- [Cisco: What is SASE?](https://www.cisco.com/site/us/en/learn/topics/security/what-is-secure-access-service-edge-sase.html)

## Category Pressure

The direct category is now crowded enough that generic "agent orchestrator" names will be hard to own. Agent
Orchestrator describes itself as an orchestration layer for parallel AI agents, spawning coding agents in git worktrees
with branches, PRs, CI-failure handling, and review-comment handling. The public "awesome agent orchestrators" list
already contains a long inventory of parallel agent runners, worktree tools, dashboards, and kanban-like products.

The common market language is:

- multiple coding agents working asynchronously
- isolated git worktrees or sandboxes
- planning, review, CI, merge, and feedback loops
- a human supervising from above rather than pair-programming with one agent

Addy Osmani's "code agent orchestra" framing captures the user mental model: the developer moves from one synchronous
agent to coordinating multiple asynchronous agents with planning and check-ins. Augment's 2026 roundup similarly says
OSS agent orchestrators largely converge on git worktrees, while coordination depth is the differentiator.

Naming implication: avoid a generic `Agent*`, `*Orchestrator`, `Conductor`, `Squad`, or `Kanban` name unless the goal is
to blend into the category. SASE's stronger wedge is controlled, reviewable software change across agents, plans,
workspaces, artifacts, and commits.

External sources:

- [Agent Orchestrator](https://github.com/AgentWrapper/agent-orchestrator)
- [Awesome Agent Orchestrators](https://github.com/andyrewlee/awesome-agent-orchestrators)
- [Augment: 9 Open-Source Agent Orchestrators for AI Coding (2026)](https://www.augmentcode.com/tools/open-source-agent-orchestrators)
- [Addy Osmani: The Code Agent Orchestra](https://addyosmani.com/blog/code-agent-orchestra/)

## Naming Criteria

I used these filters:

1. CLI-friendly: easy to type as a command and plausible as a PyPI package.
2. Searchable: not a generic noun already owned by a large adjacent tool.
3. Scope-safe: broad enough for runs, workspaces, plans, review state, memory, artifacts, and commit/PR flow.
4. Provider-neutral: should not imply a new model/runtime replacing Claude Code, Codex, Qwen Code, etc.
5. Human-in-the-loop: should leave room for supervision, review, and auditability.
6. Migration-aware: short enough to tolerate aliases, docs migration, package transition notes, and plugin renames.

This is naming research, not trademark clearance. A real rename should still include package reservation, domain
checks, GitHub org/repo checks, and legal review before public launch.

## Availability Method

I spot-checked candidate names on 2026-06-22 with:

- PyPI JSON endpoint: `https://pypi.org/pypi/<name>/json`
- npm registry endpoint: `https://registry.npmjs.org/<name>`
- GitHub repository-name search where the unauthenticated API was available
- exact-phrase web search for product, package, and adjacent-market collisions

For PyPI/npm, `404` means the exact package name was not present at the time of the check. That does not guarantee future
availability or trademark safety.

## Names I Would Avoid

| Name | Why not |
| --- | --- |
| `SASE` / `Sassy` | Too much Secure Access Service Edge collision; the "sassy" pronunciation is also used in that market. |
| `AgentOrchestrator` variants | The phrase is already a category term and an existing project name. |
| `Conductor` / `Orchestra` variants | Conceptually good, but the metaphor is already common in agent orchestration discourse. |
| `PatchPlane` | Excellent semantics, but exact web search found a GitHub project described as an "AI change control plane for coordinating agents and humans." Too direct a collision. |
| `SpecPlane` | Exact GitHub collision in AI-assisted/specification tooling. |
| `PlanWright` | Direct adjacent collision with a local-first planning/evidence engine and AI coding audit positioning. |
| `Patchbay` | Strong metaphor, but PyPI and npm names were taken and GitHub name hits were high. |
| `Gantry`, `Railyard`, `Switchyard`, `Trestle`, `Spindle` | Good infrastructure metaphors, but package and/or GitHub collisions were too high for a clean rename. |
| `Runboard`, `Worklane`, `OpsDeck`, `TaskDeck`, `Patchlane` | Exact product or package collisions in workflow, dashboard, task, or patch-maintenance spaces. |

## Viable Shortlist Before Ranking

| Candidate | Spot-check result | Read |
| --- | --- | --- |
| `Patchyard` | PyPI 404, npm 404; low exact web noise, mostly non-dev usage | Best overall semantic fit: a place where patch-producing work is staged, routed, inspected, and cleaned up. |
| `ChangeDeck` | PyPI 404, npm 404; GitHub name search returned 0; exact web noise mostly API method names | Strong control-surface feel, good for ACE/TUI positioning, but can read like the verb phrase "change deck." |
| `ChangePlane` | PyPI 404, npm 404; low direct product collision | Good "control plane for software change" semantics, but more abstract and has unrelated statistical/aviation phrase noise. |
| `PatchTower` | PyPI 404, npm 404; GitHub name search returned 0 | Strong supervision/control-tower metaphor, but may sound like OS/security patch management. |
| `DiffYard` | PyPI 404, npm 404; GitHub name search earlier returned 0; exact web noise was minimal and unrelated | Very searchable and developer-native, but narrower than the whole SASE surface. |
| `PatchStation` | PyPI 404, npm 404 | Clean enough, but less distinctive than `Patchyard` and weaker as a product story. |
| `ChangeStation` | PyPI 404, npm 404 | Clean enough, but "station" is generic and less developer-specific. |
| `DiffRail` / `DiffWright` | PyPI 404, npm 404; low collision | Distinctive, but too diff-centric and less immediately understandable. |

## Positioning Direction

The strongest naming territory is not "AI agents". It is "controlled software change".

That territory covers the project honestly:

- agents produce work, but humans supervise the flow
- workspaces isolate changes
- plans, ChangeSpecs, Beads, memory, and artifacts preserve intent and state
- CI, reviews, mentors, hooks, commits, and PRs complete the loop
- the tool coordinates durable change, not just temporary sessions

The public one-liner can then become:

> `<name>` coordinates coding agents into reviewable software changes.

That line is shorter and more legible than "Structured Agentic Software Engineering", while still leaving room for the
full system.

## Five Recommendations

1. **Patchyard**  
   Best recommendation. It is practical, developer-native, and broad enough for multiple workspaces, pending patches,
   review state, cleanup, and commit flow. The `yard` metaphor suggests a managed place where several pieces of work can
   wait, move, and be inspected without overclaiming autonomy. Package spot checks were clean (`patchyard` returned 404
   on PyPI and npm). Use the tagline: "Patchyard coordinates coding agents into reviewable software changes."

2. **ChangeDeck**  
   Best if the product identity should lean into ACE, dashboards, review surfaces, and operator control. `Deck` implies
   a control deck or work deck rather than a runtime. Package spot checks were clean, and GitHub name search returned no
   exact repository-name hits. The downside is that `change deck` can read as a verb phrase, so branding should style it
   consistently as `ChangeDeck`.

3. **ChangePlane**  
   Best if you want the most explicit "control plane for software change" positioning. It is broader than `Patchyard`
   because it covers planning, memory, dependencies, review, and artifacts before a patch exists. Package spot checks
   were clean. The downside is abstraction: it will need a strong tagline because `plane` is less concrete than `yard`
   or `deck`.

4. **PatchTower**  
   Best if you want a command-center metaphor. It clearly says that the tool supervises patch flow from above, which
   matches scheduled runs, background agents, notifications, CI/review loops, and finalization. Package spot checks were
   clean, and I did not find a strong direct product collision. The risk is that it can sound like security patch
   management unless the first-screen copy says "coding-agent patches" quickly.

5. **DiffYard**  
   Best if you want maximum distinctiveness and a code-review-heavy identity. It had clean package spot checks and very
   low exact-match noise. The name is strongest for comparing, reviewing, staging, and merging agent output. I would rank
   it below the others because SASE does important work before a diff exists: planning, scheduling, memory, dependency
   ordering, workspace allocation, and artifact capture.
