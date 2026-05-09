# Cloudflare Pages Launch Plan for `https://sase.sh/blog/`

Date: 2026-05-07

## Question

Now that `sase.sh` should use Cloudflare Pages instead of a DigitalOcean droplet, what needs to happen to get the
canonical SASE blog live at `https://sase.sh/blog/`?

## Short Recommendation

Use Cloudflare Pages as the production host for a static MkDocs Material site, with `https://sase.sh/` as the canonical
site and `https://sase.sh/blog/` as the canonical blog index.

The initial launch target was:

```text
Generator:       MkDocs Material
Repo location:   same repo, rooted at /home/bryan/projects/github/sase-org/sase_100
Docs source:     docs/
Blog posts:      docs/blog/posts/
Pages build:     python -m pip install -e ".[docs]" && python -m mkdocs build --strict
Local build:     uv sync --extra docs && uv run mkdocs build --strict
Build output:    site
Production URL:  https://sase.sh/
Blog URL:        https://sase.sh/blog/
```

Current production deployment uses GitHub Actions direct upload instead of the Cloudflare Pages dashboard build command.
The `.github/workflows/docs-deploy.yml` workflow runs `just docs-check`, then `just docs-pdf-check`, verifies the
prebuilt `site/` artifact includes `site/downloads/sase-handbook.pdf`, and uploads `site/` to the `sase-sh` Pages
project with Wrangler. The GitHub repo needs `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` Actions secrets. The
Pages dashboard Git build should stay disabled or unused for production; otherwise the lightweight MkDocs build above
can deploy a site that has links and headers for the PDF but no PDF artifact.

For Cloudflare Pages specifically, do not assume `uv` is preinstalled. Cloudflare's current v3 build image documents
Python, `pip`, `pipx`, and Poetry, but not `uv`. Unless the repo adds an explicit uv install step, the safer Pages build
command is:

```text
python -m pip install -e ".[docs]" && python -m mkdocs build --strict
```

This supersedes the prior DigitalOcean droplet path. The droplet can stop being the origin for `sase.sh` once the Pages
project has a successful production deploy and the `sase.sh` custom domain is attached.

## Strategic Direction: Pages vs Workers Static Assets

Cloudflare's stated 2025–2026 direction matters here, even though it does not change the immediate decision. Cloudflare
has publicly said that going forward "all of our investment, optimizations, and feature work will be dedicated to
improving Workers," and that Pages will continue to be supported while Pages and Workers converge into a single
experience. Workers Static Assets has reached feature parity with Pages for static hosting, SSR, and custom domains,
and supports the same `_headers` / `_redirects` files Pages uses. Cloudflare publishes an explicit Pages → Workers
migration guide.

What this means for `sase.sh/blog/`:

- For a launch-tomorrow static blog, **Cloudflare Pages is still the simpler choice**. Git integration, preview URLs
  per PR, custom domains, and built-in build pipelines are all there with no `wrangler.toml` required.
- However, two design choices now have long-term implications:
  1. Keep `_redirects` / `_headers` as the source of truth for routing and headers. They port to Workers Static Assets
     unchanged, so a future migration is mostly a `wrangler.toml` and DNS swap rather than a rewrite.
  2. Avoid Pages-specific Functions for anything you can do at the edge later as a Worker. If a backend bit is needed
     (form submit, RSS rebuild, comment proxy), prefer building it as a standalone Worker with its own route, not as a
     Pages Function.
- New side projects under `*.sase.sh` started after the blog launch should default to Workers Static Assets directly,
  to avoid migrating later.

The implicit "do nothing" risk is small: Cloudflare has committed to keeping Pages projects working, and
existing-project migration is opt-in.

## Current Starting State

Local DNS check on 2026-05-07:

```text
NS sase.sh:        kami.ns.cloudflare.com, tony.ns.cloudflare.com
A sase.sh:         67.207.92.152
CNAME www.sase.sh: sase.sh
A www.sase.sh:     67.207.92.152
```

Interpretation:

- Cloudflare is already authoritative for `sase.sh`.
- The zone still points the apex at the DigitalOcean droplet.
- `www` currently follows the apex, so it also lands on the droplet.
- The remaining DNS work is not a registrar nameserver change; it is replacing the droplet-origin records with Pages
  custom-domain records after the Pages project exists.

The `ajf.r1` agent's useful correction was that a static high-traffic blog should use Cloudflare Pages first; a droplet
is only attractive if there are dynamic server-side needs later. That matches the earlier SASE blog research, which
already recommended a static canonical site, Markdown in Git, and Cloudflare Pages as the hosting default.

