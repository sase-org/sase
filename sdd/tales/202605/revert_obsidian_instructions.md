---
create_time: 2026-05-30 16:45:29
status: done
prompt: sdd/prompts/202605/revert_obsidian_instructions.md
---
# Revert Obsidian Sibling Config And Add Vault Agent Instructions

## Goal

Undo the previously committed chezmoi-backed SASE `obsidian` sibling repo configuration, then add repository-local
instructions to `~/bob/AGENTS.md` for agents working inside the Obsidian vault. Commit the `~/bob` instruction change
using `/sase_git_commit` when complete.

## Context

- The previous change is commit `11d6332f feat: add obsidian sibling repo` in `/home/bryan/.local/share/chezmoi`.
- That commit modified:
  - `home/dot_config/sase/sase.yml`
  - `home/memory/short/sase.md`
- Both `/home/bryan/.local/share/chezmoi` and `/home/bryan/bob` are currently clean and aligned with `origin/master`.
- `/home/bryan/bob/AGENTS.md` currently only contains the title `# Bugyi's Obsidian`.
- `~/bob` is actively synced by Obsidian Sync, so future agents must assume the worktree may contain legitimate
  uncommitted changes that should not be overwritten or bundled into unrelated commits.

## Implementation Plan

1. Revert the chezmoi change safely:
   - Use `git revert --no-commit 11d6332f` in `/home/bryan/.local/share/chezmoi` so the revert is inspectable before
     committing.
   - Confirm the resulting diff only removes the `obsidian` sibling repo entry from `sase.yml` and the generated
     short-memory line from `sase.md`.
   - Commit that revert with `/sase_git_commit`, staging only the two reverted files.
   - Re-apply the affected live chezmoi targets so `~/.config/sase/sase.yml` and the live short memory no longer expose
     the reverted sibling repo configuration.

2. Add the `~/bob` agent instructions:
   - Edit `/home/bryan/bob/AGENTS.md`.
   - Add a concise section telling agents that uncommitted changes may already exist because Obsidian Sync actively
     syncs the vault.
   - Instruct agents not to overwrite, revert, stage, or commit unrelated pre-existing changes.
   - Instruct agents to commit any file changes they make under `~/bob` before terminating, using `/sase_git_commit`.

3. Verify both repos:
   - In chezmoi, verify the revert commit completed, the branch is clean and not ahead, and the live config/memory no
     longer contain the `obsidian` sibling entry.
   - In `~/bob`, run `git diff --check`, inspect `git diff -- AGENTS.md`, then commit only `AGENTS.md` with
     `/sase_git_commit`.
   - After the commit, verify `~/bob` is clean and not ahead of its upstream.

## Risks And Mitigations

- Existing or newly synced Obsidian changes could appear while editing `~/bob`. I will check status before committing
  and use `sase_git_commit -f AGENTS.md` so unrelated vault changes are not staged.
- The previous chezmoi commit was already pushed, so I will use a new revert commit instead of rewriting published
  history.
- The repo-wide chezmoi checks previously had unrelated failures, so verification will focus on targeted diff, live
  config, and git state unless a broader check becomes necessary.
