---
create_time: 2026-06-26
updated_time: 2026-06-26
status: research
---

# SASE Admin Center Popup Panel Tab Migration Opportunities

## Research Request

Find opportunities to integrate existing ACE TUI popup panels into the SASE Admin Center as additional tabs, and end with
a recommendation for the top three migration candidates.

## Consolidation Notes

This consolidates two independent research drafts:

- `sdd/research/202606/admin_center_popup_tab_migration_opportunities.md`
- `sdd/research/202606/admin_center_tab_migration_candidates.md`

Both drafts correctly identified the Admin Center migration pattern, but they disagreed on the top three. The conflict
comes from weighting product fit differently: one draft favored durable/admin surfaces such as Logs, Agent Restore, and
Model Overrides; the other favored global leader-key panels such as Runners, Task Queue, and Prompt Stash.

After re-checking the source, the strongest answer is to treat Runners and Task Queue as one **Operations** opportunity,
not as two separate tabs. That preserves their real value while avoiding duplicate "what is running?" surfaces. Model
Overrides and Prompt Stash remain plausible follow-ups, but they are weaker standalone tab candidates: Model Overrides is
currently a compact multi-step wizard, and Prompt Stash is primarily a restore-into-prompt workflow rather than an admin
resource browser.

## Admin Center Shape Today

`src/sase/ace/tui/modals/config_center_modal.py` defines the current Admin Center:

- Full-screen `ModalScreen` with a clickable tab strip and `ContentSwitcher`.
- Current tabs: `config`, `projects`, `plugins`, `xprompts`.
- `#` opens the Admin Center on Config.
- `[` and `]` cycle internal tabs.
- `initial_tab` already supports fast paths that open directly to a non-default tab.

The pane migration pattern is established by Projects, Plugins, and XPrompts:

- Extract the modal body into a `Widget`/`Vertical` pane.
- Register it in `CenterTab`, `_TAB_ORDER`, `_TAB_LABELS`, `_TAB_COLORS`, and `compose()`.
- Implement `focus_default()` so the host can focus the pane naturally after open or tab switch.
- Let `ConfigCenterModal` own close behavior, header chrome, tab switching, and the outer frame.
- Preserve old shortcuts by opening `ConfigCenterModal(initial_tab="...")`.
- Keep confirmations, pickers, duration choosers, and editor handoffs as nested `ModalScreen`s.

## Selection Criteria

The best Admin Center tabs are:

- **Global**: usable from any ACE tab without depending on the currently selected row.
- **Management-oriented**: durable configuration, archives, logs, resource catalogs, or controlled runtime state.
- **Pane-shaped**: list/detail, browser, dashboard, or manager UI that users may keep open.
- **Low surprise**: migrating the shortcut should not make a high-frequency action harder to reach.
- **Safe as a long-lived tab**: no hidden polling, blocking disk I/O, JSON parsing, subprocess work, or archive scans on
  Textual's event loop.

The audited TUI performance guidance matters here: any refresh, file read, archive scan, or multi-second mutation added
for these tabs should run through existing background-worker or tracked-task paths, and UI state should be re-read after
awaits before applying results.

## Candidate Survey

| Candidate | Current entry | Fit | Consolidated verdict |
| --- | --- | --- | --- |
| `LogModal` | `,L` | Very high | Best single-panel migration. Global, diagnostic, presentation-only, and already backed by a log-source registry. |
| `TaskQueueModal` + `RunnersModal` | `,t`, `,R` | High as one tab | Best product-value follow-up if merged into an Operations tab instead of split into two tabs. |
| `SavedAgentGroupRevivalModal` + `DismissedAgentSelectModal` | `R` on Agents tab | High | Strong archive-management fit, but needs host/callback refactor and off-thread loading. |
| `TemporaryLLMOverrideModal` | `,o` | Medium-high | Config-adjacent and global, but currently a compact wizard. Better as a future Models/Config subsection unless expanded. |
| `StashedPromptsModal` | `@` | Medium | Clean UI and global store, but primary action restores into the prompt bar. Better as future Prompt Library work. |
| `ActivityModal` | `,i` | Medium | Useful telemetry, but read-only and monitoring-oriented. Fold into Operations rather than make a standalone tab. |
| `NotificationModal` | `i`, `,n` | Medium | Architecturally similar sub-tabs, but it is a high-frequency inbox with action dispatch semantics. Keep quick-access. |
| `PromptHistoryModal` | prompt input / leader history keys | Medium-low | Valuable browser, but coupled to prompt-entry workflows. Pair with future Prompt Library work. |
| `AgentRunLogModal` | selected CL / agent run log actions | Low | Context-specific to a selected ChangeSpec or agent run. Link from Logs instead. |
| `HookHistoryModal`, command/history pickers, confirm/input dialogs | contextual | Low | Transient workflow steps, not Admin Center tabs. |

