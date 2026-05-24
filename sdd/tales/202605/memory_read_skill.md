---
create_time: 2026-05-24 13:14:49
status: done
prompt: sdd/prompts/202605/memory_read_skill.md
---
# Plan: SASE Memory Read Skill

## Goal

Factor the procedural instructions for audited long-term memory reads out of root agent instructions and into a packaged
`/sase_memory_read` skill. The skill should be the canonical agent-facing guide for when and how to run
`sase memory read`, while the root instructions keep only the policy and list of long-term memory files.

## Context

- Shipped skills are generated from `src/sase/xprompts/skills/*.md`, not from deployed `SKILL.md` files.
- The generated-skills memory requires changing the source template, then regenerating provider skills with
  `sase init-skills --force` and applying with `chezmoi apply` when appropriate.
- `AGENTS.md` currently embeds the command syntax, path relativity, and canonical-file warning directly in the Tier 3
  memory section.
- Root memory files must not be modified without approval; this work should not edit `memory/short/*` or
  `memory/long/*`.

## Implementation Approach

1. Add `src/sase/xprompts/skills/sase_memory_read.md` with `skill: true`, concise trigger metadata, and direct
   instructions for:
   - reading long-term memory only through `sase memory read`;
   - using paths relative to `memory/`, such as `long/generated_skills.md`;
   - passing a specific, non-empty `--reason` or `-r`;
   - avoiding direct reads of canonical `memory/long/*.md` files;
   - recognizing that dynamic `.sase/memory/long-*.md` copies already carry the corresponding long-memory content.
2. Update `AGENTS.md` so the Tier 3 section says to use `/sase_memory_read` for audited read procedure details, while
   retaining concrete long-memory file names and their read triggers.
3. Update skill-source coverage so the new bundled skill is explicitly checked by the existing generated-skill source
   test path.
4. Update bundled-skill documentation in `docs/xprompt.md` so the public skill list includes `sase_memory_read`.
5. Regenerate deployed skill files via the SASE skill generator, then inspect what changed. Do not hand-edit generated
   `SKILL.md` files.

## Validation

- Run a focused generated-skill source test for the new skill.
- Run skill initialization in dry-run or force mode as needed to verify rendering.
- Because this changes repository files, run `just install` followed by `just check` unless the final diff is limited to
  documentation-only paths that meet the documented exception criteria.

## Risks

- If `AGENTS.md` no longer contains a plain `memory/long/...` mention, memory inventory reachability could change. Keep
  the concrete long-memory paths in the file list.
- Provider-specific skill generation may touch chezmoi-managed files outside the repo. Inspect generated changes and
  avoid manual edits to deployed skill files.
