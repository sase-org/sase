# Plan: Add Inbox Tab to SASE TUI

## Context

The SASE TUI currently has 3 tabs: CLs, Agents, AXE. When agents complete (reach DONE/FAILED state), a gold badge
`Agents (N)` appears on the Agents tab bar, tracking which agents the user has viewed via
`~/.sase/tui/viewed_agents.json`. This approach is limited — notifications are tightly coupled to the agents tab and
don't support other notification sources.

This plan adds a dedicated **Inbox** tab (the second tab, after CLs) that serves as a centralized notification center.
Initially it surfaces agent completion notifications. The existing agents-tab badge system is then removed as obsolete.

**Tab order**: `CLs | Inbox | Agents | AXE`

## Phase 1: Build Inbox Tab (Purely Additive)

All new infrastructure; existing badge system remains intact and working.

### Step 1: Notification Data Model + Persistence

**Create** `src/sase/ace/tui/notifications.py`

- `Notification` dataclass: `notification_type` (Literal["agent_done", "agent_failed"]), `title`, `agent_identity`
  (tuple used as unique key — prevents duplicates), `agent_status`, `timestamp`, `duration`, `error_message`, `read`
  (bool)
- Persistence to `~/.sase/tui/notifications.json` (pattern: `viewed_agents.py`)
- Functions: `load_notifications()`, `save_notifications()`, `add_notification()`, `remove_notification()`,
  `mark_read()`
- Cap at ~100 notifications, prune oldest on save
- Sorted newest-first by timestamp

### Step 2: Update `TabName` Type Alias Everywhere

Change `Literal["changespecs", "agents", "axe"]` → `Literal["changespecs", "inbox", "agents", "axe"]`

~20 files define this redundantly. Update all of them. Key files:

- `app.py`, `tab_bar.py`, `event_handlers.py`, `_basic.py`, `_types.py`, `_notifications.py`, `_core.py`,
  `_interaction.py`, `_folding.py`, `base.py`, `clipboard.py`, `changespec.py`, `marking.py`, `axe.py`,
  `_entry_points.py`, `help_modal/bindings.py`, `help_modal/modal.py`, `modals/__init__.py`

### Step 3: Inbox Widgets

**Create** `src/sase/ace/tui/widgets/inbox_list.py`

- Extends `OptionList` (pattern: `agent_list.py`)
- `SelectionChanged` and `WidthChanged` messages
- Entry format:
  ```
   ●  [run] my-feature (DONE)              3m ago
      [wf] auth-refactor (FAILED)         15m ago
  ```
- Unread: warm amber `●` dot (`#FFB86C`), full-color text
- Read: no dot, dimmed text
- Agent type colors reused from `_AGENT_TYPE_COLORS` in `agent_list.py`
- CL name in teal `#00D7AF`, status colored (green DONE `#5FD75F`, red FAILED `#FF5F5F`)
- Relative timestamp right-aligned in dim

**Create** `src/sase/ace/tui/widgets/inbox_info_panel.py`

- Extends `Static` (pattern: `AgentInfoPanel`)
- Display: `Inbox: 1/5   (auto-refresh in 8s)` with "Inbox:" in amber `#FFB86C`

**Create** `src/sase/ace/tui/widgets/inbox_detail.py`

- Extends `Static` (pattern: `AgentDetail`)
- Shows: notification title, agent type + CL, status, timestamp, duration, error message (if FAILED)
- Empty state: `"No notifications yet"` (bold dim) + `"Notifications appear when agents finish running."` (dim)

**Update** `src/sase/ace/tui/widgets/__init__.py` — export the 3 new widgets

### Step 4: Tab Bar — Inbox as Second Tab

**Modify** `src/sase/ace/tui/widgets/tab_bar.py`

- Add `_inbox_tab_range` and `_inbox_attention_count` fields
- Add `set_inbox_attention_count(count)` method
- Update `_build_content()` — render Inbox between CLs and Agents:
  ```
   CLs  |  Inbox (3)  |  Agents  |  AXE
  ```