## Candidate 1: Logs

`LogModal` is the cleanest migration target.

Why it fits:

- Global entry point through `action_show_log_panel()` and leader `,L`.
- Clear admin/diagnostic purpose: launch failures, TUI diagnostics, stalls, external tools, git ops, launch timing,
  runs, and events.
- Clean backend/UI boundary in `src/sase/ace/tui/logs/sources.py`: log source metadata, canonical paths, render mode,
  and efficient tail reading live outside the modal.
- Existing UI is already a two-pane list/detail panel.

Migration shape:

- Add a `logs` tab and `LogsPane`.
- Extract the current `LogModal` body into the pane; keep `LogModal` temporarily as a shell if that reduces churn.
- Re-point `,L` to `ConfigCenterModal(initial_tab="logs")`.
- Retarget CSS IDs from `log-modal-*` to pane IDs.
- Cache file metadata/tails by path and mtime, and avoid sync disk reads or JSONL rendering on hot navigation paths.

Risk:

- Low product risk and low structural risk.
- Main technical concern is performance: the current modal does bounded tail reads, but a long-lived tab should still
  avoid synchronous disk and JSON parsing during highlight churn.

## Candidate 2: Operations

The prior drafts split on Runners versus Task Queue. Source inspection suggests they should migrate together as a single
**Operations** tab.

What it would absorb:

- `TaskQueueModal`: global background task history/output, kill, dismiss, copy, and edit.
- `RunnersModal`: global running manual agents, AXE agents, hook processes, and a duplicate background-task section.
- `ActivityModal`: optional read-only session activity/timeline view.

Why it fits:

- The user problem is one thing: "what is SASE doing right now, and what can I control?"
- `TaskQueueModal` already has a list/detail shape similar to the current Plugins and XPrompts panes.
- `RunnersModal` is the most admin-flavored live-status surface, but it overlaps Task Queue enough that a standalone
  Runners tab would add fragmentation.
- Combining them lets the Admin Center own runtime control while leaving the main ChangeSpecs/Agents/AXE tabs for
  continuous work.

Migration shape:

- Add one `operations` tab, not separate `runners` and `tasks` tabs.
- Make Task Queue the primary list/detail view.
- Add section filters or inner tabs for Tasks, Runners, and Activity if needed.
- Preserve `,t`, `,R`, and the top-right task indicator as direct-open shortcuts to the appropriate Operations subview.
- Preserve runner jump behavior by dismissing the Admin Center and navigating to the target row.

Risk:

- Medium. The product value is high, but live refresh must be designed carefully.
- `TaskQueueModal` currently polls every second until unmount. A pane hidden by `ContentSwitcher` is still mounted, so
  polling must be gated by active-tab visibility.
- `RunnersModal` currently collects a snapshot synchronously through `collect_runners()`, which scans project/change
  state and may read prompt previews. A pane should load cached data immediately and refresh off-thread.

## Candidate 3: Agent Restore

`SavedAgentGroupRevivalModal` and `DismissedAgentSelectModal` are better Admin Center candidates than their current
Agents-tab-only entry point suggests.

Why it fits:

- Saved and recent dismissed-agent groups are durable archive state.
- The current saved-group modal is already a mature two-pane manager with saved/recent sections, preview, paging,
  delete, jump hints, and a custom search entry.
- Moving restore to Admin Center makes agent archival/recovery discoverable without requiring the user to be on the
  Agents tab first.

Migration shape:

- Add an `Agent Restore` tab, probably with tab id `restore` or `agents`.
- Use `SavedAgentGroupRevivalModal` as the pane base.
- Keep confirm dialogs, project selection, and custom dismissed-agent search as nested flows.
- Preserve the existing `R` behavior on the Agents tab by opening the Admin Center directly on Restore, or by keeping a
  compatibility action that opens the same pane workflow.
- After a revive action, dismiss or navigate to Agents so the user can see the restored rows.

Risk:

- Medium-high. This is a strong product fit, but not a pure visual extraction.
- Current `_revive_agent()` loads recent/saved group pages before pushing the modal; the pane should show a loading state
  and do archive reads off-thread.
