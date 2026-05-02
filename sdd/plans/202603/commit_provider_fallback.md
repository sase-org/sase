---
create_time: 2026-03-29 13:56:59
status: done
prompt: sdd/prompts/202603/commit_provider_fallback.md
---

# Fix `sase commit` failure when GitHub plugin is absent

## Problem

In this workspace/runtime, `sase commit` fails with:

- `No VCS plugin claimed the remote URL 'git@github.com:sase-org/sase.git'`

The failure occurs even though git operations are available via the built-in `bare_git` provider. This blocks normal
commit flows for agents that do not have the optional `sase-github` plugin installed in their runtime environment.

## Root Cause

VCS auto-detection for git repos uses plugin classification first, then URL fallback:

1. Try `vcs_classify_repo` hooks from installed `sase_vcs` plugins.
2. If no plugin claims the repo, call `_classify_by_url`.

Current `_classify_by_url` behavior:

- local filesystem remote path -> `bare_git`
- hosted remotes (`https://`, `git@`, `ssh://`) with no matching plugin -> raise `VCSProviderNotFoundError`

In Codex agent venvs where only `bare_git` is installed, GitHub remotes are hosted URLs and therefore hard-fail instead
of falling back to git-only behavior.

## Proposed Solution

Adjust URL fallback semantics to preserve core git functionality:

- If no plugin claims a git repo, default to `bare_git` for any resolvable git remote URL (including hosted remotes).
- Keep hard errors only for truly indeterminate remote state (e.g., cannot read origin, no origin configured).

This keeps plugin-based specialization (GitHub, etc.) when available, while preserving baseline commit capability when
optional plugins are missing.

## Scope

1. Update `src/sase/vcs_provider/_registry.py`:

- revise `_classify_by_url` to return `bare_git` for non-empty remote URLs not matched by plugins.
- update docstrings/comments to match new fallback behavior.

2. Add regression tests in `tests/test_vcs_provider.py`:

- hosted URL fallback returns `bare_git` when plugin classification did not claim repo.
- maintain existing behavior for missing/unreadable origin (still raises).

3. Verify behavior:

- run targeted tests for VCS registry and commit CLI paths.
- run repo-required validation (`just install`, then `just check`).

## Risks / Tradeoffs

- Hosted repos without provider-specific plugins will now use generic git behavior. This is desired for commit/proposal
  flows, but provider-specific features (e.g. GitHub PR creation) still depend on plugins.
- PR workflows that require provider APIs may fail later with a clearer operation-level error instead of failing at
  detection time.

## Validation Criteria

- `sase commit` no longer fails at provider detection in a git repo with GitHub remote when only `bare_git` plugin is
  present.
- Existing tests pass, with new coverage confirming fallback semantics.
