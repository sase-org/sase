---
create_time: 2026-05-09 15:06:16
status: done
---
# Plan: Docs Markdown Accuracy And New-User Clarity Epic

## Goal

Create an executable epic bead that audits and improves every Markdown file under `docs/`, with one phase bead per file.
Each phase should be small enough for a distinct agent to own end to end: read the assigned document, verify it against
the current repository behavior where practical, improve clarity for new users, and leave the docs buildable.

This plan intentionally treats every `docs/**/*.md` file as in scope, including image prompt sidecars, blog pages, and
series pages. The prompt sidecars are documentation artifacts for future maintainers, so they should be checked for
accuracy, clarity, and consistency just like user-facing pages.

## Current Inventory

The repo currently has 33 Markdown files under `docs/`:

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

Note: the inventory command returned 34 paths despite the initial count assumption of 33. The epic should create one
phase for each path listed above.

## Shared Phase Instructions

Every per-file agent should:

- Work only on its assigned Markdown file unless a broken link or factual correction requires a tightly scoped companion
  edit; if that happens, mention it in the phase notes.
- Check the file against nearby code, CLI help, config, existing docs, and SDD material as needed. Do not invent
  behavior.
- Optimize for new-user comprehension: define terms before using them, prefer task-oriented examples, remove stale
  claims, clarify prerequisites, and keep command snippets copy-pasteable.
- Preserve existing stable URLs, headings, image asset paths, and cross-links unless they are demonstrably wrong.
- For prompt sidecars under `docs/images/`, verify that the prompt, intended alt text, target doc section, and
  post-processing notes still match the current image/documentation state.
- Run `just docs-check` after changing the assigned file. Run `just check` too if the phase edits anything outside docs
  or touches behavior/tests. Because this workspace may be stale, run `just install` before checks if dependencies are
  not already installed.
- Leave concise notes on what was verified and any remaining uncertainty.

## Concurrency Design

Use three dependency lanes. Each lane is a linear chain, and each phase in a lane depends on the previous phase in the
same lane. With three chains, `sase bead work <epic>` should have at most three ready phase beads at any point:

- Lane A starts with `docs/ace.md`.
- Lane B starts with `docs/agent_images.md`.
- Lane C starts with `docs/axe.md`.

Then the remaining files are assigned round-robin across the three lanes. This avoids a large first wave and keeps the
automation from launching more than three document agents concurrently.

## Phase Bead Layout

Create these phase beads under the epic, in this order. The title pattern should be `Docs audit: <path>`.

| #   | Lane | Markdown file                                             | Depends on |
| --- | ---- | --------------------------------------------------------- | ---------- |
| 1   | A    | `docs/ace.md`                                             | none       |
| 2   | B    | `docs/agent_images.md`                                    | none       |
| 3   | C    | `docs/axe.md`                                             | none       |
| 4   | A    | `docs/beads.md`                                           | phase 1    |
| 5   | B    | `docs/blog/index.md`                                      | phase 2    |
| 6   | C    | `docs/blog/posts/why-coding-agents-need-orchestration.md` | phase 3    |
| 7   | A    | `docs/change_spec.md`                                     | phase 4    |
| 8   | B    | `docs/commit_workflows.md`                                | phase 5    |
| 9   | C    | `docs/configuration.md`                                   | phase 6    |
| 10  | A    | `docs/images/bead-epic-work-infographic.prompt.md`        | phase 7    |
| 11  | B    | `docs/images/commit-workflow-infographic.prompt.md`       | phase 8    |
| 12  | C    | `docs/images/infographic-style-brief.md`                  | phase 9    |
| 13  | A    | `docs/images/rust-backend-boundary-infographic.prompt.md` | phase 10   |
| 14  | B    | `docs/images/workflow-execution-infographic.prompt.md`    | phase 11   |
| 15  | C    | `docs/images/xprompt-resolution-infographic.prompt.md`    | phase 12   |
| 16  | A    | `docs/index.md`                                           | phase 13   |
| 17  | B    | `docs/integrations.md`                                    | phase 14   |
| 18  | C    | `docs/llms.md`                                            | phase 15   |
| 19  | A    | `docs/mentors.md`                                         | phase 16   |
| 20  | B    | `docs/mobile_gateway.md`                                  | phase 17   |
| 21  | C    | `docs/mobile_mvp_runbook.md`                              | phase 18   |
| 22  | A    | `docs/notifications.md`                                   | phase 19   |
| 23  | B    | `docs/perf_runbook.md`                                    | phase 20   |
| 24  | C    | `docs/plugins.md`                                         | phase 21   |
| 25  | A    | `docs/project_spec.md`                                    | phase 22   |
| 26  | B    | `docs/query_language.md`                                  | phase 23   |
| 27  | C    | `docs/rust_backend.md`                                    | phase 24   |
| 28  | A    | `docs/sdd.md`                                             | phase 25   |
| 29  | B    | `docs/series/agentic-software-engineering.md`             | phase 26   |
| 30  | C    | `docs/telemetry.md`                                       | phase 27   |
| 31  | A    | `docs/vcs.md`                                             | phase 28   |
| 32  | B    | `docs/workflow_spec.md`                                   | phase 29   |
| 33  | C    | `docs/workspace.md`                                       | phase 30   |
| 34  | A    | `docs/xprompt.md`                                         | phase 31   |

The final land agent should wait for the leaf phases in all three lanes: phases 32, 33, and 34. Its job is to run a
final docs-wide coherence pass, inspect `git diff`, run `just docs-check`, and report cross-file inconsistencies that
need a follow-up bead rather than making broad unplanned rewrites.

## Epic Creation Steps

1. Add an epic plan file at `sdd/epics/202605/docs_markdown_accuracy_and_clarity.md` using this plan as the design
   source.
2. Create an epic bead:
   `sase bead create --title "Audit all docs Markdown for accuracy and clarity" --type plan(sdd/epics/202605/docs_markdown_accuracy_and_clarity.md) --tier epic`
3. Create the 34 phase beads with descriptions that name the assigned file and include the shared phase instructions.
4. Add dependencies to form the three lane chains listed above.
5. Verify the resulting schedule with `sase bead show <epic-id>` and, if available,
   `sase bead work <epic-id> --dry-run`. The dry run should show no wave wider than three phase agents.

## Acceptance Criteria

- There is one open phase bead for every `docs/**/*.md` file and no extra per-file phase beads.
- The phase descriptions are specific enough for agents to work independently without re-reading this planning file.
- Dependency chains allow exactly three initial ready doc-audit phase beads and never more than three phase agents in
  any Kahn wave.
- The epic design file records the scope, shared instructions, phase layout, and concurrency rationale.
- Only bead/design planning files are changed while setting up the epic; no documentation content is edited during
  setup.
