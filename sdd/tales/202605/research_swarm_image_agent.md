---
create_time: 2026-05-28 16:34:37
status: done
---
# Plan: Add an infographic agent to `research_swarm`

## Context

`src/sase/default_xprompts/research_swarm.md` is now a built-in multi-agent Markdown xprompt with three named agents:

- `research_swarm.cdx-@` runs independent research on `codex/gpt-5.5`.
- `research_swarm.cld-@` runs independent research on `claude/opus`.
- `research_swarm.final-@` waits for both research agents, reads their chat transcripts and research markdown files,
  consolidates the findings into one final `sdd/research/` markdown file, and deletes the two intermediate files.

`src/sase/default_xprompts/old_research_swarm.md` preserves the legacy workflow. Its final agent is:

```text
%w %g:research #fork #research/image %m:gpt-5.5
```

That legacy segment waits for the previous agent, forks its context, invokes the `#research/image` helper, and routes
the agent to `gpt-5.5`, the image-capable GPT model used by this workspace.

## Design

Add a fourth agent to the new `research_swarm` after the consolidator:

- Name it `research_swarm.image-@` to match the reusable suffix style already used by the new workflow.
- Make it wait on `research_swarm.final-@` so it only starts after the final consolidated research file exists.
- Fork `research_swarm.final-@` so `#research/image` can refer to the final research markdown file identified in the
  consolidator's context.
- Keep `%g:research` so all four swarm agents remain grouped together.
- Explicitly use `gpt-5.5` for the image step, matching `old_research_swarm`'s final image agent.

The resulting fourth segment should have this shape:

```text
%name:research_swarm.image-@ %wait:research_swarm.final-@ %g:research #fork:research_swarm.final-@ #research/image %m:gpt-5.5
```

This keeps the new workflow's explicit dependency model while preserving the legacy image-agent semantics.

## Implementation

1. Update `src/sase/default_xprompts/research_swarm.md`.
   - Change the description from "two independent research agents and consolidate" to mention the generated infographic.
   - Add the fourth `---` segment after the final consolidator instructions.
   - Use the explicit named-agent/wait/fork/model line described above.

2. Update documentation in `docs/xprompt.md`.
   - Change the `#!research_swarm` built-in xprompt summary to say it fans out two research agents, consolidates their
     outputs, then generates an infographic.
   - Leave `#!old_research_swarm` documented as the legacy initial/follow-up/image workflow.

3. Update focused tests in `tests/test_xprompt_loader_config.py`.
   - Keep existing assertions that `research_swarm` and `old_research_swarm` load from `default_xprompts`.
   - Add assertions for `research_swarm.image-@`, its wait on `research_swarm.final-@`, `#fork:research_swarm.final-@`,
     `#research/image`, and `%m:gpt-5.5`.
   - This is sufficient because the change is to packaged prompt content, not parser or launcher behavior.

## Verification

1. Run `just install` first if the workspace environment is stale.
2. Run the focused loader test:

```bash
python -m pytest tests/test_xprompt_loader_config.py -k research_swarm
```

3. Run `just check` because repo memory requires it after file changes.
4. Optionally inspect expansion with:

```bash
sase xprompt expand '#!research_swarm:: example topic'
```

If the optional expansion command is not the correct CLI form for standalone multi-agent xprompts, skip it rather than
expanding the scope into CLI behavior.
