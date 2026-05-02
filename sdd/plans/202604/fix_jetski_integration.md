---
create_time: 2026-04-24 18:57:04
status: done
prompt: sdd/prompts/202604/fix_jetski_integration.md
---
# Plan: Fix Jetski Integration for `sase_hg_commit`

## Problem Analysis

The user reported that the `jetski-default` agent had no response when tasked with a commit in an `hg` (Mercurial)
workspace. Based on the `sase ace` snapshot, the prompt included `#commit %model:#jet`. When the `#commit` workflow runs
in an `hg` workspace, the post-completion hook instructs the agent to use the `/sase_hg_commit` skill. However, if we
look at `src/sase/xprompts/skills/sase_hg_commit.md`, its frontmatter restricts deployment: `skill: [gemini]`. Because
`jetski` is an independent provider registered via the `sase-google` plugin (and is not an alias for `gemini`),
`sase init-skills` does not generate the `/sase_hg_commit` skill file for the `jetski` provider. Consequently, when the
Jetski agent is instructed to use `/sase_hg_commit`, it fails silently or errors out because the skill cannot be loaded
or activated.

## Proposed Solution

1. **Update `sase_hg_commit.md`**: Modify the YAML frontmatter in `src/sase/xprompts/skills/sase_hg_commit.md` to
   include `jetski` in the list of targeted skills.
   - Change `skill: [gemini]` to `skill: [gemini, jetski]`.
2. **Update `generated_skills.md`**: Update the reference documentation in `memory/long/generated_skills.md` to
   explicitly list `Jetski` as supporting both commit skills.
3. **Verify with `just check`**: After making the changes, run `just check` to ensure there are no linting or formatting
   errors in the workspace.
4. **Conclusion**: The user will then be able to run `sase init-skills` (or let the CI/CD pipeline handle it) to
   regenerate the missing skill for Jetski, resolving the silent failure.
