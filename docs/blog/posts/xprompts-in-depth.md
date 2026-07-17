---
title: "[02] XPrompts in Depth — From One File to Full Workflows"
date: 2026-05-12
draft: true
description: >-
  XPrompts up close: when a single Markdown file is the right shape, when typed inputs and directives are enough, and
  when the job really does want a YAML workflow.
categories:
  - Agentic Software Engineering
  - XPrompts
slug: xprompts-in-depth
links:
  - XPrompts: xprompt.md
  - Workflow Specification: workflow_spec.md
  - Getting Started: getting_started.md
  - View on GitHub: https://github.com/sase-org/sase
---

# [02] XPrompts in Depth — From One File to Full Workflows

A single `#tag` is the smallest reusable unit of agent work in SASE. This post is about what's underneath that tag and
when to stop there instead of reaching for a workflow.

<!-- more -->

[Getting Started](../../getting_started.md) shows how to turn a one-off prompt into a reusable `#docstring`. That is the
smallest XPrompt: one Markdown file in `sase/xprompts/`, invoked by name. This post zooms in. We will walk from that
one-file XPrompt up through typed inputs, directives, and multi-agent fan-out, and only at the end show why YAML
workflows exist — because most of the time you do not need one.

## The Smallest XPrompt Is a Markdown File

`sase/xprompts/docstring.md` is the entire definition. Drop the file in the canonical project directory and the prompt
becomes reachable as `#docstring`. Optional YAML frontmatter on top of the file gives it a `name`, a `description`,
typed `input` fields, a `snippet` for editor completion, and a `skill` advertisement. None of those fields are required.