## Why Pages Fits This Better Than the Droplet

Cloudflare Pages is the right default because the SASE blog should be static, repo-backed, and cacheable. Static asset
requests on Pages are free and unlimited when they do not invoke Pages Functions, so ordinary blog traffic does not need
droplet sizing, origin caching, or server maintenance. The relevant limits are build and asset limits, not request
throughput: the Free plan currently allows 500 builds per month, 1 concurrent build, 100 custom domains per project,
20,000 files, and 25 MiB maximum per asset.

Those limits are comfortable for a SASE docs/blog site. The only likely limit to watch is the 25 MiB file limit for
large screenshots, videos, or downloadable artifacts. Put oversized media in R2 or another object store instead of the
Pages build.

Pages also gives PR/branch preview URLs, GitHub check integration, custom domains, rollbacks, redirects, and custom
headers without running a web server.

## Cloudflare Pages Project Setup

Create a Pages project connected to the GitHub repo. In the Cloudflare dashboard:

1. Go to Workers & Pages.
2. Create a Pages project from Git.
3. Select the SASE GitHub repository.
4. Use the repo root as the root directory unless the site is intentionally moved into a subdirectory.
5. Set production branch to the repo's real default branch.
6. Set build command and output:

```text
Build command:     python -m pip install -e ".[docs]" && python -m mkdocs build --strict
Build output dir:  site
Root directory:    /
```

Cloudflare's MkDocs preset is `mkdocs build` with `site` as the output directory. For local development, keep using the
repo's normal `uv` workflow; for Pages, either use the pip-based command above or explicitly install uv in the build
command. The repo will need a committed docs dependency setup before the first successful Pages build.

Also consider pinning the Pages Python version to 3.12 with a `PYTHON_VERSION=3.12` environment variable or a
`.python-version` file if the docs build should match the repo's current Python tooling expectations. Cloudflare v3
currently defaults to Python 3.13.3, which satisfies `requires-python = ">=3.12"` but may expose dependency or lint
differences.

### Build image and toolchain realities

Cloudflare Pages v3 build image documents these defaults and overrides:

| Tool   | Default in v3 | How to override                                                          |
| ------ | ------------- | ------------------------------------------------------------------------ |
| Python | 3.13.3        | `PYTHON_VERSION` env var, or `.python-version` / `runtime.txt` in repo   |
| Node   | 22.16.0       | `NODE_VERSION` env var, or `.nvmrc` / `.node-version`                    |
| Go     | (see docs)    | `GO_VERSION`                                                             |
| Ruby   | (see docs)    | `RUBY_VERSION`                                                           |
| Hugo   | (see docs)    | `HUGO_VERSION`                                                           |

`uv` is **not** documented as preinstalled, and no `UV_VERSION` env var is supported. There are two practical paths if
the repo wants to use `uv` on Pages:

```text
# Option 1 — install uv at build time (pip route, no curl needed)
python -m pip install --upgrade pip uv && \
uv sync --extra docs && \
uv run mkdocs build --strict

# Option 2 — bypass uv on Pages and rely on pip + pyproject extras
python -m pip install -e ".[docs]" && \
python -m mkdocs build --strict
```

Option 2 is the lower-risk default because it keeps the Pages build path simple and identical across runs. Option 1 is
fine if you want byte-identical local and CI builds.

### Full git clone for date plugins

`mkdocs-git-revision-date-localized-plugin` and similar plugins read commit history. Pages does shallow clones by
default. If a plugin reports "no git history" on Pages but works locally, the typical fixes are:

- Set the build environment variable `GIT_DEPTH=0` (or any large value) if Cloudflare's build image honors it.
- Otherwise, run `git fetch --unshallow || true` as part of the build command before `mkdocs build`, e.g.:

  ```text
  git fetch --unshallow || true && python -m pip install -e ".[docs]" && python -m mkdocs build --strict
  ```

This is only relevant if you opt into a date/contributor plugin. The plain Material blog plugin does not need it.

### Useful Pages-provided env vars at build time

Pages injects these into the build environment and they are useful for canonical URL generation, build banners, or
preview-vs-prod gating:

```text
CF_PAGES=1
CF_PAGES_BRANCH=<branch>
CF_PAGES_COMMIT_SHA=<sha>
CF_PAGES_URL=<https://<deploy>.<project>.pages.dev>
```

