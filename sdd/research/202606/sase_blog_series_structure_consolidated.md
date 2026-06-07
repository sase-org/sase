---
create_time: 2026-06-07
updated_time: 2026-06-07
status: research
---

# SASE Blog Series Structure - Consolidated Research

## Question

Bryan originally planned roughly ten SASE blog posts, then became unsure whether that is too many. What series length and
topic structure should SASE use for a public technical blog series?

This note consolidates and verifies the two prior research drafts:

- `sdd/research/202606/sase_blog_series_structure_research.md`
- `sdd/research/202606/blog_series_count_and_structure.md`

## Bottom Line

Use **six promoted public posts**, not a ten-part serial.

Launch around a small core: the thesis essay, the quickstart, and the ChangeSpecs differentiator. Then drip three
evergreen deep-dives as a topic cluster. Keep the remaining draft material, but move it into docs, optional integration
posts, or a living roadmap instead of treating every draft as a promoted episode.

The important reframe is: separate **how much has been written** from **how much should be launched and serialized**.
The ten drafts are useful. The mistake would be asking readers to commit to a numbered ten-post feature tour before they
understand the problem SASE solves.

## Verification Notes

Verified locally on 2026-06-07:

- `docs/blog/posts/` contains ten posts, `[00]` through `[09]`.
- Only `[00] Why Coding Agents Need Orchestration` is currently non-draft.
- `[01]` through `[09]` are `draft: true`.
- `docs/series/agentic-software-engineering.md` publicly lists only `[00]` and says the rest are forthcoming.
- Existing launch research already warns against framing SASE as a large numbered series.
- Existing install/readiness research says the quickstart should not become the main conversion path until the public
  install path is current and smoke-tested.

I also rechecked the external sources most relevant to the recommendation:

- HN's Show HN rules say blog posts and other reading material are not Show HN material; submit the essay normally and
  save Show HN for a tryable product/repo launch.
- HN's guidelines discourage promotional titles, gratuitous numbers, and solicitations.
- Diataxis separates tutorial, how-to, reference, and explanation; the blog should not duplicate reference docs in essay
  form.
- Google's technical writing guidance emphasizes writing for the audience's current knowledge and avoiding the curse of
  knowledge.
- MDN emphasizes clarity, concision, consistency, logical progression, and relevant examples.
- OpenAI's harness-engineering post supports the market direction behind SASE: agent work benefits from repository-local,
  versioned plans, artifacts, constraints, and feedback loops.
- DEV and Hashnode both support canonical/source URL workflows, so `sase.sh` can remain canonical while selected posts
  are syndicated later.

## Current Draft Inventory

| Current draft | Public role | Recommendation |
| --- | --- | --- |
| `[00] Why Coding Agents Need Orchestration` | Problem essay | Keep as Post 1 and primary launch submission. |
| `[01] Hello, SASE - Your First 15 Minutes` | Quickstart | Keep as Post 2, but publish only when install/readiness is true. |
| `[02] XPrompts in Depth` | Prompt/workflow deep-dive | Keep, retitle around "Prompts as Code." |
| `[03] AXE` | Background automation | Merge into the execution/landing post. |
| `[04] Beads and SDD` | Planning/dependencies | Keep, retitle around work that lands. |
| `[05] Commit Workflows` | Diff-to-commit/PR flow | Merge into the execution/landing post. |
| `[06] ChangeSpecs` | Review state outside chat | Promote as the launch differentiator. |
| `[07] Telegram Mobile Agents` | Optional control surface | Move to docs or one later optional integration post. |
| `[08] Prompt Widget and sase-nvim` | Optional editor/control surface | Move to docs or merge with `[07]`. |
| `[09] What's Next` | Roadmap | Convert to living roadmap or end-of-series recap. |

## Research Synthesis

### A ten-part serial is the wrong shape

