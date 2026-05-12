---
create_time: 2026-05-12 10:27:28
status: done
prompt: sdd/prompts/202605/agent_provider_emoji_rows.md
---
# Plan: Provider Emoji Badges in Agent Rows

## Goal

Show a compact emoji badge on every agent row in the Agents tab when the row has a known LLM provider. This should apply
uniformly to root agent/workflow entries and child agent entries because both are rendered through the same row
formatter.

## Product Behavior

- Add a single provider emoji immediately before the agent display name, after existing row-prefix controls such as
  hints, marks, approval badges, workflow indentation, hidden markers, retry badges, and type glyphs.
- Use these mappings:
  - Claude: `🎭`
  - Gemini: `♊`
  - Codex: `🤖`
  - Qwen: `🐼`
  - OpenCode: `🐙`
- Unknown or missing providers should render no emoji to avoid misleading rows that lack persisted provider metadata.
- Workflow child rows should get the same provider treatment as root rows when `Agent.llm_provider` is populated.
- Non-agent workflow step rows, such as bash/python rows, should only show an emoji if they have an LLM provider value;
  normally they should remain unchanged.

## Technical Approach

- Keep this as a presentation-only TUI change in this repo; no Rust core or persisted metadata schema change is needed
  because `Agent.llm_provider` already exists and is loaded for running/done agents.
- Add a small provider-to-emoji helper near existing TUI provider styling code so the mapping is reusable and easy to
  test.
- Update `format_agent_option` in the agent-list row renderer to append the emoji badge before `agent.display_name`.
- Include `agent.llm_provider` in `agent_render_key` so cached rows invalidate when provider metadata changes.
- Add focused unit tests for root and workflow-child rows, covering the requested OpenCode/Qwen/Codex choices and one
  no-provider fallback.
- Update visual snapshots only if the PNG snapshot tests intentionally change; the existing fixture includes a Codex
  agent, so this change is expected to affect at least the Agents-tab snapshots.

## Verification

- Run targeted tests for agent row rendering and render cache behavior.
- Because this repo requires it after changes, run `just install` if needed and then `just check` before reporting
  completion.
