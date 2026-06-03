# SASE First Blog Posts Launch Strategy

Date: 2026-06-03

## Question

What is the best way to release SASE's first public blog posts so the project has the highest chance of reaching the
right users, earning useful feedback, and becoming credible as an open-source developer tool?

This note builds on the May 2026 research under `sdd/research/202605/`, especially:

- [`blog_series_deep_research.md`](../202605/blog_series_deep_research.md)
- [`sase_blog_series_platform_decision_matrix.md`](../202605/sase_blog_series_platform_decision_matrix.md)
- [`sase_blog_setup_advice.md`](../202605/sase_blog_setup_advice.md)

## Executive Recommendation

Use a staged, canonical-first launch:

1. Publish the canonical posts on `https://sase.sh/` first.
2. Lead public distribution with the strongest problem/positioning post, not the origin story.
3. Put the hands-on quickstart one click away from every announcement.
4. Use Hacker News as the first major technical feedback channel.
5. Cross-post to DEV and Hashnode only after the canonical URLs are live and stable.
6. Treat Reddit, Product Hunt, LinkedIn, and community channels as tailored follow-up channels, not a same-day blast.

For SASE's existing series, the launch order should be:

| Launch role | Existing post | Rationale |
| --- | --- | --- |
| Main launch essay | `[01] Why Coding Agents Need Orchestration` | Best broad thesis: one coding-agent run is not an engineering system. |
| Immediate conversion path | `[02] Hello, SASE - Your First 15 Minutes Orchestrating Coding Agents` | Gives interested readers something concrete to try. |
| Optional backstory | `[00] Origin Story - Where SASE Came From` | Useful for trust and narrative, but not the first public hook. |
| Follow-up technical proof | `[03] XPrompts`, `[04] AXE`, `[05] Beads and SDD`, `[07] ChangeSpecs` | Demonstrates that SASE is a system, not a slogan. |

Do not launch by saying "we published 11 posts." Launch by saying, in effect:

> Coding agents are powerful, but durable engineering work needs orchestration: isolated workspaces, reusable prompts,
> dependency-aware work queues, review state, resumable runs, and provider-neutral commit flow. SASE is our attempt to
> make that coordination layer explicit.

## What The Research Says

### Open-source promotion works best when the project owns its source of truth

