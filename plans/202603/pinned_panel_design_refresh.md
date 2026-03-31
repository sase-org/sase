---
create_time: 2026-03-31 08:43:23
status: done
---

# Pinned Panel Design Refresh (Agents Tab)

## Objective

Redesign the Agents tab pinned panel so it feels intuitive, reliable, and visually polished while preserving
keyboard-first operation and fast refresh behavior.

## Product Goals

- Make panel purpose and focus state immediately obvious at a glance.
- Reduce navigation ambiguity between main list and pinned panel.
- Preserve selection predictability across refreshes and panel transitions.
- Improve information density without visual clutter.
- Keep behavior robust under rapid updates (agent churn, pin/unpin, filtering).

## UX Principles

- Clear hierarchy: main list remains primary; pinned panel is a deliberate secondary lane.
- Focus affordance: active panel should be unmistakable via both border/title and list-row behavior.
- Action discoverability: concise keyboard hints and empty-state messaging should teach the feature.
- Stable mental model: pinning/unpinning should move items deterministically and keep selection coherent.

## Proposed Design

### 1) Panel Header + State Communication

- Replace the static pinned title with a dynamic title that communicates both count and focus.
- Title patterns:
  - Focused: `📌 Pinned (N) • ACTIVE`
  - Unfocused: `📌 Pinned (N)`
  - Empty (hidden) state remains auto-hidden to avoid dead UI chrome.
- Add border subtitle with a compact key hint when pinned exists:
  - On main focus: `<J> focus pinned`
  - On pinned focus: `<J> back to list`

### 2) Visual Refresh for the Pinned Container

- Strengthen visual identity with a subtle “card” feel:
  - Slightly richer base border for inactive state.
  - Brighter border + tinted background when focused.
  - Reduced visual noise by tuning padding and max-height.
- Ensure contrast/legibility remains high in terminal themes by using existing palette style conventions.

### 3) Better Empty/Transition Behavior

- Keep auto-hide when no pinned agents.
- Tighten focus fallback rules so focus never points to a non-existent panel.
- Ensure pin/unpin transitions preserve local context:
  - Pinning from main moves focus to pinned and keeps selection on that moved agent.
  - Unpinning from pinned returns to main and keeps selection on that moved agent.

### 4) Reliability Improvements in Selection Flow

- Centralize panel-selection sync for click/keyboard navigation:
  - When a panel selection event is received, update global index first, then refresh UI once.
  - Avoid intermediate states where focus and selected index are briefly inconsistent.
- Keep debounced detail updates intact for j/k responsiveness.

### 5) Footer + Help Consistency

- Keep existing footer labels (`pinned` / `list`) but ensure they always match current panel focus.
- Verify help text remains aligned with behavior (`J` toggles focus).

## Implementation Plan

1. Update panel focus styling and dynamic title/subtitle behavior in agents display mixin.
2. Refine pinned container and list CSS for clearer active/inactive appearance.
3. Adjust selection-change handling to enforce deterministic index/focus sync during panel clicks.
4. Improve pin/unpin selection continuity logic to keep the moved agent selected after panel migration.
5. Add/extend unit tests for:
   - Dynamic title/subtitle states.
   - Panel focus fallback and selection continuity on pin/unpin.
   - Selection event handling consistency across panel boundaries.
6. Run lint/type/tests via project check pipeline.

## Validation Strategy

- Unit tests around panel state machine and event handlers.
- Headless TUI checks (`sase ace --agent --keys ...`) for interaction snapshots:
  - pin -> focus pinned -> unpin -> return to list.
  - J toggling with/without pinned entries.
- Full repo gate: `just check`.

## Risks / Mitigations

- Risk: Overly decorative styling could hurt readability in some terminals.
  - Mitigation: Keep changes conservative, favor border/background cues over dense color blocks.
- Risk: Selection jumps during asynchronous refresh.
  - Mitigation: Reuse existing index maps and refresh pathways; add targeted tests for event ordering.

## Non-Goals

- No changes to pin persistence schema.
- No new keybindings.
- No runtime-specific behavior divergence.
