---
create_time: 2026-05-09 11:20:47
status: done
prompt: sdd/prompts/202605/cloudflare_pages_rss_build_fix.md
---
# Plan: Fix Cloudflare Pages RSS Build Failure

## Problem Summary

The `sase.sh` MkDocs build fails on Cloudflare Pages inside `mkdocs-rss-plugin`:

```text
File ".../mkdocs_rss_plugin/git_manager/ci.py", line 97, in commit_count
  refs = [x.split()[0] for x in refs]
IndexError: list index out of range
```

The failing code path is in `mkdocs-rss-plugin==1.18.1`. During plugin startup it checks whether the checkout is shallow
by looking for `.git/shallow`. If the checkout is shallow, it calls `git for-each-ref()`, splits each returned line, and
assumes every line has a first field. Cloudflare Pages can build from a shallow, detached checkout where no refs are
available to `for-each-ref`, so the plugin receives an empty string and crashes while trying to emit a CI shallow-clone
warning.

The site configuration already tells the RSS plugin to use frontmatter for creation dates:

```yaml
date_from_meta:
  as_creation: date
```

The current blog post has `date: 2026-05-08`, so the RSS feed does not need Git history for creation dates.

## Root Cause

The root cause is not an invalid Markdown page or a Cloudflare deploy step itself. It is the combination of:

- an unpinned `mkdocs-rss-plugin` dependency installed fresh in Cloudflare Pages,
- the plugin's default `use_git: true` behavior,
- Cloudflare's shallow/detached build checkout shape, and
- a plugin bug in the shallow-clone warning path when `git for-each-ref` returns no refs.

## Implementation Plan

1. Update `mkdocs.yml` under the `rss` plugin configuration to set `use_git: false`.
   - This disables Git log inspection and repository validation inside the RSS plugin.
   - RSS dates will come from page frontmatter via the existing `date_from_meta.as_creation: date` setting.
   - This directly avoids the Cloudflare-specific shallow-ref crash.

2. Tighten dependency reproducibility for the docs build.
   - Align `requirements-docs.txt` with the docs dependency source by adding reasonable version bounds for
     `mkdocs-material` and `mkdocs-rss-plugin`.
   - Keep bounds broad enough for patch/minor updates, but avoid silently adopting future breaking plugin behavior.
   - Because the Cloudflare build appears to use `requirements-docs.txt`, this file should be treated as the deployed
     docs dependency contract, not only a convenience file.

3. Regenerate/update the lockfile if the repo's `uv.lock` is stale relative to `pyproject.toml`.
   - `pyproject.toml` includes `mkdocs-rss-plugin` in the docs extra, but `uv.lock` currently records only
     `mkdocs-material` under the `sase[docs]` optional dependencies.
   - If `uv lock` is available and works, refresh the lock so local `just docs-check` and locked installs agree with the
     declared docs extra.

4. Validate the fix locally.
   - Run a normal strict docs build.
   - Reproduce a CI-like failure mode by building from a temporary shallow/no-ref Git checkout or by otherwise forcing
     the RSS plugin away from Git, confirming the build no longer reaches `CiHandler.commit_count`.
   - Run the repo-required `just install` and `just check` after code/config changes, unless a dependency/environment
     blocker makes that impractical.

## Risks And Tradeoffs

- Disabling Git means RSS update dates will no longer be derived from commit history. For the current blog launch state,
  creation dates from frontmatter are the important stable value.
- Future blog posts must include `date` frontmatter. That matches the existing content pattern and is clearer than
  depending on host-specific Git history.
- Pinning/bounding docs dependencies reduces deploy surprise but may require occasional manual updates.
