---
create_time: 2026-04-24 20:42:13
status: done
---
# Codex Config Cleanup Plan

## Goal

Implement the accepted Codex configuration recommendations:

- Make chezmoi's managed Codex config authoritative for the intended trust policy.
- Add Codex's pragmatic personality setting to the managed config.
- Fix the generated git commit skill source so Codex also warns agents to include untracked files when using
  `sase commit -f`.

The user explicitly wants all of `/home/bryan` trusted, so preserve that broad trust entry in the managed config rather
than narrowing it.

## Current State

- Live Codex config at `~/.codex/config.toml` contains:
  - `model = "gpt-5.5"`
  - `model_reasoning_effort = "high"`
  - trusted project entries for `/home/bryan` and several SASE workspaces.
- Managed chezmoi Codex config at `~/.local/share/chezmoi/home/dot_codex/config.toml` only contains the model settings.
  A future `chezmoi apply` would remove the trusted project entries from the live config.
- Codex's deployed `sase_git_commit` skill lacks the untracked-file warning because the shared Jinja source currently
  emits that wording only for Claude.
- Generated skill memory says deployed `SKILL.md` files must not be hand-edited. The source of truth is
  `src/sase/xprompts/skills/sase_git_commit.md`, followed by `sase init-skills --force` and `chezmoi apply`.

## Implementation

1. Update the managed Codex config:
   - Edit `~/.local/share/chezmoi/home/dot_codex/config.toml`.
   - Add `personality = "pragmatic"` next to the existing model settings.
   - Add `[projects."/home/bryan"]` with `trust_level = "trusted"`.
   - Do not duplicate the narrower SASE workspace entries, since `/home/bryan` covers them and the user explicitly wants
     that whole tree trusted.

2. Update the generated git commit skill source:
   - Edit `src/sase/xprompts/skills/sase_git_commit.md`.
   - Remove the Claude-only conditional around the untracked-file warning in step 1.
   - Remove the Claude-only conditional around the `-f` flag wording so every rendered provider gets:
     - `-f` includes modified and newly created untracked files.
     - omitting `-f` stages all changes, including untracked files.
   - Keep the provider-specific "do not mention provider name" wording intact.

3. Regenerate and deploy:
   - Run `sase init-skills --force` from the SASE repo to regenerate managed runtime skills.
   - Run `chezmoi apply` so managed Codex config and regenerated skills reach `~/.codex`.

## Validation

- Inspect `~/.local/share/chezmoi/home/dot_codex/config.toml` and `~/.codex/config.toml` to confirm both include:
  - `personality = "pragmatic"`
  - `/home/bryan` trusted project entry.
- Inspect the managed and live Codex `sase_git_commit/SKILL.md` files to confirm the untracked-file warning appears.
- Check `git status --short` in the SASE repo and chezmoi repo to report exactly what changed.
- Run `just install` if needed, then `just check` in the SASE repo because source files changed there.
- Run `just check` in the chezmoi repo because managed dotfiles changed there.