For MkDocs, these can be read by a small `hooks/` plugin to switch `site_url` between production and preview, or to
inject a "preview build" banner so previews don't get accidentally indexed.

## Repo Work Needed

The repo does not currently have a `mkdocs.yml` at the root, though it already has many docs under `docs/`. To make
Pages deployable, add the static-site scaffold:

```text
mkdocs.yml
docs/index.md
docs/blog/index.md
docs/blog/posts/<first-post>.md
docs/series/agentic-software-engineering.md
docs/_redirects
docs/_headers
```

Recommended `mkdocs.yml` settings:

```yaml
site_name: SASE
site_url: https://sase.sh/
repo_url: https://github.com/sase-org/sase
theme:
  name: material
plugins:
  - search
  - blog
strict: true
use_directory_urls: true
```

Important details:

- `site_url: https://sase.sh/` matters because MkDocs uses it to emit canonical URLs.
- Material for MkDocs has a built-in blog plugin. It expects a `docs/blog/index.md` entry point and scans posts under
  `docs/blog/posts/`.
- Use date-free, evergreen post URLs such as `/blog/why-coding-agents-need-orchestration/`.
- Keep the series landing page separate from the blog index: `/series/agentic-software-engineering/`.
- Add docs dependencies to the project, likely under a `docs` extra in `pyproject.toml`, so both local builds and Pages
  builds are reproducible.

Example docs extra:

```toml
[project.optional-dependencies]
docs = [
    "mkdocs-material",
    "mkdocs-rss-plugin",
    "mkdocs-git-revision-date-localized-plugin",
]
```

For local verification, use:

```text
uv sync --extra docs && uv run mkdocs build --strict
```

For Cloudflare Pages, prefer the pip-based command unless uv is installed as part of the build:

```text
python -m pip install -e ".[docs]" && python -m mkdocs build --strict
```

## Material Social Cards (Open Graph Images)

Material for MkDocs ships a built-in `social` plugin that auto-generates Open Graph images per page. It is part of the
open-source release, not Insiders-only. It depends on Cairo and friends:

```bash
apt-get install libcairo2-dev libfreetype6-dev libffi-dev libjpeg-dev libpng-dev libz-dev
```

Implication for Cloudflare Pages: the v3 build image does not document Cairo as preinstalled, and the Pages build
environment does not give you `sudo apt-get` to install it cleanly. Three viable approaches, in order of preference for
this project:

1. **Skip social cards at launch.** The blog plugin works fine without them. Add cards later. This is the lowest-risk
   path and keeps Pages's first-party Git pipeline.
2. **Pre-build social cards in CI, not on Pages.** Use a GitHub Actions job to run `mkdocs build` (which generates the
   cards into `site/`) and then deploy `site/` via `wrangler pages deploy`. This bypasses the Pages build image
   entirely. See "Deploy alternative" below.
3. **Try Cairo on Pages.** Some Pages users have gotten Cairo working by relying on already-present shared libraries
   in the v3 base image, but this is fragile and can break across image upgrades. Not recommended as the primary path.

If social cards are deferred, document the choice in `mkdocs.yml` so future contributors know not to flip the plugin on
without revisiting the build pipeline.

## Deploy Alternative: GitHub Actions + Wrangler

The Pages dashboard's "connect a Git repo" flow is the simplest path, but it ties you to the Pages build image. A
second supported path is to build the site in GitHub Actions (where you control the toolchain) and deploy the resulting
`site/` directory using `wrangler pages deploy`. This is worth choosing if any of these are true:

- Material social cards (or any other Cairo/Pango dependency) need to be generated.
- You want to run a build with `uv` exactly as locally, on your pinned Python.
- You want pre-deploy gates: link checking, spell checking, frontmatter linting, broken-asset detection.

Sketch:

```yaml
# .github/workflows/pages.yml
name: pages
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
  deployments: write
jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v3
      - run: sudo apt-get update && sudo apt-get install -y libcairo2-dev libfreetype6-dev libffi-dev libjpeg-dev libpng-dev libz-dev
      - run: uv sync --extra docs
      - run: uv run mkdocs build --strict
      - run: uv run lychee --no-progress site || true   # optional link check
      - uses: cloudflare/wrangler-action@v3
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: pages deploy site --project-name=sase-sh --branch=${{ github.ref_name }}
```

