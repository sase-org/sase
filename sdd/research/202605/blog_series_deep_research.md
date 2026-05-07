QUESTION: I want to post a 5 to 10 part blog series on sase (see my sase-org/sase GitHub repo). Can you do some research to help me reason about what platform I should publish these blog posts on?

# REPLY

I can’t live-check 2026 platform policies, pricing, or algorithm changes because web search is disabled here. I did inspect `sase-org/sase` and I’d treat the recommendation below as repo-grounded strategy plus general platform knowledge through Aug 2025.

## Recommendation

Publish the canonical series on an owned SASE site, preferably a repo-backed docs/blog site, then syndicate individual posts to developer-discovery platforms.

My concrete pick:

**Primary home:** `sase.dev/blog` or `blog.sase.dev`, generated from the GitHub repo using **MkDocs Material** or **Docusaurus**.
**Syndication:** cross-post to **DEV.to** and/or **Hashnode** with canonical links; post short summaries to **LinkedIn**; optionally use **Substack** only for email distribution.

I would not make Medium, LinkedIn, or Substack the only home for this series.

## Why SASE wants an owned canonical blog

SASE is a technical, developer-facing system, not a general essay brand. The repo describes it as “a Python toolkit for AI-powered software engineering workflows” combining a TUI, scheduling daemon, YAML workflow engine, and pluggable LLM/VCS abstractions for managing code changes at scale . It also explicitly targets users of coding agents such as Claude Code, Gemini CLI, Codex, and external provider via plugin support .

That means your series needs to do several things well:

1. Explain a philosophy: “agent-driven software engineering should be dependable.”
2. Show concrete mechanics: ChangeSpecs, workflows, XPrompt, ACE, AXE, SDD, mentors, telemetry.
3. Include code, YAML, terminal sessions, screenshots, diagrams, and links into docs.
4. Remain useful months later as onboarding material.
5. Drive readers toward the repo, docs, and install path.

A rented platform is good for reach, but weak as the permanent source of truth. Your repo already has deep technical documentation: workflows are YAML-defined multi-step agent pipelines with control flow, parallel execution, and human-in-the-loop approval ; ChangeSpecs are structured PR/CL specs with metadata, dependencies, and status ; and SDD stores prompts, plans, roadmap material, research, and bead state close to the code . That kind of material belongs somewhere you control.

## Platform fit matrix

| Platform                        |                       Best role |        Fit for SASE | Main upside                                                                                 | Main downside                                                             |
| ------------------------------- | ------------------------------: | ------------------: | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **Owned docs/blog site**        |                  Canonical home |       **Excellent** | Durable, repo-linked, good for code/docs/diagrams, SEO, custom domain, series navigation    | Weak built-in audience; you must distribute                               |
| **DEV.to**                      |           Syndication/discovery |           Very good | Developer audience, code-friendly, good for open-source/devtools posts                      | Less ownership; feed incentives can favor shorter tactical posts          |
| **Hashnode**                    | Managed dev blog or syndication |           Very good | Developer-focused, good long-form/code support, can work well with custom-domain publishing | Still a platform dependency                                               |
| **Substack**                    |          Email/newsletter layer | Good, but secondary | Good for subscribers and serialized delivery                                                | Less ideal as canonical technical docs; code-heavy posts can feel awkward |
| **LinkedIn**                    |      Professional amplification |   Good for excerpts | Reaches engineering managers, founders, AI/devtools people                                  | Poor canonical archive, weak code/diagram experience                      |
| **Medium**                      |            Optional syndication |               Mixed | Familiar long-form UX, possible publication reach                                           | Not ideal for open-source developer trust or canonical technical content  |
| **GitHub Discussions / README** |               Community adjunct |             Limited | Close to repo and contributors                                                              | Not a blog; poor broad discovery and narrative UX                         |

## My ranked publishing options

### 1. Owned SASE blog: best primary choice

Use an owned site as the canonical source. Since SASE already has `docs/`, Markdown, diagrams, and detailed references, I’d choose one of these:

**Option A: MkDocs Material**
Best if you want a Python-native docs site with minimal JS complexity. It fits the repo’s Python identity and would let you keep docs and blog content close together.

**Option B: Docusaurus**
Best if you want a polished docs-plus-blog experience with strong series navigation, MDX, sidebars, tags, and social sharing. It is a little heavier, but excellent for devtools projects.

Either way, create a `/blog/sase-series/` landing page with:

