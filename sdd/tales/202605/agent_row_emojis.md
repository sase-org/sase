---
create_time: 2026-05-11 21:17:11
status: done
prompt: sdd/prompts/202605/agent_row_emojis.md
---
# Plan: Choose better emojis for stopped and unread agent rows

## Context

The `sase ace` TUI Agents tab renders a right-side **runtime suffix marker** at the end of each agent row. The marker
occupies a single emoji slot just before the elapsed-time / timestamp text, so it is the most scannable per-row state
indicator in the sidebar.

The marker has three mutually exclusive variants, all defined in `src/sase/ace/tui/widgets/_agent_list_render_layout.py`
(lines 40–49):

| Variant         | Emoji  | Style     | When shown                                                                                           |
| --------------- | ------ | --------- | ---------------------------------------------------------------------------------------------------- |
| Live (running)  | 🏃‍♂️     | `#D7AF5F` | `is_ticking=True` — agent is actively executing                                                      |
| **Unread done** | **🎉** | `#FFD75F` | `is_unread=True and not is_ticking` — agent has unseen output                                        |
| **User-paused** | **🛑** | `#FF5F5F` | `agent_is_asking(status) and not is_ticking` — agent is in `PLANNING` / `QUESTION` (waiting on user) |

Suffix selection lives in `build_runtime_suffix` (lines 70–128); the "asking" predicate is `agent_is_asking` from
`src/sase/agent/status_buckets.py`. Status-bucket banners in BY_STATUS mode use a separate set of monochrome glyphs
(`▲ ▶ ⏳ ✗ ✓`) and are out of scope for this plan — we are only changing the two per-row emoji markers.

## Problem

The two markers we are revisiting both have **semantic mismatches** with the state they represent:

### 🛑 (stop sign) for "user-paused"

- Stop signs encode a _prohibition_ ("don't proceed") and feel alarming / error-adjacent. Visually near-identical to 🚫.
- The actual state is much softer: the agent has politely stopped and is **asking the user** to answer a question or
  approve a plan. The signal we want is "your turn" / "needs you", not "danger".
- Red (`#FF5F5F`) reinforces the alarming read, which competes for attention with rows that are actually failed.

### 🎉 (party popper) for "unread completed"

- Party-popper conveys **celebration / completion**, but the row is already in a DONE bucket — the marker's job here is
  to communicate **"you haven't seen this yet"**, which is orthogonal to "it finished".
- After a fresh `sase ace` open, a sidebar full of 🎉 reads as "everything is great" rather than "you have a queue of
  unread results to review".
- The bright gold `#FFD75F` is also very close to the running marker's `#D7AF5F`, so 🏃‍♂️ and 🎉 blur together when
  scanning a column of suffixes — color is not pulling its weight as a distinguisher.

## Goals

1. The user-paused marker should read as **"agent is waiting for you"** rather than "stop / error".
2. The unread-completed marker should read as **"new, unseen output"** rather than "yay, done".
3. The three markers (running / unread / paused) must be **visually distinct** at a glance — both in glyph shape and in
   color family.
4. Glyphs should render reliably in common terminals (ghostty, kitty, wezterm, alacritty, iTerm). Prefer
   single-codepoint emoji over ZWJ sequences when otherwise equal — though the existing 🏃‍♂️ already uses a ZWJ sequence,
   so this is a soft preference, not a hard rule.
5. No behavior change: same trigger conditions, same suffix slot, same width budget.

## Candidates

### User-paused (replaces 🛑)

Ranked by how well each conveys "agent stopped, needs user input":

| Glyph | Reads as            | Pros                                                             | Cons                                                        |
| ----- | ------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------- |
| ✋    | "wait / hold up"    | Soft, non-alarming, clearly says "the _agent_ paused, your move" | Slightly ambiguous (could read as "high-five" or "stop")    |
| 🙋    | "I have a question" | Strongest semantic match — agent is literally asking a question  | ZWJ-prone gendered variants; busier glyph                   |
| ❓    | "needs answer"      | Universally legible; pairs naturally with the QUESTION status    | Less distinctive shape; can be confused with help / unknown |
| ⏸️    | "paused"            | Neutral; visually unmistakable                                   | Doesn't convey _agency_ — looks like the _user_ paused it   |
| 👀    | "needs eyes"        | Conveys "look at me"                                             | Overloaded — also used elsewhere for "watching"             |

