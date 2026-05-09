# GAI Org Ideas for SASE

Date: 2026-05-09

## Research Question

Which older GAI product and workflow ideas in `/home/bryan/org` are still useful for SASE, and which should become the
next focused implementation candidates?

## Corpus and Method

The source pass searched `/home/bryan/org` for old GAI references with:

```bash
rg -il --hidden --glob '!**/.git/**' '(^|[^A-Za-z])gai([^A-Za-z]|$)|now_gai|gai_' /home/bryan/org
```

That search returned 463 files. Phase 1 grouped them into four buckets: core backlog/design notes, prompt and workflow
sources, dated execution history, and external/reference notes. Phase 2 split review across those buckets, and Phase 3
ranked ideas by product value for current SASE, evidence strength, implementation leverage, risk, and whether the idea
is implemented, partially implemented, obsolete, or still missing.

Residual top-level work and reference notes with incidental GAI mentions were used as context checks, not as a separate
recommendation bucket.

This note cites source paths for follow-up, but it does not quote private org content at length.

## Executive Summary

The strongest reusable ideas are not new broad product categories. They are reliability and observability gaps around
systems SASE already has: AXE, hooks, mentors, ChangeSpecs, beads, xprompt workflows, artifacts, and ACE.

The top recommendation is to make background execution durable and inspectable. Old GAI notes repeatedly circle around
hook output, mentor runs, process cleanup, proposal hooks, zombie runners, and evidence capture. SASE has the pieces, but
the product shape should become a queryable execution ledger where every background action has an owner, command, output
path, state, and final evidence.

The second strongest area is lifecycle hardening. The corpus supports tests and precondition checks for ChangeSpec,
bead, and VCS state transitions more than it supports another status-system rewrite. SASE should lock down invariants
around accept/revert/draft behavior, hook-output retention, parent/child ordering, and dependency waves.

The old workflow and blackboard ideas remain useful if translated into typed SASE artifacts. Workflow step outputs,
human stops, retry summaries, and handoff files should become structured artifacts with producer and consumer metadata
instead of implicit markdown conventions.

## Top Recommendations

### 1. Durable Execution Ledger for Hooks, Mentors, and Agents

Add a persisted run record for AXE hooks, mentors, and other background work. Each record should include run id, owner
ChangeSpec or bead, workspace, command, output path, start/end time, status, de-dupe key, and a short evidence summary.
ACE and CLI status views should read from the same record source.

Why now: this is the highest-leverage theme in the corpus and attaches directly to existing SASE infrastructure. Source
evidence includes `/home/bryan/org/prompts/gai_monitor.md`, `/home/bryan/org/prompts/gai_mentors.md`,
`/home/bryan/org/prompts/gai_loop.md`, `/home/bryan/org/2026/20260101_done.zo`, and
`/home/bryan/org/2026/20260120_done.zo`.

Expected product result: fewer silent background failures, easier debugging from ACE, and a clear audit trail for
automated review and quality gates.

### 2. Lifecycle Invariant Test Pack

Add focused tests around ChangeSpec status transitions, accept/reject/revert preconditions, hook-output path retention
after rename, bulk parent/child status ordering, and bead dependency wave behavior.

Why now: old notes ask for status simplification, WIP/Draft behavior, reverted visibility, hook retention, and safe
accept/revert behavior, but SASE now has enough structure to harden these flows instead of redesigning them. Source
evidence includes `/home/bryan/org/now_gai.zo`, `/home/bryan/org/gai_ideas.zo`,
`/home/bryan/org/prompts/gai_reverted.md`, `/home/bryan/org/2025/20251221_done.zo`,
`/home/bryan/org/2026/20260117_done.zo`, and `/home/bryan/org/2026/20260120_done.zo`.

Expected product result: fewer lifecycle regressions and clearer failure modes when automation touches shared state.

### 3. Typed Workflow Artifacts and Output Contracts

Define a small schema for workflow-produced artifacts: artifact kind, producer step, intended consumer step, status,
summary, and source files. Start with research-synthesis and test-failure workflows before broadening to every xprompt.

Why now: old workflow notes ask for output schemas, downstream step arguments, blackboards, file-based stop signals, and
planner/editor/researcher handoffs. SASE already has YAML xprompt workflows and explicit artifacts, so the right next
step is validation and visibility. Source evidence includes `/home/bryan/org/prompts/gai_xpl.md`,
`/home/bryan/org/prompts/gai_output_types.md`, `/home/bryan/org/chat/gai_fix_tests_prompt.md`, and
`/home/bryan/org/prompts/gai_super_fix_tests.md`.

Expected product result: better handoffs between agents, stronger reviewability, and less reliance on hidden chat
context.

### 4. ACE Run Evidence View

Make each selected agent or workflow entry expose raw prompt, rendered prompt, linked artifacts, touched files when
known, output paths, and jump targets such as ChangeSpecs or beads.

Why now: the corpus repeatedly values being able to see what ran, why it ran, what prompt it saw, what files it touched,
and how to revive or replay it. This is operational visibility, not visual polish. Source evidence includes
`/home/bryan/org/now_gai.zo`, `/home/bryan/org/text/gai_expand_agent_bug.txt`,
`/home/bryan/org/text/gai_hidden_bug_snapshot.txt`, and `/home/bryan/org/2026/20260117_done.zo`.

Expected product result: faster debugging loops, better trust in automation, and fewer disconnected artifacts.

