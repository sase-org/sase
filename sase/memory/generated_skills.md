---
type: long
parent: AGENTS.md
description:
  Read when working with sase agent skills (aka xprompt skills), which are generated from source templates in the
  `src/sase/xprompts/skills/` and deployed to managed locations (my chezmoi repo, for example).
---

# Generated Skill Files

Chezmoi skill files (`SKILL.md`) are **generated**, not hand-edited. The source templates live in
`src/sase/xprompts/skills/` and are rendered per-provider by `sase skill init`.

- Run `sase skill init --force` after changing any skill source file in `src/sase/xprompts/skills/`
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

| Skill              | Claude | Gemini | Codex |
| ------------------ | ------ | ------ | ----- |
| `/sase_git_commit` | Yes    | Yes    | Yes   |
| `/sase_hg_commit`  | No     | Yes    | No    |

Claude and Codex do NOT have the `/sase_hg_commit` skill — it is only relevant for Gemini in this repo. Do not re-add
`/sase_hg_commit` to other core-generated runtimes unless this repo grows first-class Mercurial skill support for them.

## Plan Mode and Questions

- You should use your `/sase_plan` skill for plan mode (`EnterPlanMode` and `ExitPlanMode` have been disabled).
- You should use your `/sase_questions` skill if you need to ask the user clarifying questions (`AskUserQuestion` has
  been disabled).
