# Cloudflare Pages Launch Plan for `https://sase.sh/blog/`

Date: 2026-05-07

## Question

Now that `sase.sh` should use Cloudflare Pages instead of a DigitalOcean droplet, what needs to happen to get the
canonical SASE blog live at `https://sase.sh/blog/`?

## Short Recommendation

Use Cloudflare Pages as the production host for a static MkDocs Material site, with `https://sase.sh/` as the canonical
site and `https://sase.sh/blog/` as the canonical blog index.

The immediate target should be:

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

For Cloudflare Pages specifically, do not assume `uv` is preinstalled. Cloudflare's current v3 build image documents
Python, `pip`, `pipx`, and Poetry, but not `uv`. Unless the repo adds an explicit uv install step, the safer Pages build
command is:

```text
python -m pip install -e ".[docs]" && python -m mkdocs build --strict
```

This supersedes the prior DigitalOcean droplet path. The droplet can stop being the origin for `sase.sh` once the Pages
project has a successful production deploy and the `sase.sh` custom domain is attached.

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