**Recommendation:** **✋** (raised hand) with style `#FFAF5F` (warm amber) — preserves the "attention required" energy
without the prohibition read of 🛑, and amber sits between the gold running marker and the red failure color so paused
rows stay distinguishable.

A close runner-up is **🙋** if we want the strongest "asking a question" semantic; the call between the two is largely
aesthetic.

### Unread completed (replaces 🎉)

Ranked by how well each conveys "fresh / unseen output":

| Glyph | Reads as                 | Pros                                                 | Cons                                                                      |
| ----- | ------------------------ | ---------------------------------------------------- | ------------------------------------------------------------------------- |
| 📬    | "new mail in your inbox" | Strong inbox metaphor; explicit "unread"             | Slightly wider glyph; the raised-flag detail can disappear at small sizes |
| ✨    | "new / fresh"            | Tiny footprint; pairs naturally with "just appeared" | Less explicit about _who_ should look                                     |
| 🔔    | "notification"           | Universal "new thing" signal                         | Can imply ongoing alerting; overloaded with alarms                        |
| 🆕    | "new"                    | Literally says NEW                                   | Latin letters inside an emoji — clashes with non-English UX               |
| 📨    | "incoming message"       | Inbox metaphor                                       | Reads as in-flight, not "waiting for you"                                 |

**Recommendation:** **📬** (mailbox with raised flag) with style `#5FD7FF` (cool sky-blue) — the mailbox metaphor
matches "you have unread results"; switching to a cool color pulls it cleanly away from the gold running marker so the
three states use three different color families (gold / blue / amber).

A close runner-up is **✨** in `#5FD7FF` if 📬 looks too cluttered in practice.

## Recommendation summary

|                | Before       | After (proposed)                 |
| -------------- | ------------ | -------------------------------- |
| User-paused    | 🛑 `#FF5F5F` | **✋** `#FFAF5F` (warm amber)    |
| Unread done    | 🎉 `#FFD75F` | **📬** `#5FD7FF` (cool sky-blue) |
| Running (kept) | 🏃‍♂️ `#D7AF5F` | unchanged                        |

This gives the three suffix variants three distinct color families (gold / amber / blue) and three clearly different
glyph shapes (figure / hand / object).

Because aesthetics are subjective, I will present these as the proposal but ask the user to confirm or pick alternatives
from the candidate tables before editing.

## Implementation outline

Scope is narrow — single file, plus a snapshot refresh.

1. **`src/sase/ace/tui/widgets/_agent_list_render_layout.py`**
   - Update `_RUNTIME_UNREAD_COMPLETED_MARKER` and `_RUNTIME_UNREAD_COMPLETED_MARKER_STYLE`.
   - Update `_RUNTIME_USER_PAUSED_MARKER` and `_RUNTIME_USER_PAUSED_MARKER_STYLE`.
   - No logic changes; the markers are simple string/style constants consumed in two branches each of
     `build_runtime_suffix`.

2. **Tests / snapshots**
   - `just test` exercises the visual snapshot suite (cairosvg/Pillow); any SVG/PNG snapshots that baked the old glyphs
     will need regeneration. Inspect each diff before accepting to confirm only the marker glyph/color changed.
   - Grep for the literal `🛑`, `🎉`, `_RUNTIME_USER_PAUSED_MARKER`, and `_RUNTIME_UNREAD_COMPLETED_MARKER` to catch any
     test that asserts on the marker string.

3. **Out of scope (explicitly)**
   - The BY_STATUS bucket banner glyphs (`▲ ▶ ⏳ ✗ ✓`) in `src/sase/agent/status_buckets.py` — those are monochrome
     geometric glyphs and serve a different role.
   - The mark / approve / hidden / bead context glyphs (`✓ ⚡ ◌ ◆`) in `_agent_list_styling.py`.
   - The Rust `sase-core` crate — these markers are pure Python presentation state and do not cross the core boundary.

## Validation plan

- Run `just check` after the change.
- Launch `sase ace` against a project that has at least one running agent, one agent in `QUESTION` status, and one
  completed-but-unread agent. Confirm all three suffix variants render and remain visually distinct at the default
  terminal font size.
- Confirm a sidebar full of completed-unread rows now reads as "queue of things to review" rather than "celebration
  soup".

## Open question for the user

Confirm the recommended pair (✋ + 📬) — or pick a different combination from the candidate tables above — before I
touch the code. Color tweaks are also easy to revise.
