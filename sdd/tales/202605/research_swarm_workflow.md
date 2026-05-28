---
create_time: 2026-05-28 16:03:15
status: done
prompt: sdd/prompts/202605/research_swarm_workflow.md
---
# Plan: Improve the `research_swarm` xprompt workflow

## Context

`research_swarm` is a built-in markdown xprompt at `src/sase/default_xprompts/research_swarm.md`. It currently expands
to three sequential prompt segments:

- an initial research agent that writes a new `sdd/research/` markdown file via `#research`;
- a follow-up agent that waits/forks from the first and improves that same research via `#research/more`;
- an image agent that waits/forks from the previous context and creates an infographic via `#research/image`.

The requested replacement should instead fan out two independent research agents, then run a third consolidation agent
that waits for both, reads their transcripts/research outputs, deletes the two intermediate research markdown files, and
writes one consolidated research file.

## Implementation

1. Preserve the current workflow under the new built-in xprompt name `old_research_swarm`.
   - Add `src/sase/default_xprompts/old_research_swarm.md` with the current `research_swarm.md` content.
   - Give it a description that makes clear it is the legacy initial/follow-up/image workflow.

2. Replace `src/sase/default_xprompts/research_swarm.md` with the new three-agent workflow.
   - Keep the same `prompt` input contract so existing `#research_swarm:: ...` calls continue to work.
   - Use explicit agent names with the reusable suffix syntax from `xprompts/reads.md`, for example:
     `research_swarm.cdx-@`, `research_swarm.cld-@`, and `research_swarm.final-@`.
   - First research segment:
     - `%name:research_swarm.cdx-@`
     - `%model:codex/gpt-5.5`
     - `%g:research`
     - prompt shaped like the current first segment: `{{ prompt }} #research`.
   - Second research segment:
     - `%name:research_swarm.cld-@`
     - `%model:claude/opus`
     - `%g:research`
     - same research task shape as the first segment, so it creates its own independent research file.
   - Final consolidation segment:
     - `%name:research_swarm.final-@`
     - `%wait:research_swarm.cdx-@`
     - `%wait:research_swarm.cld-@`
     - `%g:research`
     - include `{{ wait_chats }}` using the raw-Jinja escape pattern from `xprompts/reads.md`;
     - instruct the agent to read the two prior transcripts, identify and read the two created `sdd/research/` markdown
       files, verify the work, consolidate and improve it without unnecessary length growth, delete those two
       intermediate markdown files, and create one new consolidated `sdd/research/` markdown file.

3. Update documentation for built-in xprompts.
   - Change the `#!research_swarm` summary in `docs/xprompt.md` from the old follow-up/image behavior to the new
     two-researcher-plus-consolidator behavior.
   - Add `#!old_research_swarm` as the legacy initial/follow-up/image workflow so the rename is discoverable.

4. Update focused tests.
   - Extend the default-file loader test to assert both `research_swarm` and `old_research_swarm` load as built-ins.
   - Update the existing `research_swarm` content assertion to look for the new named-agent/model/wait structure.
   - Add or adjust assertions so the legacy content is still covered under `old_research_swarm`.

5. Verify.
   - Run a focused test for xprompt loading, e.g. `just install` if needed, then
     `python -m pytest tests/test_xprompt_loader_config.py -k research_swarm`.
   - Run `just check` because this repo's short memory requires it after file changes, unless the check is blocked by
     environment setup.
   - Optionally spot-check expansion with `sase xprompt expand '#research_swarm:: example topic'` or equivalent if the
     local CLI is available.