You will need a `CLOUDFLARE_API_TOKEN` (scoped to "Pages: Edit") and `CLOUDFLARE_ACCOUNT_ID` in GitHub secrets. Each
push to a non-default branch becomes a Pages preview deploy and gets its own URL; the production branch publishes to
`sase.sh`. This path also makes future migration to Workers Static Assets a one-line change
(`wrangler deploy` against a Worker config) without retraining the build.

## DNS and Domain Cutover

After the Pages project has at least one successful deployment:

1. In the Pages project, go to Custom domains.
2. Add `sase.sh` as a custom apex domain.
3. Let Cloudflare create or replace the Pages CNAME record for the apex. Do not manually point `sase.sh` at
   `<project>.pages.dev` without going through the Pages custom-domain flow; Cloudflare documents that manual-only
   records can fail with a `522`.
4. Add `www.sase.sh` only if you want it attached to the Pages project. Otherwise use a Cloudflare Bulk Redirect from
   `www.sase.sh/*` to `https://sase.sh/:path`.
5. Remove or replace the current droplet `A @ 67.207.92.152` record once the Pages custom domain is active.

Recommended canonical behavior:

```text
https://sase.sh/              canonical site
https://sase.sh/blog/         canonical blog
https://sase.sh/blog/<slug>/  canonical post
https://www.sase.sh/*         301 -> https://sase.sh/*
https://blog.sase.sh/*        optional 301 -> https://sase.sh/blog/*
https://docs.sase.sh/*        optional 301 -> https://sase.sh/docs/*
```

Cloudflare's Pages-specific `www` redirect guide uses Bulk Redirects plus a proxied placeholder DNS record for `www`.
For the SASE case, the exact record can be created through Cloudflare's redirect setup, but the important policy is:
`www` should not become a second canonical host.

### Records to preserve, not just replace

A common cutover mistake is wiping the zone and only adding the apex record. Before changing DNS, audit the existing
zone for records that are not droplet-related:

- **MX / SPF / DKIM / DMARC:** if any email is delivered to `@sase.sh` (vendor email, registrar forwarding, future
  Cloudflare Email Routing), the MX and TXT records must survive the cutover. Mail records and Pages records are
  independent — Pages only owns the apex A/AAAA/CNAME for HTTP traffic.
- **CAA:** Cloudflare manages CAA automatically for proxied hostnames. If you previously added manual CAA records that
  pinned issuance to Let's Encrypt for the droplet, those should be removed or updated, otherwise Cloudflare's
  Universal SSL issuance for the apex Pages domain may be blocked.
- **DNSSEC:** if DNSSEC is enabled at the registrar, leave it as-is when only swapping records inside an
  already-Cloudflare-authoritative zone (which is the current state). DNSSEC needs registrar-side action only when
  changing nameservers.
- **TXT / verification records:** keep any GitHub, search-console, or vendor verification TXT records.

### Optional: Cloudflare Email Routing

If you eventually want `hello@sase.sh` or similar without running a mail server, Cloudflare Email Routing is a clean
fit. It is configured per-zone and adds its own MX records. It works alongside Pages on the same apex without conflict.
This is launch-day-optional but worth recording so the apex isn't treated as web-only by future agents.

## Redirects and Headers

For path-level redirects that belong to the site artifact, commit a `docs/_redirects` file. MkDocs copies static assets
from `docs/` into the build output, which is where Pages expects `_redirects` and `_headers`.

Candidate `docs/_redirects`:

```text
/blog/sase-series/ /series/agentic-software-engineering/ 301
/docs /docs/ 301
/blog /blog/ 301
```

For domain-level redirects such as `www.sase.sh -> sase.sh`, prefer Cloudflare Bulk Redirects. Cloudflare Pages
`_redirects` rules are path-level and do not handle domain-level redirects.

Candidate `docs/_headers`:

```text
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin

/assets/*
  Cache-Control: public, max-age=31536000, immutable
```

Avoid aggressive HTML caching headers at first. Pages already serves static assets from Cloudflare's network, and
over-caching HTML makes launch corrections and post edits slower to verify.

### Pages limits to plan around

Cloudflare's Pages docs publish hard limits worth designing around so they do not surprise you mid-launch:

- **Build duration:** 20 minutes per build. MkDocs builds are typically seconds, so this is comfortable until you add
  social cards across hundreds of posts.
- **Builds per month:** 500 on Free, 5,000 on Pro, 20,000 on Business. PR-driven preview deploys count.
- **Concurrent builds:** 1 on Free. Two near-simultaneous merges queue rather than parallelize.
- **Files per project:** 20,000 on Free. The full SASE docs tree is well below this; watch out only if you commit
  generated artifacts (PDFs, images, infographics) into `docs/`.
