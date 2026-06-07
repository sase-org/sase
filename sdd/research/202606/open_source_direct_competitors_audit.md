# Open-Source Direct Competitors to SASE — GitHub Audit

Date: 2026-06-07

## Question

Which **open-source** projects compete *directly* with SASE, as opposed to the agent runtimes SASE wraps or the
component libraries it could reuse? Where does each one overlap SASE, and what (if anything) is left as SASE's
defensible differentiation?

## Method

- Hard repo data (exact stars, license, last push, archived status) pulled live from the GitHub CLI (`gh repo view` /
  `gh search repos`) on **2026-06-07**. Star counts are large because this category has grown explosively over the past
  year; the headline numbers were re-verified directly (see Sources) and are reported as the GitHub API returned them.
- Positioning/feature/license-status checked with web search and direct page fetches.
- Three parallel sub-audits, one per competitive category (fleet orchestrators, self-hosted SWE platforms, spec/task
  layers), then deduplicated and synthesized here.
- Several repos resolve through GitHub renames/transfers — noted inline (e.g. `steveyegge/beads` →
  `gastownhall/beads`, `All-Hands-AI/OpenHands` → `OpenHands/OpenHands`, `ComposioHQ/agent-orchestrator` →
  `AgentWrapper/agent-orchestrator`, `sst/opencode` → `anomalyco/opencode`).

## How "direct competitor" is scoped

SASE's README defines it precisely: *"sase orchestrates coding agents into tracked, repeatable engineering workflows. It
gives agent runs a durable operating layer: isolated workspaces, reusable prompts, scheduling, status, review state, and
commit flow."* The goal is explicitly **not to replace coding agents** — SASE wraps Claude Code, Gemini CLI, Codex, Qwen
Code, and OpenCode.

So the audit applies this lens:

- **Agent runtimes** (Claude Code, OpenCode, Qwen, Goose, Aider, Cline, Crush, …) are **complementary** — SASE drives
  them. They are *not* direct competitors. They were already covered in `202605/cli_agent_harnesses_for_sase.md` and
  `202605/qwen_opencode_vs_codex_claude.md`.
- **Memory/RAG frameworks** (Mem0, Letta, Zep, …) are **components**, not competitors. Covered in
  `202605/memory_system_prior_art.md`.
- A **direct competitor** is an open-source tool that provides the *operating layer itself*: orchestrating a fleet of
  agents across isolated workspaces, and/or the structured-engineering layer (spec-driven dev, PR/CL lifecycle tracking,
  agent-portable issue tracking, reusable prompt workflows).

SASE's seven pillars, used as the overlap rubric throughout: **ACE** (live TUI fleet view) · **workspace isolation**
(ephemeral per-task git clones/worktrees) · **AXE** (background scheduling/automation daemon) · **ChangeSpecs**
(PR/CL lifecycle state WIP→Draft→Ready→Mailed→Submitted, comments, review) · **XPrompt** (reusable prompt templates +
typed YAML workflows) · **SDD + Beads** (spec-driven planning + git-portable issue/dependency tracking) · **Memory**.

## Bottom line

1. **The directly competitive category is real, crowded, and exploded in the last year.** A year ago the closest
   comparables were Gas Town and OpenHands. Today there are 30+ open-source tools whose core *is* "run/manage many
   coding agents in isolated workspaces with a UI." This is now the single most contested space SASE sits in.

2. **No single open-source project covers all of SASE's pillars.** Every competitor nails a subset — most commonly
   *fleet view + workspace isolation* (Tier 1) or *one* of {spec-driven dev, issue tracking, prompt commands} (Tier 3).
   SASE's combination of a **TUI fleet view + a true background scheduling daemon (AXE) + first-class PR/CL review-state
   tracking (ChangeSpecs) + reusable prompt workflows (XPrompt) + spec-driven dev + git-portable issue tracking +
   memory**, all local-first on a shared Rust core, is not matched by any one OSS project.

