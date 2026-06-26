---
title: Plugin catalog verification cleanup
create_time: 2026-06-25 19:59:05
status: done
prompt: sdd/prompts/202606/plugin_catalog_verification.md
---

# Plan: Plugin catalog verification cleanup

## Context

Verification of `sase-57` found that the implementation and tests match the intended behavior for the new
`sase plugin list` / `sase plugin show` catalog feature, but one documentation sentence in `docs/plugins.md` is
over-broad: it says a missing `gh` can fall back to cache, while the source and tests intentionally hard-error when `gh`
is not on `PATH`. Failed `gh` calls with an existing cache still fall back to stale cached data.

## Steps

1. Update `docs/plugins.md` so the cache fallback description distinguishes missing `gh` from failed/unauthenticated
   `gh` calls.
2. Run focused plugin catalog tests and command smoke checks from the repo-local editable install.
3. Update the epic plan frontmatter status to `done` once the implementation and verification are complete.
4. Close bead `sase-57` as the final implementation step.
