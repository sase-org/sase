---
create_time: 2026-06-26
updated_time: 2026-06-26
status: research
---

# SASE Admin Center Popup Tab Migration Opportunities

## Research Request

Find opportunities to integrate existing ACE TUI popup panels into the new SASE Admin Center as additional tabs, and
recommend the top three candidates for migration.

## Bottom Line

The best candidates are popup panels that are global, durable or diagnostic, already browse-oriented, and not tightly
coupled to a single selected row. By that standard, the top three migration candidates are:

1. **Logs**: migrate `LogModal` into a `LogsPane`.
2. **Agent Restore**: migrate `SavedAgentGroupRevivalModal` / `DismissedAgentSelectModal` into an `AgentRestorePane`.
3. **Model Overrides**: migrate `TemporaryLLMOverrideModal` into a `ModelsPane` or `ModelOverridesPane`.

The close fourth is a combined **Operations** tab from `TaskQueueModal`, `RunnersModal`, and possibly `ActivityModal`.
It is useful, but more runtime/session-oriented than the current Admin Center tabs. Notifications, prompt history,
prompt stash, hook history, and CL-specific agent run logs should stay as contextual popups for now.

## Current Admin Center Shape

`ConfigCenterModal` is the current SASE Admin Center host:

- It is a full-screen `ModalScreen` with a clickable tab strip and `ContentSwitcher`.
- Current tabs are `config`, `projects`, `plugins`, and `xprompts`.
- `#` opens the Admin Center on Config.
- `[` / `]` cycle internal Admin Center tabs.
- `ProjectsPane`, `PluginsBrowserPane`, and `XPromptBrowserPane` are plain pane widgets hosted by the modal.

The migration pattern is already established:

- Extract the popup's body into a `Vertical` pane.
- Let `ConfigCenterModal` own close behavior, header chrome, tab switching, and tab focus.
- Preserve the old fast path by opening `ConfigCenterModal(initial_tab="...")`.
- Forward `[` / `]` from focused `Input` widgets to the host modal, as `ProjectsPane` and `XPromptBrowserPane` already do.
- Keep sub-dialogs such as confirmations, pickers, duration choosers, and editor handoffs as nested `ModalScreen`s.

## Selection Criteria

I used these criteria to rank candidates:

| Criterion | Why it matters |
| --- | --- |
| Global scope | Admin Center should be reachable from any ACE tab without depending on the current row. |
| Durable/admin semantics | Config, projects, plugins, xprompts, logs, archives, and override state fit better than one-shot actions. |
| Existing two-pane/list UI | Browse/manage panels migrate more cleanly than confirmations or tiny forms. |
| Low event-loop risk | A tab can sit open longer, so disk reads, paging, and refreshes must be worker-backed or cached. |
| Shortcut preservation | Existing power-user flows should become direct-open-to-tab paths, not disappear. |

## Candidate Inventory

| Candidate | Current entry | Fit | Notes |
| --- | --- | --- | --- |
| `LogModal` | `,L` from any tab | High | Global diagnostic panel over `sase.ace.tui.logs.sources`; already presentation-only and two-pane. |
| Agent Restore panels | `R` on Agents tab | High | Saved/recent dismissed-agent groups are durable agent archive state; already two-pane with paging, delete, preview, and custom search. |
| `TemporaryLLMOverrideModal` | `,o` from any tab | High | Global, config-adjacent, persisted temporary model state with provenance-like source labels. |
| `TaskQueueModal` / `RunnersModal` / `ActivityModal` | `,t`, `,R`, `,i` | Medium-high | Valuable as an Operations tab, but more live session monitoring than durable admin. |
| `NotificationModal` | `i` / `,n` | Medium | Has tabs and bulk actions, but selection drives urgent handlers such as plan approval/question response; better as inbox popup for now. |
| `PromptHistoryModal` | prompt input `Ctrl+K`, leader `,.` / `,>` | Medium-low | Excellent large browser, but primary behavior is launch/restore into a prompt context. |
| `StashedPromptsModal` | `@` / prompt bar restore flows | Medium-low | Global draft pile, but workflow is prompt-bar restoration; a persistent tab would need edit/preview features first. |
| `AgentRunLogModal` | selected CL, leader `,A` | Low | CL-specific and selection-dependent; better linked from ChangeSpec detail or Logs tab. |
| `HookHistoryModal` | hook input flow | Low | Adds hooks to selected ChangeSpec; context-specific action picker. |
| `AgentCleanupModal` | `X` on Agents tab | Low as standalone | It is an action chooser, not a durable browser. Its saved-group side effects support Agent Restore instead. |

