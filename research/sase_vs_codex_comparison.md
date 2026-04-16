# SASE vs OpenAI Codex: Comparison & Improvement Ideas

_Research date: 2026-04-16_

## Overview

**SASE** (Structured Agentic Software Engineering) is a self-hosted Python toolkit that orchestrates parallel AI coding
agents (Claude Code, Gemini CLI, Codex CLI) through a TUI, background daemon, and structured workflows.

**OpenAI Codex** is a cloud-hosted autonomous coding agent product (web app, desktop app, CLI, IDE extensions) that runs
tasks in isolated containers with GitHub integration. Originally announced May 2025, it has evolved into a multi-surface
product with 2M+ weekly active users as of early 2026.

Both solve the same core problem: **coordinating parallel AI coding agents on real software engineering work**.

---

## Similarities

### 1. Parallel Agent Execution

Both systems treat parallel agent execution as a first-class concern:

| Aspect               | SASE                                                  | Codex                                                |
| -------------------- | ----------------------------------------------------- | ---------------------------------------------------- |
| Isolation            | Git worktree clones (`project_2/`, `project_3/`, ...) | Docker containers (cloud) or git worktrees (desktop) |
| Concurrency tracking | `RUNNING` field in ProjectSpec with workspace claims  | Thread-per-task model with rate-limit-based caps     |
| Conflict avoidance   | Exclusive workspace claiming via PID locks            | Separate containers / worktrees per task             |

### 2. AGENTS.md / Project-Level Agent Instructions

Both use hierarchical markdown files to give agents persistent project context:

| Aspect             | SASE                               | Codex                                         |
| ------------------ | ---------------------------------- | --------------------------------------------- |
| File name          | `AGENTS.md`, `CLAUDE.md`           | `AGENTS.md`, `AGENTS.override.md`             |
| Scope              | Project root + memory tiers        | Git root, walked down to CWD                  |
| Override mechanism | Tiered memory (short/dynamic/long) | `AGENTS.override.md` replaces parent guidance |
| Size limits        | No hard cap                        | 32-64 KiB configurable cap                    |

### 3. Plan-Then-Execute Workflow

Both support a planning phase before implementation:

| Aspect        | SASE                                            | Codex                                                |
| ------------- | ----------------------------------------------- | ---------------------------------------------------- |
| Trigger       | `%plan` directive in xprompts                   | `/plan` command or Shift+Tab                         |
| Approval      | Modal in ACE TUI (approve/reject/edit/feedback) | Inline in chat thread                                |
| Persistence   | Saved to `plans/{YYYYMM}/` with frontmatter     | PLANS.md "living documents" updated during execution |
| Epic creation | Plan -> epic bead -> phase beads                | No built-in epic concept                             |

### 4. Automated Code Review

Both have built-in mechanisms for AI-powered code review:

| Aspect     | SASE                                                      | Codex                                        |
| ---------- | --------------------------------------------------------- | -------------------------------------------- |
| System     | Mentor profiles with structured JSON output               | `@codex review` on PRs                       |
| Triggering | Auto-triggered by file globs, diff regexes                | Manual (`@codex review`) or auto on every PR |
| Review UI  | Mentor Review modal (navigate, accept/reject per comment) | Standard GitHub PR review comments           |
| Apply flow | Accept comments -> launch agent to apply changes          | Follow-up in same thread                     |

### 5. Background Automation

Both can run recurring automated tasks:

| Aspect     | SASE                                                | Codex                                       |
| ---------- | --------------------------------------------------- | ------------------------------------------- |
| System     | Axe daemon with lumberjacks and chops               | Thread automations + standalone automations |
| Scheduling | Fixed intervals per lumberjack (2s-1hr)             | Recurring wake-up calls with thread context |
| Scope      | Hooks, mentors, workflows, comment polling, cleanup | Issue triage, alert monitoring, CI/CD tasks |

### 6. Skills / Reusable Prompt Templates

Both support packaged, reusable instructions:

