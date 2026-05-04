# Optional `#resume` Name Input Review

Date: 2026-05-04

## Scope

This review covers bead `sase-22`, **Optional `#resume` Name Input**. The bead database records it as a closed
epic-tier plan bead, with three closed phase beads:

- `sase-22.1` - Extract Resume Chat Resolution
- `sase-22.2` - Deterministic Multi-Prompt Bare `#resume`
- `sase-22.3` - End-to-End Workflow Coverage And Cleanup

Primary sources reviewed:

- Bead metadata from `sase bead show sase-22`
- Plan: `sdd/epics/202605/resume_optional_name.md`
- Prompt: `sdd/prompts/202605/resume_optional_name.md`
- Commits: `f8b8a4f9`, `2b477f75`, `083a40ff`

## Summary

The completed work makes `#resume` easier to use by allowing the `name` input to be omitted. Users can now type bare
`#resume` when they want to continue from the most recent named agent, while existing explicit forms continue to work.

The most important user-facing addition is deterministic behavior inside multi-prompt markdown workflows. When a
workflow contains several prompt segments separated by `---`, a bare `#resume` in a later segment resumes the previous
agent from that same workflow, not whichever agent happens to be globally most recent at that moment. This matters when
several multi-prompt workflows are launched at the same time.

## New Features

### Bare `#resume`

`#resume` can now be used without a name:

```text
#resume
Continue the prior analysis and turn it into a final recommendation.
```

When used this way, SASE selects the most recently launched named agent that has usable chat history. If there is no
previous named agent, the workflow fails with a clear "no previous named agent" style error instead of requiring users
to discover that the `name` input was missing.

### Existing Explicit Resume Forms Still Work

The previous explicit forms remain the best choice when the user wants a specific agent:

```text
#resume:builder
Review the implementation.
```

```text
#resume(builder)
Review the implementation.
```

Explicit resume keeps the existing lookup behavior: completed agents prefer their final response transcript, while
running or non-final agents can still use their active chat transcript when available.

### Safer Default Selection

Bare `#resume` avoids selecting the current agent as its own resume source when workflow execution has already written
current-agent metadata. This makes embedded `#resume` references safer in normal agent workflows.

The default selection also follows the existing named-agent conventions used by related bare-reference behavior, such
as skipping dismissed-prefixed agent names.

### Deterministic Multi-Prompt Resume

In a multi-prompt markdown workflow, later segments can now use bare `#resume` to mean "resume the previous segment":

```markdown
Build the first draft.

---

#resume
Review the draft and identify gaps.

---

#resume
Apply the review and produce the final version.
```

In this example:

- The second segment resumes the first segment's agent.
- The third segment resumes the second segment's agent.
- The choice is made from the workflow's own segment order, so concurrent workflows do not interfere with each other.

The first segment is different: if the first segment contains bare `#resume`, it still uses the global "most recent
named agent" default because there is no previous segment in the same workflow.

### Fanout Compatibility

The new behavior follows the same predecessor rule as bare `%wait` for fanout-style workflows. If one segment launches
multiple agents through multi-model or `%alt` expansion, a later bare `#resume` resolves to the last generated agent
name from that prior segment.

Use an explicit `#resume:<name>` when a workflow should resume a particular fanout branch instead of the default last
branch.

## How To Use It

Use bare `#resume` for the common "continue from the last named agent" case:

```text
#resume
Summarize the decision and next steps.
```

Use explicit resume when targeting a specific agent:

```text
#resume:frontend-pass
Turn the findings into action items.
```

Use bare `#resume` in later multi-prompt segments when each step should build on the immediately previous step:

```markdown
Research the problem and propose options.

---

#resume
Choose the strongest option and write an implementation plan.

---

#resume
Critique the plan for missing risks.
```

If exact ancestry matters across a complex fanout, prefer explicit names so the workflow documents which branch is being
resumed.

## Behavior To Remember

- `#resume` without a name now means "use the default resume target."
- Outside a multi-prompt workflow, the default target is the most recent named agent with usable chat history.
- Inside a multi-prompt workflow, bare `#resume` in segment 2 or later targets the immediately previous segment's agent.
- `#resume:<name>` and `#resume(<name>)` are unchanged and should be used for precise targeting.
- Bare `#resume` still needs a prior named agent; it is not a substitute for saving or naming useful agent runs.

## Validation Evidence

The associated commits added focused coverage for:

- Explicit completed and running-agent resume lookup.
- Omitted-name defaulting to the most recent named agent.
- Avoiding current-agent self-selection.
- Bare `#resume` rewriting in multi-prompt workflows.
- Explicit resume and fenced-code examples remaining unchanged.
- Workflow-level validation that the built-in `resume.yml` accepts omitted `name`.
- Embedded bare `#resume` loading the resolved transcript path through the real workflow path.

