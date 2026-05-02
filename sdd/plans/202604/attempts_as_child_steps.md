---
create_time: 2026-04-23 15:44:38
status: done
prompt: sdd/prompts/202604/attempts_as_child_steps.md
---

# Plan: Retry Attempts as Child Entries in the `sase ace` Agents Tab

## Product Goal

When an agent in the `sase ace` TUI has gone through one or more retries, the user currently only sees a compact summary
under `AGENT DETAILS → Retries: N/M` with one-line `error_snippet` per attempt. To see the full failure (`error_full`)
or the partial reply from a specific prior attempt, the user has to `cat` files on disk.

We want each retry attempt to be **selectable as a first-class child row** beneath the agent in the Agents tab.
Selecting a child row should make the right-hand detail pane render as though that attempt _were_ the agent — i.e., show
the full error, the prompt used, and the partial `live_reply.md` captured for that attempt. The currently-running (or
last) attempt remains represented by the parent row as today, so the collapsed view is unchanged and existing muscle
memory keeps working.

### User-visible shape

Collapsed:

```
[agent] pat_fix_far_past_1 (RUNNING) ↻2 (4 steps, 2 attempts) @p
```

Expanded:

```
[agent] pat_fix_far_past_1 (RUNNING) ↻2 (4 steps, 2 attempts) @p
  ↳ Attempt 1 · 13:40:30 · failed
  ↳ Attempt 2 · 13:52:44 · failed
  <step rows continue as today>
```

Selecting `Attempt 1` / `Attempt 2` swaps the detail panel into an **attempt-pinned** view: the full stderr /
`error_full` text, the prompt, and the reply content captured in `attempts/<N>/live_reply.md`. The parent row keeps
behaving exactly like it does today (the currently-live attempt).

## Why this shape (vs. alternatives)

- **Why children, not a dedicated key / modal?** The existing `V` toggle already stitches prior attempts into the reply
  stream, but it's a single blob — the user can't isolate one attempt, can't see `error_full`, and can't jump between
  attempts. A list child makes each attempt a navigable, selectable object with a full standalone view, which is what
  the user asked for.

