---
title: Directive composition and fan-out
description: Directives for review, follow-up, repetition, and prompt fan-out.
---

# Directive composition and fan-out

This page documents directives for review, follow-up, repetition, and prompt fan-out.

## Editor Review Marker (` @`)

The old `%edit` directive has been removed. To compose a prompt in `$EDITOR` (via
`Ctrl+G`) and then review or tweak it in sase's TUI prompt bar instead of launching
immediately, end any line of the editor buffer with the exact suffix ` @` (a space
followed by `@`):

```
Refactor the parser module to use dataclasses. @
```

This is an editor-return syntax, not a runtime directive — it is only recognized in text
handed back from the external editor. Typing ` @` directly in the prompt bar and
submitting has no special behavior, and the marker carries no meaning in CLI, mobile, or
workflow execution. Submitting `%edit` raises a `DirectiveError` pointing here rather than
silently launching; `%e` is the `%effort` alias.

When at least one line ends with ` @`, the marker is stripped from every matching line
and the cleaned text is loaded back into the prompt input bar; the agent is not launched
until you press Enter there. The returned text loads with editor-file semantics: real
multi-agent `---` segment separators (outside fenced blocks and leading YAML
frontmatter) split sase's TUI prompt stack into one editable pane per agent segment, and
any leading macro frontmatter is lifted into the prompt properties panel above the top
pane. Because the strip runs before this parsing, a marked separator line such as
`--- @` becomes a real `---` separator. See [Prompt Stacks](../tui/prompt-stacks.md#prompt-stacks-1) in the
sase's TUI docs for the full review flow.

## Plan Approval and Coder Follow-up {#plan-directive}

SASE's planning workflow is driven by the `/sase_plan` skill together with the
`sase plan` approval pipeline. An agent drafts a plan and submits it with `/sase_plan`
(or `sase plan propose`). In an agent-runner context, submission hands the session to a
processless plan gate turn and ends the planner turn; that turn, not the provider
process, owns the pending review. In the TUI the authored `TALE` or `EPIC` plan status
settles when the selected branch's commands complete.
Feedback launches a replanner; tale approval launches a coder; epic approval may be
terminal because its approval command launches epic execution itself. The `%auto:tale`
and `%auto:epic` modes use the same pipeline but answer the plan decision synchronously
when the spelling covers the plan's tier; a plan of the other tier parks for review.

Once the plan is approved, sase launches a follow-up **coder** agent. That automated
hand-off still inlines the approved plan with `@` and does not share a body with the
`#coder` built-in macro (see
[sase/macros/coder.md](https://github.com/sase-org/sase/blob/main/src/sase/macros/coder.md)).
`#coder` instead takes the approved plan file as its `plan_file` input, names it by its
`YYYYmm/<name>.md` reference, and asks the agent to locate and read the plan itself (for
example with `sase artifact read plan:<reference> "<reason>"`) rather than receiving it
pre-inlined. The coder starts with a fresh context window; the plan file is the hand-off
artifact and the coder does not inherit the planner's chat transcript. The coder prompt
also carries a `%model:` directive. A model chosen at approval time (or a `%model:`/`%m`
directive inside a custom coder prompt) wins. When no model is chosen, the follow-up
validates the tale plan it will actually hand off and routes by that plan's size:
`%model:@xsmall`, `%model:@small`, `%model:@medium`, `%model:@large`, or
`%model:@xlarge`. Tale and commit approvals publish the reviewed plan to the durable
archive before their response becomes terminal. The follow-up receives the canonical
`plan:` reference and resolves it in its own workspace instead of depending on the
approver's checkout path. If that required publication fails, SASE does not write the
terminal response, so the approval stays pending and actionable. Tale plans without size
metadata normalize to `@medium`. The recorded follow-up metadata resolves
the alias to the concrete model the coder actually launches with and keeps the size
alias as `← @<size>` launch provenance in the coder's `Model:` field.

Outside the TUI, `sase plan` shows the same pending PlanApproval notifications plus
recent approved and inferred rejected archived plans. Use the plan name from a Proposed
row with `sase plan approve <name>` to default to a tale; epic-authored plans require an
explicit `--kind epic` or `--kind tale` override. The same command can approve a scratch
or archived plan that has no live gate, launching `#coder` in the planner's agent
session when it is safe to attach or standalone otherwise; `--dry-run` previews this
without changing state, and direct approvals leave durable receipts. Approving an
already-approved plan whose coder failed, was killed, or never launched relaunches a
replacement coder against the same approval; a plan whose coder is still running or has
finished is refused instead. If another responder answers the stale gate while the
command runs, sase launches no second coder and reports what it committed, exiting 1
with recovery commands when a `tale` coder is still owed. The `approve` kind runs the
coder without committing an SDD plan; `tale` commits an SDD tale and runs the coder;
`epic` commits the matching SDD tier and launches the bead follow-up; `commit` records
the approved plan in SDD without launching a coder. `-m/--model` picks the follow-up
agent's model, while `-p/--prompt` adds extra coder instructions for the `approve` and
`tale` paths. Tale and epic approvals validate the target schema first and leave an
invalid proposal pending. CLI rejection writes the same no-feedback rejection response
as sase's TUI, then attempts to dismiss and user-kill the matching planner when it can
be found.

When an agent launched with `%auto:epic` later submits an epic plan with `/sase_plan` or
`sase plan propose`, sase follows the same epic path as the TUI Epic action: it writes
the SDD epic files, commits them as needed, initializes beads, and launches the epic
follow-up agent. Like every other `%auto` spelling, `%auto:epic` leaves question gates
waiting for human answers; it only limits which plan tier auto-resolves.

```
%auto:epic
%id:billing-epic
Plan the billing dashboard epic.
```

## Repeat Directive

The `%repeat` directive runs the same prompt multiple times. The argument is a positive
integer specifying the repeat count:

```
%repeat:3
%id:linter
Run lint checks on the codebase.
```

This launches 3 independent agents — each spawned with its own process, workspace, and
`agent_meta.json`, appearing as its own top-level entry in the Agents tab. Fan-out
happens at launch time: the directive is consumed when the agents are spawned, so there
is no outer loop or TUI affordance ticking through iterations. The slot numbers are
appended to the `%id` base (`linter.1`, `linter.2`, `linter.3`); when `%id` is omitted
the auto-assigned base is used (e.g. `a.1`, `a.2`, `a.3`).

Iterations run **sequentially**: all N agents are spawned up front and register
immediately in the TUI, but iteration `k+1` is automatically wait-chained behind
iteration `k` via an injected `%wait:<prev_name>` directive. This turns `%repeat` into a
serial iteration primitive — each iteration can observe its predecessor's work — without
blocking the launcher on any single agent.

Each iteration exposes two iteration-scoped named arguments in the agent's workflow:

| Variable | Meaning                                   | Example with `%repeat:5` |
| -------- | ----------------------------------------- | ------------------------ |
| `n`      | Current iteration (1-based)               | 1, 2, 3, 4, 5            |
| `N`      | Total iterations (the `%repeat` argument) | 5                        |

These are threaded through via the `SASE_REPEAT_ITERATION` and `SASE_REPEAT_TOTAL`
environment variables — the agent runner reads them, converts to ints, and passes them
as named args into the workflow so they appear as Jinja2 variables in the prompt body:

```
%repeat:5
Run test suite batch {{ n }} of {{ N }}.
```

### Stopping a repeat chain early with `STOP`

A repeat iteration can stop every later slot by setting the reserved `STOP` output
variable before it completes:

```
%repeat:5
Process the next batch; if there is no more work, run: sase var set STOP=1
```

Because the slots are already spawned and wait-chained, "stopping" works on wake: when a
later slot's `%wait` on its repeat predecessor resolves, the slot checks that
predecessor's `STOP` output variable. If it is truthy, the slot propagates `STOP`,
finalizes as a successful **completed** (skipped) slot — recording
`repeat_stopped: true` and `stopped_by` in its `done.json` — and exits without claiming
a workspace or running its prompt. Keeping the outcome `completed` lets the stop cascade
down the chain through the ordinary `%wait` resolution, so each remaining slot winds
down one wait-check cycle after the previous one. `STOP` is conservative: `""`, `0`,
`false`, `no`, and `off` (case-insensitive) are not-stop; any other value stops the
chain. See [Cross-Agent Output Variables](multi-agent-prompts.md#cross-agent-output-variables) for how `STOP`
behaves outside repeat chains.

## Alt Directive

The `%alt` directive splits a single prompt into multiple variant prompts, each launched
as a separate agent. Each branch replaces the directive span in the output prompt.

The preferred shorthand is `%{A | B | ...}`, which uses braces and splits branches on
top-level `|` separators:

```
%{#review | #test | #docs}
Analyze the codebase.
```

This produces three agents, each with "Analyze the codebase." but with `#review`,
`#test`, or `#docs` substituted in place of the directive. Branches can be arbitrary
text — macro references, directives, plain instructions, or `[[text blocks]]`. Because
branches split only on a top-level `|`, a comma is ordinary branch text:
`%{foo, bar | baz}` is two branches (`foo, bar` and `baz`), not three. Nested `()`,
`[]`, `{}`, and backtick-quoted spans are not split, and any `|` inside them is treated
literally.

You can also fan out just a directive value by putting the alt group after the
directive's colon. For example, `%effort:%{medium | high | xhigh}` expands into three
launched prompts with `%effort:medium`, `%effort:high`, and `%effort:xhigh`;
`%m:%{opus | sonnet}` is equivalent to `%{%m:opus | %m:sonnet}`.

### Where `%{...}` Opens

`%{` opens an alternation anywhere outside literal/definition zones: at the start of a
line, after whitespace, mid-word (`foo%{bar | baz}qux` launches `foobarqux` and
`foobazqux`), after punctuation (`pre-%{a | b}`), right after another group
(`%{a | b}%{c | d}`), inside a directive value (`%m:op%{us | x}`), and inside another
alternation's branch (`%{sase-%{core | github} | chezmoi}` launches `sase-core`,
`sase-github`, and `chezmoi`). A nested group expands only when its branch is selected.
The only way to write a literal `%{` is inside inline code, fenced blocks, or
`%macros_enabled:false` regions.

The forms `%alt(...)` and `%(...)` open only at a directive-valid position (start of
line, or after whitespace, `(`, `[`, `{`,
`"`, `'`, or `:`). That keeps `%(name)s` format strings, `50%(approx)`, and
`--format=%(refname)` ordinary text.

A branch glued to neighboring text keeps adjacent directives parseable: when a selected,
non-empty branch starts with a `%` directive marker and the character before the group
is not a directive boundary, the renderer inserts one space before the branch, and
likewise after a trailing `%name…` directive when the next character is a word
character. So `Review:%{%m:opus | %m:sonnet}` launches `Review: %m:opus` with the opus
model, and `foo %{%m:opus | %m:sonnet}bar` launches `foo %m:opus bar`. `#macro`
references and `+tag`s in a glued branch are substituted verbatim, so put whitespace
before the `%{` to keep them references.

One ambiguity to know: a literal `%` immediately followed by a Jinja `{%` tag
(`100%{% if x %}`) now reads as an alternation opener. Write `100% {% if x %}` or use
inline code instead. Conversely, a `%{`, `%(` or `%alt(` right after a literal `{`
(`{%{a | b}`) is an alternation, not a Jinja tag. It launches `{a` / `{b`.

The forms `%alt(...)` and `%(...)` are accepted; both use
parentheses with comma-separated branches:

```
%alt(#review, #test, #docs)
%(#review, #test, #docs)
```

New prompts, completions, snippets, and docs should prefer `%{...}`. `%(...)` stays
parse-compatible during the migration; it may be removed in a future release.

### Named Branches

Branches can be named with `id=value`. The `value` is inserted into the spawned prompt
and the `id` becomes the child agent suffix. For example,
`%id:review %{sec=[[security]] | perf=[[performance]]}` launches `review.sec` and
`review.perf`. Unnamed branches use numeric suffixes while skipping any numeric ids
already provided by named branches, so `%{2=[[named]] | [[first]] | [[second]]}`
launches suffixes `2`, `1`, and `3`.

When the same named branch id appears in more than one alt directive, those directives
are correlated: values with the same id render into the same child prompt, and a missing
id in one correlated directive renders as empty text. Empty renders also collapse
adjacent horizontal whitespace, so they do not leave doubled spaces or spaces before
punctuation; only spaces and tabs are collapsed, newlines and indentation are preserved,
and non-empty branches are untouched. For example:

```
%id:repo %{a=Describe | b=Explain} how this repo works %{a=in detail}.
```

This launches `repo.a` with "Describe how this repo works in detail." and `repo.b` with
"Explain how this repo works.".

### Single Branch (With/Without Split)

A single-branch alt is treated as a with/without split — it produces two prompts: one
with the branch text and one with the directive removed entirely:

```
%{Also check for security issues.}
Review this module.
```

This launches two agents: one with "Also check for security issues. Review this module."
and one with just "Review this module."

### Cartesian Product

Multiple alt directives can appear in the same prompt. Branch lists with no repeated
named ids form a **Cartesian product**: one agent is launched per combination. Brace and
paren forms mix freely:

```
%{Focus on security | Focus on perf} %{%m:opus | %m:sonnet}
Review this code.
```

This produces 2 × 2 = 4 agents (every focus area paired with every model). Model
directives used as branches inside `%{...}` participate in the Cartesian product
naturally: `%{#review | %model:opus}` fans out a default-model review branch and an opus
branch.

Repeated named ids are the exception to the Cartesian rule. Disjoint named ids and
unnamed branches remain Cartesian; only the same explicit id repeated across directives
is zipped together.

## Multi-Model Fan-Out

The `%model` directive is single-value. To launch multiple agents in parallel — one per
model — put one model directive in each `%{...}` branch:

```
%{%m:opus | %m:sonnet}
Review this code for edge cases.
```

This launches two agents with identical prompts, each using a different model. Each
agent appears as a separate entry in the Agents tab. Each branch accepts one model.
Comma-separated model arguments and repeated top-level `%model` directives are rejected.
Colon syntax (`%m:opus`) and single-model parentheses (`%m(opus)`) launch a single agent.

When a prompt fans out to multiple models, the spawned agents share a single base name
and carry a runtime suffix so they can be told apart at a glance. Given
`%{%m:opus | %m:gpt-6.1-sol} %i:foo`, the two agents are named `foo.cld` and `foo.cdx`.
The runtime suffix is a short alias declared by the provider plugin (via the
`llm_provider_short_name` hook) — `cld`, `cdx`, `agy`, `qwn`, `opc` for the built-in
providers — falling back to the full provider name for plugins that don't declare one.
If `%id` is omitted, a single auto-generated base is allocated and shared (e.g. `a.cld`
/ `a.cdx`) rather than each agent picking its own letter independently. Single-model
prompts retain their plain `%id` value unchanged. When two models share a runtime (e.g.
`%{%m:opus | %m:sonnet}` — both `claude`), the model name disambiguates the suffix:
`foo.cld-opus` and `foo.cld-sonnet`. Long model slugs are replaced with a short alias
declared by the provider plugin, so a same-runtime agy fan-out can read as
`foo.agy-flash36h` / `foo.agy-flash35h` rather than echoing the full model string. Model
arguments used for naming are first resolved through macro shorthand expansion, while
the launched prompt keeps the original `%model` value. For example,
`%i:ag %{%m:#flash | %m:#pro}` can launch agents named `ag.agy-flash35h` and
`ag.agy-flash36h`.

## Multi-Value Directives

The `%wait` directive supports multiple occurrences — each adds to the wait list:

```
%wait:agent1
%wait:agent2
%wait:agent3
Do work after all three agents finish.
```

Agent dependencies, time floors, and per-launch capacity budgets can be mixed freely —
dependencies and the time floor stay on `%wait`, while the admission budget moves to
`%queue`:

```
%wait(agent1, time=5m) %queue(capacity=1)
Wait for agent1 to finish, wait at least 5 minutes from launch, then wait until occupied
weighted load plus this launch's weight fits within its authored budget of 1.
```

## Related

- [Directive catalog](directives.md)
- [Launch directives](directive-launch.md)
- [Multi-agent prompts](multi-agent-prompts.md)
