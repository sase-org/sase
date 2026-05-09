---
create_time: 2026-05-09 03:37:37
status: wip
prompt: sdd/prompts/202605/sase_2g_deployment_finish.md
---
# Finish sase-2g Deployment Verification

## Context

The repo-side work for `sase-2g` verifies locally:

- `just install` passed.
- `just docs-check` passed.
- `just check` passed.
- `.venv/bin/python -m pip install -e ".[docs]" && .venv/bin/python -m mkdocs build --strict` passed, so the docs build
  path does not require `uv`.
- The rebuilt `site/` artifact contains `site/index.html`, `site/blog/index.html`,
  `site/series/agentic-software-engineering/index.html`, `site/sitemap.xml`, `site/robots.txt`, `site/_headers`, and
  `site/_redirects`.

The remaining issue is production deployment state:

- `https://sase.sh/` returns 200 and contains the polished homepage.
- `https://sase.sh/blog/` returns 200.
- `https://sase.sh/series/agentic-software-engineering/` returns 404 even though the local artifact contains the page.
- The live `https://sase.sh/sitemap.xml` contains blog URLs but does not contain `series/agentic-software-engineering`.
- `https://www.sase.sh/blog/` still fails DNS resolution, which matches the epic's existing external DNS follow-up note.
- This workspace does not expose Cloudflare credentials (`CLOUDFLARE_*`, `CF_*`, `WRANGLER_*`, or `PAGES_*`) and the
  repo does not contain a Cloudflare deploy workflow, so I cannot deploy or force a Pages rebuild from here.

## Plan

1. Trigger a Cloudflare Pages redeploy for the current `master` commit (`d88f8650`) through the Cloudflare dashboard or
   an authenticated `wrangler pages deploy site --project-name=sase-sh --branch=master` flow.
2. Re-run the production checks:
   - `curl -I https://sase.sh/`
   - `curl -I https://sase.sh/blog/`
   - `curl -I https://sase.sh/series/agentic-software-engineering/`
   - `curl -s https://sase.sh/ | rg 'canonical|og:|twitter:'`
   - `curl -s https://sase.sh/sitemap.xml | rg 'series/agentic-software-engineering|blog'`
   - `curl -I https://www.sase.sh/blog/`
3. If the series URL still returns 404 after redeploy, inspect the Cloudflare Pages build log and deployed artifact to
   confirm whether `site/series/agentic-software-engineering/index.html` was uploaded. Fix the deployment configuration
   if the artifact is missing.
4. Treat `www.sase.sh` DNS failure as an external Cloudflare DNS/Bulk Redirect task unless a `www` DNS record exists and
   the failure persists after redeploy.
5. Update `sdd/epics/202605/sase_sh_mkdocs_polish.md` frontmatter to `status: done` only after the apex production
   checks pass, with any external `www` DNS caveat documented.
6. Close `sase-2g` using `sase bead close sase-2g`, then run `just pyvision`.
