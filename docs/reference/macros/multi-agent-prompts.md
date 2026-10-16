---
title: Multi-agent prompts and workflows
description: Prompt segments, output variables, macro swarms, and workflows.
---

# Multi-agent prompts and workflows

This page documents prompt segments, output variables, macro swarms, and their relationship to workflows.

## Multi-Agent Prompts

A single prompt can launch multiple agents by using YAML frontmatter and `---` segment
separators. SASE plans the segments in document order, but agents do not wait for
earlier segments unless you add a dependency such as `%wait:<name>` or bare `%wait`. The
same `---`-separator convention also applies inside a macro body -- see
[Macro Swarms (Library-Defined Fan-Out)](#macro-swarms-library-defined-fan-out) below.

Within one multi-agent launch, bare `%wait` / `%w` in any segment after the first means
"wait for the previous launched segment." Empty or whitespace-only parentheses
(`%wait()`, `%wait( )`) count as bare, including when the wait is introduced by macro
expansion. If the previous segment fans out, the dependency targets that segment's last
launched child; siblings in the current segment all inherit the same previous-segment
dependency. Explicit waits such as `%wait:agent`, bead/time waits, `%queue`, and waits
inside fenced code or disabled macro regions keep their normal meanings. If the
predecessor name is not known yet, SASE records the predecessor artifact identity and
waits on that agent or session completion instead of resolving bare `%wait` against the
global latest agent.

### Frontmatter Panel (sase's TUI)

In the `sase tui` prompt input, ad hoc prompt frontmatter has a structured **Frontmatter
Panel** above the prompt stack, with the same field set a macro `.md` file supports
(`name`, `description`, `tags`, `input`, `macros`, `skill`, `snippet`). Open or focus it
with the prompt NORMAL-mode `g=` keymap; in the panel's rows mode, `g=` runs the
deactivate/apply path. `q` or `Esc` in rows mode—or from NORMAL mode inside any panel
sub-editor—returns focus to the prompt pane you entered from; an invalid raw-YAML buffer
remains open so it cannot be discarded accidentally. In rows mode, `gj` jumps directly
to the top prompt pane and `gk` to the bottom pane. The panel also auto-shows when
sase's TUI has lifted leading frontmatter into the stack, such as a multi-agent prompt
load or an editor-file return from a ` @` review marker / whole-stack `Ctrl+G`. A single
prompt recalled from history with leading frontmatter but no segment separator stays one
verbatim pane instead of auto-opening the panel. Typing `---` in the prompt body is
passive during live editing: at the very start it stays literal text, and after content
it does not split the active pane. Add a top-level property with `a` (an inline picker
sourced from the same core schema that backs the editor LSP), edit scalar/list fields
inline, delete a field with `d`, undo the latest mutation with `u`, and use `R` for a
live-validated raw-YAML escape hatch. In raw mode, `Ctrl+C` explicitly discards an
unparseable buffer. Unknown frontmatter keys remain visible as raw-only rows and survive
structured round trips.

The structured `input` and `macros` fields render as foldable sub-trees (`h`/`l`):
navigate into them with `j`/`k`, use `o`/`A` to insert a ghost row, `e`/`enter` to edit
an item in place, `d` to delete, and `J`/`K` to reorder. Cell editing uses
`Tab`/`Shift+Tab`; `Enter` commits while remaining in the panel. Input types cycle
through the core type catalog and defaults are live-coerced. Local-helper content uses a
bounded multiline editor in the panel. A `#_helper` declared here lights up
`<ctrl+t>`/`<ctrl+l>` completion and argument hints in every prompt pane exactly like a
global macro — define a helper in the panel and it is instantly usable below.

sase's TUI can also author existing definitions without `$EDITOR`. In the Macro Browser,
`Enter` loads a simple Markdown or config-backed definition as raw body plus structured
frontmatter; `E` keeps the external-editor path, and YAML workflow graphs remain
editor-only. A loaded definition is bound to its source: the prompt title shows the
source and a dirty dot, `gw` writes it atomically, and an external-change conflict
offers overwrite, reload, or save-as. `gd` on a `#name` reference loads that definition
after stashing the current draft. `gX` is a one-screen save-as view with name, location,
resolved path, and a live collision/overwrite preview.

### Frontmatter-Defined Local Macros

YAML frontmatter at the start of a prompt can define local macros under the `macros:`
key. These are defined once in the frontmatter and each segment receives only the local
macros it actually references (including transitive dependencies). Local macro names
**must** start with `_` to distinguish them from global macros.

```
---
macros:
  _review_rules: "Always check for error handling and edge cases."
---
#_review_rules
Review the authentication module.
```

Local macros support the same structured format as config-based macros (typed inputs,
Jinja2 content):

```
---
macros:
  _template:
    input: { target: word }
    content: "Review the {{ target }} module."
---
#_template(auth)
```

### Frontmatter-Declared Inputs

Prompt frontmatter can also declare `input:` arguments using the same typed shorthand as
macro files (see [Typed Inputs](arguments.md#typed-inputs)). The declared values are substituted
into every segment's `{{ name }}` placeholders before the agents fan out:

```
---
input:
  service: word
  retries: { type: int, description: how many times to retry }
  dry_run: { type: bool, default: false }
---
Refactor the {{ service }} module ({{ retries }} retries, dry_run={{ dry_run }}).
```

When a prompt with required (default-less) inputs or live raw placeholders is submitted
in `sase tui`, the **Fill in this prompt** panel opens after the whole-stack submit.
Raw-placeholder fields appear first, followed by typed, live-validated required inputs;
optional inputs stay collapsed behind a reveal toggle and show their defaults when
opened. `Enter` advances through visible fields and launches from the last one once
every required value is valid. `Ctrl+L` keeps the focused raw placeholder literal.
`Escape` cancels and returns to the draft; from field INSERT mode, the first press
returns to NORMAL and the second cancels. `path` fields reuse `Ctrl+T` path completion.
See [Raw Prompt Placeholders](templating.md#raw-prompt-placeholders) for matching, substitution, and
the collection toggle.

Non-interactive CLI launches (`sase run`) cannot prompt, so a required input without a
default fails fast with a clear message instead of a cryptic template error — give such
inputs a default or launch from the TUI.

### Segment Separators

After the frontmatter block is consumed, subsequent `---` lines on their own act as
segment separators. Each segment launches as a separate agent:

```
---
macros:
  _common: "Follow the project coding conventions."
---
%id:step1
#_common
Implement the new feature.
---
%id:step2
%wait:step1
#_common
Write tests for the new feature.
```

This launches two agents. `step2` starts after `step1` succeeds because the second
segment includes `%wait:step1`; if that line were omitted, both agents would be eligible
to run independently. Both agents share the `_common` local macro.

### Cross-Agent Output Variables

Agents can publish small JSON-shaped values for later waited agents or segments with
`sase var set`. Values may be strings, numbers, booleans, null, lists, or maps nested
within the documented reliability limits. Give the producer a stable name and make the
consumer wait before referencing the producer's variables. Every producer's variables
live under a single reserved `agents` dictionary keyed by agent name:

```
%id:build-@
Build the report, then run:
sase var set report_path=dist/report.md status=ok
---
%id:review
%wait:build-@
Review {{ agents["build"].report_path }} after the build status is {{ agents["build"].status }}.
```

Use a heredoc through `--value-file -` for a multi-line value:

```bash
sase var set summary --value-file - <<'EOF'
Tests passed.

The release artifact is ready for review.
EOF
```

Add `-j` / `--json` to any input form to decode a structured value. Structured values
remain real containers in Jinja, so consumers can access and iterate them directly:

```
%id:build-@
Run the build, then publish:
sase var set report --json --value '{"passed":true,"suites":["unit","integration"]}'
---
%id:review
%wait:build-@
Build passed: {{ agents["build"].report.passed }}
{% for suite in agents["build"].report.suites %}
- Review the {{ suite }} results.
{% endfor %}
```

Rendering a whole container with `{{ agents["build"].report }}` produces compact JSON
instead of a Python representation. Jinja's `| tojson` filter remains available for
explicit formatting. Map keys are sorted for stable storage and display, while list
order is preserved. Run `sase var get` to inspect the current agent's canonical block
display or `sase var get --format json` for compact JSON. Quote a wrapped name such as
`sase var get '<build>' --format json` for another agent's newest snapshot;
`sase var get build.*` remains selector mode.

The review prompt is rendered after the `build-@` dependency completes, so
`{{ agents["build"].report_path }}` and `{{ agents["build"].status }}` come from the
producer's stored `agent_meta.json` values. A consumer that has already started will not
see later writes.

The `agents` key is a stable Jinja namespace for the producer, not always the producer's
concrete runtime name. Agent-name templates use the template base, so a producer that
launches as `build-0` from `%id:build-@` is read as `{{ agents["build"].report_path }}`,
not `agents["build-0"]`. The key is otherwise the raw agent name with no identifier
munging, so dotted, hyphenated, and digit-leading names all work via bracket access:
`%id:research.@.final` → `{{ agents["research.final"].report_path }}`, and `%id:0n.cld`
→ `{{ agents["0n.cld"].report_path }}`. Identifier-safe keys also support attribute
access such as `{{ agents.build.report_path }}`. `agents` is a reserved agent-run Jinja
name; a workflow input named `agents` collides and fails clearly. Output variables are
persisted in the producer's `agent_meta.json` and also appear in sase's TUI Agents-tab
`OUTPUT VARIABLES` metadata section and Telegram agent-completion messages. They are
visible metadata, not secret storage.

`STOP` is a reserved output-variable name, but only for `%repeat` / `%r` chain
continuation: setting it stops later repeat slots (see
[Stopping a repeat chain early with `STOP`](directive-composition.md#stopping-a-repeat-chain-early-with-stop)).
It has no special meaning for ordinary `%wait` consumers, `---` segments, or `%alt`
fan-outs — those read it like any other variable, e.g. `{{ agents["name"].STOP }}`.

A planner that submits a plan for review (`sase plan propose`) exposes the proposed plan
path as a synthesized `plan_file` variable in the same `agents` namespace, without any
`sase var set` call. A later segment in the same multi-agent prompt reads it under the
producer's stable key, and an explicit `%wait` on the planner row reads it under the
canonical `<base>--plan` key:

```
%id:planner
Propose a plan for the feature.
---
%id:coder
%wait:planner--plan
Implement the plan at {{ agents["planner--plan"].plan_file }}.
```

`plan_file` is only ever namespaced under `agents[...]`; there is no top-level
`plan_file` variable. An explicit `sase var set plan_file=...` in the planner wins over
the synthesized value, and any other output variables the planner sets are preserved
alongside it.

`sase artifact create` exposes a SASE-managed `artifacts` list in the same `agents`
namespace, without any `sase var set` call. A research-swarm researcher registers its
report with `sase artifact create`, and a later `%wait` consumer renders it as
`{{ agents["research.final"].artifacts[0].ref }}` or loops
`{% for a in agents["research.final"].artifacts %}{{ a.label }}{% endfor %}`. Entries
share field names (`ref`, `label`, `kind`, `path`, `source_path`) with `wait.artifacts`.
Every waited target with a known epic also synthesizes `created_epic` (the first epic it
launched) and `created_epics` (every epic it launched) under the same `agents[...]` key.
Values come from the waiter's FOLLOWING entry when the wait is following that target,
else from the target's own `created_epics` record — so a `for_epic=false` consumer still
gets the ID. An explicit `sase var set` of either name wins over the synthesized value.

sase's TUI renders loaded literal `---` multi-agent prompts as a prompt stack: each
top-level segment becomes an editable pane, while prompt-level frontmatter and
fenced-code separators keep the same parsing rules described below. A `#name` macro
swarm invocation remains a single pane until launch. During live editing, typed `---`
lines are ordinary prompt text; add panes explicitly from the prompt-stack controls.
Stash restore and marked-agent kill-and-edit can also seed multiple panes, but those
paths preserve each selected draft or agent prompt as one pane. By default, use `Enter`
to open the submission panel and press `Enter` again to confirm its primary launch
action; use `g<enter>` or `Ctrl+G Enter` to launch the selected pane directly, or
`Ctrl+S` to stash the active pane. Inside the `Enter` submit chooser, `a` or `Ctrl+S`
submits all panes top-to-bottom. Set `ace.prompt_submission.confirm_on_enter: false` to
make plain `Enter` submit the active pane immediately, including in a stack. See the
[sase's TUI prompt-stack guide](../tui/prompt-stacks.md#prompt-stacks-1) for the editing keybindings and
the default active-pane behavior.

### Rules

- The first `---` pair at the start of the document is treated as YAML frontmatter.
- After frontmatter is consumed, all subsequent `---` lines are segment separators.
- If there is no frontmatter, ALL `---` lines are segment separators.
- A prompt with frontmatter but only one segment is a single-agent prompt with local
  macros (not multi-agent).
- `---` inside fenced code blocks is not treated as a separator.
- When a multi-agent prompt a user submitted is saved to prompt history, each individual
  segment is also saved as a separate entry. This allows segments to appear
  independently in the prompt history picker for reuse. Segment recording applies only
  to user-submitted multi-prompts: machine-originated launches write no history rows at
  all.

### Macro Swarms (Library-Defined Fan-Out)

A macro itself can be a macro swarm: its body contains `---` separators (outside fenced
blocks), and referencing it as the sole content of a user-prompt segment fans the call
out into one agent per body segment. The spawned agents share the same input arguments
-- each segment is rendered with the same `(args)` substituted in. The catalog, TUI
picker, and completion UI display markdown-defined macro swarms with the inline marker
(`#name`). The older `#!name` form is still recognized for macro swarms for
compatibility, but new prompts should use `#name`.

```
# sase/macros/three_phase.md
---
input:
  target: word
---
%id:plan
Draft a plan for {{ target }}.
---
%id:code
%wait:plan
Implement {{ target }} following the plan.
---
%id:review
%wait:code
Review the {{ target }} implementation and propose follow-ups.
```

Invoking it:

```bash
sase run '#three_phase(login)'
```

...dispatches three agents (`plan`, `code`, `review`), each receiving `target=login`.
The `%wait` directives chain them sequentially; without `%wait` they would run in
parallel.

For swarm-owned generated hoods, use keyed agent-name markers so every segment and prose
reference resolves in the parent launch before any agent starts:

```text
%id:research.{@1}.cdx
Audit with Codex. Write your report path for `research.{@1}.cdx`.
---
%id:research.{@1}.cld
Audit with Claude. Write your report path for `research.{@1}.cld`.
---
%id(final, clan=research.{@1})
%wait:research.{@1}.cdx,research.{@1}.cld
Summarize both reports.
```

During swarm expansion, each unqualified `{@1}` is rewritten to an invocation-specific
qualified key before dispatch, so overlapping launches of the same macro cannot steal
each other's clan or hood. Use `{@shared!}` only when a nested swarm should
intentionally share a key with its caller. See [Directives](directive-syntax.md#directives) for the
complete keyed-marker grammar and dispatch-scoping rules.

Detection happens at dispatch time (after standard `parse_multi_prompt`), in
`src/sase/agent/macro_swarm.py`, and applies at every dispatch site (`sase run`, the TUI
agent launcher, the query handler).

Macro swarms can also be embedded inside a larger prompt. In that case, the first
rendered body segment is embedded at the reference location and the remaining rendered
body segments become follow-up agent prompts:

```bash
sase run '+sase Review this first: #three_phase(login)'
```

When the call site starts with a workspace reference such as `+sase`, `#gh:sase`,
`#git:feature`, a plugin-provided ref, or a known-project underscore form such as
`#gh_sase`, that workspace reference is inherited by every generated follow-up segment
unless the generated segment already declares its own VCS reference. Leading launch
directives stay before the inherited workspace reference, so a prompt like
`%id:abq +sase #three_phase(login)` keeps `%id:abq` attached to the first generated
segment and prefixes `+sase` onto follow-ups.

#### Rules and Limitations

- A sole macro swarm reference replaces the whole segment with its generated segments.
  An embedded macro swarm reference replaces only that reference with the first
  generated segment, then appends the remaining generated segments as follow-ups.
- A user-prompt segment can contain multiple macro swarm references. They expand fully
  in document order. Text before the first reference attaches to the first generated
  segment only; text between references and after the last reference is discarded.
- Ordinary inline macro references inside a macro swarm body remain inline macro
  references; the agent runner expands them later as normal prompt text.
- `---` inside fenced code blocks in the macro body is not treated as a separator.
- Recursive fan-out (a macro swarm body whose own segments reference more macro swarms)
  is bounded by a depth cap and will raise if exceeded.

## Relationship to Workflows

Macros and [workflows](../workflows.md) share the same argument grammar, but the marker
communicates how the reference is allowed to participate in a prompt:

- `#name(args)` expands inline-capable macros and workflows with a `prompt_part` step,
  including markdown-defined macro swarms that fan out into multiple prompt segments.
- `#!name(args)` launches standalone YAML workflows that have no `prompt_part` step.

Simple markdown macros are converted internally to single-step workflows with a
`prompt_part` step, so they remain inline-capable and continue to use `#name`, even when
their body contains top-level `---` segment separators.

YAML workflow files can set a top-level `description` and use the same input-description
forms as markdown or config-defined macros:

```yaml
description: Refresh generated docs and report drift.
input:
  docs_dir:
    type: path
    description: Documentation root to refresh.
steps:
  - name: refresh
    bash: just docs
```

Workflow agent steps can embed macro references inline:

```yaml
steps:
  - name: review
    agent: |
      #mentor(prompt=[[Review error handling]])
```

See the [Workflow Specification](../workflows.md) for full details on multi-step
workflows, control flow, parallel execution, and human-in-the-loop approval.

## Related

- [Macro reference](index.md)
- [Workflow specification](../workflows.md)
- [Directive composition and fan-out](directive-composition.md)
