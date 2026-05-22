---
create_time: 2026-05-21 21:12:47
status: done
prompt: sdd/prompts/202605/commit_finalizer_closeout.md
---
# Plan: Commit Finalizer Closeout Verification

## Context

The `sase-3v` epic is mostly implemented, but closeout verification found a stale Gemini `jetski` profile copy of
`sase_git_commit/SKILL.md` in chezmoi/live config that still instructs agents to run raw `sase commit` instead of the
observable `sase_git_commit` wrapper. The normal provider skill copies were regenerated, so the remaining work is to
make the generation path cover this profile-specific Gemini skill directory and verify the regenerated output.

## Steps

1. Extend `sase init-skills` so providers can expose additional skill deployment subpaths, and teach the Gemini provider
   to include the legacy `~/.gemini/jetski/skills` profile path.
2. Add focused tests for the extra Gemini skill target path and the git-commit skill source still requiring the
   observable wrapper.
3. Regenerate the Gemini skill files through `sase init-skills --force --provider gemini`, apply chezmoi, and verify the
   normal and `jetski` Gemini `sase_git_commit` skill copies both invoke `sase_git_commit`.
4. Run focused tests plus the repo-required checks, and run chezmoi checks if the chezmoi repo is modified.
5. Update stale child bead commit-note breadcrumbs if needed, mark the epic plan file `status: done`, then close bead
   `sase-3v`.
