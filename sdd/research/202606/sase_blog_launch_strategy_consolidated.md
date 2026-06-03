# SASE Blog Launch Strategy - Consolidated Research

Date: 2026-06-03

## Question

How should SASE release its first public blog post or posts to maximize the chance of reaching the right users, earning
useful feedback, and converting serious coding-agent users into early adopters?

This note consolidates the two independent June research drafts:

- `sdd/research/202606/blog_post_launch_strategy.md`
- `sdd/research/202606/sase_first_blog_posts_launch_strategy.md`

It also builds on the May publishing research:

- [`blog_series_deep_research.md`](../202605/blog_series_deep_research.md)
- [`sase_blog_series_platform_decision_matrix.md`](../202605/sase_blog_series_platform_decision_matrix.md)
- [`sase_blog_setup_advice.md`](../202605/sase_blog_setup_advice.md)

## Executive Recommendation

Use a staged, canonical-first launch. Do not launch by saying "we published 11 posts." Launch around one sharp problem
essay, make the quickstart impossible to miss, and treat each distribution channel as a different feedback surface.

Recommended sequence:

1. Make `https://sase.sh/` and the GitHub repo stranger-ready.
2. Lead with `[01] Why Coding Agents Need Orchestration`.
3. Put `[02] Hello, SASE - Your First 15 Minutes Orchestrating Coding Agents` one click away from every announcement.
4. Submit the essay to Hacker News as a regular link, not `Show HN`.
5. Reserve `Show HN` for a later tryable product/repo launch if the install path is smooth.
6. Cross-post to DEV and Hashnode only after canonical URLs, previews, and descriptions are correct.
7. Use Reddit, Lobsters, LinkedIn, X, newsletters, and communities as tailored follow-up waves, not a same-day blast.
8. Use Product Hunt later, after SASE has a release, screenshots/demo, and a polished first-run path.

Best one-line positioning:

> Coding agents can produce patches. SASE coordinates the durable engineering system around them: workspaces, reusable
> prompts, dependency-aware work queues, review state, resumable runs, and provider-neutral commit flow.

## What Was Verified

The drafts agreed on the main strategy: canonical site first, GitHub/docs polish before distribution, positioning around
durable orchestration rather than "parallel agents," and staged promotion. The main conflict was Hacker News:

- One draft recommended using `Show HN` immediately.
- HN's own `Show HN` rules say blog posts and other reading material are off-topic for `Show HN`; they should be
  regular submissions.
- Resolution: submit the launch essay as a regular HN link, then consider a later `Show HN` for the repo or quickstart
  when users can easily run SASE.

Current repo/site observations on 2026-06-03:

- `docs/blog/posts/` contains 11 posts, `[00]` through `[10]`.
- The launch essay is `docs/blog/posts/why-coding-agents-need-orchestration.md`.
- The practical conversion post is `docs/blog/posts/hello-sase-your-first-15-minutes.md`.
- Public canonical post URLs are `https://sase.sh/blog/posts/<slug>/`.
- `https://sase.sh/blog/<slug>/` currently returns 404, so use the `/blog/posts/` shape everywhere.
- Public post pages have page-specific `<title>`, `<meta name="description">`, RSS alternates, and canonical links.
- Public post pages did not show Open Graph or Twitter-card metadata in the live HTML checked on 2026-06-03.
- `mkdocs.yml` has `site_url`, `site_description`, blog, and RSS configured, but not the Material `social` plugin.
- The blog index still emits the generic `Structured Agentic Software Engineering` meta description.
- The series hub still says some May posts are "Scheduled" even though June 3 has passed. Use "launch series now live"
  language unless dates/statuses are corrected.

## Positioning

The crowded category risk is real. Many tools now promise some variant of "run several coding agents in worktrees and
inspect the diffs." SASE should not lead with parallelism alone.

Lead with the durable operating layer:

- ChangeSpecs: CL/PR-sized work records with state, comments, mentors, commits, metadata, and review flow.
- AXE: background scheduling, hooks, dependency unblocking, mentors, and maintenance.
- XPrompts: reusable prompt templates and typed YAML workflows instead of shell-history prompts.
- Memory: audited long-term reads and human-reviewed write proposals.
- SDD and beads: versioned planning artifacts and git-portable dependency-aware work units.
- Commit finalizer and plugins: provider-neutral commit/PR flow across agent runtimes and VCS backends.

Avoid these framings:

- "A better AI coding agent." SASE coordinates agents; it does not replace them.
- "Another agent Kanban board." The differentiator is durable work state, scheduling, review, and handoff.
- "The future of software engineering." Too broad and too promotional.
- "An 11-part blog series." The reader's problem matters more than the content volume.
- "Vibe coding." SASE's claim is structure, repeatability, and reviewability.

