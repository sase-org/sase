---
create_time: 2026-05-12 11:30:48
status: done
prompt: sdd/prompts/202605/fix_homepage_blog_links.md
---
# Fix sase.sh Homepage Blog Links

## Context

The normal MkDocs build generates blog posts at `blog/posts/<slug>/`, as configured by `mkdocs.yml`:

```yaml
plugins:
  - blog:
      post_url_format: "posts/{slug}"
```

The home page currently links the launch essay as `blog/why-coding-agents-need-orchestration/`, which does not match the
generated output. The correct path is `blog/posts/why-coding-agents-need-orchestration/`.

There is also a deployment-order problem. The docs deploy workflow runs `just docs-check` and then
`just docs-pdf-check`. The PDF config inherits from the main MkDocs config, excludes `blog/` and `series/`, and writes
to the same `site/` directory. That means the PDF build can clobber the normal site output before Cloudflare deploys it,
leaving home-page links to `blog/` and `series/` broken even when the source links are otherwise correct.

## Goals

- Make home-page blog post links match the canonical MkDocs blog URLs.
- Preserve generated `blog/` and `series/` pages in the deploy artifact after the PDF handbook build.
- Keep the PDF handbook docs-only, with blog content excluded.
- Add validation that would have caught this regression locally and in CI/deploy.

## Plan

1. Update the broken home-page link in `docs/index.md` from `blog/why-coding-agents-need-orchestration/` to
   `blog/posts/why-coding-agents-need-orchestration/`.

2. Adjust the PDF build path so it does not overwrite the deployable site tree:
   - Build the PDF-configured MkDocs output into an isolated temporary directory.
   - Run the existing PDF post-processing and validation against that isolated directory.
   - Copy only `downloads/sase-handbook.pdf` into the real `site/downloads/` directory after the normal `docs-check`
     build has produced the deployable site.

3. Generalize `tools/postprocess_docs_pdf` and `tools/validate_docs_pdf` just enough to accept a site directory
   override, defaulting to `site` for current behavior. This keeps the tools reusable for the isolated PDF output
   without duplicating PDF logic.

4. Strengthen deploy artifact verification:
   - Check that `site/blog/index.html` exists.
   - Check that `site/blog/posts/why-coding-agents-need-orchestration/index.html` exists.
   - Check that `site/series/agentic-software-engineering/index.html` exists.
   - Optionally check the homepage no longer contains the known-bad `href="blog/why-coding-agents-need-orchestration/"`.

5. Validate locally:
   - Run `just docs-check`.
   - Run `just docs-pdf-check`.
   - Confirm the final `site/` tree contains the blog post, series page, homepage, `_headers`, and handbook PDF.
   - Run a small local href target check for same-site links on `site/index.html`.

6. Because these are source changes in this repo, run `just check` before finishing. Per workspace memory, run
   `just install` first if the environment looks stale or dependency state is uncertain.

## Risks and Notes

- `mkdocs-pdf.yml` intentionally excludes blog and series pages from the PDF. The fix should preserve that behavior; it
  should not put launch essays into the handbook.
- The source `site/` directory is generated and ignored. The durable fix belongs in `docs/index.md`, `Justfile`, the PDF
  helper tools, and CI/deploy verification.
- If `mkdocs-exporter` requires the output path to be named `site`, use an environment-variable override for the helper
  tools and an explicit temporary `--site-dir` passed to MkDocs rather than changing the committed `site_dir`.
