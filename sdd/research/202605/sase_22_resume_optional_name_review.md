# SASE-22 Optional `#resume` Name Review

Date: 2026-05-04

## Question

What user-facing behavior shipped with the closed `sase-22` bead, and how should people use it?

Note: the bead is recorded as an `epic` tier bead, not a `legend` tier bead. It is titled **Optional `#resume` Name
Input** and has three closed phase beads.

## Summary

`sase-22` makes `#resume` easier to use in everyday agent workflows. Users no longer have to remember or type an agent
name when they simply want to continue from the most recent named agent. Existing explicit forms still work:
`#resume:<name>` and `#resume(<name>)`.

The most important addition is safe bare `#resume` behavior:

1. A standalone bare `#resume` resumes the most recently launched named agent.
2. In a multi-prompt markdown workflow, a bare `#resume` in the second or later prompt resumes the previous agent from
   that same workflow.
3. The multi-prompt behavior is decided before each child agent is launched, so concurrently running workflows do not
   accidentally resume agents from another workflow.
4. Bare `#resume` avoids selecting the current agent as its own source.

This turns `#resume` into a convenient chaining primitive instead of only a direct reference primitive.

## New Features

### 1. Optional Name Input For `#resume`

Before this work, `#resume` required a name input. After this work, users can write:

```markdown
#resume
Continue the prior conversation and finish the review.
```

When no name is supplied, SASE chooses the latest named agent with usable chat history. This keeps the common "continue
what I was just doing" flow short.

Explicit targeting is unchanged:

```markdown
#resume:builder
Review the implementation from builder.
```

```markdown
#resume(builder)
Review the implementation from builder.
```

### 2. Most Recent Named Agent Default

Bare `#resume` now has a global default outside multi-prompt chains: it resumes the most recently launched named agent.

The behavior intentionally ignores dismissed-prefix historical names in the same way bare `%wait` does, and it excludes
the current agent artifacts directory when available. That means a running workflow should not accidentally inject its
own just-written metadata as the resume source.

User-facing effect: in normal interactive use, `#resume` means "resume the last named agent I launched," not "make me
look up the exact name first."

### 3. Deterministic Multi-Prompt Chaining

Bare `#resume` now works as a local "previous agent" reference inside multi-prompt markdown files.

Example:

```markdown
%name:builder
Build the feature.

---

#resume
Review the feature from the previous agent.
```

The second prompt is launched as if it had said:

```markdown
#resume:builder
Review the feature from the previous agent.
```

This also works when the first prompt is auto-named. SASE plans or discovers the previous segment's agent name, then
uses that concrete name for the next segment. If a segment fans out through `%alt` or multi-model expansion, the next
bare `#resume` follows the last spawned agent from that fanout, matching the existing bare `%wait` behavior.

### 4. Race-Safe Concurrent Workflows

The multi-prompt default is resolved in the parent launcher before child agents run. That matters when several
multi-prompt workflows are launched at the same time.

Without this behavior, a child agent containing bare `#resume` could independently ask "what was the most recent named
agent?" and get an agent from a different workflow. After `sase-22`, later segments in the same markdown workflow are
rewritten to explicit local predecessor names before launch, so the intended conversation chain remains stable.

### 5. Coverage For The Real Workflow

The work added test coverage for:

- explicit completed agents using their saved response path;
- running or historical agents using chat metadata when needed;
- omitted names choosing the most recent named agent;
- omitted names excluding the current agent;
- clear failure when no previous named agent exists;
- multi-prompt bare `#resume` rewriting;
- preserving explicit `#resume:<name>` and `#resume(name)`;
- ignoring examples inside fenced code blocks or disabled xprompt regions;
- the real built-in `src/sase/xprompts/resume.yml` accepting an omitted name;
- embedded bare `#resume` loading the resolved prior chat.

## How To Use It

Use bare `#resume` when you want the natural default:

```markdown
#resume
Pick up from the previous named agent and produce the final answer.
```

Use explicit `#resume:<name>` when the source agent matters or when you are referring to an older agent:

```markdown
#resume:planner
Implement the plan from planner.
```

Use bare `#resume` in a multi-prompt workflow when each step should continue from the previous step:

```markdown
Draft the migration plan.

---

#resume
Critique the plan for missing risks.

---

#resume
Rewrite the plan using the critique.
```

In that shape, the second prompt resumes the first agent, and the third prompt resumes the second agent, even if other
workflows are launching at the same time.

## Reviewed Sources

- Bead: `sase bead show sase-22`
- Plan: `sdd/epics/202605/resume_optional_name.md`
- Prompt: `sdd/prompts/202605/resume_optional_name.md`
- Phase commits:
  - `f8b8a4f9` - `feat: extract resume chat resolution (sase-22.1)`
  - `2b477f75` - `feat: make multi-prompt bare resume deterministic (sase-22.2)`
  - `083a40ff` - `test: cover bare resume workflow execution (sase-22.3)`
