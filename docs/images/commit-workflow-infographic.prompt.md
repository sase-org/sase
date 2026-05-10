---
pdf: false
---

# Commit Workflow Infographic Prompt

## Target

- Doc: `docs/commit_workflows.md`
- Insertion point: after the `## Overview` workflow table and before `## How It Works`
- Final image: `docs/images/commit-workflow-infographic.png`
- Alt text: "Shared commit workflow showing xprompt inputs flowing through the stop hook, commit skill, CommitWorkflow
  stages, VCS dispatch outputs, and conflict resume checkpoint"

## Final GPT Image Prompt

Use case: infographic-diagram

Asset type: GitHub Markdown documentation infographic for docs/commit_workflows.md

Primary request: Create a clean 16:9 architecture infographic foundation showing the shared Sase
commit/propose/pull-request workflow. Use a light neutral background, crisp blocks, clear arrows, a restrained palette
with distinct accents, and large empty label zones. This is documentation art, not marketing art.

Exact visible labels to include, spelled exactly:

- Title: Shared Commit Workflow
- Left inputs: #commit, #propose, #pr
- Main path blocks: Agent changes, Stop hook, Commit skill, sase commit, CommitWorkflow
- CommitWorkflow stage labels inside the central orchestration band: Bead lifecycle, Plan handling, Precommit, PR tags,
  Parent detection, Diff capture, Checkpoint, VCS dispatch, Result marker, Tracking
- Right output branches: Commit hash + COMMITS entry, Saved diff + COMMITS entry, PR URL + ChangeSpec
- Side loop label: Conflict checkpoint + resume
- Provider note label: VCS providers: Git, GitHub, Mercurial

Composition: left-to-right flow. Put the three input xprompts in a compact stack on the left feeding Agent changes. Then
Stop hook and Commit skill feed into `sase commit` and a large central CommitWorkflow band. Inside the band, reserve
room for ten ordered stage chips. Put bead lifecycle and plan handling before precommit: the workflow closes/syncs beads
and stages plan files before it runs the configured precommit command. Mark bead lifecycle and plan handling as skipped
for `#propose`; mark PR tags and parent detection as PR-only. From VCS dispatch, split into three clearly distinct
output branches on the right. Add a curved warning-accent conflict/resume loop that leaves VCS dispatch on conflict and
returns through the Checkpoint/VCS dispatch area after manual resolution; do not present it as a normal success branch.
Add the provider note near the dispatch area.

Avoid: logos, fake terminal screenshots, code blocks, dense paragraphs, tiny text, decorative gradients, dark
background, one-hue palette, misspelled labels, extra made-up product names, watermarks.

For reliable text, generate a mostly text-free visual foundation first, then add the exact labels locally as a raster
overlay. Keep the final stage order numbered left-to-right and top-to-bottom:

1. Bead lifecycle
2. Plan handling
3. Precommit
4. PR tags
5. Parent detection
6. Diff capture
7. Checkpoint
8. VCS dispatch
9. Result marker
10. Tracking

## Post-Processing Notes

The checked-in PNG is 1672x941. It was regenerated with GPT image generation as a mostly text-free architecture
foundation, then post-processed locally with exact labels and readable stage chips. The overlay fixes the prior critique
items by:

- labeling the left stack as `xprompts`;
- ordering the central stages as bead lifecycle, plan handling, precommit, PR tags, parent detection, diff capture,
  checkpoint, VCS dispatch, result marker, tracking;
- marking bead lifecycle and plan handling as skipped for `#propose`;
- marking PR tags and parent detection as PR-only;
- anchoring the conflict resume path around Checkpoint and VCS dispatch; and
- keeping the three output branches and VCS provider note visible on the right.
