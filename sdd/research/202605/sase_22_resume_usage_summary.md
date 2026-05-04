# SASE-22 Optional `#resume` Usage Summary

Date: 2026-05-04

## Scope

This note reviews the completed work for bead `sase-22`, titled **Optional #resume Name Input**. The bead is closed and
has three closed child phases:

- `sase-22.1` - Extract Resume Chat Resolution
- `sase-22.2` - Deterministic Multi-Prompt Bare #resume
- `sase-22.3` - End-to-End Workflow Coverage And Cleanup

Although the request called this a legend bead, `sase bead show sase-22` records it as an epic-tier plan bead.

## User-Facing Summary

The work makes `#resume` easier to use. Users can now omit the agent name when they want the normal continuation target:

```markdown
#resume
Continue from the prior agent and summarize the result.
```

Explicit resume still works and remains the right choice when the source agent matters:

```markdown
#resume:builder
Review builder's implementation notes.
```

```markdown
#resume(builder)
Review builder's implementation notes.
```

The new behavior is a convenience layer over the existing resume concept. It does not remove precise named resume, and
it does not replace `#resume_by_chat:<path>` for direct chat-file targeting.

## New Features

### Bare `#resume`

`#resume` can now be used without a `name` argument. Outside a multi-prompt workflow, the default target is the most
recent named agent with usable chat history.

Use it for quick follow-ups where the latest named agent is obviously the one you mean:

```markdown
#resume
Turn the previous findings into a short decision memo.
```

If SASE cannot find a previous named agent with usable chat history, the resume fails clearly instead of silently
choosing an ambiguous source.

### Safer Embedded Resume

Bare `#resume` avoids selecting the current running agent as its own resume source when it is expanded inside an active
workflow. In day-to-day use, this means embedded resume is safer without requiring a different command.

### Multi-Prompt Chaining

In markdown workflows split by `---`, a bare `#resume` in the second or later segment now means "resume the previous
agent from this same workflow."

```markdown
Draft a migration plan.

---

#resume
Critique the plan for missing risks.

---

#resume
Rewrite the plan using the critique.
```

In this workflow:

- the second segment resumes the first segment's agent;
- the third segment resumes the second segment's agent;
- the chain is local to this workflow, even if other workflows are launching at the same time.

The first segment has no previous workflow segment, so a bare `#resume` there keeps the standalone behavior and uses the
most recent named agent.

### Explicit Names Still Win

If a segment has an explicit name, the next bare `#resume` uses that name:

```markdown
%name:builder
Build the first version.

---

#resume
Review the first version.
```

The review segment resumes `builder`.

### Fanout Compatibility

When a segment launches multiple agents through fanout, a following bare `#resume` follows the same convention as bare
`%wait`: it targets the last generated agent from the previous segment.

Use explicit names when a later step should resume a specific branch instead of the default last branch.

## Recommended Usage

Use bare `#resume` when:

- you are writing a quick standalone follow-up to the latest named agent;
- a multi-prompt workflow should read as a simple step-by-step chain;
- the exact prior agent name is incidental and obvious from workflow order.

Use explicit `#resume:<name>` or `#resume(name)` when:

- the workflow should resume an older agent;
- multiple plausible prior agents exist;
- a fanout branch needs to be selected deliberately;
- the prompt should document exact ancestry for later review.

Use `#resume_by_chat:<path>` when the source should be a specific chat transcript file rather than an agent name.

## Practical Examples

Continue the latest named agent:

```markdown
#resume
Extract the key action items.
```

Chain a review after a named builder:

```markdown
%name:builder
Implement the requested CLI behavior.

---

#resume
Review the implementation from the user perspective.
```

Prefer explicit targeting in ambiguous workflows:

```markdown
#resume:security-review
Turn the security findings into release blockers and non-blockers.
```

## Reviewed Sources

- Bead metadata: `sase bead show sase-22`
- Plan: `sdd/epics/202605/resume_optional_name.md`
- Phase commits:
  - `f8b8a4f9` - `feat: extract resume chat resolution (sase-22.1)`
  - `2b477f75` - `feat: make multi-prompt bare resume deterministic (sase-22.2)`
  - `083a40ff` - `test: cover bare resume workflow execution (sase-22.3)`
- User-facing workflow: `src/sase/xprompts/resume.yml`
- Related coverage:
  - `tests/test_agent_chat_from_name.py`
  - `tests/test_multi_prompt_launcher_resume.py`
  - `tests/test_resume_workflow.py`
