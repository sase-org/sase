# Research: SASE vs Nous Research Hermes Agent

**Source under review:** [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent)
("The agent that grows with you" — MIT-licensed, Python-dominant agent framework.)

**Methodology:** README + `agent/` directory inventory via WebFetch; cross-referenced against the SASE codebase
(`src/sase/`, `memory/`, `xprompts/`). I did not run Hermes locally; claims about Hermes internals are derived from its
public docs and filenames. Where Hermes detail is thin, I say so rather than guess.

---

## 1. Positioning

|                  | SASE                                                      | Hermes Agent                                                          |
| ---------------- | --------------------------------------------------------- | --------------------------------------------------------------------- |
| Primary user     | Engineer doing structured CL/PR work in a repo            | General-purpose personal assistant + coder                            |
| Primary surface  | TUI (`ace`) over local repo + ephemeral `sase_<N>` clones | CLI + multi-platform messaging gateway (Telegram, Discord, Slack, …)  |
| LLM strategy     | Wraps coding CLIs (Claude Code, Gemini CLI, Codex)        | Direct API adapters (Anthropic, Bedrock, Gemini native, OpenRouter, …)|
| Work atom        | ChangeSpec (`.gp` file) tied to a CL/PR                   | Conversation/task                                                     |
| Distinctive bet  | Deep CL/PR lifecycle automation (beads, epics, mentors)   | Self-improving skills + cross-platform persona reachable everywhere   |

These are different products. Hermes wants to be a single agent that follows you across phones and chats; SASE wants
to be the loom that weaves many short-lived coding agents into structured changes against a real repo. Most of the
contrasts below fall out of that framing.

---

## 2. Architectural Comparison

### 2a. Agent loop & provider integration

- **SASE** treats each agent as a **subprocess of a coding CLI**. `src/sase/axe/run_agent_exec.py` drives the loop;
  providers in `src/sase/llm_provider/` (claude, gemini, codex) are subprocess wrappers that map tier hints to model
  aliases. Spawn-on-retry (`run_agent_retry_spawn.py`) replaces an in-process retry with a freshly spawned detached
  child that inherits the workspace claim.
- **Hermes** runs an **in-process agent loop** with native API adapters (`anthropic_adapter.py`, `bedrock_adapter.py`,
  `gemini_native_adapter.py`). It owns prompt construction (`prompt_builder.py`), context shaping (`context_engine.py`,
  `context_compressor.py`), error classification (`error_classifier.py`), and rate-limit accounting
  (`nous_rate_guard.py`, `rate_limit_tracker.py`).

The key implication: **SASE inherits the host CLI's tool set and safety harness** and pays for it with a
process-per-turn boundary. **Hermes owns the loop** and therefore owns context compression, rate budgeting, and
trajectory capture as first-class concerns. Different tradeoffs — neither dominates.

### 2b. Skills

- **SASE** generates skills *into runtime-specific paths* (e.g. `~/.claude/skills/`, `~/.gemini/skills/`,
  `.gemini/jetski/skills/` for the `sase-google` plugin). They are authored in `xprompts/skills/` and expanded by the
  init-skills handler. Skills are **static artifacts** versioned with the repo.
- **Hermes** advertises **agent-curated skills**: created from experience, "self-improving during use," browseable via
  `/skills`, and shareable on agentskills.io (Skills Hub). It implements the open agentskills.io standard.

SASE's skill model is rigorous and reproducible; Hermes's is dynamic and social. The agentskills.io standard is
notable — adopting it would let SASE-authored skills be portable.

### 2c. Memory

- **SASE** has a deliberate **three-tier static memory** (`memory/short/`, dynamic via keyword match,
  `memory/long/`). Dynamic memory is **pre-session** keyword-driven injection with positive and negative keywords (see
  `gotchas.md`).
- **Hermes** combines:
  - persistent persona/user files (SOUL.md, MEMORY.md, USER.md migrated from OpenClaw),
  - **FTS5 session search with LLM summarization** (full-text recall over past chats),
  - **Honcho dialectic user modeling** (cross-session inference of user preferences),
  - explicit `/compress` for in-context window management.

Hermes's memory is **agent-initiated and adaptive** (search past sessions, infer the user); SASE's is
**author-curated and deterministic** (a human writes the memory file, keywords decide when it loads). The codified
context paper already noted this gap; Hermes is a concrete instance of the agent-initiated retrieval design.

### 2d. Multi-platform reach

- **SASE** has `src/sase/notifications/` + the external `sase-telegram` plugin. Telegram is bolted on; it isn't a
  general gateway abstraction.
