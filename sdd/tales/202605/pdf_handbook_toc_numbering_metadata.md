---
create_time: 2026-05-09 15:33:39
status: done
prompt: sdd/prompts/202605/pdf_handbook_toc_numbering_metadata.md
---
# Plan: Fix PDF Handbook Cover, TOC, Numbering, And Metadata

## Problem

The deployed `https://sase.sh/downloads/sase-handbook.pdf` is now present and valid, but its first pages are broken and
the document lacks the affordances expected from a real handbook:

- The front cover template is being inserted literally. The PDF shows raw `{{ config.site_name }}` and `{% if ... %}`
  text across the first few pages.
- The aggregated PDF only reports `Producer: MkDocs Exporter`; it has no useful PDF metadata such as title, author,
  subject, or keywords.
- PDF viewers do not get a document outline/bookmarks for handbook sections and chapters.
- The visible handbook content is not numbered, so the PDF does not read like a stable sectioned document.
- The current validator only checks that the PDF exists and contains broad sentinel text, so this regression passed.

The root cause of the broken cover is `mkdocs-exporter` behavior: version `6.2.0` wraps cover template files as raw HTML
in `Renderer.cover()` and does not evaluate Jinja itself. The upstream documentation shows Jinja-looking examples, but
the installed implementation does not render them. The aggregator metadata option is also not enough for this pipeline
because the installed plugin does not pass configured `aggregator.metadata` into `Aggregator.save()`.

## Implementation

### 1. Replace the raw Jinja cover with static PDF front matter

Remove the dynamic Jinja from `docs/templates/pdf/front.html.j2` and make it static HTML that renders cleanly when
inserted by `mkdocs-exporter`.

The front matter should include:

- A polished cover page with the site name, handbook title, description, site URL, and source URL.
- A table-of-contents/front-matter section listing the main handbook chapters in the same order as `mkdocs.yml`.
- No build date/ref/run fields in the cover itself, because the exporter does not render Jinja and dynamic values would
  require a separate pre-render step.

Keep the styling in `docs/stylesheets/pdf.css`, with page breaks and compact TOC styling that does not fragment
awkwardly on Letter pages.

### 2. Add PDF-only heading numbering before export

Add a PDF-only JavaScript file loaded through `mkdocs-pdf.yml` under `formats.pdf.scripts`.

The script should define `window.MkDocsExporter.render`, which `mkdocs-exporter` already calls before Paged.js lays out
the PDF. It should:

- Detect the current page via its canonical URL.
- Use a path-to-chapter map matching the MkDocs nav order.
- Prefix the content `h1` with the chapter number.
- Prefix `h2` and `h3` headings with nested section numbers within that chapter.
- Avoid mutating headings inside the generated cover/front matter.
- Be idempotent so the normal per-page render and the aggregator re-render cannot double-prefix headings.

This keeps the public website unchanged because the script is referenced only by `mkdocs-pdf.yml`.

### 3. Post-process the final aggregate PDF for metadata and bookmarks

Add a small build tool, for example `tools/postprocess_docs_pdf`, and call it from `just docs-pdf-check` after
`mkdocs build --strict -f mkdocs-pdf.yml` and before validation.

The tool should use `pypdf` and the generated per-page PDFs to:

- Write standard PDF document metadata:
  - `/Title`: `SASE Handbook`
  - `/Author`: `SASE contributors`
  - `/Subject`: `Structured Agentic Software Engineering`
  - `/Keywords`: `SASE, agentic software engineering, coding agents, workflows`
  - `/Creator`: the local post-processing tool
  - Keep `/Producer` meaningful.
- Add PDF outline/bookmark entries for every numbered handbook chapter in the same order as the aggregate.
- Add nested bookmarks for the main `h2` sections when practical from each page's MkDocs-generated table of contents or
  HTML headings. If nested bookmark page targeting is too expensive to make precise, add the chapter-level outline first
  and keep nested bookmarks out rather than adding misleading locations.

The tool should write atomically: produce a temporary PDF next to `site/downloads/sase-handbook.pdf`, then replace the
final file only after successful write.

### 4. Strengthen PDF validation

Update `tools/validate_docs_pdf` so CI catches this class of regression:

- Assert the first few pages do not contain raw Jinja tokens such as `{{`, `{%`, `config.site_name`, or
  `pdf_meta.build_date`.
- Assert visible numbering exists for representative chapters/sections, e.g. `1 Structured Agentic Software Engineering`
  and `2.1`/another stable nested section.
- Assert PDF metadata includes the expected title and author.
- Assert the PDF outline/bookmark list is present and includes representative entries such as `ACE TUI User Guide` and
  `Configuration`.

Keep the existing size, page-count, and content sentinel checks.

### 5. Rebuild and inspect locally

After implementation:

1. Run `just docs-pdf-check`.
2. Download production again for comparison if useful, but verify the rebuilt local artifact at
   `site/downloads/sase-handbook.pdf`.
3. Convert the first several local pages to PNG with `pdftoppm` and inspect them for:
   - clean cover rendering,
   - usable TOC/front matter,
   - no raw template syntax,
   - numbered chapter/section headings.
4. Use `pdfinfo` and/or `pypdf` to confirm metadata and outline entries.
5. Run the repo-required `just check` before the final response because implementation files will change.

## Risks And Mitigations

- **Risk:** Manual chapter maps can drift from `mkdocs.yml`. **Mitigation:** keep the map small and explicit, and have
  validation check representative output. If drift becomes frequent, replace it later with a generated JSON manifest.
- **Risk:** PDF bookmarks can point to the wrong pages if computed from final text extraction. **Mitigation:** compute
  page starts from the generated per-page PDFs and the aggregate order, not from fuzzy text matching.
- **Risk:** A rich TOC cover could add several pages and shift all bookmarks. **Mitigation:** compute the final outline
  after the aggregate PDF exists and after front matter has been included.
- **Risk:** The exporter may call the injected JS twice for a page. **Mitigation:** make heading numbering idempotent
  via data attributes.
- **Risk:** Full `just check` may be slow or fail on unrelated environment issues. **Mitigation:** run the targeted PDF
  build first, then run `just check` and report any unrelated failure clearly.