## Top Candidate 1: Logs Tab

### Why It Fits

`LogModal` is the cleanest migration target. It is already global (`action_show_log_panel()` pushes it from any tab), and
its backend/UI boundary is clean: `sase.ace.tui.logs.sources` defines canonical log sources, paths, render modes, and
tail-reading behavior. The modal body is already a two-pane source list plus detail view.

This matches the Admin Center's "admin/debug" purpose better than a transient popup. Logs are a management/diagnostic
surface users may keep open while investigating failures.

### Migration Shape

- Add `logs` to `CenterTab`, `_TAB_ORDER`, `_TAB_LABELS`, and `_TAB_COLORS`.
- Extract `LogModal` into `LogsPane(OptionListNavigationMixin, CopyModeForwardingMixin, Vertical)`.
- Keep `LogModal` temporarily as a thin wrapper if needed, or re-point `,L` to `ConfigCenterModal(initial_tab="logs")`.
- Move or duplicate CSS selectors from `LogModal #log-modal-*` to `LogsPane #logs-*`.
- Prefer worker-backed refresh for tail reads, even though current reads are bounded to 500 lines and use efficient
  seek-from-end logic.

### Risk

Low. The main work is structural extraction and CSS retargeting. The biggest performance consideration is avoiding disk
tail reads directly in highlight/refresh handlers once it becomes a long-lived tab.

## Top Candidate 2: Agent Restore Tab

### Why It Fits

The Agent Restore flow already acts like an archive-management panel:

- `SavedAgentGroupRevivalModal` lists recent dismissal groups and saved agent groups.
- It has pagination, preview, jump hints, and saved-group deletion.
- It leads to custom dismissed-agent search via `DismissedAgentSelectModal`.
- It manages durable state under dismissed-agent group/archive storage, not just current in-memory row state.

This is much closer to Projects/XPrompts than to a confirmation popup. It would make restore operations accessible from
any Admin Center context, instead of only after navigating to Agents and pressing `R`.

### Migration Shape

- Add an `AgentRestorePane` tab, probably labeled **Restore** or **Agents**.
- Use `SavedAgentGroupRevivalModal` as the starting point, but load initial saved/recent pages inside the pane rather
  than before pushing a modal.
- Keep confirmation (`ConfirmActionModal`) and custom search as nested dialogs or sub-panels.
- Preserve the old Agents-tab `R` behavior by opening `ConfigCenterModal(initial_tab="restore")`, ideally with the
  restore pane focused on the same default row.
- Move synchronous saved-group/dismissed-bundle reads to workers. The current flow reads saved/recent groups before
  opening the modal; as a tab, that should become a loading state plus background result application.

### Risk

Medium. The panel is already mature, but its action flow returns a result to the Agents-tab host, and custom search
eventually revives agents into the current app state. The pane needs a host callback layer similar to the current
`AgentReviveFlowMixin`, not just a visual extraction.

## Top Candidate 3: Model Overrides Tab

### Why It Fits

`TemporaryLLMOverrideModal` is global and config-adjacent. It manages persisted state in
`~/.sase/llm_override.json` and `~/.sase/llm_worker_override.json`, shows primary and worker model lanes, and already
labels source/provenance such as override, config, follows primary, and default.

This belongs near Config and Plugins because it answers a common operational question: "What model will new launches use
right now, and why?" A full Admin Center tab could make that more discoverable without pretending the override is
permanent `sase.yml` configuration.

### Migration Shape

- Add a **Models** or **Overrides** tab.
- Convert the top-level modal body into `ModelOverridesPane`.
- Keep `ModelPickerModal`, `CustomModelInputModal`, and `_DurationPickerModal` as nested modal steps.
- Re-point `,o` to `ConfigCenterModal(initial_tab="models")`.
- Refresh the top-bar `LLMOverrideIndicator` from the same callback path after set/clear actions.
- Consider expanding the pane with read-only effective default details from permanent config, so it is more useful as a
  tab than the current compact modal.

### Risk

Medium-low. The UI is smaller than a typical tab, so the product risk is over-expanding a compact workflow. The technical
risk is mostly around keeping provider/model resolution light; prior startup-performance work has already identified
LLM override/provider resolution as a path to keep lean.

## Close Fourth: Operations Tab

A combined Operations tab could merge:

- `TaskQueueModal`: tracked background tasks, live output, kill, dismiss, copy, edit.
- `RunnersModal`: manual agents, AXE agents, hook processes, background tasks.
- `ActivityModal`: idle/active timeline and session summary.

