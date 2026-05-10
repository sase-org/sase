# Research: SASE vs Nous Research Hermes Agent

**Source under review:** [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent)
("The agent that grows with you" — MIT-licensed, Python-dominant agent framework.)

**Methodology:** README + source/docs inventory from `NousResearch/hermes-agent` at
`456955c2e4e49e4b48f4b1505f0a45fe7802a83f` (2026-04-29), cross-referenced against the SASE codebase
(`src/sase/`, `memory/`, `xprompts/`). I did not run Hermes locally; claims about Hermes internals are derived from its
public docs and filenames. Where Hermes detail is thin, I say so rather than guess.

---

## 1. Positioning

|                  | SASE                                                      | Hermes Agent                                                          |
| ---------------- | --------------------------------------------------------- | --------------------------------------------------------------------- |
| Primary user     | Engineer doing structured CL/PR work in a repo            | General-purpose personal assistant + coder                            |
| Primary surface  | TUI (`ace`) over local repo + ephemeral `sase_<N>` clones | CLI/TUI, gateway, web dashboard, ACP adapter, mobile/chat surfaces     |
| LLM strategy     | Wraps coding CLIs (Claude Code, Gemini CLI, Codex)        | Direct APIs + OpenAI-compatible transports + provider/tool gateway     |
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
  `gemini_native_adapter.py`, `codex_responses_adapter.py`) and transport abstractions under `agent/transports/`. It
  owns prompt construction (`prompt_builder.py`), context shaping (`context_engine.py`, `context_compressor.py`), error
  classification (`error_classifier.py`), prompt caching (`prompt_caching.py`), and rate-limit accounting
  (`nous_rate_guard.py`, `rate_limit_tracker.py`, `account_usage.py`).

The key implication: **SASE inherits the host CLI's tool set and safety harness** and pays for it with a
process-per-turn boundary. **Hermes owns the loop** and therefore owns context compression, rate budgeting, and
trajectory capture as first-class concerns. Different tradeoffs — neither dominates.

### 2b. Skills

- **SASE** generates skills *into runtime-specific paths* (e.g. `~/.claude/skills/`, `~/.gemini/skills/`,
  provider-specific directories for plugins). They are authored in `xprompts/skills/` and expanded by the
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
  - explicit `/compress` for in-context window management,
  - a SQLite `state.db` with WAL mode, `sessions`, `messages`, `messages_fts`, session lineage, platform/source tags,
    token/cost fields, and migrations.

Hermes's memory is **agent-initiated and adaptive** (search past sessions, infer the user); SASE's is
**author-curated and deterministic** (a human writes the memory file, keywords decide when it loads). The codified
context paper already noted this gap; Hermes is a concrete instance of the agent-initiated retrieval design.

### 2d. Multi-platform reach

- **SASE** has `src/sase/notifications/` plus external messaging plugins (`sase-telegram`, `retired chat plugin`, and related
  sibling work). The shape is still notification/plugin-oriented rather than one general gateway runtime.
- **Hermes** ships a **unified gateway process** spanning Telegram, Discord, Slack, WhatsApp, Signal, SMS, Email,
  Home Assistant, Mattermost, Matrix, DingTalk, Feishu/Lark, WeCom/Weixin, BlueBubbles/iMessage, QQ/Yuanbao,
  webhooks, and an OpenAI-compatible API server. It also handles voice messages, attachments, streaming updates,
  per-chat sessions, busy-input modes (interrupt/queue/steer), pairing, and cron delivery.

If sase-org wants assistant-style reachability beyond the laptop, Hermes's gateway is a much more developed reference
than what's in the tree today.

### 2e. Deployment / execution sandboxing

- **SASE** runs in **ephemeral `sase_<N>` clones** of the host repo, each with its own venv. Workspace claims are
  atomic and transferable across spawn-on-retry boundaries.
