# SASE Blog Series — How Many Posts, and Which Topics?

Date: 2026-06-07

## Question

The original plan was **ten blog posts, posted individually**. That now feels like a lot. How many posts should the
series actually be, and what should they cover? This note researches the decision and ends with a recommended series
structure (named posts + short descriptions).

## TL;DR Recommendation

**Don't post ten things in a row. Restructure from a 10-part serial into a hub-and-spoke cluster, and only *launch* a
small core.**

- **Launch 3 posts** as real "events" you actively promote: the problem essay (pillar), the 15‑minute quickstart, and
  one showpiece that demonstrates the core differentiator end to end.
- **Drip 3 evergreen deep-dives** over the following weeks as the topic cluster around the pillar — low-pressure, no
  "episode N of 10" framing.
- **Demote 2–3 of the existing drafts to documentation pages** (or merge them), not standalone promoted posts.

Net: **~6 promoted blog posts (only 3 of them launch-day), down from 10**, with nothing you already wrote thrown away.

The key reframe: separate **how much you *wrote*** from **how much you *launch and serialize*.** All ten drafts are
useful. The mistake is treating all ten as sequential blog "episodes" that a reader is expected to follow in order.

## Current State (what already exists in the repo)

`docs/blog/posts/` already contains **ten drafted posts**. Only `[00]` is published; the rest are `draft: true`:

| # | File / Title | Words | Role |
| --- | --- | ---: | --- |
| 00 | Why Coding Agents Need Orchestration | 965 | Problem essay (the "why") — **published** |
| 01 | Hello, SASE — Your First 15 Minutes | 1399 | Hands-on quickstart (the "try it") |
| 02 | XPrompts in Depth — From One File to Full Workflows | 1461 | Feature deep-dive: prompt language |
| 03 | AXE — The Background Daemon | 1125 | Feature deep-dive: scheduler |
| 04 | Beads and SDD — Planning Multi-Agent Work | 1201 | Feature deep-dive: planning |
| 05 | Commit Workflows — Diff to PR | 1379 | Feature deep-dive: commit/PR pipeline |
| 06 | ChangeSpecs in Practice — Review State Outside the Chat | 1384 | Feature deep-dive: **the differentiator** |
| 07 | Driving SASE From Your Phone — Telegram | 1766 | Integration/surface: mobile |
| 08 | Where You Type — Prompt Widget and sase-nvim | 1694 | UI/editor detail (narrowest audience) |
| 09 | What's Next — Shared Memory, Mobile, Web | 963 | Roadmap |

So the "ten posts" already exist as drafts. The decision is not *whether to write them* — it's **how to package,
promote, and sequence them.**

This builds on prior in-repo research that should be read alongside this note:

- [`blog_series_deep_research.md`](../202605/blog_series_deep_research.md) — platform/hosting (MkDocs + sase.sh).
- [`sase_blog_launch_strategy_consolidated.md`](sase_blog_launch_strategy_consolidated.md) — canonical-first launch
  sequence, HN strategy, positioning. **Already warns against the "11-part blog series" framing.**
- [`sase_hacker_news_popularity_strategy_consolidated.md`](sase_hacker_news_popularity_strategy_consolidated.md)
- [`sase_install_use_understand_readiness_consolidated.md`](sase_install_use_understand_readiness_consolidated.md)

## What the Research Says

### 1. Serialized series bleed readers; hub-and-spoke clusters don't

Serialized content "loses steam faster than episodic content when there are long gaps between episodes, because the
audience forgets where the story left off." To hold a narrative serial together you need a **tight cadence (2–3×/week)** —
which is a brutal pace to sustain for ten technical posts.

Pillar/cluster content behaves the opposite way: it's **always available and navigable**, each page links to related
ones, and engagement comes from internal linking and structure rather than the reader remembering "episode 4." That's a
much better fit for an evergreen developer-tool reference that should still onboard people a year from now.

**Implication:** a strict 10-part serial is the *worst* shape for this content. A pillar essay + a cluster of linked
deep-dives is the *best* shape.

### 2. DevTool marketing rewards focus over volume

Across multiple early-stage devtool/OSS marketing playbooks the consistent advice is **focused iteration over volume** and
**quality over quantity** — "choose a few tactics… and optimize those before expanding." Fewer substantial pillars
outperform many thin posts. The highest-converting formats are:

- **Step-by-step how-to / quickstart guides** ("the most durable content format in developer marketing").
- **Comparison / "X vs Y" posts** (high-intent search).
- **Integration-focused tutorials** with tools devs already use.

Note what's *not* on that list: long internal-architecture tours (AXE process model, the prompt-input widget). Those are
great **documentation**, but weak **launch** content — they're for people who are already sold.

### 3. Post length: the drafts are already right-sized

Guidance converges on **~1,500–2,500 words** for in-depth technical posts, and "match length to intent" over chasing word
counts. The existing drafts (≈960–1,770 words) are already in a healthy range; the problem is **count and sequencing, not
length.** Time-sensitive launch posts should stay tight and lead with the point.

### 4. The launch itself is a sequence, not a dump

Standard devtool launch timelines stage content over ~6–8 weeks and **lead with fundamentals** (README, docs, quickstart)
before fanning out into tutorials and comparison content. This matches the in-repo launch strategy doc: lead with one
sharp essay, keep the quickstart one click away, and treat each channel as a feedback surface — **not** "we published 10
posts today."

## The Decision: How Many?

**Six promoted posts, organized as a hub + cluster, with only three launched as events.** Here's the reasoning by tier.

### Why not keep all 10 as a serial?
- Ten sequential "episodes" demand a cadence you can't sustain and a reader commitment almost no one makes.
- Two of the ten ([08] prompt widget/nvim, parts of [07] Telegram) are narrow-audience internals — excellent docs, weak
  blog draws.
- The in-repo launch research already says to avoid the "N-part series" framing because **the reader's problem matters
  more than your content volume.**

### Why not cut down to just 1–2?
- SASE's differentiation is genuinely a *system* (durable work units + planning + scheduling + provider-neutral commit).
  One essay can't carry that; you need a few spokes to prove the pillar's claim.
- The content is already written. Discarding 8 finished drafts is pure waste.

### The middle path (recommended)
Promote a **small, sharp core**, keep the rest as an **always-available cluster**, and **fold the two narrowest drafts
into docs.** This cuts the *promotion* surface roughly in half while preserving every draft as durable, navigable
content.

## Recommended Series Structure

### Tier 1 — The Launch Core (3 posts, promoted as events)

These three get the highest polish, social cards, and active distribution (HN, DEV, LinkedIn, X). They must stand alone
and cross-link tightly.

1. **Why Coding Agents Need Orchestration** *(the pillar — keep `[00]` ~as-is)*
   The flagship problem essay: a coding agent can produce a patch, but real work needs durable plans, state, review,
   dependencies, retries, and handoff. This is the post you submit to Hacker News and link from the README. Everything
   else is a spoke off this hub.

2. **Hello, SASE — Your First 15 Minutes** *(the on-ramp — keep `[01]`)*
   The hands-on quickstart: install, launch your first agent, find the resulting ChangeSpec in ACE, learn the vocabulary.
   Always one click from the pillar and from every announcement. This is the highest-converting format in devtool
   marketing, so it must be flawless on a clean machine.

3. **ChangeSpecs — The Durable Unit of Agent Work** *(the showpiece — promote `[06]`, lead with the differentiator)*
   The single best proof of the pillar's thesis: review state that lives on disk and survives the chat, with mentors,
   commits, and status that ACE operates on. This is SASE's sharpest "this is what makes it different from running agents
   in tmux panes" story, so it belongs in the launch core rather than buried mid-serial.

### Tier 2 — Evergreen Deep-Dives (3 posts, dripped weekly after launch)

Published as the topic cluster around the pillar. No "episode N" pressure — each is a self-contained reference that earns
its own search traffic. Release one per week (or whenever ready) over the following month.

4. **Prompts as Code — From One File to Full Workflows** *(keep `[02]` XPrompts)*
   How a reusable `#tag` grows from a single Markdown file to typed inputs, directives, multi-agent fan-out, and only-
   when-you-need-them YAML workflows. The "authoring" story — how operators actually drive SASE day to day.

5. **Planning Work That Lands — Beads, SDD, and Multi-Agent Fan-Out** *(keep `[04]`)*
   How plans become durable artifacts (tales/epics/legends), how those turn into dependency-ordered beads, and how one
   command turns an epic into a multi-agent run. The "how big work gets split and ordered" story.