- **Asset size:** 25 MiB per file. Large videos and PDFs should live in R2 or another object store, not in `docs/`.
- **`_redirects`:** up to 2,000 static rules + 100 dynamic rules; one rule per line; placeholders match dynamic rules.
- **`_headers`:** up to 100 rule blocks; individual header values capped at 2,000 characters.
- **Custom domains per project:** 100 on Free.

### Recommended security headers and HSTS

When the launch is stable (all known third-party embeds load cleanly), tighten `_headers` rather than starting strict:

```text
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  Permissions-Policy: geolocation=(), microphone=(), camera=()
```

HSTS preload is a separate step (submit at hstspreload.org) and is irreversible for ~12 months — defer it until you are
certain `sase.sh` and every present and future subdomain will always be HTTPS. A Content-Security-Policy is worth
adding once Material's exact inline-script needs are known; ship without CSP at launch and add a report-only CSP first.

## Cache Strategy

Cloudflare Pages automatically purges asset URLs on each deploy, so cache busting via hashed filenames is not strictly
required. That makes the safe defaults:

- HTML: `Cache-Control: public, max-age=0, must-revalidate` (or short, like `max-age=60`). Edits show up almost
  immediately because each deploy invalidates the URL.
- Hashed assets in `/assets/*`: `public, max-age=31536000, immutable`.
- RSS feed: `public, max-age=300` so subscribers see updates within minutes without battering origin (origin is
  Cloudflare, but downstream caches still apply).

Do **not** set long max-age on bare HTML at launch. The Pages auto-purge gives you instant updates only if browsers and
intermediaries don't already hold a long-lived copy.

## SEO: Sitemap, robots.txt, RSS

MkDocs auto-generates `sitemap.xml` when `site_url` is set, which the recommended config already does. To make this
discoverable:

- Add `docs/robots.txt` with:

  ```text
  User-agent: *
  Allow: /
  Sitemap: https://sase.sh/sitemap.xml
  ```

- Confirm `<link rel="canonical">` in rendered pages points to `https://sase.sh/...`. Material does this when `site_url`
  is set; verify after the first deploy with `curl -s https://sase.sh/blog/ | grep canonical`.
- Submit `https://sase.sh/sitemap.xml` to Google Search Console and Bing Webmaster Tools after launch. Verification can
  be done via a TXT record (preferred — survives Pages redeploys) rather than an HTML file.
- Add `mkdocs-rss-plugin` for the blog so syndication targets (DEV.to, Hashnode, RSS readers) see new posts. Material
  Insiders' built-in RSS is not required.

## Comments and Discussion

If the blog wants comments, the lowest-friction path that fits a static MkDocs site is **giscus**, which uses GitHub
Discussions as the storage backend and renders an iframe widget. Pros: no third-party tracker, content lives in the
repo's GitHub org, moderation uses existing GitHub tools, no Pages Function needed. Cons: requires a GitHub account to
post.

If anonymous comments matter, fall back to a hosted comments service (Disqus, Cusdis, Hyvor Talk). All three work as a
client-side widget on Pages — none require a Function.

Defer this decision until at least one post is live; it can be added later by editing the Material blog template and
committing a giscus config.

## CI Build Validation

Even with Pages's first-party Git pipeline, run a separate `mkdocs build --strict` check in GitHub Actions on PRs.
Reasons:

- Pages's preview build will run regardless of strictness, and a broken-link warning under `strict: false` quietly
  ships.
- A separate CI run can also do `lychee` link checking and verify that no `docs/blog/posts/*` post is missing required
  frontmatter.

This is cheap insurance against the Pages dashboard becoming the only authority on whether the site is healthy.

## Launch Checklist

Before public launch:

1. Add `mkdocs.yml`, blog structure, homepage, and first post stub.
2. Add docs dependencies and a local/docs check command.
3. Run `uv sync --extra docs && uv run mkdocs build --strict` locally.
4. Connect repo to Cloudflare Pages.
5. Confirm Pages production deploy succeeds.
6. Add `sase.sh` custom domain in the Pages project.
7. Replace droplet DNS with Pages-managed DNS.
8. Add `www -> apex` Bulk Redirect.
9. Verify:

```bash
curl -I https://sase.sh/
curl -I https://sase.sh/blog/
curl -I https://www.sase.sh/blog/
curl -I https://<project>.pages.dev/blog/
```