3. **The four pillars that are rarest in the field — SASE's wedge — are:** (a) AXE's background **scheduling/automation
   daemon** (essentially no competitor has a cron-style agent scheduler), (b) **ChangeSpec PR/CL lifecycle as
   first-class durable state** with review, (c) **XPrompt** reusable typed prompt workflows, and (d) the **shared Rust
   core** enabling cross-frontend consistency.

4. **The closest single architectural twins to watch:** `AgentWrapper/agent-orchestrator` (ex-Composio) and **Gas Town**
   among self-hosted orchestrators; **claude-squad**, **cmux**, and **emdash** among TUI/desktop fleet managers;
   **GitHub Spec Kit**, **OpenSpec**, **Task Master**, and **Beads** (the name collision is real) on the structured-work
   layer.

5. **"Local-first" is becoming a trend, not a moat.** Plandex Cloud is winding down, Vibe Kanban's commercial product is
   sunsetting to community OSS, and Conductor/Superset/Tessl are pushing the polished-but-closed end. SASE should lean on
   *operating-layer breadth + durability*, not local-first alone.

---

## Category 1 — Parallel agent fleet orchestrators (most direct to ACE + workspace isolation)

Open-source TUI/CLI/desktop tools whose primary job is to **run and manage multiple coding agents in parallel across
isolated workspaces** (git worktrees / containers), usually with a dashboard. This is the most direct analog to SASE's
ACE + ephemeral-workspace core. A community index now exists: `andyrewlee/awesome-agent-orchestrators` (its "Parallel
Agent Runners" section maps almost 1:1 to this category).

### Tier 1A — strongest direct overlap

| Project | Repo | Stars | License | Last push | Overlap | One-line vs SASE |
| --- | --- | --- | --- | --- | --- | --- |
| **claude-squad** | `smtg-ai/claude-squad` | 7,740 | AGPL-3.0 | 2026-05-18 | DIRECT (ACE, isolation) | Canonical OSS "fleet TUI + tmux + worktree isolation"; lacks AXE scheduling, ChangeSpec lifecycle, XPrompt, memory. |
| **cmux** | `manaflow-ai/cmux` | 21,333 | AGPL-3.0 (+commercial) | 2026-06-07 | DIRECT (ACE, isolation, PR surface) | Native macOS fleet UI w/ per-workspace branch/PR status + scriptable browser; macOS-only, no scheduling/lifecycle/XPrompt/memory. |
| **vibe-kanban** | `BloopAI/vibe-kanban` | 26,830 | Apache-2.0 | 2026-04-24 | DIRECT/PARTIAL (board fleet + task tracking) | Highest-mindshare kanban orchestrator (Claude/Codex/Gemini/Amp); board-first, no TUI fleet, no AXE, shallow lifecycle. Commercial arm sunsetting → community OSS. |
| **emdash** | `generalaction/emdash` | 4,779 | Apache-2.0 | 2026-06-07 | DIRECT (ACE, isolation, multi-runtime) | Fastest-rising true-OSS "agentic dev environment" (YC W26), daily-active; desktop, no scheduling/lifecycle/XPrompt/memory. |
| **Crystal / Nimbalyst** | `stravu/crystal` | 3,076 | MIT | 2026-02-26 | DIRECT (fleet, isolation, diff/compare) | GUI to run parallel Codex/Claude in worktrees with strong side-by-side compare/merge; rebranding to Nimbalyst; no TUI/daemon/lifecycle/memory. |
| **mux** | `coder/mux` | 1,817 | AGPL-3.0 | 2026-06-07 | DIRECT (fleet, isolation) | Coder-backed desktop app for isolated parallel agentic dev; desktop-first, lacks SASE's structured layers. |
| **1code** | `21st-dev/1code` | 5,554 | Apache-2.0 | 2026-03-06 | DIRECT/PARTIAL (fleet UI + remote exec) | UI for Claude Code with local *and* remote execution; less active lately. |

### Tier 1B — worktree-first runners / multi-runtime session managers

| Project | Repo | Stars | License | Last push | Notes |
| --- | --- | --- | --- | --- | --- |
| **ccmanager** | `kbwo/ccmanager` | 1,142 | MIT | 2026-05-31 | TUI session manager across many runtimes (Claude/Gemini/Codex/Cursor/Copilot/Cline/OpenCode/Kimi) + worktree isolation. Multi-runtime like SASE. |
| **jean** | `coollabsio/jean` | 1,028 | Apache-2.0 | 2026-06-06 | Desktop & web app orchestrating Claude/Codex/OpenCode across projects + worktrees. |
| **parallel-code** | `johannesjo/parallel-code` | 704 | MIT | 2026-06-05 | Desktop: Claude/Codex/Gemini side-by-side, each in its own worktree, diff + one-click merge. |
| **dmux** | `standardagents/dmux` | 1,624 | MIT | 2026-05-25 | Dev-agent multiplexer over git worktrees; CLI, no dashboard/scheduling. |
| **workmux** | `raine/workmux` | 1,595 | MIT | 2026-06-06 | git worktrees + tmux windows, one agent per feature. |
| **Dorothy** | `Charlie85270/Dorothy` | 298 | MIT | 2026-05-05 | Desktop orchestrator w/ automations + Kanban + MCP — automations partially echo AXE. |
| **constellagent** | `owengretzinger/constellagent` | 210 | none | 2026-05-05 | Each agent gets its own terminal+editor+worktree in one window. |
| **amux** | `andyrewlee/amux` | 122 | MIT | 2026-06-07 | TUI for parallel agents (author of the awesome-list); exact ACE shape, minus structured layers. |
| **uzi** | `devflowinc/uzi` | 579 | MIT | 2025-06-04 | Influential CLI for many parallel worktree agents — **stale ~1yr**, likely dormant. |

### Tier 1C — issue/board-driven orchestration & container-sandbox backends

| Project | Repo | Stars | License | Last push | Notes |
| --- | --- | --- | --- | --- | --- |
| **agent-kanban** | `saltbo/agent-kanban` | 331 | source-available | 2026-06-06 | Agent-first kanban, leader-worker, multi-runtime. |
| **sortie** | `sortie-ai/sortie` | 73 | Apache-2.0 | 2026-06-03 | Turns tracker tickets into autonomous agent sessions (Go + SQLite) — light AXE-from-issues. |
| **agentbox** | `madarco/agentbox` | 48 | MIT | 2026-06-07 | Parallel agents each in a sandboxed box (Docker/cloud VM), sub-1s checkpoints. |
| **container-use** | `dagger/container-use` | 3,813 | Apache-2.0 | 2026-02-23 | COMPLEMENTARY — per-agent dev environments; an isolation *primitive* (containers vs SASE's git clones), no fleet UI. |
| **catnip** | `wandb/catnip` | 485 | Apache-2.0 | 2026-05-20 | W&B agentic coding tool; partial/complementary. |
| **gwq** | `d-kuro/gwq` | 426 | Apache-2.0 | 2026-05-02 | COMPLEMENTARY — pure git-worktree manager marketed for parallel AI workflows. |

### Category 1 — most direct (ranked)

1. **claude-squad** — the canonical OSS "fleet TUI + worktree isolation," same core shape as ACE; the highest-credibility
   one-to-one comparison.
2. **cmux** — 21k★, very active, native fleet UI with per-workspace branch/PR status + isolation; strongest funded OSS
   analog to ACE + workspace isolation (macOS-only).
3. **emdash** — fastest-rising true-OSS agentic dev environment (YC W26), provider-agnostic parallel agents in isolated
   workspaces.

*Honorable mention:* **vibe-kanban** for sheer board mindshare (26.8k★).

---

## Category 2 — Self-hosted autonomous SWE platforms (end-to-end overlap)

Open-source platforms/terminal agents that bring their **own durable workflow layer** (planning, sandboxing, state
persistence, PR handling) and so overlap SASE end-to-end, not just as a single chat agent.

| Project | Repo | Stars | License | Last push | Overlap | One-line vs SASE |
| --- | --- | --- | --- | --- | --- | --- |
| **OpenHands** (ex-OpenDevin) | `OpenHands/OpenHands` | 76,082 | custom (MIT-family) | 2026-06-07 | DIRECT (orchestration, sandbox isolation, skills/memory) | The category gravity well; now V1 on a `software-agent-sdk`, skills replace microagents. SASE differs on multi-runtime *wrapping*, TUI fleet, AXE scheduling, ChangeSpec review-state, XPrompt. |
| **Gas Town** | `gastownhall/gastown` | 15,768 | MIT | 2026-06-06 | DIRECT (fleet, isolation, merge queue, Beads memory) | Yegge's "Kubernetes for coding agents" — role agents (Mayor/Polecats/Witness/Refinery), git-backed Beads as memory/control plane; now has a cloud version (Kilo). SASE adds a structured TUI, AXE, XPrompt, SDD, Rust core. |
| **Composio Agent Orchestrator** | `AgentWrapper/agent-orchestrator` (ex `ComposioHQ/…`) | 7,438 | MIT | 2026-06-01 | DIRECT — closest architectural twin | Agent-agnostic + runtime-agnostic fleet over git worktrees with autonomous PR-lifecycle (CI fixes, conflict/review handling) + Linear/GitHub. Lacks AXE scheduling, XPrompt, SDD, memory, Rust core. ⚠️ org rename/transfer — verify provenance before citing. |
| **Open SWE** | `langchain-ai/open-swe` | 9,928 | MIT | 2026-06-07 | DIRECT (async long-running, sandbox isolation, PR creation) | LangGraph-based async agent, mid-run steerable, pluggable sandboxes (Daytona/Modal/Runloop); self-hostable but cloud-/sandbox-leaning. No multi-runtime wrap, TUI fleet, AXE, review-state, SDD. Fastest-moving new entrant. |
| **Plandex** | `plandex-ai/plandex` | 15,441 | MIT | 2025-10-03 | DIRECT (sandbox isolation, plan versioning, git) | Terminal agent for large multi-file tasks w/ a quarantine "diff sandbox" + version-controlled plans + 2M-token tree-sitter maps. Its own engine (not a wrapper); needs PostgreSQL; **commit cadence slowing (~8mo)**. No TUI fleet, AXE, multi-runtime, SDD. |
| **SWE-agent** | `SWE-agent/SWE-agent` | 19,444 | MIT | 2026-06-06 | PARTIAL (sandboxed exec, batch/parallel) | Princeton research issue-fixer via Agent-Computer Interface; `run-batch` for parallel runs. Benchmark-oriented single-shot, not a durable operating layer. (Related: `mini-swe-agent` 4,988★; `SWE-ReX` 520★ is the parallel sandbox backend ≈ isolation primitive.) |

### Refresh — runtimes/IDE agents with *partial* platform overlap (mostly complementary)

| Project | Repo | Stars | License | Last push | Note |
| --- | --- | --- | --- | --- | --- |
| **OpenCode** | `anomalyco/opencode` (ex `sst/opencode`) | 171,018 | MIT | 2026-06-07 | COMPLEMENTARY — SASE *wraps* it as a supported runtime, not a competitor. |
| **Goose** | `block/goose` | 47,135 | Apache-2.0 | 2026-06-06 | PARTIAL — extensible local agent, MCP-native; general-purpose, not SWE-fleet. |
| **Cline** | `cline/cline` | 62,869 | Apache-2.0 | 2026-06-07 | PARTIAL — SDK/IDE/CLI with plan-act + orchestrator modes; single-agent at heart. |
| **Aider** | `Aider-AI/aider` | 45,850 | Apache-2.0 | 2026-05-22 | COMPLEMENTARY — terminal pair-programmer (architect/editor split, repo map, atomic git commits); wrappable as a runtime. |
| **Roo Code** | `RooCodeInc/Roo-Code` | 24,211 | Apache-2.0 | 2026-05-15 | **ARCHIVED** — VS Code orchestrator modes (Cline-lineage); no longer maintained under this repo. |
| **Coder** | `coder/coder` | 13,383 | AGPL-3.0 | 2026-06-07 | COMPLEMENTARY — self-hosted dev-environment substrate now positioned for "developers and their agents"; could *run* SASE, not replace it. |

### Category 2 — most direct (ranked)

1. **Composio Agent Orchestrator** — closest architectural twin: agent- *and* runtime-agnostic fleet + worktree
   isolation + autonomous PR lifecycle, self-hosted; overlaps the most SASE pillars at once.
2. **Gas Town** — most direct *philosophical* competitor: local-first multi-agent fleet + git-backed issue
   tracking/memory + merge orchestration, in the exact "dependable agentic engineering" framing.
3. **OpenHands** — broadest end-to-end overlap and by far the largest mindshare/momentum.

*Honorable mention:* **Open SWE** — async + LangGraph ecosystem momentum, pushed daily.

### Research demos / dormant (historically relevant, not live threats)

- **Devika** `stitionai/devika` — 19,510★, MIT, last push 2025-09-25 (~9mo stale). First open Devin clone; stalled.
- **Devon** `entropy-research/Devon` — 3,449★, AGPL-3.0, push 2025-05-26 (>1yr). Abandoned.
- **MetaGPT** `FoundationAgents/MetaGPT` — 68,609★, MIT — multi-agent "AI software company" *framework*, not an operating layer.
- **ChatDev** `OpenBMB/ChatDev` — 33,339★, Apache-2.0 — "virtual software company" research project.
- **AutoGPT** `Significant-Gravitas/AutoGPT` — 184,807★ — generic autonomous-agent platform, low SWE-workflow overlap.

---

## Category 3 — Spec-driven development + agentic task/issue tracking + prompt-workflow libraries

These overlap SASE's structured-engineering layer (SDD + ChangeSpecs + Beads + XPrompt). Almost all are stateless prompt/
command scaffolds or standalone trackers — each covers *one* of SASE's four structured pillars.

### Tier 3A — direct / strong overlap

| Project | Repo | Stars | License | Last push | Overlap | One-line vs SASE |
| --- | --- | --- | --- | --- | --- | --- |
| **GitHub Spec Kit** | `github/spec-kit` | 109,774 | MIT | 2026-06-06 | DIRECT — SDD/specs (+ XPrompt-ish) | The category-defining SDD toolkit; `specify` scaffolds `/specify→/plan→/tasks→/implement` slash commands. Stateless scaffold — no durable ChangeSpec lifecycle, no Beads graph, no orchestration. |
| **OpenSpec** | `Fission-AI/OpenSpec` | 53,276 | MIT | 2026-06-03 | DIRECT — SDD + change-proposal ≈ ChangeSpecs | Closest concept to SDD + ChangeSpec proposals (approval-before-code on spec deltas); but no real VCS PR lifecycle, no dependency graph, no orchestration. |
| **BMAD-METHOD** | `bmad-code-org/BMAD-METHOD` | 48,707 | MIT | 2026-06-07 | DIRECT/PARTIAL — SDD + story units ≈ Beads | Role-based agentic agile method (Analyst/PM/Architect/SM/Dev) → PRD→architecture→sharded stories. A methodology + persona pack, not an operating layer. |
| **Task Master** | `eyaltoledano/claude-task-master` | 27,344 | MIT + Commons Clause | 2026-04-28 | DIRECT — Beads + PRD→tasks half of SDD | Leading "PRD → tasks → code" engine; tasks are flat JSON, no git-portable graph, no lifecycle/orchestration. ⚠️ Commons Clause restricts commercial resale (not fully OSI-open). |
| **Beads** | `gastownhall/beads` (ex `steveyegge/beads`) | 24,390 | MIT | 2026-06-07 | DIRECT — essentially SASE's Beads concept | Yegge's git-native, dependency-aware agent issue tracker ("memory upgrade for your agent"); JSONL graph that travels with the repo. **Most direct competitor to the Beads layer specifically — same concept and name.** Issue tracker only; no SDD/ChangeSpec/XPrompt/orchestration. |

### Tier 3B — partial overlap

| Project | Repo | Stars | License | Last push | Notes |
| --- | --- | --- | --- | --- | --- |
| **Backlog.md** | `MrLesk/Backlog.md` | 5,696 | MIT | 2026-05-30 | Markdown/git task + kanban tool for human+AI; tasks as `.md`. Beads-lite, no dependency semantics. |
| **spec-workflow-mcp** | `Pimzino/spec-workflow-mcp` | 4,217 | GPL-3.0 | 2026-05-05 | MCP server for requirements→design→tasks + live dashboard/VSCode ext. SDD + light task tracking. |
| **Agent OS** | `buildermethods/agent-os` | 4,784 | MIT | 2026-05-05 | Standards + spec-generation prompt scaffolding; SDD + context engineering, not tracked workflow. |
| **potpie** | `potpie-ai/potpie` | 5,418 | Apache-2.0 | 2026-06-07 | "Spec-driven dev for large codebases" via code-knowledge-graph agents; more comprehension than workflow. |
| **claude-code-spec-workflow** | `Pimzino/claude-code-spec-workflow` | 3,759 | MIT | 2025-09-07 | Slash-command pack for Req→Design→Tasks→Impl; stale, superseded by the author's MCP server. |
| **spec-kitty** | `Priivacy-ai/spec-kitty` | 1,302 | MIT | 2026-06-07 | SDD + kanban dashboard + git worktrees + auto-merge, multi-agent — the most SASE-feature-rich of the small SDD tools. |

### Tier 3C — niche specs + prompt/command libraries (compete with XPrompt's template side, not its workflow engine)

- **shotgun** `shotgun-sh/shotgun` (679★, MIT), **LeanSpec** `codervisor/leanspec` (258★), **specs.md** `fabriqaai/specs.md`
  (170★), **chainlink** `dollspace-gay/chainlink` (343★, Beads-lite), **agent-teams-lite** `Gentleman-Programming/…`
  (1,226★, **archived**).
- Prompt/command collections: `hesreallyhim/awesome-claude-code` (45,883★), `VoltAgent/awesome-claude-code-subagents`
  (21,313★), `wshobson/commands` (2,502★, stale), `gsd-build/get-shit-done` (63,990★, MIT — meta-prompting + SDD).
  These are reusable *templates* (XPrompt's static side) but none offer **typed inputs + output-variable handoffs in a
  YAML multi-step workflow engine** like XPrompt.

### Category 3 — most direct (ranked)

1. **GitHub Spec Kit** — category-defining, highest-mindshare SDD toolkit; the default reference everyone compares to.
2. **Beads** — most direct competitor to SASE's Beads layer specifically (same git-portable issue-graph concept *and*
   name), with a fork ecosystem and tight ties to Gas Town.
3. **Task Master** — the leading PRD→tasks→code engine; huge install base (license caveat applies).

*Honorable mentions spanning the most SASE layers in one tool:* **OpenSpec** (SDD + change-proposal ≈ ChangeSpec) and
**BMAD-METHOD** (PRD→architecture→stories).

---

## Closed-source / source-available "competitors to watch" (excluded from the OSS count, flagged here)

These are conceptually direct but **not OSI open source**, so they don't satisfy the request — listed so they aren't
mistaken for OSS:

- **Conductor** (conductor.build, Melty Labs/YC) — CLOSED, macOS-only. Parallel agents in isolated workspaces + auto
  PR/merge. The most prominent *closed-source* direct competitor to ACE + workspace isolation. (Its predecessor Melty
  was OSS; Conductor is not.)
- **Superset** `superset-sh/superset` (11,614★) — **Elastic License 2.0 (source-available, not OSI)**. "Code editor for
  the AI agents era": army of Claude/Codex over isolated worktrees + review.
- **Sculptor** `imbue-ai/sculptor` (171★) — source-available ("Other"). Desktop, each agent in its own *container*
  (explicitly no worktrees). Direct on concept; well-funded (Imbue).
- **Kiro** (AWS, kiro.dev; `kirodotdev/Kiro` 3,836★ no source) — PROPRIETARY spec-driven agentic IDE
  (requirements→design→tasks→code), Claude-via-Bedrock; positioned as the Amazon Q Developer successor. Conceptually a
  direct SDD competitor, but a closed SaaS/IDE.
- **Tessl** (tessl.io, Snyk founder; ~$125M Series A) — CLOSED "spec-as-source" platform (Framework + 10,000+-spec
  Registry). Direct on specs-as-source; only a tiny public adapter is open.
- Also source-available / restrictive-license: **cmux** (AGPL + commercial), **Sketch** `boldsoftware/sketch` (703★,
  "Other"), **agent-kanban** (source-available).

---

## Not competitors (complementary — for the record)

- **Agent runtimes SASE wraps:** Claude Code, Gemini CLI, Codex, Qwen Code, OpenCode — and adjacent single-agent CLIs
  (Goose, Aider, Cline, Crush, gptme, Amp). SASE drives these; growth here *helps* SASE. See
  `202605/cli_agent_harnesses_for_sase.md`.
- **Isolation primitives:** `dagger/container-use`, `coder/coder`, `d-kuro/gwq`, `SWE-agent/SWE-ReX` — building blocks
  SASE could integrate, not orchestration layers.
- **Memory/RAG frameworks:** Mem0, Letta/MemGPT, Zep/Graphiti, A-MEM, HippoRAG, Cognee — components, see
  `202605/memory_system_prior_art.md`.

---

## Consolidated "most direct" shortlist (the names to track)

| Rank | Project | Repo | Stars | Why it's the closest |
| --- | --- | --- | --- | --- |
| 1 | Composio Agent Orchestrator | `AgentWrapper/agent-orchestrator` | 7,438 | Closest architectural twin: agent+runtime-agnostic fleet, worktree isolation, autonomous PR lifecycle, self-hosted. |
| 2 | Gas Town | `gastownhall/gastown` | 15,768 | Same "dependable local-first agentic engineering fleet" framing + git-backed Beads control plane. |
| 3 | claude-squad | `smtg-ai/claude-squad` | 7,740 | The canonical OSS ACE analog (fleet TUI + worktree isolation). |
| 4 | cmux | `manaflow-ai/cmux` | 21,333 | Funded, very active native fleet UI w/ per-workspace branch/PR status (macOS). |
| 5 | OpenHands | `OpenHands/OpenHands` | 76,082 | Broadest end-to-end SWE-platform overlap + dominant mindshare. |
| 6 | GitHub Spec Kit | `github/spec-kit` | 109,774 | Category-defining SDD layer; reference point for spec-driven work. |
| 7 | Beads | `gastownhall/beads` | 24,390 | Direct competitor to SASE's Beads (concept + name collision). |
| 8 | vibe-kanban | `BloopAI/vibe-kanban` | 26,830 | Highest-mindshare board orchestrator. |
| 9 | Task Master | `eyaltoledano/claude-task-master` | 27,344 | Leading PRD→tasks→code engine (Beads + SDD overlap). |
| 10 | Open SWE | `langchain-ai/open-swe` | 9,928 | Fastest-rising async self-hostable SWE agent. |

---

## SASE's differentiation wedge

Mapping the field onto SASE's seven pillars, this is what is **rare-to-absent** across all open-source competitors:

| SASE pillar | Covered by competitors? | Verdict |
| --- | --- | --- |
| ACE — TUI fleet view | Common (claude-squad, ccmanager, amux; GUIs: cmux, emdash, mux) | **Contested** — table stakes now. |
| Workspace isolation | Near-universal (worktrees or containers) | **Contested** — table stakes. |
| Multi-runtime wrapping | Some (vibe-kanban, ccmanager, Composio AO) | **Partially contested.** |
| ChangeSpecs — PR/CL lifecycle + review state | Rare; Composio/Conductor automate PRs but don't track durable review *state*; OpenSpec tracks spec proposals only | **Strong wedge.** |
| AXE — background scheduling/automation daemon | Essentially none (Dorothy/sortie touch automation-from-issues) | **Strongest wedge.** |
| XPrompt — typed reusable prompt *workflows* | Template collections exist; typed YAML workflow engine w/ output handoffs does not | **Strong wedge.** |
| SDD + Beads (integrated) | Each exists separately (Spec Kit; Beads/Task Master) but not integrated with lifecycle + orchestration | **Wedge via integration.** |
| Memory | Frameworks exist as components; few orchestrators ship it (Gas Town via Beads) | **Moderate wedge.** |
| Shared Rust core (cross-frontend) | None | **Structural wedge.** |

**The defensible story:** competitors win individual pillars (fleet view, isolation, specs, issue tracking), but *no
open-source project combines the durable operating layer end-to-end* — fleet + isolation + scheduling daemon + PR/CL
review-state + prompt workflows + spec-driven dev + portable issue tracking + memory, on one local-first Rust-backed
substrate. That integration, not any single feature, is the moat.

## Strategic implications

1. **Stop comparing SASE to runtimes; compare it to the operating layer.** The relevant peer set is now Composio AO / Gas
   Town / claude-squad / Spec Kit / Beads — not Claude Code or OpenCode. A public comparison page (already a P2 item in
   `202606/sase_install_use_understand_readiness_consolidated.md`) should target *these*.
2. **Lead with AXE + ChangeSpecs + XPrompt.** These are the pillars almost nobody else has. The fleet-view + isolation
   demo is no longer differentiating on its own.
3. **Address the Beads name collision.** `gastownhall/beads` (24k★, Yegge) is high-profile and shares SASE's exact term.
   Either differentiate sharply or risk confusion; worth a deliberate naming/positioning decision.
4. **Don't over-index on local-first.** It's becoming common (and several "cloud" peers are retreating to OSS/self-host).
   The durability + breadth of the operating layer is the more durable claim.
5. **Watch the fast movers:** Composio AO (autonomy/throughput), Open SWE (async + LangGraph momentum), emdash/cmux
   (funded fleet UIs), Spec Kit/OpenSpec (SDD mindshare). All pushed within days of this audit.

## Open questions / follow-ups

- Worth a dedicated deep-dive note on the single closest twin, **Composio Agent Orchestrator**, the way prior research
  did for Gas Town / OpenHands / Manus?
- Should SASE publish a SDD interop story (import/export with Spec Kit / OpenSpec specs) rather than competing head-on?
- Does the Beads name collision warrant a rename, or a "compatible-with-Beads" stance?
- Re-run this audit quarterly — the category added ~25 projects in the last year; numbers here will drift fast.

## Relationship to prior research

This note focuses on the **operating-layer / orchestration** competitors that prior files under-covered. It complements:

- `202605/sase_vs_gastown.md` — deep Gas Town comparison (refreshed here: 15.8k★, cloud "Kilo" version added).
- `202605/openhands_vs_sase.md` — deep OpenHands comparison (refreshed: 76k★, V1 on software-agent-sdk).
- `202605/manus_vs_sase_lessons.md`, `202605/mantis_vs_sase.md`, `202604/sase_vs_hermes_agent.md`,
  `202604/sase_vs_codex_comparison.md` — single-agent assistants / commercial platforms.
- `202605/cli_agent_harnesses_for_sase.md`, `202605/qwen_opencode_vs_codex_claude.md` — the *runtimes* SASE wraps
  (complementary, not competitors).
- `202605/memory_system_prior_art.md` — memory *components* (not competitors).

## Sources

GitHub data (live `gh repo view` / `gh search repos`, 2026-06-07): all repos listed above, re-verified for the
shortlist — `github/spec-kit`, `Fission-AI/OpenSpec`, `eyaltoledano/claude-task-master`, `gastownhall/beads`,
`gastownhall/gastown`, `OpenHands/OpenHands`, `plandex-ai/plandex`, `langchain-ai/open-swe`,
`AgentWrapper/agent-orchestrator`, `smtg-ai/claude-squad`, `manaflow-ai/cmux`, `BloopAI/vibe-kanban`,
`generalaction/emdash`, `stravu/crystal`, `anomalyco/opencode`, `bmad-code-org/BMAD-METHOD`, `coder/mux`,
`superset-sh/superset`.

Community index: `github.com/andyrewlee/awesome-agent-orchestrators` (Parallel Agent Runners section).

Web/positioning: conductor.build, kiro.dev, tessl.io, nimbalyst.com,
martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html (Spec Kit / Kiro / Tessl comparison), and project READMEs/
docs for the entries above.

Local: `README.md` (SASE positioning + supported-runtime table), `memory/short/*.md`.
