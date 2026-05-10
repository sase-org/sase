---
pdf: false
---

# SASE README Overview Prompt

## Target

- Docs: `README.md` and `docs/index.md`
- README insertion point: after the opening description and before `## Why sase`
- Docs homepage insertion point: inside the hero visual
- Final image: `docs/images/sase_overview.png`
- Alt text: "Visual overview of sase"

## Final GPT Image Prompt

Use case: infographic-diagram

Asset type: GitHub README overview image for the open-source project "sase - Structured Agentic Software Engineering".

Primary request: Create a clean 16:9 landscape technical architecture infographic that explains SASE as an operating
layer for dependable agent-driven software engineering. This image will render near the top of a GitHub README at about
800px wide, so it must be readable, calm, and documentation-oriented.

Exact visible labels to include, spelled exactly:

- Title: SASE
- Subtitle: Structured Agentic Software Engineering
- Center hub: Agent Operating Layer
- Left sources: Developer, Prompt, Plan
- Agent row: Claude Code, Gemini CLI, Codex, Qwen Code, OpenCode
- Core modules around the hub: ACE TUI, AXE Automation, XPrompt, ChangeSpecs, Workspaces, Beads, Plugins
- Right outcomes: Tracked Runs, Reviews, Commits, Artifacts
- Footer note: Durable workflow state for coding agents

Composition: Use a left-to-right systems diagram. On the left, show Developer, Prompt, and Plan as compact source cards
feeding the central SASE hub. In the center, make "Agent Operating Layer" the largest architecture block, surrounded by
smaller module blocks for ACE TUI, AXE Automation, XPrompt, ChangeSpecs, Workspaces, Beads, and Plugins. Beneath or
within the central area, show a thin row of supported coding agents labeled Claude Code, Gemini CLI, Codex, Qwen Code,
and OpenCode connected through the operating layer, not shown as competing products. On the right, split into four clear
outcome blocks: Tracked Runs, Reviews, Commits, and Artifacts. Use arrows to show state and work flowing through SASE
from inputs to agents to outcomes.

Strict visual constraints: Do NOT draw or imitate any company, model, provider, or product logos. The supported-agent
row must be plain text pills or neutral generic terminal/chat icons only. Do not use starbursts, knot symbols,
official-looking app marks, mascots, badges, trademarks, or branded color marks. All icons must be generic line icons
such as user, document, checklist, terminal, gear, chat bubble, folder, nodes, puzzle piece, graph, review, branch,
cube, database.

Style requirements: Technical architecture infographic, not marketing art. Light neutral background, dark readable text,
crisp rounded rectangles with radius no more than 8px, precise arrows, subtle grid or paper texture only if it stays
very faint. Use a restrained but varied palette with neutral base plus teal, blue, amber, and green accents so it does
not read as one-hue. No logos, no mascots, no fake terminal screenshots, no code paragraphs, no decorative gradients, no
dark background, no watermarks. Keep all text large and legible at GitHub README width. Generous spacing, professional
open-source documentation feel.

## Post-Processing Notes

Generated with the built-in image generation tool and copied into `docs/images/sase_overview.png`. A first pass had a
similar composition but included provider-like marks in the supported-agent row; the final prompt added strict no-logo
constraints and produced neutral terminal-style agent pills.
