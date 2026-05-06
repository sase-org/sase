# Publishing a SASE Blog Series: Site Options and Workflow

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
| Optional newsletter home | Substack or Ghost | Use if the goal is a recurring email relationship, not just public technical posts. |
| Broad mirror | Medium | Useful for reach and imports, but weaker for developer ownership than Hashnode/DEV. |

My bias: start with canonical site + Hashnode + DEV + LinkedIn. Add Substack only if email subscribers become a primary
goal. Add Medium only if a specific publication or audience segment justifies the extra formatting pass.

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

Good implementation choices:

- GitHub Pages + Jekyll. GitHub Pages is free hosting for public pages on `github.io` or a custom domain, and Jekyll is
  blog-aware with Markdown post files:
  <https://jekyllrb.com/docs/github-pages/> and <https://jekyllrb.com/docs/posts/>.
- Hugo, Astro, Eleventy, or Next.js if the SASE site already uses one of them.
- A docs-site-like `/blog/` under the main SASE website if the goal is project credibility over personal writing.

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

DEV's editor uses Markdown with Jekyll-style front matter. It supports `canonical_url`, up to four tags, `cover_image`,
and a `series` field: <https://dev.to/p/editor_guide/>.

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

### Substack

Best for:

- recurring reader relationship;
- email-first audience;
- founder/essay style;
- eventual paid/community content.

Substack is free for publishing and charges a 10% platform fee on paid subscriptions:
<https://support.substack.com/hc/en-us/articles/360037607131-How-much-does-Substack-cost>. It can import posts from
Medium, Ghost, WordPress, Mailchimp, Beehiiv, Tumblr, Blogspot, RSS, and CSV:
<https://support.substack.com/hc/en-us/articles/360037830351-How-do-I-import-my-posts-from-another-platform-such-as-Mailchimp-WordPress-Medium-or-Ghost>.
Custom domains require a one-time fee:
<https://support.substack.com/hc/en-us/articles/360051222571-How-do-I-set-up-my-custom-domain-on-Substack>.

Tradeoffs:

- Excellent when the point is email.
- Less developer-native than Hashnode/DEV.
- Paid subscription economics and platform culture may not match an open-source engineering series.

Recommendation: wait until there is a clear newsletter strategy. Use `sase.substack.com` or `newsletter.sase.dev` only
if email becomes central.

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
| 1 | Canonical SASE site | Source of truth and long-term archive. |
| 2 | Hashnode | Best developer-blog platform fit for the series. |
| 3 | DEV Community | Best feed for practical engineering posts. |
| 4 | LinkedIn | Best professional audience beyond hands-on developers. |
| 5 | Substack | Best if email/community is a goal. |
| 6 | Medium | Useful optional mirror, especially for broader essays. |
| 7 | Ghost | Best later upgrade if SASE becomes a full publication. |

## Open Questions

- Should the canonical voice be `sase.dev/blog` as project publication or Bryan's personal blog as founder narrative?
- Is the primary goal contributors, users, sponsors/customers, or general technical reputation?
- Should posts be written under "SASE" branding immediately, or should early posts be personal essays that introduce the
  concept before pushing a project identity?
- Does SASE need a newsletter signup from day one, or is RSS plus LinkedIn enough for the first month?

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
