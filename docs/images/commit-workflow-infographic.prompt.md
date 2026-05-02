# Commit Workflow Infographic Prompt

## Target

- Doc: `docs/commit_workflows.md`
- Insertion point: after the `## Overview` workflow table and before `## How It Works`
- Final image: `docs/images/commit-workflow-infographic.png`
- Alt text: "Shared commit workflow showing xprompt inputs flowing through the stop hook, commit skill, CommitWorkflow
  stages, VCS dispatch outputs, and conflict resume checkpoint"

## Final GPT Image Prompt

Use case: infographic-diagram Asset type: GitHub Markdown documentation infographic for docs/commit_workflows.md Primary
request: Create a clean 16:9 architecture infographic showing the shared Sase commit/propose/pull-request workflow. Use
a light neutral background, crisp blocks, clear arrows, restrained palette with distinct accents, and short legible
labels only. This is documentation art, not marketing art.

Exact visible labels to include, spelled exactly: Title: Shared Commit Workflow Left inputs: #commit, #propose, #pr Main
path blocks: Agent changes, Stop hook, Commit skill, sase commit, CommitWorkflow CommitWorkflow stage labels inside the
central orchestration band: Precommit, Bead lifecycle, Plan handling, PR tags, Parent detection, VCS dispatch, Tracking,
Result marker Right output branches: Commit hash + COMMITS entry, Saved diff + COMMITS entry, PR URL + ChangeSpec Side
loop label: Conflict checkpoint + resume Provider note label: VCS providers: Git, GitHub, Mercurial

Composition: left-to-right flow. Put the three input xprompts in a compact stack on the left feeding Agent changes. Then
Stop hook and Commit skill feed into a large central CommitWorkflow band with the stage labels as small chips. From VCS
dispatch, split into three clearly distinct output branches on the right. Add a small curved side loop from VCS dispatch
back to CommitWorkflow labeled Conflict checkpoint + resume, using a warning accent but not presenting it as a normal
success branch. Add the provider note near the dispatch area.

Avoid: logos, fake terminal screenshots, code blocks, dense paragraphs, tiny text, decorative gradients, dark
background, one-hue palette, misspelled labels, extra made-up product names, watermarks.

## Post-Processing Notes

No manual label post-processing was needed. The generated raster labels were readable at GitHub Markdown width and
matched the requested terminology.
