---
title: Built-in and configured macros
description: Built-in macros, configuration-defined macros, and local macro files.
---

# Built-in and configured macros

This page documents built-in and configuration-defined macros and their local files.

## Built-in Macros

Core macros ship in `src/sase/default_config.yml`, `src/sase/default_macros/*.md`, and
`src/sase/macros/` (bundled skills ship in the nested `src/sase/macros/skills/`
resource). They are always available without needing a project- or user-level
definition. They're at the built-in end of the [discovery order](discovery.md#discovery-order), so
any project, user, or config macro with the same name overrides the packaged defaults.
Common entries include:

| Reference             | Body summary                                                                                                |
| --------------------- | ----------------------------------------------------------------------------------------------------------- |
| `#git`                | Check out a git ref in an isolated workspace and show resulting changes                                     |
| `#commit`             | Create a normal commit from completed agent changes                                                         |
| `#propose`            | Create a proposal from completed agent changes                                                              |
| `#file`               | Require the agent to write its response to a named markdown artifact                                        |
| `#fork`               | Resume context from an agent, named proc, monitor, a complete clan, or the next completed entity in a tribe |
| `#fork_by_chat`       | Resume context from a specific chat transcript path                                                         |
| `#mentor`             | Run a structured mentor review against a PR                                                                 |
| `#split_file`         | Ask an agent to split one large Python file into import-safe smaller files                                  |
| `#summarize`          | Summarize a file in a short phrase for a specified use                                                      |
| `#tribe`              | Assign an auto-named agent to a user-managed tribe                                                          |
| `#json`               | Require the agent response to satisfy a JSON schema                                                         |
| `#!sync`              | Sync the current workspace and launch conflict-resolution help if needed                                    |
| `#plan`               | Asks the agent to think the work through and use its `/sase_plan` skill before any file changes             |
| `#epic`               | Marks the request as a multi-phase epic and chains `#plan`                                                  |
| `#review`             | Asks the agent to fix bugs and apply only clear-win improvements                                            |
| `#prompt/approve`     | Boilerplate "I've edited the previous reply with my decisions; implement this" preamble + `#plan`           |
| `#prompt/review`      | Wraps a `prompt` input and asks for a gap/ambiguity review before implementation                            |
| `#x:name,cmd`         | Saves a freeform `sase_xcmd` command to the prompt (`@$(sase_xcmd <name> <cmd>)`)                           |
| `#bd/work_phase_bead` | Per-phase agent prompt used by `sase bead work`; uses the default queue priority                            |
| `#bd/work_task`       | Task-agent prompt used by `sase bead work`; completes assigned task beads                                   |
| `#bd/land_epic`       | Final lander; reviews all bead notes and routes distinct follow-ups through `/sase_new_task`                |
| `#bd/review/plan`     | Plan-review helper for an epic plan                                                                         |
| `#bd/review/prompt`   | Prompt-review helper for an epic plan                                                                       |

When `#fork` / `#fork_by_chat` injects a `# Previous Conversation` block, the prior
**user prompts** in that block are sanitized first: sase directives (`%id`, `%wait`,
`%model`, ...), `#`/`#!` macro and workspace references, and any unrendered Jinja2
markers (`{{ }}`, `{% %}`, `{# #}`) are stripped so the forked agent sees clean
natural-language text. Fenced code blocks and real markdown headings are preserved, and
assistant responses are left untouched. Raw transcripts on disk are unchanged — the
cleanup happens only when building resume history (so `sase chat show` still shows the
original prompts).

`#fork:<clan>` waits for a complete clan generation and injects a launch-ordered clan
summary. The summary includes each member's sanitized prompts, outcome/model metadata,
reply size, and transcript path, but deliberately omits full member replies so the child
can open only the transcripts it needs. `#fork:@<tribe>` waits for the earliest
completed standalone agent or complete clan in that tribe launched after the new agent,
then injects the matching agent conversation or clan summary. Multiple `#fork(...)`
parents can mix agent, clan, and tribe references; SASE preserves the declared parent
order while removing duplicates.

A terminally failed agent is also a valid `#fork:<agent>` source. Its injected history
is marked `PARENT AGENT FAILED`, includes the recorded failure message and traceback
tail when available, and treats the transcript as incomplete context to verify rather
than successful work to trust. Because an already-failed parent can never satisfy a
wait, SASE skips the normally implied `%wait:<agent>` for that fork target; an explicit
`%wait:<agent>` you typed is still preserved.

When a new agent forks a session it already belongs to, its own artifact does not count
against the fork target's completeness. The implied wait still holds for any other live
session member, because that member's transcript or execution record is not ready to
inject yet.

A bare-name `#fork` bound while the parent is still a plain agent is recorded as a
session wait, so a later promotion of that parent into a session keeps the fork waiting
through review and coding. A fork bound to an exact `--<suffix>` member name keeps
waiting on that one member only.

`#fork` also resolves a stand-alone named proc (by its reusable proc name or its exact
proc ID) and a monitor session member (by its `--mon`/`--mon-N` proc name or exact proc
ID). Both are execution records, never a prior conversation: the injected block states
the proc role, command or safe code preview, cwd/project, timestamps, exit/timeout
status, and a bounded, explicitly untrusted tail of program output, plus the full log
path and exact `sase proc show <id> --all-lines` (or `sase monitor show`) command when
more output is available. A reusable proc/monitor turn name is bound to one exact
durable proc ID when the fork directive is extracted, so a later proc reusing that name
never redirects an already-queued fork. An exact proc ID is always the unambiguous
choice when a proc name collides with an agent name. Like an agent source, an implicit
`%wait` for a proc or monitor target releases on that target's terminal success or
failure, not only on success.