* Part list with “next” and “previous” links.
* A permanent “start here” page.
* Links to the repo, docs, install instructions, and examples.
* RSS.
* Open Graph images for social sharing.
* Canonical URLs for cross-posts.

This is the best match because SASE’s story is cumulative. The README frames the problem as coordination pain around scheduling, prompt logic, tracking, portability, and supervision . A series page can gradually build that argument and turn each post into reusable onboarding material.

### 2. DEV.to: best developer-discovery syndication

I would cross-post most articles to DEV.to after publishing canonically. SASE is an open-source developer tool with practical primitives: ACE, AXE, XPrompt, Workflows, SDD, ChangeSpecs, Beads, Mentors, Telemetry, LLM providers, VCS providers, and query language are all first-class features in the README . That maps well to DEV.to-style posts such as:

* “Stop running coding agents as one-off terminal sessions”
* “Prompt logic as code: why SASE uses XPrompt”
* “YAML workflows for human-in-the-loop coding agents”
* “ChangeSpecs: a durable unit of work for agentic software engineering”

Use DEV.to for reach, comments, and tags, but make the top or bottom of every post point back to the canonical SASE blog.

### 3. Hashnode: viable alternative or second syndication target

Hashnode is a strong choice if you want a managed developer blog without building a site immediately. It is especially attractive if you want custom-domain publishing but do not want to maintain a static site yet.

I’d still prefer an owned repo-backed site for SASE, because the project is docs-heavy and will likely evolve into a full developer portal. But Hashnode is a reasonable “move fast” option if you want to start publishing before setting up a docs site.

### 4. LinkedIn: use for summaries, not originals

LinkedIn is useful because SASE’s thesis is not only technical. It also speaks to engineering workflow, review state, supervision, and managing code changes at scale. ACE, for example, is the primary TUI for navigating, managing, and operating on ChangeSpecs, agents, and the Axe daemon . That story can appeal to engineering leads and founders.

But LinkedIn is bad as the canonical archive. I’d post short, punchy summaries like:

> Coding agents are powerful, but the hard part is no longer one prompt. The hard part is scheduling, tracking, review, and reproducibility across dozens of agent runs. That’s what SASE is trying to structure.

Then link to the canonical post.

### 5. Substack: only if you want an email audience

Substack is good if your goal is to build a personal or project newsletter around agentic software engineering. It is not my first choice for code-heavy canonical posts, but it can be useful as a digest:

* Weekly: “Part 3 is out: XPrompt and prompt logic as code.”
* Monthly: “What we learned building SASE.”
* Launch roundup: “The complete SASE series.”

I would not put the full canonical technical series only on Substack unless email growth is your primary goal.

### 6. Medium: lowest-priority syndication

Medium is fine if you already have followers there or can get into a relevant publication. Otherwise, it is not where I’d center an open-source devtools launch. The audience fit and developer trust are weaker than an owned site plus DEV.to/Hashnode.

## Suggested publishing strategy

Start with this structure:

1. **Canonical post on SASE site**
2. **Full or lightly edited cross-post on DEV.to / Hashnode**
3. **Short LinkedIn post with a strong thesis**
4. **Selective sharing to Hacker News, Reddit, Lobsters, Python/AI/devtools communities only for the strongest posts**
5. **End-of-series roundup post pinned from the README**

The canonical post should be the one you link from GitHub, docs, future talks, issue replies, and announcements.

## Series shape that fits the platform choice

A 5–10 part series should not read like release notes. It should start with the problem and gradually reveal the system.

A strong 8-part version would be:

| Part | Working title                                                    | Best primary audience                        |
| ---: | ---------------------------------------------------------------- | -------------------------------------------- |
|    1 | Why coding agents need an orchestration layer                    | Broad devtools / AI engineers                |
|    2 | ChangeSpecs: a durable unit of agentic work                      | Senior engineers, code review/process people |
|    3 | XPrompt: prompt logic as code                                    | Agent/prompt/workflow builders               |
|    4 | Workflows: YAML pipelines for coding agents                      | Automation-heavy developers                  |
|    5 | ACE and AXE: supervising foreground and background agent work    | Power users of coding agents                 |
|    6 | SDD: keeping prompts, plans, research, and roadmap close to code | Teams adopting spec-driven workflows         |
|    7 | Provider portability: Claude, Codex, Gemini, VCS plugins         | Devtools / platform engineers                |
|    8 | Toward dependable agent-driven software engineering              | Broad conclusion / launch essay              |

