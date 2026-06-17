---
create_time: 2026-06-17 08:09:41
status: done
prompt: sdd/prompts/202606/fix_stale_pdf_blog_sentinels.md
---
# Fix stale blog-post sentinels in the docs PDF validator

## Problem

The `docs-pdf-check` job in GitHub Actions (`.github/workflows/docs-deploy.yml`, `.github/workflows/ci.yml`) fails with:

```
[postprocess_docs_pdf] ok: /tmp/.../downloads/sase-handbook.pdf (38 chapter outlines)
[validate_docs_pdf] missing blog-post sentinel text
error: Recipe `docs-pdf-check` failed on line 277 with exit code 1
```

The PDF handbook **builds correctly**. The mkdocs log shows every blog page rendering into the aggregated PDF
(`blog/index.md`, `blog/posts/why-coding-agents-need-orchestration.md`,
`blog/posts/hello-sase-your-first-15-minutes.md`), and `postprocess_docs_pdf` reports success with 38 chapter outlines.
The failure is a **stale post-build assertion**, not a broken build.

## Root cause

`tools/validate_docs_pdf` confirms blog content reached the PDF by requiring that the extracted text contain at least
one of two hardcoded `BLOG_SENTINELS` (lines 27-30, checked at lines 155-157 with `any(...)`):

```python
BLOG_SENTINELS = (
    "Coding agents are strongest when they operate inside a workflow",
    "Published posts appear below",
)
```

Both phrases have since been edited out of the docs, so neither appears in the rendered PDF and the `any(...)` check
fails:

- `"Coding agents are strongest when they operate inside a workflow"` was the opening paragraph of
  `docs/blog/posts/why-coding-agents-need-orchestration.md`. It was removed when commit `e96510106` ("docs: rewrite SASE
  launch essay") rewrote the essay; the post now opens with "SASE is not a better model."
- `"Published posts appear below"` was a line in `docs/blog/index.md`. It was removed by commit `bd687ae04` ("chore:
  audit blog index docs"); the index now ends that paragraph with "...lists only the entries included in the public
  site."

The validator was never updated to track these edits, so the sentinels rot whenever the blog prose changes. (Note: the
sibling `REQUIRED_SENTINELS` entry `"Why Coding Agents Need Orchestration"` still passes only by luck — it now matches
`docs/index.md:214` ("Why coding agents need orchestration above individual provider CLIs.") rather than the blog post
it was meant to track. This is the same class of fragility but is not the current failure; see Out of scope.)

No tests or fixtures reference `validate_docs_pdf`, its sentinels, or the `BLOG_SENTINELS` constant — the fix is
self-contained to the tool. This change touches only a docs-tooling Python script under `tools/`, so it does not cross
the Rust core backend boundary.

## Goal

Make `docs-pdf-check` pass again by validating against blog text that actually exists in the current PDF, and choose
anchors durable enough that ordinary blog-prose edits will not re-break the check.

## Approach

Replace the two stale `BLOG_SENTINELS` in `tools/validate_docs_pdf` with phrases drawn from the **structural /
definitional** parts of the current blog content rather than essay-flavored prose that is likely to be rewritten:

1. From `docs/blog/index.md` (line 3, the blog's self-description, stable boilerplate):
   `"The SASE Blog is the publishing surface for essays"`
2. From `docs/blog/posts/why-coding-agents-need-orchestration.md` (the definitional sentence in the "What SASE Is"
   section, line ~46): `"SASE is a local orchestration layer above coding-agent CLIs"`

Keep the existing `any(...)` semantics: the check still passes when at least one blog surface (index or post body) is
present in the PDF. Using one anchor from the blog index and one from a blog post body preserves the original
index-or-post intent while making both anchors resistant to prose churn.

The exact replacement strings will be re-verified against the working-tree docs at implementation time (normalizing
whitespace the way `_normalize` does) so they match the current source verbatim.

## Validation

- Run `just docs-pdf-check` locally (builds the PDF via mkdocs + playwright/chromium and runs the validator) and confirm
  `[validate_docs_pdf] ok: ...` instead of the sentinel error. This is the authoritative reproduction of the CI step.
- If a full local PDF build is impractical in this environment, additionally confirm both new sentinel strings appear
  verbatim in the current `docs/blog/index.md` and `docs/blog/posts/why-coding-agents-need-orchestration.md`, since the
  validator extracts the same rendered text the build aggregates.
- Run `just check` (per repo policy for file changes), recognizing the heavy PDF build may be the real gate.

## Out of scope

- Rewriting blog content — the prose is fine; only the validator assertion is stale.
- Re-architecting the validator to derive sentinels dynamically from source files. Worth considering as a durability
  follow-up, but larger than this fix; the chosen structural anchors already greatly reduce churn risk.
- Hardening the `REQUIRED_SENTINELS` "Why Coding Agents Need Orchestration" coincidental match. It is not the current
  failure; can be tracked separately if we want every sentinel pinned to its intended page.
