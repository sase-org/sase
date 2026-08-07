---
pdf: false
---

# Window Farm Vs Control Tower Diagram Prompt

## Target

- Document: `docs/blog/posts/structured-agentic-software-engineering.md`
- Intended insertion point: after the intro's tmux/SASE comparison and before
  `## SASE Wraps Agent CLIs, Not Models`.
- Final asset path: `docs/images/blog/window_farm_vs_control_tower.png`
- Current status: prompt brief only; raster generation is a follow-up.

## Intended Alt Text

Diagram contrasting separate tmux agent windows with one SASE ACE control surface that tracks
agents, notifications, and approval gates.

## Final GPT Image Prompt

Use case: blog illustration.

Asset type: 16:9 documentation-friendly infographic for a technical blog post, final PNG may be
post-processed with deterministic labels.

Primary request: Create a clean, lightly funny 16:9 landscape illustration contrasting an unmanaged
tmux window farm with a SASE control tower. Use a light neutral background, crisp flat vector-like
shapes, short-label whitespace, and a restrained multi-accent palette. No dark terminal screenshots,
no logos, no fake readable text, no decorative gradients, and no tiny UI details.

Composition: split into two balanced halves with a clear before/after flow. Left half: several
overlapping terminal windows arranged like a messy grid, each representing a separate coding-agent
CLI session; add visual hints of missing state such as loose scrollback strips, repeated prompt
cards, and small unattended alert dots. Right half: one calm ACE control surface with grouped agent
rows, a notification bell, a plan approval gate, and durable artifact cards feeding into a single
dashboard. Use subtle arrows from the loose windows toward the organized control surface. Leave
blank label zones for deterministic labels such as "tmux windows", "manual monitoring", "ACE Agents
tab", and "tracked runs".

Tone: dry, practical, and slightly humorous, but still appropriate for product documentation. The
image should make the reader understand the article's thesis in one glance: SASE keeps the same CLIs
and adds the operating layer around them.

## Post-Processing Notes

- Add labels locally after generation if the model produces misspellings or low-contrast text.
- Keep any final labels short enough to read at blog width.
- Do not imply that SASE replaces provider CLIs; the right side should show orchestration around the
  same terminal-agent boxes, not a model API cloud.
