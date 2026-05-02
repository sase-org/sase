---
create_time: 2026-03-25 16:16:08
status: done
prompt: sdd/prompts/202603/chezmoi_commit_skills.md
---

# Plan: Add commit skills to Gemini/Codex and remove hg_commit from Claude

## Context

The chezmoi repo (`~/.local/share/chezmoi/`) manages agent-specific skill configurations under
`home/dot_<agent>/skills/`. Currently:

- **Claude** has both `sase_git_commit` and `sase_hg_commit` skills
- **Gemini** has no commit skills (only `sase_plan`, `sase_questions`, `sase_beads`)
- **Codex** has no commit skills (only `sase_plan`, `sase_questions`, `sase_beads`)

Claude doesn't run on any machines using the Mercurial VCS provider, so `sase_hg_commit` should be removed from Claude.
Gemini does run on such machines, so it needs `sase_hg_commit`. Both Gemini and Codex need `sase_git_commit`.

## Changes

### Phase 1: Add `sase_git_commit` skill for Gemini

- Create `~/.local/share/chezmoi/home/dot_gemini/skills/sase_git_commit/SKILL.md`
- Content: identical to Claude's `sase_git_commit/SKILL.md` (the skill is agent-agnostic — it describes VCS workflow
  steps and the `sase commit` CLI interface, with no Claude-specific references)

### Phase 2: Add `sase_git_commit` skill for Codex

- Create `~/.local/share/chezmoi/home/dot_codex/skills/sase_git_commit/SKILL.md`
- Content: identical to Claude's `sase_git_commit/SKILL.md`

### Phase 3: Add `sase_hg_commit` skill for Gemini

- Create `~/.local/share/chezmoi/home/dot_gemini/skills/sase_hg_commit/SKILL.md`
- Content: identical to Claude's `sase_hg_commit/SKILL.md`

### Phase 4: Remove `sase_hg_commit` skill from Claude

- Delete `~/.local/share/chezmoi/home/dot_claude/skills/sase_hg_commit/SKILL.md`
- Delete the `~/.local/share/chezmoi/home/dot_claude/skills/sase_hg_commit/` directory

### Phase 5: Commit and apply

- Commit changes to the chezmoi repo using `/sase_git_commit`
- Run `chezmoi apply` to deploy the changes
