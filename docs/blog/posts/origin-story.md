---
title: "[00] Origin Story — Where SASE Came From"
date: 2026-05-06
description: >-
  The day-job constraint that made the case for SASE: large-codebase rigor, a lagging in-house model, and the
  realization that the cheapest part of an agentic workflow should be the workflow itself.
categories:
  - Agentic Software Engineering
slug: origin-story
links:
  - SASE Blog Series: series/agentic-software-engineering.md
  - "[01] Why Coding Agents Need Orchestration": blog/posts/why-coding-agents-need-orchestration.md
  - Start with ACE: ace.md
  - View on GitHub: https://github.com/sase-org/sase
---

# [00] Origin Story — Where SASE Came From

SASE started as a coping mechanism. I was a software engineer at Google, working in codebases and on teams large enough
that the everyday open-source playbook — read a file, change a file, send a PR — stops being a complete description of
the job. The rigor that scales to those environments is not just _writing code_ rigor; it is _surrounding the code_
rigor: durable plans, review state that outlives a chat window, dependencies between changes, retries that don't lose
context, and handoffs that someone else can pick up cold.

<!-- more -->

This post is the prequel to the rest of the [SASE Blog Series](../../series/agentic-software-engineering.md). It
explains the lived constraint that pushed SASE's design toward a particular shape: a coordination layer above coding
agents that treats workflows as cheap and models as mortal. If you would rather skip the backstory and start from the
technical argument, jump to [\[01\] Why Coding Agents Need Orchestration](why-coding-agents-need-orchestration.md).

## Large-Codebase Rigor Is Different

A lot of writing about agentic coding starts from the small-repo experience: one project, one developer, one prompt, one
diff. That world is real and it matters. But it is not the world I spent most of my time in. In a large engineering org,
the load-bearing surfaces are different:

- A change is rarely "this file." It is "this slice of behavior across the services and tests that touch it."
- A review is rarely "two engineers in a thread." It is a record that survives reassignments, partial approvals,
  rebases, follow-up changes, and the occasional revert.
- A task is rarely independent. It is a node with parents, blockers, and downstream work that is already half-written
  somewhere else.
- A retry is rarely "rerun the same command." It is a question about which artifacts to keep, which to throw away, and
  which agent or human to hand it to next.

You can do all of that with a single chat session and good notes. You _can_. It just doesn't compose. The state lives in
human memory, scattered tabs, and the local diff. The moment work spans multiple sessions, multiple people, or multiple
agents, the gaps in that state show up as repeated context-setting, re-reviewed diffs, and "wait, why did we do it that
way again?" That is the rigor problem SASE is trying to solve, and it is the part most agent demos quietly skip.

## The Day-Job Model Lag

The second half of the origin story is the constraint that made the first half urgent. At work I was — for legitimate
policy reasons — restricted to the in-house model. Gemini has improved a lot, and it will keep improving. I don't want
to take a shot at it here. But for some time now, and still as I'm writing this, the in-house model has trailed Claude
and (more recently) Codex on the kinds of agentic coding tasks I cared about most: multi-file refactors, long-horizon
debugging sessions, large-scale plan execution, and any workflow that needs the model to keep its own state straight
across many tool calls.

So the working setup was lopsided on purpose:

- The **production** target — the model I had to ship workflows against during the day — was the lagging one.
- The **research** target — the model I could experiment with on personal time and in personal projects — was whatever
  was state of the art that week. Claude was the early winner; Codex came up the curve more recently.

That mismatch sounds like a complaint. It turned out to be the most useful design pressure I had.

## The Asymmetry Was the Forcing Function

If you only build against today's strongest model, it is easy to convince yourself that the model _is_ the system.
Prompt it well enough and it will handle the planning, the dependencies, the review state, the retries. Demos look
great. Productionizing is painful, but the demos are great.

If you only build against a lagging model, it is easy to convince yourself that the workflow _is_ the system. You
overspecify every step, lock the agent into a rigid harness, and end up with a Rube Goldberg pipeline that survives
exactly until the next model release renders half of it unnecessary.

