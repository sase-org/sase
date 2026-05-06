# SASE Blog Series Publishing Platform Decision Matrix

Date: 2026-05-06 (revised 2026-05-06 to add scoring rubric, decision-by-goal flow, gotchas, pre-launch plumbing,
AI-agent communities, channel-edit matrix, KPI baselines, and verified 2026 platform updates)

Sibling reference: [`sase_blog_series_publishing_sites.md`](./sase_blog_series_publishing_sites.md) — broader options
survey. This file is the decision-focused companion: criteria, scoring, and rules for picking and running the stack.

## Question

Where should a 5-10 part SASE blog series be published so it reaches the right technical audience while preserving
ownership, search equity, and a sane authoring workflow?

## Recommendation

Use a canonical-first publishing model:

1. Publish the canonical version on a SASE-controlled site, ideally `sase.dev/blog` or `blog.sase.dev`.
2. Cross-post technical installments to Hashnode and DEV with canonical links pointing back to the SASE site.
3. Publish shorter LinkedIn-native excerpts for engineering leaders, founders, and professional-network readers.
4. Add Buttondown only if email subscriptions become a first-class goal.
5. Treat Substack, Medium, Hacker News, Lobsters, Reddit, and AI-agent communities as distribution channels, not the
   source of truth.

The highest-confidence launch stack is:

| Role | Platform | Decision |
| --- | --- | --- |
| Canonical archive | SASE-owned static site | Best long-term home. Own URLs, Markdown source, SEO, RSS, analytics, and migration path. |
| Developer mirror | Hashnode | Strong developer fit; supports Markdown-oriented writing, custom domains, GitHub publishing/backup, newsletters, and canonical URLs. |
| Developer feed | DEV Community | Good for practical code-heavy posts; supports `canonical_url`, `series`, and Markdown front matter. |
| Professional distribution | LinkedIn articles/newsletter | Good for process, leadership, and "why this matters" posts, but weak as the canonical archive. |
| Email list | Buttondown | Best SASE-shaped newsletter choice if needed: minimalist, Markdown-friendly, custom-domain friendly, and cheaper to start than heavier newsletter stacks. |

## Decision Criteria and Weights

Score each candidate platform against the criteria below. Weights reflect what matters for a technical, open-source,
agentic-software-engineering project. Higher is better; weight × score then sum per platform.

| Criterion | Weight | What "high" means |
| --- | --- | --- |
| URL/content ownership | 5 | Custom domain, Markdown-in-Git source, full migration path, no lock-in. |
| Canonical/SEO control | 5 | Supports `rel=canonical` or original-URL field, sitemap, structured data. |
| Developer audience fit | 4 | Reader base is engineers, not generalists or marketers. |
| Markdown + code workflow | 4 | First-class fenced code, syntax highlighting, front matter, drafts, previews. |
| Discovery/distribution | 3 | Native feed, tags, search, network effects beyond your existing followers. |
| Series support | 3 | Native series/multi-part metadata that surfaces other parts to readers. |
| Email/newsletter integration | 3 | Built-in or trivial-to-bolt-on email capture. |
| Analytics ownership | 2 | First-party, privacy-friendly, exportable. |
| Operational cost | 2 | Time and money to set up and maintain over a 6-month series. |
| Strategic optionality | 2 | Can you migrate off cleanly without breaking URLs? |

Quick scoring against this rubric (out of 5 per criterion; not exhaustive but enough for a launch decision):

| Platform | Own | SEO | DevAud | MD/Code | Discovery | Series | Email | Analytics | OpCost | Optional | Weighted |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SASE-owned static site | 5 | 5 | 4 | 5 | 1 | 4 | 3 | 5 | 2 | 5 | 121 |
| Hashnode | 3 | 4 | 5 | 5 | 4 | 4 | 4 | 3 | 5 | 4 | 124 |
| DEV Community | 2 | 3 | 5 | 5 | 5 | 5 | 1 | 2 | 5 | 3 | 109 |
| LinkedIn (article/newsletter) | 2 | 2 | 2 | 1 | 4 | 1 | 4 | 2 | 5 | 2 | 70 |
| Substack | 2 | 3 | 3 | 2 | 4 | 1 | 5 | 3 | 4 | 3 | 87 |
| Buttondown | 4 | 3 | 4 | 5 | 1 | 1 | 5 | 4 | 4 | 4 | 95 |
| Beehiiv | 3 | 3 | 3 | 3 | 3 | 1 | 5 | 4 | 3 | 3 | 84 |
| Ghost (Pro) | 4 | 4 | 3 | 4 | 2 | 2 | 5 | 4 | 3 | 4 | 100 |
| Medium | 2 | 3 | 2 | 3 | 3 | 2 | 1 | 1 | 5 | 2 | 65 |

