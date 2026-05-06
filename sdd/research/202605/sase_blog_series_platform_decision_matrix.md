# SASE Blog Series Publishing Platform Decision Matrix

Date: 2026-05-06

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

Use DEV for hands-on posts: ChangeSpecs, workspaces, xprompts, multi-agent orchestration, memory, skills, mentors, and
operational lessons.

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
  promotion channel.
- Reddit and AI-agent communities can work well for specific posts, but only when the post has a concrete technical
  hook and the submission follows each community's self-promotion rules.

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

## Open Decisions

- Should the canonical voice be a SASE project blog or Bryan's personal blog? Project blog is better for durable project
  credibility; personal blog is better for founder narrative and professional reputation.
- Should the first post be a concept essay or a practical technical post? A practical post will perform better on
  developer feeds; a concept essay may explain the SASE category better.
- Is email capture important from day one? If yes, add Buttondown now. If no, RSS plus GitHub/LinkedIn follows are enough
  for the first few posts.
- Should the series be 5, 6, 8, or 10 posts? A six-post core series is likely easier to finish while still covering the
  major SASE ideas.

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
- Lobsters about page:
  <https://lobste.rs/about>
