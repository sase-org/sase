---
create_time: 2026-03-28 11:52:47
status: done
---

# Plan: Default PR Tags for `sase commit`

## Problem

When `sase commit` creates a PR (`create_pull_request` method), there's no way to automatically include
provider-specific metadata tags in the PR description. For example, the retired Mercurial plugin plugin needs every CL to include
tags like `AUTOSUBMIT_BEHAVIOR=SYNC_SUBMIT`, `MARKDOWN=true`, `R=startblock`, etc. Today these would need to be manually
added to every commit message.

## Design

New config field: **`vcs_provider.pr_tags`** — a dict of `TAG: VALUE` pairs, empty by default. Each VCS provider plugin
can define its own defaults via its `default_config.yml`. Users can override in `~/.config/sase/sase.yml`.

**Key insight**: Tags must appear in both `message` (used by Google/Hg for CL description) and `_pr_body` (used by
GitHub for PR body). By appending tags to `message` **before** `_build_pr_body()` runs, `_pr_body` (which is built from
`message`) naturally includes them — no special-casing per provider.

## Changes

### Phase 1: Core (sase_100)

1. **`src/sase/default_config.yml`** — Add `pr_tags: {}` under `vcs_provider`

2. **`src/sase/vcs_provider/config.py`** — Add `get_pr_tags() -> dict[str, str]` helper

3. **`src/sase/workflows/commit/workflow.py`** — Add `_append_pr_tags()` method called before `_build_pr_body()` in the
   `create_pull_request` path. Appends `\nTAG=VALUE` lines to `payload["message"]`.

4. **Tests** — Unit tests for config reader and tag appending; integration test verifying tags flow through to
   `_pr_body`.

### Phase 2: retired Mercurial plugin plugin

5. **`../retired Mercurial plugin/src/retired_mercurial_plugin/default_config.yml`** — Add default `pr_tags`:
   ```yaml
   vcs_provider:
     pr_tags:
       AUTOSUBMIT_BEHAVIOR: SYNC_SUBMIT
       MARKDOWN: "true"
       R: startblock
       STARTBLOCK_AUTOSUBMIT: "yes"
       WANT_LGTM: all
   ```

No changes to sase-github or bare_git — they inherit empty `pr_tags` by default.
