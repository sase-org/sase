---
pdf: false
---

# One Prompt Five CLIs Diagram Prompt

## Target

- Document: `docs/blog/posts/structured-agentic-software-engineering.md`
- Intended insertion point: after the multi-model fan-out GIF in
  `## SASE Wraps Agent CLIs, Not Models`.
- Final asset path: `docs/images/blog/one_prompt_five_clis.png`
- Current status: prompt brief only; raster generation is a follow-up.

## Intended Alt Text

Diagram showing one SASE prompt flowing through an operating layer to five provider CLI
subprocesses: Claude, Codex, Antigravity, Qwen, and OpenCode.

## Final GPT Image Prompt

Use case: architecture-blog infographic.

Asset type: 16:9 technical illustration for a blog post, final PNG may be post-processed
with deterministic labels.

Primary request: Create a clean 16:9 landscape architecture infographic showing one user
prompt entering SASE, then SASE routing work to five existing agent CLI subprocesses.
Use a light neutral background, flat vector-like panels, thin outlines, short arrows,
and a restrained multi-accent palette. Include no logos, no generated readable text, no
fake terminal screenshots, no clouds labeled as direct model APIs, and no decorative
gradients.

Composition: left side has one prompt card with small visual layers for workspace
reference, directives, XPrompt expansion, and prompt text. Center has a larger SASE
operating-layer panel with durable state cards around it: agent record, transcript,
status, artifacts, notifications, and approval gates. Right side has five equal
subprocess lanes, each represented as a small CLI terminal tile with a distinct accent
color. One lane should visually indicate that Antigravity can carry Gemini-named model
labels without implying a separate Gemini CLI. Arrows should run from the prompt into
SASE and then from SASE to all five CLI lanes.

Tone: precise and pragmatic. The visual should emphasize inheritance of provider CLI
behavior plus uniform SASE workflow state around the launches.

## Post-Processing Notes

- Deterministic labels to add later: "one prompt", "SASE operating layer", "durable
  agent record", "notifications", "approval gates", "claude", "codex", "agy", "qwen",
  and "opencode".
- Keep the provider/model distinction crisp. Do not label any CLI lane as `gemini`.
- Do not show raw model API calls from SASE.