The owned site handles the coherent arc. DEV.to/Hashnode provide discovery for each tactical part. LinkedIn carries the broader workflow thesis.

## What I would do next

I’d create a small `blog/` or `docs/blog/` area in the repo, publish Part 1 on an owned SASE domain, and cross-post it to DEV.to with a canonical link. After two or three posts, add a series landing page and link it from the README near the overview/vision section.

---

QUESTION: How should I host my canonical blog (I'm thinking I'll use the sase.sh domain name)?

# REPLY

I’d host it as a **static, repo-backed site at `https://sase.sh`**, with the blog as a first-class section of the product/docs site:

```text
https://sase.sh/                         product landing page
https://sase.sh/docs/                    technical docs
https://sase.sh/blog/                    canonical blog
https://sase.sh/blog/<slug>/             canonical post URLs
https://sase.sh/series/agentic-se/       series landing page
```

I can’t live-check 2026 hosting prices or platform limits from here, so I’d verify the final Cloudflare/GitHub/Vercel details before committing. The architecture recommendation itself is stable: **static site, Markdown in git, deploy from CI, own the canonical URLs.**

## My recommendation

Use:

**Generator:** **MkDocs Material**
**Hosting:** **Cloudflare Pages**
**Source:** same GitHub repo, under `docs/` plus a `mkdocs.yml`
**Domain:** `sase.sh` as the canonical apex domain
**Syndication:** DEV.to / Hashnode / LinkedIn posts link back to `sase.sh`

This fits SASE particularly well because the repo is already a Python/devtool project: the README describes SASE as a Python toolkit for agentic software engineering workflows , and the project already has a docs-heavy surface area: ACE, AXE, XPrompt, Workflows, SDD, ChangeSpecs, Beads, Mentors, telemetry, LLM providers, VCS providers, and query language are all top-level concepts/features . A static docs/blog site will age better than a hosted CMS or newsletter as the canonical source.

## Why MkDocs Material over Docusaurus or a CMS

For SASE, I’d prefer **MkDocs Material** because:

* SASE is already Python-based; the package is defined as a Python project named `sase` with Python `>=3.12` .
* The repo already expects Python/`uv`/`just` in the dev loop .
* Your content is likely to be Markdown, code blocks, YAML snippets, CLI output, diagrams, screenshots, and internal docs links.
* It keeps the blog close to the docs and code, which matches SASE’s own SDD philosophy of keeping durable context close to the code it describes .

Docusaurus is also a good choice, especially if you want a more polished React/MDX marketing site. But I would only pick it if you specifically want MDX components or a more JS-heavy website stack. For a Python CLI/devtool, MkDocs is the more natural starting point.

I would avoid WordPress, Ghost, Medium, or Substack as the canonical host. They are fine for syndication or email, but not ideal as the permanent technical archive.

## Why Cloudflare Pages

I’d use **Cloudflare Pages** rather than serving directly from a VPS or CMS. The site should be static, so you do not need servers, databases, containers, or application hosting.

The main things I’d want from the host are:

* Static deploys from GitHub.
* Custom domain support for `sase.sh`.
* HTTPS.
* Preview deploys for pull requests.
* Easy redirects.
* Easy cache/header control.
* Low lock-in: the output is just static HTML/CSS/JS.

Cloudflare Pages is a good fit for that model. GitHub Pages is the best simpler fallback. Vercel and Netlify are also fine, but they are more attractive if you choose Docusaurus, Astro, or a heavier frontend stack.

My ranking would be:

| Rank | Host                 | Use it when                                                                               |
| ---: | -------------------- | ----------------------------------------------------------------------------------------- |
|    1 | **Cloudflare Pages** | You want a polished static site with custom domain, previews, redirects, and CDN behavior |
|    2 | **GitHub Pages**     | You want the simplest possible GitHub-native setup                                        |
|    3 | **Netlify**          | You want excellent static-site ergonomics and form/redirect features                      |
|    4 | **Vercel**           | You choose Docusaurus/Astro/Next-style tooling and want a frontend-platform workflow      |

## Repo layout I’d use

I’d keep the site in the main repo, not a separate `sase-site` repo, at least initially.

