---
create_time: 2026-05-08 17:46:38
status: done
prompt: sdd/prompts/202605/cloudflare_pages_blog_launch_steps_1_3.md
---
# Cloudflare Pages Blog Launch Steps 1-3 Plan

## Context

The launch checklist in `sdd/research/202605/cloudflare_pages_sase_blog_launch.md` defines the first three repo-side
steps before Cloudflare dashboard work:

1. Add `mkdocs.yml`, blog structure, homepage, and first post stub.
2. Add docs dependencies and a local/docs check command.
3. Run `uv sync --extra docs && uv run mkdocs build --strict` locally.

The current repo already has a populated `docs/` directory but no root `mkdocs.yml`, no `docs/index.md`, no `docs/blog/`
structure, and no docs optional dependency extra in `pyproject.toml`. `Justfile` has the normal install, lint, format,
test, and `check` targets but no docs-specific build target.

The implementation should keep this as a static MkDocs Material site rooted at the repo root, using the existing `docs/`
tree as the source. It should not touch Cloudflare DNS, Pages project settings, analytics, comments, social cards, or
deploy workflows in this phase.

## Design Choices

- Use root-level `mkdocs.yml` and existing `docs/`, matching the research recommendation and avoiding a second docs
  source tree.
- Use `mkdocs-material` with the built-in Material blog plugin. Current Material docs confirm the blog plugin is built
  in once Material is installed and only needs `plugins: - blog` configuration.
- Configure `site_url: https://sase.sh/` so canonical URLs are correct once deployed.
- Use date-free blog post URLs by setting the blog plugin `post_url_format` to `{slug}`. This matches the research
  preference for evergreen SASE posts at `/blog/<slug>/`.
- Keep launch navigation conservative. Strict MkDocs builds fail on warnings, including omitted files when an explicit
  nav leaves docs out. The lowest-risk first implementation is either:
  - omit explicit `nav` and let MkDocs infer the full existing docs tree while the blog plugin adds blog navigation, or
  - include a complete explicit nav covering every existing docs file.

  I will start with inferred navigation unless the build output shows a reason to define a full nav immediately. This
  gets the site compiling without creating a large, brittle navigation taxonomy as part of the launch bootstrap.

- Add a `docs` optional dependency extra in `pyproject.toml`, then update `uv.lock` through `uv sync --extra docs`. This
  keeps local builds, Cloudflare's pip-based build, and future CI checks aligned around the same package metadata.
- Add a `Justfile` target for docs builds, likely `docs-check`, that runs `uv run mkdocs build --strict`. Do not wire it
  into `just check` yet unless the initial strict build is stable and quick enough; the launch checklist only requires a
  local/docs check command and a local strict build.

## Implementation Plan

1. Add the MkDocs site scaffold.
   - Create root `mkdocs.yml` with `site_name`, `site_url`, `repo_url`, `docs_dir`, `site_dir`, Material theme, search
     plugin, and blog plugin.
   - Add Material features only where they support existing docs and do not introduce new moving parts.
   - Keep social cards, RSS, comments, analytics, and custom templates out of this initial pass.

2. Add launch content structure.
   - Create `docs/index.md` as a compact product/docs homepage adapted from the README and research notes.
   - Create `docs/blog/index.md` as the canonical blog index landing page.
   - Create `docs/blog/posts/why-coding-agents-need-orchestration.md` as the first post stub, with front matter, an
     excerpt separator, and enough placeholder structure to validate the blog pipeline without pretending the final
     article is written.
   - Create `docs/series/agentic-software-engineering.md` as the series landing stub if the blog index or first post
     links to it. If not needed for strict-link success, defer it to avoid extra surface.

3. Add Cloudflare-compatible static files.
   - Add `docs/_headers` with conservative baseline headers for generated static output.
   - Add `docs/_redirects` with local path redirects only, such as `/blog /blog/ 301`.
   - Do not encode `www -> apex` in `_redirects`; that belongs in Cloudflare Bulk Redirects per the research.

4. Add docs dependencies and local command.
   - Add a `docs` extra under `[project.optional-dependencies]` with `mkdocs-material`.
   - Add `mkdocs-rss-plugin` only if it is configured and passes strict build in this phase; otherwise defer until RSS
     is explicitly configured.
   - Avoid `mkdocs-git-revision-date-localized-plugin` for now because the first three launch steps do not require
     git-history-aware dates and Cloudflare shallow clone behavior adds avoidable complexity.
   - Add a `Justfile` docs target, using the repo's `.venv` and `uv run` conventions, for example `docs-check`.

5. Run and fix the strict docs build.
   - Run `uv sync --extra docs`.
   - Run `uv run mkdocs build --strict`.
   - If strict build fails on existing docs links or Markdown issues, fix only issues required for the docs site to
     build. Avoid opportunistic docs rewrites.
   - Re-run the strict build until it passes.

6. Run repo verification.
   - Because the work changes tracked repo files, run `just install` first if dependencies may be stale.
   - Run `just check` before reporting completion, per local instructions.
   - If Markdown formatting changes are needed, use `just fmt-md` or targeted formatting and re-run checks.

## Expected File Changes

- `mkdocs.yml`
- `docs/index.md`
- `docs/blog/index.md`
- `docs/blog/posts/why-coding-agents-need-orchestration.md`
- possibly `docs/series/agentic-software-engineering.md`
- `docs/_headers`
- `docs/_redirects`
- `pyproject.toml`
- `uv.lock`
- `Justfile`

## Risks

- Existing docs may contain relative links that render fine on GitHub but fail under MkDocs strict validation. Those
  should be repaired narrowly.
- A full explicit navigation would be nicer for launch polish but risks turning the bootstrap into a larger taxonomy
  task. The first pass should prioritize a working strict build.
- Adding optional dependencies changes `uv.lock`; this is expected and should be reviewed as dependency churn, not hand
  edited.
- The first post will be a stub. It proves the blog route, metadata, excerpt, and generated URL, but it should remain
  clearly unfinished until the real article content is ready.

## Definition of Done

- `uv sync --extra docs` succeeds.
- `uv run mkdocs build --strict` succeeds and writes `site/`.
- The generated site includes `/`, `/blog/`, and a first post URL under `/blog/`.
- A local docs check command exists in `Justfile`.
- `just check` passes after the repo changes.