- **Hermes** ships a **unified gateway process** spanning Telegram, Discord, Slack, WhatsApp, Signal, Email, plus
  voice-memo transcription and cross-platform conversation continuity. `hermes gateway {setup,start}` is a
  first-class subcommand.

If sase-org wants assistant-style reachability beyond the laptop, Hermes's gateway is a much more developed reference
than what's in the tree today.

### 2e. Deployment / execution sandboxing

- **SASE** runs in **ephemeral `sase_<N>` clones** of the host repo, each with its own venv. Workspace claims are
  atomic and transferable across spawn-on-retry boundaries.
- **Hermes** has six terminal backends: **local, Docker, SSH, Daytona, Singularity, Modal**, with the latter two
  offering serverless persistence with hibernation.

SASE's workspace model is tighter and IDE-friendly; Hermes's is broader and friendlier to running on a $5 VPS or a
serverless platform.

### 2f. Workflow / multi-agent composition

- **SASE** has **xprompts** (`src/sase/xprompt/`) — typed YAML workflows with parallel/sequential steps, control flow,
  HITL approval, and a multi-agent dispatch syntax (`---` body separators). Plus `bead work <epic_id>`'s
  Kahn-wave phase scheduler with rollback on launch failure.
- **Hermes** advertises "spawn isolated subagents for parallel workstreams" and "Python scripts call tools via RPC,"
  collapsing multi-turn pipelines into single-turn operations.

SASE's xprompts are far more structured (typed YAML, DAG, mentor hooks). Hermes's RPC-tool model is the more
interesting *primitive* — it eliminates the multi-turn tax for deterministic pipelines and is something xprompts
could learn from for `python:` steps.

### 2g. Scheduling & background work

- **SASE**: lumberjack daemon + chop scripts (`src/sase/axe/lumberjack.py`,
  `chop_script_runner.py`) drive periodic runs.
