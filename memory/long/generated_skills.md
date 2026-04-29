---
keywords:
  [
    sase commit,
    SKILL.md,
    init-skills,
    sase_commit,
    sase_git_commit,
    sase_hg_commit,
    commit workflow,
    commit skill,
    xprompt skill,
  ]
---

# Generated Skill Files

Chezmoi skill files (`SKILL.md`) are **generated**, not hand-edited. The source templates live in
`src/sase/xprompts/skills/` and are rendered per-provider by `sase init-skills`.

- Run `sase init-skills --force` after changing any skill source file in `src/sase/xprompts/skills/`
- Then run `chezmoi apply` to deploy the generated files to their live locations
- Do NOT edit the chezmoi skill files directly — changes will be overwritten on the next generation

## CLI/Skill Contract Synchronization

Any change to `sase commit` CLI arguments must include same-turn updates to:

- In-repo callers/wrappers that invoke the changed arguments
- Relevant skill `SKILL.md` files that document or demonstrate those arguments
- Tests validating both CLI parsing and skill invocation examples

## Commit Skills per Runtime

The commit stop hook dynamically resolves to `/sase_git_commit` or `/sase_hg_commit` based on the detected VCS provider.
However, not every runtime has every skill installed:

| Skill              | Claude | Gemini | Codex | Jetski |
| ------------------ | ------ | ------ | ----- | ------ |
| `/sase_git_commit` | Yes    | Yes    | Yes   | Yes    |
| `/sase_hg_commit`  | No     | Yes    | No    | Yes    |

Claude does NOT have the `/sase_hg_commit` skill — it is only relevant for Gemini and Jetski, which run on machines
using the Mercurial VCS provider (sase-google plugin). Do not re-add `/sase_hg_commit` to Claude.

## Plan Mode and Questions

- You should use your `/sase_plan` skill for plan mode (`EnterPlanMode` and `ExitPlanMode` have been disabled).
- You should use your `/sase_questions` skill if you need to ask the user clarifying questions (`AskUserQuestion` has
  been disabled).