The drafts are not too long; the public commitment is too large. A ten-post numbered sequence signals homework. It also
turns SASE's launch into a list of internal nouns: XPrompts, AXE, SDD, beads, ChangeSpecs, commit workflows, Telegram,
nvim, and roadmap. Those concepts are real, but new readers should first see a problem, a first run, and one sharp proof
of differentiation.

The series should behave like a hub-and-spoke cluster:

- the pillar explains why orchestration exists;
- the quickstart converts interest into a first run;
- each follow-up answers one reader question and can stand alone;
- detailed command tables and subsystem internals stay in docs.

### ChangeSpecs should be promoted, not buried

The two prior drafts disagreed on ChangeSpecs:

- one folded ChangeSpecs into a broader "from diff to reviewable change" post;
- the other promoted ChangeSpecs as a launch-core differentiator.

Final resolution: **promote ChangeSpecs as a standalone post**, but frame it in reader language. "The Durable Unit of
Agent Work" is stronger than a product-noun tour because it explains why SASE is different from agents in tmux panes or
plain worktrees: state survives the chat, review data lives on disk, mentors and comments attach to a durable record, and
commits/PRs have a place to land.

To avoid duplication, keep AXE and commit workflows together in a separate "Engine Room" post about background execution
and landing code. That post can point at ChangeSpecs without re-explaining the whole format.

### The quickstart is valuable, but readiness-gated

The quickstart is the highest-conversion post in the set, but it is also the most dangerous to publish too early. The
current readiness research says public PyPI/source install state is not yet stranger-ready. If a reader follows the
launch essay and immediately hits a stale install path, the whole series loses credibility.

Therefore:

- keep the quickstart one click from the thesis essay;
- do not make `pip install sase` or `uv tool install sase` the blog CTA until the current release is published and
  smoke-tested;
- if launch happens before that, label the setup as a source checkout path and be explicit about prerequisites.

### Optional surfaces are not launch pillars

Telegram, prompt widget, `sase-nvim`, mobile gateway work, and future web/memory surfaces matter for power users, but
they are weaker as early public posts. They answer "where can I operate SASE from?" after the reader already accepts the
core model. For launch, they should become docs pages or one later optional integration post.

### A comparison post is still missing

Neither current draft directly answers the high-intent comparison question: "Why not just run agents in tmux, worktrees,
or a dashboard?" Existing competitor-audit research can support that later. It should not block the six-post plan, but a
future comparison post would likely convert better than another subsystem tour.

## Decision Criteria

A promoted SASE blog post should pass all four tests:

1. It moves the reader to a new state: believes the premise, tries SASE, understands the durable work unit, reuses a
   workflow, plans multi-agent work, or understands how agent output lands.
2. It can stand alone when shared on HN, DEV, Hashnode, Reddit, LinkedIn, or directly.
3. It has a proof artifact: a command, workflow snippet, ChangeSpec example, bead queue, screenshot, or before/after
   failure mode.
4. It is not just reference documentation in essay form.

Under those criteria, six posts are enough to prove the system while keeping the launch focused.

## Recommended Blog Series Structure

### Tier 1 - Launch Core

Promote these hardest. The external launch should lead with Post 1; Post 2 must be one click away; Post 3 should be ready
as the first differentiator proof inside the launch window.

1. **Why Coding Agents Need Orchestration**

   The flagship problem essay. Show the failure modes of one-off coding-agent sessions: lost intent, workspace
   collisions, fragile handoffs, missing review state, unclear dependencies, and commit chaos. Introduce SASE as the
   durable operating layer around existing agent CLIs, not as another coding agent.

2. **Hello, SASE - Your First 15 Minutes**

   The conversion post. Walk a stranger through the smallest honest first run: install or source setup, explicit
   workspace target, one agent launch, where the result appears in ACE, and what artifact proves the run was tracked.
   Publish this only when the public install path is true or the source-install caveat is explicit.

