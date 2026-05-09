---
create_time: 2026-05-09 13:06:04
status: done
prompt: sdd/prompts/202605/pdf_download_404_fix.md
---
# Plan: Fix Deployed PDF Download 404

## Problem Summary

The production URL `https://sase.sh/downloads/sase-handbook.pdf` fails in the browser with "Failed to load PDF
document." Direct inspection shows the response is a `404` while Cloudflare still applies the `/downloads/*.pdf`
`Content-Type: application/pdf` header from `docs/_headers`. Chrome then tries to render the error response as a PDF,
which produces the misleading PDF viewer error.

The PDF build itself was validated locally and in GitHub Actions via `just docs-pdf-check`, but the public Cloudflare
Pages deploy path is documented as a lightweight MkDocs build:

```text
python -m pip install -e ".[docs]" && python -m mkdocs build --strict
```

That command uses `mkdocs.yml`, not `mkdocs-pdf.yml`, and therefore never generates `site/downloads/sase-handbook.pdf`.
The homepage link and headers deploy, but the binary artifact does not.

## Root Cause

The root cause is a split between validation and deployment:

- GitHub Actions runs `just docs-pdf-check`, proving the PDF can be generated.
- Cloudflare Pages appears to build only the normal site from `mkdocs.yml`.
- `mkdocs-pdf.yml` writes the aggregate PDF to `site/downloads/sase-handbook.pdf`, but that output is not part of the
  Pages-managed deploy artifact unless the Pages build command is changed.
- `docs/_headers` applies `Content-Type: application/pdf` to the missing route, making the 404 look like a corrupt PDF
  instead of a missing file.

## Fix Strategy

Make the deployed artifact include the PDF by moving the production deployment path into the repository, where CI can
build the normal site and PDF in one controlled flow before publishing the resulting `site/` directory to Cloudflare
Pages.

The safer fix is not to make Cloudflare Pages run Playwright/Chromium directly. The existing PDF research and current
`docs-pdf-check` target already recognize that headless-browser PDF generation is better suited to GitHub Actions than
to the Pages build image. Publishing a prebuilt `site/` artifact also removes the current gap where GitHub Actions and
Pages run different commands.

## Implementation Plan

1. Add a dedicated docs deploy workflow.
   - Trigger on pushes to `master`.
   - Check out the repo, set up Python 3.12 and `uv`, install `just`, run `just docs-check`, then run
     `just docs-pdf-check`.
   - Deploy the complete `site/` directory to Cloudflare Pages with `cloudflare/pages-action` or
     `wrangler pages deploy`.
   - Use repository secrets for `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`, and set the configured Pages project
     name in the workflow.

2. Keep the existing `docs-build` CI job as a PR/build gate.
   - It already catches normal docs failures and PDF generation failures.
   - Avoid duplicating deploy credentials in PR contexts.

3. Add a deployed-artifact guard to prevent this regression.
   - Extend `tools/validate_docs_pdf` or add a small deploy check so `site/downloads/sase-handbook.pdf` must exist after
     the complete docs build.
   - The existing validator already checks the generated file, page count, size, and text sentinels; the deploy workflow
     should run it before upload.

4. Reduce the misleading 404 behavior if possible.
   - Keep the correct PDF headers for the successful file.
   - Do not rely on headers alone as proof of file existence.
   - Optionally add a post-deploy smoke command that requests the production URL and verifies `HTTP 200`, `%PDF` magic
     bytes, and a sane `Content-Length`.

5. Document the deployment contract.
   - Update the Cloudflare deployment notes/research or README docs section to say production is deployed from the
     GitHub Actions prebuilt `site/` artifact, not from the Pages dashboard build command.
   - Include the required Cloudflare secrets and Pages project name so future maintainers do not silently fall back to
     the lightweight Pages build.

## Validation

- Run `just install` if the workspace dependencies may be stale.
- Run `just docs-check`.
- Run `just docs-pdf-check`.
- Run `just check` because repo files changed.
- Run `git diff --check`.
- If deploy credentials are unavailable locally, validate the deploy workflow statically and report that the final live
  URL verification requires the workflow to run on `master`.

## Risks And Tradeoffs

- This requires Cloudflare deploy secrets in GitHub Actions. If they are not configured, the workflow will fail until
  the project owner adds them.
- The Pages dashboard Git integration should be disabled or left unused for production after the Actions deploy path is
  enabled, otherwise two independent deploy systems can race.
- PDF generation adds time to the deploy workflow, but it already runs in CI and is the artifact users now expect at the
  public URL.