| Aspect      | SASE                                                                   | Codex                                                              |
| ----------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------ |
| System      | XPrompts (`.md` or `.yml` files)                                       | Skills (`SKILL.md` with frontmatter)                               |
| Discovery   | 8-level priority search (CWD -> home -> config -> plugins -> built-in) | Skills picker sidebar, explicit `$skill-name` or implicit matching |
| Composition | `#xprompt(args)` references, Jinja2 templating, workflow steps         | Not composable in the same way                                     |
| Parameters  | Typed inputs (`word`, `int`, `path`, etc.)                             | Frontmatter metadata for matching                                  |

### 7. Query / Filtering

Both provide ways to filter and find work items:

| Aspect     | SASE                                                          | Codex                                |
| ---------- | ------------------------------------------------------------- | ------------------------------------ |
| System     | Boolean query language with field filters, shorthands         | Project/thread organization, search  |
| Complexity | Full boolean expressions, property filters, status shorthands | Simpler organization-based filtering |

---

## Key Differences

### 1. Cloud vs Local Execution

**Codex** runs tasks in cloud containers with managed infrastructure. Containers are pre-built with dozens of language
runtimes, have a two-phase model (internet-enabled setup, then sandboxed execution), and cache state for up to 12 hours.

**SASE** runs everything locally. Agents execute in cloned workspace directories on the user's machine. There is no
sandboxing, no managed container infrastructure, and no network isolation.

**Implication**: Codex can offer stronger isolation and reproducibility. SASE offers more flexibility and no dependency
on cloud infrastructure, but loses security guarantees.

### 2. LLM Provider Lock-in

**Codex** is tightly coupled to OpenAI's models (GPT-5.3-Codex, GPT-5.4, etc.).

**SASE** is provider-agnostic with pluggable LLM backends (Claude, Gemini, Codex CLI) and configurable model tier
mapping. This is a significant architectural advantage.

### 3. VCS Provider Flexibility

**Codex** is GitHub-only for cloud features (PR creation, code review, issue integration). No native support for GitLab,
Bitbucket, or Azure DevOps.

**SASE** has a pluggable VCS and workspace provider system supporting bare git, GitHub, and Mercurial via plugins. This
is another architectural advantage.

### 4. Desktop App & Multi-Surface Experience

**Codex** has a polished desktop app (macOS/Windows) with:

- Built-in diff viewer with inline comments and hunk-level staging
- Integrated terminal, in-app browser for previewing local dev servers
- Voice dictation (Ctrl+M)
- Computer use (operating macOS apps via vision)
- Pop-out windows for detaching threads
- IDE sync with VS Code/Cursor/Windsurf

**SASE** has ACE, a terminal-based TUI with vim-style keybindings. Powerful for terminal users but no graphical diff
viewer, no browser preview, no voice input.

### 5. Third-Party Integrations

**Codex** integrates with: GitHub (deep), Slack (`@Codex` in channels), Linear, Jira, Figma, MCP protocol, Gmail, Google
Drive, and IDE extensions.

**SASE** integrates with: GitHub (via plugin), Telegram (via plugin), and Chezmoi. The integration surface is narrower
but extensible via the plugin system.

### 6. Issue Tracking

**SASE** has a built-in issue tracker (Beads) with plans/phases, dependencies, multi-workspace merged views, and
git-native storage (SQLite + JSONL). This is a feature Codex does not have -- Codex relies on external issue trackers
(GitHub Issues, Linear, Jira).

### 7. ChangeSpec Lifecycle

**SASE** tracks the full lifecycle of a code change from WIP through Submitted/Archived with structured metadata (parent
chains, hooks, comments, mentors, timestamps). Codex has no equivalent -- each task is relatively independent with PR
creation as the main output.

### 8. Observability

**SASE** has Prometheus-based telemetry with 33 metrics across 7 subsystems, a live TUI dashboard, and a Docker Compose
monitoring stack.

**Codex** has real-time task logs and progress indicators but no comparable self-hosted observability system.

### 9. Pricing Model

**Codex** is a paid SaaS product ($8-$200/month) with rate limits on concurrent agents.

**SASE** is free/self-hosted -- you pay only for the underlying LLM API costs.

---

## Recommendations: Improving SASE Based on Codex Ideas

### High Priority

#### 1. Inline Diff Review in ACE

**Codex feature**: Built-in diff viewer with inline commenting, per-hunk staging/reverting.

**Current SASE**: The `d` key shows diffs, but there's no inline commenting or hunk-level operations within ACE.