Read this as guidance, not gospel — weights shift if SASE's primary goal changes. Key takeaway: SASE-owned site and
Hashnode tie at the top, DEV is close behind. That matches the canonical + 2-mirror recommendation.

## Decision by Primary Goal

The "right" stack depends on what SASE wants the series to do. Use this lookup before treating the recommendation as
fixed.

| If the primary goal is... | Then prioritize | And demote |
| --- | --- | --- |
| Build contributor pipeline | DEV + Hashnode + GitHub Discussions + RSS | Substack, LinkedIn newsletter |
| Build user/early-adopter base | Hashnode + Discord/Slack + selective HN | Medium, Beehiiv |
| Build founder/leader reputation | Personal canonical + LinkedIn newsletter + selected HN | DEV, Lobsters |
| Build sponsor/customer pipeline | LinkedIn newsletter + Buttondown email + canonical site | DEV feed reactions |
| Build SEO/long-tail traffic | Canonical site + Hashnode mirror with original URL | Pure-LinkedIn or pure-Substack stack |
| Build a paid-subscription business | Substack or Ghost + canonical site as backup | DEV (no paywall) |

If two of these goals are tied, default to the developer-mirror stack (Canonical + Hashnode + DEV) — it's strictly
better than the alternatives for "no decision yet" because it preserves optionality.

## Decision Logic

### Why Not Pick One Hosted Platform as the Only Home?

SASE is a technical project and concept that should remain durable. A 5-10 part series may become onboarding material,
documentation-adjacent strategy writing, contributor context, and launch collateral. That argues for a home controlled by
the SASE project rather than a platform-owned URL.

Google's canonical guidance is the core SEO reason: canonical URLs help search engines consolidate signals across
duplicate or similar pages and let publishers say which URL should represent the content. That means the SASE site should
be the canonical source and mirrors should point back to it.

### Canonical Site

A SASE-owned static site is the best source of truth.

Pros:

- Full ownership of URLs and Markdown source.
- Easy to keep posts in Git with the same discipline as SASE docs.
- Native fit for RSS, OpenGraph metadata, canonical tags, sitemaps, and privacy-friendly analytics.
- Better long-term credibility for an open-source engineering system than a platform subdomain.

Cons:

- Discovery is weaker than Hashnode, DEV, LinkedIn, or Substack.
- Requires site setup, visual polish, RSS, analytics, and deploy plumbing.

Implementation preference:

- Use Astro if starting fresh. Astro content collections are built for local Markdown/MDX content and blog-like static
  pages.
- Use GitHub Pages/Jekyll if the priority is almost-zero infrastructure and the site can stay simple.
- Use the existing SASE docs/site stack if one already exists elsewhere; the platform choice is less important than
  keeping the canonical URLs under SASE control.

### Hashnode

Hashnode is the strongest developer-blog mirror.

Pros:

- Developer-focused audience and editor.
- Markdown/code support.
- GitHub publishing and backup paths.
- Newsletter and analytics built in.
- Canonical/original URL support for republished posts.
- 2026 free tier: custom domain mapping, AI writing assistance, analytics, unlimited posts at $0/mo. Pro is $7/mo
  (annual: $70/yr) for advanced features like newsletters at scale and team workflows.

Cons:

- Still a platform dependency.
- Less controlled than a custom SASE site for brand, analytics, and long-term migration.

Use Hashnode for nearly full cross-posts of the technical posts. Set the original URL to the SASE canonical post.

### DEV Community

