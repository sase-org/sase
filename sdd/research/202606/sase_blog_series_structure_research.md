---
create_time: 2026-06-07
updated_time: 2026-06-07
status: research
---

# SASE Blog Series Structure Research

## Question

Bryan originally planned roughly ten SASE blog posts, then became unsure whether that is too many. What series length and
topic structure should SASE use for a public technical blog series?

## Short Answer

Use a six-post public series, not ten.

Publish the first two as the launch on-ramp: one thesis essay and one quickstart. Then publish four focused follow-ups
that compress the product surface into reader journeys:

1. why orchestration exists;
2. how to try SASE;
3. how prompt logic becomes reusable workflow infrastructure;
4. how plans become dependency-aware work;
5. how agent output becomes reviewable, landed change;
6. where operators use SASE and where the system is headed.

This keeps the series substantial enough to explain SASE's actual differentiation, but avoids a feature-by-feature tour
that asks readers to care about every internal noun before they have felt the problem.

## Local Findings

### Current repo state

Observed in this workspace on 2026-06-07:

- `docs/blog/posts/` contains ten posts: `[00]` through `[09]`.
- Only `[00] Why Coding Agents Need Orchestration` is non-draft.
- `[01]` through `[09]` all have `draft: true`.
- The current draft topics are:
  - quickstart;
  - XPrompts;
  - AXE;
  - Beads and SDD;
  - commit workflows/plugins;
  - ChangeSpecs;
  - Telegram/mobile;
  - prompt widget and `sase-nvim`;
  - roadmap.

Existing local launch research already warns against launching as "an 11-part blog series" and recommends leading with
one sharp problem essay plus a quickstart:

- `sdd/research/202606/sase_blog_launch_strategy_consolidated.md`
- `sdd/research/202606/sase_hacker_news_popularity_strategy_consolidated.md`
- `sdd/research/202606/sase_install_use_understand_readiness_consolidated.md`

The install/readiness research is especially important: the quickstart should not become the public conversion artifact
until the current release and install path are stranger-ready.

### Prior SDD history

The blog structure has already swung between two poles:

- `sdd/tales/202605/blog_series_two_posts.md` reframed the site around only two public posts: thesis plus quickstart.
- `sdd/tales/202605/new_blog_posts.md` then planned six additional subsystem posts.

That history explains the current tension. Two posts are too thin to preserve SASE's real technical differentiation,
but ten posts turn the launch into a feature inventory. The best compromise is not halfway by count; it is a tighter
reader journey that merges adjacent subsystem posts.

## External Findings

### Hacker News launch constraints

HN's official Show HN rules say blog posts and other reading material should be regular submissions, not Show HN
submissions, because they cannot be tried directly. Show HN is a better fit later when the product/repo/quickstart is
easy for strangers to run.

HN's general guidelines also favor original sources, plain titles, no hype, no gratuitous numbers, no soliciting, and
human-written comments. For SASE this means:

- submit the thesis essay as `Why Coding Agents Need Orchestration`, without `[00]`;
- do not make "ten-part series" or "six-part series" the hook;
- use the series page as navigation, not as the launch pitch;
- save `Show HN: SASE` for a tryable product launch.

Sources:

- [Show HN Guidelines](https://news.ycombinator.com/showhn.html)
- [Hacker News Guidelines](https://news.ycombinator.com/newsguidelines.html)

### Category saturation

Recent HN examples show that "parallel coding agents in worktrees" is now a crowded pitch:

- [Emdash](https://news.ycombinator.com/item?id=47140322) positioned itself as a provider-agnostic desktop app for
  parallel coding agents in isolated worktrees and drew meaningful discussion.
- [Optio](https://news.ycombinator.com/item?id=47520220) positioned around ticket-to-merged-PR orchestration in
  Kubernetes, including CI/review feedback loops.
- [Stoneforge](https://news.ycombinator.com/item?id=47267105), `wt`, `agent-worktree`, `20x`, `Foolery`, and similar
  launches all use overlapping language around worktrees, agents, tickets, dashboards, and orchestration.

The implication: SASE should not spend many separate posts proving that it can run multiple agents. The series should
lead with what competitors often flatten:

- durable plans and approved intent;
- dependency-aware work queues;
- review records outside chat;
- provider-neutral commit/PR flow;
- background automation and resumable handoff;
- local-first, repo-linked artifacts.

### Agent-first engineering context

OpenAI's 2026 "Harness engineering" post validates the market direction behind SASE's thesis: once agents are useful,
the work shifts toward environments, specifications, repo-local knowledge, feedback loops, architectural constraints,
and human steering. The post also argues that knowledge outside agent-accessible context effectively does not exist for
the running agent, which supports SASE's emphasis on SDD artifacts, ChangeSpecs, beads, memory, and executable workflow
state.

Source:

- [Harness engineering: leveraging Codex in an agent-first world](https://openai.com/index/harness-engineering/)

### Technical content principles

The blog should not duplicate the reference docs. Diataxis separates tutorials, how-to guides, reference, and
explanation; blog posts for SASE should mostly be explanation plus one or two runnable/tutorial moments, while detailed
command and subsystem coverage stays in docs.

Google's technical writing guidance frames good documentation as the difference between what the audience needs to do a
task and what they already know. For SASE, the likely first public audience already knows coding agents and git, but
does not know SASE's internal vocabulary. A long sequence of posts named after product nouns will trigger the curse of
knowledge.

MDN's technical writing guidance emphasizes clarity, conciseness, and consistency. That argues for fewer, stronger posts
with stable mental models, not ten separate pieces that each introduce new terms.

Sources:

- [Diataxis](https://diataxis.fr/)
- [Google Technical Writing: Audience](https://developers.google.com/tech-writing/one/audience)
- [MDN: Creating effective technical documentation](https://developer.mozilla.org/en-US/blog/technical-writing/)

### Syndication and canonical URLs

DEV and Hashnode both support canonical/source URL workflows, so the SASE-owned blog can remain the canonical source
while selected posts are syndicated later.

The practical implication for structure: every post should be strong enough to stand alone on a distribution channel.
If a post only makes sense because someone has already read five previous subsystem posts, it belongs in docs or should
be merged.

Sources:

- [DEV Help: Writing, Editing and Scheduling](https://dev.to/help/writing-editing-scheduling)
- [Hashnode: How to Set a Canonical Link](https://docs.hashnode.com/help-center/hashnode-editor/how-to-set-a-canonical-link)

## Decision Criteria

A public SASE blog post should pass all four tests:

1. It moves the reader to a new state: believes the premise, tries SASE, reuses a workflow, plans agent work, reviews
   landed output, or understands the roadmap.
2. It can stand alone when shared on HN, DEV, Hashnode, Reddit, LinkedIn, or a direct link.
3. It has a concrete proof artifact: a command, screenshot, workflow snippet, ChangeSpec example, bead queue, or
   before/after failure mode.
4. It is not just reference documentation in essay form.

Under those criteria, the ten current drafts over-split the middle of the journey. AXE, ChangeSpecs, and commit
workflows are separate implementation concepts, but a new reader experiences them together as "how an agent result
keeps moving, becomes reviewable, and lands." Telegram, prompt input, editor integration, mobile, memory, and web are
also separate features, but for a public series they are better framed as "where the operator controls SASE, now and
next."

## Topic Compression

Recommended mapping from current drafts to the tighter public series:

| Current draft | Recommendation |
| --- | --- |
| `[00] Why Coding Agents Need Orchestration` | Keep as Post 1. |
| `[01] Hello, SASE - Your First 15 Minutes` | Keep as Post 2, but publish only after the install path is true. |
| `[02] XPrompts in Depth` | Keep the core material; fold workflow/YAML examples into Post 3. |
| `[03] AXE` | Fold into Post 5 as background automation that keeps work moving. |
| `[04] Beads and SDD` | Keep as the basis for Post 4. |
| `[05] Commit Workflows` | Fold into Post 5 as the landing path from diff to PR/commit. |
| `[06] ChangeSpecs` | Fold into Post 5 as the review-state artifact. |
| `[07] Telegram Mobile Agents` | Fold into Post 6 as one control surface, not its own launch post. |
| `[08] Prompt Widget and sase-nvim` | Fold into Post 6 as operator/editor ergonomics. |
| `[09] What's Next` | Fold into Post 6 as roadmap, with memory/mobile/web as the forward-looking close. |

## Publishing Cadence

Recommended cadence:

- Launch with Post 1 and Post 2 linked together, but promote Post 1 externally first.
- Publish the remaining four no faster than weekly.
- Use each publication as a feedback checkpoint. If HN or GitHub issues show confusion after a post, patch docs and the
  next post before continuing.
- Do not publish all six at once. A backlog is useful, but staged release gives each post a purpose and avoids the
  "large unread series" effect.

## Recommended Blog Series Structure

1. **Why Coding Agents Need Orchestration**

   The launch thesis. Show the failure modes of one-off coding-agent sessions: lost intent, workspace collisions,
   fragile handoffs, missing review state, unclear dependencies, and commit chaos. Introduce SASE as the durable
   operating layer around existing agent CLIs, not as another agent runtime.

2. **Hello, SASE - Your First 15 Minutes Orchestrating Coding Agents**

   The conversion post. Walk a stranger through the smallest honest first run: install or source setup, explicit
   workspace target, one agent launch, where the result appears in ACE, and what artifact proves the run was tracked.
   This post should stay draft until the public install path is current and smoke-tested.

3. **Prompt Logic as Engineering Infrastructure**

   The reusable-workflow post. Explain XPrompts as the bridge from shell-history prompts to versioned prompt/workflow
   assets: Markdown prompts, typed inputs, directives, multi-agent fanout, YAML workflows when needed, and plugin-shipped
   defaults. Keep this practical and example-driven; link the full grammar/reference docs.

4. **Plans That Agents Can Execute**

   The planning and dependency post. Combine SDD and beads into one story: approved plans become durable files; epics
   become phase beads; dependencies produce ready/blocked queues; `sase bead work` turns a plan into ordered agent
   execution. This is the post that differentiates SASE from "a bunch of worktrees."

5. **From Agent Diff to Reviewable Change**

   The review/landing post. Follow one completed agent run through AXE, hooks, mentors, ChangeSpecs, commit workflows,
   proposals/PRs, and `commit_result.json`. The reader should leave understanding how SASE preserves accountability
   between "the agent wrote code" and "a human can review or land this safely."

6. **Operating SASE Beyond One Terminal**

   The control-surface and roadmap post. Show how ACE, notifications, the prompt widget, `sase-nvim`, Telegram, mobile
   gateway work, and future memory/web surfaces fit the same operator model. End with the roadmap: shared memory,
   mobile-native control, and a web surface, while being explicit about what is shipped versus planned.