```text
sase/
├── README.md
├── pyproject.toml
├── docs/
│   ├── index.md
│   ├── blog/
│   │   ├── index.md
│   │   └── posts/
│   │       ├── why-coding-agents-need-orchestration.md
│   │       ├── changespecs-durable-unit-of-work.md
│   │       └── xprompt-prompt-logic-as-code.md
│   ├── series/
│   │   └── agentic-software-engineering.md
│   ├── images/
│   │   └── ...
│   ├── ace.md
│   ├── axe.md
│   ├── change_spec.md
│   ├── workflow_spec.md
│   └── ...
├── mkdocs.yml
└── .github/
    └── workflows/
        └── docs.yml
```

The key idea: the blog is not separate from the product. It should be part of the same knowledge system as the docs.

## URL structure

Use date-free URLs for evergreen technical posts:

```text
https://sase.sh/blog/why-coding-agents-need-orchestration/
https://sase.sh/blog/changespecs-durable-unit-of-work/
https://sase.sh/blog/xprompt-prompt-logic-as-code/
https://sase.sh/blog/yaml-workflows-for-coding-agents/
```

Avoid URLs like:

```text
https://sase.sh/2026/05/06/post-title/
```

Dates in the metadata are good; dates in canonical URLs make evergreen technical writing feel stale.

For the 5–10 part series, create a landing page:

```text
https://sase.sh/series/agentic-software-engineering/
```

Every post should include:

```text
Part 3 of “Structured Agentic Software Engineering”
Previous: ...
Next: ...
Full series: ...
```

## Domain setup

Use `sase.sh` as the canonical domain.

I’d set these up:

```text
sase.sh          canonical site
www.sase.sh      redirect to https://sase.sh
docs.sase.sh     optional redirect to https://sase.sh/docs/
blog.sase.sh     optional redirect to https://sase.sh/blog/
```

Do **not** make `blog.sase.sh` the canonical blog unless you have a strong reason. For SEO, memory, and product cohesion, `sase.sh/blog/...` is better.

Reserve these future URLs:

```text
https://sase.sh/install
https://sase.sh/install.sh
https://sase.sh/docs/
https://sase.sh/blog/
https://sase.sh/changelog/
https://sase.sh/examples/
```

Because `.sh` feels CLI-native, `sase.sh/install.sh` may become useful later, even if you do not publish an install script now.

## Build/deploy workflow

I’d make publishing work like this:

1. Write posts as Markdown in `docs/blog/posts/`.
2. Open a PR.
3. CI runs:

   ```bash
   mkdocs build --strict
   ```
4. Preview deploy is generated.
5. Merge to `master`.
6. Cloudflare Pages deploys to `https://sase.sh`.

The important part is `--strict`: broken links and malformed docs should fail the build before they become canonical.

You can keep docs dependencies either in `pyproject.toml` as a `docs` extra or in a small `docs/requirements.txt`. Since the repo already uses Python packaging, I’d probably add a docs extra:

```toml
[project.optional-dependencies]
docs = [
    "mkdocs-material",
    "mkdocs-rss-plugin",
    "mkdocs-git-revision-date-localized-plugin",
]
```

Then CI/build can use something like:

```bash
python -m pip install -e ".[docs]"
mkdocs build --strict
```

Or, if you want to stay closer to the repo’s `uv` workflow:

```bash
uv sync --extra docs
uv run mkdocs build --strict
```

## Canonical-post checklist

For each post, include frontmatter along these lines:

```yaml
---
title: "Why Coding Agents Need an Orchestration Layer"
description: "The case for treating agent runs as durable, tracked software-engineering work."
date: 2026-05-10
authors:
  - sase
tags:
  - agentic software engineering
  - coding agents
  - workflows
  - open source
slug: why-coding-agents-need-orchestration
---
```

Each page should produce:

* `<link rel="canonical" href="https://sase.sh/blog/.../">`
* Open Graph title/description/image.
* RSS/Atom feed.
* Sitemap.
* Stable slug.
* “Edit this page” link to GitHub.
* Links to the repo and relevant docs.

When cross-posting to DEV.to, Hashnode, Medium, or elsewhere, set the canonical URL to the `sase.sh` post where the platform supports it. Where it does not, put this at the top or bottom:

> Originally published at `https://sase.sh/blog/.../`.

## What I’d put on the homepage

Do not make the homepage just a blog index. Make `sase.sh` a compact product landing page:

```text
sase
Structured Agentic Software Engineering

A Python toolkit for orchestrating coding agents through durable ChangeSpecs,
YAML workflows, prompt templates, background scheduling, and human supervision.

[Get started] [Read the blog series] [GitHub]
```

