---
create_time: 2026-05-11 19:23:48
status: done
prompt: sdd/prompts/202605/new_blog_posts.md
---
# Plan: Add Posts 3–8 to the Agentic Software Engineering Blog Series

## Context

The blog at `docs/blog/posts/` currently has two numbered posts in the Agentic Software Engineering series:

- **Post 1** — `why-coding-agents-need-orchestration.md` (2026-05-08), the conceptual argument.
- **Post 2** — `hello-sase-your-first-15-minutes.md` (2026-05-10), the hands-on tour.

The user wants six new posts that go deeper on individual subsystems and close with a forward-looking essay. Today is
2026-05-11; Post 2 was published yesterday. Posts 3–8 should publish on sequential dates starting 2026-05-12.

All six follow the same shape already established by Posts 1 and 2:

- Material-blog frontmatter (`date`, `description`, `categories`, `slug`, `links`).
- Numbered H1 (`# Post N: <Title>`) — Material's blog plugin reads the H1, so this also drives the listing, drawer,
  browser title, and RSS.
- One-paragraph lede above `<!-- more -->`.
- Section skeleton fleshed out with on-topic prose pulled from the relevant product doc (linked, not duplicated
  wholesale).
- "Series Navigation" footer with Previous/Next wired into the chain.

Auxiliary surfaces that name posts by number need to be kept in sync, the same way commit `9da6c0eb`
(`chore(blog): number each blog post across sase.sh surfaces`) did the work for Posts 1–2.

## Topics, in order

Six posts, six topics. Working titles below — I'll keep them short enough to fit the post drawer and browser tab
cleanly.

| #   | Date       | Working title                                                | Slug                           |
| --- | ---------- | ------------------------------------------------------------ | ------------------------------ |
| 3   | 2026-05-12 | XPrompts in Depth: From One File to Full Workflows           | `xprompts-in-depth`            |
| 4   | 2026-05-14 | AXE: The Background Daemon That Keeps Agent Work Moving      | `axe-background-daemon`        |
| 5   | 2026-05-16 | Beads and SDD: Planning Multi-Agent Work That Actually Lands | `beads-and-sdd`                |
| 6   | 2026-05-18 | Commit Workflows: The Pluggable Path From Diff to PR         | `commit-workflows-plugins`     |
| 7   | 2026-05-20 | ChangeSpecs in Practice: Review State Outside the Chat       | `changespecs-in-practice`      |
| 8   | 2026-05-22 | What's Next: Shared Memory, Mobile, and the Web Surface      | `whats-next-memory-mobile-web` |

Dates step every other day so the archive page reads as a deliberate series rather than a same-week dump.

## Section skeletons

Each skeleton lists the H2s I'll write, with one-line notes on what each section covers. I'll write the prose inside the
same edit pass; the notes are the contract.

### Post 3 — XPrompts in Depth

- **Lede**: a single `#tag` is the smallest reusable unit of agent work in SASE. This post is about what's underneath
  that tag and when to stop there instead of reaching for a workflow.
- **The smallest XPrompt is a Markdown file** — one `.md` file in `xprompts/`, invoked as `#name`. Optional YAML
  frontmatter for name, description, snippet, skill, keywords. Discovery order: project → user → home → config → plugins
  → built-ins.
- **Typed inputs and Jinja substitution** — when prompts need parameters, declare them with `input:`
  (word/line/text/path/int/bool/float). Default values, validation, Jinja access.
- **Directives** — `%model`, `%name`, `%wait`, `%time`, `%approve`, `%epic`, `%plan`, `%repeat`, `%alt`. The
  minimum-viable list, with the point: directives let you control execution without leaving Markdown.
- **Workflow YAML: when prose is no longer enough** — `step` types (`prompt_part`, `agent`, `bash`, `python`,
  `parallel`), control flow (`if`, `for`, `while`, `repeat`/`until`), join modes, artifact passing, HITL approvals,
  `finally`/cleanup steps, the `done.json` completion marker.
- **Multi-agent fan-out without a workflow** — the `---` separator in any prompt or `.md` xprompt splits dispatch into N
  agents. Often the right answer instead of a workflow.
- **Don't reach for workflows first** — explicit caution. If a single `.md` file plus `---` and a couple of directives
  gets the job done, that is the answer. Workflows are for control flow that genuinely needs YAML (loops, parallel
  joins, HITL, typed structured outputs). Cost of YAML: more state, more failure modes, more to debug.