## Launch Plan

### Phase 0: Preflight

Goal: every external click should land somewhere credible and tryable.

Checklist:

- Verify the README first screen answers: what SASE is, who it is for, why now, and how to try it.
- Verify the quickstart from a fresh machine and keep it under roughly 15 minutes.
- Confirm `https://sase.sh/blog/`, `[01]`, `[02]`, the series hub, and the repo links are live.
- Use only `https://sase.sh/blog/posts/<slug>/` canonical URLs.
- Fix or explicitly accept the stale "Scheduled" labels on the series hub.
- Add or verify Open Graph and Twitter-card metadata for launch URLs.
- Add a 1200x630-style overview/social image, or enable Material for MkDocs social cards.
- Check link previews for HN, LinkedIn, X, DEV, Hashnode, Slack/Discord, and Reddit where possible.
- Add GitHub topics if missing, using lowercase hyphenated topics such as `ai-agents`, `coding-agents`, `devtools`,
  `cli`, `tui`, `python`, `agentic-workflows`, and `open-source`.
- If SASE is ready for external users, create a tagged GitHub release with honest early-stage release notes.
- Prepare a short FAQ for predictable objections.

Expected objections:

- How is this different from Claude Code, Codex, Gemini CLI, or Cursor?
- Why do I need orchestration instead of scripts and tmux panes?
- Is this for one developer, teams, or both?
- How stable is it?
- Does it lock me into one model provider?
- What is the smallest workflow that makes SASE worth installing?
- What happens when an agent fails halfway through?

### Phase 1: Canonical Launch

Launch around `[01] Why Coding Agents Need Orchestration`, with `[02]` as the immediate try-it path.

Suggested SASE-owned announcement:

> Coding agents can write patches, but real engineering work also needs durable plans, isolated workspaces, dependency
> ordering, review state, retries, handoffs, and commit flow. The first SASE launch essay explains why the coordination
> layer matters; the companion quickstart shows how to try it in about 15 minutes.

Primary links:

- Essay: `https://sase.sh/blog/posts/why-coding-agents-need-orchestration/`
- Quickstart: `https://sase.sh/blog/posts/hello-sase-your-first-15-minutes/`
- Repo: `https://github.com/sase-org/sase`

### Phase 2: Hacker News

Use HN as the first serious technical feedback test, but follow HN's channel rules.

First HN submission:

```text
Why coding agents need orchestration
```

Submit the canonical `[01]` URL as a regular link. Do not use `Show HN` for the essay.

First comment draft:

```text
I wrote this after using coding agents heavily enough that the bottleneck stopped being "can an agent produce a patch?"
and became "how do I keep dozens of agent runs, handoffs, workspaces, review records, and commits coordinated?"

SASE is the open-source tool I am building around that problem. The essay is the conceptual launch post; the hands-on
quickstart is here: https://sase.sh/blog/posts/hello-sase-your-first-15-minutes/

I am especially interested in feedback from people already using Claude Code, Codex, Gemini CLI, or similar tools in
real repos: what coordination failure do you hit first?
```

HN conduct:

- Be online for at least the first 2-4 hours.
- Respond plainly to every substantive comment.
- Treat critics as useful reviewers; answer for the silent readers too.
- Do not ask for upvotes, submissions, or booster comments.
- Keep titles plain and avoid superlatives.

Later `Show HN` path:

```text
Show HN: SASE - orchestration for coding-agent work
```

Use this only when the quickstart is smooth enough that readers can run or inspect SASE easily. Link to the repo or
quickstart, then put the essay and backstory in the first comment.

### Phase 3: Cross-Post

After the canonical URL works and HN feedback settles:

- Cross-post `[01]` and `[02]` to DEV and Hashnode.
- Set DEV `canonical_url` to the SASE URL.
- Use Hashnode's republishing/original URL field for the SASE URL.
- Use complete, useful posts rather than teaser excerpts.
- Use DEV's `series` field consistently, for example `SASE: Structured Agentic Software Engineering`.

Suggested DEV tags:

| Post | Tags |
| --- | --- |
| `[01]` orchestration essay | `ai`, `agents`, `softwareengineering`, `devtools` |
| `[02]` quickstart | `ai`, `agents`, `tutorial`, `opensource` |
| `[03]` XPrompts | `ai`, `agents`, `workflow`, `promptengineering` |
| `[05]` Beads and SDD | `ai`, `agents`, `productivity`, `git` |

### Phase 4: Targeted Follow-Up