- Current modal results are handled by `AgentReviveFlowMixin`, which mutates app state and marks groups revived. The pane
  needs an explicit host/controller layer rather than returning a simple screen result.

## Deferred Candidates

### Model Overrides

`TemporaryLLMOverrideModal` is global and config-adjacent, and it manages persisted temporary primary/worker override
state. It is a real opportunity, but I would not make it a top-three standalone tab yet.

The current surface is a compact wizard: choose primary/worker, pick model, pick duration, clear override. It would feel
thin as a full tab unless expanded into a broader **Models** view showing effective defaults, configured worker mapping,
temporary overrides, and provenance. That likely belongs either inside the Config tab's model section or as a later
Models tab after config editing matures.

### Prompt Stash And Prompt History

`StashedPromptsModal` is clean and global, and `PromptHistoryModal` is a useful browser, but both are still prompt-entry
workflows. Moving them into Admin Center would make sense only as a broader **Prompt Library** design that can inspect,
search, delete, pin, edit, convert to XPrompt, and replay. Until then, keep `@` and prompt-history actions close to the
prompt bar and consider cross-links from the existing XPrompts tab.

### Notifications

`NotificationModal` is an important architectural precedent because it already uses internal tag tabs and `[`/`]`
navigation. It should not move into Admin Center now. Notifications are a high-frequency inbox, and selecting one
dispatches urgent action handlers for plan approval, user questions, HITL, mentor review, memory review, tmux, and
navigation. It is better kept as quick-access, or promoted to a main TUI tab if it needs more permanence.

## Implementation Notes

- Preserve existing power-user shortcuts as direct-open-to-tab paths.
- Keep one-shot confirmations, pickers, editor handoffs, duration choosers, and modal child workflows as nested
  `ModalScreen`s.
- Add `focus_default()` to each new pane and forward `[`/`]` from focused inputs when needed.
- Avoid hidden polling in `ContentSwitcher` panes. Start/stop timers based on active tab, not just mount/unmount.
- Move file reads, JSON parsing, archive scans, and runner collection off the Textual event loop.
- For multi-second mutations such as killing tasks or reviving many agents, keep using tracked background tasks where
  appropriate so Task Queue and quit confirmation remain accurate.
- Update help bindings, command palette entries, `default_config.yml` keymaps, docs, and visual snapshots with each
  migration.

## Sources Checked

- `src/sase/ace/tui/modals/config_center_modal.py`
- `src/sase/ace/tui/modals/projects_pane.py`
- `src/sase/ace/tui/modals/plugins_browser_pane.py`
- `src/sase/ace/tui/modals/xprompt_browser_pane.py`
- `src/sase/ace/tui/modals/log_modal.py`
- `src/sase/ace/tui/logs/sources.py`
- `src/sase/ace/tui/modals/task_queue_modal.py`
- `src/sase/ace/tui/modals/runners_modal.py`
- `src/sase/ace/tui/modals/_runners_data.py`
- `src/sase/ace/tui/modals/activity_modal.py`
- `src/sase/ace/tui/modals/saved_agent_group_revival_modal.py`
- `src/sase/ace/tui/modals/revive_agent_modal.py`
- `src/sase/ace/tui/actions/agents/_revive_flow.py`
- `src/sase/ace/tui/modals/temporary_llm_override_modal.py`
- `src/sase/ace/tui/modals/stashed_prompts_modal.py`
- `src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash.py`
- `src/sase/ace/tui/modals/notification_modal.py`
- `src/sase/ace/tui/actions/agents/_notification_modal_flow.py`
- `src/sase/ace/tui/actions/base.py`
- `src/sase/ace/tui/actions/axe.py`
- `src/sase/ace/tui/actions/task_actions.py`
- `src/sase/default_config.yml`
- `sdd/research/202606/sase_config_tui_panel_ux_consolidated.md`
- `sdd/epics/202606/projects_admin_center_tab.md`
- `sdd/epics/202606/log_panel.md`
- Audited memory: `sase memory read tui_perf.md`

## Final Recommendation

1. **Logs tab**: migrate `LogModal` first. It is the lowest-risk, highest-fit standalone popup-panel migration.
2. **Operations tab**: migrate `TaskQueueModal` and `RunnersModal` together, with `ActivityModal` as a secondary subview.
   Do not spend two Admin Center tabs on overlapping live-runtime panels.
3. **Agent Restore tab**: migrate `SavedAgentGroupRevivalModal` and the custom dismissed-agent search flow after Logs and
   Operations. It is a strong archive-management fit, but needs more host/callback and async-loading work than Logs.
