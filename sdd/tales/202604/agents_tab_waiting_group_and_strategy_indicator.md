---
name: Agents tab — "Waiting" status bucket + grouping-strategy indicator
description: Add a dedicated "Waiting" bucket to BY_STATUS grouping on the ACE TUI
  Agents tab, and surface the active grouping strategy in the AgentInfoPanel header.
create_time: 2026-04-26 03:45:01
status: done
prompt: sdd/prompts/202604/agents_tab_waiting_group_and_strategy_indicator.md
---

# Agents tab — "Waiting" status bucket + grouping-strategy indicator

## 1. Motivation

The ACE TUI Agents tab supports three grouping strategies cycled with `g`: `STANDARD` (project / ChangeSpec hierarchy),
`BY_DATE` (Today / Yesterday / This Week / Earlier), and `BY_STATUS` (Needs Attention / Running / Failed / Done).

Two real problems today:

1. **`WAITING` agents are split awkwardly.** Agents in status `WAITING` get bucketed by whether they have a `wait_until`
   timestamp:
   - `WAITING` _with_ `wait_until` (timer-driven `%wait:5m`, `%wait:1430`) currently lands in **Running** even though
     the agent isn't doing anything — it's just counting down.
   - `WAITING` _without_ `wait_until` (paused on user input) lands in **Needs Attention**.

   So a user scanning **Running** to see what's actually executing is shown a mix of live agents and inert timers, and
   there is no single place to see "what is currently parked / blocked but not requiring my intervention."

2. **No visible signal for which grouping strategy is active.** Cycling `g` only emits a 1.5s toast. After the toast
   fades, the only cue is the shape of the tree — which is fine for an experienced user but invisible to anyone glancing
   at the tab. There is no equivalent of the existing `[view: file]` bracket badge that the AgentInfoPanel already uses
   for view modes.

Both gaps live in the same surface (the Agents tab header + the BY_STATUS bucketing) and benefit from being designed
together so the new bucket reads cleanly in the new badge.

## 2. Design

### 2.1 New bucket: "Waiting"

Add **Waiting** as a first-class bucket in `BY_STATUS`. Final order:

```
Needs Attention   ▲   user must act (failed-not-retried, paused-on-input, plan-done, …)
Running           ▶   actively executing
Waiting           ⏳   blocked but progressing on its own (timer wait, dependency wait)
Failed            ✗   failed and already retried (handed-off)
Done              ✓   completed
```

**Bucket assignment (proposed `_status_bucket_for` rules):**

| Agent state                                              | Today           | Proposed                                    |
| -------------------------------------------------------- | --------------- | ------------------------------------------- |
| `DONE`                                                   | Done            | Done                                        |
| `WAITING` + `wait_until` set                             | Running         | **Waiting**                                 |
| `WAITING` + no `wait_until` + non-empty `waiting_for`    | Needs Attention | **Waiting**                                 |
| `WAITING` + no `wait_until` + no `waiting_for`           | Needs Attention | Needs Attention (unchanged — user must act) |
| `QUESTION`, `PLAN APPROVED`, `PLAN DONE`, `EPIC CREATED` | Needs Attention | Needs Attention                             |
| `FAILED*` + no `retried_as_timestamp`                    | Needs Attention | Needs Attention                             |
| `FAILED*` + `retried_as_timestamp`                       | Failed          | Failed                                      |
| anything else                                            | Running         | Running                                     |

The semantic line we are drawing: **Needs Attention** = "you need to act"; **Waiting** = "agent is blocked but nothing
is asked of you." A `WAITING` agent with no timer and no `waiting_for` _is_ asking the user something (implicitly — it's
parked with nothing to unblock it), so it stays in Needs Attention.

**Why this split is worth it:**

- Restores the integrity of "Running" — only agents actually executing live there.
- Stops "Needs Attention" from quietly absorbing dependency-waits, which aren't actionable for the user.
- Gives users a single place to monitor `%wait` timers (the original ask).

**Bucket position in the order:** Waiting goes _after_ Running because Running is the highest-velocity state and users
scanning top-to-bottom expect "most-active first." Putting Waiting between Running and Failed also means the failure
buckets stay grouped at the bottom.

**Glyph:** `⏳` — distinct from the existing four (`▲ ▶ ✗ ✓`), reads as "time / blocked / will resume on its own," and
renders consistently in monospace terminals (single cell).

### 2.2 Grouping-strategy indicator in the header

Extend `AgentInfoPanel` with a `[group: <label>]` badge that follows the existing `[view: …]` convention.

**Visual placement** (left → right within the existing top bar):

```
Agents: 12/47   filter: foo   [view: file]   [group: by status]   (auto-refresh in 4s)
```

**Mode → label & color** (each strategy gets a distinct accent so the eye learns to associate hue with mode):

| Mode        | Label       | Color          | Rationale                                         |
| ----------- | ----------- | -------------- | ------------------------------------------------- |
| `STANDARD`  | `default`   | dim italic     | Matches the visually quietest tree, not noisy.    |
| `BY_DATE`   | `by date`   | bold `#87D7FF` | Same cyan as `Agents:` header — "time-of-things." |
| `BY_STATUS` | `by status` | bold `#FFAF87` | Warm amber — matches the bucket-glyph palette.    |

Brackets and the `group:` prefix render `dim` (matching `[view: …]`). The badge is **always shown** (never empty), so
the indicator is permanent and learnable rather than appearing only after the user has cycled.