Then include three cards:

```text
ChangeSpecs
Tracked units of agentic work.

Workflows
YAML pipelines for agents, shell, Python, and human checkpoints.

ACE / AXE
Interactive and background supervision for agent-driven engineering.
```

The blog series should be prominent, but not the whole site.

## What I’d link from the README

Once live, add links near the top of the README:

```md
- Website: https://sase.sh
- Documentation: https://sase.sh/docs/
- Blog series: https://sase.sh/series/agentic-software-engineering/
```

The README already has a strong overview and vision section, so the blog should deepen that story rather than duplicate it. The README frames the problem as scheduling, prompt logic, tracking, portability, and supervision pain around repeated agent use . That is exactly the narrative the canonical blog should expand.

## My concrete recommendation

Do this:

```text
Static site generator: MkDocs Material
Canonical domain:       https://sase.sh
Host:                   Cloudflare Pages
Content source:          same GitHub repo
Canonical blog path:     /blog/
Series path:             /series/agentic-software-engineering/
Redirects:               www.sase.sh → sase.sh
Syndication:             DEV.to/Hashnode/LinkedIn → canonical sase.sh URL
```

This gives you the right balance: polished enough for launch, simple enough to maintain, fully owned, easy to migrate, and aligned with the way SASE already treats durable engineering context.

---

QUESTION: I already have a digital ocean droplet. Can I use that to host sase.sh?

# REPLY

Yes. A DigitalOcean droplet can absolutely host `sase.sh`.

I’d still keep the site **static**: generate the blog/docs with MkDocs Material or another static generator, then serve the built HTML from the droplet with **Caddy** or **Nginx**. Do **not** run a CMS or app server unless you have a strong reason.

My recommended setup:

```text
GitHub repo
  ↓ GitHub Actions builds static site
DigitalOcean droplet
  ↓ Caddy serves /var/www/sase.sh
https://sase.sh
```

## Should you use the droplet?

Yes, especially if:

* You already maintain the droplet.
* You are comfortable with Linux/server updates.
* You want full control.
* You may later host demos, preview builds, downloads, or other SASE services.

But the tradeoff is that **you become responsible for uptime, patching, TLS, firewalling, and backups**. A static host like Cloudflare Pages or GitHub Pages is lower maintenance. Since you already have the droplet, I’d use it, but keep the production surface tiny.

## Recommended architecture

Use:

```text
Domain:       sase.sh
Server:       existing DigitalOcean droplet
Web server:   Caddy
Site type:    static HTML
Build:        GitHub Actions
Deploy:       rsync over SSH
Canonical:    https://sase.sh/blog/...
Redirects:    www.sase.sh → sase.sh
```

Caddy is the simplest choice because it can handle HTTPS certificates automatically. Nginx is also fine, but Caddy gives you a cleaner setup for a small static site.

## DNS setup

Point `sase.sh` at your droplet:

```text
A     sase.sh       <your_droplet_ipv4>
A     www           <your_droplet_ipv4>
AAAA  sase.sh       <your_droplet_ipv6>   optional
AAAA  www           <your_droplet_ipv6>   optional
```

Then configure the server so:

```text
https://sase.sh      canonical
https://www.sase.sh  redirects to https://sase.sh
http://...           redirects to https://...
```

Using Cloudflare DNS in front is optional but useful. You can use Cloudflare just for DNS, or enable proxy/CDN later.

## Server setup with Caddy

On an Ubuntu droplet, the shape would be:

```bash
sudo apt update
sudo apt upgrade -y

sudo apt install -y caddy rsync ufw

sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

sudo mkdir -p /var/www/sase.sh/current
sudo chown -R $USER:www-data /var/www/sase.sh
```

Create a Caddy config:

```bash
sudo nano /etc/caddy/Caddyfile
```

Use:

```caddyfile
sase.sh {
    root * /var/www/sase.sh/current
    encode zstd gzip
    file_server

    header {
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
        X-Frame-Options DENY
    }
}

www.sase.sh {
    redir https://sase.sh{uri} permanent
}
```

Then reload:

```bash
sudo caddy fmt --overwrite /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Once DNS points to the droplet, Caddy should obtain HTTPS certificates automatically.

## Deployment model

I’d deploy from GitHub Actions using `rsync`.

The build output for MkDocs is usually:

```text
site/
```

Deploy that to:

```text
/var/www/sase.sh/current/
```

A simple workflow would look like this:

```yaml
name: Deploy site

