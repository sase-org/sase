---
bead_id: sase-xu6
---

# Plan: Claude Thinking Panel on Agents Tab

## Context

When monitoring agents on the Agents tab, there's currently no way to see what Claude is _thinking_ — only the prompt
and file diffs are visible. Claude Code stores full conversation transcripts (including extended thinking blocks) as
JSONL files in `~/.claude/projects/`. This plan adds a toggleable "Thinking" panel that reads these transcripts and
displays Claude's internal reasoning, giving users insight into agent behavior in real-time.

## Design Overview

Press `i` on the Agents tab to toggle between the **file panel** (diffs) and a new **thinking panel** (Claude's extended
thinking). The thinking panel replaces the file panel in the same layout position (70% of the detail area), keeping the
UI clean. It auto-refreshes for running agents, showing the latest thinking at the top.

### Layout

```
Default (current):              With thinking (press i):
┌──────────┬───────────────┐    ┌──────────┬───────────────┐
│          │ Prompt  (30%) │    │          │ Prompt  (30%) │
│  Agent   ├───────────────┤    │  Agent   ├───────────────┤
│  List    │ File    (70%) │    │  List    │ Thinking(70%) │
│          │   (green)     │    │          │  (purple)     │
└──────────┴───────────────┘    └──────────┴───────────────┘
```

### Visual: Thinking Panel Content

```
─── CLAUDE THINKING ─────────────────────────────
 3 thinking blocks · 8.2k chars

╭─ #3 · 14:32:05 ─────────────── → Read file ─╮
│ Let me analyze the agent_detail.py to        │
│ understand the current layout structure...   │
│ The compose method creates two panels:       │
│ prompt (30%) and file (70%)...               │
╰──────────────────────────────────────────────╯

╭─ #2 · 14:31:42 ──────────── → Edit code ────╮
│ I need to modify the CSS to add the new      │
│ thinking panel styles...                     │
╰──────────────────────────────────────────────╯

╭─ #1 · 14:31:20 ─────────────────────────────╮
│ The user wants to see Claude's thinking...   │
╰──────────────────────────────────────────────╯
```

---

## Phase 1: Core Data Layer (Session Resolver + Thinking Parser)

**Scope**: Create the `src/sase/ace/tui/thinking/` package with the data extraction logic. No UI changes — pure data
layer that can be tested independently.

### Files to Create

| File                                            | Description                                                                        |
| ----------------------------------------------- | ---------------------------------------------------------------------------------- |
| `src/sase/ace/tui/thinking/__init__.py`         | Package exports: `resolve_agent_session`, `parse_thinking_blocks`, `ThinkingBlock` |
| `src/sase/ace/tui/thinking/session_resolver.py` | Maps Agent → Claude JSONL transcript path                                          |
| `src/sase/ace/tui/thinking/parser.py`           | Extracts thinking blocks from JSONL files                                          |

### Session Resolver (`session_resolver.py`)

Maps an Agent to its Claude Code JSONL transcript file.

**Resolution chain**: Agent → workspace CWD → Claude project hash directory → most-recent JSONL file

```python
def resolve_agent_session(agent: Agent) -> Path | None
```

- Extract `project_name` from `agent.project_file` (e.g., `~/.sase/projects/sase/sase.gp` → `"sase"`)
- Get workspace CWD via `get_workspace_directory(project_name, workspace_num)` from `sase.running_field`
- Convert CWD to Claude's project hash directory name: replace all non-alphanumeric chars with `-`, prepend `-`
  - Example: `/home/bryan/projects/github/bbugyi200/sase_100` → `-home-bryan-projects-github-bbugyi200-sase-100`
- Find the most recently modified `.jsonl` in `~/.claude/projects/{hash}/`
- If agent has no `workspace_num`, fall back to workspace 1
- Catch `RuntimeError` from `get_workspace_directory()` gracefully (return None)

### Thinking Parser (`parser.py`)

```python
@dataclass
class ThinkingBlock:
    text: str
    timestamp: str
    index: int                      # 1-based position in conversation
    following_action: str | None    # e.g., "Read agent_detail.py", "Edit code"

def parse_thinking_blocks(jsonl_path: Path) -> list[ThinkingBlock]
```

- Read JSONL line by line, collect `{"type": "thinking"}` content blocks from `assistant` messages
- For each thinking block, look at the next content block in the same message to determine `following_action` (tool_use:
  extract name + first input arg; text: "Reply")