Use smaller, channel-native posts tailored to the audience.

| Channel | Best use | Tactic |
| --- | --- | --- |
| Reddit | Practical discussion | Ask a concrete question about coordinating agent runs; post only where rules allow it. |
| Lobsters | Deep technical proof | Submit one subsystem post with a real architecture angle, not the whole series. |
| LinkedIn | Professional workflow framing | Publish a short native summary for engineering leads and founders. |
| X | Visual thread | Use a TUI screenshot/GIF, a tight thesis, and links to `[01]`, `[02]`, and GitHub. |
| Discord/Slack | Warm feedback | Share only in communities where you participate; tailor to the channel's norms. |
| Newsletters | Second wave | Pitch the launch essay or a technical subsystem post after initial feedback. |

Reddit framing:

> For people running multiple coding-agent sessions in real repos: how are you tracking work state and handoffs today?
> I have been building an open-source coordination layer around this problem and wrote up the design tradeoffs.

### Phase 5: Product Hunt

Product Hunt is not the first blog-post channel. Use it later if SASE has:

- A release or clearly installable package.
- Screenshots or a short demo.
- A polished README and quickstart.
- A maker comment and support window.
- A product tagline, not a blog-series tagline.

Suggested Product Hunt one-liner:

> Coordinate coding-agent work with durable plans, isolated workspaces, reusable prompts, review state, and
> provider-neutral commit flow.

## Release Cadence

If the posts are already live with May dates, do not pretend they were published today. Use language such as "launch
series now live" or "first public push."

Suggested cadence:

| Day | Action |
| --- | --- |
| Day 0 | Public push around `[01]`; share `[02]` beside it; submit `[01]` to HN. |
| Day 1 | Respond to feedback; patch README, docs, quickstart, and FAQ if confusion appears. |
| Day 2 | Cross-post `[01]` to DEV and Hashnode with canonical URL. |
| Day 3 | Publish LinkedIn-native summary and X thread. |
| Day 4 | Promote one technical proof post, likely `[03]` XPrompts or `[07]` ChangeSpecs. |
| Week 2 | Share a feedback/lessons post and consider the later product-focused `Show HN`. |

## Metrics

Track signal that reflects adoption, not only attention:

| Metric | Why it matters |
| --- | --- |
| HN points, comments, and objection themes | Technical resonance and positioning problems. |
| GitHub stars, forks, issues, and contributors | Open-source attention and conversion. |
| Install/release downloads, if available | Actual product trial. |
| Docs/blog visitors and referrers | Which channels worked. |
| README/quickstart confusion reports | Conversion friction. |
| Serious external users running SASE in real repos | Strongest early signal. |

Interpretation rule: a few serious users with real repositories are more valuable than broad low-intent social
engagement.

## Immediate Next Steps

1. Fix or accept the current site metadata gaps: social cards/Open Graph/Twitter-card tags, generic blog-index
   description, and stale "Scheduled" labels.
2. Verify the quickstart from a clean machine.
3. Prepare one screenshot/GIF of ACE and one simple overview/social image.
4. Draft the HN first comment and FAQ before submitting.
5. Submit the canonical `[01]` essay as a regular HN link.
6. Cross-post only after the canonical URL and preview behavior are correct.
7. Save `Show HN` and Product Hunt for a later product-oriented launch.

## Sources

Official and primary sources:

- [Hacker News Guidelines](https://news.ycombinator.com/newsguidelines.html)
- [Show HN Guidelines](https://news.ycombinator.com/showhn.html)
- [Product Hunt Launch Guide](https://www.producthunt.com/launch/)
- [Google canonical URL guidance](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls)
- [Google title link guidance](https://developers.google.com/search/docs/appearance/title-link)
- [Google meta description/snippet guidance](https://developers.google.com/search/docs/appearance/snippet)
- [Open Graph protocol](https://ogp.me/)
- [Material for MkDocs social cards](https://squidfunk.github.io/mkdocs-material/setup/setting-up-social-cards/)
- [DEV editor guide](https://dev.to/p/editor_guide)
- [Hashnode canonical link docs](https://docs.hashnode.com/help-center/hashnode-editor/how-to-set-a-canonical-link)
- [Reddit spam guidance](https://support.reddithelp.com/hc/en-us/articles/360043504051-Spam)
- [GitHub repository topics docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)

Research sources:

- [How do Developers Promote Open Source Projects?](https://arxiv.org/abs/1908.04219)
- [Launch-Day Diffusion: Tracking Hacker News Impact on GitHub Stars for AI Tools](https://arxiv.org/abs/2511.04453)