A study of popular GitHub projects found that Twitter/social channels, user meetings, and blogs were common promotion
channels, and it specifically called out Hacker News as important for open-source promotion
([arXiv:1908.04219](https://arxiv.org/abs/1908.04219)). This supports the previous SASE decision to make the SASE site
the canonical archive and use other networks for distribution.

Recent research on HN exposure for AI and LLM repositories found measurable star growth after HN exposure: an average of
121 stars within 24 hours, 189 within 48 hours, and 289 within a week across its studied launches, while noting that
timing was an important predictor and that the `Show HN` label itself was not an advantage after controls
([arXiv:2511.04453](https://arxiv.org/abs/2511.04453)). Treat those numbers as directional rather than guaranteed for
SASE, but the core point matters: HN can be high-leverage for AI/dev-tool launches, and execution details matter.

### Hacker News wants interesting work, not marketing

HN's general guidelines say submissions should gratify intellectual curiosity, use plain titles, submit the original
source, avoid title hype, and not solicit votes or comments
([HN Guidelines](https://news.ycombinator.com/newsguidelines.html)).

HN's `Show HN` rules are narrower: `Show HN` is for something people can try, run, inspect, or give feedback on. Blog
posts and other reading material are explicitly not `Show HN`; those should be regular submissions. The project should
be non-trivial, personally worked on, easy to try, and the maker should be around to discuss it
([Show HN Guidelines](https://news.ycombinator.com/showhn.html)). HN's FAQ also notes that all Show HNs appear in
`newest`/`shownew`, but need a small points threshold before they appear on the main `show` page
([HN FAQ](https://news.ycombinator.com/newsfaq.html)).

Implication for SASE:

- Submit `[01] Why Coding Agents Need Orchestration` as a regular link post.
- Save `Show HN` for a later product/repo launch only if the quickstart is genuinely smooth.
- If doing `Show HN`, link to the repo or quickstart, then add a first comment with the backstory and blog links.
- Be present for the first 2-4 hours and answer questions plainly.
- Do not ask friends, contributors, or followers to upvote.

### Product Hunt is a later polish channel

Product Hunt's own launch guide frames PH as a global community of makers, technophiles, product people, entrepreneurs,
investors, creators, and early adopters. Its FAQ says the best day to launch is the day you are most prepared, that
12:01am Pacific is the best planned launch time, and that makers can hunt their own products. It also says promotion is
allowed, but makers should ask people to visit/comment rather than directly ask for upvotes
([Product Hunt Launch Guide](https://www.producthunt.com/launch/)).

PH categories currently include SASE-relevant buckets such as Engineering & Development, AI Agents, AI Coding Agents,
AI Infrastructure Tools, Prompt Engineering Tools, AI Workflow Automation, and Code Review Tools
([Product Hunt Launch Guide](https://www.producthunt.com/launch/)).

Implication for SASE:

- Do not use Product Hunt as the first blog-post release channel.
- Use it after the canonical site, README, install path, screenshots, and quickstart are polished.
- Prepare a short product tagline, a visual, a maker comment, and a support window.
- Ask people to try it and leave feedback, not to upvote.

### Reddit is useful only when targeted and rule-aware

Reddit's help docs define spam as repeated, unwanted, or unsolicited actions, and note that promotional content is not
inherently spam. However, many communities disallow promotion, and others use a 10% rule where only 10% of posting and
comment history in that community can be self-promotional while the rest should be helpful organic participation
([Reddit Help](https://support.reddithelp.com/hc/en-us/articles/28012014962580-How-do-I-keep-spam-out-of-my-community)).

Implication for SASE:

- Do not cross-post the same launch link broadly across subreddits.
- Pick a small number of communities where the post's problem is directly relevant.
- Read each community's rules and recent posts before posting.
- If rules are ambiguous, ask moderators first or post a text summary with no link unless requested.
- Prefer a practical angle: "How are you coordinating multiple coding-agent runs?" rather than "I launched SASE."

### SEO and social cards need to be correct before distribution

Google's title-link guidance says every page should have a title, titles should be descriptive and concise, and each
page should avoid boilerplate or keyword-stuffed titles
([Google title links](https://developers.google.com/search/docs/appearance/title-link)). Google's SEO starter guide says
good snippets can come from page content or a concise, unique meta description, and recommends high-quality images near
relevant text
([Google SEO starter guide](https://developers.google.com/search/docs/fundamentals/seo-starter-guide)).

Google's canonicalization docs recommend canonical URLs for duplicate or similar content, especially to consolidate link
signals and simplify metrics. Redirects and `rel="canonical"` annotations are both strong signals, and consistent
internal linking to the canonical URL helps Google understand the preference
([Google canonical docs](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls)).

The Open Graph protocol requires `og:title`, `og:type`, `og:image`, and `og:url`; it recommends `og:description` and
structured image metadata such as width, height, and alt text
([Open Graph protocol](https://ogp.me/)). Material for MkDocs can generate social preview images and metadata, but
requires `site_url` so social preview images can point to absolute URLs
([Material social cards](https://squidfunk.github.io/mkdocs-material/setup/setting-up-social-cards/)).

Implication for SASE:

- Verify every launch post has a plain, descriptive page title and description.
- Use absolute canonical URLs under `https://sase.sh/`.
- Add or verify Open Graph/Twitter card metadata before posting links anywhere.
- Prefer a readable SASE overview image or post-specific card over a generic screenshot.
- Run link preview checks for HN/link unfurling targets where possible before launch.

SASE's current `mkdocs.yml` already has `site_url`, `site_description`, blog support, and RSS. It has RSS configured
for `blog/posts/.*` with a default image, but does not currently show the Material `social` plugin enabled. That makes
social cards a concrete pre-launch gap to evaluate.

### Cross-posts should preserve the SASE canonical URL

DEV's editor guide supports Jekyll front matter, up to four tags, a `series` field, a cover image, and `canonical_url`
for the canonical version of the content ([DEV editor guide](https://dev.to/p/editor_guide)). DEV's help page also
documents setting canonical URLs in the editor
([DEV writing help](https://dev.to/help/writing-editing-scheduling)).

Hashnode supports adding an original URL for republished articles in the "Are you republishing?" section
([Hashnode canonical docs](https://docs.hashnode.com/help-center/hashnode-editor/how-to-set-a-canonical-link)).
Medium also supports canonical links and says its import tool automatically applies a canonical link to the original
source ([Medium canonical docs](https://help.medium.com/hc/en-us/articles/360033930293-Set-a-canonical-link)).

Implication for SASE:

- Publish first on `sase.sh`.
- Wait until the canonical URL is live and the social preview works.
- Then cross-post to DEV and Hashnode with canonical URLs pointing to SASE.
- Do not use excerpt-only clickbait cross-posts; developer platforms respond better to complete, useful posts.

### GitHub hygiene is part of the launch

GitHub says repository topics help people find and contribute to a project; admins can add up to 20 lowercase,
hyphenated topics related to purpose, subject area, community, or language ([GitHub topics docs][github-topics]).
GitHub releases package software with release notes and links to assets, and releases are visible to anyone with read
access
([GitHub releases docs](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)).

Research on README and CONTRIBUTING files says these files are often the first point of contact for potential
contributors, and prominent open-source organizations advocate creating community-focused and process-oriented docs
early ([arXiv:2502.18440](https://arxiv.org/abs/2502.18440)).

Implication for SASE:

- Before the first major push, make the README's first screen answer: what is SASE, who is it for, why now, and how to
  try it.
- Add GitHub topics such as `ai-agents`, `coding-agents`, `devtools`, `cli`, `tui`, `python`, `software-engineering`,
  `agentic-workflows`, and `open-source` if they fit GitHub's topic constraints and actual project positioning.
- Create a real tagged release if SASE is ready for users, even if it is explicitly early.
- Make the install path and first-run commands correct for a fresh machine.

## Recommended Launch Plan

### Phase 0: Preflight, 1-3 days before public posting

Goal: make sure every external click lands somewhere credible.

Checklist:

- Build and manually inspect the published site.
- Verify `https://sase.sh/blog/`, the series hub, `[01]`, and `[02]` are live.
- Confirm canonical URLs and redirects use `https://sase.sh/`, not `www` or local paths.
- Confirm RSS exists and includes posts.
- Confirm each post has a title and description that make sense in search snippets.
- Add or verify Open Graph/Twitter metadata and a 1200x630-style card image.
- Check the README first screen and quickstart.
- Check that `pip`/`uv`/`just`/first-run requirements are accurate.
- Add or verify GitHub topics.
- If ready, create a GitHub release with practical release notes.
- Prepare a short FAQ for expected objections.

Expected objections:

- "How is this different from Claude Code/Codex/Gemini CLI?"
- "Why do I need orchestration instead of scripts?"
- "Is this only for one developer or for teams?"
- "How stable is it?"
- "What does it cost?"
- "Can I use this without buying into one model provider?"
- "What is the smallest useful workflow?"

### Phase 1: Canonical launch

Publish the first public announcement around `[01]`, with `[02]` as the immediate "try it" link.

Suggested primary headline on SASE-owned channels:

> Why Coding Agents Need Orchestration

Suggested short announcement text:

> Coding agents can write patches, but real engineering work also needs durable plans, isolated workspaces, dependency
> ordering, review state, retries, handoffs, and commit flow. I wrote the first SASE launch essay on why the
> coordination layer matters, plus a 15-minute quickstart for trying it.

Links:

- Primary: `https://sase.sh/blog/posts/why-coding-agents-need-orchestration/`
- Secondary: `https://sase.sh/blog/posts/hello-sase-your-first-15-minutes/`
- Repository: `https://github.com/sase-org/sase`

### Phase 2: Hacker News

Use HN as the highest-leverage first external test.

Recommended first HN submission:

```text
Why coding agents need orchestration
```

Use a regular link submission to the canonical `[01]` post. Do not use `Show HN` for the blog post because HN's own
rules classify blog posts as off-topic for `Show HN`.

First comment draft:

```text
I wrote this after using coding agents heavily enough that the bottleneck stopped being "can an agent produce a patch?"
and became "how do I keep dozens of agent runs, handoffs, workspaces, review records, and commits coordinated?"

SASE is the open-source tool I'm building around that problem. The essay is the conceptual launch post; the hands-on
quickstart is here: https://sase.sh/blog/posts/hello-sase-your-first-15-minutes/

I'm especially interested in feedback from people already using Claude Code, Codex, Gemini CLI, or similar tools in
real repos: what coordination failure do you hit first?
```

Later, if the product is ready for a `Show HN`, use a title closer to:

```text
Show HN: SASE - orchestration for coding-agent work
```

Then link to the repo or quickstart, not just the essay.

### Phase 3: Cross-post to developer platforms

After the HN discussion settles and canonical URLs are proven:

- Cross-post `[01]` and `[02]` to DEV and Hashnode.
- Set canonical URL to the SASE URL.
- Use DEV's `series` field consistently, e.g. `SASE: Structured Agentic Software Engineering`.
- Use DEV's four tags conservatively.

Suggested DEV tags:

| Post | Tags |
| --- | --- |
| `[01]` | `ai`, `agents`, `softwareengineering`, `devtools` |
| `[02]` | `ai`, `agents`, `tutorial`, `opensource` |
| `[03]` XPrompts | `ai`, `agents`, `workflow`, `promptengineering` |
| `[05]` Beads and SDD | `ai`, `agents`, `productivity`, `git` |

### Phase 4: Targeted community follow-up

Use smaller posts tailored to specific communities:

- Python/devtools communities: emphasize CLI/TUI, packaging, and open-source architecture.
- AI coding-agent communities: emphasize multi-provider orchestration.
- Git/review communities: emphasize ChangeSpecs, commits, and review state.
- Engineering leadership/professional networks: emphasize operating model and durable work.

Avoid posting the same text everywhere. Each community should get a version that stands alone even if the link is
removed.

### Phase 5: Product Hunt, if desired

Do Product Hunt only after:

- The GitHub repo has a release.
- The first-run path is smooth.
- Screenshots or a short demo are ready.
- You can monitor and reply for the launch day.
- The launch copy describes the product, not the blog series.

Suggested PH one-liner:

> Coordinate coding-agent work with durable plans, isolated workspaces, reusable prompts, review state, and
> provider-neutral commit flow.

## Messaging Guidance

### Lead with the coordination problem

Best SASE hook:

> Coding agents can produce patches. SASE coordinates the engineering system around them.

Good supporting proof:

- Durable work state outside the chat transcript.
- Isolated numbered workspaces for parallel work.
- XPrompts for reusable prompt/workflow logic.
- ACE for observing and operating agent work.
- AXE for background scheduling and maintenance.
- ChangeSpecs and beads for reviewable, dependency-aware work.
- Provider-neutral boundaries across Claude Code, Codex, Gemini CLI, Qwen Code, and OpenCode.

### Avoid these launch framings

Avoid:

- "A better AI coding agent" - SASE is not replacing the agent.
- "The future of software engineering" - too broad and hype-coded.
- "An 11-part blog series" - this is about the reader's pain, not the content volume.
- "Agentic software engineering framework" without examples - the phrase needs grounding.
- "Vibe coding" positioning - SASE's differentiator is structured work, review, and durability.

### Use concrete channel-specific copy

HN:

> Why coding agents need orchestration

LinkedIn:

> Coding agents are changing the unit economics of software work, but teams still need durable state: plans, work
> queues, review records, tests, commits, dependencies, and handoffs. SASE is my attempt to make that operating layer
> explicit.

DEV/Hashnode:

> Stop treating coding-agent work as disposable chat history. This post explains the orchestration layer SASE is
> building around workspaces, reusable prompts, dependency-aware execution, and review state.

Reddit:

> For people running multiple coding-agent sessions in real repos: how are you tracking work state and handoffs today?
> I have been building an open-source coordination layer around this problem and wrote up the design tradeoffs.

## Release Cadence

Preferred cadence if the series is not yet public:

| Day | Action |
| --- | --- |
| Day 0 | Publish `[01]` and `[02]` canonically. Share `[01]` on HN. |
| Day 1 | Respond to HN/comments; patch docs/README if launch feedback reveals confusion. |
| Day 2 | Cross-post `[01]` to DEV/Hashnode with canonical URL. |
| Day 3 | Share LinkedIn-native summary. |
| Day 4 | Publish or promote `[03]` XPrompts as the first deeper technical proof. |
| Day 6-7 | Publish/promote `[04]` or `[05]` depending on feedback themes. |
| Week 2 | Share a "what we learned from launch feedback" post and update quickstart. |

If all posts are already public by the time launch happens, reframe as:

> The SASE launch series is now live. Start with the orchestration essay and the 15-minute quickstart; the rest of the
> series goes subsystem by subsystem.

Do not pretend older posts are newly published if timestamps already show otherwise. Use exact language: "now live",
"launch series", or "first public push."

## Metrics To Track

Minimum useful launch dashboard:

| Metric | Why |
| --- | --- |
| GitHub stars, forks, issues, contributors | Open-source attention and conversion. |
| GitHub release downloads, if release assets exist | Product adoption signal. |
| Docs/blog unique visitors and referrers | Which channels actually worked. |
| HN points/comments and comment themes | Technical resonance and objections. |
| README/quickstart exits or issue reports | Friction in conversion path. |
| RSS subscribers, if measurable | Durable readership. |
| DEV/Hashnode reactions/comments after canonical cross-posting | Syndication value. |

Interpretation rule: prioritize high-signal feedback and successful first installs over raw likes. For SASE, a few
serious users running it in real repositories are more valuable than broad low-intent social engagement.

## Concrete Pre-Launch Gaps To Check In This Repo

Based on local inspection on 2026-06-03:

- `mkdocs.yml` has blog and RSS configured.
- `mkdocs.yml` has `site_url: https://sase.sh/`, which is required for absolute social metadata.
- `mkdocs.yml` does not show the Material `social` plugin enabled.
- The blog nav currently lists all posts directly, which is fine for docs navigation but may make the launch feel like a
  fully published archive rather than a staged release.
- Existing post dates are in May 2026. If the first public push is in June 2026, use "launch series now live" language
  instead of "published today" language.
- The homepage already links to the launch essay and the SASE Blog Series.
- The README already has a strong first screen, but it should be checked from a fresh user's perspective before HN.

## Bottom Line

The best launch is not "publish all the posts and announce everywhere." For SASE, the better play is:

1. Make `sase.sh` the polished canonical source.
2. Launch the orchestration essay first.
3. Put the 15-minute quickstart directly beside it.
4. Use HN as the first major technical feedback test.
5. Fix confusion quickly.
6. Cross-post with canonical URLs.
7. Follow with focused subsystem posts and targeted community discussions.

The success condition is not just traffic. It is getting serious coding-agent users to understand that SASE is the
coordination layer around agents, try the quickstart, and tell you where the model succeeds or breaks in real work.

[github-topics]: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics
