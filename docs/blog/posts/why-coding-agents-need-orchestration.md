---
title: "[00] The Missing Operating Layer for Coding Agents"
date: 2026-05-08
draft: true
description: >-
  SASE's first principles: XPrompts, SDD, Beads, ACE, AXE, plugins, and the durable
  operating layer around coding-agent CLIs.
categories:
  - Agentic Software Engineering
slug: why-coding-agents-need-orchestration
links:
  - Getting Started: getting_started.md
  - XPrompts: xprompt.md
  - Spec-Driven Development: sdd.md
  - ACE TUI: ace.md
  - View on GitHub: https://github.com/sase-org/sase
---

# [00] The Missing Operating Layer for Coding Agents

> Terminology note (July 2026): the “companion repos” named in this historical post are
> now called **sidecar repos**.

SASE is not a better model. SASE is the layer I wanted after realizing that the hard
part of running coding agents is not always "can the model write the patch?" Sometimes
the hard part is "where did the patch go?", "what was it trying to do?", "who is waiting
on it?", "why did it start six follow-up agents while I was brushing my teeth?", and
"can I please see the diff before the robot commits crimes against `just check`?"

That layer needs reusable prompts, durable plans, dependency-aware work items, review
records, background automation, notifications, and a control surface that lets humans
steer without becoming a full-time air-traffic controller.

Borrowing the name from the research paper discussed later, SASE calls that layer
**Structured Agentic Software Engineering**. This post is the map of the fundamentals:
XPrompts, SDD, Beads, ACE, AXE, plugins, and why SASE wraps coding-agent CLIs instead of
raw model APIs.

<!-- more -->

If you want to install first and read philosophy later, jump to
[Getting Started](../../getting_started.md). That page is the practical quickstart. This
one explains what the pieces are and why they exist.

One notation note before we start:

> **Friction note:** Blocks like this call out SASE pain points, rough edges, or future
> improvements. SASE is useful today, but it is not a marble statue. It is a useful
> toolbox with several labels still written in Sharpie.

## What SASE Is

SASE is a local orchestration layer above coding-agent CLIs such as Codex, Claude Code,
Antigravity CLI (`agy`), Qwen Code, OpenCode, and Meta's Muse Code. It gives those
agents a common workflow: launch in isolated workspaces, expand reusable prompts, save
prompt and response artifacts, track PR-sized work as Patches, coordinate dependency
graphs with Beads, and supervise background work through AXE.

The repo split is intentionally boring:

| Repo                                                         | What it does                                                                                                                                                  |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`sase`](https://github.com/sase-org/sase)                   | The Python host package: CLI, ACE TUI, AXE daemon, XPrompt expansion, SDD, Beads integration, config, and built-in providers.                                 |
| [`sase-core`](https://github.com/sase-org/sase-core)         | Shared Rust core for deterministic data operations and cross-frontend APIs. It also houses the mobile gateway and XPrompt LSP crates.                         |
| [`sase-github`](https://github.com/sase-org/sase-github)     | GitHub VCS/workspace provider plugin. It uses `gh` for PR operations and ships GitHub-focused xprompts such as `#gh`, `#new_pr_desc`, and `#prdd`.            |
| [`sase-telegram`](https://github.com/sase-org/sase-telegram) | Telegram integration package. It runs as inbound/outbound AXE chops so you can receive notifications, answer approvals, and launch or steer agents from chat. |
| [`sase-nvim`](https://github.com/sase-org/sase-nvim)         | Neovim integration for SASE syntax, xprompt completion, hover, diagnostics, and the XPrompt LSP.                                                              |

The short version: `sase` owns the cockpit, `sase-core` owns shared engine-room logic,
and the plugins add providers or frontends without forcing the core workflow to become
GitHub-only, Telegram-only, or Neovim-only.

<!--
ARCHITECTURE DIAGRAM BRIEF 1 - place here after the repo table.
Title: "SASE as the operating layer"
Shape: horizontal layered architecture diagram.
Top layer: "Human surfaces" with ACE TUI, Telegram, Neovim/XPrompt LSP, future Web UI, future Mobile app.
Middle layer: "SASE Python host" with XPrompts, agent launcher, AXE daemon, Patches, SDD, Beads, VCS/workspace plugins.
Right side attached to middle: "Provider CLIs" with Codex, Claude Code, Antigravity (agy), Qwen, OpenCode, and Muse Code. Draw them as replaceable
execution engines rather than the center of the system.
Show Muse Code as explicitly selected by provider/model directive, not auto-detected.
Bottom layer: "sase-core Rust" with state/indexing, mobile gateway, xprompt LSP core, deterministic file/query helpers.
Persistent storage under everything: ~/.sase plus the resolved SDD store.
Make the visual point that SASE is not another model wrapper; it is the state/control plane around several CLIs.
-->

## Install The Smallest Useful Thing

SASE needs Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and at least one
authenticated coding-agent CLI. Install the core package:

```bash
uv tool install sase
sase version
sase doctor
```

Add GitHub support when you want PR/workspace integration:

```bash
uv tool install sase --with sase-github
gh auth login
sase doctor -C plugins.github
```

Add Telegram support when you want chat-driven notifications and remote control:

```bash
uv tool install sase --with sase-telegram
sase axe chop doctor
```

Install both plugins together if that is your normal setup:

```bash
uv tool install sase --with sase-github --with sase-telegram
```

If you are replacing an existing `uv tool` install, add `--force` to the same command.
The quickstart has the fuller walkthrough: [Getting Started](../../getting_started.md).

> **Friction note:** Plugin installation is improving, but it is still a little too easy
> to install `sase` correctly and forget that `sase-github` also needs an authenticated
> `gh` CLI, while `sase-telegram` needs Telegram bot secrets and AXE chops configured.
> `sase doctor` and `sase axe chop doctor` are the first places to look when something
> feels haunted. Technically it is not haunted. Usually.

## SASE Wraps Agents, Not Models

SASE deliberately wraps CLI agents rather than raw model APIs. A SASE provider plugin
constructs commands for existing agent runtimes: Codex CLI, Claude Code, Antigravity CLI
(`agy`), Qwen Code, OpenCode, Muse Code, or another provider that implements the same
boundary. The [LLM provider docs](../../llms.md) describe that layer in detail.

This buys a lot:

- You inherit each CLI's auth, sandboxing, approval model, local tool behavior, and
  provider-specific improvements.
- You can swap providers per prompt with `%model` instead of rewriting the orchestration
  layer.
- SASE can focus on work state: prompts, workspaces, plans, Beads, Patches, and UI.
- Users can keep using the agent CLI they already trust, which is a boring advantage and
  therefore an excellent one.

The trade-off is real: SASE has less direct control over token accounting, tool
protocols, streaming details, and model semantics than it would have with raw APIs. It
also inherits provider pricing and policy shifts. For example,
[Anthropic says](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
that starting **June 15, 2026**, Claude Agent SDK and `claude -p` usage moves to a
separate monthly Agent SDK credit bucket. Past that credit, usage can flow to standard
API-rate usage credits if enabled; otherwise those requests stop until the credit
refreshes.

That is not a reason to avoid provider CLIs. It is a reason to make the orchestration
layer provider-aware, explicit, and replaceable.

## The Codex App Is The Real Competitor

I consider the [Codex app](https://developers.openai.com/codex/app) SASE's closest
competitor. Not because it has the same architecture, but because it targets the same
daily shape of work: many agent threads, local worktrees, review surfaces, automations,
Git actions, IDE/app integration, and a human trying to keep the whole circus pointed at
useful software.

OpenAI's docs describe Codex app features such as
[automations and background worktrees](https://developers.openai.com/codex/app/features)
and pricing tiers that include Codex on the web, CLI, IDE extension, and app surfaces
([pricing](https://developers.openai.com/codex/pricing)). That is exactly the kind of
product surface SASE has to take seriously.

The difference is emphasis. Codex app is a polished product around OpenAI's agent stack.
SASE is an open, local, provider-pluggable operating layer for people who want durable
work records, Git-portable state, custom prompt systems, AXE automation, and
cross-provider routing. That makes SASE less shiny in places and more hackable in
others. I have made peace with this, mostly.

## The Fundamental Loop

Here is the SASE loop:

1. You type a prompt, usually with one or more XPrompt references.
2. SASE expands the prompt, strips directives, resolves workspace references, and
   launches one or more agents.
3. Each agent runs in a managed workspace and writes prompt, transcript, status, and
   artifacts.
4. If the work needs planning, SASE records the prompt archive, plan, and bead graph as
   durable project state.
5. ACE shows the live state. AXE watches the background state. Plugins translate VCS and
   notification operations.

The docs that matter most at first are [XPrompts](../../xprompt.md),
[SDD](../../sdd.md), [Beads](../../beads.md), [ACE](../../ace.md), [AXE](../../axe.md),
[VCS providers](../../vcs.md), and [plugins](../../plugins.md).

<!--
FUNNY DIAGRAM BRIEF 1 - place here after "The Fundamental Loop".
Title: "The prompt burrito"
Shape: silly cutaway diagram of a burrito labeled in layers.
Center: "tiny user prompt: fix the thing".
Layers outward: config xprompt, markdown xprompt, multi-agent segments, directives, workspace ref, SDD/Beads metadata.
Final arrow: "several agents with actual names instead of mystery chat tabs".
Visual joke: a tiny warning label on the YAML wrapper reading "use only when structurally necessary".
Keep it funny, but make the hierarchy legible.
-->

## XPrompts Are The Smallest Load-Bearing Idea

An [XPrompt](../../xprompt.md) is a reusable prompt reference. You write `#foo`, SASE
expands `foo`, and the agent sees the rendered text. It sounds small. It is not small.
XPrompts are how SASE keeps prompts composable enough to reuse and structured enough to
orchestrate.

The hierarchy runs from tiny to large:

| Level                             | Where it lives                                                                  | Use it for                                                                                                                                          |
| --------------------------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Config xprompt                    | `xprompts:` in `sase/sase.yml`                                                  | Aliases and tiny reusable phrases. Example: `x: "xprompt"` or `xw: "xprompt workflow"`.                                                             |
| Structured config xprompt         | `sase/sase.yml` with `content`, `description`, `input`                          | Small templates with typed inputs.                                                                                                                  |
| Markdown xprompt                  | Project/home `sase/xprompts/`, compatibility dirs, plugins, or built-ins        | Normal reusable prompt bodies. This is the sweet spot.                                                                                              |
| Markdown xprompt with frontmatter | Same as above                                                                   | Inputs, snippets, skill metadata, and local helper xprompts.                                                                                        |
| Xprompt swarm                     | Markdown file with top-level `---` segment separators                           | Fan-out or sequenced multi-agent work without needing a YAML workflow. Prefer this for most multi-agent work.                                       |
| YAML xprompt workflow             | `.yml` workflow file launched with `#!name` or embedded through a `prompt_part` | Real control flow: `agent`, `bash`, `python`, `parallel`, approvals, step outputs, artifact passing. Use it only when the structure earns its keep. |

My recommendation is simple: prefer markdown xprompts, including xprompt swarms, until
you genuinely need a YAML workflow. YAML workflows are powerful, but power is how a
three-line prompt becomes a small enterprise resource-planning system wearing a fake
mustache.

Cases where YAML workflows really are necessary:

- `#!sync`, because it coordinates repository and daemon state around the operation.
- Research swarms, because they need fan-out, aggregation, and artifacts.
- Bead epic creation workflows, because they write SDD plans, initialize beads, and
  launch follow-up work.

The key distinction: an xprompt swarm is excellent when the structure is "run these
prompt segments, maybe with `%wait` ordering." A YAML workflow is for "run code, branch,
gather outputs, call agents, validate, and continue."

```text
---
input:
  target:
    type: str
    description: What to improve.
---
%i:plan
Plan a safe change for {{ target }}.
---
%i:code
%w:plan
#fork:plan
Implement the approved safe change for {{ target }}.
---
%i:review
%w:code
Review the diff and call out risks.
```

That is an xprompt swarm. It is readable. It does not need a workflow engine. It can sit
happily in `sase/xprompts/three_phase.md` until the day it needs Bash, Python, or step
outputs.

> **Friction note:** XPrompt discovery is intentionally flexible: repo-local,
> user-local, config-defined, plugin-shipped, and built-in sources all participate. That
> is powerful, but the mental model can get slippery. Use `sase xprompt list`,
> `sase xprompt explain`, and the ACE XPrompt Browser when you are not sure which
> `#thing` wins.

## XPrompt Directives, In One Place

Directives are `%` tags that change launch behavior. They are extracted from the prompt
before the agent sees it. The full reference is in
[XPrompts: Directives](../../xprompt.md#directives); this is the practical tour.

| Directive | Alias | What it does                                                                                                                     | Example                                                            |
| --------- | ----- | -------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `%model`  | `%m`  | Select a provider/model. Model branches can fan out into one agent per model.                                                    | `%m:claude/opus audit this API`                                    |
| `%effort` | `%e`  | Set the provider reasoning-effort level for this prompt.                                                                         | `%e:xhigh investigate the race`                                    |
| `%id`     | `%i`  | Give an agent a stable name, or assign clan, family, or tribe identity through one mutually-exclusive keyword.                   | `%i:reviewer`, `%id(reviewer, tribe=review)`                       |
| `%clan`   | `%c`  | Join a named, rootless parallel clan; the member name must be inside the clan's hood.                                            | `%i:release.test %clan:release`                                    |
| `%wait`   | `%w`  | Start only after named agents or workflows complete successfully. Bare `%wait` waits for the most recently named agent.          | `%w:planner`, `%wait:agent1,agent2`, `%wait`                       |
| `#t`      |       | Delay launch by a duration or until wall-clock time. Use `%wait(time=...)` when combining with agent dependencies.               | `#t:5m`, `%wait(time=1h30m)`, `%wait(planner, time=1430)`          |
| `%hide`   | `%h`  | Hide the agent from the default Agents tab display. ACE can toggle hidden rows back into view.                                   | `%h %i:background-log-checker inspect logs`                        |
| `%auto`   | `%a`  | Request gate-specific automatic resolution; plan compatibility aliases include `plan`, `tale`, and `epic`.                       | `%a #!sync` or `%auto:epic %i:checkout plan the rewrite`           |
| `%repeat` | `%r`  | Run the same prompt serially multiple times; later slots wait on earlier slots. A slot can set `STOP` to stop the chain.         | `%r:5 %i:flaky-repro try to reproduce the flaky test once`         |
| `%alt`    | `%(`  | Split one prompt into variants. Named variants become child suffixes; model branches and text variants form a Cartesian product. | `%alt(sec=focus on auth,perf=focus on hot paths) review this diff` |

Directives compose. This launches two named model variants, assigns tribe `@review`, and
keeps them hidden unless you toggle hidden agents:

```bash
sase run '%id(api-review, tribe=review) %h %{%m:codex/gpt-5.6-sol | %m:claude/sonnet} review the API boundary'
```

And this chains a planner, coder, and reviewer without inventing a YAML workflow:

```text
%i:planner
Plan a safe docs refresh.
---
%i:coder
%w:planner
#fork:planner
Implement the plan.
---
%i:reviewer
%w:coder
Review the diff and list follow-ups.
```

## Forks Instead Of Multi-Turn Agents

SASE does not really have a first-class "multi-turn agent" concept. It has durable agent
records, transcripts, artifacts, and `#fork`.

`#fork:<agent-name>` injects sanitized previous conversation context into a new agent
prompt. That gives you the useful part of "continue this agent" without making every
workflow depend on one mutable, forever-growing chat session. It also plays nicely with
`%wait`: wait for the prior agent to finish, then fork from it.

```bash
sase run '%i:design propose a small architecture improvement'
sase run '%i:implement %w:design #fork:design implement the approved part only'
```

The forked agent gets a new record and a new workspace. You still have lineage, but the
unit of work stays inspectable.

## SDD: Prompts, Tales, Epics, And Beads

SASE's [Spec-Driven Development](../../sdd.md) store is where agent intent becomes
durable project state. Provider policy places it at `sdd/` for in-tree projects,
`.sase/sdd/` for providerless local and legacy single-companion projects, or split
`--plans` and `--research` roots for newly initialized or migrated managed GitHub
projects.

The core logical roots are:

- `<plans-root>/<YYYYMM>/`: approved implementation plans, classified by
  `tier: tale|epic`. Tales are focused plans; epics are executable multi-phase plans
  that can be turned into Beads and driven by `sase bead work`.
- `<agents-sidecar>/prompts/<YYYYMM>/`: canonical committed run prompts. XPrompts are
  resolved, directives are stripped, and prompt-linked artifacts are made clickable.
- `<agents-sidecar>/artifacts/<YYYYMM>/`: copied prompt-linked bytes, named with a
  SHA-256 prefix; clean tracked files link to hosted source blobs instead of being
  duplicated.
- `beads/`: git-portable issue/dependency state under the resolved SDD store, with bead
  data, events, JSONL compatibility output, and the SQLite query cache.

The flow is intentionally concrete:

```bash
sase plan search
sase plan links validate
sase bead ready                 # unblocked task beads explicitly marked ready
sase bead show <bead-or-task-id>
sase bead work <epic-id>
sase bead work <task-id>
```

An epic can produce dependency-ordered phase beads, and `sase bead work <epic-id>`
launches their workers plus a final land agent. A standalone task bead has no parent
epic: move it from draft `open` to `ready` for human triage, then launch one worker with
`sase bead work <task-id>`. `sase bead ready` lists only task beads explicitly marked
`ready` whose dependencies are closed.

This is where Steve Yegge's [Beads](https://github.com/gastownhall/beads) influence is
most obvious. Beads makes agent-friendly work items git-portable and dependency-aware.
SASE borrows that spirit, then integrates it with SDD plans, Patches, ACE, AXE, and
local workspace orchestration.

<!--
ARCHITECTURE DIAGRAM BRIEF 2 - place here after the SDD/Beads section.
Title: "Durable work state graph"
Shape: graph/flow diagram, not a stack.
Nodes: user prompt -> agents-sidecar prompt archive -> tale OR epic -> phase beads in the resolved SDD store -> agent
runs -> commits -> Patch -> PR provider -> final archive. Add a separate standalone task bead -> one worker branch.
Side nodes: ACE reads Patches/agents/beads; AXE watches waits/hooks/chops; Telegram emits/receives notifications.
Draw dependencies between phase beads clearly; reserve the `ready` label for standalone task triage.
Purpose: show that chat history is not the source of truth; durable files and state records are.
-->

> **Friction note:** SDD has a lot of nouns. Prompt, tale, epic, bead, Patch. The nouns
> are there because the lifecycle stages are different, but the docs and UI need to keep
> doing better at teaching "what do I touch today?" versus "what exists for the full
> research roadmap?"

## ACE: The Cockpit

`sase ace` opens the Agentic Change Explorer, the terminal UI for daily work. ACE has
three top-level tabs:

- **Agents**: live and recent agents, groups, tags, hidden rows, child workflow steps,
  prompt panels, transcript panels, artifact viewers, tool metadata, file panels,
  retry/fork/wait/kill actions, and model/provider badges.
- **Artifacts**: Stitches, Patches, Beads, and Files top-level views, with Plans, Chats,
  and Other nested under Files. The Patches view owns Patch status, hooks, comments,
  mentor output, diffs, file deltas, mail/submit flows, rewind, revert, restore, and
  archive operations; Chats browses transcripts with local/shared/remote sync
  provenance.
- **Axe**: the daemon view: lumberjacks, chops, run history, live output, wait checks,
  hook checks, mentor checks, comment polling, and error digests.

<!--
SCREENSHOT BRIEF 1 - place immediately after the ACE tab list.
Asset suggestion: docs/images/blog/00-ace-agents-tab.png
View: ACE Agents tab in a real terminal, 16:10 or 16:9 crop.
Show several grouped agents: at least one running, one waiting via %wait, one completed, and one hidden/toggled row.
Include the prompt preview panel on the right and a bottom prompt bar with completion hints visible.
Make sure provider/model badges are legible, and include one tribe side panel so the screenshot says "control
surface" rather than "log list".
Alt text: "ACE Agents tab showing grouped coding-agent runs, provider badges, wait state, prompt preview, and prompt
input completion."
-->

ACE is fun because it treats agents as work records, not mystical chat bubbles. You can
fork an agent, wait on one, retry a failed run, inspect its artifacts, view its changed
files, jump to the workspace, or hide background noise until you care about it. You can
also open the XPrompt Browser, insert snippets, complete directives, complete file
paths, and compose multi-agent prompts directly in the prompt input widget.

The VCS support is the part that makes ACE feel like engineering software instead of a
prettier terminal. SASE's VCS providers are pluggy-based. Bare Git support ships with
`sase`; GitHub support lives in `sase-github`. ACE shows the same review objects either
way: file deltas, diffs, commit lists, Patch status, and provider-backed actions.

In practice, this means you can:

- inspect a Patch's diff from the TUI;
- view added/modified/deleted file counts and line deltas;
- rewind a PR to an earlier state;
- revert an agent's committed work and archive the Patch;
- restore a reverted Patch by re-applying its diff;
- launch follow-up agents against the exact work record you are looking at.

<!--
SCREENSHOT BRIEF 2 - place after the VCS paragraph above.
Asset suggestion: docs/images/blog/00-ace-prs-diff.png
View: ACE Artifacts tab with the Patches sub-tab focused on one Patch with file deltas and diff preview visible.
Show status, commits, and at least one action hint for diff/revert/rewind. The key visual should be "this is not just
chat; this is reviewable code state."
Alt text: "ACE Artifacts Patches view showing a Patch with file deltas, commits, diff preview, and VCS actions."
-->

## AXE, Lumberjacks, And Chops

[AXE](../../axe.md) is the background daemon. It runs **lumberjacks**, and lumberjacks
run **chops**. Yes, the naming theme got away from me. No, I am not apologizing yet.

A lumberjack is a scheduled lane of background work. A chop is one script-only unit of
work in that lane. Built-in lumberjacks handle things like hook checks, wait checks,
mentor checks, workflow cleanup, comment polling, stale-running cleanup, and error
digests.

Scripts can return a versioned JSON result with structured launch proposals. AXE
validates those proposals, injects workspace/name/tribe scaffolding, launches the
agents, and follows them through success or failure. The scripts never self-launch.
Declarative commit triggers, Patch and agent-hood guards, once-per dedupe, and project
target fan-out keep the scheduling mechanics out of individual scripts.

The builtin `sase_chop_refresh_docs`, for example, fans out over enabled projects and
proposes an update agent followed by a polish agent. External chop packages can add
focused audits or maintenance jobs through full-name console scripts, while `tg_inbound`
and `tg_outbound` connect AXE to `sase-telegram`.

That is the pattern: AXE is not "one more agent." It is the supervisor that notices
state changes, runs the right scripts, and owns any resulting agent lifecycle.

<!--
SCREENSHOT BRIEF 3 - optional, place after the AXE examples if the final post wants a third TUI image.
Asset suggestion: docs/images/blog/00-ace-axe-tab.png
View: ACE Axe tab with lumberjack tree on the left, recent chop runs in the center, and live output/history panel on the
right. Include a Telegram chop and a GitHub Actions fixer chop if possible.
Alt text: "ACE Axe tab showing lumberjacks, scheduled chops, recent run status, and live chop output."
-->

> **Friction note:** AXE is powerful, but it needs more friendly defaults and clearer
> onboarding. The daemon model is correct; the "why is a lumberjack holding my CI logs?"
> learning curve is still a curve.

## Telegram: The Pocket Cockpit

[`sase-telegram`](https://github.com/sase-org/sase-telegram) gives SASE a chat bridge.
It is implemented as AXE chops: an outbound chop reads notifications and sends them to
Telegram, while an inbound chop polls Telegram and turns replies or slash commands into
SASE actions.

Useful things it can do:

- notify you when an agent finishes, fails, asks a question, or needs plan approval;
- let you approve, reject, or give feedback on plans from your phone;
- list, kill, fork, retry, or inspect agents with slash commands;
- show Patch and Bead summaries;
- launch agents from messages, including messages with images or PDF attachments;
- keep outbound notifications quiet when ACE sees you actively working at the terminal.

<!--
TELEGRAM SCREENSHOT BRIEF 1 - place after the feature list.
Asset suggestion: docs/images/blog/00-telegram-plan-approval.png
View: Telegram chat showing a SASE plan approval message with concise plan summary and inline buttons.
Buttons should include Tale, Epic, Reject, and Feedback if the current UI supports them.
The message should make clear which repo/workspace/agent produced the plan.
Alt text: "Telegram message from SASE asking for plan approval with action buttons for Tale, Epic, Reject, and
Feedback."
-->

<!--
TELEGRAM SCREENSHOT BRIEF 2 - place after the paragraph below.
Asset suggestion: docs/images/blog/00-telegram-agent-actions.png
View: Telegram chat showing an agent completion notification with action buttons such as Fork, Wait, Retry, Kill, Files,
or Changes, plus a small prompt excerpt.
Include one example where the user replies with a slash command like /list or /changes.
Alt text: "Telegram chat showing a SASE agent notification with follow-up action buttons and slash-command control."
-->

Telegram is not meant to replace ACE. It is the thing you use when an agent asks a
yes/no question while you are away from the keyboard and your laptop is, unreasonably,
not strapped to your face.

## Neovim, The XPrompt LSP, And The Prompt Widget

[`sase-nvim`](https://github.com/sase-org/sase-nvim) is the canonical editor
integration. The important idea is not "Neovim gets a plugin," although it does. The
important idea is that SASE exposes an XPrompt language server.

The XPrompt LSP can provide:

- completion for `#xprompt`, `#!workflow`, slash skills, directives, arguments, and file
  paths;
- hover text for xprompt definitions and inputs;
- diagnostics for malformed references or arguments;
- go-to-definition for xprompt files;
- snippets and skeleton insertion for typed xprompt inputs;
- YAML schema help for workflow files.

ACE's prompt input widget overlaps with that on purpose. It uses the same catalog and
helper machinery for directive completion, xprompt insertion, slash-skill insertion,
argument hints, snippets, file completion, and prompt history.

The division of labor is ergonomic: ACE is fastest for launching and steering work in
the cockpit; Neovim is better for writing longer prompt files, editing workflow YAML,
navigating xprompt definitions, and using editor-native muscle memory. The same prompt
system should feel familiar in both places.

> **Friction note:** The editor story should not be Neovim-only forever. `sase-nvim` is
> the reference client because I live there, but the LSP exists so other editors can use
> the same xprompt intelligence without copying SASE internals.

## Scarcity Is Coming For Our Robot Budgets

I am using **AI era of scarcity** as my shorthand for a trend I picked up from
[The AI Daily Brief](https://podcasts.apple.com/us/podcast/the-ai-daily-brief-artificial-intelligence-news/id1680633614)
and its "token scarcity" framing: the era of infinite-feeling subsidized inference is
giving way to usage limits, provider tiers, routing decisions, and pricing details that
matter.

SASE is an answer to that world because it assumes agent work should be schedulable,
inspectable, and routable across providers. The `model_aliases` config map is a small
example:

```yaml
llm_provider:
  provider: codex
  model_aliases:
    builtin:
      codex_coder: claude/opus
      claude_coder: codex/gpt-5.6-sol
```

That means delegated coder follow-ups can use a different provider/model than the
planner that handed them off. If the planner is Codex, its coder can go to Claude Opus.
If the planner is Claude, its coder can go to Codex. The goal is not "always use the
biggest model." The goal is "put scarce reasoning where it matters and route routine
follow-up work somewhere sensible."

The same idea appears in prompts:

```bash
sase run '%i:api-audit %{%m:codex/gpt-5.6-sol | %m:claude/sonnet} audit the API boundary and compare findings'
```

That launches a model fan-out. Sometimes the right answer is not trusting one model
harder. Sometimes it is asking two models, comparing the overlap, and letting ACE keep
the results from turning into tab soup.

> **Friction note:** SASE needs better budget visibility. It can route work today, but
> the future version should make cost, quota, rate limits, and provider health visible
> in the same way ACE makes agent state visible.

## Useful Commands

These are the commands I reach for most:

| Command                                                  | Why you use it                                                       |
| -------------------------------------------------------- | -------------------------------------------------------------------- |
| `sase doctor`                                            | Read-only install, config, provider, project, and state diagnostics. |
| `sase version`                                           | Exact SASE, Rust core, and plugin package inventory.                 |
| `sase ace`                                               | Open the TUI cockpit.                                                |
| `sase run "..."`                                         | Launch an agent, xprompt, or workflow.                               |
| `sase agent list`                                        | See active and recent agent runs from the terminal.                  |
| `sase xprompt list`                                      | See available xprompts and workflows.                                |
| `sase xprompt explain "#foo"`                            | Inspect how a prompt reference resolves.                             |
| `sase xprompt graph "#!workflow"`                        | Visualize workflow structure.                                        |
| `sase plan`                                              | Review, approve, and manage submitted plans.                         |
| `sase plan search` / `sase plan links validate`          | Inspect and validate SDD artifacts.                                  |
| `sase bead ready` / `sase bead work`                     | Triage unblocked ready tasks, or execute a task or epic.             |
| `sase axe lumberjack status`                             | Check scheduled background automation.                               |
| `sase axe chop doctor`                                   | Verify configured chops, scripts, and Telegram chop setup.           |
| `sase workspace open -p <linked_repo> -r "<reason>" <n>` | Open a configured linked repo's matching numbered workspace.         |
| `sase lsp`                                               | Start the XPrompt language server for editor integrations.           |
| `sase mobile gateway start`                              | Start the workstation-hosted mobile gateway.                         |

The [CLI reference](../../cli.md) is the full inventory.

## The Papers Behind The Name

SASE is heavily inspired by the paper
["Agentic Software Engineering: Foundational Pillars and a Research Roadmap"](https://arxiv.org/abs/2509.06216).
The paper presents the **Structured Agentic Software Engineering (SASE)** vision, and
this project takes its name and framing directly from that vocabulary. It splits the
future of software engineering into **SE for Humans** and **SE for Agents**, then
proposes two workbenches: **ACE**, the **Agent Command Environment**, where humans
orchestrate and mentor agent teams, and **AEE**, the **Agent Execution Environment**,
where agents execute work and call humans in for ambiguity or complex trade-offs. SASE
maps that lineage into local tooling: its **ACE** cockpit is the **Agentic Change
Explorer**, but it deliberately echoes the paper's Agent Command Environment; **AXE** is
the background execution/supervision daemon that echoes the paper's Agent Execution
Environment.

SASE is also inspired by IBM's
[Prompt Declaration Language](https://github.com/IBM/prompt-declaration-language) and
the [PDL paper](https://arxiv.org/abs/2410.19135). PDL argues for declarative,
composable prompt programs that keep prompts visible rather than burying them in
framework code. SASE's YAML xprompt workflows borrow that idea, then specialize it for
local software-engineering work: agent steps, Bash/Python steps, workspace references,
SDD files, Beads, and VCS state.

The lesson from both papers is the same: agentic coding becomes agentic software
engineering only when prompts, artifacts, process, and supervision become first-class.

## Gas Town, Beads, And The Interface Question

Steve Yegge's [Beads](https://github.com/gastownhall/beads) and
[Gas Town](https://docs.gastownhall.ai/) have also influenced SASE. Gas Town's docs
describe a world of towns, rigs, the Mayor, Deacon, Witness, Refinery, crew workspaces,
and polecat worker worktrees. The phrase from the docs that best captures the philosophy
is the "Propulsion Principle": if work lands on an agent's hook, the agent runs it.

SASE agrees with the premise that agents can run agents and perform useful autonomous
work. Where it differs is focus. Gas Town appears to explore what becomes possible when
a town of agents dispatches and executes work through roles and autonomous propulsion.
SASE assumes that premise is true, then asks a narrower product question: what is the
right local interface for one developer supervising many coding agents across real
repos, real diffs, real plans, and real PRs?

One concrete difference is xprompt workflows. SASE YAML workflows can intersperse agent
calls with Python and Bash steps, pass outputs, branch, parallelize, and validate. I did
not find an equivalent control surface in the public Gas Town docs; Gas Town's public
model is more role/rig/dispatch oriented. That does not make one approach universally
better. It just means SASE leans harder into "prompt/workflow as local programmable
artifact."

<!--
FUNNY DIAGRAM BRIEF 2 - place here after the Gas Town comparison.
Title: "Mayor vs cockpit"
Shape: split-panel cartoon.
Left panel: Gas Town as city hall. A Mayor at a desk dispatches beads to rigs, with polecats in hard hats running to
worktrees. Label it "autonomous town experiments".
Right panel: SASE as a terminal cockpit. A developer sits at ACE with levers labeled XPrompts, Beads, AXE, VCS, and
model_aliases; several agent planes are queued on a runway.
Caption: "Both believe agents can do work. SASE obsesses over the control surface."
Keep it affectionate and clearly respectful of Gas Town/Beads.
-->

## Future Directions: Memory, Mobile, Web

Three directions are incomplete but important:

- [Memory](../../memory.md): SASE already has short-term project memory, audited
  long-term memory reads, and proposal-based writes. The next frontier is better
  retrieval, staleness handling, trust boundaries, and UI.
- Mobile: the [mobile gateway](../../mobile_gateway.md) and Android MVP work point
  toward a real mobile SASE client. Telegram covers a lot today, but a purpose-built app
  can expose richer state than chat buttons.
- Web: the Rust core boundary exists partly so a future web interface can share the same
  domain behavior as ACE, Telegram, and editor integrations instead of becoming a
  separate almost-SASE.

These are exciting because they all point at the same principle: the agent state should
be durable and shared across surfaces. The terminal should not be the only window into
the work.

> **Friction note:** The future-surface story is promising but unfinished. Today, ACE is
> the daily driver; Telegram and Neovim are useful companions; mobile and web are still
> early. The architecture is moving in the right direction, but nobody should pretend
> the phone app is already the Death Star. Also, given my luck, the exhaust port would
> be YAML.

## The Point

Coding agents need more than better prompts. They need an operating layer: a place where
intent, workspaces, plans, dependencies, review state, automation, notifications, and
provider choices become explicit.

That is what SASE is trying to be.

Not the model. Not the IDE. Not the VCS host. The layer that lets those pieces cooperate
without making a human keep the entire system in short-term memory and twelve terminal
tabs.

The practical on-ramp is [Getting Started](../../getting_started.md).