Discovery order is deterministic and project-aware: canonical project files, legacy project fallbacks, canonical home
files, legacy home fallbacks, project-specific home files, config entries, `sase_xprompts` plugin packages, then SASE's
built-in defaults. First match wins. The [full table is in the docs](../../xprompt.md#discovery-order); the practical
implication is that a project-local override always beats a user override which always beats a plugin which always beats
a built-in. That ordering is what lets `crs`, `fix_hook`, and the commit workflows ship as overridable defaults.

## Typed Inputs Add Light Validation

When a prompt needs parameters, declare them in frontmatter and the runner will validate before the agent ever sees the
text:

```markdown
---
name: review
input:
  target: word
  depth:
    type: int
    default: 3
---

Review the {{ target }} module to depth {{ depth }}.
```

Supported types are `word`, `line`, `text`, `path`, `int`, `bool`, and `float`. `word` rejects whitespace, `line`
rejects newlines, `bool` accepts the usual `true/false/yes/no/1/0/on/off` set. A field with no `default` is required;
omitting it raises a template error at expansion time, which is the failure mode you want — bad arguments stop before
the model is invoked, not after.

Inputs are exposed as Jinja2 variables, so the body is a real template: conditionals, filters, and substitution all
work. For most XPrompts you will not need that — but it is there when an argument needs to ripple through five places in
the prompt body.

## Directives Control Execution Without Leaving Markdown

Directives are in-prompt tags with a `%` prefix that modify the agent runner instead of the prompt text. They are
stripped before the prompt reaches the model. The ones worth knowing on day one:

| Directive | What it does                                                                                              |
| --------- | --------------------------------------------------------------------------------------------------------- |
| `%model`  | Override the LLM model for this run                                                                       |
| `%name`   | Assign a permanent agent name (or auto-generate one)                                                      |
| `%wait`   | Wait for another named agent to complete successfully                                                     |
| `#t`      | Defer launch by a duration or until an absolute wall-clock time (`%wait(time=...)` long form)             |
| `%auto`   | Request gate-specific automatic resolution; plan compatibility aliases include `plan`, `tale`, and `epic` |
| `%repeat` | Run the prompt N times                                                                                    |
| `%alt`    | Split the prompt into variants with different text                                                        |

Directives compose. `%wait(planner, time=5m)` waits for the `planner` agent to land, then adds a five-minute floor
before launching. `%name:!reviewer` forces reuse of an existing name by wiping the previous owner from the TUI — useful
when retrying a flow that already claimed the name. The
[full directive reference](../../xprompt.md#supported-directives) lists every directive, alias, and form.

The point is that you can control execution — model, dependencies, autonomy, plan mode — from the same Markdown file
that contains the prompt. There is no second YAML file, no orchestration boilerplate.

## Multi-Agent Fan-Out Without a Workflow

A bare `---` line on its own inside an XPrompt body (outside any fenced code block) is a segment separator. Each segment
becomes its own agent at dispatch time, with the same input arguments threaded through:

```markdown
# sase/xprompts/three_phase.md

---

input: target: word

---

%name:plan Draft a plan for {{ target }}.

---

%name:code %wait:plan Implement {{ target }} following the plan.

---

%name:review %wait:code Review the {{ target }} implementation and propose follow-ups.
```

Run it with `sase run '#three_phase(login)'`. SASE dispatches three agents named `plan`, `code`, and `review`, each
receiving `target=login`. The `%wait` directives chain them sequentially; remove the waits and they run in parallel.

The catalog and TUI picker show fan-out XPrompts with the normal `#` marker because they can be referenced inline while
still expanding into multiple prompt segments at launch. That is most of the time the right answer for "I need three
agents in order" — no YAML, no step graph, just a Markdown file with three sections.

## When Prose Is No Longer Enough: YAML Workflows

YAML workflows exist for control flow that genuinely needs a graph: typed structured outputs, conditional steps,
parallel joins, human-in-the-loop approvals, and steps that are not agent prompts at all. A workflow file (`.yml` /
`.yaml` next to your `.md` XPrompts) declares `steps` with one of these types:

- `prompt_part` — inline prompt fragment, the same shape as a plain `.md` XPrompt.
- `agent` — launch a sub-agent with a rendered prompt.
- `bash` / `python` — run host commands or Python directly.
- `parallel` — fan a list of steps out concurrently and join.

Control flow is `if`, `for`, `while`, and `repeat`/`until`. Loops support `on_error` policies. Parallel steps support
configurable join modes. Steps can pass `artifacts` to later steps. Agent steps can declare an `output:` schema and SASE
will validate the response. A final `done.json` artifact records the completion outcome the rest of the system
(notifications, `%wait` resolution, ChangeSpec stitching) consumes.

The [workflow spec reference](../../workflow_spec.md) covers every field, control flow form, and template feature.

## Don't Reach for Workflows First

Workflows are powerful, and they are also more state and more failure modes than a Markdown file. A YAML graph has
intermediate artifacts, step retries, join semantics, and approval gates that all have to behave correctly under
failure. A single `.md` file with `---` separators and `%wait` directives has none of that.

The rule of thumb that holds up:

- Single prompt, no parameters → plain `.md` XPrompt, end of story.
- Same prompt with arguments → add `input:` frontmatter and Jinja.
- "Run agent A, then B, then C" → `---` segments with `%wait` directives. Still one file.
- Conditional logic, parallel joins, structured outputs, HITL approvals, mixing bash/python steps with agent steps —
  _now_ it is a workflow.

Workflows earn their existence when the graph genuinely needs to branch. If you find yourself writing one because you
want to "be thorough," that is a sign the markdown form was already sufficient.

## The Plugin Path

XPrompts also ship from `sase_xprompts` entry-point packages. That is how `crs`, `fix_hook`, and the commit workflows
become overridable: the built-in `commit.yml` is at priority 17 in the discovery order, a plugin's commit XPrompt is at
priority 15, and a project-local `sase/xprompts/commit.md` wins at priority 1. Disabling resource plugins is a single
env var (`SASE_DISABLE_PLUGINS`, `SASE_DISABLE_PLUGIN_XPROMPTS`) — useful when debugging which copy of an XPrompt is
actually being expanded.

`sase xprompt expand --trace '#myprompt'` prints the full expansion trace to stderr: every resolved reference, its
source file, its arguments. When something resolves to the wrong copy, that is the command that tells you why.

## What To Read Next

- [XPrompts reference](../../xprompt.md) — the full surface: discovery, frontmatter, directives, Jinja, fan-out, plugin
  packaging.
- [Workflow specification](../../workflow_spec.md) — every step type, control flow form, join mode, and template
  feature.
- [\[03\] AXE — The Background Daemon That Keeps Agent Work Moving](axe-background-daemon.md) — what runs your `%wait`
  dependencies and `done.json` completions in the background.