Having to support both, simultaneously, taught me a different lesson: **workflows are scaffolding around models, not
replacements for them.** The agentic system has to do real work — durable plans, dependency ordering, review records,
handoffs — but it has to do that work in a way that:

1. Stays useful when the model is weaker than you want, by absorbing the work the model can't reliably do yet.
2. Gets out of the way when the model gets stronger, by being cheap enough to discard the parts that have become dead
   weight.

The expensive thing is the model; the workflow should be the cheap thing. That ordering is easy to invert in practice,
and inverting it is how you end up with frameworks that are still around long after their reason to exist has gone.

## Low-Cost Workflows Cut Both Ways

Once "workflow as scaffolding" was the design center, two specific properties of a workflow started to matter much more
than I would have guessed up front.

**It has to be easy to spin up.** When today's model fails at something — fails to plan, fails to keep state, fails to
hand off cleanly — you want to surround it with just enough structure to get the work done, without writing an entire
framework first. An XPrompt fragment, a small workflow spec, a phase bead, a ChangeSpec. Each one should cost minutes,
not days, to introduce. If the smallest unit of "add structure" is large, you will simply not add it; you will go back
to a single chat session and accept the rework.

**It has to be easy to wind down.** When tomorrow's model catches up to the thing you scaffolded around, the scaffolding
becomes the choke point. The workflow that compensated for a model's short context window is the same workflow that
prevents the new long-context model from doing the work in one pass. If a workflow is expensive to remove — because too
much logic, review state, or muscle memory has accreted into it — you will keep paying for it long after it has stopped
earning its keep. SASE treats the ability to delete a workflow as a first-class property, not a luxury.

A useful way to read the rest of this series is through that lens. Each subsystem is trying to be small enough to
introduce in an afternoon and easy enough to peel back when the model on the other side of it gets better.

## What That Made SASE Look Like

Several of SASE's design choices fall out of those two pressures more or less directly:

- **Provider independence.** The same SASE workflow has to run against the lagging model at work and the
  state-of-the-art model at home. That means agent runtimes are interchangeable, commit workflows are uniform, and the
  durable objects are plans, beads, and ChangeSpecs — not provider-specific prompt formats.
- **Plans as artifacts.** A plan that lives only in a chat transcript is the workflow you can't wind down, because
  nobody else can see it. Tales, epics, and legends in [Spec-Driven Development](../../sdd.md) make the plan a file with
  frontmatter, links, and history.
- **Work units that survive the session.** [Beads](../../beads.md) are deliberately git-portable and issue-shaped so a
  weaker model can chip at a phase, a stronger model can pick up the next, and a human can take over either.
- **Review state outside the chat.** [ChangeSpecs](../../change_spec.md) record the CL/PR-sized truth so review doesn't
  depend on the model remembering it. When the model gets better, the ChangeSpec gets smaller. When the model gets
  worse, the ChangeSpec absorbs more of the load. Either way, the surface stays.
- **An orchestrator that's not the agent.** The [Axe daemon](../../axe.md) handles the long-tail supervision work —
  `%wait` checks, hook completion, mentor launches — so the agent itself can be replaced without rebuilding the
  background loop around it.

None of these were designed as bets on a particular model staying ahead or staying behind. They were designed for a
world where the model you can use _right now_ is rarely the model you wish you had, in either direction.

## Why I'm Writing This Down

The honest version of "why SASE exists" is that I needed to do real engineering work with the tools I had, against
codebases and review processes that didn't care about my model preferences. The structured version of "why SASE exists"
is the rest of this series.

If you have spent any time orchestrating coding agents inside a serious codebase, the rest of the posts will probably
feel like a description of problems you already know. That's the point. SASE is not a new theory of agentic software
engineering. It's the smallest coordination layer I could write that still survived the mismatch between a lagging
day-job model and the state-of-the-art model I built things with at night.

## Series Navigation

This is [00] in the [SASE Blog Series](../../series/agentic-software-engineering.md).

- Previous: none.
- Next: [\[01\] Why Coding Agents Need Orchestration](why-coding-agents-need-orchestration.md).
- Continue reading: [SASE Blog Series](../../series/agentic-software-engineering.md), [blog home](../index.md), or
  [ACE guide](../../ace.md).
