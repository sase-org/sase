---
pdf: false
---

# Prompt Burrito Diagram Prompt

## Target

- Document: `docs/blog/posts/structured-agentic-software-engineering.md`
- Intended insertion point: near the end of `## XPrompts`, after the prompt history/stash GIF.
- Final asset path: `docs/images/blog/prompt_burrito.png`
- Current status: prompt brief only; raster generation is a follow-up.

## Intended Alt Text

Funny layered diagram showing a SASE prompt built from workspace refs, directives, XPrompt
templates, typed inputs, and the final task text.

## Final GPT Image Prompt

Use case: blog illustration.

Asset type: 16:9 playful technical infographic, final PNG may be post-processed with deterministic
labels.

Primary request: Create a clean, funny, 16:9 landscape illustration of a "prompt burrito" that
explains SASE prompt composition. Use a light neutral background, crisp flat illustration, simple
layered shapes, and generous blank label areas. Do not include generated readable text, logos, fake
UI screenshots, dense paragraphs, or dark terminal panels.

Composition: show a large open wrap or layered stack in the center, with five clearly separated
ingredient-like layers: workspace reference, directives, XPrompt template, typed inputs, and final
task text. Around it, show small source cards feeding the layers: `#git:nova`-style workspace card,
`%model`/`%wait` directive card, `#review` template card, an input form card, and plain-language
task card. On the right, show the assembled prompt becoming one or more agent launch cards, with a
small branch/fan-out visual for alternations. Keep the humor visual rather than wordy.

Tone: warm and dry, useful for a blog reader who just learned that SASE prompts are composable. It
should feel like an explanatory aside, not a marketing hero image.

## Post-Processing Notes

- Add deterministic labels locally if generated text is wrong or hard to read.
- Suggested short labels: "workspace", "directives", "XPrompt", "typed inputs", "task", and "agent
  launch".
- Keep syntax examples outside the raster when possible; the surrounding Markdown already carries
  exact syntax.
