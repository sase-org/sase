---
create_time: 2026-05-09
status: done
tier: epic
---

# Plan: Docs Markdown Accuracy And New-User Clarity Epic

## Goal

Audit and improve every Markdown file under `docs/` for accuracy, current behavior, and new-user clarity. This epic is
executable: one phase bead owns one Markdown file end to end, while a final land agent performs a docs-wide coherence
pass after the three dependency lanes finish.

The setup phase intentionally does not edit documentation content. It creates the epic bead, one phase bead per
`docs/**/*.md` file, and dependencies that bound `sase bead work <epic-id>` to at most three concurrent document agents.

## Scope

The current inventory has 34 Markdown files:

1. `docs/ace.md`
2. `docs/agent_images.md`
3. `docs/axe.md`
4. `docs/beads.md`
5. `docs/blog/index.md`
6. `docs/blog/posts/why-coding-agents-need-orchestration.md`
7. `docs/change_spec.md`
8. `docs/commit_workflows.md`
9. `docs/configuration.md`
10. `docs/images/bead-epic-work-infographic.prompt.md`
11. `docs/images/commit-workflow-infographic.prompt.md`
12. `docs/images/infographic-style-brief.md`
13. `docs/images/rust-backend-boundary-infographic.prompt.md`
14. `docs/images/workflow-execution-infographic.prompt.md`
15. `docs/images/xprompt-resolution-infographic.prompt.md`
16. `docs/index.md`
17. `docs/integrations.md`
18. `docs/llms.md`
19. `docs/mentors.md`
20. `docs/mobile_gateway.md`
21. `docs/mobile_mvp_runbook.md`
22. `docs/notifications.md`
23. `docs/perf_runbook.md`
24. `docs/plugins.md`
25. `docs/project_spec.md`
26. `docs/query_language.md`
27. `docs/rust_backend.md`
28. `docs/sdd.md`
29. `docs/series/agentic-software-engineering.md`
30. `docs/telemetry.md`
31. `docs/vcs.md`
32. `docs/workflow_spec.md`
33. `docs/workspace.md`
34. `docs/xprompt.md`

Prompt sidecars under `docs/images/` are in scope because they are maintenance documentation. Agents should verify that
each prompt, target doc section, intended alt text, and post-processing note still matches the current image and docs.

## Shared Phase Instructions

Each phase agent must:

- Work only on the assigned Markdown file unless a broken link or factual correction requires a tightly scoped
  companion edit. Mention any companion edit in phase notes.
- Check the file against nearby code, CLI help, config, existing docs, and SDD material as needed. Do not invent
  behavior.
- Optimize for new-user comprehension: define terms before using them, prefer task-oriented examples, remove stale
  claims, clarify prerequisites, and keep command snippets copy-pasteable.
- Preserve stable URLs, headings, image asset paths, and cross-links unless they are demonstrably wrong.
- For prompt sidecars, verify the prompt, intended alt text, target doc section, and post-processing notes against the
  current image/documentation state.
- Run `just docs-check` after changing the assigned file. Run `just check` too if the phase edits anything outside docs
  or touches behavior/tests. If dependencies are stale, run `just install` first.
- Leave concise notes describing what was verified and any remaining uncertainty.

## Concurrency Design

Use three linear dependency lanes. Lane A starts with `docs/ace.md`, lane B starts with `docs/agent_images.md`, and lane
C starts with `docs/axe.md`. The remaining files are assigned round-robin across those lanes.

This gives exactly three initial ready phase beads and keeps every Kahn wave at three phase beads or fewer. The final
land agent produced by `sase bead work <epic-id>` should wait for the three leaf phases: phases 32, 33, and 34.

## Phase Layout

| # | Lane | Markdown file | Depends on |
| --- | --- | --- | --- |
| 1 | A | `docs/ace.md` | none |
| 2 | B | `docs/agent_images.md` | none |
| 3 | C | `docs/axe.md` | none |
| 4 | A | `docs/beads.md` | phase 1 |
| 5 | B | `docs/blog/index.md` | phase 2 |
| 6 | C | `docs/blog/posts/why-coding-agents-need-orchestration.md` | phase 3 |
| 7 | A | `docs/change_spec.md` | phase 4 |
| 8 | B | `docs/commit_workflows.md` | phase 5 |
| 9 | C | `docs/configuration.md` | phase 6 |
| 10 | A | `docs/images/bead-epic-work-infographic.prompt.md` | phase 7 |
| 11 | B | `docs/images/commit-workflow-infographic.prompt.md` | phase 8 |
| 12 | C | `docs/images/infographic-style-brief.md` | phase 9 |
| 13 | A | `docs/images/rust-backend-boundary-infographic.prompt.md` | phase 10 |
| 14 | B | `docs/images/workflow-execution-infographic.prompt.md` | phase 11 |
| 15 | C | `docs/images/xprompt-resolution-infographic.prompt.md` | phase 12 |
| 16 | A | `docs/index.md` | phase 13 |
| 17 | B | `docs/integrations.md` | phase 14 |
| 18 | C | `docs/llms.md` | phase 15 |
| 19 | A | `docs/mentors.md` | phase 16 |
| 20 | B | `docs/mobile_gateway.md` | phase 17 |
| 21 | C | `docs/mobile_mvp_runbook.md` | phase 18 |
| 22 | A | `docs/notifications.md` | phase 19 |
| 23 | B | `docs/perf_runbook.md` | phase 20 |
| 24 | C | `docs/plugins.md` | phase 21 |
| 25 | A | `docs/project_spec.md` | phase 22 |
| 26 | B | `docs/query_language.md` | phase 23 |
| 27 | C | `docs/rust_backend.md` | phase 24 |
| 28 | A | `docs/sdd.md` | phase 25 |
| 29 | B | `docs/series/agentic-software-engineering.md` | phase 26 |
| 30 | C | `docs/telemetry.md` | phase 27 |
| 31 | A | `docs/vcs.md` | phase 28 |
| 32 | B | `docs/workflow_spec.md` | phase 29 |
| 33 | C | `docs/workspace.md` | phase 30 |
| 34 | A | `docs/xprompt.md` | phase 31 |

## Final Land Agent

After phases 32, 33, and 34 complete, the final land agent should:

- Run a docs-wide coherence pass.
- Inspect `git diff`.
- Run `just docs-check`.
- Report cross-file inconsistencies that need a follow-up bead instead of making broad unplanned rewrites.

## Acceptance Criteria

- One open phase bead exists for every `docs/**/*.md` file and no extra per-file phase beads exist.
- Phase descriptions name the assigned file and contain enough shared instructions for independent agents.
- Dependency chains allow exactly three initial ready doc-audit phase beads and no Kahn wave wider than three phases.
- This epic design records the scope, shared instructions, phase layout, and concurrency rationale.
- Setup changes are limited to bead/design planning files; no documentation content is edited during setup.
