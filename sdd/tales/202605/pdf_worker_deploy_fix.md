---
create_time: 2026-05-09 14:07:29
status: done
prompt: sdd/prompts/202605/pdf_worker_deploy_fix.md
---
# Plan: Fix SASE Handbook Deployment To Cloudflare Worker

## Problem

`https://sase.sh/downloads/sase-handbook.pdf` still returns `404` even though the repo now builds and validates
`site/downloads/sase-handbook.pdf`. The latest production response applies the `/downloads/*.pdf` header from
`docs/_headers`, so Chrome reports the missing route as an invalid PDF response.

GitHub Actions shows the current `Deploy Docs` workflow failing at the Cloudflare deploy step. The workflow still runs
`wrangler pages deploy site --project-name=sase-sh`, but Cloudflare reports that the `sase-sh` Pages project does not
exist in the account. A recently merged Cloudflare bot PR added `wrangler.jsonc` for a Cloudflare Worker named `sase`
with static assets served from `site/`, which means the deployment target changed from Pages to Workers Static Assets.

## Implementation

1. Update `.github/workflows/docs-deploy.yml` so it deploys the prebuilt `site/` directory with the checked-in
   `wrangler.jsonc` Worker configuration.
   - Keep the existing `just docs-check`, `just docs-pdf-check`, and artifact verification steps.
   - Replace the Pages deploy command with `wrangler deploy`.
   - Keep the post-deploy PDF smoke test against `https://sase.sh/downloads/sase-handbook.pdf`.

2. Update documentation that currently says production deploys to the `sase-sh` Cloudflare Pages project.
   - Describe the production target as the `sase` Cloudflare Worker with Static Assets.
   - Keep the required `CLOUDFLARE_API_TOKEN` note, and remove stale Pages project/account-secret guidance unless still
     needed by the workflow.

3. Validate the change locally.
   - Run `just install` first if the workspace dependencies may be stale.
   - Run `just docs-check`.
   - Run `just docs-pdf-check`.
   - Run `just check` because repo files changed.
   - Run `git diff --check`.

## Expected Outcome

The next `master` deploy should publish the generated PDF inside the Worker static asset bundle. The smoke step should
fail the workflow if the live URL is still missing or not a real PDF, preventing another silent broken download.

## Remaining External Requirement

The GitHub repository must have a `CLOUDFLARE_API_TOKEN` secret with permission to deploy the `sase` Worker. If that
token is scoped only to Pages and not Workers, the code change is correct but the secret permissions must be expanded in
Cloudflare.