6. **The Engine Room — How Agents Run in the Background and Land Their Code** *(merge `[03]` AXE + `[05]` Commit Workflows)*
   The execution engine: AXE's background daemon (hooks, mentors, dependency unblocking) plus the runtime-uniform
   commit→proposal→PR pipeline that lands a diff without the agent caring which VCS is underneath. Merging these two
   drafts answers one reader question — "how does work actually get done and committed without me babysitting?" — and
   removes a post from the count. (Keep them separate only if you want two shorter, more focused references.)

### Tier 3 — Demote to Docs / Optional (not promoted blog posts)

7. **Operating SASE Beyond the Terminal** *(optional — merge `[07]` Telegram + `[08]` nvim, or move both to docs)*
   The "surfaces" story: drive SASE from a Neovim buffer or from a Telegram chat on your phone. Narrow audiences, better
   as documentation pages or a single optional integration post than as two launch-day blog events. Publish later, if at
   all, once the core series has traction.

8. **What's Next — Shared Memory, Mobile, and the Web** *(convert `[09]` to a living roadmap page or use as series recap)*
   Roadmap content goes stale fast and reads as promotional in a launch slot. Make it a maintained `/roadmap` page that
   you update, or use it once as an end-of-series recap post pinned from the README — not a mid-series episode.

### At a glance

| Tier | Post | Source draft(s) | Promote? |
| --- | --- | --- | --- |
| 1 | Why Coding Agents Need Orchestration | `[00]` | Launch event (HN) |
| 1 | Hello, SASE — Your First 15 Minutes | `[01]` | Launch event |
| 1 | ChangeSpecs — The Durable Unit of Agent Work | `[06]` | Launch event |
| 2 | Prompts as Code | `[02]` | Weekly drip |
| 2 | Planning Work That Lands | `[04]` | Weekly drip |
| 2 | The Engine Room | `[03]` + `[05]` merged | Weekly drip |
| 3 | Operating SASE Beyond the Terminal | `[07]` + `[08]` | Docs / optional |
| 3 | What's Next | `[09]` | Roadmap page / recap |

## Practical Notes

- **Renumber by tier, not by a 1–10 serial.** The `[00]`…`[09]` numbering in the titles signals "10-part serial" — the
  exact framing the launch research says to avoid. Consider dropping numeric prefixes from titles and letting the series
  hub define reading order, so each post reads as a standalone reference.
- **The series hub page is the spine.** A single `/series/agentic-software-engineering/` hub (already planned) with a
  clear "Start here → pillar, then quickstart" and a grouped list of deep-dives gives you cluster benefits without serial
  fragility.
- **One comparison post is missing and would convert well.** The research repeatedly flags "X vs Y" as high-intent. A
  future "SASE vs. running agents in tmux/worktrees" post (drawing on the existing competitor-audit research) would slot
  naturally into Tier 2 and is worth writing even though it isn't among the current ten drafts.
- **Cadence:** launch the 3-post core together (pillar + quickstart one click away, ChangeSpecs ready as the first
  follow-up), then drip Tier 2 weekly. Don't gate the launch on all six being perfect.

## Sources

External:

- [How long should a blog post be? (Semrush)](https://www.semrush.com/blog/how-long-should-a-blog-post-be/)
- [Ideal length for a technical blog post (DEV)](https://dev.to/scrabill/what-is-the-ideal-length-for-a-technical-blog-post-26po)
- [How to build a signature content series (Later)](https://later.com/blog/how-to-build-a-signature-content-series/)
- [Content pillars (Neil Patel)](https://neilpatel.com/blog/content-pillars/)
- [Developer marketing guide (markepear)](https://www.markepear.dev/blog/developer-marketing-guide)
- [Early-stage devtools & OSS marketing playbook (Decibel)](https://www.decibel.vc/articles/developer-marketing-and-community-an-early-stage-playbook-from-a-devtools-and-open-source-marketer)
- [Dev tool go-to-market / launch sequence (daily.dev)](https://business.daily.dev/resources/dev-tool-companies-go-to-market-strategy-launch-scale/)
- [DevTools content marketing strategies (SaaS Hero)](https://www.saashero.net/content/devtools-content-marketing-strategies/)

Internal (read alongside):

- `sdd/research/202605/blog_series_deep_research.md`
- `sdd/research/202606/sase_blog_launch_strategy_consolidated.md`
- `sdd/research/202606/sase_hacker_news_popularity_strategy_consolidated.md`
- `sdd/research/202606/sase_install_use_understand_readiness_consolidated.md`
- `sdd/research/202606/open_source_sase_competitor_audit.md`
</content>
</invoke>
