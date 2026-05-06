# Publishing a SASE Blog Series: Site Options and Workflow

Date: 2026-05-06 (revised 2026-05-06 with additional research on minimalist platforms, newsletter
alternatives, static-site generators, AI-agent communities, posting etiquette, analytics, and KPIs)

## Question

Where should a SASE blog series be posted, and how should publishing work so the series builds audience without giving
up ownership, search equity, or operational simplicity?

## Short Recommendation

Use a **canonical home plus syndication** model.

1. Publish the canonical version on a domain/repo you control.
2. Cross-post to developer-heavy platforms that support canonical links, especially Hashnode and DEV.
3. Use LinkedIn and Substack for relationship-driven distribution, but treat them as audience channels rather than the
   only archive.
4. Share links to Hacker News, Reddit, Lobsters, X, Bluesky, and relevant Discord/Slack communities only when each post
   has a concrete technical hook.

For SASE specifically, the strongest starting stack is:

| Role | Site | Why |
| --- | --- | --- |
| Canonical archive | `sase.dev` / `blog.sase.dev` or GitHub Pages | Own the URL, keep Markdown source in Git, preserve long-term control. |
| Main developer mirror | Hashnode | Developer audience, custom domain, Markdown/editor support, GitHub backup/publish integration, newsletter. |
| Secondary developer mirror | DEV Community | Strong developer feed, Markdown with front matter, `series`, and `canonical_url`. |
| Professional/social mirror | LinkedIn Articles or Newsletter | Reaches founders, engineering managers, platform teams, and existing professional network. |
| Optional newsletter home | Buttondown, Beehiiv, Substack, or Ghost | Use if the goal is a recurring email relationship, not just public technical posts. |
| Broad mirror | Medium | Useful for reach and imports, but weaker for developer ownership than Hashnode/DEV. |
| AI/agent communities | r/LocalLLaMA, r/AI_Agents, r/LangChain, r/MachineLearning, r/programming | Targeted technical audience for SASE's specific niche; treat as link-share, not primary host. |

My bias: start with canonical site + Hashnode + DEV + LinkedIn. Add a newsletter (Buttondown if simplicity matters,
Beehiiv if growth tooling matters) only if email subscribers become a primary goal. Add Medium only if a specific
publication or audience segment justifies the extra formatting pass.

## Why Canonical-First Matters

Publishing the same post across several domains can split search signals and produce duplicate-content ambiguity. Google
Search Central documents canonical URLs as the way to tell search engines which URL is the preferred representative for
duplicate or similar pages: <https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls>.

Several relevant platforms support this:

- Medium lets authors set a canonical link, and its import tool automatically adds the source as canonical:
  <https://help.medium.com/hc/en-us/articles/360033930293-Set-a-canonical-link> and
  <https://help.medium.com/hc/en-us/articles/214550207-Importing-a-post-to-Medium>.
- DEV supports `canonical_url` in article front matter:
  <https://dev.to/p/editor_guide/>.
- Hashnode supports adding an original URL for republished articles:
  <https://docs.hashnode.com/help-center/hashnode-editor/how-to-set-a-canonical-link>.

The practical rule: publish the canonical URL first, then mirror elsewhere with a canonical link back to the original.

## Platform Notes

### Canonical Site: Own Domain + Static Blog

Best for:

- durable archive;
- SEO ownership;
- open-source credibility;
- Markdown-first workflow;
- posts that should remain useful for years.

Good implementation choices, ranked for a 2026 dev-blog launch:

- **Astro (recommended default)**. Content-first, ships almost no JavaScript by default, has first-class Markdown/MDX
  with `astro:content` collections, native RSS, and works with any framework for sprinkles of interactivity. In 2026
  comparisons it is the default recommendation for new content/marketing sites: ships less JS than any JS-based
  alternative, supports React/Vue/Svelte/Preact islands, and has a fast-growing ecosystem.
- **Hugo**. Single Go binary, sub-second builds even on huge sites, mature theme ecosystem. Pick this if the site is
  pure Markdown with no interactivity and build speed at scale matters.
- **GitHub Pages + Jekyll**. Free hosting on `github.io` or a custom domain with Jekyll's blog-aware Markdown
  conventions: <https://jekyllrb.com/docs/github-pages/> and <https://jekyllrb.com/docs/posts/>. Lower velocity than
  Astro/Hugo but zero infra if you're already on GitHub.