- **Why leave the parent row as "current attempt" instead of creating an N+1 child for the live run?** It preserves the
  existing default (one row per agent, select it and see what's happening _now_) and matches how users already read the
  list. Introducing a "current" child would force everyone to expand to reach the live view.

- **Why reuse the step-expansion pattern?** `agent_list.py` already has a mature `parents_with_visible_children` /
  `fold_counts` / `_compute_fold_annotation` machinery for steps. Grafting attempts onto the same machinery keeps
  behavior (annotations, fold keys, rendering idioms) coherent and avoids introducing a parallel vocabulary.

## Scope

In scope:

1. Render attempt rows as children in the Agents `OptionList` when an agent has `attempt_history` and is expanded.
2. Selection of an attempt child routes to a new "attempt-pinned" detail view.
3. Detail view renders: full `error_full`, the prompt (the agent's current prompt, shared across attempts), and the
   attempt's `live_reply.md` content. Header shows which attempt is being viewed and how/when it failed.
4. Fold annotation updated to include an attempt count alongside the step count (single parent line, no separate
   "attempts" header).
5. Footer / keybinding hints updated so users know attempts are selectable.

Out of scope (noted, not done):

- Per-attempt archived thinking/files panels. `run_agent_exec_attempts.py` only snapshots `live_reply.md` +
  `live_reply_timestamps.jsonl`, so we can't reconstruct thinking/files history. Those sub-panels show "not archived for
  prior attempts" in the attempt-pinned view.
- Deprecating the existing `V` merged-reply toggle. It stays; per-attempt children are additive.
- Changing on-disk formats. All data already exists.

## Architecture Outline

### 1. Selection identity: (agent, attempt_number | None)

Today `app.current_idx: int` indexes into `self._agents`. That's insufficient — an attempt child points at _the same
agent_ as its parent. Two viable approaches:

- **(A) Wrap selection in a small value object.** Introduce `SelectedEntry = (agent_id, attempt_number | None)` and
  carry it alongside `current_idx`. The OptionList's per-row id becomes this tuple; the detail panel consumes it.
- **(B) Flatten attempts into the agents list.** Each attempt becomes its own pseudo-Agent in the index mapping. Cheap
  to wire but pollutes every consumer of `self._agents`.

Recommend **(A)**. The list-index → entry mapping already exists (`_main_panel_indices` / `_pinned_panel_indices`) and
converting those to `SelectedEntry` values is local. Downstream code that wants "the agent" just reads `entry.agent`;
the new detail-rendering path reads `entry.attempt_number`.

### 2. List rendering (`src/sase/ace/tui/widgets/agent_list.py`)

- `update_list()` currently inserts per-step child options when the parent is in `parents_with_visible_children`. Extend
  the loop: when the current agent is in `parents_with_visible_children` _and_ has `agent.attempt_history`, emit one
  `Option` per attempt _before_ the step rows. Each option's prompt is styled text similar to what
  `_agent_display_parts.py:305-328` already produces for the Retries header —
  `Attempt N · HH:MM:SS [fallback] · failed: <short error>` — but in list styling (dim/indented).
- Each option carries a stable `id` encoding `(agent_raw_suffix, attempt_number)` so the selection handler can recover
  both.
- `_compute_fold_annotation` updated: the parent annotation becomes `(N steps, M attempts)` when both exist. If only
  attempts exist (no workflow steps), it becomes `(M attempts)`. Expansion state already covers the "hidden/shown"
  affordance; attempts are either all shown or all hidden with the parent's existing fold key.
- Auto-expand policy: an agent with prior attempts auto-joins `parents_with_visible_children` on first load when
  `retry_count > 0`, so the failure evidence is immediately reachable. User can still collapse.

### 3. Selection dispatch (`src/sase/ace/tui/actions/event_handlers.py`, `app.py`)

- `on_agent_list_selection_changed` decodes the option id. If it's an attempt child, set `current_idx` to the parent
  agent's global index **and** set a new `current_attempt_number: int | None` on the app (None = "live/current").
- `watch_current_idx` stays as today; add a `watch_current_attempt_number` that calls the same refresh hook. Both flow
  into `AgentDetail.update_display(agent, attempt_number=...)`.

### 4. Detail panel (`src/sase/ace/tui/widgets/agent_detail.py` + `prompt_panel/_agent_display.py`)

- `AgentDetail.update_display` grows an optional `attempt_number` arg. When provided:
  - Header block replaces "Retries: …" summary with a banner: `Viewing Attempt N of M (failed at HH:MM:SS)` plus the
    full `error_full` text rendered verbatim in an error style.
  - Reply content is loaded from `attempts/<N>/live_reply.md` (path already on `AttemptRecord`). Reply-stream merging is
    bypassed — attempt-pinned mode is exclusive with the existing merged / current-only toggle.
  - Prompt panel still renders the agent's prompt unchanged (prompt is invariant across retries by design).
  - Files / Thinking sub-panels show a short placeholder noting that those aren't archived per-attempt.
- `_attempt_view_mode` stays valid only when `attempt_number is None`. The `V` footer key is hidden when viewing an
  attempt-pinned entry.

### 5. Footer / discoverability (`src/sase/ace/tui/widgets/keybinding_footer.py`)

- When parent row is selected and `agent.attempt_history` is non-empty, add a hint like `↲ attempts` or repurpose the
  existing fold key.
- When an attempt child is selected, show `esc parent` (or equivalent) that snaps selection back to the parent agent,
  for quick return to the live view.

## File Change Inventory (high level)

| File                                                            | Change                                                                                                                                                |
| --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `src/sase/ace/tui/widgets/agent_list.py`                        | Emit attempt child `Option`s; extend `_compute_fold_annotation`; stable ids; auto-expand on retries.                                                  |
| `src/sase/ace/tui/models/agent.py`                              | (Possibly) small helper on `AttemptRecord` to load `live_reply.md` lazily; already has paths.                                                         |
| `src/sase/ace/tui/app.py`                                       | Add `current_attempt_number` state + watcher; plumb to refresh.                                                                                       |
| `src/sase/ace/tui/actions/event_handlers.py`                    | Decode attempt-child option ids; set both indices.                                                                                                    |
| `src/sase/ace/tui/actions/agents/_panels.py`                    | Gate `toggle_attempt_view` when attempt-pinned.                                                                                                       |
| `src/sase/ace/tui/widgets/agent_detail.py`                      | `update_display(agent, attempt_number=None)`; attempt-pinned rendering path.                                                                          |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py`       | New `_render_attempt_pinned()`; skip merged-mode when attempt-pinned.                                                                                 |
| `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` | Factor the per-attempt line renderer so list and detail banner share styling.                                                                         |
| `src/sase/ace/tui/widgets/keybinding_footer.py`                 | Add/guard hints for the new flow.                                                                                                                     |
| `src/sase/ace/tui/bindings.py`                                  | Optional new binding (`esc` to parent, or reuse).                                                                                                     |
| tests under `tests/`                                            | Unit tests for: list expansion with attempts, option-id decode → SelectedEntry, `update_display(attempt_number=N)` renders `error_full` + reply file. |

## Edge Cases

- **Agent with no retries** — attempt_history empty, nothing changes (no child rows, no annotation bump, no extra
  state).
- **Agent completed successfully after retries** — still show attempts as children (past failures remain interesting).
  Current attempt's parent row reflects DONE.
- **Missing `live_reply.md` on disk** — render "(no partial reply captured)" gracefully; don't crash.
- **Running attempt_number mid-write** — `run_agent_exec_attempts.py` uses atomic rename, so we only observe
  fully-written `attempts/<N>/` dirs. Safe.
- **Refresh loop rebuilds the list** — preserve the (agent, attempt_number) selection across refreshes by looking up
  option id, not raw index.

## Implementation Order

1. Data plumbing: add `current_attempt_number` to the app, extend `AgentDetail.update_display` signature (no-op on the
   default path).
2. List rendering: attempt-child options + updated fold annotation + auto-expand.
3. Selection decode in `on_agent_list_selection_changed`.
4. Attempt-pinned renderer in `_agent_display.py` + detail banner.
5. Footer / keybinding touch-ups.
6. Tests + manual verification against a real `.sase/projects/.../artifacts/...` tree.

## Validation

- Unit: option id encode/decode; list produces the right rows for an agent with 2 attempts; detail renderer, given a
  fixture `attempt_meta.json` + `live_reply.md`, emits the expected Rich text.
- Manual: reproduce against a failed-retry agent (point at a real artifacts dir); verify `V` still works on the parent,
  attempt children show full stderr, `esc`/back restores live view.
- `just check` must pass.
