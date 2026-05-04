---
created: 2026-05-04
bead_id: sase-22
topic: Optional #resume Name Input
---

# SASE-22 Resume Behavior User Summary

## Scope

This note reviews the completed work associated with bead `sase-22`, titled **Optional #resume Name Input**.

The prompt called this a legend bead, but the bead database records `sase-22` as a closed **epic-tier** plan bead with
three completed child phases:

- `sase-22.1` - Extract Resume Chat Resolution
- `sase-22.2` - Deterministic Multi-Prompt Bare #resume
- `sase-22.3` - End-to-End Workflow Coverage And Cleanup

## User-Facing Summary

`#resume` is now easier to use because the agent name is optional.

Before this work, users generally had to write a target name, such as `#resume:builder` or `#resume(builder)`, to load a
previous agent conversation into a new prompt. After `sase-22`, users can write bare `#resume` and SASE chooses a
reasonable default.

The explicit forms still work:

```text
#resume:builder
```

```text
#resume(builder)
```

The new shorthand also works:

```text
#resume
```

## New Features

### Bare `#resume`

Users can now omit the name argument.

When `#resume` is used without a name in a normal prompt, SASE resumes the most recently launched named agent that has a
usable chat history.

Example:

```text
Summarize the decisions from the previous agent.
#resume
```

This is useful for quick follow-ups when the desired source is simply "the last named agent I worked with."

### Current-Agent Exclusion

Bare `#resume` avoids selecting the currently running agent as its own source when SASE knows the current artifacts
directory.

The practical effect is that an agent can use `#resume` inside a workflow without accidentally loading its own partial
or newly written metadata as the previous conversation.

### Deterministic Multi-Prompt Resume Defaults

Bare `#resume` is now deterministic inside multi-prompt markdown workflows.

For a workflow split into multiple agent segments with `---`, later segments that contain bare `#resume` resume the
previous agent from the same workflow instead of consulting the global "most recent agent" list at child-agent runtime.

Example:

```text
%name:builder
Implement the change.

---

#resume
Review the implementation.
```

The second segment resumes `builder`.

This also works when the first segment uses an auto-generated name:

```text
Implement the change.

---

#resume
Review the implementation.
```

SASE plans or discovers the first agent's name before launching the second segment, then treats the second segment as if
it had explicitly referenced that predecessor.

### Fanout-Friendly Resume Behavior

When a workflow segment fans out through multi-model or `%alt` style expansion, a later bare `#resume` follows the same
default behavior as bare `%wait`: it points at the last generated agent from the prior segment fanout.

Example shape:

```text
%name:ag
%alt(sec=Build security review,perf=Build performance review)

---

#resume
Compare the final result.
```

The following resume target becomes the last generated variant from the previous fanout, such as `ag.perf` in the tested
case.

### Workflow-Level Support

The built-in `resume.yml` workflow now declares the `name` input as optional. Embedded `#resume` calls can therefore
pass validation without a name argument, resolve a chat path, and inject the previous conversation into the prompt.

## How To Use It

Use an explicit name when you need a specific agent:

```text
#resume:builder
Continue from the builder's last answer.
```

Use bare `#resume` for quick follow-ups to the most recent named agent:

```text
#resume
Turn this into release notes.
```

Use bare `#resume` in the second or later segment of a multi-prompt workflow when the intended source is the immediately
previous agent in that workflow:

```text
Draft the migration plan.

---

#resume
Find gaps in the migration plan.

---

#resume
Apply the review feedback.
```

Each later segment resumes the previous segment's agent, giving the workflow a natural handoff chain.

## Behavior To Remember

- `#resume:<name>` and `#resume(<name>)` keep their existing explicit-target behavior.
- Bare `#resume` in a normal prompt means "resume the most recent named agent."
- Bare `#resume` in later multi-prompt segments means "resume the previous agent in this workflow."
- Bare `#resume` in the first multi-prompt segment keeps the normal global default behavior.
- Examples inside fenced code blocks or disabled xprompt regions are not rewritten.
- Related xprompts like `#resume_by_chat` are not treated as bare `#resume`.

## Verification Sources

- Bead metadata: `sase bead show sase-22`
- Plan: `sdd/epics/202605/resume_optional_name.md`
- Prompt: `sdd/prompts/202605/resume_optional_name.md`
- Implementation commits:
  - `f8b8a4f9` - `feat: extract resume chat resolution (sase-22.1)`
  - `2b477f75` - `feat: make multi-prompt bare resume deterministic (sase-22.2)`
  - `083a40ff` - `test: cover bare resume workflow execution (sase-22.3)`
- User-facing behavior confirmed from:
  - `src/sase/xprompts/resume.yml`
  - `tests/test_agent_chat_from_name.py`
  - `tests/test_multi_prompt_launcher_resume.py`
  - `tests/test_resume_workflow.py`
