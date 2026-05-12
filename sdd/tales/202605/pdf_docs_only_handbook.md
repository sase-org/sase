---
create_time: 2026-05-12 11:10:06
status: wip
prompt: sdd/prompts/202605/pdf_docs_only_handbook.md
---
# Plan: Fix "Failed to load PDF document" and Shrink Handbook PDF to docs/ Only

## Problem Statement

Two related problems are tracked here:

1. **Visible symptom.** Visiting `https://sase.sh/downloads/sase-handbook.pdf` shows Chrome's "Failed to load PDF
   document" viewer error.
2. **Content scope.** The aggregate PDF currently bundles the full SASE Blog series alongside `docs/`. The user wants
   the handbook to contain only the documentation pages, not the blog/series content, so the file stays small.

## Diagnosis: Why The PDF Fails To Load

The Chrome error is **not** a corruption of the binary itself. The PDF that the build produces is well-formed:

- `just docs-pdf-check` runs `tools/postprocess_docs_pdf` and `tools/validate_docs_pdf` on every deploy and the
  validator passes (`340 pages, 17.3 MiB`) on the latest `master` runs.
- A direct download (`curl` against `https://sase.sh/downloads/sase-handbook.pdf`) at the moment of investigation
  returned an 18,118,834-byte file whose `pdfinfo` output reports a valid PDF 1.4 with 340 pages, the expected metadata
  (`Title: SASE Handbook`, `Author: SASE contributors`, `Producer: MkDocs Exporter; pypdf post-processing`), and a
  well-formed `%%EOF` trailer.

What is failing is the **delivery**, not the file. The same URL alternates between `HTTP/2 200` (returning the real PDF)
and `HTTP/2 404` from the Cloudflare Worker. The 404 response is what the user is seeing in the browser:

```
HTTP/2 404
content-type: application/pdf
cache-control: public, max-age=3600, must-revalidate
content-length: 0
```

`docs/_headers` applies `Content-Type: application/pdf` to every `/downloads/*.pdf` route. When the underlying asset is
missing for a request, the Worker still returns the rule's content-type on the 404, so Chrome's built-in PDF viewer
tries to render zero bytes as a PDF and surfaces "Failed to load PDF document." This is the **exact same masking
pattern** that previous tales (`sdd/tales/202605/pdf_download_404_fix.md`, `sdd/tales/202605/pdf_worker_deploy_fix.md`,
`sdd/tales/202605/pdf_wrangler_v4_pin.md`) tracked — only this time the deploy succeeds end-to-end and the file does
exist, so it's an availability gap, not a build/deploy gap.

The availability gap has two contributing factors:

1. **Pushy deploy cadence.** Every push to `master` triggers `.github/workflows/docs-deploy.yml`, which runs
   `wrangler deploy` and replaces the Workers Static Assets manifest. There's a short window during a deploy where the
   route can resolve to 404 for clients that miss the prior manifest's cache.

2. **PDF size near the per-asset boundary.** Cloudflare Workers Static Assets has a documented 25 MiB hard limit per
   individual file. The handbook is at 17.3 MiB after the validator's 22 MiB gate. The file keeps growing every time a
   new doc or blog post is added: the prior recorded build was 16.6 MiB / 267 pages; the current build is 17.3 MiB / 340
   pages. We are inside the headroom but trending toward it, and the headroom only exists because we haven't yet hit a
   ceiling. Reducing the bundle is the durable fix; the headroom is not.

The cleanest, single-cause framing: **a 404 served as `Content-Type: application/pdf` is indistinguishable from a
corrupt PDF in the browser.** Whatever else we do, the priority fix is to (a) stop including content we don't want in
the bundle, which drops both size and number of files, and (b) close the masking-headers gap so a future asset miss
doesn't surface as "broken PDF" again.

## Fix Strategy

Two concurrent threads, neither of which depends on the other:

### Thread A — Bundle only `docs/` content (the user's request and the main remediation)

Change the PDF build to consume the same `docs/` Markdown files except the blog and the series outline:

- Drop from the PDF nav:
  - `docs/blog/index.md`
  - `docs/series/agentic-software-engineering.md`
  - All `docs/blog/posts/*.md`
- Keep everything else under `docs/` exactly as it is.

Implementation approach: introduce a **PDF-specific nav** in `mkdocs-pdf.yml` that overrides `mkdocs.yml`'s `nav:` block
with the docs-only chapter list. The PDF config already overrides plugins (`exporter`, `blog`, `rss`); overriding `nav`
fits the same model and keeps the website build untouched — `sase.sh` continues to host the blog as before.

Downstream pieces that hard-code the blog-bearing chapter map must move in lockstep:

