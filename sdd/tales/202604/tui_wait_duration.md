---
create_time: 2026-04-10 22:47:38
status: done
prompt: sdd/prompts/202604/tui_wait_duration.md
---

# Plan: TUI Duration Wait Visual Support

## Goal

Make duration-based `%wait` agents visually rich and informative in the `sase ace` Agents tab. Currently, a `%wait:10m`
agent shows as RUNNING with a BEGIN timestamp and no indication that it's sleeping. After this change, users will see:

- **WAITING status** with a **live countdown** in the agent list (e.g., `WAITING (4m32s)`)
- **"Waiting for:"** line in details panel showing the duration and remaining time
- **WAIT timestamp** (not BEGIN) until the agent actually starts running

## Design

### Live Countdown in Agent List

The RETRYING status already shows a live countdown (`RETRYING (45s)`) — this is the precedent. For WAITING agents with a
duration, display similarly:

```
  [agent] deploy_tests (WAITING) (4m32s)     ← duration-only wait
  [agent] deploy_tests (WAITING) (4m32s)     ← mixed (agents + duration)
  [agent] deploy_tests (WAITING)             ← agent-only wait (no countdown)
```

The countdown computes: `remaining = (start_time + wait_duration) - now`. When remaining reaches 0, the agent either
transitions to RUNNING (duration-only) or continues waiting for agent deps (mixed case, where the countdown disappears
but WAITING persists).

Format: `Xh Ym Zs` for >1h, `Ym Zs` for >1m, `Zs` for <1m. Always show the two most significant non-zero units.

### Details Panel: "Waiting for:" Line

Currently shows `Waiting for: agent1, agent2` for agent-name waits. Extend to show duration info:

```
Waiting for: 10m (4m32s left)                ← duration-only
Waiting for: agent1, agent2 + 10m (4m32s left)  ← mixed
Waiting for: agent1, agent2                  ← agent-only (unchanged)
```

The `(Xm Ys left)` portion uses dimmed styling to avoid visual noise when the primary info is the dependency list.

### Timestamps: WAIT vs BEGIN

This already works correctly! The existing `timestamps_display` property shows:

- "WAIT" when agent has `status == "WAITING"` and no `run_start_time`
- "WAIT" + "BEGIN" when `run_start_time` exists (agent waited then started)

No changes needed here — just ensuring duration-only waits get WAITING status (see below).

### Backend: Write `waiting.json` for Duration-Only Waits

Currently, duration-only waits skip writing `waiting.json`, so the TUI can't detect them as WAITING. Fix: always write
`waiting.json` when there's a duration, even with no agent-name deps. Structure:

```json
{
  "waiting_for": [],
  "cl_name": "...",
  "timestamp": "...",
  "wait_duration": 600.0
}
```

This lets the TUI's existing `waiting.json exists → WAITING` logic work unchanged for status detection. The file is
cleaned up when the wait completes (existing behavior for agent-name waits).

### Agent Model: `wait_duration` Field

Add `wait_duration: float | None` to the `Agent` dataclass. Populated from either:

- `waiting.json["wait_duration"]` (preferred, since it reflects live state)
- `agent_meta.json["wait_duration"]` (fallback)

The countdown uses `agent.start_time + agent.wait_duration` as the target epoch.

## Phases

### Phase 1: Write `waiting.json` for duration-only waits

In `src/sase/axe/run_agent_phases.py`, modify `wait_for_dependencies()`:

- In the duration-only branch, write `waiting.json` with `waiting_for: []` and `wait_duration` before sleeping.
- Clean up `waiting.json` after sleep completes (same as agent-name path).

### Phase 2: Add `wait_duration` field to Agent model

In `src/sase/ace/tui/models/agent.py`:

- Add `wait_duration: float | None = None` field to the `Agent` dataclass.

### Phase 3: Read `wait_duration` in artifact loader

In `src/sase/ace/tui/models/_loaders/_artifact_loaders.py`, in `enrich_agent_from_meta()`:

- Read `wait_duration` from `waiting.json` (already being opened for `waiting_for`).
- Fallback: read from `agent_meta.json["wait_duration"]`.
- Set `agent.wait_duration`.

### Phase 4: Live countdown in agent list

In `src/sase/ace/tui/widgets/agent_list.py`, in the status display section:

- When `agent.status == "WAITING"` and `agent.wait_duration` is set, compute remaining time from
  `agent.start_time + timedelta(seconds=agent.wait_duration) - now`.
- Format as compact duration string (e.g., `4m32s`, `1h5m`).
- Display: `WAITING (4m32s)` in amethyst bold, countdown portion slightly dimmed.

### Phase 5: Duration info in details panel "Waiting for:" line

In `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py`, in `build_header_text()`:

- When `agent.wait_duration` is set, format the total duration (e.g., "10m").
- Show countdown remaining in dimmed parens: `(4m32s left)`.
- Handle mixed case: `agent1, agent2 + 10m (4m32s left)`.
- Handle duration-only: `10m (4m32s left)`.

### Phase 6: Tests

- Test the countdown formatting helper (compact duration display).
- Test that `enrich_agent_from_meta()` populates `wait_duration` from both sources.
- Test that the agent list renders the countdown for WAITING agents with duration.

### Phase 7: Lint and check

Run `just install && just check`.

## Out of Scope

- Interactive modification of duration waits from the TUI (future: extend WaitModal).
- Progress bar visualization (countdown text is sufficient and consistent with RETRYING precedent).
- Duration countdown in notifications or Axe tab.