- **The plugin path** — XPrompts can ship from `sase_xprompts` entry-point packages. This is how `crs`, `fix_hook`, and
  commit workflows become overridable.
- **What to read next** — `xprompt.md`, `workflow_spec.md`, Post 4.

### Post 4 — AXE: The Background Daemon

- **Lede**: agents shouldn't poll. AXE is the daemon that does the polling for them so the engineering workflow keeps
  moving while individual agents finish, fail, or wait.
- **The architecture in one paragraph** — Orchestrator → Lumberjacks (scheduler loops) → Chops (jobs). Default
  lumberjacks and their cadences: `hooks` (5s), `waits` (2s), `checks` (5m), `comments` (1m), `housekeeping` (1h).
- **Hooks chop** — runs hook checks, mentor checks, workflow checks, pending-checks polling, suffix transforms, orphan
  cleanup. This is the bulk of "what AXE is doing on your behalf."
- **Waits chop** — `%wait` resolves here. The matching agent's newest run must produce a `done.json` with outcome
  `completed` before the waiter unblocks. The point: dependencies between agents without a workflow YAML.
- **Comments chop** — polls the VCS for new review comments, kicks off critique agents. Where mentor follow-up actually
  lives.
- **Housekeeping chop** — error-digest summarization, the `ViewErrorReport` notification, periodic cleanup.
- **Lumberjack control surface** — `sase axe lumberjack status`, start / stop, custom intervals, the maintenance-mode
  protocol (`sase axe maintenance enter --reason …`) for safely pausing AXE before plugin updates or workspace moves.
- **Don't run resource-heavy work inside a chop tick** — short jobs only; long-running ones become agents.
- **What to read next** — `axe.md`, `notifications.md`, Post 5.

### Post 5 — Beads and SDD

- **Lede**: orchestration only matters if you can split work into pieces with a real ordering. Beads and SDD are how
  SASE files that work and schedules it.
- **SDD in one minute** — Spec-Driven Development. Three plan tiers: _tales_ (ordinary plans), _epics_ (executable
  multi-phase), _legends_ (cross-cutting). On-disk artifacts with frontmatter, dates, and prompt-plan back-links.
  `sase sdd list`, `sase sdd validate`.
- **Beads are the work unit** — git-portable, SQLite-backed, JSONL-shadowed issue records. Status: `open` →
  `in_progress` → `closed`. Dependency edges. A bead can carry a plan reference, an epic id, or just a task.
- **Ready vs blocked** — `sase bead ready` shows what is open with all deps closed. `sase bead blocked` shows the rest.
  The point: the queue tells you what to start next instead of you reconstructing it from chat.
- **`sase bead work <epic-id>`: multi-agent execution** — builds the dependency schedule from open phase beads,
  pre-claims each phase, launches one agent per phase in order, then a final land agent. This is the part that turns a
  plan into work.
- **The promote-from-chat discipline** — agents propose plans, humans promote them into SDD. The reason: keeping raw
  transcripts out of the canonical artifact, so the durable plan is something a reviewer can trust.
- **Multi-workspace behavior** — reads are unified across `sase_<N>` workspaces, writes always go to the primary. So an
  agent in a sibling workspace closes its own phase, not the epic.
- **What to read next** — `sdd.md`, `beads.md`, Post 6.

### Post 6 — Commit Workflows: Pluggable VCS

- **Lede**: every agent eventually has to land code somewhere. The commit XPrompt workflows are the small,
  runtime-uniform layer that turns an agent's diff into a commit, a proposal, or a pull request — without the agent
  caring which VCS is underneath.
- **One CLI, three outcomes** — `sase commit` drives `#commit`, `#propose`, and `#pr`. Each is an XPrompt workflow with
  the same pre-stages (bead association → lifecycle → plan handling → precommit → parent detection → diff capture →
  checkpoint) and a different VCS dispatch at the end.
- **The stop-hook contract** — `sase_commit_stop_hook` detects an agent that finished with uncommitted changes and
  instructs it to invoke the matching commit skill. Same hook for every runtime — Claude, Codex, Gemini, Qwen, OpenCode.
  No runtime-specific branching.
- **Runtime-uniform commit skills** — each agent runtime ships the same skill surface. The point: the skill names,
  flags, and outputs are identical across runtimes, so an XPrompt that calls into the commit workflow runs the same way
  regardless of who is on the other end.
- **VCS provider boundary** — `create_commit`, `create_proposal`, `create_pull_request` are pluggy hooks.
  `BareGitPlugin`, `GitHubPlugin`, and `HgPlugin` implement them. New VCS providers slot in without touching the
  workflow.
