---
create_time: 2026-06-29 08:46:54
status: done
prompt: sdd/prompts/202606/project_display_name_agent_rows.md
---
# Show `PROJECT_NAME` (not the directory key) on Agent Rows & the Agent Panel

## Problem

When `#gh:actstat` is used (a GitHub project-scoped xprompt workflow), the Agents tab still shows the verbose canonical
directory key `gh_bbugyi200__actstat` instead of the project's logical name `actstat`. The user expects to see `actstat`
everywhere — "we shouldn't ever see `gh_bbugyi200__actstat`".

The recently-landed `PROJECT_NAME` feature already does the hard part correctly:

- The project spec at `~/.sase/projects/gh_bbugyi200__actstat/gh_bbugyi200__actstat.sase` contains
  `PROJECT_NAME: actstat`.
- `Agent.project_display_name` (a display-only field on the agent model) is populated during the Agents-tab load
  pipeline by `_attach_project_display_names()` in `src/sase/ace/tui/actions/agents/_loading_compute.py` (batched, off
  the event loop — one project-records read per refresh), so for these agents `project_display_name == "actstat"`.

So the data is present and cached on every agent row. This is purely a **display-layer gap**: the friendly name was
wired into some surfaces but not the two that the user is actually looking at in the screenshot.

## Root Cause

The `PROJECT_NAME` change wired `project_display_name` into:

- the L0 "by project" grouping banner (`src/sase/ace/tui/models/agent_groups/_keys.py:_project_name`),
- tmux window names (`src/sase/ace/tui/actions/agents/_panel_tmux.py`),
- saved-group project records (`src/sase/ace/tui/actions/agents/_saved_group_records.py`).

But it **missed** the two surfaces that render a project agent's name in the default view:

1. **The agent-list row label.** `src/sase/ace/tui/widgets/_agent_list_render_agent.py` renders `agent.display_name` for
   the row's leading label. The `Agent.display_name` property (`src/sase/ace/tui/models/agent.py`) returns `cl_name` for
   project agents, and for a project agent `cl_name` **is** the directory key (`is_project_agent` is defined as
   `cl_name == <project dir name>`). So the row shows `gh_bbugyi200__actstat`. This is the leak in the screenshot (both
   the top "Running" row and the `#actstat-1` tag group rows).

2. **The right-hand agent panel "Project:" field.** `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py`
   renders `Project: {agent.cl_name}` for project agents (and `Project: {meta_project}` when a workflow step recorded a
   `meta_project`), and `src/sase/ace/tui/widgets/prompt_panel/_workflow_render.py` does the same for the workflow
   header. Both surface the directory key. (Not visible in the screenshot only because the currently-selected agent is a
   `sase` agent, which has no `PROJECT_NAME`.)

## Goal / Target Behavior

For any project whose spec defines a `PROJECT_NAME`, the Agents tab shows the logical name (`actstat`) instead of the
directory key (`gh_bbugyi200__actstat`) in:

- the agent-list row label, and
- the agent detail panel's "Project:" field.

Projects without a `PROJECT_NAME` (e.g. `home`, `sase`) are unchanged — they keep displaying by their directory name.
Nothing about grouping, identity, dedup, storage paths, or launch/canonicalization changes: the directory key remains
the storage identity; only what is _shown_ changes.

This is a `sase`-repo-only, display-layer change. No `sase-core` (Rust) or `sase-github` changes are required — the
`PROJECT_NAME` is already parsed, stored, resolved, and cached onto agents.

## Design

Reuse the already-populated, already-cached `Agent.project_display_name` field. No new disk reads, no per-row lookups —
the field is filled once per refresh by the existing load pipeline, so every fix below is a pure in-memory read.

### Fix 1 — Agent row label (primary, fixes the screenshot)

Make `Agent.display_name` (in `src/sase/ace/tui/models/agent.py`) return the logical project name for project agents.
Insert the substitution **after** the existing top-level-workflow special case and **before** the `cl_name` fallback:

- If the agent is a project agent (`is_project_agent`) and `project_display_name` is set, return `project_display_name`.
- Otherwise behave exactly as today.

Centralizing here (rather than only at the row-render call site) is deliberate and is the cleanest fix because
`display_name` is the single "name to show in list display" property. It also resolves the same directory-key leak for
every other agent display surface that already reads `display_name` (revive/cleanup modals, clipboard copy, mark/kill
notifications, context-member labels, and the `name:` query filter), satisfying the "never see it" requirement without
touching each surface individually.