- `docs/templates/pdf/front.html.j2` lists chapters 1–27 in the cover TOC. Drop "SASE Blog" (currently #2) and "SASE
  Blog Series" (currently #3), then renumber the rest down by two. The cover template is PDF-only, so this is a pure
  text edit.
- `docs/javascripts/pdf-numbering.js` numbers headings in each chapter by path. Remove the `/blog/` and
  `/series/agentic-software-engineering/` entries from its `chapters` map and renumber every entry below them. The
  script is loaded only during PDF export (`mkdocs-pdf.yml: plugins.exporter.formats.pdf.scripts`), so the live site is
  unaffected.
- `tools/validate_docs_pdf` currently enforces blog-presence sentinels (`BLOG_SENTINELS`,
  `"Why Coding Agents Need Orchestration"` in `REQUIRED_SENTINELS`). Replace those with docs-only sentinels and remove
  the blog sentinel block entirely so the validator fails fast if blog content ever sneaks back into the bundle.
- `tools/postprocess_docs_pdf` reads `mkdocs.yml` to flatten the nav for chapter outlines. Point it at the PDF config
  (`mkdocs-pdf.yml`) instead, so the outline pages match what was actually rendered.
- `MAX_SIZE_BYTES` in `tools/validate_docs_pdf` is currently 22 MiB. After the trim the file will be substantially
  smaller; tighten the gate to a sensible new ceiling (proposal: 16 MiB) so size regressions are caught quickly. The
  exact number can be set after observing the post-trim size locally.

### Thread B — Stop 404s from being framed as broken PDFs

Two small belt-and-suspenders changes so the deploy-window 404 (or any future asset miss) is unambiguous in the browser:

- In `docs/_headers`, remove the unconditional `Content-Type: application/pdf` on `/downloads/*.pdf`. Workers Static
  Assets already infers `application/pdf` from the file extension when the asset exists; the only behavior that the
  header rule adds is mis-labeling 404 responses. Keep `Cache-Control` and `X-Content-Type-Options` on the same route if
  we still want those.
- Optionally, add a small post-deploy probe in `.github/workflows/docs-deploy.yml` that waits for the deploy to
  propagate and confirms `Content-Length` matches the locally built artifact's size, not just that the file is non-empty
  and starts with `%PDF`. The current smoke step already polls and tolerates the propagation gap, so this is purely a
  hardening; we may decide it's not worth the complexity.

Thread B is independent of Thread A and can be skipped without blocking the main work, but it directly addresses the
"failed to load PDF document" symptom the user actually saw, so it belongs in the same change.

## Implementation Plan

1. **Add the docs-only nav to `mkdocs-pdf.yml`.** Copy `mkdocs.yml`'s `nav:` block, delete the `Blog:` section entirely.
   Verify locally with `just docs-pdf-check` that the aggregate file only contains docs chapters.

2. **Update the cover TOC** (`docs/templates/pdf/front.html.j2`) so its enumerated chapter list matches the new PDF-only
   nav order.

3. **Update `docs/javascripts/pdf-numbering.js`** to drop the blog/series entries and renumber the rest.

4. **Repoint `tools/postprocess_docs_pdf`** at `mkdocs-pdf.yml` (`MKDOCS_CONFIG = Path("mkdocs-pdf.yml")`) so chapter
   outlines come from the actual PDF nav.

5. **Update `tools/validate_docs_pdf`:**
   - Remove `BLOG_SENTINELS` and the `"Why Coding Agents Need Orchestration"` entry from `REQUIRED_SENTINELS`.
   - Add a positive sentinel asserting the blog is **absent** (e.g. assert that none of the blog post titles appear in
     the extracted text) so a regression that re-adds blog content fails the gate.
   - Lower `MAX_SIZE_BYTES` to a new headroom-respecting ceiling once the trimmed size is observed.

6. **Address the masking headers** in `docs/_headers`: drop the explicit `Content-Type: application/pdf` on
   `/downloads/*.pdf`. Keep cache and nosniff rules.

7. **Run the full local validation:** `just install` (workspace may be stale), `just docs-check`, `just docs-pdf-check`,
   `just check`. The PDF validator must pass with the new sentinels and the new size ceiling.

8. **Manual end-to-end check** after merge: confirm the deployed PDF opens in Chrome and Firefox, and that the file size
   dropped meaningfully (target: well under 12 MiB).

## Validation

- `just install`
- `just docs-check`
- `just docs-pdf-check` — must produce `site/downloads/sase-handbook.pdf` whose validator output reflects the smaller
  size and docs-only chapters.
- `just check`
- `git diff --check`
- Post-merge: hit `https://sase.sh/downloads/sase-handbook.pdf` from a fresh browser session and confirm the file opens.

## Risks And Tradeoffs

- **Removing blog content from the PDF is a documentation surface decision.** Readers who downloaded the PDF for the
  full SASE narrative (including blog) will see fewer chapters. The live site still hosts the blog. We accept this
  reduction as the explicit intent of the change.
- **Renumbering chapters** in two places (the cover template and the JS heading-numbering map) is duplicated state; a
  follow-up could derive both from the PDF nav at build time. Out of scope for this change.
- **Dropping the `Content-Type` header on `/downloads/*.pdf`** assumes Cloudflare Workers Static Assets correctly infers
  PDF MIME from the file extension. This is documented behavior, but the post-deploy smoke step will catch regressions
  on the next deploy. If we want to be conservative, we can keep the rule and instead add a 404 page for `/downloads/*`
  that returns proper headers; that's bigger and not necessary here.
- **Lowering `MAX_SIZE_BYTES`** can cause false-positive CI failures the first time someone adds a large image to docs.
  Pick the ceiling with enough headroom that ordinary docs growth is fine but a re-bundled blog (the regression we care
  about) will trip it.

## Out Of Scope

- Changing the Cloudflare deploy infrastructure (Worker vs. Pages, wrangler version, asset routing). The current setup
  is correct and the existing tales already covered those issues.
- Adding new content to the handbook PDF.
- Refactoring `postprocess_docs_pdf` to derive cover TOC and JS chapter map automatically. Worth doing later if we
  reorder chapters again.