- Return blocks in **reverse chronological order** (newest first — most useful for monitoring running agents)
- Handle large files gracefully: cap at last ~200 assistant events or last 500KB

### Key Reference Files

- `src/sase/running_field.py:535` — `get_workspace_directory()` for Agent → CWD resolution
- `src/sase/gh_workspace.py:153` — `_get_git_clone_dir()` shows `{base}__{workspace_num}/` naming
- `src/sase/llm_provider/_subprocess.py:151` — `_process_json_line()` shows JSONL event structure
- `src/sase/ace/tui/models/agent.py` — Agent dataclass fields (`project_file`, `workspace_num`, etc.)

### JSONL Format Reference

```json
{
  "type": "assistant",
  "message": {
    "content": [
      { "type": "thinking", "thinking": "reasoning text...", "signature": "..." },
      { "type": "tool_use", "name": "Read", "input": { "file_path": "/path" } }
    ]
  },
  "sessionId": "uuid",
  "timestamp": "2026-02-19T18:03:06.794Z"
}
```

### Verification

- `just lint` passes (mypy + ruff)
- Write a quick manual test: `python -c "from sase.ace.tui.thinking import parse_thinking_blocks; ..."` to parse an
  existing JSONL file and print results

---

## Phase 2: Thinking Panel Widget

**Scope**: Create the `AgentThinkingPanel` widget. This follows the same patterns as the existing `AgentFilePanel`
(`file_panel.py`). No integration yet — just the standalone widget.

**Depends on**: Phase 1 (uses `resolve_agent_session` and `parse_thinking_blocks`)

### Files to Create

| File                                         | Description                                                       |
| -------------------------------------------- | ----------------------------------------------------------------- |
| `src/sase/ace/tui/widgets/thinking_panel.py` | `AgentThinkingPanel` widget + `ThinkingVisibilityChanged` message |

### Widget Design

Follow the patterns from `src/sase/ace/tui/widgets/file_panel.py`:

- `ThinkingVisibilityChanged(Message)` — posted when thinking data availability changes (like `FileVisibilityChanged`)
- `AgentThinkingPanel(Static)`:
  - Background worker thread for JSONL parsing (via `self.run_worker()`)
  - Module-level cache: `_thinking_cache: dict[str, _ThinkingCacheEntry]` with `blocks` and `fetch_time`
  - Cache key: `f"{agent.cl_name}:{agent.agent_type.value}:{agent.workspace_num}"`
  - Stale threshold: 10 seconds (same as file panel)
  - Scroll position preservation on refresh (`_save_scroll_position` / `_restore_scroll_position`)
  - `update_display(agent, stale_threshold_seconds=10)` — main entry point
  - `show_empty()` — "No agent selected"

### Rich Display Format

Header:

```
CLAUDE THINKING                    (bold #AF87D7 underline)
3 thinking blocks · 8.2k chars    (dim)
```

Each block — use Rich `Text` with styled borders:

```
╭─ #3 · 14:32:05 ─── → Read agent_detail.py ──╮ (dim #AF87D7)

 Let me analyze the agent_detail.py to          (#D7D7FF on default)
 understand the current layout structure...

╰──────────────────────────────────────────────╯ (dim #AF87D7)
```

- Block number and timestamp in `#AF87D7` (purple)
- Following action in `#87D7FF` (blue)
- Thinking text in `#D7D7FF` (light lavender) for readability

### Key Reference Files

- `src/sase/ace/tui/widgets/file_panel.py` — primary pattern to follow (worker, cache, scroll, messages)
- `src/sase/ace/tui/thinking/` — Phase 1 outputs (session_resolver, parser)

### Verification

- `just lint` passes
- Widget can be imported: `from sase.ace.tui.widgets.thinking_panel import AgentThinkingPanel`

---

## Phase 3: Integration (Agent Detail + Keybindings + CSS)

**Scope**: Wire the thinking panel into the agent detail layout, add the `i` keybinding, update scroll navigation,
footer, and help modal. This is the integration phase that makes everything work end-to-end.

**Depends on**: Phase 2 (uses `AgentThinkingPanel` widget)

### Files to Modify

