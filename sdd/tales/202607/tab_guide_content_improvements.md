---
create_time: 2026-07-07 11:36:06
status: done
prompt: sdd/prompts/202607/tab_guide_content_improvements.md
---
# Improve the `,?` Tab Guide Popup Contents

## Background

The leader-mode `,?` keymap (`tab_guide`) opens `TabGuideModal` (`src/sase/ace/tui/modals/tab_guide_modal.py`), which
shows a per-tab guide:

| Tab    | Widget                 | File                                                |
| ------ | ---------------------- | --------------------------------------------------- |
| Agents | `AgentOnboarding`      | `src/sase/ace/tui/widgets/agent_onboarding.py`      |
| PRs    | `ChangeSpecOnboarding` | `src/sase/ace/tui/widgets/changespec_onboarding.py` |
| AXE    | `AxeOnboarding`        | `src/sase/ace/tui/widgets/axe_onboarding.py`        |

Shared Rich-text helpers live in `src/sase/ace/tui/widgets/_onboarding_common.py`. All keybinding copy is rendered from
the live `KeymapRegistry`, so custom keymaps stay accurate — this property must be preserved by every change below.

These widgets are used **only** by the tab guide modal (the empty-tab quickstart is a separate `TabQuickStart` widget
and is out of scope, as is the `?` help modal).

## Review Findings

I rendered all three guides with the default keymap registry and verified every key claim against the actual action
dispatch code. Results:

### Accuracy (verified against code)

Nearly all key claims are correct (AXE `j`/`k`/`r`/`ctrl+n`/`ctrl+p`/`e`/`X`/`!!`, Admin Center `i`/`u`, PRs `shift+tab`
→ Agents per `TAB_ORDER`, the AXE status-bar anatomy, `~/.sase/projects/` storage path, status lifecycle). Two claims
are accurate-but-misleading:

1. **AXE guide documents `x` twice with contradictory meanings.** The "What is Axe?" card says "`x` start or stop Axe"
   while the "Background commands" card says "`x` kill a running command". Both are true, but only because `x` is
   row-contextual (`_toggle_or_kill_axe_view`: toggles the daemon when the Axe dashboard row is selected, kills the
   selected background command otherwise). Neither card states the condition, so a new user reads a contradiction.
2. **Agents guide: "Works from any tab; shell: `sase ace`."** This mashes two unrelated ideas (the prompt bar works from
   any tab; the TUI is launched with `sase ace`) into one cryptic fragment. Shown _inside_ the TUI, "shell: sase ace" is
   noise at best and confusing at worst.

### Clarity / new-user intuition

3. **Agents guide launch card is too terse.** "`+` pick a project or CL first." doesn't say what `+` does (opens a
   launch-target picker so the agent runs against that project/CL instead of the home workspace) or why you'd want it.
   "home workspace" is also unexplained jargon on the very first card a new user sees.
