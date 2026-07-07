---
create_time: 2026-07-06 22:40:55
status: done
prompt: sdd/prompts/202607/sase_run_skill_prompt_guidance.md
---
# Plan: Teach the /sase_run skill to compose better launch prompts

## Context

The `/sase_run` skill (source: `src/sase/xprompts/skills/sase_run.md`) tells agents how to request a SASE agent launch
through `LaunchApproval` (`sase launch request`). Today it covers the request mechanics, family-member naming, and
outcome handling — but says nothing about how to _compose_ the requested prompt. Agents therefore don't deliberate
about:

1. **The wait directive** (`%w`/`%wait`) — whether the new agent should park until another agent lands successfully.
2. **The VCS workspace xprompt** (`#gh:`/`#git:`/`#hg:`/`#cd:`) — where the new agent runs, and whether the ref should
   be a project name or (occasionally) a ChangeSpec name.
3. **xprompts in general** — that the requested prompt is a full sase prompt where `#` references expand templates and
   multi-step workflows.

Goal: add concise guidance for these three concerns to the skill. Token budget matters — the skill is injected into
every agent that uses it, so include only decision-relevant facts, no reference-manual material.

## Key facts the guidance must encode (verified against the codebase)

- Prompts with no VCS workspace reference are normalized to `#git:home` (`DEFAULT_VCS_WORKFLOW_PREFIX` in
  `src/sase/xprompt/_parsing_vcs_tags.py`) — almost always wrong for repo work.
- The workspace ref is usually a project name (`#gh:sase`); a ChangeSpec name (`#gh:my_change`) checks out that existing
  CL/PR branch; `#gh:@agent` resolves at runtime to the named agent's ChangeSpec (docs/xprompt.md, "VCS Workspace
  References").
- Family-attach launches (`%n(parent, suffix)`) inherit the parent's workspace and ChangeSpec
  (`src/sase/agent/family_attach.py`), so they must NOT get a workspace reference.
- `%w(<agent>)` parks the launch until the named agent completes **successfully**; failed/killed/still-running runs do
  not satisfy it (docs/axe.md). Wait launches keep workspace number 0 and only resolve a real workspace after the
  dependency lands (docs/workspace.md) — so the new agent sees the awaited agent's landed changes.
- `%w(time=<dur>)` defers by time; args compose: `%w(planner, time=5m)`. The requesting agent's own name is available in
  `$SASE_AGENT_NAME`.
- Rollover xprompts `#commit` / `#propose` / `#pr(<name>)` decide how the launched agent's changes land
  (docs/commit_workflows.md).
- `sase xprompt list` enumerates available xprompts/workflows; `sase xprompt expand '<prompt>'` previews expansion.

## File changes

### 1. `src/sase/xprompts/skills/sase_run.md`

Insert a new `## Compose The Requested Prompt` section between the existing `## Request A Launch` and
`## Family Members` sections. Keep all existing content unchanged (the init-skills test asserts phrases from it).
Proposed text (implementer may tighten wording but should keep all bullets and the section/heading structure):

```markdown
## Compose The Requested Prompt

The requested prompt is a full sase prompt: `%` directives and `#` xprompt references all work. Before submitting, think
hard about the workspace and wait choices below — they determine where the agent runs and which changes it sees.

### VCS Workspace xprompt

Standalone (non-family) prompts should normally start with a VCS workspace reference:

- `#gh:<ref>` (GitHub), `#git:<ref>` (bare git), `#hg:<ref>` (Mercurial), or `#cd:<path>` (plain directory, no VCS
  workspace management).
- `<ref>` is usually a project name (`#gh:sase`). Use a ChangeSpec name (`#gh:my_change`) only when the agent must
  continue that existing CL/PR branch, or `#gh:@agent` to target the ChangeSpec created by the named agent.
- A prompt with no workspace reference defaults to `#git:home`, which is usually wrong for repo work.
- Family-attach launches (`%n(parent, suffix)`) inherit the parent's workspace and ChangeSpec; do not add a workspace
  reference to them.

### Wait Directive

`%w(<agent>)` parks the launch until the named agent completes successfully. The workspace is checked out only after the
wait resolves, so the new agent sees the awaited agent's landed changes. Think hard about whether you need it:

- Wait on your own agent name (from `$SASE_AGENT_NAME`) when the new agent must build on changes this run has not landed
  yet; wait on another agent's name when it depends on that agent instead.
- Omit `%w` when the work is independent, so the agent starts immediately.
- Failed or killed runs never satisfy `%w`; the launch stays parked until a successful run of that name exists.
- `%w(time=10m)` defers by time instead; arguments compose: `%w(planner, time=5m)`.

### Other xprompts

`#name` / `#name(args)` references expand reusable templates and multi-step workflows: they can inject prompt text, run
python/bash steps, set environment variables, and split work across multiple agents. Rollover workflows `#commit`,
`#propose`, and `#pr(<name>)` control how the launched agent's changes land. Discover what is available with
`sase xprompt list`; preview a prompt's expansion with `sase xprompt expand '<prompt>'`.
```

Deliberately excluded to save tokens: directive reference tables, `#t:<time>` long form, `#!` standalone-workflow syntax
details, project activation/alias mechanics, and rollover finalizer internals.

### 2. `tests/main/test_init_skills_sources.py`

Extend the `sase_run` entry's `expected_phrases` tuple with stable anchors from the new section so the guidance cannot
silently regress, e.g.:

- `"#git:home"`
- `"%w("`
- `"sase xprompt list"`

### 3. Regenerate and deploy the generated skill files

Per the `generated_skills` long-term memory, chezmoi `SKILL.md` files are generated — never hand-edit them:

1. `sase skill init --force` (re-render per-provider skill files from the updated source)
2. `chezmoi apply` (deploy generated files to their live locations)

## Verification

1. `just install` (fresh ephemeral workspace), then `just check`.
2. Targeted test: `pytest tests/main/test_init_skills_sources.py`.
3. Sanity-check one rendered provider `SKILL.md` (e.g. the Claude one under the chezmoi source dir) to confirm the new
   section renders and existing sections are intact.

## Out of scope

- No changes to launch-request mechanics, directive parsing, or xprompt workflows themselves.
- No changes to other skill sources.
- No doc-site changes (docs/xprompt.md etc. already document these features).