**Optional polish — discoverability:** append a dim ` (g)` after the label, mirroring the `(auto-refresh in Ns)`
parenthetical. Final form: `[group: by status (g)]`. Settle whether to include this during code review; defaulting to
**yes** because the badge is the only place outside the help modal that surfaces the binding.

**Why the header (not the footer):** The `keybinding_footer.py` rules in `src/sase/ace/AGENTS.md` reserve the footer for
_conditional_ keymaps (sometimes-available actions). Grouping is always available on the agents tab, so the footer is
the wrong surface. The header bar already carries persistent metadata (counts, filter, view, refresh) — the strategy
indicator belongs there.

**Toast change:** keep the existing 1.5s `Grouping: <label>` toast on cycle. The badge confirms the durable state; the
toast confirms the _change_. Remove the toast only if it proves redundant during dogfooding.

### 2.3 Out of scope

- No new keybinding (the existing `g` cycle is sufficient).
- No reordering of the cycle itself (`STANDARD → BY_DATE → BY_STATUS → STANDARD` is unchanged).
- No new strategy (e.g. `BY_PROVIDER`) — orthogonal feature.
- No change to `STANDARD` or `BY_DATE` bucketing.
- Footer keybinding rendering — unchanged, per the AGENTS.md convention.

## 3. Implementation outline

Implementation should be small and contained. Phasing isn't necessary — both pieces ship together.

1. **Bucketing logic** — `src/sase/ace/tui/models/agent_groups.py`
   - Insert `"Waiting"` into `_STATUS_BUCKETS` at index 2.
   - Update `_status_bucket_for()` per §2.1, including the `waiting_for` check.
   - Update the `_NEEDS_ATTENTION_STATUSES` TODO comment to reflect the new split.

2. **Glyph** — `src/sase/ace/tui/widgets/_agent_list_styling.py`
   - Add `"Waiting": "⏳"` to `_STATUS_BUCKET_GLYPHS`.
   - Pick a complementary color for the bucket header (consistent with existing palette — likely a soft amber/yellow
     that's visibly distinct from the warning red of `Failed` and the active green of `Running`).

3. **Header badge** — `src/sase/ace/tui/widgets/agent_info_panel.py`
   - Add `_grouping_mode: str` instance field and `update_grouping_mode(label: str) -> None` setter.
   - Add `_GROUPING_MODE_STYLES` dict mirroring `_VIEW_MODE_STYLES`.
   - Render `[group: <label>]` segment in `_update_display()` between the `[view: …]` segment and the auto-refresh
     segment. Always emit it (no empty-string suppression).

4. **Wire-up** — `src/sase/ace/tui/app.py` (and/or wherever `AgentInfoPanel.update_view_mode` is currently called)
   - Push the current grouping label on app init and on every `action_cycle_grouping_mode` invocation (likely just after
     the existing `_refilter_agents()` call in `_grouping.py`).
   - Reuse `_MODE_LABELS` from `actions/agents/_grouping.py` as the source of truth for label strings to avoid drift.

5. **Help modal** — `src/sase/ace/tui/widgets/help_modal.py`
   - Update the description for `g` to mention all four buckets including **Waiting**.
   - Mention the new header badge in the relevant section.
   - Respect the `_BOX_WIDTH = 57` / `_CONTENT_WIDTH = 50` invariants and the 32-char keybinding-description cap from
     `src/sase/ace/AGENTS.md`.

6. **Tests**
   - `tests/ace/tui/models/test_agent_groups_grouping_mode.py` — add cases:
     - `WAITING + wait_until` → `Waiting` (replacing the existing "stays in Running" assertion).
     - `WAITING + waiting_for` (no `wait_until`) → `Waiting`.
     - `WAITING + no wait_until + no waiting_for` → still `Needs Attention`.
     - Bucket sort order includes `Waiting` between `Running` and `Failed`.
   - `tests/ace/tui/test_agent_grouping_cycle.py` — confirm the toast/cycle still passes; add coverage for the new label
     feeding into the panel (or split into a focused panel test).
   - New `tests/ace/tui/widgets/test_agent_info_panel.py` (or extend the existing one) — assert that
     `update_grouping_mode("by status")` yields a `[group: by status]` segment with the expected style.
   - Run `just check` before completion.

7. **Docs sweep** — search `plans/`, `home/dot_config/nvim/`, and any sase-ace user docs for "Needs Attention",
   "Running", "Failed", "Done" lists and append "Waiting." Update screenshots only if the user asks (defer otherwise).

## 4. Risks & open questions

- **`waiting_for` semantics.** Need to confirm that an agent with non-empty `waiting_for` in any non-DONE, non-FAILED
  status should bucket as Waiting (e.g. status=`RUNNING` while waiting on a child). If that's a real state, the rule
  generalizes from "WAITING + waiting_for" to "non-terminal + waiting_for". Worth a quick check before coding — a
  one-line tweak either way.
- **Existing `BY_STATUS` muscle memory.** Power users who learned that timer-waits sit under Running will briefly see
  the count there drop. The toast + new badge + help-modal update mitigates this; calling it out in the next release
  notes is enough.
- **Color choice for the `by status` badge accent.** `#FFAF87` is a proposal; the final palette pick belongs in the
  implementation PR alongside a quick screenshot.
- **`(g)` hint in the badge.** Defaulting to including it; trivial to drop if it feels noisy.