- **Hermes**: built-in cron with **natural-language scheduling delivered to platform channels** (e.g. "Daily at 9am,
  audit my inbox and Slack me a summary"). The delivery side is what makes it distinctive.

### 2h. Lifecycle artifacts (CL/PR, beads, mentors)

This is **SASE's strongest moat**. ChangeSpecs, the COMMITS drawer, mentor reviews, beads (epic → phase → land), the
tag suffix system, and submission workflows have no Hermes analog — Hermes treats work as conversation, not as
typed objects in a repo. Don't dilute this.

### 2i. Observability

- **SASE** has Prometheus + Grafana, a TUI dashboard, 33 metrics across 7 subsystems (`src/sase/telemetry/`).
- **Hermes** has `/usage` and `/insights --days N` for token telemetry; no evidence of structured metrics export.

Win for SASE.

### 2j. Research artifacts (RL / trajectories)

- **Hermes** ships trajectory capture (`agent/trajectory.py`), batch trajectory generation, trajectory compression,
  and Atropos RL environments — explicit infrastructure for **producing training data for tool-calling models**.
- **SASE** has no equivalent. Chat transcripts exist (`sase chats`) but aren't shaped for RL/eval consumption.

This is the cleanest "Hermes does something SASE doesn't even attempt" gap. Whether SASE *should* care depends on
whether sase-org wants to train its own models.

---

## 3. Where SASE is Stronger Than Hermes

To keep the comparison honest:

1. **Repo-grade structured work.** ChangeSpec / beads / epics / mentors / `.gp` files are a real model of "what an
   engineer does." Hermes has nothing comparable.
2. **Determinism and reproducibility.** Static memory tiers, generated skills, version-controlled xprompts. Hermes's
   self-improving skills and dialectic user model trade reproducibility for adaptability.
3. **Workspace isolation per agent.** `sase_<N>` clones with claim-transfer give cleaner concurrency than a single
   shared workspace.
4. **Provider-agnosticism via host CLIs.** SASE inherits Claude Code's / Gemini CLI's safety, tool sets, and updates
   for free. Hermes has to maintain adapters per provider.
5. **First-class observability.** Prometheus + dashboard.
6. **Spawn-on-retry with workspace claim transfer** — a sharper failure-recovery primitive than generic retry loops.

---

## 4. Recommended Improvements to SASE Inspired by Hermes

Ranked by expected leverage. Each is scoped to "what would actually be a good fit for SASE," not blind copy.

### 4.1. Full-text + LLM-summarized search over past agent chats — **HIGH leverage**

Hermes's FTS5 + summarization over past sessions is a clean answer to "what did agent X say last week about Y?" SASE
has `sase chats` but no real recall layer. Recommendation: index `sase chats` artifacts with SQLite FTS5 (or tantivy
via the new Rust backend) and expose `sase chats search <query>` plus an xprompt-callable retrieval skill so agents
can self-recall. This composes naturally with the codified-context paper's "agent-initiated retrieval" idea already
on file in `codified_context_paper_insights.md`.

### 4.2. Agent-initiated dynamic-memory retrieval (in addition to pre-session keyword match) — **HIGH leverage**

Already flagged in our codified-context research note. Hermes is a concrete existence proof. Add a tool/skill for
`find_relevant_memory(task)` that the agent can call mid-loop, in addition to the existing pre-session injection.
Keeps determinism for the common case, adds adaptivity for the long tail.

### 4.3. `/compress` and budgeted context management — **MEDIUM-HIGH leverage**

SASE relies on the host CLI's auto-compaction. A SASE-owned `/compress` (or pre-turn budgeter) that knows about
ChangeSpec / mentor / plan structure could be a lot smarter than generic compaction — e.g. preserve the plan, drop
old tool output. Especially relevant on long-running coder agents.

### 4.4. Adopt the agentskills.io skills standard for portability — **MEDIUM leverage**

If the standard is reasonable, having SASE-generated skills also be Hermes-/community-loadable is cheap interop. At
minimum, audit the standard and document any divergence. Riskier path: a "Skills Hub" for SASE — probably premature.

### 4.5. RPC tool dispatch for xprompt `python:` steps — **MEDIUM leverage**

Hermes's "Python scripts call tools via RPC, collapsing multi-turn pipelines into single-turn" is the right shape for
xprompts where a deterministic script wants to invoke the same tool surface as the agent. Concretely: let
`workflow_executor.py` Python steps call into a tool RPC instead of re-implementing logic. Reduces drift between
xprompt code and agent code paths.

### 4.6. Trajectory / training-data export — **MEDIUM leverage, conditional**

Only worth it if sase-org plans model training or rigorous offline eval. If yes, copy the shape of
`agent/trajectory.py` + a compression utility. Otherwise this is a YAGNI.

### 4.7. Container / serverless workspace backends — **MEDIUM leverage**

`sase_<N>` is great for local dev but bad for "run my long task on a remote box." A `workspace_provider` plugin for
Docker (and possibly Modal/Daytona) would let lumberjack-style continuous runs execute outside the developer's
machine. This is largely additive and aligns with the existing pluggy provider model.

### 4.8. Unified messaging-gateway abstraction — **MEDIUM leverage, conditional**

If we want more than `sase-telegram`, define the gateway contract once instead of per-plugin. Hermes's gateway is a
useful reference for the verb set: pair, send, receive, interrupt, deliver-scheduled-output. Skip until there's a
second messaging plugin that demands it.

### 4.9. Cron with platform delivery for natural-language scheduled work — **LOW-MEDIUM leverage**

`axe`/lumberjack/chop already cover the cron half. The novel piece is **delivery to a chosen platform channel**
(Slack me, Telegram me) when the scheduled job finishes. Worth designing only after 4.8 lands.

### 4.10. Per-provider rate-limit tracker / shared credential pool — **LOW leverage today**

`nous_rate_guard.py` + `credential_pool.py` are good ideas in a multi-provider world. SASE relies on the host CLI's
quota for now, so this is only relevant if SASE starts making direct API calls — i.e. only if 4.6 happens.

### 4.11. Voice-memo / mobile prompt entry — **LOW leverage**

Cool for personal-assistant Hermes; off-thesis for engineering-tool SASE. Skip.

---

## 5. Anti-Recommendations (things in Hermes that SASE should NOT copy)

- **Self-improving skills with implicit edits.** SASE's reproducibility-via-VCS is a feature; agent-mutated skill
  files would erode it. If we adopt anything skill-curating, gate it behind explicit ChangeSpec + commit.
- **Dialectic user modeling as background process.** Same reason — quietly mutating a user model file conflicts with
  the SASE convention that memory is human-curated and reviewed.
- **Direct provider API adapters in core.** Wrapping coding CLIs is a deliberate choice; replacing it with native
  adapters would force SASE to reimplement Claude Code's tool surface and safety harness.
- **Single shared workspace.** The `sase_<N>` clone model is better for parallel coder agents than Hermes's
  conversation-centric workspace.

---

## 6. Open Questions

1. Does Hermes's FTS5 search index the *agent's* internal turns or only user-visible messages? The README is
   ambiguous; this changes how directly we can lift the design for `sase chats`.
2. How does Honcho's dialectic user modeling resolve conflicts with explicit user instructions? Worth a separate
   read before considering anything similar.
3. Is the agentskills.io standard sufficiently specified for production interop, or is it aspirational? Audit before
   recommendation 4.4 becomes an action item.
4. RL / trajectory tooling: is there appetite within sase-org to actually train? If not, drop 4.6 entirely instead
   of half-building it.