To see the exact body of any built-in inline macro, run
`sase macro expand --trace '#<name>'` or browse the catalog with `sase macro catalog`.
Use `sase macro explain <name>` for workflows; the explain command takes the workflow
name without a `#` or `#!` marker.

Bundled task, phase, and lander workers do not author a priority wait or a non-default
queue weight, so they use the runner's default priority (`10`) and the default `1.0`
capacity unit when otherwise eligible. Higher-precedence project, user, config, and
plugin overrides supply their own bodies and may choose a different priority or weight.

The bundled task worker reads, completes, and closes its assigned task. The epic lander
reviews the epic's own notes and every child note, keeps unresolved issues caused by the
epic inside that epic, and uses `/sase_new_task` only for distinct follow-ups. Phase
workers remain prohibited from creating tasks and instead append `PROPOSED FOLLOW-UP:`
notes for the lander.

### Bundled Follow-Up Macros

SASE ships two embeddable follow-up prompt workflows for manual session rounds:

| Reference        | Inputs                        | Purpose                                                                  |
| ---------------- | ----------------------------- | ------------------------------------------------------------------------ |
| `#with_feedback` | `feedback`, optional `parent` | Append plan feedback using the same replan prompt renderer as the runner |
| `#with_q_and_a`  | `prompt`, `qa_file`           | Append answered SASE questions using the same Q&A renderer as the runner |

Both macros only assemble prompt text; `%i(suffix, session=parent)` is the launch
directive that attaches the new agent to the session. See
[Agent Clans, Sessions, and Tribes](../agents/index.md) for the full attachment and
launch-approval model.

For feedback, pass `parent=` explicitly or combine it with `%i(suffix, session=parent)`
and let SASE infer the parent:

```text
%i(@, session=planner) #with_feedback:: Add failure handling before coding.
%i(reviewer, session=planner) #with_feedback(parent=planner):: Re-check the API shape.
```

For Q&A, provide a JSON file containing one or more answered question rounds:

```text
%i(@, session=planner) #with_q_and_a(qa_file=/tmp/qa_rounds.json):: Continue with the base prompt.
```

The Q&A file should use the same structured request/response shape SASE writes for user
questions: `questions` plus a `response`, or a top-level `rounds` list of those objects.
Literal `#macro` text inside answers is protected so it does not expand accidentally.

Glossary note: this feature uses the runner's double-dash plan-chain session model —
agents such as `foo--0`, `foo--plan`, and `foo--code` share the pure session container
`foo`. Dot-separated names such as `foo.bar` are agent hoods/neighbors in sase's TUI, a
distinct grouping concept. See [Agent Clans, Sessions, and Tribes](../agents/index.md)
for the full session model.

### Scheduled Work Uses Jobs

Scheduled automation runs AXE scripts that may emit structured launch proposals;
shared triggers, guards, checkpoints, dedupe, and target fan-out stay in the runner.
Proposal prompts may use inline `#macro` templates, but standalone `#!workflow`
references are rejected. See [Axe](../automation/scheduler-jobs.md#structured-results-and-launch-proposals) for
the script/result contract and the builtin documentation refresh job.

## Config-Based Macros

Macros can be defined inline in `sase.yml` under the `macros:` key.

### Simple Format

```yaml
macros:
  propose: "Please propose your changes before applying them."
```

### Structured Format

```yaml
macros:
  greet:
    description: Greet a user a configurable number of times.
    input:
      name:
        type: word
        description: Name to greet.
      count:
        type: int
        default: 1
        description: Number of greetings to render.
    content: "Hello {{ name }}, count is {{ count }}"
```

## Related

- [Macro reference](index.md)
- [Discovery](discovery.md)

Config-based macros follow project and home file sources and precede plugin/package file
resources. Within config, project `sase/sase.yml` wins over user overlays and base
config.

Standalone workflows are YAML content from the file-backed sources in
[Macro discovery](discovery.md#discovery-order). Top-level `workflows:` blocks in project
`sase/sase.yml`, global `sase.yml`, and `sase_*.yml` overlays are ignored by the runtime.
See [Macro migration notes](../upgrading/macros.md#workflow-configuration) for the
configuration rule.

## Local Configuration Files

You can define project-specific macros in `sase/sase.yml` at the detected project root.
This is a full SASE config file that can override any configuration, including macros.
It is the highest-priority config source in the
[deep-merge system](../config/files-and-merging.md#deep-merge-system), overriding
global `sase.yml`, overlay files, plugin configs, and built-in defaults. Individual
`.md` files in macros directories still take precedence over config-defined macros. A
root-level `sase.yml` is an exclusive read-only fallback during the compatibility window.

```yaml
macros:
  # Simple format — value is the template body
  propose: "Please propose your changes before applying them."

  # Structured format — with typed inputs and/or output
  greet:
    description: Greet a user a configurable number of times.
    input:
      name:
        type: word
        description: Name to greet.
      count:
        type: int
        default: 1
        description: Number of greetings to render.
    content: "Hello {{ name }}, count is {{ count }}"
```