Expected:

- `https://sase.sh/blog/` returns `200`.
- `https://www.sase.sh/blog/` returns `301` or `308` to `https://sase.sh/blog/`.
- Pages preview URLs work for PRs.
- Search engines see canonical links pointing to `https://sase.sh/...`.

## Decisions Still Needed

- **Repo path:** Use root-level `mkdocs.yml` and existing `docs/` unless there is a strong reason to create a separate
  site subdirectory.
- **Dependency style:** Prefer `pyproject.toml` docs extra over a standalone `docs/requirements.txt`, because the repo is
  already Python/uv-oriented.
- **Homepage scope:** Launch a compact product/docs homepage, not only a blog index.
- **Analytics:** Use Cloudflare Web Analytics or Plausible later. Do not block the blog launch on analytics.
- **Email capture:** Defer Buttondown or another newsletter until at least the first few posts exist.
- **Build pipeline:** Pages-managed Git build vs GitHub Actions + `wrangler pages deploy`. Choose Actions if social
  cards, `uv`-pinned builds, or pre-deploy gates matter; otherwise stay on the dashboard flow.
- **Hosting target:** Cloudflare Pages now vs Workers Static Assets later. Default to Pages now and design routing/
  headers to be migration-friendly; do not start a brand-new Workers Static Assets project just to be future-proof
  unless a Worker-side feature is needed at launch.
- **Comments:** giscus vs deferred. Recommend deferred until first 1–2 posts are public.

## Sources

- Existing local research:
  - `sdd/research/202605/blog_series_deep_research.md`
  - `sdd/research/202605/sase_blog_setup_advice.md`
  - `sdd/research/202605/sase_blog_series_platform_decision_matrix.md`
- SASE chat transcript:
  - `ajf.r1`, via `sase chats show --agent ajf.r1 -f response`
- Cloudflare Pages build configuration:
  <https://developers.cloudflare.com/pages/configuration/build-configuration/>
- Cloudflare Pages build image:
  <https://developers.cloudflare.com/pages/configuration/build-image/>
- Cloudflare Pages custom domains:
  <https://developers.cloudflare.com/pages/configuration/custom-domains/>
- Cloudflare Pages limits:
  <https://developers.cloudflare.com/pages/platform/limits/>
- Cloudflare Pages Functions pricing / static asset request note:
  <https://developers.cloudflare.com/pages/functions/pricing/>
- Cloudflare Pages GitHub integration:
  <https://developers.cloudflare.com/pages/configuration/git-integration/github-integration/>
- Cloudflare Pages preview deployments:
  <https://developers.cloudflare.com/pages/configuration/preview-deployments/>
- Cloudflare Pages redirects:
  <https://developers.cloudflare.com/pages/configuration/redirects/>
- Cloudflare Pages headers:
  <https://developers.cloudflare.com/pages/configuration/headers/>
- Cloudflare Pages `www` to apex redirect:
  <https://developers.cloudflare.com/pages/how-to/www-redirect/>
- MkDocs configuration:
  <https://www.mkdocs.org/user-guide/configuration/>
- Material for MkDocs blog setup:
  <https://squidfunk.github.io/mkdocs-material/setup/setting-up-a-blog/>
- Material for MkDocs social plugin:
  <https://squidfunk.github.io/mkdocs-material/plugins/social/>
- Material for MkDocs image-processing requirements (Cairo et al.):
  <https://squidfunk.github.io/mkdocs-material/plugins/requirements/image-processing/>
- Cloudflare Pages → Workers migration guide:
  <https://developers.cloudflare.com/workers/static-assets/migration-guides/migrate-from-pages/>
- Cloudflare blog "Full-stack development on Workers" (Pages/Workers convergence statement):
  <https://blog.cloudflare.com/full-stack-development-on-cloudflare-workers/>
- Cloudflare blog "Pages and Workers are converging into one experience":
  <https://blog.cloudflare.com/pages-and-workers-are-converging-into-one-experience/>
- Cloudflare Workers Static Assets:
  <https://developers.cloudflare.com/workers/static-assets/>
- Cloudflare Email Routing:
  <https://developers.cloudflare.com/email-routing/>
- `cloudflare/wrangler-action` (deploy from GitHub Actions):
  <https://github.com/cloudflare/wrangler-action>
- giscus (GitHub-Discussions-backed comments for static sites):
  <https://giscus.app/>
