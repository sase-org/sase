---
pdf: false
---

# Infographic Style Brief

This brief records the shared contract for five documentation infographics produced from
`sdd/epics/202605/docs_gpt_image_infographics.md`. Use it when auditing, regenerating,
or post-processing the images so their sidecar prompts, target docs, insertion points,
visual language, and semantic guardrails stay aligned.

## Shared Visual Contract

- Use a landscape architecture-infographic composition that reads well at GitHub
  Markdown width. Match the current `docs/images/*-infographic.png` family: 16:9 PNGs,
  light background, crisp blocks, clear arrows, and limited short labels.
- Prefer a neutral base with distinct accent colors for different concept groups. Avoid
  a one-hue palette, decorative gradients, logos, fake terminal screenshots, and
  paragraph-length text inside the raster image.
- Keep labels deterministic and terminology-aligned with the target doc. If regenerated
  labels are misspelled, too small, or semantically wrong, preserve only the useful
  layout/artwork and add final labels in a local post-processing step.
- Each final image has a sidecar prompt file next to the PNG. The sidecar should include
  the final prompt, target insertion point, intended alt text, and any post-processing
  notes; update it whenever the image is regenerated or relabeled.
- Embed images with relative Markdown links such as
  `![Useful alt text](images/name-infographic.png)`. The alt text should describe the
  model shown, not just repeat the filename.

## Targets And Insertions

| Doc                        | Final image                                         | Insertion point / status                                                                                | Rationale                                                                                                                     |
| -------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `docs/xprompt.md`          | `docs/images/xprompt-resolution-infographic.png`    | Embedded after the introductory use-case list and before the authoritative text pipeline.               | Readers need the reference-resolution model before entering CLI and syntax reference sections.                                |
| `docs/workflow_spec.md`    | `docs/images/workflow-execution-infographic.png`    | After the opening paragraph and before `## Table of Contents`.                                          | The doc immediately becomes a format reference; the diagram should establish the execution model first.                       |
| `docs/commit_workflows.md` | `docs/images/commit-workflow-infographic.png`       | Candidate insertion after the `## Overview` table and before `## How It Works`; currently not embedded. | The table defines the three outputs; the diagram should bridge from that summary into orchestration details once regenerated. |
| `docs/beads.md`            | `docs/images/bead-epic-work-infographic.png`        | Retired; retained as a historical asset but no longer embedded.                                         | The image predates task beads and the task-only `ready` status, so it no longer represents the current model.                 |
| `docs/rust_backend.md`     | `docs/images/rust-backend-boundary-infographic.png` | At the start of `## Architecture`, before the existing ASCII diagram.                                   | The section already owns the Python facade and Rust extension boundary, and the image can summarize ownership before details. |

Active sidecar prompts and target doc embeds match the insertion points above except for
the commit-workflow infographic, whose stale PNG and prompt remain but are intentionally
not embedded. The retired bead PNG is retained without its obsolete prompt/critique
sidecars and is also not embedded. The four 1672x941 images and the 1600x900
Rust-backend image are all 16:9 PNGs.

## Per-Doc Guardrails

### `docs/xprompt.md`

- Show a user prompt containing `#name`, `#!workflow`, directives, and workspace
  references.
- Include the key resolution stages: protected/disabled-region masking, reference
  parsing, discovery order, aliases, typed input validation, Jinja2 rendering, and
  multi-agent fan-out.
- Keep the distinction clear: `#name` expands inline-capable xprompts or workflows with
  `prompt_part`; `#!name` launches standalone workflows.
- Do not imply a strict one-level fan-out rule; multi-agent fan-out is bounded by the
  documented recursion depth cap.

### `docs/workflow_spec.md`

- Show input parameters and environment feeding ordered steps, with outputs/artifacts
  flowing forward by named fields.
- Represent step types as `agent`, `prompt_part`, `bash`, `python`, `hidden`, and
  `parallel`.
- Make it explicit that `prompt_part` injects text into a containing prompt and is not a
  separate LLM call.
- Show control flow (`if`, `for`, `while`, `repeat/until`), parallel branches, join
  modes (`object`, `array`, `text`, `lastOf`), and HITL gates without suggesting
  unsupported nested parallel/loop/HITL combinations.

### `docs/commit_workflows.md`

- Show the shared path from `#commit`, `#propose`, or `#pr` through the provider-neutral
  commit finalizer, commit skill, `sase stitch create`, and `CommitWorkflow`.
- Keep the three dispatch outputs visually distinct: commit hash plus STITCHES entry,
  saved diff plus STITCHES entry, and PR URL plus Patch entry.
- Include bead lifecycle, plan handling, PR tags, parent detection, VCS dispatch, result
  marker, and tracking as orchestrator stages.
- Show conflict resume as a checkpoint/recover side loop, not as a normal success
  branch.
- Keep labels VCS-agnostic enough to cover Git, GitHub, and Mercurial provider
  implementations.

### `docs/beads.md`

- Do not re-embed the historical image without regenerating it for plan, phase, and
  standalone task beads.
- Separate the issue model from the execution flow: plan beads with tiers (`plan`,
  `epic`), phase children, standalone tasks, statuses, dependencies, ready/blocked
  states, and hierarchical IDs belong in one area; `sase bead work` belongs in another.
- Show `events/**` as the git-portable source of truth, `issues.jsonl` as a
  compatibility projection, and `beads.db` as the local compatibility cache, all owned
  by Rust-backed bead operations.
- Show the current checkout's in-tree `sdd/beads/` event store as the source of truth
  for in-tree SDD.
- For epic work, show Kahn waves, pre-claimed phase beads, one agent per phase, waits
  from dependency edges, and a final land agent waiting on every phase agent.
- For standalone tasks, show the `open` → `ready` → `in_progress` → `closed` lifecycle,
  dependency-filtered `sase bead ready` output, AXE triage gates, and direct
  `sase bead work` launch.
- Do not reproduce the full command table inside the image.

### `docs/rust_backend.md`

- Use a layered boundary model: top-level `sase` Python UI/CLI/TUI/workflow host logic,
  `sase.core` Python facade and wire records, required `sase_core_rs` PyO3 extension,
  and sibling `../sase-core` Rust workspace.
- Distinguish Rust-owned operation groups from Python-owned host responsibilities. Rust
  owns data/query/planning cores; Python owns file-path APIs, VCS/workspace plugins,
  xprompt resolution, user prompts, process orchestration, TUI rendering, and
  side-effecting transitions.
- Include `sase core health`, golden fixtures, and focused Python/Rust tests as a
  secondary contract loop.
- Do not imply a pure-Python fallback or optional Rust backend for ported operations.