### 5. Bounded Test-Failure Workflow Refresh

Refresh the old fix-tests design as a SASE artifact workflow. The planner should choose editor, researcher, or stop;
retries should preserve summaries; comparisons should report whether failures changed; and blind retry loops should be
treated as a bug.

Why now: the old notes are specific enough to be useful. They describe durable blackboards, output trimming, failure
comparison, and stop conditions rather than generic autonomous repair. Source evidence includes
`/home/bryan/org/chat/gai_fix_tests_prompt.md`, `/home/bryan/org/prompts/gai_super_fix_tests.md`,
`/home/bryan/org/prompts/gai_test_cmd.md`, `/home/bryan/org/now_gai.zo`, and
`/home/bryan/org/2026/20260120_done.zo`.

Expected product result: test automation that preserves context and helps humans intervene before loops waste time.

## Secondary Candidates

Jinja and named xprompt arguments are worth a narrow gap check. `/home/bryan/org/plans/gai_xprompt_jinja.md` is concrete
and implementable, but it should be compared against current SASE xprompt support before opening new work.

Proposal-first review flows remain valuable, especially dry-run mutation previews, proposal hook isolation,
artifact-backed accept/reject choices, and stale-runner cleanup. Evidence appears in
`/home/bryan/org/prompts/gai_accept.md`, `/home/bryan/org/prompts/gai_loop.md`, and
`/home/bryan/org/prompts/gai_history.md`. This should follow ledger and artifact work rather than become another broad
commit-workflow rewrite.

Context and memory work should stay focused on curation and retrieval. The Claude/context references support compact
indexes plus explicit source loading, not importing old org material into every SASE prompt. Evidence includes
`/home/bryan/org/claude_code_ref.zo`, `/home/bryan/org/lib/code/gai_claude_mds.pdf`, and related notes under
`/home/bryan/org/lib/chat`.

## Thematic Findings

### Agent Orchestration

The corpus supports multi-agent work when scopes are naturally partitioned and shared state is explicit. Beads,
ChangeSpecs, artifacts, and ledgers are better SASE primitives than hidden shared chat state. This aligns with the epic
itself: the source review succeeded because the work was split by source bucket and synthesized through a written
handoff.

### Lifecycle and VCS Automation

Older GAI notes contain many status and VCS requests, but their current value is as regression evidence. The product
direction should be invariant coverage, precondition clarity, and durable records for automation that mutates branches,
ChangeSpecs, or beads.

### Hooks, Mentors, and Quality Gates

Hooks and mentors are the strongest repeated cluster. The missing product layer is not "more reviewers"; it is reliable
execution state, output retention, deterministic de-dupe, stale-process cleanup, and evidence-oriented mentor results.

### Workflow Language

Typed outputs, blackboards, human stop states, and downstream step inputs are still useful ideas. They should be
implemented as SASE artifact contracts and workflow validation, not as a parallel workflow system.

### ACE and Agent History

ACE should make runs explainable. The recurring requests for prompt display, workflow expansion, file panels,
notification context, chats listing, revive, and jump targets all point to one product goal: the user should be able to
answer "what happened here?" from the agent row.

## Ideas Not Recommended Now

- A broad multi-agent orchestration rewrite. The evidence favors explicit shared state through existing SASE primitives.
- A full project file or ChangeSpec format migration. Stabilize invariants before revisiting storage formats.
- A large memory import from `/home/bryan/org`. Better source loading beats bigger default prompts.
- Generic "better test fixing." The useful slice is bounded failure triage with durable evidence and stop points.
- One-off old UI/keymap requests. Many are implemented, obsolete after the GAI-to-SASE migration, or too small to rank.

## Source Index

Core backlog and design sources:

- `/home/bryan/org/now_gai.zo`
- `/home/bryan/org/gai_ideas.zo`
- `/home/bryan/org/plans/gai_xprompt_jinja.md`
- `/home/bryan/org/text/gai_expand_agent_bug.txt`
- `/home/bryan/org/text/gai_hidden_bug_snapshot.txt`
- `/home/bryan/org/text/gai_split_syntax.txt`

Prompt and workflow sources:

- `/home/bryan/org/prompts/gai_xpl.md`
- `/home/bryan/org/prompts/gai_output_types.md`
- `/home/bryan/org/prompts/gai_monitor.md`
- `/home/bryan/org/prompts/gai_mentors.md`
- `/home/bryan/org/prompts/gai_loop.md`
- `/home/bryan/org/prompts/gai_accept.md`
- `/home/bryan/org/prompts/gai_history.md`
- `/home/bryan/org/prompts/gai_reverted.md`
- `/home/bryan/org/prompts/gai_super_fix_tests.md`
- `/home/bryan/org/prompts/gai_test_cmd.md`
- `/home/bryan/org/chat/gai_fix_tests_prompt.md`

Dated execution history:

- `/home/bryan/org/2025/20251221_done.zo`
- `/home/bryan/org/2026/20260101_done.zo`
- `/home/bryan/org/2026/20260117_done.zo`
- `/home/bryan/org/2026/20260120_done.zo`

External/reference sources:

- `/home/bryan/org/agent_ref.zo`
- `/home/bryan/org/claude_code_ref.zo`
- `/home/bryan/org/lib/docs/beads_faq.md`
- `/home/bryan/org/lib/code/gai_claude_mds.pdf`
- `/home/bryan/org/lib/chat`