- **Eleventy or Next.js**. Use Eleventy for raw simplicity, Next.js if SASE's main site is already React/Next-based and
  you want one codebase.
- **Docs-style `/blog/`** under the main SASE website if the goal is project credibility over personal writing.

Hosting: Cloudflare Pages, Vercel, Netlify, or GitHub Pages all serve any of the above for free at this scale. Pick by
DNS and CDN preference, not generator.

Tradeoffs:

- You own the archive but not discovery.
- Email subscriptions, analytics, search, OpenGraph images, and RSS need setup.
- Initial design/setup is more work than posting directly to a platform.

Recommendation: make this the source of truth. Even if the first public wave starts on Hashnode, keep a Git-backed
canonical copy so the series can be moved later.

### Hashnode

Best for:

- developer audience;
- custom-domain developer blog;
- Markdown-friendly posts with code;
- publishing from or backing up to GitHub.

Hashnode positions Blogs as a developer and team blogging platform with a developer-focused community, Markdown/code
support, SEO features, analytics, headless mode, and GitHub integration:
<https://docs.hashnode.com/blogs/getting-started/introduction>. Its GitHub docs say it can publish Markdown files from
GitHub and back up articles to GitHub:
<https://docs.hashnode.com/help-center/github/how-to-set-up-github-as-source> and
<https://docs.hashnode.com/help-center/github/how-to-backup-articles-to-github>. It also has imports from Medium, DEV,
bulk Markdown, and RSS: <https://docs.hashnode.com/blogs/blog-dashboard/import>.

Tradeoffs:

- Strong fit for SASE's technical audience.
- Platform dependency still exists even with GitHub backup.
- Newsletter sender/domain behavior is less brand-controlled than a custom email stack.

Recommendation: use as the main developer mirror, or as the first public home if the standalone SASE site is not ready.

### DEV Community

Best for:

- developer feed/discovery;
- practical implementation posts;
- code-heavy articles;
- series metadata.

DEV's editor uses Markdown with Jekyll-style front matter. Concrete constraints to plan around (confirmed against the
2026 editor guide):

- Hard cap of **4 tags** per article.
- `cover_image` recommended at **1000x420**.
- Front matter supports `title`, `published`, `tags`, `canonical_url`, `cover_image`, and `series`.
- Drafts get a public-but-unlisted preview URL useful for review before publishing.

Source: <https://dev.to/p/editor_guide/>.

Tradeoffs:

- Great for hands-on posts like "how SASE manages agent workspaces" or "what we learned from ChangeSpecs."
- Less ideal for long manifesto posts or product-positioning essays.
- Tag choice matters because discoverability is feed-driven.

Recommendation: cross-post most technical posts here with `canonical_url` set.

### LinkedIn Articles or Newsletter

Best for:

- professional network reach;
- engineering leaders and founders;
- posts about team process, software engineering practice, and organizational implications.

LinkedIn newsletters let members subscribe and be notified about new articles:
<https://www.linkedin.com/help/linkedin/answer/a522525/linkedin-newsletters?lang=en>.

Tradeoffs:

- Good reach to people who may not read DEV/Hashnode.
- Weak Markdown workflow; expect manual formatting.
- Canonical SEO controls are limited compared with DEV/Medium/Hashnode.

Recommendation: do not mirror every post verbatim. Publish shorter LinkedIn-native versions or excerpts that link back
to the canonical post.

### Newsletter Platforms (Substack, Buttondown, Beehiiv, Ghost)

If email becomes a goal, the choice is no longer just Substack vs Ghost. The 2026 landscape splits along two axes:
**writer-minimal vs. growth-tooling**, and **hosted vs. self-hostable**.