- **Resume after conflict** — checkpoint preserved before VCS dispatch. `sase commit --resume` re-runs the post-dispatch
  work after a human resolves a merge conflict. This is the recovery path that makes multi-agent execution survivable.
- **What's in `commit_result.json`** — method, result (hash/path/URL/null), message, name, bead_id, ChangeSpec name. The
  durable hand-off between the agent that wrote the code and whoever (or whatever) consumes the result.
- **The public plugin API** — what `sase_vcs` and `sase_xprompts` entry points let you do; the disable-via-env story
  (`SASE_DISABLE_PLUGINS`, `SASE_DISABLE_PLUGIN_XPROMPTS`, `SASE_DISABLE_PLUGIN_CONFIG`).
- **What to read next** — `commit_workflows.md`, `plugins.md`, `vcs.md`, Post 7.

### Post 7 — ChangeSpecs in Practice

- **Lede**: ChangeSpecs are the durable, reviewable shape of one CL/PR of agent work. They survive the chat. Post 2
  named them; this post lives inside them.
- **The `.gp` record, end to end** — section order: NAME, DESCRIPTION, PARENT, BUG, CL/PR, STATUS, TEST TARGETS,
  COMMITS, DELTAS, HOOKS, COMMENTS, MENTORS, TIMESTAMPS. Active specs in `<project>.gp`, terminal ones (Submitted /
  Reverted / Archived) in `<project>-archive.gp`. Status lifecycle WIP → Draft → Ready → Mailed → Submitted.
- **COMMITS, drawers, and proposals** — numbered entries `(1)`, `(2)`, proposals as `(2a)`/`(2b)` with
  `(!: NEW PROPOSAL)`. The CHAT, DIFF, PLAN drawers stitched under each commit are how you get back from a ChangeSpec to
  the artifacts the agent produced.
- **Mentors** — what they actually do. Mentor profiles match commits via `file_globs`, `diff_regexes`,
  `amend_note_regexes`, or `first_commit`. When a profile matches, AXE waits for non-skipped hooks, then launches one
  background mentor agent per mentor in the profile. Output is structured JSON: focus, file, line, description,
  severity. Statuses: STARTING / RUNNING / PASSED / COMMENTED / FAILED / KILLED / DEAD.
- **`fix_hook` and `crs`** — the two canonical mentor-adjacent XPrompts: `fix_hook` for hook-failure remediation, `crs`
  for code-review surfacing. Both are pluggable via tag override.
- **HOOKS, the `!` and `$` prefixes** — `!` skips fix-hook hints, `$` skips the hook for proposals. Where to put each,
  why.