| File                                              | Changes                                                  |
| ------------------------------------------------- | -------------------------------------------------------- |
| `src/sase/ace/tui/widgets/__init__.py`            | Export `AgentThinkingPanel`, `ThinkingVisibilityChanged` |
| `src/sase/ace/tui/widgets/agent_detail.py`        | Add third panel, toggle logic, visibility management     |
| `src/sase/ace/tui/styles.tcss`                    | CSS for `#agent-thinking-scroll`                         |
| `src/sase/ace/tui/app.py`                         | Add `Binding("i", "toggle_thinking", ...)`               |
| `src/sase/ace/tui/actions/agents/_interaction.py` | Add `action_toggle_thinking()` method                    |
| `src/sase/ace/tui/actions/navigation/_basic.py`   | Update scroll actions for thinking panel                 |
| `src/sase/ace/tui/widgets/keybinding_footer.py`   | Add `("i", "thinking")` to agent bindings                |
| `src/sase/ace/tui/modals/help_modal/bindings.py`  | Add help entry under "Agent Actions"                     |

### Agent Detail Changes (`agent_detail.py`)

Add thinking panel as a third VerticalScroll container (hidden by default):

```python
def compose(self) -> ComposeResult:
    with Vertical(id="agent-detail-layout"):
        with VerticalScroll(id="agent-prompt-scroll"):
            yield AgentPromptPanel(id="agent-prompt-panel")
        with VerticalScroll(id="agent-file-scroll"):
            yield AgentFilePanel(id="agent-file-panel")
        with VerticalScroll(id="agent-thinking-scroll", classes="hidden"):
            yield AgentThinkingPanel(id="agent-thinking-panel")
```

New state: `_thinking_visible: bool = False`

New methods:

- `toggle_thinking()` — swap file↔thinking panel visibility. When toggling ON: hide `#agent-file-scroll`, show
  `#agent-thinking-scroll`, call `thinking_panel.update_display(agent)`. When toggling OFF: reverse.
- `is_thinking_visible() -> bool`

In `update_display()`: when `_thinking_visible` is True, call `thinking_panel.update_display(agent)` in addition to (or
instead of) `file_panel.update_display(agent)`.

Handle `ThinkingVisibilityChanged` message similar to `FileVisibilityChanged`.

### CSS Additions (`styles.tcss`)

Add after `#agent-file-scroll` rules (line ~443):

```css
#agent-thinking-scroll {
  height: 70%;
  border: solid #af87d7;
  padding: 1 2;
  scrollbar-gutter: stable;
}

#agent-thinking-scroll.hidden {
  display: none;
}

#agent-thinking-scroll.layout-secondary {
  height: 30%;
}
```

### Keybinding (`app.py`)

Add near line 151 (after the `p` layout binding):

```python
Binding("i", "toggle_thinking", "Thinking", show=False),
```

### Action (`_interaction.py`)

Add `action_toggle_thinking()`:

- Guard: `if self.current_tab != "agents": return`
- Get current agent from `self._agents[self.current_idx]`
- Call `agent_detail.toggle_thinking()`
- Update footer bindings to reflect new state

### Scroll Navigation (`_basic.py`)

Update `action_scroll_detail_down`, `action_scroll_detail_up`, `action_scroll_to_top`, `action_scroll_to_bottom`:

- When on agents tab: check `agent_detail.is_thinking_visible()`
- If thinking visible: scroll `#agent-thinking-scroll` instead of `#agent-file-scroll`

### Footer (`keybinding_footer.py`)

In `_compute_agent_bindings()`, add `("i", "thinking")` — always show this binding when an agent is selected (thinking
toggle always works).

### Help Modal (`bindings.py`)

In `AGENTS_BINDINGS`, under "Agent Actions" section, add:

```python
("i", "Toggle Claude thinking panel"),
```

### Edge Cases

- **No JSONL found** (no workspace, non-Claude agent): Thinking panel shows "No thinking data available" in dim italic
- **JSONL exists but no thinking blocks**: Show "No thinking blocks in this session" with session path
- **Agent without workspace_num**: Fall back to workspace 1 / main project directory
- **`get_workspace_directory()` raises RuntimeError**: Resolver returns None, panel shows empty state
- **Layout toggle (`p`)**: Should work with thinking panel visible — `layout-priority`/`layout-secondary` classes apply
  to thinking scroll too

### Verification

1. `just check` — all lint and tests pass
2. `sase ace --agent --keys tab` — Agents tab renders without errors
3. `sase ace --agent --keys tab i` — Thinking panel toggles on
4. Manual test: launch a real agent, switch to Agents tab, press `i`, verify thinking blocks appear and auto-refresh
5. Test edge case: select an agent without thinking data, press `i`, verify graceful "no data" message
6. Test `p` key toggles layout with thinking panel visible
7. Test `Ctrl+D`/`Ctrl+U` scroll the thinking panel when it's active