- **Hermes** documents local, Docker, SSH, Daytona, Singularity, Modal, and Vercel Sandbox terminal backends. Container
  backends support CPU/memory/disk sizing, persistent filesystems, and hardening such as read-only roots, dropped Linux
  capabilities, no privilege escalation, and PID limits.

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

### 2k. Tool ecosystem, MCP, and ACP

- **SASE** has xprompts, generated skills, provider plugins (`llm_provider`, `vcs_provider`, `workspace_provider`), and
  workflow hooks. These are strong local extension points, but they are SASE-specific surfaces.
- **Hermes** has a central tool registry (`tools/registry.py`, `model_tools.py`, `toolsets.py`), platform presets
  (`hermes-cli`, `hermes-telegram`, `hermes-acp`, dynamic `mcp-<server>`), per-tool availability checks, and pre/post
  tool-call plugin hooks. It also supports MCP stdio/HTTP servers with per-server include/exclude filters and utility
  wrappers for resources/prompts. Separately, `acp_adapter/` exposes Hermes over the Agent Client Protocol for editor
  clients, with session/fork/list/cancel methods, editor-cwd binding, approval bridging, and tool-result rendering.

The missed point is not "SASE needs Hermes's tool registry." SASE intentionally delegates most tools to host coding
CLIs. The useful gap is a **control-plane protocol**: expose SASE operations (agent status, ChangeSpec lookup, bead
work, chat search, notifications, kill/retry/resume) via stable MCP/ACP-style surfaces so editors and agents can call
SASE without scraping CLI text or TUI state.

### 2l. UI/session architecture

- **SASE's `ace` TUI** is a repo operations console: ChangeSpecs, agent lists, hooks, mentors, notifications, file
  panels, and dashboard views over filesystem artifacts.
- **Hermes's Ink TUI** is a chat client over a Python sidecar (`tui_gateway/`) using newline-delimited JSON-RPC. It
  handles transcript rendering, queues, slash commands, approvals, clarify/sudo/secret prompts, completion, and
  structured gateway events. Hermes also has a React/FastAPI web dashboard for config, API keys, and session
  monitoring.

This is a product-shape difference. SASE should not replace `ace` with chat-first UX, but Hermes's protocol split is a
good reference if SASE wants non-TUI clients for the same runtime state.

### 2m. Security and trust boundaries

- **SASE** inherits most command safety from the wrapped coding CLI and adds SASE-specific HITL surfaces such as plan
  approvals, workflow approvals, mentor hooks, and notification handling.
- **Hermes** owns the terminal tool, so it also owns dangerous-command approval. Its docs describe manual/smart/off
  modes, fail-closed timeouts, session/permanent allowlists, messaging approval callbacks, gateway user allowlists, DM
  pairing codes, MCP environment filtering, path traversal hardening for cron storage, and prompt-injection scanning for
  context files (`AGENTS.md`, `CLAUDE.md`, `.hermes.md`, `.cursorrules`).

The security lesson for SASE is conditional: if SASE builds more direct execution surfaces (remote workspaces,
webhooks, gateway commands, MCP tools), it needs its own explicit authorization and approval model instead of assuming
the underlying coding CLI remains the only authority.

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

### 4.1. Full-text + LLM-summarized search over past agent chats/artifacts — **HIGH leverage**

Hermes's SQLite `state.db` + FTS5 + summarization over past sessions is a clean answer to "what did agent X say last
week about Y?" SASE has `sase chats` and rich artifact directories, but no durable recall/index layer. Recommendation:
index `sase chats` artifacts, agent metadata, ChangeSpec names, prompts, tool outputs, and done/failure summaries with
SQLite FTS5 (or tantivy via the Rust backend). Expose `sase chats search <query>` plus an xprompt-callable retrieval
skill so agents can self-recall. This composes naturally with the codified-context paper's "agent-initiated retrieval"
idea already on file in `codified_context_paper_insights.md`.

### 4.2. Agent-initiated dynamic-memory retrieval (in addition to pre-session keyword match) — **HIGH leverage**