on:
  push:
    branches: [master]
    paths:
      - "docs/**"
      - "mkdocs.yml"
      - "pyproject.toml"
      - ".github/workflows/deploy-site.yml"

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install docs dependencies
        run: |
          python -m pip install --upgrade pip
          pip install mkdocs-material mkdocs-rss-plugin

      - name: Build
        run: mkdocs build --strict

      - name: Deploy to droplet
        uses: burnett01/rsync-deployments@7.0.2
        with:
          switches: -avzr --delete
          path: site/
          remote_path: /var/www/sase.sh/current/
          remote_host: ${{ secrets.SASE_SH_HOST }}
          remote_user: ${{ secrets.SASE_SH_USER }}
          remote_key: ${{ secrets.SASE_SH_SSH_KEY }}
```

You’d add these GitHub secrets:

```text
SASE_SH_HOST       your droplet IP or hostname
SASE_SH_USER       deploy
SASE_SH_SSH_KEY    private deploy key
```

For better hygiene, create a non-root deploy user:

```bash
sudo adduser deploy
sudo usermod -aG www-data deploy
sudo chown -R deploy:www-data /var/www/sase.sh
```

Then add the GitHub Actions public key to:

```text
/home/deploy/.ssh/authorized_keys
```

## Better deploy: atomic releases

For a small blog, direct `rsync --delete` into `current/` is fine.

For a cleaner production-style deploy, use releases:

```text
/var/www/sase.sh/
  releases/
    20260506-120000/
    20260507-091500/
  current -> releases/20260507-091500