DEV is useful for feed-driven developer discovery.

Pros:

- Markdown/front-matter workflow.
- `canonical_url` support.
- `series` metadata for a multi-part blog series.
- Good audience for practical engineering posts.

Cons:

- Four-tag limit requires careful tag choices.
- Less suitable for high-level essays or project-positioning pieces.
- Feed discovery is bursty.
- Per-article attention has trended down through 2025-2026 as overall posting volume rose; the platform is more
  saturated than two years ago, so a single post is less likely to top the feed without strong tags and timing.
- The `ai` tag has overtaken `webdev` and `programming` since mid-2025; SASE's agent-focused angle should benefit, but
  expect competition for visibility.

Use DEV for hands-on posts: ChangeSpecs, workspaces, xprompts, multi-agent orchestration, memory, skills, mentors, and
operational lessons.

Suggested 4-tag bundles:

- Concept post: `ai`, `agents`, `softwareengineering`, `productivity`.
- ChangeSpecs/workflow post: `ai`, `agents`, `git`, `productivity`.
- Memory/skills post: `ai`, `agents`, `architecture`, `tutorial`.
- Multi-agent post: `ai`, `agents`, `architecture`, `discuss`.

### LinkedIn

LinkedIn is a distribution channel, not the canonical archive.

Pros:

- Reaches engineering managers, founders, platform leads, investors, and professional peers.
- LinkedIn newsletters can notify subscribers by app, push, and email.
- Good for "why this matters for teams" framing.

Cons:

- Poor Markdown workflow.
- Weak canonical/SEO control.
- Verbatim technical cross-posts often read poorly in the LinkedIn feed.

Use LinkedIn for 400-900 word excerpts or adapted essays that link to the full canonical article.

### Buttondown, Substack, Beehiiv, and Ghost

Do not start with a newsletter platform unless email capture is a real goal. For a SASE launch series, web reach and
developer credibility matter first.

| Platform | Fit for SASE | Notes |
| --- | --- | --- |
| Buttondown | Best optional email layer | First 100 subscribers are free; Markdown/custom-domain friendly; features are modular add-ons. |
| Substack | Good only if Substack network effects are the strategy | Free to publish, but paid subscriptions have a 10% Substack fee plus Stripe fees; custom domains have a one-time $50 fee. |
| Beehiiv | Good for growth experiments | Free Launch tier up to 2,500 subscribers; stronger growth tooling than SASE likely needs at first. |
| Ghost | Good later if SASE becomes a publication | Strong ownership story, but more CMS/newsletter infrastructure than needed for the first 5-10 posts. |
| Kit (formerly ConvertKit) | Good if creator-funnels matter | Free Newsletter plan up to 10,000 subscribers; unlimited broadcasts, forms, and landing pages. Creator plan starts at $33/mo annual ($39/mo monthly) for automations. Mainly relevant if SASE eventually does paid courses or digital products. |

Recommendation: embed or link a simple Buttondown signup from post #1 if collecting email addresses matters. Defer a
full newsletter publication until after the first 3-4 posts show which audience is responding.

### Medium

Medium is optional. It supports canonical links and its import tool can apply a canonical URL to the original source, but
its audience is less specifically developer-tooling focused than Hashnode or DEV. Use Medium only for polished,
broader-audience essays or if a relevant Medium publication offers meaningful reach.

### Hacker News, Lobsters, Reddit, and AI-Agent Communities

These are promotion targets, not hosts.

Guidelines:

- Submit blog posts to Hacker News as regular links, not "Show HN"; HN says Show HN is for things readers can try, and
  blog posts/newsletters are off-topic for Show HN.
- Use the original title on HN and avoid promotional language.
- Lobsters is computing-focused, invite-based, tag-driven, and explicitly discourages using it as a write-only
  promotion channel. Self-promo guidance is "less than a quarter" of submitted stories and comments; in practice the
  enforcement threshold kicks in only when self-authored stories exceed half. Self-authored links also get a small
  +0.25 hotness boost, so a sharp technical post from an active commenter performs reasonably well.
- Reddit and AI-agent communities can work well for specific posts, but only when the post has a concrete technical
  hook and the submission follows each community's self-promotion rules.

