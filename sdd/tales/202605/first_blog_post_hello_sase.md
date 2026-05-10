---
name: first_blog_post_hello_sase
status: draft
create_time: 2026-05-10 19:41:03
prompt: sdd/prompts/202605/first_blog_post_hello_sase.md
---

# Plan: First Blog Post — A Hands-On "Hello, SASE" Tour

## Goal

Write the first blog post for SASE that gets a curious reader **installed, running an agent, and aware of every
important component within ~15 minutes**. The post should be the practical on-ramp that the existing launch essay ("Why
Coding Agents Need Orchestration") deliberately is not — it should hook new users with concrete commands and visible
results, then point them at the conceptual essay and per-component guides for depth.

Concretely, after finishing the post a reader should be able to:

1. Install SASE and verify the install.
2. Launch their first agent run with `sase run`.
3. Open ACE and find the resulting ChangeSpec, the agent record, and any notifications.
4. Recognize the names of the other major SASE pieces (Beads, XPrompts, Workflows, AXE, SDD, Plugins) and know which doc
   page to read next for each.

## Current state

- `docs/blog/posts/` contains exactly one post: `why-coding-agents-need-orchestration.md`. It is conceptual ("durable
  intent beats chat history", "supervision belongs outside the agent"), with very few shell commands and no install
  step. It is positioned as series post #1 in `docs/series/agentic-software-engineering.md`.
- `docs/index.md` (the site landing page) is feature-rich but is a marketing surface, not a guided tour. Its primary
  CTAs are "Read the launch essay", "Start with ACE", "Explore the series", "Download PDF", "View on GitHub".
- `README.md` has a 6-line Quick Start (`uv venv` → `just install` → `sase`) plus four "useful first commands"
  (`sase ace`, `sase run`, `sase agents status`, `sase bead onboard`), but it is README-shaped — not a narrative.
- The blog index page (`docs/blog/index.md`) and the series hub both expect new posts to live under `docs/blog/posts/`
  with frontmatter (`date`, `description`, `categories`, `slug`, `links`), and posts are routed by slug via
  `mkdocs.yml`'s `post_url_format: "{slug}"`.
- There is no existing "getting started" / "your first run" narrative anywhere on the site. That is the gap this post
  fills.

## Why a new post (not editing the existing essay)

The launch essay is intentionally a manifesto: it argues _why_ SASE exists. A reader who has not yet installed anything
cannot evaluate that argument. The two pieces are complementary:

- **Hands-on first post (this plan)** — "I tried it, here is what happened, here is the map." Hooks practitioners.
- **Launch essay (existing)** — "Here is why this shape of system is the right one." Hooks skeptics and architects.

Both should be reachable from the blog home and the series hub, with the hands-on post listed first so a new reader's
default click is the practical one.

## Proposed post

### Metadata

- **Path:** `docs/blog/posts/hello-sase-your-first-15-minutes.md`
- **Slug:** `hello-sase-your-first-15-minutes` (URL becomes `/blog/hello-sase-your-first-15-minutes/`)
- **Date:** today (2026-05-10)
- **Categories:** `Agentic Software Engineering`, `Getting Started`
- **Frontmatter `links`:** ACE guide, SDD guide, the launch essay, the series hub, GitHub repo
- **Working title (recommended):** _Hello, SASE: Your First 15 Minutes Orchestrating Coding Agents_
  - Alternates: _Your First Agent Run With SASE_, _From `pip install` To Your First ChangeSpec_

### Audience and tone

- Audience: a developer who already uses at least one coding-agent CLI (Claude Code, Codex, Gemini CLI, Qwen, OpenCode)
  and is curious whether SASE is worth a Saturday afternoon. Comfortable in a terminal, comfortable with `uv` / `just`.
- Tone: matches the existing essay (clear, declarative, low marketing). Short paragraphs. Real commands the reader can
  copy.
- Length target: ~1,000–1,400 words (roughly 6–8 minute read), shorter than the launch essay so the on-ramp feels light.

### Structure

A tour shaped like the actual user journey, with one section per phase. Each section has a "what just happened"
paragraph that names the SASE component the reader just touched and links to its full guide.

1. **Lede (3–4 sentences).** What SASE is in one breath ("a coordination layer above coding-agent CLIs"), what this post
   will accomplish, and a `<!-- more -->` cut after the lede so the blog index excerpt stays clean.

2. **Step 1 — Install (≈90 seconds).**
   - Prereqs (Python 3.12+, `uv`, `just`).
   - The Quick Start block from the README, verbatim, with one extra line: `sase --help` to confirm.
   - "What you just did": installed the `sase` CLI plus the required `sase_core_rs` Rust extension.
   - Link out: install troubleshooting in `development.md`.

3. **Step 2 — Launch your first agent (≈3 minutes).**
   - One command: `sase run "<small task prompt>"` (use a tiny, safe task, e.g. _"add a docstring to the most recent
     function I edited"_ — pick one that produces a visible diff without external dependencies).
   - Note that `sase run` allocates an isolated `sase_<N>` workspace (clone of the repo) so the agent never edits the
     reader's working tree directly.
   - "What you just did": dispatched a coding-agent run inside an ephemeral **workspace**, tracked as a SASE **agent
     record** with its own artifacts directory.
   - Links out: workspaces guide (`workspace.md`), CLI reference (`cli.md`).

4. **Step 3 — Open ACE and find the result (≈3 minutes).**
   - `sase ace` to open the TUI.
   - Walk through the three tabs (CLs / Agents / Axe) at a high level, showing where to find:
     - the new **ChangeSpec** that wraps the agent's commit (CLs tab) — name, status, commits, diff;
     - the **agent record** with prompt + reply transcript (Agents tab);
     - the **AXE daemon** ticking in the background (Axe tab) — mention that ACE auto-starts AXE.
   - Two screenshots reused from existing assets if available (`docs/images/sase_tui_tabs_infographic.png` is already on
     the home page) — see "Images" section below.
   - "What you just did": observed a `sase run` produce a durable **ChangeSpec** (CL/PR-sized review state) and a
     persistent **agent artifact**, both visible in **ACE**, with **AXE** handling background lifecycle work.
   - Links out: ACE guide (`ace.md`), ChangeSpec guide (`change_spec.md`), AXE guide (`axe.md`).

5. **Step 4 — Reuse the prompt as an XPrompt (≈3 minutes).**
   - Show how to wrap the same prompt in a tiny `xprompts/docstring.md` so the next run is `sase run "#docstring"`.
   - Mention typed inputs and YAML workflow form in one sentence; don't dive in.
   - "What you just did": turned a one-off prompt into a reusable **XPrompt**, the smallest unit of repeatable agent
     work in SASE.
   - Links out: XPrompts guide (`xprompt.md`), workflow specs (`workflow_spec.md`).

6. **Step 5 — Plan bigger work with SDD and Beads (≈3 minutes).**
   - Briefly: when the task is too big for one run, write a plan, file it as a **bead**, and let
     `sase bead work <epic-id>` schedule the phase agents in dependency order.
   - One short snippet: `sase bead onboard`, `sase bead ready`, `sase bead show <id>`.
   - "What you just did": stepped from one-shot prompts into **Spec-Driven Development** with **Beads** as
     dependency-aware work units.
   - Links out: SDD guide (`sdd.md`), Beads guide (`beads.md`).

7. **The component map (recap).**
   - A compact list (or small two-column table) recapping every component the reader just touched, plus the ones they
     did _not_ touch but should know exist:
     - **ACE** — TUI control surface.
     - **AXE** — background automation daemon.
     - **`sase run`** — launch agents and workflows.
     - **Workspaces** — isolated `sase_<N>` clones for parallel work.
     - **ChangeSpecs** — durable CL/PR-sized review state.
     - **Beads** — dependency-aware work units; powers epic execution.
     - **XPrompts** — reusable prompt templates and YAML workflows.
     - **SDD** — plans, epics, and legends as first-class artifacts on disk.
     - **Plugins / Providers** — model and VCS providers behind a common boundary (Claude Code, Gemini CLI, Codex, Qwen,
       OpenCode; bare git, GitHub).
   - Each item is a one-line description plus a link to the full guide. This is the "you now know the vocabulary"
     payoff.

8. **What to read next.**
   - The launch essay (`why-coding-agents-need-orchestration.md`) for the _why_.
   - The series hub for the planned ChangeSpecs / Beads / XPrompts / ACE+AXE essays.
   - The CLI reference for breadth.
   - GitHub repo for issues and source.

9. **Series navigation footer.**
   - Mirror the footer style of the launch essay so the two posts feel like part of one track. Recommended wording:
     "This is a hands-on companion to the
     [Agentic Software Engineering series](../../series/agentic-software-engineering.md)."

### Component coverage checklist

The post must mention every item below at least once with a link to its guide. This is the "all of the most important
components" bar from the user's request:

- [ ] `sase` CLI install / `sase --help`
- [ ] `sase run`
- [ ] Ephemeral `sase_<N>` workspaces
- [ ] ACE (the TUI)
- [ ] AXE (the background daemon)
- [ ] ChangeSpecs
- [ ] Agent records / artifacts
- [ ] XPrompts (and a sentence on YAML workflows)
- [ ] Beads
- [ ] SDD (plans / epics / legends)
- [ ] Provider / plugin abstraction (one sentence naming supported model + VCS providers)
- [ ] Pointer to the launch essay and the series hub

### Images

Reuse what already exists; do not generate new assets in this post:

- `docs/images/sase_overview.png` (top-of-post hero, optional — also used on home page).
- `docs/images/sase_tui_tabs_infographic.png` for Step 3 (ACE tabs).
- Optionally `docs/images/sase-component-communication.png` near the component recap.

If a screenshot of the actual ACE CLs tab with a fresh ChangeSpec would help and one already exists in `docs/images/`,
prefer it; otherwise omit rather than invent.

## Cross-cutting changes outside the post

To make sure the new post is the default first click and not buried below the existing essay:

1. **`docs/blog/index.md`** — promote the new post above the launch-essay link in the "Start With The Launch Series"
   section (or rename that section to "Start Here" and list the hands-on post first, the launch essay second).
2. **`docs/index.md`** — replace the primary `md-button--primary` "Read the launch essay" CTA with a "Start in 15
   minutes" CTA pointing at the new post; keep the launch-essay link as a secondary button. The "Read the launch essay"
   card near the bottom can stay.
3. **`docs/series/agentic-software-engineering.md`** — add a row above the current post #1 (or a "Start here" callout
   above the table) pointing at the hands-on post. Do **not** renumber the existing series entries; the hands-on post is
   positioned as the practical on-ramp, the launch essay remains series post #1.

These three edits are small and self-contained; doing them in the same PR keeps the post discoverable from day one.

## Out of scope

- Rewriting `docs/index.md` beyond the CTA swap.
- Editing or restructuring the existing launch essay.
- Adding a new docs page (e.g. a stand-alone "Getting Started" page under `docs/`). Everything goes in the blog post,
  with deep links to existing docs.
- Generating new images or infographics. Reuse `docs/images/` assets only.
- Adding a new top-level nav entry in `mkdocs.yml`. The blog plugin already handles post routing.
- Writing the next planned essays in the series (ChangeSpecs / Beads / XPrompts / ACE+AXE). Those are separate posts.

## Verification

1. `just docs-check` — strict MkDocs build catches broken links, missing frontmatter, and the like.
2. `just docs-pdf-check` — handbook PDF build, since the new post will be included.
3. Eyeball the blog index (`docs/blog/index.md`) and series hub renders to confirm the new post is listed first / above
   the existing essay.
4. Confirm the post's frontmatter `links` resolve (each `links:` entry is a real path under `docs/`).
5. Read the post end-to-end and copy each shell command into a fresh shell to confirm it actually works on a clean
   checkout — the entire premise of the post is that the commands run as printed.
6. Run `just check` after edits, per repo memory.
