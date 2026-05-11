---
create_time: 2026-05-11 19:09:15
status: done
prompt: sdd/prompts/202605/research_swarm_other_model.md
---
# Plan: Make `research_swarm` xprompt portable across models

## Context

`src/sase/default_xprompts/research_swarm.md` is a default multi-agent xprompt that spawns three sequential research
phases:

```
{{ prompt }} #research        # phase 1: initial research (default model)
---
%w #resume #research/more %m:opus   # phase 2: deeper follow-up research
---
%w #resume #research/image          # phase 3: image-producing follow-up
```

Two problems:

1. Phase 2 hard-codes `opus`. This makes the default xprompt useless for any user who hasn't configured a Claude-family
   `opus` model — and even users who have one may prefer to route "alternate" work somewhere else. The `%m:other` alias
   was introduced precisely for this case: it resolves to whatever the user has configured as their secondary model
   (`%model:other` / `%m:other`, override-aware per `sdd/tales/202605/other_alias_override_aware.md`).
2. Phase 3 inherits the model from the previous segment (or falls back to the default), so the model used for image
   generation is non-deterministic across environments. Image work is the one phase that _does_ need a specific model —
   `gpt-5.5` — because that's the model wired up to produce images in this workspace.

The fix is a two-line edit in one file. There is no API or schema change.

## Goals

- Phase 2 of `research_swarm` uses the user's configured "other" model, not a hard-coded `opus`.
- Phase 3 of `research_swarm` always runs on `gpt-5.5`, explicitly.
- No behavior change for users who already had `opus` configured as their "other" model (they'll keep using opus for
  phase 2).
- No test breakage.

## Non-goals

- Do not touch any other xprompt that references `%m:opus` — only `research_swarm.md` is in scope.
- Do not change the `%m:other` alias resolution, the directive parser, or the workflow tag inheritance logic. All of
  that already exists and is tested.
- No new tests. The change is configuration-data only.

## Change

File: `src/sase/default_xprompts/research_swarm.md`

```
---
input:
  - name: prompt
    type: text
---

{{ prompt }} #research

---

%w #resume #research/more %m:other

---

%w #resume #research/image %m:gpt-5.5
```

Two edits:

- Line 11: `%m:opus` → `%m:other`
- Line 15: append ` %m:gpt-5.5` after `#research/image`

## Test-impact analysis

`tests/test_xprompt_parsing.py:486` contains the literal string `%w #resume #research/more %m:opus`. Read in context,
this test (`test_inherit_vcs_tag_preserves_leading_directives`) is asserting that `inherit_vcs_workflow_tag()` inserts a
`#gh:sase` tag after leading `%` directives on an arbitrary prompt string — the `%m:opus` is illustrative input, not a
reference to the contents of `research_swarm.md`. So the test does **not** need to change.

No other tests grep against `research_swarm.md`'s contents. (Confirmed: a search for `research_swarm` in the test tree
only finds this file referenced for the default-xprompts inventory, never its body.)

## Risk

Very low.

- `%m:other` is a documented, supported alias (see `docs/llms.md` and `src/sase/llm_provider/config.py`). If a user has
  no "other" model configured, the resolution path either falls back to the default model or surfaces a clear error at
  agent-launch time — the same UX users already get from a misconfigured `%m:other` anywhere else. We don't need to
  special-case it here.
- `gpt-5.5` is a recognized bare model name (`src/sase/llm_provider/codex.py:20`,
  `src/sase/xprompts/skills/sase_beads.md:52`). `%m:gpt-5.5` parses through the same directive path as `%m:opus`.
- The xprompt is part of the default-xprompts directory, so any active user of `research_swarm` picks up the new
  behavior the next time they invoke it. That is the desired outcome.

## Verification

1. Apply the two edits above.
2. Run `just check` per `memory/short/build_and_run.md` (in a fresh workspace, also run `just install` first per
   `memory/short/workspaces.md` — this is `sase_104`, which may be stale).
3. Spot-check the file with `cat src/sase/default_xprompts/research_swarm.md` to confirm both directives.

That's it. No code, no tests, no docs changes beyond the data file.