Why this is safe (no behavior change beyond display):

- **Identity / dedup / option IDs** use `cl_name`, not `display_name` (`Agent.identity`, the row `option_id`), so they
  are untouched.
- **Render cache** (`src/sase/ace/tui/widgets/_agent_list_render_cache.py`) already folds both `display_name` and
  `cl_name` into its key, so a friendly-name change invalidates the cache correctly and identity is still keyed on
  `cl_name`.
- **Grouping**: the L0 project bucket is computed separately (`_keys.py:_project_name`, already friendly-name aware).
  The only grouping consumer of `display_name` is `_grouping_name` (dotted agent-family sub-grouping). For the agents in
  question that path is never reached — they have an `agent_name` (`actstat-1.N`, `09n`), which `_grouping_name`
  consults first. For a project agent with no `agent_name`, a dotless friendly name (the norm for GitHub repos like
  `actstat`) yields the same empty name-root it does today, so sub-grouping is unchanged. (Edge note: a `PROJECT_NAME`
  containing a `.` could create a name-root sub-group for an unnamed project agent; this is an unusual configuration and
  the result is benign, so it is accepted rather than special-cased.)
- **Revived/dismissed agents** intentionally do not persist `project_display_name` in their bundle
  (`src/sase/ace/tui/models/agent_bundle.py` lists it in the skip set), so `display_name` gracefully falls back to
  `cl_name` for those — a cosmetic fallback, never a wrong value.

### Fix 2 — Agent panel "Project:" field

In `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py`, prefer `agent.project_display_name` when rendering
the project label:

- the `is_project_agent` branch (currently prints `agent.cl_name`), and
- the `meta_project` branch (currently prints the raw `meta_project`, which for a project-scoped agent is the directory
  key of that agent's own project).

Apply the same substitution in `src/sase/ace/tui/widgets/prompt_panel/_workflow_render.py`'s `meta_project` branch.

Each becomes "use `project_display_name` if present, else the existing value", a pure in-memory read of the cached field
(the panel renders for a single selected agent, not per row, so there is no performance concern). Optionally factor the
`project_display_name or <fallback>` shim into one tiny helper to keep the three call sites consistent.

### Out of scope

- No changes to `sase-core` (Rust) or `sase-github` — `PROJECT_NAME` is already parsed, stored, and resolved.
- No change to storage identity, path computation, alias/`#gh:` canonicalization, grouping keys, or the `project:` query
  filter (it already substring-matches the directory key, and `actstat` is a substring of `gh_bbugyi200__actstat`).
- No migration of existing projects; behavior for projects without `PROJECT_NAME` is unchanged.

## Tests

Add focused tests in the existing display-rendering suite (`tests/ace/tui/widgets/test_agent_display_list_rendering.py`,
using the `make_agent` / `format_agent_option` / `build_header_text` harness), constructing a project agent so that
`cl_name == <project dir name>` and `project_display_name` is set:

1. **Row label uses the logical name.** A project agent with `cl_name="gh_acme__widgets"`,
   `project_file=".../gh_acme__widgets/gh_acme__widgets.sase"`, `project_display_name="widgets"` →
   `format_agent_option(...)` left text contains `widgets` and **not** `gh_acme__widgets`.
2. **Fallback unchanged.** Same agent with `project_display_name=None` → row still shows `gh_acme__widgets`.
3. **Panel "Project:" field uses the logical name.** `build_header_text` for the project agent shows `Project: widgets`;
   add the analogous case for a `meta_project`-carrying workflow agent.
4. **Grouping is unchanged for a dotless logical name.** Assert the project agent (no `agent_name`,
   `project_display_name="widgets"`) still yields an empty name-root in `agent_groups/_keys.py` (no spurious sub-group),
   confirming Fix 1 does not perturb grouping.

## Validation

Per repo rules for this ephemeral workspace: run `just install` first, then `just check` (lint + mypy + tests, including
the PNG visual snapshot suite). Optionally update a TUI PNG snapshot if one happens to pin a project agent's row,
accepting it with `--sase-update-visual-snapshots` only if the change is the expected directory-key → logical-name swap.

## Risk Summary

- Lowest-risk class of change: display-only, reading an already-cached field; no storage/identity/path impact.
- Worst-case failure mode is cosmetic (a verbose name shows where the field wasn't populated, e.g. a revived agent),
  matching the design philosophy of the original `PROJECT_NAME` work.