#### AI-agent communities most relevant to SASE (May 2026)

These match SASE's audience: agent builders, plan-first workflows, multi-agent orchestration, memory/skills, agent
governance. Treat each as a link-share target with channel-specific etiquette, not a host.

| Community | Why it fits SASE | Posting cue |
| --- | --- | --- |
| r/AI_Agents | Agent builders explicitly debating cost, reliability, governance | Lead with the concrete primitive (ChangeSpecs, workspaces) and a real-world failure it prevents. |
| r/LocalLLaMA | Local-model + agent practitioners | Only post if the SASE concept applies to local-model agents, not just hosted models. |
| r/LangChain | Workflow/graph builders debugging cyclic agents | Frame the SASE pattern in terms of LangChain pain points it solves. |
| r/AutoGenAI | Multi-agent orchestration | Multi-agent xprompt and retry-chain posts fit best here. |
| r/MachineLearning | Research-leaning | Tag posts `[D]` discussion or `[P]` project; needs measured claims. |
| r/programming | Generalist developer feed | Strict against blog spam; needs a sharp technical title. |
| r/devtools | Tool builders | Editor integrations, CLI ergonomics, and skill workflows are on-topic. |
| r/ChatGPTCoding | Coding-with-LLMs hobbyists | Higher tolerance for opinion and DX writing. |
| Discord/Slack: LangChain, LlamaIndex, AutoGen, Aider, OpenDevin, Cursor | Builder communities | Look for a `#showcase` or `#share` channel; ask the channel etiquette first. |

The 2026 trend in these communities favors posts about: explicit plan/state hand-offs, drift, governance and review
loops, and what happens after the demo. SASE has a story to tell on every one of those — pick the angle per post.

## Platform Gotchas Quick Reference

The cheapest way to learn these is here, not the day before launch.

