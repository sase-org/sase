---
web: true
description:
  Architectural decision records — accepted choices, their rejected alternatives, and
  what would reopen them.
roster: list
roster_label: DECISIONS
strand_noun: decision
---

# Decisions

A decision record is not a design doc or a subsystem overview — those go stale as the
code changes underneath them. A record is immutable once accepted: if the project
changes course, a new record is written and the old one is marked superseded with a
`metadata.status` plus `superseded_by` mark and a `[[...]]` back-link, never edited in
place. Read one on demand with `sase memory read decisions:<keyword> -r "<why>"`; each
record states the claim, why it was chosen over the credible alternatives, what it
costs, and the condition that would reopen it.

<!-- sase:strands -->

1. **A Gate Never Blocks An Agent** (`gates-never-block`)
   - Creating a gate from inside an agent ends that agent's turn; continuation is a gate
     shell's follow-up, never a wait.
2. **Adapters Normalize Harnesses** (`adapters-normalize-harnesses`)
   - Each provider adapter makes its CLI harness conform to the single-turn contract
     instead of the host modeling private wait semantics.
3. **Agents Are Single-Turn** (`single-turn-agents`)
   - A SASE agent run is one provider turn; continuation is always mechanical, never a
     promise to resume.
4. **Agents-Sync Is Publish-Only, The Import Leg Is Deleted**
   (`agents-sync-publish-only`) - Epic sase-ws deleted the entire agents-sync import leg
   (v1, v2, and the ACE incomplete-import UI); the module only publishes agent
   prompts/pages outward now, and one explicit purge command is the sole supported
   operation on leftover imported local state.
5. **Check-Full Is Explicit-Only** (`check-full-is-explicit`)
   - just check is the only agent-initiated verification recipe; just check-full runs
     only when explicitly instructed, typically to repair a CI failure.
6. **CI Is Two-Speed** (`ci-two-speed-split`)
   - Master pushes run a per-SHA fast gate, while the exhaustive CI matrix runs off the
     push path on a schedule and remains a release prerequisite through ci_watch
     freshness checks.
7. **Completion Is Host-Owned** (`host-owned-completion`)
   - An agent never creates commits, branches, or PRs; it submits a declaration and
     host-owned finalizers act.
8. **Expensive Commands Are Recorded Before They Are Admitted** (`record-before-admit`)
   - _[partly superseded by `guarded-recipes`, `explicit-handoff-fails-closed`]_ The
     sase tool control plane lands its ToolRun record first; prediction and admission
     only ever consume a corpus that already exists.
9. **Explicit Handoff Fails Closed** (`explicit-handoff-fails-closed`)
   - Explicit sase tool run -H fails closed when its ToolRun reservation cannot commit;
     foreground and monitor-start recording stay fail-open.
10. **Guarded Recipes Refuse Raw Agent Runs** (`guarded-recipes`)
    - A SASE agent runs a guarded recipe only inside sase tool run for that project
      root, or with an explicit bypass; the guard refuses anything else.
11. **Legacy V1 Agent Transport Is Read-Only History, Not An Import Source**
    (`v1-import-retired`) - _[superseded by `agents-sync-publish-only`]_ The legacy v1
    agents-sync import leg is sunset behind v1_import_retired; v1 payloads stay readable
    as v2-adoption matcher evidence but are never materialized as new imported
    artifacts.
12. **Machine Artifact-Link Writes Stay Off the Primary**
    (`machine-link-writes-off-primary`) - Machine artifact-link mutations never target
    the sidecar clones nested under a project's primary checkout; the machine write lane
    is the hidden host-owned clone, and the primary converges only through pull-based
    auto-sync.
13. **Memory Links Are Authored** (`memory-links-are-authored`)
    - A memory file declares how its links are detected and rendered, and authors links
      inline as `[[target]]` / `![[target]]`.
14. **Memory Webs** (`memory-webs`)
    - _[partly superseded by `webs-render-in-their-own-section`,
      `memory-links-are-authored`]_ A keyed memory collection is a flat descriptor note
      plus a sibling strand directory, addressed web:keyword.
15. **Memory Webs Render In Their Own Section** (`webs-render-in-their-own-section`)
    - A memory web's placement in generated agent instructions follows from its kind,
      not from a `type:` declaration on its descriptor.
16. **No Retrieval Mechanism Before Its Corpus** (`corpus-before-mechanism`)
    - SASE does not build memory retrieval or linking machinery ahead of a corpus that
      demonstrably needs it.
17. **Size Aliases Descend The Effort Ladder** (`size-alias-effort-ladder`)
    - Built-in size aliases run a model at xhigh on its first appearance from @xlarge
      down and one rung lower on each reappearance; every alias should span more than
      one provider.
18. **The Rust Core Is Required** (`rust-core-required`)
    - Shared backend behavior lives in sase-core with no Python fallback and no env-var
      backend switch.
19. **Triage Annotates; It Never Changes an Exit Code**
    (`triage-annotates-does-not-change-exit-codes`) - KNOWN needs an independent
    witness; triage classifies failure evidence without changing command outcomes.
20. **Verification Is Two-Speed** (`two-speed-verification`)
    - _[superseded by `check-full-is-explicit`]_ just check is the agent default and
      just check-full gates landing, because host capacity is the constraint, not test
      speed.

<!-- /sase:strands -->