**Recommendation**: Add a diff review panel to ACE that shows file diffs with the ability to:

- Add inline comments that feed back into the agent's next prompt
- Accept/reject individual hunks (not just whole files)
- Stage partial changes

This would make the review-iterate loop much tighter without leaving the TUI.

#### 2. PLANS.md-Style Living Documents

**Codex feature**: PLANS.md files are "living design documents" that agents continuously update as work progresses. They
include timestamped progress checkboxes, a decision log, surprises/discoveries, and recovery instructions.

**Current SASE**: Plans are saved as static artifacts in `plans/{YYYYMM}/`. They have a `status: done` field but aren't
updated during execution.

**Recommendation**: Evolve the plan system so agents update their plan file as they work:

- Add a `## Progress` section with timestamped checkboxes
- Add a `## Decision Log` for recording choices made during implementation
- Add a `## Surprises` section for unexpected findings
- Display live plan progress in the ACE Agents tab
- Enable plan resumption: if an agent fails, a new agent can pick up from the plan's last checkpoint

This makes plans useful for long-running tasks and multi-session work.

#### 3. Slack / Chat Integration for Task Creation

**Codex feature**: Tag `@Codex` in a Slack channel to create a cloud task. It gathers conversation context and creates
the task automatically.

**Current SASE**: Telegram plugin exists but is limited.

**Recommendation**: Build a richer Slack or Discord integration where:

- Users can create tasks by mentioning the bot with a prompt
- The bot selects the appropriate project and workspace
- Task status updates are posted back to the thread
- PR links are shared when work completes

This enables non-terminal users (PMs, designers) to trigger agent work.

#### 4. Container-Based Sandboxing (Optional)

**Codex feature**: Two-phase container model with internet-enabled setup and sandboxed execution.

**Current SASE**: No sandboxing. Agents run with full access to the local filesystem.

**Recommendation**: Add an optional container mode:

- Define a `Dockerfile` or use a standard base image per project
- Run agent workspaces inside containers with controlled network access
- Two-phase model: `setup` phase (internet on, install deps) -> `agent` phase (internet off)
- Cache container state to avoid repeated setup

This doesn't need to be the default, but would be valuable for:

- Running untrusted agent outputs safely
- Reproducible environments across team members
- CI/CD integration

### Medium Priority

#### 5. GitHub Issue/PR Trigger Integration

**Codex feature**: Mention `@codex` on a GitHub issue or PR to spin up a task. Auto-review on every new PR.

**Current SASE**: No way to trigger agent work from GitHub.

**Recommendation**: Build a GitHub App or webhook handler that:

- Watches for `@sase` mentions on issues/PRs
- Automatically creates a bead and launches an agent
- Posts results back as PR comments
- Optionally auto-triggers mentor reviews on new PRs

This closes the loop between GitHub and sase's local execution.

#### 6. IDE Extension for Context Sync

**Codex feature**: VS Code/Cursor/Windsurf extensions that sync editor context (open files, cursor position, selections)
to the desktop app.

**Current SASE**: No IDE integration beyond terminal.

**Recommendation**: Build a lightweight VS Code extension that:

- Shows agent status in the sidebar
- Sends current file/selection context to ACE prompts
- Displays agent-generated diffs inline
- Provides a prompt input widget

This would make sase accessible to developers who prefer GUI editors.

#### 7. Agent Wait Dependencies with Richer Semantics

**Codex feature**: Thread automations that preserve context across recurring tasks.

**Current SASE**: `%wait` directive and `wait_checks` lumberjack for agent dependencies.

**Recommendation**: Extend the wait system with:

- **Conditional waits**: "wait for agent X only if it succeeds" vs "wait regardless of outcome"
- **Data passing**: Agent X's output becomes Agent Y's input (beyond just "done" signal)
- **Fan-out/fan-in**: Launch N parallel agents, then merge results in a final agent

The workflow system already supports parallel steps, but making this more ergonomic for ad-hoc agent-to-agent
dependencies would be valuable.

#### 8. Session Compaction / Context Management

**Codex feature**: Automatic compaction that summarizes context to stay within the window for multi-hour tasks.

**Current SASE**: No built-in context management for long-running agents.

**Recommendation**: Add a compaction-aware workflow mode:

- Monitor agent context usage during long tasks
- Automatically summarize prior work and inject it as a "checkpoint" prompt
- Enable multi-session agents that can resume from compacted state

This is particularly important for epic-level work that spans multiple agent sessions.

### Lower Priority (But Interesting)

#### 9. Voice Input for Prompts

**Codex feature**: Hold Ctrl+M to dictate prompts via voice.

**Recommendation**: Integrate with a local speech-to-text model (Whisper) for voice prompt input in ACE. Low priority
but a nice ergonomic improvement for hands-busy situations.

#### 10. In-TUI Browser Preview

**Codex feature**: In-app browser for previewing local dev servers.

**Recommendation**: For frontend work, allow ACE to open a browser preview (even if it's just launching `xdg-open` /
`open` to the dev server URL) and displaying a screenshot via terminal image protocols (sixel, kitty). Very ambitious
but would close the frontend development loop.

#### 11. MCP (Model Context Protocol) Support

**Codex feature**: Extensible integration framework for connecting to external tools, databases, CI/CD.

**Recommendation**: Add MCP server/client support to sase's plugin system, enabling:

- Agents to query databases, CI systems, monitoring tools during execution
- Third-party tool providers to build sase integrations
- Standardized context injection beyond xprompts

---

## Summary Matrix

| Capability            | SASE                                      | Codex                                    | Winner                    |
| --------------------- | ----------------------------------------- | ---------------------------------------- | ------------------------- |
| Parallel agents       | Local worktrees + workspace claiming      | Cloud containers + worktrees             | Tie (different tradeoffs) |
| LLM flexibility       | Multi-provider (Claude, Gemini, Codex)    | OpenAI-only                              | **SASE**                  |
| VCS flexibility       | Git, GitHub, Mercurial via plugins        | GitHub-only                              | **SASE**                  |
| Issue tracking        | Built-in (Beads)                          | External only                            | **SASE**                  |
| Change lifecycle      | Full ChangeSpec lifecycle tracking        | PR as primary output                     | **SASE**                  |
| Observability         | Prometheus + 33 metrics + dashboard       | Task logs only                           | **SASE**                  |
| Plan system           | Static plan artifacts + epic workflow     | Living PLANS.md updated during execution | **Codex**                 |
| Diff review           | Basic diff view                           | Inline comments, hunk staging            | **Codex**                 |
| Sandboxing            | None                                      | Container-based with network isolation   | **Codex**                 |
| Desktop experience    | Terminal TUI                              | Polished GUI app                         | **Codex**                 |
| Integrations          | GitHub, Telegram, Chezmoi                 | GitHub, Slack, Linear, Jira, Figma, IDEs | **Codex**                 |
| Third-party triggers  | None                                      | GitHub @mention, Slack @mention          | **Codex**                 |
| Prompt templates      | XPrompts (rich, composable, typed)        | Skills (simpler, metadata-matched)       | **SASE**                  |
| Workflow engine       | YAML multi-step with parallel/conditional | Single-task (no multi-step pipelines)    | **SASE**                  |
| Background automation | Axe daemon with configurable lumberjacks  | Thread/standalone automations            | **SASE**                  |
| Query language        | Full boolean expression language          | Basic search/filter                      | **SASE**                  |
| Cost                  | Free (pay LLM costs)                      | $8-$200/month + rate limits              | **SASE**                  |
| Setup complexity      | Self-hosted, requires configuration       | Managed SaaS                             | **Codex**                 |
| Code review           | Mentor profiles with structured output    | PR review via GitHub comments            | Tie                       |

### Bottom Line

SASE is stronger on **infrastructure flexibility** (multi-LLM, multi-VCS, self-hosted), **structured workflows**
(xprompts, YAML pipelines, Axe daemon), and **work tracking** (ChangeSpecs, Beads, telemetry).

Codex is stronger on **user experience** (desktop app, IDE sync, voice), **integrations** (Slack, Linear, Figma),
**sandboxing** (containers), and **accessibility** (managed SaaS, no setup).

The highest-impact improvements for SASE would be:

1. **Inline diff review** in ACE (tighter review loop)
2. **Living plans** that update during execution (better long-task support)
3. **Chat/webhook triggers** (GitHub @mention, Slack integration)
4. **Optional container sandboxing** (security + reproducibility)
