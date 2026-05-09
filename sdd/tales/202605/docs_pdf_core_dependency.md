---
create_time: 2026-05-09 13:19:26
status: done
prompt: sdd/prompts/202605/docs_pdf_core_dependency.md
---
# Fix `docs-pdf-check` dependency resolution

## Context

GitHub Actions fails while running `just docs-pdf-check` in docs-only workflows:

```text
uv pip install --python .venv/bin/python --no-sources -e ".[docs-pdf]"
Because sase-core-rs was not found in the package registry and
sase==0.1.0 depends on sase-core-rs>=0.1.1,<0.2.0
```

The project correctly declares `sase-core-rs` as a hard runtime dependency of the `sase` Python package. Application
jobs satisfy that dependency by checking out the sibling `sase-core` repository and building the local PyO3 package
before installing `sase`.

The docs CI and docs deployment workflows intentionally do not check out `sase-core` or install Rust. That is
reasonable: MkDocs and the PDF validation script need documentation tooling, Playwright/Chromium, and `pypdf`; they do
not need the runtime `sase` package or the Rust extension.

The root cause is that `docs-pdf-check` installs the editable project with the `docs-pdf` extra. Installing any project
extra still installs the base project and therefore requires the base runtime dependency `sase-core-rs`. Since
`sase-core-rs` is unavailable in that docs-only CI environment, dependency resolution fails before the PDF build starts.

This mirrors the earlier `docs-check` issue, which was fixed by installing MkDocs dependencies directly instead of
installing `sase[docs]`.

## Plan

1. Update `Justfile` so `docs-pdf-check` remains docs-only:
   - keep it depending on `_venv`;
   - replace `uv pip install --no-sources -e ".[docs-pdf]"` with direct installation of the tooling required by the
     recipe;
   - use the same version constraints as the `docs-pdf` optional dependency group in `pyproject.toml`.

2. Preserve the existing PDF build behavior:
   - keep the Playwright Chromium install step;
   - keep `SASE_PDF_BUILD_DATE`, strict `mkdocs-pdf.yml` build, and `tools/validate_docs_pdf`;
   - do not weaken the `sase-core-rs` runtime dependency for real package installs.

3. Improve nearby comments if needed so future edits do not reintroduce editable project installs in docs-only checks.

4. Validate the fix:
   - run `SASE_CORE_DIR=/tmp/nonexistent-sase-core just docs-pdf-check` to simulate docs CI without a Rust core
     checkout;
   - run `just install` if the workspace environment needs refreshing;
   - run `just check` because the repo instructions require it after file changes, unless an environment blocker
     prevents completion.

## Expected Result

`just docs-pdf-check` will build and validate the handbook PDF in docs-only GitHub Actions jobs without trying to
resolve or build `sase-core-rs`. Application install/test jobs continue to exercise the normal Rust-core dependency
path.
