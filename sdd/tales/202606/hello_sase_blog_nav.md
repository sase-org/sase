---
create_time: 2026-06-13 16:09:56
status: done
prompt: sdd/prompts/202606/hello_sase_blog_nav.md
---
# Plan: Move [01] Hello, SASE Back Under Blog Navigation

## Objective

Move the public navigation entry for `[01] Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents` out of the
top-level `Getting Started` section and back under the `Blog` section on the generated `sase.sh` site.

## Current State

- The post source is already a blog post: `docs/blog/posts/hello-sase-your-first-15-minutes.md`.
- Its frontmatter title and H1 already use the canonical
  `[01] Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents` title.
- `mkdocs.yml` currently places `blog/posts/hello-sase-your-first-15-minutes.md` under `Getting Started` with the
  shorter label `"Hello, SASE: Your First 15 Minutes"`.
- The `Blog` nav currently contains `Blog Home`, `SASE Blog Series`, and `[00] Why Coding Agents Need Orchestration`,
  but not `[01]`.
- The Material blog plugin is configured with `post_url_format: "posts/{slug}"`, and the deploy checks already expect
  `site/blog/posts/hello-sase-your-first-15-minutes/index.html`, so this should be a navigation placement fix rather
  than a slug or plugin behavior change.

## Proposed Change

1. Edit only `mkdocs.yml`.
2. Remove `blog/posts/hello-sase-your-first-15-minutes.md` from the `Getting Started` nav group.
3. Add the same post path under the `Blog` nav group immediately after `[00] Why Coding Agents Need Orchestration`.
4. Use the canonical visible label: `[01] Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents`
5. Leave all post source, frontmatter, slug, blog plugin configuration, RSS configuration, homepage links, blog index
   copy, series hub copy, and deploy checks unchanged unless verification exposes a concrete inconsistency.

## Verification

After implementation:

1. Run `just install` first, per workspace guidance.
2. Run `just docs-check` to confirm the MkDocs strict build accepts the nav move.
3. Run `just docs-pdf-check` because the PDF build consumes MkDocs navigation and the changed post placement affects the
   generated handbook ordering.
4. Run `just check` because the repo instructions require it after file changes outside the documented exceptions.
5. Inspect the generated navigation output enough to confirm:
   - `Hello, SASE` no longer appears under `Getting Started`.
   - `[01] Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents` appears under `Blog`.
   - The post URL remains `/blog/posts/hello-sase-your-first-15-minutes/`.

## Risks And Constraints

- Do not change the post URL, because existing homepage, blog, series, sitemap, RSS, and deploy checks expect the
  `/blog/posts/hello-sase-your-first-15-minutes/` path.
- Do not change draft handling for unpublished posts.
- Do not edit memory files.
- If strict MkDocs or PDF validation reveals blog-nav edge cases, keep the fix focused on navigation placement and avoid
  broad blog plugin or PDF post-processing changes unless they are necessary for this exact regression.

## Acceptance Criteria

- The `Getting Started` section contains `Initialization` but no direct `Hello, SASE` post entry.
- The `Blog` section lists `[00] Why Coding Agents Need Orchestration` followed by
  `[01] Hello, SASE — Your First 15 Minutes Orchestrating Coding Agents`.
- Generated docs continue to build with the existing `/blog/posts/.../` URL scheme.
- Verification commands pass or any failure is reported with the relevant output and next action.
