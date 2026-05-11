---
create_time: 2026-05-11 17:43:18
status: done
prompt: sdd/prompts/202605/workflow_step_type_emojis.md
---
# Workflow Step Type Emojis in Agent Rows

## Problem

On the `sase ace` "Agents" tab, child workflow step entries (Python, Bash, agent, parallel) are currently distinguished
from each other **only by accent color** on the step-type prefix. Color alone is a weak signal:

- Colorblind users can't rely on it.
- When scanning a long workflow, the eye has to land on a row, decode the hue against the `_STEP_TYPE_COLORS` palette,
  and translate that back to "oh, this is the bash one." That's slower than recognizing a glyph.
- Bash and Python rows in particular look almost identical structurally — both render `step_source` rather than an agent
  prompt — so they benefit most from a glyph that says "shell" or "code" at a glance.

We want a small leading icon on Python and Bash workflow child rows that makes the step type obvious without relying on
color.

## Goal

Add a distinguishing emoji prefix to **Python** and **Bash** workflow step entries in the `AgentList` rendering,
immediately after the existing `└─ ` indent and the `1/3 ` step-number prefix, before the display name.

Out of scope (for this CL):

- Adding emojis to `agent`-typed child steps. Agent rows are already named with a meaningful `display_name` (the prompt
  step name) and often carry an `@agent_name` tag, so they don't need an extra type glyph. Adding one to every child
  would just be noise, since `agent` is by far the most common type.
- Adding emojis to `parallel` and `prompt_part` steps. `parallel` already has the lavender accent + structural fan-out
  children that make it readable; `prompt_part` is a single-line invisible-by-default step. We can revisit if/when
  feedback warrants it.
- Changing the detail panel, prompt panel, or vim syntax. The agent row is the primary scanning surface and the smallest
  change that solves the problem.

## Design

### Glyph choice

| Step type | Emoji | Reasoning                                                                 |
| --------- | ----- | ------------------------------------------------------------------------- |
| `python`  | 🐍    | Universally recognized as "Python" — used by python.org, PyPI, GH icons.  |
| `bash`    | 🐚    | Reads as "shell" (which is what bash is); narrow enough to avoid clutter. |

These two were chosen because they are:

1. Instantly readable at small scale in a terminal font.
2. Distinct from each other in silhouette (curved snake vs spiral shell).
3. Distinct from existing icons in the row palette (`⚡ ◌ ◆ ≡ ❑ ↻ ▲ ▼ │ └─ ▌ ▎ ▸`), all of which are monochrome line
   glyphs — emojis stand out as a different visual category, which is exactly what we want for a "type" hint.

If the user prefers alternates, near-miss candidates are 💻 / ⌨️ for bash and 🧪 / 📜 for python; the implementation is
one constant change away.

### Placement in the row

Current child-row layout:

```
│  │    └─ 1/3 step-name (RUNNING) ...
^^^^^^^^^^^^^^^^^^^
tier      indent + step#
gutter
```

New layout:

```
│  │    └─ 1/3 🐍 step-name (RUNNING) ...
                ^^
              type glyph (only for python/bash)
```

The emoji sits between the step-number prefix and the display name, with a single trailing space. Putting it after the
step number (rather than before) keeps the `1/3` numbering left-aligned with sibling rows that don't get an emoji — so
the eye still tracks step ordering down a workflow without zig-zag.

Color: render the glyph in the same `_STEP_TYPE_COLORS` accent that the row already uses for its color cue. That ties
the glyph to the color so users who learn one learn the other.

### Width and alignment

Emojis are typically 2 cells wide in modern terminals. This shifts the display name 3 cells right (2 for the glyph + 1
for the space) on python/bash rows relative to agent rows. We accept this minor jaggedness — workflow children are
already visually indented and the misalignment is between sibling step types within the same workflow, which actively
reinforces "these are different kinds of steps." If alignment becomes a problem, we can later pad non-emoji rows with
three spaces to match.

### Cache invalidation

`AgentRenderCache` already includes `agent.step_type` in its key (`_agent_list_render_cache.py:142`), so adding glyph
rendering keyed on `step_type` requires no cache changes — flipping a row's type or arriving with a previously unseen
step type produces a cache miss naturally.

## Files Touched

1. `src/sase/ace/tui/widgets/_agent_list_styling.py`
   - Add a new `_STEP_TYPE_GLYPHS: dict[str, str]` mapping with entries `"python": "🐍"` and `"bash": "🐚"`. Leave other
     step types absent (so they get no glyph and the existing rendering is unchanged).

2. `src/sase/ace/tui/widgets/_agent_list_render_agent.py`
   - Import `_STEP_TYPE_GLYPHS` alongside the other styling constants.
   - Inside the existing `if agent.is_workflow_child:` block, immediately after the step-number text is appended (around
     line 93), append the glyph if `agent.step_type in _STEP_TYPE_GLYPHS`, styled with the matching `_STEP_TYPE_COLORS`
     accent and a trailing space.

3. `tests/` — update or add unit tests that exercise the `format_agent_option` path for python/bash children and assert
   the glyph appears (and is absent for agent/parallel/prompt_part children).

4. Visual snapshot suite (`just test` regenerates PNGs that include the agent list). Any agents-tab golden image showing
   a workflow with python/bash children will need to be regenerated and committed.

## Glossary Touches

None. The "Child Agent/Workflow Step Entry" glossary entry in `memory/short/glossary.md` already describes these rows;
the new glyph is a visual aid, not a new concept.

## Risks / Open Questions

- **Font support**: Some minimal terminal fonts (e.g. monochrome Powerline setups) may render 🐍/🐚 as boxes. Most
  modern terminals (kitty, wezterm, ghostty, iTerm, recent gnome-terminal) render color emoji correctly and the fallback
  (a tofu box) is still distinguishable per step type since it sits in a known position. Worth a one-shot eyeball check
  after implementation but not a blocker.
- **User taste on glyph choice**: 🐍 and 🐚 are the obvious picks, but the user said "a good emoji" — if they have a
  strong preference for an alternate set (e.g. ⚙️ / $) we should swap the constants before merging.

## Acceptance Criteria

- A workflow whose children include a python step and a bash step shows `└─ N/M 🐍 …` and `└─ N/M 🐚 …` respectively on
  the Agents tab.
- Agent-typed and parallel-typed children render exactly as they do today (no emoji, no shift in spacing).
- `just check` passes (lint + mypy + tests + coverage gate).
- Visual snapshots regenerated and reviewed.