```

Then deploy into a new release directory and flip the `current` symlink. That avoids half-updated pages during deploys. Not necessary on day one, but nice later.

## Keep it static

For your canonical SASE blog, I would avoid:

```text
WordPress
Ghost
Node server
Python web app
Database-backed CMS
```

SASE already has a strong docs/devtool identity. The repo describes SASE as a Python toolkit for AI-powered software engineering workflows, with an interactive TUI, scheduler daemon, YAML workflow engine, and pluggable LLM/VCS abstractions . A static Markdown site fits that much better than a dynamic CMS.

## Security checklist

At minimum:

```bash
sudo apt update
sudo apt upgrade
sudo ufw status
```

And configure:

```bash
sudo apt install unattended-upgrades
sudo dpkg-reconfigure unattended-upgrades
```

Recommended:

* SSH keys only; disable password SSH login.
* No root SSH login.
* Only ports 22, 80, and 443 open.
* Use a separate `deploy` user.
* Keep `/var/www/sase.sh` owned by `deploy:www-data`.
* Do not put secrets in the web root.
* Take DigitalOcean snapshots or backups.
* Add uptime monitoring.
* Keep Caddy/Nginx and the OS patched.

## Where the blog should live in the repo

I’d still keep the content in the SASE repo:

```text
sase/
├── docs/
│   ├── index.md
│   ├── blog/
│   │   ├── index.md
│   │   └── posts/
│   │       ├── why-coding-agents-need-orchestration.md
│   │       ├── changespecs-durable-unit-of-work.md
│   │       └── xprompt-prompt-logic-as-code.md
│   ├── series/
│   │   └── agentic-software-engineering.md
│   └── ...
├── mkdocs.yml
└── .github/workflows/deploy-site.yml
```

That matches SASE’s own approach of keeping durable planning/docs context close to the code; the SDD docs say the `sdd/` directory keeps prompts, approved plans, roadmap material, and bead state close to the code so humans and agents can reference the same artifacts over time .

## My final recommendation

Use the droplet, but keep the setup boring:

```text
MkDocs Material → GitHub Actions → rsync → Caddy → sase.sh
```

That gives you an owned canonical blog with very little runtime complexity. Use Cloudflare Pages/GitHub Pages only if you decide you do not want to maintain server updates.

---

QUESTION: What if this blog series blows up and gets a lot of traffic? What size droplet would I need?

# REPLY

Yes, and the answer is probably: **you do not need a large droplet if the site is static.**

For `sase.sh`, assuming:

```text
MkDocs/Docusaurus/static HTML
Caddy or Nginx
No database
No server-side rendering
No WordPress/Ghost
No app process
```

then I’d start with:

```text
1 vCPU / 1 GB RAM
```

and put **Cloudflare in front** of it.

That setup can handle a surprisingly large launch spike because the droplet is only serving static files, and Cloudflare can absorb most repeat traffic.

## Practical recommendation

Use your current droplet unless it is extremely tiny or overloaded with other services.

My sizing rule:

| Setup                                                |                           Droplet size I’d use |
| ---------------------------------------------------- | ---------------------------------------------: |
| Static site + Cloudflare cache                       |                          **1 vCPU / 1 GB RAM** |
| Static site, no CDN, moderate spike                  |                        **1 vCPU / 1–2 GB RAM** |
| Static site, no CDN, very image-heavy                | **2 vCPU / 2–4 GB RAM**, but better to add CDN |
| WordPress/Ghost/CMS                                  |                **2 vCPU / 2–4 GB RAM minimum** |
| Static site plus search, analytics, demos, API, etc. |        Depends on those services, not the blog |

For the SASE canonical blog, I’d do:

```text
1 vCPU / 1 GB RAM droplet
Caddy
Cloudflare DNS/proxy enabled
Aggressive static caching
Images optimized
Builds done in GitHub Actions, not on the droplet
```

## The real bottleneck is bandwidth, not CPU

A static blog post is cheap to serve. The main risk during a viral spike is transfer volume.

Rough math:

```text
100,000 pageviews × 500 KB/page ≈ 50 GB transfer
100,000 pageviews × 1 MB/page   ≈ 100 GB transfer
1,000,000 pageviews × 1 MB/page ≈ 1 TB transfer
```

That is manageable, but you do not want all of it coming directly from your droplet if the post really takes off.

With Cloudflare in front, most repeated assets and pages can be served from cache. Your droplet might only see a fraction of the traffic. Without a CDN, the droplet can still serve the traffic, but you may burn through included transfer much faster. I can’t live-check current DigitalOcean bandwidth allowances here, so verify the current transfer limits for your exact plan.

## “Blows up” traffic is usually less scary than it sounds

Suppose a post gets **250,000 pageviews in one day**. That sounds huge, but the average request rate is:

```text
250,000 / 86,400 ≈ 2.9 pageviews/sec
```

Even if the peak is 20× the daily average:

```text
~60 pageviews/sec
```

A small droplet serving static files with Caddy or Nginx can handle that, especially with compression and CDN caching.

The scary case is not average load. It is:

```text
huge unoptimized images
no CDN
many uncached assets per page
bots/scrapers
analytics scripts
server-side rendering
```

Avoid those and the droplet size barely matters.

## What I would configure before launch

### 1. Put Cloudflare in front

Use:

```text
sase.sh      proxied through Cloudflare
www.sase.sh  redirect to sase.sh
```

Keep the droplet as the origin.

### 2. Cache static assets hard

For assets with hashed filenames, cache for a long time:

```text
Cache-Control: public, max-age=31536000, immutable
```

For HTML pages, use a shorter cache:

```text
Cache-Control: public, max-age=300
```

or something similarly conservative.

### 3. Optimize images

This matters more than droplet size.

Use:

```text
WebP / AVIF where practical
reasonable dimensions
lazy loading
compressed social preview images
no 5 MB screenshots inline
```

A viral post with ten 2 MB images is a bandwidth problem. A viral post with compressed images and cached assets is easy.

### 4. Do not build on the droplet

Build in GitHub Actions:

```text
mkdocs build --strict
rsync site/ to droplet
```

The droplet should only serve files.

### 5. Add basic monitoring

Watch:

```text
CPU usage
RAM usage
network outbound
Caddy/Nginx access logs
5xx errors
disk space
Cloudflare cache hit ratio
```

Upgrade only if the metrics say you need to.

## When would I upgrade?

I would not upgrade preemptively unless the current droplet is already under load.

Upgrade from **1 GB → 2 GB** if:

```text
RAM is consistently above ~70–80%
CPU is consistently high during normal traffic
you are running other services on the droplet
Caddy/Nginx starts competing with background jobs
```

Upgrade from **2 GB → 4 GB** only if:

```text
you add dynamic services
you host demos/APIs on the same box
you run search indexing locally
you run analytics/database workloads
you refuse to use a CDN and traffic is huge
```

For a static blog alone, a 4 GB droplet is usually unnecessary.

## My preferred launch setup

```text
Droplet:       1 vCPU / 1 GB RAM
Web server:    Caddy
CDN/DNS:       Cloudflare
Build:         GitHub Actions
Deploy:        rsync over SSH
Content:       static HTML/CSS/JS/images
Images:        compressed and lazy-loaded
Monitoring:    DO graphs + uptime monitor + logs
```

That should survive a very successful launch.

## The best safety valve

The most important move is this:

```text
Enable Cloudflare proxy/cache before announcing the series.
```

That gives you room to handle a big spike without resizing the droplet. If the series truly explodes, you can later move static assets to object storage or a static host, but you probably will not need to.

---

QUESTION: I already host bryanbugyi.com on this droplet (which gets very little traffic). Would I be able to host 2 websites from the same droplet?

# REPLY

Yes. You can host **both `bryanbugyi.com` and `sase.sh` on the same DigitalOcean droplet**. This is a normal setup.

A single web server listens on ports `80` and `443`, then routes requests based on the requested hostname:

```text
bryanbugyi.com  → /var/www/bryanbugyi.com/current
sase.sh         → /var/www/sase.sh/current
```

The browser sends the hostname in the request, and Caddy/Nginx uses that to serve the right site.

## Recommended setup

Use one frontend web server:

```text
Caddy or Nginx
  ├── bryanbugyi.com
  └── sase.sh
