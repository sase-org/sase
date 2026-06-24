---
create_time: 2026-06-24 16:26:48
status: done
prompt: sdd/prompts/202606/wait_modal_redesign.md
---
# Plan: Redesign the `w` "Wait" panel as a pop-up with agent completion + time keyword

## Goal & product context

On the Agents tab, pressing `w` opens the **Wait** panel, which lets the user defer/redirect an agent's launch. Today
that panel (`WaitModal`) is a bare, full-bleed `ModalScreen` with a single free-text input: the user types a
comma-separated list of agent names (no assistance), and the modal returns a raw string. It has three weaknesses:

1. It visually takes over the whole screen (it is a `ModalScreen` with **no** sizing CSS, so its `Container` fills the
   terminal) rather than reading as a focused pop-up.
2. It has no support for the **time keyword** — the recently shipped `%wait(time=…)` / `#t` time-floor feature is
   unreachable from this panel. You can only wait on agents, never on a clock.
3. To wait for an agent you must remember and hand-type its name. There's no way to pick from the agents you're already
   looking at, and no metadata to disambiguate similarly named ones.

This redesign turns Wait into a compact, beautiful pop-up that:

- Reads as a centered dialog (sized like every other modal in the app), not a screen takeover.
- Lets you **build a wait spec**: zero-or-more agent dependencies **and/or** an optional time floor — in one place.
- Lets you **pick an agent from a live completion menu** of the agents currently visible on the Agents tab, with enough
  per-agent metadata (status, runtime/model, start time, runtime duration, role/tag) to identify it at a glance.
- Live-validates the time field and shows a human preview of what the wait will do.

The wait the panel produces is expressed in the **canonical `%wait(<agents>, time=<token>)` spelling** that the prior
migration established — so this feature rides on existing, tested parsing and storage. No new wire/storage format.

## Background: how Wait works today (confirmed in code)

- **Keymap:** `w` → `action_reword` (a shared binding). On the Agents tab `action_reword` dispatches to `_wait_agent`
  (`AgentWaitResumeMixin`); on other tabs it falls through to the ChangeSpec reword. Keep this dispatch unchanged.
- **Eligibility:** `_wait_agent` only proceeds for agents whose status is `STARTING`, `WAITING`, or `RUNNING`, and that
  have an artifacts dir.
- **Current modal:** `WaitModal(ModalScreen[str | None])` — one input, returns the trimmed string (`""` = run now,
  `None` = cancel). It is exported from `modals/__init__.py` and pushed from `_wait_agent`.
- **Apply paths (`AgentWaitResumeMixin`):**
  - `is_running = status in {STARTING, RUNNING}`.
  - **WAITING agent →** `_apply_wait`: if names given, rewrite `waiting.json` (`waiting_for` set; `wait_duration` /
    `wait_until` **cleared**); if empty, write `ready.json` (run now). In-place, preserves the agent's identity.
  - **RUNNING/STARTING agent →** `_apply_wait_running`: confirm-kill, then relaunch with `%w:<name>` **prepended** to
    the agent's raw prompt.
- **Canonical wait-target name:** the value to put in `waiting_for` is the target agent's resolvable name. The helper
  `_agent_prompt_name(agent)` already returns exactly this string (family base for family roots, else
  `agent.agent_name`) and returns `None` for agents that can't be waited on (no name). The runtime dependency resolver
  matches an entry against the target's `agent_meta.json` `name` (with family/workflow fallbacks).

### The reliability constraint that shapes the design

The wait-evaluation process (`run_agent_wait.py::wait_for_dependencies`) reads `wait_duration` / `wait_until` **once at
launch** and then loops on local variables — it never re-reads `waiting.json` for the time floor. The `wait_checks` chop
re-reads only `waiting_for` (to write `ready.json`). Therefore:

- Editing `waiting_for` in an already-waiting agent's `waiting.json` **is** honored (chop re-reads it). ✅
- Writing/changing a `wait_duration` / `wait_until` in an already-waiting agent's `waiting.json` would be **silently
  ignored** by the already-running wait loop. ❌

