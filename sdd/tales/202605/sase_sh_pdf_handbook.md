---
create_time: 2026-05-09 12:45:32
status: done
prompt: sdd/prompts/202605/sase_sh_pdf_handbook.md
---
# SASE.sh PDF Handbook Implementation Plan

## Goal

Add a build-time PDF handbook to the `sase.sh` MkDocs Material site so users can download the current public
documentation and blog articles from one stable URL:

```text
/downloads/sase-handbook.pdf
```

The implementation should be static-hosting friendly, reproducible in CI/local builds, and separate from the normal docs
iteration path so `just docs-check` remains fast.

## Design Decisions

Use `mkdocs-exporter` as the first implementation, not `mkdocs-to-pdf`.

Rationale:

- It has first-class aggregate PDF output, which directly matches the product requirement.
- It uses Playwright/Chromium plus Paged.js, so rendering is closer to the live Material site and future JS-rendered
  content such as Mermaid is less likely to produce blank output.
- It is Python-package installable and compatible with the repo's existing docs dependency pattern.
- It can be gated behind a dedicated MkDocs config and Just target, avoiding extra cost for normal docs builds.

Keep the public URL renderer-agnostic. If `mkdocs-exporter` later proves too brittle, the build target can swap
renderers while preserving `/downloads/sase-handbook.pdf`.

Do not generate the PDF dynamically per request. The PDF is a site artifact produced during the docs build.

## Scope

Implement the production path for local and CI validation:

- Add PDF docs dependencies.
- Add a PDF-specific MkDocs config inheriting from `mkdocs.yml`.
- Add PDF print styling and a simple front cover template.
- Add a Just target that installs docs PDF tooling, installs Chromium if needed, builds the PDF, and validates the
  resulting artifact.
- Add a small validation script that checks the PDF exists, is under Cloudflare Pages' practical size headroom, and
  contains sentinel text from the docs and blog corpus.
- Add a visible homepage download link and response headers for PDF assets.
- Wire the CI docs job to build and validate the PDF.

Out of scope for the first implementation:

- Monthly archive copies.
- Cloudflare Worker telemetry.
- Formal PDF/UA conformance certification.
- Moving PDF generation to a separate deployment workflow.

## Files To Change

- `pyproject.toml`
  - Add a `docs-pdf` optional dependency group with `mkdocs-exporter`, while keeping the existing `docs` group for the
    lightweight site build.
- `requirements-docs.txt`
  - Keep it as the plain docs requirement file unless the repo already expects it to mirror all docs extras.
- `mkdocs-pdf.yml`
  - New config with `INHERIT: mkdocs.yml`.
  - Re-declare plugins in safe order: `search`, `blog`, `rss`, then `exporter`.
  - Configure `exporter.formats.pdf.aggregator.output` as `downloads/sase-handbook.pdf`.
  - Use `docs/stylesheets/pdf.css` and `docs/templates/pdf/front.html.j2`.
- `docs/stylesheets/pdf.css`
  - Add print/Paged.js CSS for page size, margins, running headers/footers, readable code blocks, external link
    annotation, image scaling, and website chrome suppression.
- `docs/templates/pdf/front.html.j2`
  - Add a simple cover using site metadata and optional git/build metadata from environment variables if available.
- `docs/index.md`
  - Add a `Download PDF` action in the hero and a handbook card in the "Next clicks" section.
- `docs/_headers`
  - Add `/downloads/*.pdf` headers for content type and conservative cache control.
- `Justfile`
  - Add `docs-pdf-check` that installs `.[docs-pdf]`, ensures the Playwright Chromium browser exists, builds
    `mkdocs-pdf.yml` with strict mode, and runs validation.
  - Keep `docs-check` unchanged for fast normal docs validation.
- `.github/workflows/ci.yml`
  - Update the docs build job to run both `just docs-check` and `just docs-pdf-check`.
- `tools/validate_docs_pdf`
  - New executable Python script using a lightweight PDF reader from the `docs-pdf` extras, preferably `pypdf`, to
    validate size and sentinel text without requiring system `pdftotext`.

## Validation Rules

The validation script should fail when:

- `site/downloads/sase-handbook.pdf` is missing or empty.
- The file is larger than 22 MiB, leaving margin below Cloudflare Pages' 25 MiB per-file cap.
- The extracted text is missing sentinel strings from key docs areas:
  - `Structured Agentic Software Engineering`
  - `ACE TUI`
  - `AXE Automation`
  - `Spec-Driven Development`
  - `ChangeSpecs`
  - `Why Coding Agents Need Orchestration`
- No blog-post sentinel is found.
- The PDF has too few pages to plausibly include the current docs and blog corpus.

The page-count threshold should be conservative at first so styling changes do not create brittle failures. Sentinel
coverage is the stronger omission detector.

## Implementation Steps

1. Add the `docs-pdf` dependency group and lock/update dependencies as needed.
2. Add `mkdocs-pdf.yml`, `docs/stylesheets/pdf.css`, and the front-cover template.
3. Add `tools/validate_docs_pdf` and the `docs-pdf-check` Just target.
4. Run `just docs-pdf-check`, inspect failures, and tune the MkDocs exporter config/CSS until the PDF builds.
5. Add the homepage links and PDF headers.
6. Wire the CI docs job to run `docs-pdf-check`.
7. Run repo validation:
   - `just install`
   - `just docs-check`
   - `just docs-pdf-check`
   - `just check`
   - `just sdd-validate` if any SDD files are touched

## Risks And Mitigations

- `mkdocs-exporter` may require a Playwright browser install in fresh environments.
  - Mitigation: make `docs-pdf-check` install Chromium explicitly and document the target as the supported path.
- Generated blog pages may not be included in the aggregate output.
  - Mitigation: keep the exporter plugin after `blog` and fail validation on the launch-essay sentinel.
- The PDF may exceed Cloudflare's 25 MiB asset cap as image-heavy docs grow.
  - Mitigation: fail above 22 MiB and revisit image compression or split PDFs when that happens.
- CSS generated for browser pages may not translate cleanly to paged output.
  - Mitigation: keep PDF CSS separate and conservative, focused on readability rather than exact site mimicry.
- CI wall time may increase because Chromium is required.
  - Mitigation: only the docs build job pays this cost, and normal `docs-check` stays lightweight.