3. **ChangeSpecs - The Durable Unit of Agent Work**

   The differentiator showpiece. Explain how review state survives outside chat: ChangeSpecs, status, comments, mentors,
   commits, proposals/PRs, and ACE operations all attach to one durable record. This is the clearest answer to "why not
   just run agents in worktrees?"

### Tier 2 - Evergreen Deep-Dives

Publish these as self-contained cluster posts, not "episodes." Weekly is a reasonable default, but feedback from the
launch should be allowed to change order or wording.

4. **Prompts as Code - From One File to Full Workflows**

   The reusable-workflow post. Explain XPrompts as the bridge from shell-history prompts to versioned workflow assets:
   Markdown prompts, typed inputs, directives, multi-agent fanout, YAML workflows when needed, and plugin-shipped
   defaults. Keep it example-driven and link the full reference.

5. **Planning Work That Lands - Beads, SDD, and Multi-Agent Fan-Out**

   The planning/dependency post. Show how approved plans become durable files, how epics become phase beads, how
   dependencies produce ready/blocked queues, and how `sase bead work` turns a plan into ordered agent execution. This is
   the main "more than a pile of worktrees" planning story.

6. **The Engine Room - How Agents Run in the Background and Land Code**

   The execution/landing post. Merge the AXE and commit-workflow drafts into one reader question: how does work keep
   moving and land without babysitting? Cover AXE, hooks, waits, mentors, conflict/resume, commit workflows, VCS plugins,
   proposals/PRs, and `commit_result.json`, while linking back to ChangeSpecs for review state.

### Not Promoted as Core Blog Posts

These are useful, but should not expand the launch series:

- **Operating SASE Beyond the Terminal** - merge Telegram, prompt widget, `sase-nvim`, notifications, and mobile gateway
  into docs or one later optional integration post.
- **What's Next - Shared Memory, Mobile, and Web** - maintain as a roadmap page or use once as a recap after the core
  posts have shipped.
- **SASE vs. Agents in Tmux, Worktrees, and Dashboards** - consider writing later as a comparison post using the
  competitor audit research.

## Publishing Notes

- Drop `[00]`...`[09]` from public titles. Numbered titles signal the ten-part serial you are trying to avoid.
- Keep a series hub, but organize it by reader path: Start here, Try it, Durable work, Reusable workflows, Planning,
  Execution.
- Do not submit a blog post as `Show HN`; submit the thesis essay as a regular HN link with a plain title.
- Save `Show HN: SASE` for a later product/repo launch when strangers can try it without friction.
- Use `sase.sh` as canonical. Syndicate only selected posts to DEV/Hashnode with canonical URLs set.
- Treat each post as a feedback checkpoint. If HN, GitHub issues, or direct readers show confusion, patch docs and the
  next post before continuing.

## Sources

Internal:

- `docs/blog/posts/`
- `docs/series/agentic-software-engineering.md`
- `sdd/research/202605/blog_series_deep_research.md`
- `sdd/research/202606/sase_blog_launch_strategy_consolidated.md`
- `sdd/research/202606/sase_hacker_news_popularity_strategy_consolidated.md`
- `sdd/research/202606/sase_install_use_understand_readiness_consolidated.md`
- `sdd/research/202606/open_source_sase_competitor_audit.md`

External:

- [Show HN Guidelines](https://news.ycombinator.com/showhn.html)
- [Hacker News Guidelines](https://news.ycombinator.com/newsguidelines.html)
- [Diataxis](https://diataxis.fr/)
- [Google Technical Writing: Audience](https://developers.google.com/tech-writing/one/audience)
- [MDN: Creating effective technical documentation](https://developer.mozilla.org/en-US/blog/technical-writing/)
- [OpenAI: Harness engineering](https://openai.com/index/harness-engineering/)
- [DEV Help: Writing, Editing and Scheduling](https://dev.to/help/writing-editing-scheduling)
- [Hashnode: How to Set a Canonical Link](https://docs.hashnode.com/help-center/hashnode-editor/how-to-set-a-canonical-link)
