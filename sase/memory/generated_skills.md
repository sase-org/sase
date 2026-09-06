---
type: reference
parent: AGENTS.md
description:
  Read when working with sase agent skills (aka xprompt skills), which are generated
  from source templates in the `src/sase/xprompts/skills/` and deployed to managed
  locations (my chezmoi repo, for example).
---

# Generated Skill Files

Chezmoi skill files (`SKILL.md`) are **generated**, not hand-edited. The source
templates live in `src/sase/xprompts/skills/` and are rendered per-provider by
`sase skill init`. Newly generated skills teach canonical commands; the
compatibility-only `sase_changespecs` source has been retired, so the next
`sase skill init` from a landed host revision should prune leftover provider copies. Do
not deploy generated skills from an unlanded source revision.

- Do NOT edit the chezmoi skill files directly — changes will be overwritten on the next
  generation

### Commit First, Then Deploy

The chezmoi destination is global and shared by every workspace, so deploying from a
dirty or unmerged tree deploys content that exists in no landed source revision in the
sase repo and reverts whatever another agent deployed. After changing a skill source
file in `src/sase/xprompts/skills/`:

1. Preview while iterating with `sase skill init --diff` or `--dry-run` (read-only; no
   guard applies).
2. Commit the template change to the sase repo and land it on the canonical branch.
3. From that clean, merged tree, run `sase skill init --force`, then `chezmoi apply` if
   it was skipped.

A chezmoi deploy is refused when `src/sase/xprompts/` has uncommitted changes, when
`HEAD` is not an ancestor of the canonical branch, or when the recorded provenance
manifest (`.sase-skills-manifest.json` in the chezmoi source root) names a source commit
different from the one being deployed. These refusals mean the source is not canonical
yet — land it instead of overriding.

`--allow-dirty` (source-integrity guard) and `--force` (manifest provenance guard) are
deliberate escape hatches. Both can revert another agent's deployment; use them only
when you know the destination is stale.

## CLI/Skill Contract Synchronization

Any change to `sase stitch create` CLI arguments must include same-turn updates to:

- In-repo callers/wrappers that invoke the changed arguments
- Generated skill sources and provider `SKILL.md` files that document or demonstrate
  those arguments
- Tests validating both CLI parsing and skill invocation examples

## Commit Skills per Runtime

The commit stop hook dynamically resolves to `/sase_git_commit` or `/sase_hg_commit`
based on the detected VCS provider. However, not every runtime has every skill
installed:

| Skill              | Claude | Gemini | Codex |
| ------------------ | ------ | ------ | ----- |
| `/sase_git_commit` | Yes    | Yes    | Yes   |
| `/sase_hg_commit`  | No     | Yes    | No    |

Claude and Codex do NOT have the `/sase_hg_commit` skill — it is only relevant for
Gemini in this repo. Do not re-add `/sase_hg_commit` to other core-generated runtimes
unless this repo grows first-class Mercurial skill support for them.

## Plan Mode and Questions

- You should use your `/sase_plan` skill for plan mode (`EnterPlanMode` and
  `ExitPlanMode` have been disabled).
- You should use your `/sase_questions` skill if you need to ask the user clarifying
  questions (`AskUserQuestion` has been disabled).
