---
type: core
parent: AGENTS.md
web: true
description:
  Architectural decision records — accepted choices, their rejected alternatives, and
  what would reopen them.
roster: list
roster_label: DECISIONS
strand_noun: decision
closure: none
---

# Decisions

A decision record is not a design doc or a subsystem overview — those go stale as the
code changes underneath them. A record is immutable once accepted: if the project
changes course, a new record is written and the old one is marked superseded in prose,
never edited in place. Read one on demand with
`sase memory read decisions:<keyword> -r "<why>"`; each record states the claim, why it
was chosen over the credible alternatives, what it costs, and the condition that would
reopen it.

<!-- sase:strands -->

- **A Gate Never Blocks An Agent** (`gates-never-block`) - Creating a gate from inside
  an agent ends that agent's turn; continuation is a gate shell's follow-up, never a
  wait.
- **Agents Are Single-Turn** (`single-turn-agents`) - A SASE agent run is one provider
  turn; continuation is always mechanical, never a promise to resume.
- **Completion Is Host-Owned** (`host-owned-completion`) - An agent never creates
  commits, branches, or PRs; it submits a declaration and host-owned finalizers act.
- **Memory Webs** (`memory-webs`) - A keyed memory collection is a flat descriptor note
  plus a sibling strand directory, addressed web:keyword.
- **No Retrieval Mechanism Before Its Corpus** (`corpus-before-mechanism`) - SASE does
  not build memory retrieval or linking machinery ahead of a corpus that demonstrably
  needs it.
- **The Rust Core Is Required** (`rust-core-required`) - Shared backend behavior lives
  in sase-core with no Python fallback and no env-var backend switch.
- **Verification Is Two-Speed** (`two-speed-verification`) - just check is the agent
  default and just check-full gates landing, because host capacity is the constraint,
  not test speed.

<!-- /sase:strands -->
