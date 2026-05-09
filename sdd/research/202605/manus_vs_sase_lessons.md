# Manus vs. SASE: Research and Lessons

Date: 2026-05-09

## Purpose

This note compares Manus with SASE and extracts lessons SASE can use. It treats Manus as a product signal, not as a
system to copy wholesale: Manus optimizes for broad autonomous task completion across web, files, apps, and generated
deliverables; SASE optimizes for structured, auditable software-engineering work around coding agents, VCS state,
ChangeSpecs, beads, reusable xprompts, workflow execution, and human-supervised handoffs.

The user prompt said "mantis" once after asking about "Manus"; this research assumes Manus was intended.

## Sources

Primary Manus sources:

- Manus docs: [Welcome](https://manus.im/docs/introduction/welcome), [Cloud Browser](https://manus.im/docs/features/cloud-browser), [Browser Operator](https://manus.im/docs/features/browser-operator), [Desktop](https://manus.im/docs/features/desktop), [Projects](https://manus.im/docs/features/projects), [Skills](https://manus.im/docs/features/skills), [Wide Research](https://manus.im/docs/features/wide-research), [Scheduled Tasks](https://manus.im/docs/features/scheduled-tasks), [Collab](https://manus.im/docs/features/collab), [Plans and Pricing](https://manus.im/docs/introduction/plans)
- Manus API docs: [Introduction](https://open.manus.im/docs/v2/introduction), [Task Lifecycle](https://open.manus.im/docs/v2/task-lifecycle), [Connectors](https://open.manus.im/docs/v2/connectors), [Agents](https://open.manus.im/docs/v2/agents-overview), [Structured Output](https://open.manus.im/docs/v2/structured-output)
- Manus Website Builder docs: [Code Control](https://manus.im/docs/website-builder/code-control), [Publishing](https://manus.im/docs/website-builder/publishing), [GitHub Integration](https://manus.im/docs/website-builder/github-integration)
- Manus help center: [My Computer capabilities](https://help.manus.im/en/articles/14178443-what-is-the-my-computer-feature-capable-of)
- Manus engineering blog: [Context Engineering for AI Agents: Lessons from Building Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus) (Yichao "Peak" Ji)
- Manus product blog: [Introducing Manus 1.5](https://manus.im/blog/manus-1.5-release)

Secondary / independent sources:

- AWS press release: [Manus Selects AWS to Power General Purpose AI Agent](https://press.aboutamazon.com/aws/2025/12/manus-selects-aws-to-power-general-purpose-ai-agent-serving-millions-globally)
- AP: [Meta buys startup Manus](https://apnews.com/article/meta-manus-purchase-ai-agents-aaf01029923011a403ceeb949cf3db5e)
- Axios: [New Chinese AI agent draws DeepSeek comparison](https://www.axios.com/2025/03/10/manus-chinese-ai-agent-deepseek)
- TechCrunch: [Manus probably isn't China's second DeepSeek moment](https://techcrunch.com/2025/03/09/manus-probably-isnt-chinas-second-deepseek-moment/) and [Manus launches paid plans and mobile app](https://techcrunch.com/2025/03/31/manus-launches-paid-subscription-plans-and-a-mobile-app/)
- The Decoder: [Chinese AI agent Manus uses Claude Sonnet and open-source technology](https://the-decoder.com/chinese-ai-agent-manus-uses-claude-sonnet-and-open-source-technology/)
- arXiv: [From Mind to Machine: The Rise of Manus AI as a Fully Autonomous Digital Agent](https://arxiv.org/html/2505.02024v3)
- DataCamp: [Manus AI: Features, Architecture, Access, Early Issues & More](https://www.datacamp.com/blog/manus-ai)
- Technical investigation gist by renschni: [Manus AI architecture and tool orchestration](https://gist.github.com/renschni/4fbc70b31bad8dd57f3370239dccd58f)
- GAIA benchmark paper: [GAIA: a benchmark for General AI Assistants](https://arxiv.org/abs/2311.12983)
- OpenManus: [FoundationAgents/OpenManus on GitHub](https://github.com/FoundationAgents/OpenManus) and [OpenManus-RL](https://github.com/OpenManus/OpenManus-RL)

Local SASE sources:

- `README.md`
- `docs/index.md`
- `docs/sdd.md`
- `docs/workflow_spec.md`
- `docs/beads.md`
- `docs/ace.md`
- `docs/notifications.md`

## Manus Summary

Manus presents itself as an autonomous general AI agent that completes tasks rather than only answering questions. Its
official docs describe a sandboxed virtual computer with internet access, a persistent file system, installable
software, and custom tools. AWS describes the system as built around independent thinking, dynamic planning, autonomous
decision-making, task decomposition, code generation, debugging, and large numbers of isolated sandbox instances.

The product surface has expanded beyond the initial "cloud agent" idea:

| Area | Manus Capability |
| --- | --- |
| Cloud execution | Cloud Browser, cloud sandbox, asynchronous tasks, persistent files, browser automation. |
| Local execution | Browser Operator for controlling the user's existing browser session; Desktop / My Computer for local files, apps, CLI tools, and hardware. |
| Scale-out work | Wide Research decomposes item-wise work and runs many independent agents in parallel before synthesizing results. |
| Reuse | Projects provide shared instructions and file knowledge bases; Skills package reusable workflows and load progressively. |
| Integrations | OAuth connectors, custom MCP servers, Zapier, Slack, Gmail, Google Calendar, GitHub, many SaaS/data connectors. |
| API | REST API for tasks, projects, files, webhooks, skills, agents, browser clients, connectors, structured output, and usage. |
| Human gates | API task lifecycle exposes `waiting` states and event-specific confirmation schemas for email sends, terminal commands, deploys, calendar changes, browser selection, and other risky actions. |
| Collaboration | Shared task workspace where collaborators can see task history, prompt Manus, and export outputs while the owner controls invites and pays credits. |
| Web app delivery | Builder can generate apps, expose/download code, sync with GitHub, and publish with managed hosting, SSL, and domains. |

Manus also has strong public product momentum. AWS claimed a $90M revenue run rate four months after subscription launch.
AP later reported Meta's acquisition of Manus, with Meta saying Manus served millions of users and businesses. These
numbers should be treated as commercial signals rather than technical proof.

### Underlying model and multi-agent topology

Manus is not a from-scratch foundation model; it is an agent harness on top of frontier models. Independent reverse
engineering and reporting consistently identify the primary reasoning model as Anthropic's **Claude 3.5 Sonnet** (with
Claude 3.7 tested internally), supplemented by fine-tuned **Alibaba Qwen** variants for auxiliary tasks. The runtime is
reported to expose roughly 29 tools and use the open-source **Browser Use** library for browser automation
([The Decoder](https://the-decoder.com/chinese-ai-agent-manus-uses-claude-sonnet-and-open-source-technology/);
[renschni technical gist](https://gist.github.com/renschni/4fbc70b31bad8dd57f3370239dccd58f)).

The architecture is multi-agent with separated context windows: a user-facing **Executor** runs an iterative
analyze → plan → execute → observe loop, while **Planner**, **Knowledge**, and **Verifier** sub-agents operate in their
own contexts. Actions are emitted as executable Python (the **CodeAct** pattern from the OpenHands lineage) rather than
free-form tool calls, which gives Manus a single, expressive action surface.

This matters for SASE because it means the Manus story is mostly about *agent harness design* — context engineering,
tool boundaries, sandbox shape, and review surfaces — on top of the same models SASE already orchestrates. Most of
what SASE could borrow is harness design, not novel model capability.

### Benchmark numbers

At launch, Manus reported state-of-the-art **GAIA** results (self-reported, not independently re-verified):

| GAIA Level | Manus | OpenAI Deep Research (prior SOTA at the time) |
| --- | --- | --- |
| Level 1 | 86.5% | 74.3% |
| Level 2 | 70.1% | 69.1% |
| Level 3 | 57.7% | 47.6% |

GAIA tests real-world, tool-using assistants across reasoning, multimodality, browsing, and tool use, but does not
exercise long-horizon authenticated workflows or multi-day software-engineering loops. SASE should treat the numbers as
directional and build domain-specific evaluations that better reflect engineering work (see "Benchmark interpretation"
below).

### Manus 1.5 (October 2025)

The [Manus 1.5 release post](https://manus.im/blog/manus-1.5-release) reports a roughly **4× speed improvement**
(average task time 15 min → ~4 min), a 15% quality lift on internal benchmarks, an expanded ("unlimited") context
window, and a one-prompt full-stack web app builder with backend/auth/database/analytics. It also introduces shared
**Collaboration** sessions and a **Library** for centralized artifacts. The release ships in two tiers — `Manus-1.5-Lite`
for all users and `Manus-1.5` for subscribers — which is a useful precedent for "good-enough free vs. premium agent"
tiering.

### Pricing and credits

Manus runs on a credit model with daily refresh credits in addition to monthly pools. Public 2026 plans land roughly
at: Free ($0, 300 daily credits), Standard ($20/mo, ~4,000 credits), a customizable tier (~$40/mo), and Extended
(~$200/mo, ~40,000 credits). Team plans add shared credit pools, SSO, audit, and admin features
([Manus pricing docs](https://manus.im/docs/introduction/plans)). The credit model has drawn user complaints because
long autonomous runs can burn credits unpredictably — relevant context for SASE's own cost-budget thinking.

### Open-source counterpart: OpenManus

[OpenManus](https://github.com/FoundationAgents/OpenManus) is an open-source clone built by MetaGPT contributors in the
days after Manus's launch. It uses GPT-4o (or any pluggable LLM) and a modular agent loop. It is genuinely useful as a
reference implementation when reasoning about Manus's mechanics — particularly its tool/agent loop and prompt scaffolding
— without having to infer everything from the closed product. [OpenManus-RL](https://github.com/OpenManus/OpenManus-RL)
extends it with RL fine-tuning experiments. SASE doesn't need to adopt either, but they're cheaper to read than the
Manus binary.

## SASE Summary

SASE is not a general-purpose consumer agent. It is an engineering orchestration system above provider CLIs such as
Claude Code, Gemini CLI, Codex, Qwen Code, and OpenCode. Its core claim is that real agentic software engineering needs
durable state outside chat transcripts.

Key SASE primitives:

| Area | SASE Capability |
| --- | --- |
| Work state | ChangeSpecs track CL/PR-sized work, lifecycle, commits, review state, comments, mentors, hooks, and metadata. |
| Planning memory | SDD persists prompt snapshots, tales, epics, legends, myths, research, and bead links under `sdd/` or `.sase/sdd/`. |
| Issue / dependency execution | Beads provide git-native issue tracking, phase dependencies, and multi-agent epic execution plans. |
| Prompt reuse | XPrompts package reusable prompts and YAML workflows with typed inputs, reference expansion, semantic tags, DAG/explain tools, and inline prompt parts. |
| Workflow engine | YAML workflows support agent, bash, python, prompt-part, parallel execution, artifacts, cleanup, output fields, control flow, and human-in-the-loop gates. |
| Operator surface | ACE TUI navigates ChangeSpecs, agents, notifications, artifacts, mentors, and Axe automation. |
| Background automation | AXE runs scheduled/background chops, maintenance, mentors, hooks, and workflow automation. |
| Provider portability | LLM, VCS, and workspace abstractions let SASE orchestrate existing tools rather than replace them. |
| Auditability | Agent artifacts, chat transcripts, diffs, generated PDFs/images, notifications, plan approvals, and commit metadata preserve the work trail. |

The central SASE advantage is engineering rigor: VCS-native state, repeatable workflows, reviewable plans, explicit
handoffs, and provider-agnostic orchestration. The central limitation versus Manus is product surface area: SASE is
powerful but terminal/workstation-centric, with fewer out-of-the-box consumer or team workflows.

## Comparison

| Dimension | Manus | SASE | Implication |
| --- | --- | --- | --- |
| Product thesis | General-purpose autonomous worker that turns prompts into delivered outputs. | Structured orchestration layer for software-engineering agents. | SASE should not dilute its domain, but can borrow Manus's outcome-oriented UX. |
| Execution environment | Cloud sandbox first, plus local browser and desktop bridges. | Local repo/workspace first, with provider/runtime adapters. | SASE's local-first model is safer for code ownership; optional cloud or remote workers could broaden reach. |
| Unit of work | Task / project / agent subtask. | ChangeSpec, SDD artifact, bead, workflow run, agent run. | SASE has richer engineering state but a more complex mental model. |
| Parallelism | Wide Research markets item-wise parallelism as a first-class mode. | Workflows and bead epic waves support parallel steps/agents, but the user-facing primitive is more engineering-specific. | SASE can expose a simpler "map/synthesize" primitive for research, review, and batch code tasks. |
| Browser/web app automation | Strong: cloud browser, local browser, website builder, publish flow. | Mostly coding-agent/provider and repo workflows; mobile gateway exists but web/browser automation is not core. | SASE can learn from browser/session permission UX without becoming a browser agent. |
| Integrations | Large connector catalog, OAuth, MCP, API usage. | Pluggy providers and external packages; mobile, Telegram, GitHub, Google, Slack-style integrations exist or are in adjacent repos. | SASE needs connector discovery, permission summaries, and task-level connector selection that feel first-class. |
| Reusable instructions | Projects and Skills. Skills use progressive disclosure. | Project config, memory, xprompts, generated skills, workflows. | SASE has the raw pieces; Manus packages them more legibly for ordinary users. |
| Human approvals | API has explicit waiting states and JSON schemas for confirmations. | HITL workflow gates, plan/question notifications, mentor review, commit/review lifecycle. | SASE should standardize action-confirmation schemas across CLI/TUI/mobile/API surfaces. |
| Collaboration | Real-time shared task workspace and owner-controlled invite model. | Local artifacts and TUI are mostly single-operator; docs/SDD are shareable via VCS. | SASE could add share/review workflows for plans, artifacts, and running agents. |
| Structured outputs | API-level JSON Schema extraction delivered through events/webhooks. | Workflow step outputs have typed fields; artifacts and notifications carry files. | SASE could add schema-validated final agent outputs as a stable integration contract. |
| Reliability posture | High autonomy, but independent early testing reported loops, crashes, missed facts, and incomplete real-world bookings/builds. | More explicit checkpoints, VCS state, and user-controlled engineering review. | SASE should preserve gates and audit trails while improving convenience. |
| Security posture | Powerful but sensitive: authenticated cloud browser, local browser/session control, local CLI command execution. | Local workspace and VCS-oriented; less pressure to hand over broad web/app credentials. | SASE's narrower scope is a strength; any connector/browser feature must be scoped, logged, and revocable. |

## Where Manus Looks Strong

### 1. Outcome-first task UX

Manus does not lead with "create a workflow file" or "select a provider"; it leads with task outcomes: reports,
dashboards, websites, presentations, data extraction, emails, and scheduled deliveries. SASE can feel like an expert
console by comparison. ACE is operationally dense, but SASE should also offer guided outcome entry points such as
"research and write a note", "review this PR", "split this epic", "monitor this dependency", or "run a batch codebase
audit".

### 2. Wide Research as a memorable abstraction

Wide Research packages parallel decomposition and synthesis in a way users can understand immediately. SASE already has
parallel workflow steps and bead dependency waves, but "parallel agents" are usually hidden inside implementation
planning. A first-class `map -> per-item agent -> reducer` mode would be useful for:

- auditing many files or modules;
- comparing many agent/provider outputs;
- researching many external tools;
- generating migration notes per subsystem;
- reviewing many ChangeSpecs or beads;
- applying repeated low-risk edits across independent packages.

### 3. API task lifecycle

The Manus API's `running` / `waiting` / `stopped` / `error` lifecycle is a clean integration boundary. The `waiting`
state is especially useful because it carries a concrete event id, event type, human-readable description, and
confirmation schema. SASE has plan approvals, questions, HITL gates, and notifications, but they are not yet presented as
one uniform external protocol.

### 4. Connector packaging

Manus's connector model is pragmatic: authorize in the web app, pass connector UUIDs to a task, fall back to project or
user defaults, and use OAuth/revocation semantics. SASE has provider/plugin abstractions and integrations, but it can
improve the user experience around "which external powers does this run have?" before launch.

### 5. Progressive disclosure for skills

Manus Skills emphasize three levels: small metadata at startup, `SKILL.md` when triggered, and extra scripts/resources
only when referenced. SASE already follows this pattern in Codex skills and has xprompts/generated skills, but should
make the pattern a product contract: searchable metadata, auditable instructions, lazy resources, and security review
for community or team skills.

### 6. Collaboration around a live task

Manus Collab's strongest idea is not multiplayer novelty; it is a single shared task history where collaborators can
prompt, inspect, and export the same output. SASE's artifacts are durable, but collaboration currently happens mostly
through git, terminal sharing, or external chat. Plan approvals, mentor findings, and research notes would benefit from
shareable review links or a lightweight web/mobile review mode.

### 7. Delivery surface

Manus publishes websites, decks, dashboards, and reports. SASE writes high-quality local artifacts and can render PDFs,
but "turn this artifact into a shareable deliverable" is not yet a major product path. Research notes, mentor summaries,
agent replays, and ChangeSpec bundles could become first-class shareable outputs.

### 8. Replay as a first-class artifact

Manus exposes a step-by-step **replay** of every task — the pages it opened, searches it ran, files it created — and
lets the user jump in mid-run, take over, or re-run a subtask. This isn't just a UX flourish: it doubles as a debugging
surface, a teaching surface, and a sales surface. SASE retains the underlying data (chat transcripts, diffs, artifacts,
notifications, axe/agent meta), but doesn't yet stitch them into a single chronological replay view. A timeline that
threads agent events, file edits, tool calls, plan transitions, and HITL gates would unlock the same affordances.

### 9. Published context-engineering discipline

The Manus team's [Context Engineering for AI Agents](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
post is unusually concrete and worth reading in full. The headline lessons — and what they imply for SASE's own
agent runtime, workflow steps, and provider adapters — are:

| Manus lesson | What it means | Relevance to SASE |
| --- | --- | --- |
| **Design around the KV cache.** Stable prefixes, append-only context, deterministic JSON serialization. Manus reports a 10× cost gap for Claude Sonnet between cached (≈$0.30/Mtok) and uncached (≈$3/Mtok) input tokens. | Cache hit rate is the dominant cost/latency lever for tool-use agents. | SASE should make prefix stability a first-class concern in xprompt/skill rendering: avoid timestamps and run-IDs early in prompts, prefer deterministic key ordering, and give workflow authors a "cache-stable" lint. |
| **Mask, don't remove tools.** Use logit masking and a state machine to gate tool availability instead of mutating the tool list mid-run. | Removing a tool invalidates earlier tool-call references and breaks the cache. | SASE provider adapters that prune tools per phase (e.g. plan vs. execute) should mask via decoding constraints or a no-op stub, not by editing the tool catalog mid-conversation. |
| **File system as external memory.** Drop large web/file content from context but keep a restorable handle (URL, path). | Treats the workspace itself as unbounded context. | SASE already has artifacts, the workspace, and SDD storage. Codify a convention where any large tool observation is written to disk and referenced by path/hash, with a small structured stub kept inline. |
| **Manipulate attention through recitation.** Continuously rewrite a `todo.md`-style task list so active goals stay in recent context. | Combats "lost in the middle" on long horizons. | SASE has beads, ChangeSpec status, plans, and bead phase trees — but few of them are surfaced *back* into the agent's prompt over time. A recurring "what we have done / what is next" injection is a cheap intervention. |
| **Preserve errors as learning signals.** Don't hide failed actions; let the model see its mistakes. | Implicit in-context belief updating; better recovery. | SASE's hook failure messages, mentor findings, and lint/test errors should be surfaced into the next agent step rather than swallowed by retry logic. The spawn-on-retry path in particular should hand the new agent a structured failure summary. |
| **Avoid few-shot pattern collapse.** Add structured variation to action/observation phrasing. | Models overgeneralize from monotonous examples and lock into a rut. | SASE skill/xprompt authors who use heavy templating should be aware that highly uniform tool outputs invite repetitive behavior. Workflow templates should leave room for varied prose, not rigid table dumps. |

These are the most directly transferable technical lessons in this whole comparison: they apply regardless of the
provider behind a SASE run, and several can be adopted without any product surface change.

## Where SASE Is Stronger

### 1. Engineering state is explicit

Manus tasks can be impressive but task state is product-owned and broad. SASE stores intent, plans, work units,
dependencies, commits, diffs, hooks, reviews, mentors, and notifications in domain-specific structures that fit real
software work. That makes SASE better suited for change management, review, rollback, and historical reconstruction.

### 2. Provider neutrality

Manus is a single agent platform. SASE deliberately orchestrates Claude, Gemini, Codex, Qwen, OpenCode, and future
providers under one workflow layer. That is strategically valuable: teams can route work by model strength, cost,
availability, policy, or experiment without rewriting the process.

### 3. Human-supervised autonomy

Manus's pitch is autonomous completion. SASE's current bias is supervised, reviewable, reproducible automation. For
software engineering, SASE's conservatism is a feature. TechCrunch's early testing reported Manus loops, crashes, missed
facts, and incomplete booking/build tasks; those are exactly the failure modes that make explicit ChangeSpecs, plan
approval, mentor review, and VCS gates valuable.

### 4. Local ownership and auditability

SASE's repo/workspace-first model gives the user direct access to code, artifacts, and history. Manus provides code
download and GitHub sync for website projects, but much of its core execution remains platform mediated. SASE should keep
"your repo is the source of truth" as a non-negotiable principle.

## Risks And Caveats From Manus

### Reliability gap

Manus markets high autonomy, but early independent reporting showed a gap between demos/benchmark claims and real-world
completion. SASE should avoid implying that autonomy alone equals reliability. For software engineering, the better
promise is "faster work with explicit state, review, and recovery."

### Benchmark interpretation

Manus's launch narrative leaned on GAIA. GAIA is relevant because it tests real-world, tool-using assistants involving
reasoning, multimodality, web browsing, and tool use. However, GAIA scores do not prove reliability for authenticated
real-world operations, long-running software projects, or security-sensitive tasks. SASE should create domain-specific
evaluation suites around ChangeSpec completion, review quality, regression rate, artifact completeness, and recovery.

### Permission scope

Manus's cloud browser and local desktop features are powerful because they touch authenticated sessions, personal files,
local command execution, and remote operation of a user's computer. The official docs are not perfectly consistent:
Desktop docs say every local command requires explicit approval, while the help center says Manus runs commands
automatically once a folder is authorized and asks only for sensitive commands. That kind of ambiguity is a product risk.
SASE should make permission boundaries mechanically precise and visible.

### Credit and cost predictability

Manus uses a credit model. TechCrunch reported paid plans and task concurrency limits shortly after launch, while AWS
later described large-scale sandbox infrastructure. Long-running agents can burn meaningful compute. SASE already has
telemetry and token usage tracking; it should make per-run cost, expected budget, and stop conditions more prominent.

## Lessons / Improvements For SASE

### 1. Add a unified task lifecycle protocol

Create a stable task/event contract spanning CLI, ACE, mobile gateway, API, and notifications:

- `queued`, `running`, `waiting`, `blocked`, `succeeded`, `failed`, `cancelled`, `retried`;
- event id and parent id;
- current workspace / ChangeSpec / bead / workflow step;
- current action description;
- `waiting_for` object with type, prompt, files, and JSON Schema for accepted response;
- artifact list and structured output list;
- retry-chain metadata.

This would turn SASE's existing primitives into a coherent external integration story.

### 2. Standardize action confirmations with schemas

SASE already has plan approvals, questions, HITL, mentor review, commit flows, and command prompts. Make every human gate
emit a schema-validated confirmation request. This helps TUI, mobile, Telegram, API clients, and future web surfaces
share one response implementation.

Examples:

- approve/reject plan;
- answer agent question;
- allow command;
- approve commit;
- approve PR/CL creation;
- accept mentor patch;
- allow external connector action;
- accept high-cost continuation.

### 3. Build a first-class map/reduce agent mode

Add an ergonomic "wide work" primitive on top of workflows and beads:

```yaml
name: audit_modules
input:
  paths: list[path]
map:
  items: "{{ paths }}"
  agent: "#audit_one_module(path=item)"
reduce:
  agent: "#synthesize_audits(reports=map.outputs)"
```

For code, keep write scopes disjoint and make merge/reducer phases explicit. For research, output to
`sdd/research/{YYYYMM}/`. For review, output structured findings tied to file paths or ChangeSpecs.

### 4. Expose project profiles as a product concept

SASE has config layers, memory, xprompts, and workspaces, but Manus Projects make recurring setup legible. Add a project
profile surface that says:

- default provider/model tiers;
- default xprompts/workflows;
- standard repo instructions;
- approved connectors;
- default mentors;
- default SDD storage mode;
- common tasks / launch buttons;
- inherited files or knowledge references.

This could be rendered in ACE and mobile, and stored as versioned project config.

### 5. Improve skill/xprompt discovery and trust

Borrow the Manus Skill packaging story while preserving SASE's stronger local control:

- searchable skill/xprompt catalog;
- metadata-only startup index;
- lazy resource loading;
- "review this skill/workflow for dangerous commands" command;
- signed or checksummed official skills;
- team skill library or project-local skill registry;
- import from GitHub with explicit trust state.

### 6. Add connector intent and permission summaries before launch

Before starting an agent/workflow, show a compact "this run can access..." summary:

- repo/workspace paths;
- VCS provider and remote actions;
- installed MCP/connectors;
- browser/session access, if any;
- allowed shell command policy;
- notification outputs;
- cost budget and concurrency.

This is especially important if SASE adds broader OAuth, browser, or remote execution features.

### 7. Make structured final outputs a stable artifact type

SASE workflow steps support typed outputs, but final agent results should also be able to declare JSON Schema output and
publish a validated `structured_output.json` artifact. This would help:

- editor integrations;
- automation consumers;
- dashboards;
- mentor summaries;
- research tables;
- bead status updates;
- external API clients.

Use deterministic validation, include extraction errors, and keep the raw chat/artifacts for audit.

### 8. Add a shareable artifact/replay surface

Manus uses replay/share links as part of its product story. SASE can implement a local-first equivalent:

- static HTML/PDF run bundle for a completed agent;
- prompt, plan, chat, diff, artifacts, structured outputs, and timeline;
- redaction pass for secrets/paths;
- optional mobile/web gateway view;
- stable links from notifications and SDD frontmatter.

This would make SASE easier to explain, review, and teach.

### 9. Upgrade scheduled automation UX

AXE is powerful but low-level. Add a scheduled-work facade:

- named scheduled tasks;
- natural or cron schedule;
- target project/workspace/query;
- workflow/xprompt to run;
- last/next run;
- failure policy;
- notification destination;
- run history;
- pause/resume.

This can compile down to existing axe/lumberjack infrastructure.

### 10. Add cost budgets and stop conditions

For long-running agents, especially future map/reduce work, require optional budgets:

- max wall time;
- max token spend or provider credits when available;
- max spawned agents;
- max external calls;
- stop on first failure vs continue and summarize;
- notify before expensive continuation.

This is a practical answer to the cost unpredictability seen in broad autonomous platforms.

### 11. Keep autonomy bounded by VCS and review gates

The clearest strategic lesson is negative: do not chase full autonomy at the cost of software-engineering correctness.
SASE should make the easy path:

1. capture intent;
2. decompose work;
3. run agents in isolated workspaces;
4. collect artifacts and structured outputs;
5. run mentors/tests/hooks;
6. present human approval;
7. commit with traceability.

This is less flashy than "leave it to Manus", but better matched to production code.

### 12. Adopt KV-cache-aware prompt and tool plumbing

Translate the Manus context-engineering lessons into concrete SASE conventions:

- xprompt/skill renderers should keep a **stable prefix** (system prompt, project profile, tool catalog) and put
  volatile content (timestamps, run IDs, dynamic memory matches) *after* it.
- Tool catalogs should be **append-only within a run**; gate availability via masking/no-op stubs instead of removing
  tool definitions mid-conversation.
- Large tool observations (web fetch bodies, file dumps, search results) should be **spilled to the workspace** and
  referenced by path/hash, with a short structured stub kept inline.
- Provide a `sase doctor` / lint check that flags cache-hostile patterns (early-prefix timestamps, non-deterministic
  JSON ordering, mid-run tool mutation).
- Surface estimated KV-cache hit rate per agent run in telemetry next to token counts so authors can see the cost
  impact of their prompt edits.

### 13. Use the workspace as long-horizon memory, deliberately

Manus uses its sandbox file system as an explicit memory store; SASE has a richer notion of workspace but uses it
mostly as a build directory. Promote the workspace to a memory tier:

- Standard subpaths (e.g. `.sase/run/<id>/notes/`, `.../observations/`, `.../scratch/`) for agent-written context.
- A "recall" tool the agent can use to re-read its own earlier notes and observations by topic, not by scrolling chat.
- A periodic `todo.md` recitation injected into the prompt so the agent re-grounds in the active plan.
- Automatic redaction/summary of stale scratch files when the run wraps, with the originals retained in artifacts.

### 14. Consider optional browser/local-desktop bridges only with narrow scope

SASE could benefit from browser automation for docs, issue trackers, dashboards, and web QA, but should avoid broad
ambient control. A safe design would be:

- per-task opt-in;
- specific browser profile or Playwright context;
- no stored passwords in SASE;
- explicit domain allowlist;
- action logs;
- stop/takeover controls;
- separate permission for authenticated sessions;
- no filesystem access beyond the workspace unless explicitly granted.

## Prioritized Roadmap Ideas

| Priority | Idea | Why |
| --- | --- | --- |
| P0 | Unified task lifecycle and schema-based waiting events | Connects existing SASE strengths and improves every surface. |
| P0 | Structured final output artifact | Makes SASE automation easier to consume programmatically. |
| P0 | KV-cache-aware prompt/tool plumbing | Pure-internal change with the largest cost/latency payoff; informed by published Manus numbers (≈10× cached vs. uncached input cost on Claude Sonnet). |
| P1 | First-class map/reduce agent mode | Captures Manus Wide Research's strongest technical abstraction in a SASE-native way. |
| P1 | Project profile surface | Reduces setup friction and makes recurring workflows legible. |
| P1 | Cost budgets / stop conditions | Required for safe wider parallelism and long-running agents; addresses credit-burn complaints seen on Manus. |
| P1 | Workspace-as-memory conventions and recitation | Cheap intervention with outsized effect on long-horizon runs. |
| P2 | Shareable run/replay bundles + chronological replay view | Improves collaboration, review, onboarding, and demos; mirrors Manus's most-loved UX surface. |
| P2 | Connector permission summary | Prepares for broader integrations without weakening trust. |
| P2 | Scheduled-task UX over AXE | Makes existing automation more approachable. |
| P3 | Browser/local desktop bridge | Useful but security-sensitive; only after lifecycle, permissions, and audit logs are solid. |

## Bottom Line

Manus shows that users respond to an agent that feels like an outcome-producing worker: asynchronous, connected,
parallel, collaborative, and able to publish polished deliverables. SASE should borrow that product clarity, especially
around task lifecycle, wide parallel work, connector packaging, structured outputs, scheduled runs, and shareable
artifacts.

SASE should not copy Manus's broad autonomy posture. Its strongest differentiation is that it treats software
engineering as a structured system: durable intent, tracked work units, VCS state, repeatable workflows, review gates,
and provider portability. The best path is to make those strengths easier to launch, inspect, integrate, and share.