| Platform | Gotcha |
| --- | --- |
| SASE-owned site | Static-site `rel=canonical` must be self-referential on the canonical URL itself. Search engines treat canonical as a strong hint, not a directive — they can still pick a different URL if signals conflict. Audit with Google Search Console after launch. |
| Hashnode | Free custom-domain mapping requires CNAME plus 24-48h propagation. The original-URL field is per-post; forgetting it on a republished post produces a duplicate canonical. |
| DEV Community | Hard 4-tag cap. `series` field is exact-string match — typos create new orphan series. `cover_image` recommended at 1000x420 px. Drafts produce a public-but-unlisted preview URL. |
| LinkedIn | Markdown is not supported in articles or newsletters; expect manual reformatting. Engagement decays fast (~24h half-life) so cross-post timing matters. Newsletters force a subscribe prompt to the author's followers, which can feel pushy if the SASE/personal split is wrong. |
| Substack | 10% platform fee on paid subs (plus Stripe). Custom domain has a one-time $50 fee. SEO is platform-mediated. |
| Buttondown | Free tier capped at 100 subscribers — plan migration path before scale, not after. |
| Beehiiv | Free tier reaches 2,500 subscribers but layers on growth features (referrals, ads, boosts) you may not want. |
| Ghost (Pro) | No free tier; cheapest hosted plan starts around $9-11/mo. Self-hosted is free but you own ops. |
| Medium | Membership paywall and friction prompts on every read; canonical works but UX is unfriendly to first-time readers. |
| Hacker News | Show HN is for things readers can try; blog posts are off-topic there — submit as a regular link. Voting rings and comment seeding are detectable and penalized. |
| Lobsters | Invite-only. Tag list is fixed; mismatched tags get the post removed. |
| r/* (Reddit) | Each sub has its own self-promo ratio (often 10:1). Subreddit auto-mods catch marketing language in titles. |
| Bluesky / X / Mastodon | Link previews depend on OpenGraph tags; missing OG image kills CTR. Mastodon links get fewer auto-previews than Bluesky. |

## Pre-Launch Plumbing Checklist

Set these up before post #1, in this order. Skipping any is cheap now and expensive later.

1. **DNS and hosting.** Custom domain pointing to canonical site (Cloudflare Pages, Vercel, Netlify, or GitHub Pages).
   HTTPS verified.
2. **Canonical tags.** Self-referential `<link rel="canonical">` on every post on the canonical site. Sitemap.xml
   listing all posts. Robots.txt allowing crawl.
3. **OpenGraph + Twitter Card metadata.** Default OG image at 1200x630 px and per-post override field. Verified by
   pasting URLs into LinkedIn Post Inspector and the OpenGraph debugger of choice.
4. **RSS feed.** Validates against the W3C feed validator. Includes either full content or a substantial summary plus
   stable canonical link.
5. **Privacy-friendly analytics.** Plausible (~$9/mo for 10k visitors), Fathom (~$14-15/mo for 100k pageviews), or
   GoatCounter (free for personal/non-commercial; $5/mo commercial up to 100k pageviews). Avoid GA4 unless something
   specifically requires it.
6. **Email-capture form.** Even if a newsletter platform isn't picked yet, embed a single form (Buttondown free,
   Hashnode newsletter, or a static signup form that emails you) so reader interest from week one is not lost.
7. **Series index page.** A `/blog/series/sase/` (or equivalent) page listing all parts in order, with a stable URL
   that can be referenced from each post.
8. **Front-matter template.** A repo-checked-in template enforcing `title`, `slug`, `date`, `description`,
   `canonical_url`, `tags`, `series`, and `cover_image` for every post.
9. **Search Console + Bing Webmaster Tools.** Submit sitemap; verify post indexing within 48h of publish.
10. **Backup and archive.** Hashnode → GitHub backup configured if Hashnode is the mirror; SASE site source in Git;
    canonical-site export ritual documented.

## Channel-Specific Editing Rules

Do not paste the same text into every channel. The minimum edit per channel:

| Channel | Edit |
| --- | --- |
| Canonical site | Full post, strongest diagrams, complete links, durable wording. Never gets shortened. |
| Hashnode | Mostly full post; keep code and diagrams; set original/canonical URL; pick 5 tags carefully. |
| DEV | Full technical body; reduce abstract framing; use 4 tags + `series`; add a 1-line `canonical_url` note at the top. |
| LinkedIn article | 400-900 words; lead with a sharp claim; remove dense code blocks; link to canonical for full version. |
| LinkedIn newsletter | Same as article, but written as if the reader subscribed; include "what's next in the series." |
| Substack (if used) | Email-oriented opening; clear next-post preview; less code, more narrative. |
| Medium | Polished essay version; remove repo-specific details unless central; rely on canonical import. |
| Bluesky / X / Mastodon | Three-post thread max: claim, evidence, link. Image card with OG. |
| HN / Reddit / Lobsters | Link only; comment factually about what's novel; do not seed upvotes or replies. |

## KPI Baselines and Targets

Track these per post and per channel for the first 90 days. The goal is to learn which channels actually work for
SASE, not to chase vanity numbers.

Per post:

- Unique visitors.
- p50 time-on-page; share scrolling past the halfway mark.
- Inbound links from new domains in the 7-day window after publish.
- New GitHub stars/issues attributable to the post (UTM or referral).
- New newsletter or RSS subscribers attributable.

Per channel:

- Referral source breakdown for visitors and conversions (signup, GitHub click, repo view).

Per series:

- % of readers who read >=2 posts in the series.
- RSS subscriber growth.
- Email subscriber growth.

Realistic baselines for a small open-source project blog launching cold:

- 300-1,500 unique readers on a "good" technical post in week one.
- 3-10x that on a Hacker News or Lobsters hit.
- 1-3% of readers convert to RSS or email follow.
- Cross-posts on Hashnode and DEV typically add 30-200% on top of canonical traffic in the first week, depending on
  tag picks and feed luck.

If a post falls below the low end of these baselines, the cause is usually one of: weak hook in the first 200 words,
missing OpenGraph image, wrong DEV tags, or no cross-post at all in the first 24-48h.

## Anti-Patterns

- **Cross-posting without canonical URLs.** Splits SEO and confuses readers.
- **Marketing language in HN/Lobsters/Reddit titles.** Instant flag/downvote on technical communities.
- **Inconsistent series naming.** DEV's `series`, Hashnode's series, and the canonical site's series page must all use
  the exact same string or the cross-platform reading experience fragments.
- **Canonical site lagging the syndicated mirrors.** Readers hit Hashnode first, then there is no canonical URL to
  migrate to later.
- **Mirroring everything to LinkedIn unedited.** LinkedIn's tone and length differ; verbatim mirrors read as
  low-effort.
- **Starting Substack and Ghost and Medium imports in the same week.** Pick one syndication and one optional
  newsletter; add channels only after a successful post on the existing ones.
- **No email capture from day one.** RSS-only means the readers who care most have no fallback if they switch readers.
- **Treating "post in 8 places" as the strategy.** Each channel needs the smallest channel-specific edit; otherwise
  the volume dilutes signal.
- **Starting a video companion before posts ship.** Editing time is the top abandonment cause for solo
  developer-creators; a screen-recording per post is worthwhile only if it does not delay publication.

## Platform Ranking

1. SASE-owned canonical site.
2. Hashnode mirror.
3. DEV Community mirror.
4. LinkedIn excerpt/newsletter.
5. Buttondown signup/newsletter if email matters.
6. Hacker News, Lobsters, Reddit, and AI-agent communities for selective distribution.
7. Medium for selected broader essays.
8. Substack only if its reader network is explicitly part of the strategy.
9. Ghost only if SASE content becomes a larger publication.
10. Beehiiv only if growth tooling becomes more important than simplicity.

## Suggested Publishing Workflow

1. Draft in Markdown in Git.
2. Publish the canonical SASE-site version first.
3. Verify canonical tag, RSS entry, sitemap, OpenGraph image, title, description, and code highlighting.
4. Cross-post to Hashnode with the original URL set.
5. Cross-post to DEV with `canonical_url`, `series`, and no more than four tags.
6. Publish a shorter LinkedIn-native version or excerpt.
7. Share selectively on HN/Lobsters/Reddit/community channels only when the post has a strong technical hook.
8. Review channel results after 48-72 hours: referrals, GitHub stars/issues, RSS/email signups, comments, and inbound
   links.

### Per-Post Time Window

| Hour | Action |
| --- | --- |
| T+0 | Publish canonical, verify OG/RSS/canonical tags, share with personal Bluesky/X/Mastodon. |
| T+2-4h | Cross-post to Hashnode (original URL set) and DEV (canonical_url + series). |
| T+24h | LinkedIn excerpt with canonical link. Reddit/AI-agent community share if there's a sharp hook. |
| T+48h | Hacker News submission as a regular link if the post stands on its own technical claim. |
| T+72h | Capture metrics, update series index page, queue any reader follow-ups. |

## Series Cadence Suggestion

A 6-post series over 6-8 weeks is the easiest to actually finish while still covering the major SASE concepts.
Suggested per-post angles and best-fit channels:

| Post | Working angle | Best channels |
| --- | --- | --- |
| 1 | What is Structured Agentic Software Engineering? | Canonical, Hashnode, DEV, LinkedIn |
| 2 | Why agent work needs explicit workspaces and state | Canonical, DEV, Hashnode, HN if the technical hook is sharp |
| 3 | ChangeSpecs, beads, and durable handoffs | Canonical, DEV, Hashnode, r/AI_Agents |
| 4 | Memory, skills, and project-local context | Canonical, Hashnode, LinkedIn, r/LangChain |
| 5 | Multi-agent work without losing control | Canonical, DEV, LinkedIn, r/AutoGenAI |
| 6 | Lessons from building SASE in public | Canonical, Hashnode, Medium/LinkedIn, HN |

## Open Decisions

- **Project vs personal canonical voice.** Project blog (`sase.dev/blog`) is better for durable project credibility,
  contributor pipeline, and SEO around the SASE term. Personal blog is better for founder narrative and reputation.
  A hybrid (personal-domain canonical, cross-published to `sase.dev/blog` with the personal site as canonical) is a
  reasonable compromise but increases operational cost.
- **Concept-first vs practical-first post.** A practical, code-heavy post performs better on developer feeds and HN; a
  concept essay defines the SASE category better. Recommended split: concept post #1 on canonical + LinkedIn,
  immediately followed by a practical post #2 on canonical + Hashnode + DEV.
- **Email capture from day one?** RSS plus GitHub follows cover most readers for the first month, but list-building
  gets harder the longer you wait. Lowest-cost middle ground: a free Buttondown form embedded from post #1.
- **Series length.** Six posts is the recommended target — long enough to cover ChangeSpecs, workspaces, memory,
  skills, multi-agent, and a "what we learned" closer; short enough to actually finish.
- **Static-site generator.** Astro is the strongest 2026 default; if SASE already runs Hugo or Next.js elsewhere,
  prefer that for repo-mono-skill reasons.
- **Video companion.** Worth recording a 5-10 minute screen recording per post if production cost stays low (OBS +
  Descript). Skip podcasting until there's a clear audience pulling for it.

## Sources

- Google Search Central canonical URL guidance:
  <https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls>
- Hashnode Blogs introduction:
  <https://docs.hashnode.com/blogs/getting-started/introduction>
- Hashnode publish from GitHub:
  <https://docs.hashnode.com/help-center/github/how-to-set-up-github-as-source>
- Hashnode canonical/original URL docs:
  <https://docs.hashnode.com/help-center/hashnode-editor/how-to-set-a-canonical-link>
- DEV editor guide:
  <https://dev.to/p/editor_guide/>
- LinkedIn newsletters help:
  <https://www.linkedin.com/help/linkedin/answer/a522525/linkedin-newsletters?lang=en>
- Buttondown pricing:
  <https://buttondown.com/pricing>
- Substack creator pricing:
  <https://support.substack.com/hc/en-us/articles/360037607131-How-much-does-Substack-cost>
- Substack custom domain docs:
  <https://support.substack.com/hc/en-us/articles/360051222571-How-do-I-set-up-my-custom-domain-on-Substack>
- Beehiiv pricing:
  <https://www.beehiiv.com/pricing>
- Medium canonical and import docs:
  <https://help.medium.com/hc/en-us/articles/360033930293-Set-a-canonical-link>,
  <https://help.medium.com/hc/en-us/articles/214550207-Importing-a-post-to-Medium>
- Astro content collections:
  <https://docs.astro.build/en/guides/content-collections/>
- GitHub Pages:
  <https://pages.github.com/>,
  <https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages>
- Jekyll GitHub Pages and posts docs:
  <https://jekyllrb.com/docs/github-pages/>,
  <https://jekyllrb.com/docs/posts/>
- Hacker News Show HN and general guidelines:
  <https://news.ycombinator.com/showhn.html>,
  <https://news.ycombinator.com/newsguidelines.html>
- Lobsters about page and self-promo discussion:
  <https://lobste.rs/about>,
  <https://lobste.rs/s/zdyeou/submitting_your_own_stuff>
- Lobsters front-page algorithm explanation:
  <https://blog.nilenso.com/blog/2026/01/20/lobsters-front-page/>
- Hashnode pricing (free tier with custom domains, Pro $7/mo):
  <https://hashnode.com/pricing>
- Hashnode free custom-domain mapping changelog:
  <https://hashnode.com/changelog/free-custom-domain-mapping>
- Kit (formerly ConvertKit) pricing and free Newsletter plan:
  <https://kit.com/pricing>,
  <https://help.kit.com/en/articles/9053602-the-kit-newsletter-plan>
- DEV community engagement / 1M-article analysis:
  <https://dev.to/marina_eremina/i-analyzed-1-million-devto-articles-2022-2026-heres-what-the-data-reveals-44gm>
- Privacy analytics pricing and comparisons:
  <https://plausible.io/#pricing>,
  <https://usefathom.com/pricing>,
  <https://www.goatcounter.com/help/gc-vs-self>,
  <https://openpanel.dev/articles/self-hosted-web-analytics>
- AI-agent Reddit communities and what they discuss:
  <https://github.com/danielrosehill/Awesome-AI-Subreddits>,
  <https://github.com/caramaschiHG/awesome-ai-agents-2026>
