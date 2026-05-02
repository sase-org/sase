# Infographic Style Brief

This brief is the shared contract for the five documentation infographics planned in
`sdd/epics/202605/docs_gpt_image_infographics.md`. It confirms the target docs, insertion points, visual language, and
semantic guardrails for the image-generation phases.

## Shared Visual Contract

- Use a landscape architecture-infographic composition that reads well at GitHub Markdown width. Match the existing
  `docs/images/*-infographic.png` family: approximately 16:9, light background, crisp blocks, clear arrows, and limited
  short labels.
- Prefer a neutral base with distinct accent colors for different concept groups. Avoid a one-hue palette, decorative
  gradients, logos, fake terminal screenshots, and paragraph-length text inside the raster image.
- Keep labels deterministic and terminology-aligned with the target doc. If generated labels are misspelled, too small,
  or semantically wrong, preserve only the useful layout/artwork and add final labels in a local post-processing step.
- Each final image needs a sidecar prompt file next to the PNG. The sidecar should include the final prompt, target
  insertion point, intended alt text, and any post-processing notes.
- Embed images with relative Markdown links such as `![Useful alt text](images/name-infographic.png)`. The alt text
  should describe the model shown, not just repeat the filename.

## Confirmed Targets And Insertions

| Doc                        | Final image                                         | Confirmed insertion point                                                                      | Rationale                                                                                                                     |
| -------------------------- | --------------------------------------------------- | ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `docs/xprompt.md`          | `docs/images/xprompt-resolution-infographic.png`    | After the introductory "Use xprompts when you want to" list and before `## Table of Contents`. | Readers need the reference-resolution model before entering CLI and syntax reference sections.                                |
| `docs/workflow_spec.md`    | `docs/images/workflow-execution-infographic.png`    | After the opening paragraph and before `## Table of Contents`.                                 | The doc immediately becomes a format reference; the diagram should establish the execution model first.                       |
| `docs/commit_workflows.md` | `docs/images/commit-workflow-infographic.png`       | After the `## Overview` table and before `## How It Works`.                                    | The table defines the three outputs; the diagram should bridge from that summary into orchestration details.                  |
| `docs/beads.md`            | `docs/images/bead-epic-work-infographic.png`        | After the opening paragraph and before `## Table of Contents`.                                 | The data model, storage model, readiness, and epic execution flow need a single orientation map before command examples.      |
| `docs/rust_backend.md`     | `docs/images/rust-backend-boundary-infographic.png` | At the start of `## Architecture`, before the existing ASCII diagram.                          | The section already owns the Python facade and Rust extension boundary, and the image can summarize ownership before details. |

Do not edit these five target docs in phase 1. Later phases should insert only a minimal lead-in sentence when needed.

## Per-Doc Guardrails

### `docs/xprompt.md`

- Show a user prompt containing `#name`, `#!workflow`, directives, workspace references, and dynamic-memory triggers.
- Include the key resolution stages: protected/disabled-region masking, reference parsing, discovery order, aliases,
  typed input validation, Jinja2 rendering, dynamic memory, and multi-agent fan-out.
- Keep the distinction clear: `#name` expands inline-capable xprompts or workflows with `prompt_part`; `#!name` launches
  standalone workflows.
- Do not imply recursive multi-agent fan-out beyond the documented one-level behavior.

### `docs/workflow_spec.md`

- Show input parameters and environment feeding ordered steps, with outputs/artifacts flowing forward by named fields.
- Represent step types as `agent`, `prompt_part`, `bash`, `python`, `hidden`, and `parallel`.
- Make it explicit that `prompt_part` injects text into a containing prompt and is not a separate LLM call.
- Show control flow (`if`, `for`, `while`, `repeat/until`), parallel branches, join modes (`object`, `array`, `text`,
  `lastOf`), and HITL gates without suggesting unsupported nested parallel/loop/HITL combinations.

### `docs/commit_workflows.md`

- Show the shared path from `#commit`, `#propose`, or `#pr` through the stop hook, commit skill, `sase commit`, and
  `CommitWorkflow`.
- Keep the three dispatch outputs visually distinct: commit hash plus COMMITS entry, saved diff plus COMMITS entry, and
  PR URL plus ChangeSpec entry.
- Include bead lifecycle, plan handling, PR tags, parent detection, VCS dispatch, result marker, and tracking as
  orchestrator stages.
- Show conflict resume as a checkpoint/recover side loop, not as a normal success branch.
- Keep labels VCS-agnostic enough to cover Git, GitHub, and Mercurial provider implementations.

### `docs/beads.md`

- Separate the issue model from the execution flow: plan beads with tiers (`plan`, `epic`, `legend`), phase children,
  statuses, dependencies, ready/blocked states, and hierarchical IDs belong in one area; `sase bead work` belongs in
  another.
- Show SQLite as the local query/mutation cache and JSONL as the git-portable export, both owned by Rust-backed bead
  operations.
- Show multi-workspace merged reads separately from primary-workspace writes.
- For epic work, show Kahn waves, pre-claimed phase beads, one agent per phase, waits from dependency edges, and a final
  land agent waiting on leaf phases.
- Do not reproduce the full command table inside the image.

### `docs/rust_backend.md`

- Use a layered boundary model: top-level `sase` Python UI/CLI/TUI/workflow host logic, `sase.core` Python facade and
  wire records, required `sase_core_rs` PyO3 extension, and sibling `../sase-core` Rust workspace.
- Distinguish Rust-owned operation groups from Python-owned host responsibilities. Rust owns data/query/planning cores;
  Python owns file-path APIs, VCS/workspace plugins, xprompt resolution, user prompts, process orchestration, TUI
  rendering, and side-effecting transitions.
- Include `sase core health`, golden fixtures, and focused Python/Rust tests as a secondary contract loop.
- Do not imply a pure-Python fallback or optional Rust backend for ported operations.