| Platform | Stance | Free tier | Pricing past free | Markdown / API | Best for |
| --- | --- | --- | --- | --- | --- |
| Substack | Hosted, social-network-flavored | Unlimited subscribers, free posts | 10% fee on paid subscriptions | Limited Markdown, no public API | Founder essays, audience-network discovery |
| Buttondown | Hosted, intentionally minimalist | 100 subscribers | From ~$9/mo for ~1k subs, no rev cut | Markdown-native, API-first | Developer-style newsletters, automation |
| Beehiiv | Hosted, growth-feature-rich | Up to 2,500 subs (with limits) | Tiered by subs and features | API and integrations | Newsletters that lean into ad network, referrals, SEO hosting |
| Ghost(Pro) | Hosted CMS + email + members | None | Tiered hosting, no rev cut | Markdown + API | Long-term, self-owned publication |
| Ghost (self-hosted) | Open-source, self-run | Free (infra cost) | Your hosting bill | Markdown + API | Maximum control |
| Kit (formerly ConvertKit) | Hosted creator-focused | 10k subs free tier | Tiered | API | Creator funnels and forms |

Substack is free for publishing and charges a 10% platform fee on paid subscriptions:
<https://support.substack.com/hc/en-us/articles/360037607131-How-much-does-Substack-cost>. It can import from Medium,
Ghost, WordPress, Mailchimp, Beehiiv, Tumblr, Blogspot, RSS, and CSV:
<https://support.substack.com/hc/en-us/articles/360037830351-How-do-I-import-my-posts-from-another-platform-such-as-Mailchimp-WordPress-Medium-or-Ghost>.
Custom domains require a one-time fee:
<https://support.substack.com/hc/en-us/articles/360051222571-How-do-I-set-up-my-custom-domain-on-Substack>.

Buttondown is built by a single developer and is deliberately minimalist with Markdown editing, an API-first
architecture, automations, segmentation by tags/metadata, and no platform fee on paid subs:
<https://buttondown.com/comparisons/beehiiv>.

Beehiiv is feature-rich and growth-focused — referrals, ad network, boosts, SEO hosting, integrations, and a public
API — at the cost of more complexity than Buttondown: <https://www.beehiiv.com/comparisons/substack>.

Tradeoffs to weigh for SASE:

- If the goal is "engineers reading on the web," none of these are required. RSS plus Hashnode's built-in newsletter
  covers most of it.
- If the goal is "I want to talk to subscribers directly and own the list," pick by philosophy: **Buttondown** if the
  newsletter should feel like a developer log, **Beehiiv** if you intend to run growth experiments, **Ghost** if the
  newsletter is meant to be a long-term publication, **Substack** only if the in-platform discovery network is the
  point.
- A self-hosted Ghost on the SASE domain is the most "own everything" option but also the most operational cost.

Recommendation: defer until at least 3-4 canonical posts exist. When the time comes, default to Buttondown for SASE's
profile (single project, technical audience, want simple Markdown + API). Reserve Substack for the moment when network
effects are explicitly the strategy.

### Ghost

Best for:

- a self-owned publication with built-in newsletter/members;
- more control than Substack;
- long-term content business infrastructure.

Ghost supports writing in Markdown in its editor and provides publishing, pages, tags, metadata, and API access:
<https://docs.ghost.org/publishing/>. Ghost(Pro) includes a site, email newsletter, custom domains, and managed hosting:
<https://ghost.org/pricing>.

Tradeoffs:

- More professional and controllable than Substack.
- More operational cost than GitHub Pages/Hashnode/DEV.
- Overkill unless newsletter/membership becomes important.

Recommendation: consider later if SASE content becomes a serious publication, not just a launch series.

### Medium

Best for:

- broad non-developer audience;
- existing Medium publications;
- reposting polished essays;
- people who still follow writers there.

Medium supports canonical links and import-from-URL workflows:
<https://help.medium.com/hc/en-us/articles/360033930293-Set-a-canonical-link> and
<https://help.medium.com/hc/en-us/articles/214550207-Importing-a-post-to-Medium>.

Tradeoffs:

- Easy cross-posting.
- Less developer-specific than DEV/Hashnode.
- Platform UX and membership prompts may reduce the sense of SASE as an open technical project.

Recommendation: optional. Use for selected essays, especially if accepted into a relevant Medium publication.

### Minimalist Alternatives (Bear Blog, Mataroa, Micro.blog)

Best for:

- a "throw-up-a-blog-in-an-hour" canonical home before sase.dev exists;
- a personal-essay companion to the SASE site;
- writers who want zero theme/CSS/SEO ceremony;
- privacy-first defaults with no tracking and no ads.

Notes:

- **Bear Blog** is a privacy-first, ultra-minimal platform with no ads/trackers. Custom domain and analytics are paid
  ($5/mo or $48/yr). Markdown-native; no native comments.
- **Mataroa** is similarly minimalist, accepts comments, allows free image hosting, and supports rich exports
  (Markdown, .epub, Hugo, Zola). Premium with custom domain is ~$9/yr. The platform is open source and self-hostable.
- **Micro.blog** is good if a microblog/IndieWeb posture matters; supports custom domains, RSS, and crossposting.

Tradeoffs:

- Lowest possible operational cost; trivial to migrate off via Markdown export.
- Less brand control than a self-hosted SASE site.
- Discovery is weaker than Hashnode/DEV; treat them like canonical homes, not promotion channels.

Recommendation: only relevant if `sase.dev/blog` is going to be delayed by weeks. In that case, Mataroa is the best
"hold the canonical URL while I build the real site" choice because of its open export formats and self-host option.

### AI-Agent and SASE-Adjacent Communities

SASE's natural audience overlaps with several AI-agent and dev-tooling communities. Treat each as a place to share
finished posts, not a host for the writing itself. Self-promotion etiquette varies by community; read the rules before
posting and lurk for at least a few days.

| Community | Reason it's relevant to SASE | Notes |
| --- | --- | --- |
| r/programming | General developer feed | Strict against blog spam; needs a strong technical hook in the title. |
| r/LocalLLaMA | Local-model-running developers | Self-promotion guidance: keep it under ~10% of activity, factual titles, direct links; mods are aggressive about low-value AI spam. |
| r/AI_Agents | Builders explicitly working on agents | Smaller, more receptive to project posts when the technical content is real. |
| r/LangChain | Agent framework users debugging cyclic graphs | Cross-link well when posts touch agent observability or workflow shape. |
| r/MachineLearning | Research-leaning | Heavy moderation; tag posts as `[D]` discussion or `[P]` project; needs rigor. |
| r/ChatGPTCoding, r/vibecoding | Coding-with-LLMs hobbyists | Higher tolerance for opinion posts and developer-experience writing. |
| r/devtools | Dev-tool-builders | Good for posts about SASE's editor integrations and CLI ergonomics. |
| Hacker News | Generalist technical | See "Posting Etiquette" below. |
| Lobsters | Tagged technical link aggregator | Invite-only; submitter-tagged; self-promo > 25% of activity is discouraged. |
| Discord/Slack: LangChain, LlamaIndex, AutoGen, Cursor, Aider, OpenDevin | Agent-tooling builders | Ask the channel's etiquette; usually a `#showcase` or `#share` channel exists. |

Useful index repos: `danielrosehill/Awesome-AI-Subreddits` and `caramaschiHG/awesome-ai-agents-2026`.

### Posting Etiquette: Hacker News, Lobsters, Reddit

Three failure modes ruin otherwise good posts on these sites: marketing language, missing technical hook, and astroturf
comments. Concrete rules:

**Hacker News.**

