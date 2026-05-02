---
create_time: 2026-04-26 03:06:15
status: done
prompt: sdd/prompts/202604/fix_agents_tab_project_banners.md
---
# Fix Agents Tab Project-Scoped Banner Duplication

## Problem

The Agents tab now renders project-scoped agents as duplicated group banners, for example:

```text
▌ home ... 1 agent
  ▎ home ... 1 agent
```

and similarly for `sase`. This makes the tree look broken because the second row is presented as a ChangeSpec-level
bucket even though project-scoped agents are not tied to a ChangeSpec.

## Diagnosis

Recent Agents-tab grouping work split the standard hierarchy into:

1. project
2. ChangeSpec
3. name root

The grouping code currently enables the ChangeSpec level when any agent in the panel has a truthy `cl_name`, and it uses
`Agent.cl_name` directly as the ChangeSpec key.

Project-scoped agents intentionally set `cl_name` to the project name for display and identity purposes. They are
distinguishable via `Agent.is_project_agent`, which checks whether `cl_name == Path(project_file).parent.name`.

The live loader output confirms the failing shape:

- `home` project agent: `cl_name == "home"`, `is_project_agent == True`
- `sase` project agents: `cl_name == "sase"`, `is_project_agent == True`
- current tree: `("home",)` followed by `("home", "home")`; `("sase",)` followed by `("sase", "sase")`

So the root cause is not rendering width, Rich/Textual wrapping, or the detail pane. It is semantic grouping: project
agent display names are being mistaken for real ChangeSpec names.

## Implementation Plan

1. Update standard-mode grouping semantics in `src/sase/ace/tui/models/agent_groups.py`:
   - Treat `Agent.is_project_agent` as "no ChangeSpec" for grouping purposes.
   - Decide whether a panel uses the ChangeSpec level based on at least one non-project agent with a real ChangeSpec.
   - Preserve non-standard `BY_DATE` / `BY_STATUS` behavior, where the ChangeSpec level is already intentionally
     dropped.

2. Keep project-scoped-only panels compact:
   - A panel containing only project-scoped agents should render as project -> optional name-root, not project ->
     duplicate project/ChangeSpec.
   - Existing name-root grouping should still work for project-scoped agents with dotted names.

3. Handle mixed panels conservatively:
   - If a panel contains both real ChangeSpec agents and project-scoped agents, real ChangeSpec agents keep their
     ChangeSpec buckets.
   - Project-scoped agents should fall into the existing synthetic no-ChangeSpec bucket rather than a duplicate
     project-name bucket.

4. Add regression tests:
   - Model-level tests for project-scoped-only panels.
   - Model-level tests for mixed real-ChangeSpec plus project-scoped panels.
   - Widget-level tests that the rendered row shape no longer includes the duplicate banner.

5. Verify:
   - Run the focused grouping/widget tests first.
   - Run `just install` if this workspace environment is stale, then run `just check` as required by the repo memory.
