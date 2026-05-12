---
create_time: 2026-05-12 11:19:20
status: done
prompt: sdd/prompts/202605/live_agent_chat_skill_followups.md
---
# Live Agent Chat Skill Followups

## Context

The older `improve_live_agent_chat_skills.md` plan is mostly implemented in the current source templates:

- `/sase_chats` already falls back from `sase chats show --agent <name>` to content-filtered chat search, then
  `sase agents status -a -j`, then `/sase_agents_status` for live artifact inspection.
- `/sase_agents_status` already documents `artifacts_dir`, `live_reply.md`, workflow checkpoints, `done.json`, workspace
  resolution, submitted plan paths, and the stable-versus-streaming distinction.

The remaining useful recommendations are narrower:

- make the citation requirement for live artifacts explicit, not only transcript paths;
- make review/comparison/selection tasks explicit in `/sase_agents_status`, since that was the observed failure mode;
- add content-oriented tests that preserve the cross-skill contract in generated skill files.

## Plan

1. Update `src/sase/xprompts/skills/sase_chats.md` with one focused clarification:
   - When the fallback chain reaches live artifacts, responses must name the artifact paths read and label whether the
     evidence came from draft/live files or stable/completed files.

2. Update `src/sase/xprompts/skills/sase_agents_status.md` with two focused clarifications:
   - Under artifacts guidance, require citing artifact paths when using live state to answer a user question.
   - Add a short review/comparison guidance note: inspect each relevant active agent's artifacts, distinguish partial
     from final evidence, and avoid treating absence of a completed transcript as absence of useful evidence.

3. Extend `tests/main/test_init_skills_sources.py`:
   - Add expected examples for `sase_agents_status`, which is not currently covered by the shipped-source rendering
     test.
   - Strengthen the `sase_chats` expected examples to include the fallback chain and `/sase_agents_status` handoff.
   - Use phrase-level assertions rather than exact prose matching.

4. Verify:
   - Run `just install` first, per workspace memory.
   - Run the focused init-skills source test.
   - Run `just check` before finishing.

## Out Of Scope

- Do not hand-edit generated installed skill files or memory files.
- Do not run `sase init-skills --force` or `chezmoi apply` unless tests or repo docs show they are required for this
  source-only change. The prior completed work established `src/sase/xprompts/skills/` as the source of truth.