- Plain blog posts go as a regular submission, not "Show HN." Show HN is for things readers can run or hold; a blog
  post does not qualify (<https://news.ycombinator.com/showhn.html>).
- HN guidelines (<https://news.ycombinator.com/newsguidelines.html>) say it's fine to post your own work part of the
  time, but the primary use of the account should be curiosity. Build account history before submitting your own
  content.
- Use the post's literal headline. No "[Blog]", no emoji, no marketing.
- Don't ask friends to upvote or seed comments — the community spots and flags it.
- Best time slot tends to be early US morning weekdays, but a strong technical hook beats timing.

**Lobsters.**

- Submitter must pick from the predefined tag list. Mismatched tags get the post removed.
- The community tolerates self-submission but enforces a soft "no more than ~25% self-promo" guideline; build other
  activity (votes, comments) first (<https://lobste.rs/about>).
- Mods scale response by user history: regular community participants get gentler nudges than zero-activity accounts
  posting their own blog.

**Reddit.**

- Each subreddit has its own self-promotion threshold (often 10:1 community-to-self ratio). Read the sidebar.
- Title should be the post's actual title, not clickbait. Many subs auto-remove anything that looks like a marketing
  pitch.
- For technical subs, post Monday-Wednesday US daytime. Reply to comments within a few hours.

The single best lever across all three: lead with what is novel and concrete, not with positioning.

### Analytics, RSS, and Email Plumbing

These are easy to skip, costly to retrofit. Set them up before post #1.

- **Analytics:** Use a privacy-first tool to avoid the GDPR/cookie-banner tax. Plausible (~$9/mo, hosted) and Fathom
  (~$15/mo, hosted) are the cleanest hosted options. GoatCounter is the best free/self-hostable option for a small
  technical blog. Avoid Google Analytics 4 unless something specifically requires it; GDPR enforcement and cookie
  consent overhead make it a poor default for a small project blog.
- **RSS:** Always-on. Astro and Hugo emit RSS out of the box; double-check the feed validates and includes full content
  or a useful summary plus a stable canonical link. Technical readers still use RSS, and many syndication tools (Hashnode
  GitHub source, IFTTT, Zapier, n8n) consume it.
- **OpenGraph + Twitter Card metadata:** Required for clean previews on LinkedIn, X/Bluesky, Discord, and Slack.
- **Sitemap + canonical tags:** Required if you want syndicated copies on Hashnode/DEV/Medium to consolidate to your
  canonical URL.
- **Newsletter sign-up form:** Even if you don't pick a newsletter platform yet, capture interest with a single
  email-only form (e.g., a Buttondown free embed) so you can migrate the list later.

### Video and Audio Companion (Optional)

Short-form video on YouTube, X, and LinkedIn is a separate channel, not a replacement. A pragmatic approach for SASE:

- For each post, record a 5-10 minute screen-recorded explanation that mirrors the post outline. Embed it at the top of
  the canonical post and upload as a YouTube video with the canonical post URL in the description.
- Hold off on a full podcast. The cost-to-value ratio is poor for a single project blog series until there's a clear
  audience pulling for it.
- If video is on, plan editing time: 2026 surveys of developer-creators consistently flag editing as the top cause of
  abandonment. OBS for capture and Descript for editing is the common stack.

### What "Good" Looks Like (KPIs)

Track these per post for the first three months. The point is to learn which channels actually work for SASE, not to
hit vanity numbers.

- **Per post:** unique visitors, p50 time-on-page, scroll depth past the halfway mark, count of inbound links from new
  domains, count of new GitHub stars/issues attributable in the 48h window after publishing, count of newsletter
  signups attributable.
- **Per channel:** referral-source breakdown for visitors and conversions (signup, GitHub click).
- **Per series:** % of readers who read >=2 posts in the series, RSS subscriber growth, email subscriber growth.

Realistic baselines for a small open-source project blog launching cold:

- 300-1,500 unique readers on a "good" technical post in week one, with 3-10x that on a HN/Lobsters hit.
- 1-3% of readers convert to RSS or email follow.
- Cross-posts on Hashnode and DEV typically add 30-200% on top of canonical traffic in the first week, depending on tag
  picks and feed luck.

### Anti-Patterns to Avoid

- **Cross-posting without canonical URLs.** Splits SEO and confuses readers about which version is authoritative.
- **Marketing language in HN/Lobsters/Reddit titles.** Instant flag/downvote on technical communities.
- **Inconsistent series naming across platforms.** DEV's `series` field, Hashnode's series feature, and your canonical
  site's series page must all use the same exact title or the cross-platform reading experience fragments.
- **Letting the canonical site lag the syndicated mirrors.** If readers find the Hashnode version first and there's no
  canonical version, you lose the option to migrate later.
- **Mirroring everything to LinkedIn unedited.** LinkedIn's tone, expected length, and audience differ; verbatim mirrors
  read as low-effort.
- **Starting a Substack and a Ghost site and a Medium import in the same week.** Pick one syndication and one optional
  newsletter. Add channels only after a post has shipped successfully on the existing ones.
- **No email capture from day one.** RSS-only means the readers who care most have no way to follow updates if RSS dies
  or they switch readers.
- **Treating "post in 8 places" as the strategy.** Each channel needs the smallest amount of channel-specific edit
  necessary to fit. Otherwise the volume just dilutes signal.

## Recommended Publishing Workflow

### Authoring

Keep the source post as Markdown in Git. A simple structure:

```text
content/blog/
  2026-05-10-structured-agentic-software-engineering.md
  2026-05-17-changespecs.md
  2026-05-24-memory-and-skills.md
```

Each post should include front matter that can map cleanly to multiple platforms:

```yaml
---
title: "Structured Agentic Software Engineering"
date: 2026-05-10
slug: structured-agentic-software-engineering
description: "Why agentic coding needs a software engineering discipline around workspaces, memory, plans, and review."
canonical_url: https://sase.dev/blog/structured-agentic-software-engineering/
tags:
  - agentic-software-engineering
  - ai-agents
  - software-engineering
series: "Structured Agentic Software Engineering"
---
```

### Per-Post Steps

1. Draft in Markdown.
2. Publish canonical post on the SASE site.
3. Verify canonical URL, title, description, OpenGraph image, RSS entry, and code formatting.
4. Cross-post to Hashnode with the original/canonical URL set.
5. Cross-post to DEV with `canonical_url` and `series` front matter.
6. Post a LinkedIn-native excerpt with a link to the canonical article.
7. Share in selective communities only when the post has a crisp technical claim, demo, or lesson.
8. After 48-72 hours, record which channels produced meaningful readers, comments, stars, issues, or subscribers.

### Cadence

Start with a 6-post series over 6-8 weeks:

| Post | Working angle | Best channels |
| --- | --- | --- |
| 1 | What is Structured Agentic Software Engineering? | Canonical, Hashnode, DEV, LinkedIn |
| 2 | Why agent work needs explicit workspaces and state | Canonical, DEV, Hashnode, HN if technical enough |
| 3 | ChangeSpecs, beads, and durable handoffs | Canonical, DEV, Hashnode |
| 4 | Memory, skills, and project-local context | Canonical, Hashnode, LinkedIn |
| 5 | Multi-agent work without losing control | Canonical, DEV, LinkedIn |
| 6 | Lessons from building SASE in public | Canonical, Hashnode, Medium/LinkedIn |

## Channel-Specific Editing

Do not paste the same text everywhere without adjustment.

| Channel | Edit |
| --- | --- |
| Canonical | Full post, strongest diagrams, complete links, durable wording. |
| Hashnode | Mostly full post; keep code and diagrams; set canonical URL if republishing. |
| DEV | Full technical post; use DEV tags and `series`; reduce abstract/product sections. |
| LinkedIn | 400-900 word essay/excerpt; add concrete example; link to full post. |
| Substack | Email-oriented version with stronger narrative intro and clear next-post preview. |
| Medium | Polished essay version; avoid overly repo-specific details unless relevant. |
| HN/Reddit/Lobsters | Link post plus a short, factual comment explaining what is novel. |

## Platform Ranking for SASE

| Rank | Site | Use |
| --- | --- | --- |
| 1 | Canonical SASE site (Astro on Cloudflare Pages or similar) | Source of truth and long-term archive. |
| 2 | Hashnode | Best developer-blog platform fit for the series. |
| 3 | DEV Community | Best feed for practical engineering posts. |
| 4 | LinkedIn | Best professional audience beyond hands-on developers. |
| 5 | Buttondown (or Beehiiv) | Best if email/community is a goal; pick by simplicity vs. growth tooling. |
| 6 | r/LocalLLaMA / r/AI_Agents / r/LangChain | Best targeted AI-agent audience for SASE's niche. |
| 7 | Hacker News (regular submission, not Show HN) | Best generalist technical reach when a post has a sharp hook. |
| 8 | Lobsters | Best high-signal technical audience; needs invite and tag discipline. |
| 9 | Medium | Useful optional mirror, especially for broader essays. |
| 10 | Ghost | Best later upgrade if SASE becomes a full publication. |
| 11 | Bear Blog / Mataroa / Micro.blog | Best holding pattern if `sase.dev/blog` is delayed. |
| 12 | Substack | Best when in-platform discovery network is the strategy. |

## Open Questions

- **Voice and home:** Should the canonical voice be `sase.dev/blog` as project publication or Bryan's personal blog as
  founder narrative? Decision criterion: if the goal includes contributors and users, project-domain wins; if the goal
  is reputation and hiring leverage, personal-domain wins. A hybrid (`bryanbugyi.dev` cross-publishing to
  `sase.dev/blog` with canonical at the personal site) is also viable.
- **Primary audience:** Contributors, users, sponsors/customers, or general technical reputation? Each implies a
  different default channel: contributors → DEV + GitHub, users → Hashnode + Discord, sponsors → LinkedIn +
  newsletter, reputation → HN + Lobsters.
- **Branding ramp:** Should posts be written under "SASE" branding immediately, or should early posts be personal
  essays that introduce the concept before pushing a project identity?
- **Newsletter from day one?** RSS plus LinkedIn covers most readers for the first month, but list-building gets harder
  the longer you wait. A free Buttondown form embedded from post #1 is the lowest-cost middle ground.
- **Static-site generator choice:** Astro is the strongest 2026 default, but if the SASE org already runs Hugo or
  Next.js elsewhere, prefer that for repo-mono-skill reasons.
- **Video companion:** Worth the editing time for SASE specifically? The agentic-coding niche rewards screen
  recordings, but only if the production cost stays low.

## Sources

- Google Search Central, canonical duplicate URL guidance:
  <https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls>
- Hashnode Blogs introduction:
  <https://docs.hashnode.com/blogs/getting-started/introduction>
- Hashnode GitHub publish/backup docs:
  <https://docs.hashnode.com/help-center/github/how-to-set-up-github-as-source>,
  <https://docs.hashnode.com/help-center/github/how-to-backup-articles-to-github>
- Hashnode import, newsletter, and canonical docs:
  <https://docs.hashnode.com/blogs/blog-dashboard/import>,
  <https://docs.hashnode.com/blogs/blog-dashboard/newsletters>,
  <https://docs.hashnode.com/help-center/hashnode-editor/how-to-set-a-canonical-link>
- DEV editor guide:
  <https://dev.to/p/editor_guide/>
- Medium canonical/import docs:
  <https://help.medium.com/hc/en-us/articles/360033930293-Set-a-canonical-link>,
  <https://help.medium.com/hc/en-us/articles/214550207-Importing-a-post-to-Medium>
- LinkedIn newsletters help:
  <https://www.linkedin.com/help/linkedin/answer/a522525/linkedin-newsletters?lang=en>
- Substack cost, import, and custom domain docs:
  <https://support.substack.com/hc/en-us/articles/360037607131-How-much-does-Substack-cost>,
  <https://support.substack.com/hc/en-us/articles/360037830351-How-do-I-import-my-posts-from-another-platform-such-as-Mailchimp-WordPress-Medium-or-Ghost>,
  <https://support.substack.com/hc/en-us/articles/360051222571-How-do-I-set-up-my-custom-domain-on-Substack>
- Ghost publishing and pricing:
  <https://docs.ghost.org/publishing/>,
  <https://ghost.org/pricing>
- Jekyll GitHub Pages and posts docs:
  <https://jekyllrb.com/docs/github-pages/>,
  <https://jekyllrb.com/docs/posts/>
- Astro vs Hugo 2026 comparisons:
  <https://criztec.com/hugo-vs-astro/>,
  <https://thesoftwarescout.com/best-static-site-generators-2026-astro-next-js-hugo-more/>
- Newsletter platform comparisons:
  <https://www.beehiiv.com/comparisons/substack>,
  <https://buttondown.com/comparisons/beehiiv>,
  <https://newsletter.co/buttondown-review/>
- Bear Blog / Mataroa / Micro.blog:
  <https://www.blogsareback.com/guides/start-a-blog/simple-platforms>,
  <https://mataroa.blog/>,
  <https://verysimpleblogging.com/bear-blog/>
- Hacker News guidelines:
  <https://news.ycombinator.com/showhn.html>,
  <https://news.ycombinator.com/newsguidelines.html>
- Lobsters about and self-promo:
  <https://lobste.rs/about>,
  <https://lobste.rs/s/zdyeou/submitting_your_own_stuff>
- AI-agent community indexes:
  <https://github.com/danielrosehill/Awesome-AI-Subreddits>,
  <https://github.com/caramaschiHG/awesome-ai-agents-2026>,
  <https://agentsindex.ai/r-ai-agents>,
  <https://agentsindex.ai/r-localllama>
- Privacy analytics options:
  <https://openpanel.dev/articles/self-hosted-web-analytics>,
  <https://openpanel.dev/articles/open-source-web-analytics>