Already flagged in our codified-context research note. Hermes is a concrete existence proof. Add a tool/skill for
`find_relevant_memory(task)` that the agent can call mid-loop, in addition to the existing pre-session injection.
Keeps determinism for the common case, adds adaptivity for the long tail.

### 4.3. `/compress` and budgeted context management — **MEDIUM-HIGH leverage**

SASE relies on the host CLI's auto-compaction. A SASE-owned `/compress` (or pre-turn budgeter) that knows about
ChangeSpec / mentor / plan structure could be a lot smarter than generic compaction — e.g. preserve the plan, drop
old tool output. Especially relevant on long-running coder agents.

### 4.4. MCP/ACP-style control plane for SASE operations — **MEDIUM-HIGH leverage**

Hermes's MCP and ACP support is the best missed gap in the earlier pass. SASE does not need to expose arbitrary model
tools, but it would benefit from a stable machine-facing control plane for operations it already owns: list/status
running agents, inspect ChangeSpecs, search chats, kill/retry/resume agents, create/update beads, launch `bead work`,
read notifications, and submit plan/question responses. Start with a local MCP server because it is broadly useful to
agents; consider ACP only if editor clients want a first-class SASE agent surface.

### 4.5. Generic webhook/event ingress for repo automation — **MEDIUM leverage**

Hermes can accept signed webhooks, template payloads into prompts, attach skills, and deliver results to a target
platform or skip the LLM entirely for direct delivery. SASE's CL/PR model makes this especially useful: GitHub/GitLab
events could create beads, launch mentors, file ChangeSpec comments, or trigger hook repair agents. Recommendation:
define a small signed event-ingress daemon/plugin contract before building one-off inbound adapters.

### 4.6. Adopt the agentskills.io skills standard for portability — **MEDIUM leverage**

If the standard is reasonable, having SASE-generated skills also be Hermes-/community-loadable is cheap interop. At
minimum, audit the standard and document any divergence. Riskier path: a "Skills Hub" for SASE — probably premature.

### 4.7. RPC tool dispatch for xprompt `python:` steps — **MEDIUM leverage**

Hermes's "Python scripts call tools via RPC, collapsing multi-turn pipelines into single-turn" is the right shape for
xprompts where a deterministic script wants to invoke the same tool surface as the agent. Concretely: let
`workflow_executor.py` Python steps call into a tool RPC instead of re-implementing logic. Reduces drift between
xprompt code and agent code paths.

### 4.8. Explicit authorization/approval policy for new execution surfaces — **MEDIUM leverage, conditional**

Hermes has dangerous-command approval, gateway allowlists, DM pairing, context-file scanning, and MCP env filtering
because it owns terminal execution and remote access. SASE can continue leaning on host coding CLIs for ordinary agent
tool safety, but the moment SASE adds webhooks, remote workspaces, MCP tools, or messaging commands that mutate repo
state, it needs a SASE-level approval matrix. Good first scope: signed webhook routes, allowed ChangeSpec/bead actions,
per-channel permissions, fail-closed timeouts, and audit logs for external approvals.

### 4.9. Trajectory / training-data export — **MEDIUM leverage, conditional**

Only worth it if sase-org plans model training or rigorous offline eval. If yes, copy the shape of
`agent/trajectory.py` + a compression utility, but include SASE-specific labels such as ChangeSpec status, hook
failures, mentor findings, test outcomes, and whether the CL landed. Otherwise this is a YAGNI.

### 4.10. Container / serverless workspace backends — **MEDIUM leverage**

`sase_<N>` is great for local dev but bad for "run my long task on a remote box." A `workspace_provider` plugin for
Docker (and possibly Modal/Daytona/Vercel Sandbox) would let lumberjack-style continuous runs execute outside the
developer's machine. This is largely additive and aligns with the existing pluggy provider model. Preserve SASE's
workspace-claim semantics; do not collapse remote runs into one shared workspace.

### 4.11. Unified messaging-gateway abstraction — **MEDIUM leverage, conditional**

If we want more than `sase-telegram`, define the gateway contract once instead of per-plugin. Hermes's gateway is a
useful reference for the verb set: pair, send, receive, interrupt, deliver-scheduled-output. Skip until there's a
second messaging plugin that demands it.

### 4.12. Cron with platform delivery for natural-language scheduled work — **LOW-MEDIUM leverage**

`axe`/lumberjack/chop already cover the cron half. The novel piece is **delivery to a chosen platform channel**
(Slack me, Telegram me) when the scheduled job finishes. Worth designing only after 4.11 lands.

### 4.13. Progressive subdirectory context discovery — **LOW-MEDIUM leverage**

Hermes progressively discovers nested `AGENTS.md`/`CLAUDE.md`/`.cursorrules` when tools touch subdirectories, avoiding
startup prompt bloat. SASE mostly delegates this to the host CLI, but generated skills/xprompts could still benefit
from a uniform helper that finds relevant nested project instructions before launching agents in large monorepos.

### 4.14. Per-provider rate-limit tracker / shared credential pool — **LOW leverage today**

`nous_rate_guard.py` + `credential_pool.py` are good ideas in a multi-provider world. SASE relies on the host CLI's
quota for now, so this is only relevant if SASE starts making direct API calls in core or in a future sdd/research/eval
pipeline.

### 4.15. Voice-memo / mobile prompt entry — **LOW leverage**

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
- **Broad tool registry in SASE core.** Hermes needs a broad registry because it owns the model loop. SASE should expose
  SASE-native operations as tools/protocol methods, not rebuild generic web/browser/file/terminal tools already owned by
  the host coding CLIs.
- **Gateway sprawl before a contract.** Hermes supports many platforms. SASE should not copy the adapter count; it
  should first define the small set of semantics it needs for engineering workflows.

---

## 6. Source Pointers for the Follow-up Pass

- Hermes repo snapshot: `NousResearch/hermes-agent@456955c2e4e49e4b48f4b1505f0a45fe7802a83f`.
- README: high-level positioning, gateway, skills, cron, terminal backends, RL claims.
- `website/docs/developer-guide/session-storage.md`: SQLite state DB, FTS5, session lineage, write contention.
- `website/docs/user-guide/features/mcp.md`: stdio/HTTP MCP server config, tool filtering, resource/prompt utilities.
- `website/docs/developer-guide/acp-internals.md`: ACP adapter lifecycle, sessions, approval bridge, cwd binding.
- `website/docs/user-guide/features/tools.md` and `developer-guide/tools-runtime.md`: tool registry, toolsets, terminal
  backends, dangerous-command approval.
- `website/docs/user-guide/messaging/index.md` and `messaging/webhooks.md`: gateway platforms, auth, busy-input modes,
  delivery targets, signed webhook routes.
- `website/docs/user-guide/security.md`: approval modes, gateway authorization, pairing, context-file safety scanning.
- `ui-tui/README.md` and `web/README.md`: Ink TUI sidecar/protocol and React/FastAPI web dashboard.

---

## 7. Open Questions

1. How does Honcho's dialectic user modeling resolve conflicts with explicit user instructions? Worth a separate
   read before considering anything similar.
2. Is the agentskills.io standard sufficiently specified for production interop, or is it aspirational? Audit before
   recommendation 4.6 becomes an action item.
3. RL / trajectory tooling: is there appetite within sase-org to actually train? If not, drop 4.9 entirely instead
   of half-building it.
4. Should SASE's first machine-facing protocol be MCP, ACP, or a plain JSON CLI? MCP fits agent tools, ACP fits editor
   agents, and JSON CLI is cheapest; the right answer depends on who the first consumer is.
5. If SASE adds webhook-triggered work, which operations are safe to run unattended and which require a human approval
   boundary?