**Consequence:** a time floor can only be applied reliably through the launch path. So the panel keeps the lightweight
in-place edit for the _dependency-only_ case, and routes any change that sets a time floor through kill + relaunch with
a canonical `%wait(...)` directive (the same proven mechanism `_apply_wait_running` already uses). See Decision D1.

## Design of the new Wait pop-up

A centered modal (`WaitModal`, rewritten in place to keep the export/call sites stable) with two sections plus a footer:

```
┌─ Wait ──────────────────────────────────────────────────────┐
│ Wait for agents to finish and/or hold until a time floor.    │
│                                                              │
│ Agents   [ planner, cod▌                                  ]  │  ← free text; comma-separated
│   ┌────────────────────────────────────────────────────┐    │
│   │ ● coder       RUNNING   claude · xhigh   12:03  2m   │    │  ← live-filtered completion menu
│   │ ● coder.review WAITING  gpt-5            12:05   —   │    │     (visible agents + metadata)
│   │   planner     PLAN DONE claude           11:40  18m  │    │
│   └────────────────────────────────────────────────────┘    │
│                                                              │
│ Time     [ 5m▌                                            ]  │  ← duration or absolute token
│   floor: waits 5m after deps        e.g. 5m · 1h30m · 1430   │  ← live preview / validation
│                                                              │
│ ⏎ apply   ·   ^r run now   ·   esc cancel                    │
└──────────────────────────────────────────────────────────────┘
```

### Agents combobox (the completion menu)

- An `Input` with a dropdown `OptionList` directly beneath it (a self-contained combobox local to the modal — it does
  **not** reuse the prompt-bar completion machinery, which is tightly coupled to `PromptInputBar`).
- **Candidates** = the agents currently visible on the Agents tab (respecting the active panel/tag filter, search query,
  and h/l fold state). Source these from the rendered rows of the active `AgentList` (see "Plumbing"). Exclude:
  - the selected agent itself (no self-wait), and
  - agents with no waitable name (`_agent_prompt_name(agent) is None`).
- **Filtering:** typing filters the dropdown on the _active fragment_ (text after the last comma), matching against the
  agent's display name and waitable name. Empty fragment shows all candidates.
- **Selection:** ↑/↓ highlight; Enter or Tab on the dropdown replaces the active fragment with the candidate's
  `_agent_prompt_name` plus `", "`, so the user can immediately pick/type another. This satisfies the "multiple agents"
  case while optimizing for the common single pick.
- **Row content (the per-agent metadata):** a status dot/badge colored by status, the primary label (`agent_name` or
  `display_name`, bold), then dim secondary fields: `status`, `llm_provider`/`model`, `start_time_short`,
  `duration_display`, and `agent_family_role`/`tag` when present. Styled to match the app's existing completion rows so
  it feels native.

### Time field

- A free-text `Input` accepting a duration (`5m`, `1h30m`, `90s`) or an absolute time (`1430`, `260415/0900`).
- **Live validation** via the existing `parse_duration` / `parse_absolute_time` helpers, with a preview line:
  - valid duration → "floor: waits 5m after deps";
  - valid absolute → "until <pretty wall-clock>";
  - non-empty invalid → red error;
  - empty → neutral hint with examples.
- No new parsing — reuse `src/sase/xprompt/_directive_time.py`. The value is passed through as the `time=` token,
  exactly like the `#t` xprompt does.

### Prefill (editing an existing wait)

When opened on an agent that already has a wait, prefill the Agents input from `agent.waiting_for` and the Time field
from `agent.wait_duration` / `agent.wait_until`, rendered back into a human token (seconds → `5m`, ISO → `1430`). A
small reverse-formatter is needed (verify whether one already exists before adding one).

### Result type

The modal dismisses with a small structured result instead of overloading `str | None`, e.g.:

```python
@dataclass
class WaitModalResult:
    agents: list[str]          # waitable names, in order
    time_token: str | None     # validated duration/absolute token, or None
    run_now: bool = False      # user chose "run now" (clear all waits)
```

Dismiss with `None` on cancel. This keeps the apply logic explicit and testable.

## Apply logic (rewritten `AgentWaitResumeMixin` handlers)

Given a `WaitModalResult`, choose the path by agent state, optimizing for reliability:

1. **Run now** (`run_now=True`, or empty spec on a WAITING agent): unchanged behavior — write `ready.json` for a WAITING
   agent; for a RUNNING/STARTING agent this is a no-op with a notify.
2. **WAITING agent, agents-only (no time token):** in-place `waiting.json` edit — set `waiting_for`, clear time fields
   (today's `_apply_wait` path). Instant, preserves identity. ✅
3. **WAITING agent with a time token, OR any RUNNING/STARTING agent:** confirm-kill, then **relaunch** with a canonical,
   **replacement** wait directive prepended:
   - Build `%wait(<agents…>, time=<token>)` (omit the empty part — pure time → `%wait(time=5m)`; pure agents →
     `%wait(a, b)`).
   - For a WAITING agent, **strip the existing wait directives** (`%wait`/`%w`, and any wait-producing xprompt ref such
     as `#t`/legacy `%time`) from the agent's raw prompt first, so the new spec **replaces** rather than **adds** to the
     old wait. (A RUNNING agent has already run past its wait, so its raw prompt carries no live wait — matching today's
     `_apply_wait_running` assumption.)
   - Relaunch via the existing `_finish_agent_launch` flow. The time floor is now established through the proven
     `wait_for_dependencies` launch path and is honored. ✅

The confirm-kill dialog message should reflect the full spec (e.g. "Kill and restart waiting for planner, then 5m").

## Scope of changes (Python, this repo only)

This is a TUI presentation + live-state feature. The agent picker lists _live_ agents and is not shared editor/LSP
completion, so **no `sase-core` change is required** — the only cross-frontend artifact is the canonical `%wait(...)`
spelling, which already exists. (Call this out explicitly so reviewers don't expect a Rust mirror.)

1. **`src/sase/ace/tui/modals/wait_modal.py`** — rewrite `WaitModal` into the two-section pop-up: Agents combobox
   (Input + dropdown `OptionList`), Time input with live validation/preview, footer. Add the local
   `_AgentCompletionList` widget and the `WaitModalResult` dataclass. Reuse the `OptionListNavigationMixin` /
   readline-input conventions from `modals/base.py`. Accept `selected_agent` + the candidate agents + current wait
   prefill in `__init__`.
2. **`src/sase/ace/tui/actions/agents/_wait_resume.py`** — update `_wait_agent` to gather visible candidate agents and
   push the new modal; rewrite the result callback and `_apply_wait` / `_apply_wait_running` to consume
   `WaitModalResult` and implement the state-based apply logic above (including the wait-directive stripping for the
   WAITING-with-time relaunch). Reuse `_agent_prompt_name` for candidate names.
3. **`src/sase/ace/tui/widgets/agent_list.py`** — add a small public accessor, e.g. `visible_agents() -> list[Agent]`,
   that maps the rendered `_row_entries` → `_agents` (skipping banner rows, de-duped, order-preserving). This is the
   reliable "what's on screen right now" source. (Verify how the app reaches the active `AgentList` instance; fall back
   to the app-level `self._agents` filtered by `agent_is_rendered_in_agents_panel` if a single active list isn't cleanly
   addressable.)
4. **`src/sase/ace/tui/styles.tcss`** — add a `WaitModal` block: `align: center middle`; `> Container` sized like peer
   modals (width ~76, `height: auto`, `max-height: 80%`, `border: thick $primary`, `background: $surface`,
   `padding: 1 2`); plus styling for the dropdown list (bounded `max-height`, `solid $secondary` border, highlighted row
   `background: $accent 40%`), section labels (`$secondary` bold), the time preview line (`$success`/`$error`/
   `$text-muted`), and the footer (`$text-muted`). Match the existing completion-row palette for status badges.
5. **Help + footer docs** (per `src/sase/ace/AGENTS.md`): update the `?` help-modal Wait description to mention the
   completion picker and the time keyword; review `keybinding_footer.py` so the `w` description still reads correctly
   (no new key is added — `w` stays bound).

## Tests & verification

- **New modal interaction tests** (none exist today): candidate construction (excludes self + unnamed agents); fragment
  filtering; selecting a candidate appends its waitable name; multi-select via comma; time-field live validation (valid
  duration, valid absolute, invalid, empty); prefill round-trips an existing wait; `WaitModalResult` shape; run-now
  path.
- **Apply-logic tests** in the actions layer: WAITING agents-only → in-place `waiting.json` (time cleared); WAITING +
  time → relaunch with replacement `%wait(...)` and stripped body (assert old `%w:x`/`#t:5m` do not survive);
  RUNNING/STARTING + spec → relaunch with `%wait(...)`; run-now → `ready.json`.
- **Stripping test:** raw prompt `"%w:old #t:5m do the thing"` + new spec `{agents:[new], time:10m}` → relaunch prompt
  waits only on `new` with a 10m floor.
- **Visual snapshot:** add/refresh an ACE PNG snapshot for the new pop-up under the agents-interaction visual suite so
  the "beautiful" layout is pinned (`just test-visual`, accept with `--sase-update-visual-snapshots`).
- **Full check:** `just install` then `just check` in this repo.
- **Manual spot-check** in the TUI: `w` on a WAITING agent (pick an agent from the list, no time → in-place edit); `w`
  with a time floor → confirm-kill + relaunch; `w` on a RUNNING agent; run-now; invalid time shows inline error.

## Decisions to confirm (with recommendations)

- **D1 — Applying a time floor to a WAITING agent.** _Recommend:_ kill + relaunch with the canonical `%wait(...)` (the
  only reliable mechanism, since the wait loop froze its time params at launch); keep the lightweight in-place
  `waiting.json` edit for the _agents-only_ case. _Alternatives:_ (a) always relaunch for WAITING agents too (simpler,
  one path, but a dependency-only tweak would needlessly change the agent's identity and require a kill confirm); (b)
  patch `run_agent_wait.py` to re-read `wait_until`/`wait_duration` each loop so in-place time edits become reliable
  (nicest UX — preserves identity, no prompt munging — but expands scope into sensitive axe runtime, adds re-anchoring
  and concurrency concerns, and the pure-time countdown loops would also need to re-read). Going with the relaunch
  recommendation; (b) is noted as a possible follow-up.
- **D2 — Multi-agent selection.** _Recommend:_ support multiple via the existing comma convention, with the dropdown
  filtering on the last fragment; optimize visuals for the single-pick common case. _Alternative:_ single-select only
  (simpler, but a regression vs. today's comma-separated free text and the bulk-wait feature).
- **D3 — Candidate source.** _Recommend:_ the active `AgentList`'s rendered rows via a new `visible_agents()` accessor
  (exactly "what's on screen"). _Alternative:_ the app-level `self._agents` filtered by
  `agent_is_rendered_in_agents_panel` (close, but may not match fold/children state precisely). Confirm the cleanest
  active-list handle during implementation.
- **D4 — Result type.** _Recommend:_ a small `WaitModalResult` dataclass rather than overloading the old `str | None`
  return, for explicit, testable apply logic.

## Out of scope

- Changing the persisted `waiting.json` schema or the `wait_duration`/`wait_until` fields.
- Changing how waits are _evaluated_ at launch time (no `run_agent_wait.py` semantics change in the primary plan; the
  re-read enhancement is noted only as a D1 alternative).
- The directive-parsing migration itself (`%wait(time=…)` / `#t`) — already shipped; this feature consumes it.
- Any `sase-core` / editor-LSP change.
