# SASE-22 Optional Resume Review

Date: 2026-05-04

## Scope

This reviews bead `sase-22`, titled "Optional #resume Name Input." The bead is closed and recorded as an `epic`-tier
plan bead, not a `legend`-tier bead. Its closed child work is:

- `sase-22.1` - Extract Resume Chat Resolution
- `sase-22.2` - Deterministic Multi-Prompt Bare #resume
- `sase-22.3` - End-to-End Workflow Coverage And Cleanup

## Summary

SASE-22 makes `#resume` easier to use in day-to-day prompting. Before this work, users normally had to name the agent
they wanted to resume, for example `#resume:builder`. After this work, users can write bare `#resume` and let SASE pick
the right previous chat in common workflows.

The explicit forms still work:

```text
#resume:builder
#resume(builder)
```

The new shortcut is:

```text
#resume
```

## New Features

### Bare `#resume` continues the most recent named agent

When `#resume` has no name, SASE now resolves it to the most recently launched named agent with usable chat history.
This makes follow-up prompts shorter when the user simply wants to continue the latest named conversation.

Example:

```text
#resume
Continue the previous investigation and turn the findings into a short plan.
```

If there is no previous named agent with chat history, SASE fails clearly instead of silently choosing an ambiguous
source.

### Bare `#resume` avoids resuming the current agent

When `#resume` is expanded from inside an active workflow, SASE excludes the current agent's artifact directory from the
default lookup. This prevents a workflow from accidentally treating its own still-forming metadata as the chat to
resume.

In practice, users do not need a new command for this. The same bare `#resume` form is safer in embedded workflow usage.

### Multi-prompt workflows can chain with bare `#resume`

In a multi-prompt markdown workflow, a bare `#resume` in a later segment now means "resume the previous segment's
agent." SASE resolves that relationship before launching the child process, so the chain does not depend on a global
"latest agent" race.

Example:

```text
Build the first version of the feature.
---
#resume
Review the first version and tighten the user-facing behavior.
```

The second segment resumes the first segment's agent.

### Named predecessor chains stay ergonomic

If the previous segment has an explicit name, the next bare `#resume` uses it.

Example:

```text
%name:builder
Build the first version of the feature.
---
#resume
Review the builder output.
```

The review segment resumes `builder`.

### Auto-named predecessor chains also work

If the previous segment does not have an explicit user-provided name, SASE plans or observes the generated name and uses
that for the next bare `#resume`. This keeps the workflow convenient without forcing users to name every intermediate
agent.

### Fanout uses the last generated agent name

For multi-model or `%alt` fanout, a later bare `#resume` follows the same convention as bare `%wait`: it resumes the
last generated agent from the previous fanout segment.

Example pattern:

```text
%n:ag
%alt(sec=Review security,perf=Review performance)
---
#resume
Summarize the last fanout result.
```

With named alternatives like `sec` and `perf`, the following segment resumes the last generated alternative.

### Examples stay examples

SASE only rewrites top-level bare `#resume` references. It leaves these alone:

- explicit forms like `#resume:builder` and `#resume(builder)`
- `#resume_by_chat:<path>`
- examples inside fenced code blocks
- disabled xprompt regions

## How To Use It

Use explicit `#resume:<name>` when you know exactly which agent should be resumed.

Use bare `#resume` when you want the normal default:

- in a standalone prompt, continue the most recent named agent;
- in a multi-prompt workflow segment after the first, continue the previous segment's agent;
- in a first multi-prompt segment, use the same global "most recent named agent" behavior as a standalone prompt.

## What Did Not Change

`#resume_by_chat:<path>` remains the direct path-based option when the user wants to resume a specific chat file.

Existing explicit `#resume` forms remain valid and keep their old meaning. The new behavior adds a default for omitted
names; it does not remove named resume control.

## Source Trail

- Bead: `sase bead show sase-22`
- Plan: `sdd/epics/202605/resume_optional_name.md`
- Phase commits:
  - `f8b8a4f9` - `feat: extract resume chat resolution (sase-22.1)`
  - `2b477f75` - `feat: make multi-prompt bare resume deterministic (sase-22.2)`
  - `083a40ff` - `test: cover bare resume workflow execution (sase-22.3)`
- User-facing workflow file: `src/sase/xprompts/resume.yml`
- Behavior coverage:
  - `tests/test_agent_chat_from_name.py`
  - `tests/test_multi_prompt_launcher_resume.py`
  - `tests/test_resume_workflow.py`