- **Advanced ACE operations on ChangeSpecs** — grouping (`o`/`O` cycles BY_PROJECT / BY_DATE / BY_STATUS), tree
  navigation (`<`/`>`/`~`, Ctrl+O/Ctrl+K history, `` ` `` jump-all), CL actions (`a`/`C`/`d`/`e`/
  `f`/`M`/`m`/`n`/`R`/`s`/`Y`), fold modes (`z c`, `z h`, `z m`, `z t`), mentor review (`,m` to review, `Space` to
  toggle accept, `a` to apply+propose, `A` to apply+commit, `r` to re-run a profile, `K` to kill).
- **TIMESTAMPS** — auto audit trail. Useful when a ChangeSpec has been through several agents and you want to know which
  one did what.
- **What to read next** — `change_spec.md`, `mentors.md`, `ace.md`, Post 8.

### Post 8 — What's Next

- **Lede**: SASE today is the orchestration layer. The next horizon is about the things that horizon-line doesn't quite
  reach yet — durable shared memory, a phone you can drive from, and a browser the team can open without learning a TUI.
- **Shared memory across agents** — the gap today: short-term and dynamic memory work per-session, but there's no
  canonical cross-agent store. The direction (sketched in `sdd/research/202605/zettel_sase_shared_memory.md`): a
  two-layer system with a canonical zettel and SASE memory projections, agents proposing facts via an inbox and humans
  promoting them, agent-initiated retrieval (`sase memory search` / `show` / `related`). Why this matters: today's
  agents reconstruct context every time; tomorrow's should be able to ask.
- **Why this isn't shipping yet** — memory poisoning, projection cost, retrieval determinism. The proposal lists the
  four-phase rollout: read- only projections first, project-local zettel next, then the agent proposal flow, finally
  agent-initiated retrieval. Each phase ships something usable; the whole stack doesn't have to land at once.
- **Mobile** — the mobile gateway already exists (`sase mobile gateway start`, loopback by default, Tailscale Serve for
  remote, pairing flow via `POST /session/pair/start` then `/finish`). Today's gateway is a tightly-scoped HTTP API:
  list agents, launch text, kill, retry, ChangeSpec tag operations, XPrompt catalog, beads list, SSE event stream.
  What's missing: richer interactions, push hints that feel native, and a story for non-loopback deployments that isn't
  "wire up Tailscale yourself."
- **Web** — analogous shape to mobile: an HTTP surface that doesn't require terminal-native ACE. Open question on
  whether the web frontend reuses the gateway or stands up its own.
- **The throughline** — every horizon in this list trades terminal-native context for context that lives outside one
  developer's head. Memory moves intent across agents; mobile and web move the control surface to wherever the operator
  is.
- **What to read next** — `mobile_gateway.md`, `sdd/research/202605/zettel_sase_shared_memory.md`, the series hub.

## Frontmatter shape (uniform across all six)

```yaml
---
date: <YYYY-MM-DD>
description: >-
  One-to-two-sentence description used by Material's blog plugin in the listing drawer and the RSS feed.
categories:
  - Agentic Software Engineering
  - <topic-specific category>
slug: <slug-from-table>
links:
  - Agentic Software Engineering Series: series/agentic-software-engineering.md
  - <one or two on-topic doc links>
  - "Post <prev-N>: <prev-title>": blog/posts/<prev-slug>.md
  - View on GitHub: https://github.com/sase-org/sase
---
```

Per-post `categories` additions: Post 3 = `XPrompts`; Post 4 = `Automation`; Post 5 = `Planning`; Post 6 = `Workflows`;
Post 7 = `Review`; Post 8 = `Roadmap`.

## Series Navigation footer (uniform)

At the bottom of every new post:

```markdown
## Series Navigation

This is Post N of the [Agentic Software Engineering series](../../series/agentic-software-engineering.md).

- Previous: [Post N-1: <title>](<prev-slug>.md).
- Next: [Post N+1: <title>](<next-slug>.md). <!-- "none (latest post)" on Post 8 -->
- Continue reading: [series hub](../../series/agentic-software-engineering.md), [blog home](../index.md), or
  [<closest-on-topic doc>](../../<doc>.md).
```

Post 2 (existing) currently says `Next: none (latest post)` — it will be updated to link Post 3.

## Auxiliary surfaces to update

The same surfaces the numbering commit (`9da6c0eb`) touched, plus the obvious inclusion edits:

1. **`docs/blog/posts/why-coding-agents-need-orchestration.md`** — no change needed (already links Post 2 as Next).
2. **`docs/blog/posts/hello-sase-your-first-15-minutes.md`** — update the Series Navigation footer's Next link from
   "none (latest post)" to Post 3. Leave its `links:` frontmatter alone (Material limits how many fit cleanly in the
   drawer).
3. **`docs/blog/index.md`** — extend the "Start Here" list from two items to all eight. Keep the orientation paragraph;
   consider trimming the "If you'd rather run the system before reading…" sentence so the section doesn't sprawl.
4. **`docs/series/agentic-software-engineering.md`** — replace the two-row series table with an eight-row one. Update
   intro prose from "two posts" to "eight posts." Reader Paths list is still accurate but I'll re-anchor it to read
   naturally after a longer series.
5. **`mkdocs.yml`** — extend the `Blog` nav block with one entry per new post, in numbered order, matching the existing
   `"Post N: <Title>": blog/posts/<slug>.md` format. Update the surrounding `# claudeMd`-style comment if any (none
   currently).

## Validation

After writing, run from the workspace root:

```bash
just check
```

`just check` covers `ruff`, `mypy`, and the test suite. Markdown-only changes won't trip linters, but the test suite
catches doc-link breakage via the docs-link-validator tests if any are present. If the docs build is wired into
`just check`, that will also surface bad relative links between posts.

## Out of scope

- No new docs under `docs/<concept>.md`. Each post links into existing docs; this is a publishing change, not a docs
  rewrite.
- No mkdocs config beyond the nav block. Categories, slugs, and the existing `blog` plugin config already do what we
  need.
- No backfilling of Posts 1–2 (they were just renumbered in `9da6c0eb`).
- No `sdd/tales/` plan file is being added for this work — the request is a publishing/editorial change, not a
  multi-phase implementation.