- Inbox active: `bold reverse #FFB86C` (warm amber)
- Inbox with unread: `bold #1a1a1a on #FFB86C` (amber badge, matching agents badge pattern)
- Inbox inactive: `dim`
- Update `on_click` for inbox range

### Step 5: Inbox Action Mixin

**Create** `src/sase/ace/tui/actions/inbox.py`

- `InboxMixin` class with methods:
  - `_load_inbox()` — load notifications, refresh display
  - `_refresh_inbox_display()` — update list, detail, info panel, footer
  - `_update_inbox_info_panel()` — position + countdown
  - `_dismiss_current_notification()` — remove with `x`
  - `_mark_current_as_read()` — mark on selection
  - `_get_unread_count()` → int
  - `_update_inbox_badge()` — update tab bar unread count

**Update** `src/sase/ace/tui/actions/__init__.py` — export `InboxMixin`

### Step 6: App Integration

**Modify** `src/sase/ace/tui/app.py`

- Add `InboxMixin` to class hierarchy
- Add state: `_notifications: list[Notification] = []`, `_inbox_last_idx: int = 0`
- Load notifications in `__init__`
- Add `I` keybinding: `Binding("I", "jump_to_inbox", "Inbox", show=False)`
- Add `action_jump_to_inbox()` — save position, switch to inbox, restore inbox position
- Add inbox view to `compose()` (second position, hidden by default):
  ```python
  # Inbox Tab (hidden by default) — after changespecs-view, before agents-view
  with Horizontal(id="inbox-view", classes="hidden"):
      with Vertical(id="inbox-list-container"):
          yield InboxInfoPanel(id="inbox-info-panel")
          yield InboxList(id="inbox-list-panel")
      with Vertical(id="inbox-detail-container"):
          with VerticalScroll(id="inbox-detail-scroll"):
              yield InboxDetail(id="inbox-detail-panel")
  ```
- Update `watch_current_tab` — add inbox show/hide case, call `_load_inbox()`
- Default tab stays `"changespecs"`

### Step 7: Navigation Updates

**Modify** `src/sase/ace/tui/actions/navigation/_basic.py`

- Tab cycling: `CLs → Inbox → Agents → Axe → CLs`
- Add `_get_clamped_inbox_idx()`
- Update `_save_current_tab_position()` for inbox
- Update `action_next_changespec` / `action_prev_changespec` with inbox list navigation
- Update scroll actions — inbox uses `#inbox-detail-scroll`

### Step 8: Notification Generation

**Modify** `src/sase/ace/tui/actions/agents/_notifications.py`

- In `_poll_agent_completions`, after detecting `newly_completed`, call
  `_generate_inbox_notifications(newly_completed, all_agents)`
- New method `_generate_inbox_notifications()` — creates `Notification` objects for each newly completed agent (captures
  `display_type`, `cl_name`, `duration_display`, `error_message` at creation time)
- Call `_update_inbox_badge()` to update tab bar unread count
- **Keep all existing badge logic intact** (Phase 2 removes it)

### Step 9: Event Handler Updates

**Modify** `src/sase/ace/tui/actions/event_handlers.py`

- Add `on_inbox_list_selection_changed` — sync selection + mark as read
- Add `on_inbox_list_width_changed` — dynamic list width
- Update `_on_auto_refresh` — refresh inbox if on inbox tab
- Update `_on_countdown_tick` — update inbox info panel if on inbox tab
- Update `on_tab_bar_tab_clicked` — handle "inbox" click

### Step 10: CSS Styling

**Modify** `src/sase/ace/tui/styles.tcss`

```css
/* ===== Inbox Tab Styling ===== */
#inbox-view {
  width: 100%;
  height: 100%;
}
#inbox-list-container {
  width: 50;
  min-width: 40;
  max-width: 80;
  height: 100%;
}
#inbox-info-panel {
  height: auto;
  max-height: 1;
  padding: 0 1;
  background: $surface;
}
#inbox-list-panel {
  width: 100%;
  height: 1fr;
  border: solid #ffb86c;
  padding: 0 1;
}
#inbox-detail-container {
  width: 1fr;
  height: 100%;
}
#inbox-detail-scroll {
  height: 1fr;
  border: solid $secondary;
  padding: 1 2;
  scrollbar-gutter: stable;
}
#inbox-detail-panel {
  height: auto;
}
```