The product value is real: users currently have separate global popups for "what is running?", "what background tasks
exist?", and "what has this session been doing?" But this is more runtime cockpit than admin center, so I would defer it
until after Logs/Restore/Models or explicitly decide that Admin Center should become a full "control center."

If implemented, make it a single **Operations** tab rather than three separate tabs. It should reuse `TaskQueue` as the
primary left-side list and offer subviews for Tasks, Runners, and Activity. Keep the top-right task indicator as the
fast entry point to `ConfigCenterModal(initial_tab="operations")`.

## Why Not Notifications Yet

`NotificationModal` is tempting because it already has internal tag tabs, bulk mark/dismiss, mute, snooze, attachments,
and jump-mode behavior. But its modal result is semantically important: selecting a notification dispatches handlers for
plan approvals, user questions, HITL, mentor review, memory review, tmux, and navigation.

That urgency makes it feel like an inbox/action popup rather than a passive Admin Center tab. It can be revisited after
the notification provider offers a cleaner page/detail/action contract for a long-lived tab.

## Why Not Prompt History Or Prompt Stash Yet

`PromptHistoryModal` and `StashedPromptsModal` are polished, but their main purpose is to load text into the current
prompt workflow. As Admin Center tabs, they would need a broader "Prompt Library" product shape: inspect, search,
delete, pin, edit, convert to xprompt, and maybe replay. Without that, moving them would make a launch workflow feel
farther away.

Since the Admin Center already has an XPrompts tab, prompt-history/stash integration should probably happen as
cross-links from XPrompts or a future dedicated Prompt Library, not as the next migration.

## Implementation Notes For Any Migration

- Preserve existing shortcuts by making them direct-open-to-tab paths.
- Keep the old popup class as a compatibility shell during phased migration if it reduces test churn.
- Add `focus_default()` to each new pane.
- Forward `[` / `]` from focused text inputs to the host modal.
- Do not put blocking disk I/O, JSON parsing, subprocess calls, or archive scans in Textual event handlers. Use
  `asyncio.to_thread()` or `run_worker(..., thread=True)`.
- For multi-second mutations, use tracked tasks so they appear in the Task Queue and quit-confirmation flow.
- Re-read selected row/tab identity after awaits before applying worker results.
- Add visual snapshots for each new tab, following the existing Config Center snapshot helpers.

## Recommended Migration Order

1. **Logs tab**: lowest risk, best architecture fit, immediate diagnostic value.
2. **Agent Restore tab**: high user value and strong management semantics; requires more host/action refactoring.
3. **Model Overrides tab**: config-adjacent and global; should be expanded slightly so the tab feels justified.

After those, revisit a combined **Operations** tab if the desired Admin Center scope is broader than durable/admin
management and includes live runtime monitoring.

## Sources Checked

- `src/sase/ace/tui/modals/config_center_modal.py`
- `src/sase/ace/tui/modals/projects_pane.py`
- `src/sase/ace/tui/modals/plugins_browser_pane.py`
- `src/sase/ace/tui/modals/xprompt_browser_pane.py`
- `src/sase/ace/tui/modals/log_modal.py`
- `src/sase/ace/tui/logs/sources.py`
- `src/sase/ace/tui/modals/saved_agent_group_revival_modal.py`
- `src/sase/ace/tui/modals/revive_agent_modal.py`
- `src/sase/ace/tui/actions/agents/_revive_flow.py`
- `src/sase/ace/tui/actions/agents/_revive_archive.py`
- `src/sase/ace/tui/modals/temporary_llm_override_modal.py`
- `src/sase/llm_provider/temporary_override.py`
- `src/sase/ace/tui/modals/task_queue_modal.py`
- `src/sase/ace/tui/modals/runners_modal.py`
- `src/sase/ace/tui/modals/activity_modal.py`
- `src/sase/ace/tui/modals/notification_modal.py`
- `src/sase/ace/tui/actions/agents/_notification_modal_flow.py`
- `src/sase/ace/tui/modals/prompt_history_modal.py`
- `src/sase/ace/tui/modals/stashed_prompts_modal.py`
- `src/sase/ace/tui/modals/agent_run_log_modal.py`
- `src/sase/ace/tui/modals/hook_history_modal.py`
- `src/sase/ace/tui/actions/base.py`
- `src/sase/ace/tui/actions/agent_workflow/_leader_mode.py`
- `src/sase/ace/tui/styles.tcss`
- `docs/ace.md`
- `docs/configuration.md`
- `sdd/epics/202606/projects_admin_center_tab.md`
- `sdd/epics/202606/log_panel.md`
- Audited memory: `sase memory read tui_perf.md`
