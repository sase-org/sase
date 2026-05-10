---
create_time: 2026-05-10
status: done
tier: epic
---

# Plan: Review Existing Diagrams for Clarity and Accuracy

## Goal

Audit every committed diagram under `docs/images/` (excluding the README hero `sase_overview.png` and the two paper covers `pdl_paper.png`, `sase_paper.png`) for:

1. **Clarity** — would a new user understand what this diagram is showing?
2. **Accuracy** — does this faithfully reflect how the code actually works today?

Each diagram gets a two-phase pipeline: a **critique phase** that produces a written review, and a **generation phase** that uses GPT image generation, taking the critique as input, to produce a revised diagram. The two phases run in distinct agents so the model best suited for each task can own its phase.

## Diagrams in Scope

| # | Image | Where it appears |
|---|---|---|
| 1 | `docs/images/bead-epic-work-infographic.png` | `docs/beads.md` |
| 2 | `docs/images/commit-workflow-infographic.png` | `docs/commit_workflows.md` |
| 3 | `docs/images/rust-backend-boundary-infographic.png` | `docs/rust_backend.md` |
| 4 | `docs/images/sase-component-communication.png` | `docs/architecture.md` / `docs/index.md` |
| 5 | `docs/images/sase-rust-core-integration.png` | `docs/architecture.md` / `docs/index.md` |
| 6 | `docs/images/sase-telegram-integration.png` | `docs/architecture.md` / `docs/index.md` |
| 7 | `docs/images/sase_tui_tabs_infographic.png` | `docs/index.md` |
| 8 | `docs/images/workflow-execution-infographic.png` | `docs/workflow_spec.md` |
| 9 | `docs/images/xprompt-resolution-infographic.png` | `docs/xprompt.md` |
| 10 | `docs/images/zorg-zettel-vision-infographic.png` | `docs/index.md` / blog/series |

Out of scope: `docs/images/sase_overview.png` (README hero — confirmed good), `docs/images/pdl_paper.png`, `docs/images/sase_paper.png` (paper covers, not diagrams).

## Phase Pattern

For each diagram `<D>` we create two phase beads:

### Critique phase — `<D> critique` (model: `claude/opus`)

- Open the PNG and inspect it.
- If a `<D>.prompt.md` sidecar exists, read it for the original intent. If not, infer intent from the doc that embeds the image.
- Read the sections of the embedding doc(s) and any code paths the diagram refers to (xprompt resolver, workflow runner, commit workflow, bead work fan-out, Rust core boundary, etc.) to validate accuracy claims against current code, not against the original prompt.
- Produce a written critique covering: clarity issues a new user would hit; specific accuracy errors (wrong arrows, wrong labels, missing or stale concepts, terminology drift); concrete suggested changes for the regenerated image.
- Write the critique to `docs/images/<D>.critique.md` so the next phase can pick it up.
- Do **not** modify the PNG, the prompt sidecar, or the embedding doc in this phase.

### Generation phase — `<D> regen` (model: `codex/gpt-5.5`)

- Read `docs/images/<D>.critique.md` from the critique phase.
- Read the existing `<D>.prompt.md` if present, otherwise the relevant doc sections, to ground the regenerated prompt.
- Use GPT image generation to produce a revised PNG that addresses the critique.
- Overwrite `docs/images/<D>.png` with the new image.
- Update or create `docs/images/<D>.prompt.md` to reflect the new prompt and any post-processing.
- Do **not** alter unrelated diagrams or docs.

The critique file is a hand-off artifact between the two agents and is intentionally checked in alongside the image so future regenerations have a starting point.

## Concurrency Cap

We never want more than **6** of these agents running at once. With 20 phase beads, that requires deliberately staggered dependencies in addition to the workflow ordering (each `regen` waits on its `critique`).

The dependency graph is built two ways:

1. **Workflow edges** — for every diagram `i`, `regen_i` depends on `critique_i`.
2. **Concurrency-rail edges** — order the 20 beads in a queue (`critique_1..10`, then `regen_1..10`) and add an edge `bead_N -> bead_{N-6}` for every `N > 6`. This guarantees that at any moment, the active set is contained within a sliding window of 6 positions on the queue, so at most 6 are runnable simultaneously.

Concrete edges (`A -> B` means A is blocked by B):

Workflow edges (10):
- `regen_1 -> critique_1`
- `regen_2 -> critique_2`
- ... through `regen_10 -> critique_10`

Concurrency-rail edges (14):
- `critique_7 -> critique_1`
- `critique_8 -> critique_2`
- `critique_9 -> critique_3`
- `critique_10 -> critique_4`
- `regen_1 -> critique_5`
- `regen_2 -> critique_6`
- `regen_3 -> critique_7`
- `regen_4 -> critique_8`
- `regen_5 -> critique_9`
- `regen_6 -> critique_10`
- `regen_7 -> regen_1`
- `regen_8 -> regen_2`
- `regen_9 -> regen_3`
- `regen_10 -> regen_4`

Initial ready set: `critique_1..6` (six beads). Whenever one bead in the active window closes, exactly one new bead becomes unblocked, keeping the live count ≤ 6.

## Verification (per phase)

Every phase agent should, before closing its bead, confirm:

- Critique phase: `docs/images/<D>.critique.md` exists, references the diagram by filename, and contains both clarity and accuracy sections.
- Generation phase: `docs/images/<D>.png` is a valid PNG, the new `<D>.prompt.md` exists and matches the committed image, and the embedding doc still renders the image correctly (no broken Markdown link).

After all phases close, the land agent should run `just install && just check` per repo convention, and confirm that `rg -n "images/.*\\.png" docs/` still resolves to existing files.

## Risks and Mitigations

- **Stale critiques** — code changes between critique and regen could invalidate the critique. Mitigation: the regen phase is the next bead in the queue and starts as soon as its critique closes; we do not let critiques pile up.
- **Visual drift across diagrams** — independent regen agents could produce inconsistent styles. Mitigation: each regen prompt should explicitly reference `docs/images/infographic-style-brief.md` where relevant.
- **Generation flakiness** — GPT image runs can produce broken text. Mitigation: regen phases should inspect output and fall back to layout-only generation plus deterministic labels when raster text is unreadable, matching the policy in `docs_gpt_image_infographics.md`.
- **Scope creep** — agents may be tempted to rewrite surrounding doc prose. Out of scope; only the PNG, its sidecar, and (if needed) the critique file are in scope per phase.
