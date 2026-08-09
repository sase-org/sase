---
pdf: false
---

# Commit Workflow Infographic Prompt

## Target

- Doc: `docs/commit_workflows.md`
- Candidate insertion point: after the `## Overview` workflow table and before
  `## How It Works`
- Candidate image: `docs/images/commit-workflow-infographic.png`
- Alt text: "Shared commit workflow showing xprompt inputs flowing through the commit
  finalizer, commit skill, CommitWorkflow stages, VCS dispatch outputs, and conflict
  resume checkpoint"

## Final GPT Image Prompt

Use case: infographic-diagram

Asset type: GitHub Markdown documentation infographic for docs/commit_workflows.md

Primary request: Create a clean 16:9 architecture infographic foundation showing the
shared Sase commit/propose/pull-request workflow. Use a light neutral background, crisp
blocks, clear arrows, a restrained palette with distinct accents, and large empty label
zones. This is documentation art, not marketing art.

Exact visible labels to include, spelled exactly:

- Title: Shared Commit Workflow
- Left inputs: #commit, #propose, #pr
- Main path blocks: Agent changes, Commit finalizer, Commit skill, sase commit,
  CommitWorkflow
- CommitWorkflow stage labels inside the central orchestration band: Bead lifecycle,
  Plan handling, Before hook, PR tags, Parent detection, Diff capture, Checkpoint, VCS
  dispatch, After hook, Result marker, Tracking
- Right output branches: Commit hash + STITCHES entry, Saved diff + STITCHES entry, PR
  URL + Patch
- Side loop label: Conflict checkpoint + resume
- Provider note label: VCS providers: Git, GitHub, Mercurial

Composition: left-to-right flow. Put the three input xprompts in a compact stack on the
left feeding Agent changes. Then Commit finalizer and Commit skill feed into
`sase commit` and a large central CommitWorkflow band. Inside the band, reserve room for
eleven ordered stage chips. Put bead lifecycle and plan handling before the before hook:
the workflow closes/syncs beads and stages plan files before it runs
`commit_hooks.before`. Mark bead lifecycle and plan handling as skipped for `#propose`;
mark PR tags and parent detection as PR-only. Put the after hook immediately after VCS
dispatch, mark it commit/PR-only, and note that it runs after push. From VCS dispatch,
split into three clearly distinct output branches on the right. Add a curved
warning-accent conflict/resume loop that leaves VCS dispatch on conflict and returns
through the Checkpoint/VCS dispatch area after manual resolution; do not present it as a
normal success branch. Add the provider note near the dispatch area.

Avoid: logos, fake terminal screenshots, code blocks, dense paragraphs, tiny text,
decorative gradients, dark background, one-hue palette, misspelled labels, extra made-up
product names, watermarks.

For reliable text, generate a mostly text-free visual foundation first, then add the
exact labels locally as a raster overlay. Keep the final stage order numbered
left-to-right and top-to-bottom:

1. Bead lifecycle
2. Plan handling
3. Before hook
4. PR tags
5. Parent detection
6. Diff capture
7. Checkpoint
8. VCS dispatch
9. After hook
10. Result marker
11. Tracking

## Current Status

The checked-in PNG is stale and is not currently embedded in `docs/commit_workflows.md`.
It still labels the provider-neutral finalizer as `Stop hook`. Regenerate or locally
relabel the image before re-embedding it.

## Required Post-Processing Notes

The target PNG size is 1672x941. Regenerate with GPT image generation as a mostly
text-free architecture foundation, then post-process locally with exact labels and
readable stage chips. The overlay should fix the prior critique items by:

- labeling the left stack as `xprompts`;
- ordering the central stages as bead lifecycle, plan handling, before hook, PR tags,
  parent detection, diff capture, checkpoint, VCS dispatch, after hook, result marker,
  tracking;
- marking bead lifecycle and plan handling as skipped for `#propose`;
- marking PR tags and parent detection as PR-only;
- marking the after hook as commit/PR-only and post-push;
- anchoring the conflict resume path around Checkpoint and VCS dispatch; and
- keeping the three output branches and VCS provider note visible on the right.