4. **The Agents guide never explains the Agents tab itself.** It covers launching, the tab bar, plugins, and help — but
   nothing about what appears after you launch: the agent list, the detail panels, or the 2-3 keys needed to inspect a
   finished agent (e.g. `e` open the chat transcript, `enter` jump to the agent's CL, `a` artifacts). The guide for the
   app's default tab is thinner about its own tab than the AXE guide is.
5. **PRs guide has no "how to use this tab" content at all.** It explains the ChangeSpec concept well, but contains
   exactly one keybinding (`shift+tab`, which leaves the tab!). AXE gets two key-driven cards. A new user on the PRs tab
   learns what a ChangeSpec _is_ but not that `d` shows the diff, `s` changes status, `M` mails, `e` opens the spec in
   their editor, or `/` filters the list.
6. **PRs guide: "The commit workflow appends commits and hook results…"** — "commit workflow" is internal jargon; the
   sentence can say the same thing in user terms ("as the agent commits, its commits and hook results appear on the spec
   automatically").

### Consistency between the three guides

7. **Footer copy diverges.** Agents/PRs: "esc closes · ,? reopens this guide on any tab". AXE: "Press ,? on any tab to
   open that tab's guide." (and the AXE footer drops the esc hint entirely).
8. **The help-modal line diverges.** Agents/PRs: "`?` open the help pop-up for this tab"; AXE: "`?` open the full
   keybinding reference for this tab". The AXE phrasing is the more informative one.
9. **The `,?` self-reference line diverges** in wording ("reopen this guide anytime" vs "opens this guide") and position
   (AXE puts it after the sase.sh line; the others before).

### Stale with respect to a new feature

10. **In-modal tab switching is invisible.** Commit `904a3e151` made `tab`/`shift+tab` switch the app tab _while the
    guide is open_, with the guide content following along. No copy mentions this — yet it's exactly the affordance a
    new user touring the app wants ("read all three guides without closing"). The footers and the modal's border
    subtitle ("esc closes") should advertise it.

### Test coverage gap

11. PNG snapshots exist for the AXE and Agents tab guides (`tab_guide_axe_120x40`, `tab_guide_agents_120x40` in
    `tests/ace/tui/visual/test_ace_png_snapshots_tab_guide.py`) but **not for the PRs tab guide**.

## Proposed Changes

### Phase 1 — Shared consistency scaffolding

In `_onboarding_common.py`, add a shared footer builder (e.g. `build_guide_footer(registry)`) used by all three widgets
so the footer can never drift again. Unified footer copy (single line, dim):

> esc closes · tab / shift+tab other tabs' guides · ,? reopens anytime

Also update `TabGuideModal`'s border subtitle from "esc closes" to a short form that includes the tab-switch hint. Keep
the subtitle concise; the footer carries the full sentence.

Unify the recurring help lines in all three "Learn more"/"Get more help" cards to one phrasing each:

- "`?` full keybinding reference for this tab." (adopt the AXE wording)
- Drop the per-card ",? reopen this guide" line entirely — it duplicates the footer, and with the new footer (Phase 1)
  it is stated once, better.

### Phase 2 — Agents guide

- **Launch card:** rewrite for a first-time user.
  - "`space` open the prompt bar and describe a task — this launches an agent in your home workspace." (one sentence
    that says what launching _is_)
  - When launch targets exist: "`+` launch against a specific project or CL instead." (says what it does, not just "pick
    first")
  - Replace "Works from any tab; shell: `sase ace`." with "The prompt bar works from any tab." (drop the shell
    fragment).
- **New "Inspect the results" card** (between the launch card and the tabs card): the missing bridge from "I launched"
  to "I can read what happened". ~3 registry-driven bindings with the same keycap style: `j`/`k` select an agent, `e`
  open a finished agent's chat transcript in your editor, `enter` jump to the CL it produced, `a` browse artifacts. Add
  it to `_STEP_BASE_TITLES` so the step numbering stays contiguous (plugins-card hiding already renumbers).
- Tabs card and plugins card: keep as-is (verified accurate; tab rows already derive from `TAB_ORDER`).

### Phase 3 — PRs guide

- **New "Work the queue" card** (between "How ChangeSpecs get here" and "Learn more") with the core registry-driven
  keys: `j`/`k` move through specs, `d` show the diff, `s` change status, `M` mail for review, `e` open the spec in
  `$EDITOR`, `/` filter with a query.
- Reword the "commit workflow" sentence in user terms (finding 6).
- Keep the `shift+tab` cross-reference line — it's a good touch for the empty-queue first-run case — but make it
  conditional-friendly wording ("No specs yet? `shift+tab` to the Agents tab and launch your first agent.").

### Phase 4 — AXE guide

- Qualify the two `x` mentions (finding 1):
  - What card: "`x` start or stop Axe (with the Axe row selected)."
  - Bgcmd card: "`x` kill the selected running command."
- Reword "edit captured output" → "open the captured output in your editor" (that is what `e` does).
- Move/merge the `,?` line per Phase 1 and adopt the shared footer.
- Minor: "Axe starts with sase ace" → "Axe starts automatically with `sase ace`".

### Phase 5 — Tests & snapshots

- Update the copy assertions in:
  - `tests/ace/tui/widgets/test_agent_onboarding.py`
  - `tests/ace/tui/widgets/test_changespec_onboarding.py`
  - `tests/ace/tui/widgets/test_axe_onboarding.py`
  - `tests/ace/tui/test_agents_onboarding.py`, `tests/ace/tui/test_changespecs_onboarding.py`,
    `tests/ace/tui/modals/test_tab_guide_modal.py` (wherever guide copy is pinned)
- Add unit coverage for the new cards (registry-driven keys appear, custom keymaps are reflected — mirror the existing
  `f1`/`f2` override tests).
- Regenerate the affected PNG goldens (`tab_guide_agents_120x40`, `tab_guide_axe_120x40`) with
  `--sase-update-visual-snapshots`.
- **Add the missing PRs tab-guide PNG snapshot** (`tab_guide_changespecs_120x40`) to
  `test_ace_png_snapshots_tab_guide.py` (finding 11).

## Non-goals

- No keymap/behavior changes — copy, structure, and tests only (plus the modal border subtitle string).
- No changes to the `?` help modal, the empty-tab `TabQuickStart` widget, or the docs site.
- No hardcoded key names in new copy: every binding renders through the `KeymapRegistry` helpers (the Admin Center
  pane-local `i`/`u` remain the one existing, justified exception).

## Verification

- Targeted:
  `pytest tests/ace/tui/widgets/test_*_onboarding.py tests/ace/tui/modals/test_tab_guide_modal.py tests/ace/tui/test_agents_onboarding.py tests/ace/tui/test_changespecs_onboarding.py`
  plus `just test-visual` for the PNG suite.
- Manual: open `sase ace`, press `,?` on each tab, switch tabs with `tab`/`shift+tab` inside the modal, and confirm each
  guide reads correctly at 120x40 and smaller sizes (cards wrap, no truncation).
- `just check` before finishing (note: the llm_provider `default_effort` failures are known pre-existing issues in this
  dev environment).
