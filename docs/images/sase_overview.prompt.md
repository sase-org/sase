---
pdf: false
---

# SASE README Overview Prompt

## Target

- Docs: `README.md` and `docs/index.md`
- README insertion point: after the opening description and before `## Why sase`
- Docs homepage insertion point: inside the hero visual
- Final image: `docs/images/sase_overview.png`
- Alt text: "Overview of SASE coordinating parallel coding agents, isolated workspaces, and durable workflow state"

## Final GPT Image Prompt

Use case: infographic-diagram

Asset type: GitHub README overview image for the open-source project "sase - Structured Agentic Software Engineering".

Primary request: Create a clean 16:9 landscape technical architecture infographic that accurately explains how SASE
works. It must be readable at about 800px wide in a GitHub README, with short labels and precise flow.

Exact visible labels to include, spelled exactly:

- Title: SASE
- Subtitle: Structured Agentic Software Engineering
- Top-left actor: Developer supervises many agents
- Coordination layer: ACE TUI + AXE Automation
- Input lane: Prompt / XPrompt / Workflow
- Planning handoff: Planner agent -> plan artifact -> coder agents
- Workspace fan-out labels: Workspace 1, Workspace 2, Workspace 3
- Agent labels inside workspaces: Claude Code, Codex, Antigravity CLI
- Provider boundary label: Agent, VCS, Workspace, Notification plugins
- Durable state labels: ChangeSpecs, Beads, Comments, Commits, Artifacts
- Outcome labels: Reviewed changes, Tracked runs, Scheduled work
- Footer note: One developer coordinates parallel coding agents with durable workflow state

Composition:

- Show a left-to-right and top-to-bottom systems diagram, not a marketing poster.
- Top left: a single Developer node supervising the system, with multiple thin lines reaching parallel workspaces.
- Left/middle: a horizontal coordination layer labeled "ACE TUI + AXE Automation". ACE should read as interactive
  control surface; AXE should read as background scheduling/automation.
- Input lane feeds the coordination layer: "Prompt / XPrompt / Workflow".
- Below input lane, show the planning handoff explicitly: "Planner agent -> plan artifact -> coder agents". The plan
  artifact is produced by the planner and then handed to coder agents, not shown as a normal user input.
- Center/right: show fan-out into three isolated workspace columns labeled "Workspace 1", "Workspace 2", and "Workspace
  3". Each workspace contains one neutral terminal/chat agent pill labeled "Claude Code", "Codex", or "Antigravity CLI"
  and a small branch/file icon, implying real coding work happens in external agents inside isolated checkouts.
- Beneath the workspaces, show a durable state layer as shared repositories/records: "ChangeSpecs", "Beads", "Comments",
  "Commits", "Artifacts". Use database/document/node icons and arrows from workspaces back into state.
- Along the lower edge, show a provider boundary strip labeled "Agent, VCS, Workspace, Notification plugins" to clarify
  plugins are integration boundaries.
- Right side outcomes: three compact blocks labeled "Reviewed changes", "Tracked runs", and "Scheduled work".

Accuracy constraints:

- Do not draw ACE, AXE, XPrompt, ChangeSpecs, Workspaces, Beads, and Plugins as equal sibling modules around a hub.
- Do not make "Plan" look like a normal user-supplied input; show it as a planner-agent output handed to coder agents.
- Do not draw agents as passive leaves. They are the execution workers inside isolated workspaces.
- Do not use the phrase "Agent Operating Layer" anywhere.
- Show parallelism clearly: one developer, several workspace columns, several agents working at once.
- Show durable state separately from runtime coordination.
- Show plugins as boundaries/integrations, not as a central feature box.

Strict visual constraints: Do NOT draw or imitate any company, model, provider, or product logos. The supported-agent
labels must be plain text pills or neutral generic terminal/chat icons only. Do not use starbursts, official-looking app
marks, mascots, badges, trademarks, branded color marks, fake screenshots, code paragraphs, or watermarks. Icons must be
generic thin line icons: user, terminal, clock, calendar, branch, folder, database, document, comment, checklist,
artifact cube, plug.

Style requirements: Technical architecture infographic, not marketing art. Light neutral background, dark readable text,
crisp rectangles with radius no more than 8px, precise arrows, generous spacing. Restrained varied palette: neutral base
plus teal for coordination, blue for workspaces, amber for planning handoff, green for durable state, slate for provider
boundary. Avoid one-hue palettes and decorative gradients. All text must be large, clean, and legible at README width.
16:9 landscape PNG-like output, professional systems diagram.

## Post-Processing Notes

Generated with the built-in image generation tool and copied into `docs/images/sase_overview.png`. This replacement was
generated after an accuracy review of the earlier overview image. The revised prompt emphasizes one developer
supervising parallel agents, planner-to-coder handoff through a plan artifact, isolated workspaces, durable workflow
state, and plugins as provider boundaries.