```

Do **not** run two separate web servers both trying to bind to ports `80` and `443`. One Caddy/Nginx process should own those ports and route traffic by domain.

## DNS

Point both domains to the same droplet IP:

```text
bryanbugyi.com    A     <droplet-ip>
www               A     <droplet-ip>

sase.sh           A     <droplet-ip>
www               A     <droplet-ip>
```

If your droplet has IPv6, you can also add `AAAA` records.

## Caddy example

If you use Caddy, your `/etc/caddy/Caddyfile` could look like this:

```caddyfile
bryanbugyi.com {
    root * /var/www/bryanbugyi.com/current
    encode zstd gzip
    file_server
}

www.bryanbugyi.com {
    redir https://bryanbugyi.com{uri} permanent
}

sase.sh {
    root * /var/www/sase.sh/current
    encode zstd gzip
    file_server

    header {
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
        X-Frame-Options DENY
    }
}

www.sase.sh {
    redir https://sase.sh{uri} permanent
}
```

Then:

```bash
sudo caddy fmt --overwrite /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy should automatically issue and renew HTTPS certificates for both domains once DNS is pointed correctly.

## Directory layout

I’d keep the sites separate:

```text
/var/www/
├── bryanbugyi.com/
│   └── current/
│       └── index.html
└── sase.sh/
    └── current/
        └── index.html
```

For the SASE site, GitHub Actions can deploy the built static site to:

```text
/var/www/sase.sh/current/
```

Your existing personal site can keep whatever deployment path it already uses.

## If bryanbugyi.com is already using Nginx

Then add a second `server` block for `sase.sh`.

Conceptually:

```nginx
server {
    server_name bryanbugyi.com www.bryanbugyi.com;
    root /var/www/bryanbugyi.com/current;
}

server {
    server_name sase.sh www.sase.sh;
    root /var/www/sase.sh/current;
}
```

You would then use Certbot or your existing TLS setup for the new domain.

## If bryanbugyi.com is an app, not static

Still fine. Example with Caddy:

```caddyfile
bryanbugyi.com {
    reverse_proxy localhost:3000
}

sase.sh {
    root * /var/www/sase.sh/current
    encode zstd gzip
    file_server
}
```

The important rule is: one public reverse proxy on `80/443`, different backends or static roots per hostname.

## Capacity concerns

For your case, hosting both on the same droplet is fine. A low-traffic personal site plus a static SASE blog is a light workload.

The only caveat: if `sase.sh` gets a huge spike and you are **not** using Cloudflare or another CDN, it could affect `bryanbugyi.com` because they share CPU, RAM, disk, and bandwidth. The simple fix is to put `sase.sh` behind Cloudflare caching. You can also put both domains behind Cloudflare.

## My recommendation

Use the same droplet.

Set it up like this:

```text
bryanbugyi.com → existing site
sase.sh        → static MkDocs/Docusaurus build
Caddy          → handles both domains + HTTPS
Cloudflare     → optional but recommended for sase.sh traffic spikes
```

This is a good, boring setup: cheap, simple, and easy to split later if `sase.sh` grows enough to deserve its own infrastructure.