### Step 11: Help Modal + Keybinding Footer

**Modify** `src/sase/ace/tui/modals/help_modal/bindings.py`

- Add `INBOX_BINDINGS` (Navigation: j/k, Ctrl+D/U, Enter jump; Actions: x dismiss, X dismiss all; General: Tab, I, @, !,
  y, q, ?)
- Update `TAB_DISPLAY_NAMES` and `COLUMN_SPLITS`

**Modify** `src/sase/ace/tui/widgets/keybinding_footer.py`

- Add `update_inbox_bindings(notification)` — shows `x dismiss`, `Enter jump to agent`, `X dismiss all`

### Step 12: Handle `current_tab` Switch Statements

Every file that branches on `current_tab` needs an inbox case (usually early return / no-op for tab-specific actions).
Key files: `_basic.py`, `event_handlers.py`, `base.py`, `changespec.py`, `marking.py`, `clipboard.py`, `axe.py`,
`_core.py`, `_interaction.py`, `_folding.py`, `_entry_points.py`

---

## Phase 2: Remove Old Agents Tab Badge System (Purely Subtractive)

### Step 1: Remove Badge from Tab Bar

**Modify** `src/sase/ace/tui/widgets/tab_bar.py`

- Remove `_attention_count` field and `set_attention_count()` method
- Remove gold badge rendering for agents tab in `_build_content()`

### Step 2: Remove Viewed Agents Persistence

**Delete** `src/sase/ace/tui/viewed_agents.py`

### Step 3: Remove Viewed Agents from App

**Modify** `src/sase/ace/tui/app.py`

- Remove `_viewed_agents` initialization and `load_viewed_agents` import
- Remove `_pending_attention_count` initialization

### Step 4: Simplify AgentNotificationMixin

**Modify** `src/sase/ace/tui/actions/agents/_notifications.py`

- Remove `_viewed_agents` and `_pending_attention_count` attribute declarations
- Remove viewed/badge logic from `_poll_agent_completions()` (keep completion detection + inbox notification
  generation + tmux bell)
- Remove `_update_tab_bar_emphasis()`, `_clear_tab_bar_emphasis()`, `_mark_current_agents_as_viewed()`

### Step 5: Clean Up watch_current_tab

**Modify** `src/sase/ace/tui/app.py`

- Remove `_mark_current_agents_as_viewed()` call in `watch_current_tab` agents case
- Remove `_clear_tab_bar_emphasis()` call

### Step 6: Clean Up Agent Dismissal

**Modify** agent dismissal code that interacts with `_viewed_agents` — remove `_viewed_agents.discard()` and
`save_viewed_agents()` calls from `_killing.py`

---

## Verification

After each phase, run:

```bash
just check    # fmt-check + lint (ruff + mypy) + test
just test     # pytest with coverage
sase ace      # Manual TUI testing
```

Manual testing checklist:

- [ ] Tab bar shows `CLs | Inbox | Agents | AXE` in correct order
- [ ] `Tab`/`Shift+Tab` cycles through all 4 tabs correctly
- [ ] `I` key jumps to Inbox from any tab
- [ ] Clicking "Inbox" in tab bar switches to it
- [ ] Agent completing creates notification in inbox
- [ ] Unread badge `Inbox (N)` appears in amber on tab bar
- [ ] Selecting notification marks it as read (dot disappears)
- [ ] `x` dismisses individual notification
- [ ] `j`/`k` navigation works in inbox list
- [ ] Detail panel shows notification info
- [ ] Empty state shows clean message
- [ ] Tmux bell still rings on agent completion
- [ ] (Phase 2) No badge on Agents tab anymore
- [ ] (Phase 2) `viewed_agents.json` no longer written
