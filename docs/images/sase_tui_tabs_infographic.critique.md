---
pdf: false
---

# Critique: `sase_tui_tabs_infographic.png`

!!! warning "Historical review"

    This critique records the pre-Artifacts ACE layout and the state of the asset before its 2026-05-10 regeneration.
    Current ACE navigation is **Agents · Artifacts · Axe**. Artifacts has **Stitches · Patches · Beads**,
    configured document-provider panes, and **Files**. The PNG is no longer embedded in active documentation, and
    claims below about current code paths or a missing prompt sidecar should be read only as historical context.

This is a clarity-and-accuracy review of `docs/images/sase_tui_tabs_infographic.png`,
the diagram embedded in the "How the pieces connect" section of `docs/index.md`
(line 137) with the figcaption "ACE gives operators one place to inspect agents,
changes, notifications, and automation state." The diagram is reviewed against:

- The embedding doc (`docs/index.md`) — there is **no
  `sase_tui_tabs_infographic.prompt.md` sidecar** in `docs/images/`, unlike most peer
  infographics. Original intent is inferred from the embedding caption, the diagram
  title strap, and `docs/ace.md`.
- The current TUI code: `src/sase/ace/tui/widgets/tab_bar.py` (tab labels and colors),
  `src/sase/ace/tui/app.py` (composition of each tab's panes), and the surrounding
  chrome (`Header`, `TaskIndicator`, `LLMOverrideIndicator`, `NotificationIndicator`,
  `KeybindingFooter`, `Footer`).
- `docs/ace.md` (canonical user-facing description of the three tabs).

## What the diagram currently shows

A title strap reads "sase ACE TUI: 3 tabs, one control plane". Below it, three
side-by-side coloured cards represent the tabs:

- **PRs (teal)** — caption "PRs: Patch command center" with three small icon rows:
  `query, group, fold`; `status lifecycle`; `review, mail, sync`.
- **Agents (light blue)** — caption "Agents: live run supervision" with three rows:
  `running + completed runs`; `prompts, files, diffs`; `resume, tag, kill`.
- **AXE (red)** — caption "AXE: background automation" with three rows: `daemon health`;
  `background commands`; `scheduled work`.

A bottom horizontal strip shows four nodes connected left-to-right by a circuit-trace
path: `plan` (clipboard icon) → `launch` (rocket) → `monitor` (graph) → `land`
(landing-pin).

## Clarity issues a new user would hit

1. **The bottom `plan → launch → monitor → land` strip is not a TUI element and has no
   labelled relationship to the three tab cards above it.** A reader who has never
   opened ACE will assume this strip corresponds either to a navigation row in the
   actual UI or to a one-to-one mapping with the three tabs (plan→PRs? launch→Agents?
   monitor→AXE?), but `land` has no tab counterpart and the mapping is not even
   one-to-one. The strip is best read as the _conceptual_ agent lifecycle, but nothing
   in the diagram says so.
2. **"One control plane" is the headline claim and it is not depicted.** What makes ACE
   a single control plane is the shared chrome — the persistent tab bar, the right-side
   indicator stack (`TaskIndicator`/`LLMOverrideIndicator`/`NotificationIndicator` in
   `app.py:236-239`), and the `KeybindingFooter` (`app.py:268`) — all of which surround
   every tab. The diagram instead shows three independent cards with no shared frame,
   which contradicts the title.
3. **The three rows inside each tab card mix three different categories without flagging
   them as such.** Each card conflates _what is shown_ (e.g. `running + completed runs`,
   `prompts, files, diffs`), _state model_ (e.g. `status lifecycle`), and _available
   actions_ (e.g. `review, mail, sync`, `resume, tag, kill`). A new reader cannot tell
   which row is "what you see" vs. "what you can do".
4. **`status lifecycle` (PRs row 2) is opaque.** The actual PR lifecycle is documented
   as `WIP → Draft → Ready → Mailed → Submitted` (per `memory/glossary.md`). Without
   those chips visible, the row is a label without content.
5. **`review, mail, sync` (PRs row 3) is a grab-bag.** "review" and "mail" are real PR
   actions (`docs/ace.md` lists `M` to mail, `a` to accept, etc.) but "sync" has no
   clear referent — it could mean refresh-interval auto-pulls, `fetch` from origin, or
   the SQLite/JSONL bead sync, none of which is a PRs-tab concept. A new user will
   guess.
6. **`scheduled work` (AXE row 3) is misleading.** Cron-style routine scheduling lives
   in `sase schedule` / `sase axe schedule` and is not a primary surface inside the AXE
   tab; the AXE tab's right pane is the `AxeDashboard` (daemon health, Lumberjack
   output) and its left pane is `BgCmdList`. Putting `scheduled work` on equal footing
   with `daemon health` and `background commands` overstates how prominent scheduled
   jobs are in the tab.
7. **Three colour-coded cards but the meaning of the colour coding is not
   legend-stated.** The colours do match `_TAB_COLORS` in code, which is great, but a
   new reader who never sees the live UI cannot confirm that and may read "red AXE" as a
   warning state rather than a brand colour.
8. **Iconography is decorative, not informative.** The small icons next to each row
   (magnifying-glass, refresh arrow, envelope/cloud, play arrow, document,
   calendar/clock) repeat the row label rather than adding information. Removing them
   would not lose any meaning.
9. **No mention of how to switch tabs.** `Tab` / `Shift+Tab` (and the equivalent `[` /
   `]` keymap) is the single most-used affordance for a "3 tabs, one control plane" UI;
   omitting any hint at the switching gesture is a clarity miss for an overview
   infographic. (This is acceptable if the diagram is purely conceptual, but the title
   suggests it is operator-facing.)
10. **The `plan / launch / monitor / land` strip uses different visual language from the
    cards.** The cards have rounded boxes, the strip has chip-on-circuit-trace nodes;
    the eye reads them as different domains, which is appropriate, but nothing labels
    them as "lifecycle below, tabs above". A divider, an eyebrow caption, or a "Agent /
    PR lifecycle" label would resolve the ambiguity.

## Specific accuracy errors against current code

The accuracy bar is whether the diagram matches today's
`src/sase/ace/tui/widgets/tab_bar.py`, `src/sase/ace/tui/app.py`, and `docs/ace.md`.

1. **Tab labels and ordering are correct.** `_TAB_LABELS` in `tab_bar.py:20-24` declares
   the order `("changespecs","PRs"), ("agents","Agents"), ("axe","AXE")` and the diagram
   matches. ✓
2. **Tab colour coding is correct.** `_TAB_COLORS` in `tab_bar.py:14-18` is
   `changespecs=#00D7AF` (teal), `agents=#87D7FF` (light blue), `axe=#FF5F5F` (red) —
   all three match the card colours in the image. ✓
3. **PRs-tab content row "query, group, fold" understates what is on screen.** The PRs
   view composes `PatchInfoPanel`, `PatchList`, the host-owned **`RelationPanel`**,
   `SearchQueryPanel`, and `PatchDetail`. Ancestor / child / sibling navigation (`<`,
   `>`, `~` per `docs/ace.md:PRs Tab`) is one of the distinctive features of the tab and
   is not represented at all in the icon row.
4. **PRs-tab grouping is named generically.** Code supports three explicit grouping
   modes — `BY_PROJECT`, `BY_DATE`, `BY_STATUS` — cycled with `o`/`O` (per `docs/ace.md`
   and the `app.py` grouping logic referenced from the AGENTS.md note in
   `src/sase/ace/`). The diagram says only "group", losing the named-mode information
   that would help a reader recognise the screenshots.
5. **PRs-tab "review, mail, sync" — `sync` does not correspond to any tab affordance.**
   No keybinding, no widget, no config option in `docs/ace.md` is named "sync". The
   closest concept is the `--refresh-interval` flag (auto-refresh of the query result
   set), but that is global TUI behaviour, not a PRs-specific action.
6. **Agents-tab "running + completed runs" is correct,** but the diagram omits the
   `AgentInfoPanel` summary banner at the top (`app.py:253`) and the agent **tree /
   retry chain** structure that `AgentList` renders. The retry chain
   (`retry_of_timestamp` / `retried_as_timestamp` / `retry_chain_root_timestamp` per
   `memory/glossary.md`) is a defining shape of the Agents tab and is invisible here.
7. **Agents-tab "prompts, files, diffs" matches `AgentDetail` panes** (`app.py:258`) —
   accurate. ✓
8. **Agents-tab "resume, tag, kill" matches real keybindings** (resume, tag, kill are
   documented in `docs/ace.md`'s Agents-tab section) — accurate. ✓
9. **AXE-tab "daemon health" maps to the `AxeInfoPanel` banner** (`app.py:266`) —
   accurate. ✓
10. **AXE-tab "background commands" maps to `BgCmdList`** (`app.py:263`) — accurate. ✓
11. **AXE-tab "scheduled work" is at best partial.** The right-side `AxeDashboard`
    (`app.py:267`) shows daemon health, Lumberjack output, and recent automation
    activity; cron-style scheduled work is configured via `sase axe schedule` /
    `sase schedule` and surfaces only summarily. The diagram label suggests a "scheduled
    jobs view" that the tab does not really own.
12. **The bottom `plan / launch / monitor / land` strip has no UI counterpart.** This is
    the conceptual lifecycle of an SDD epic / agent run, drawn from `docs/ace.md` (agent
    phases) and the SDD epic-work flow (`memory/glossary.md`). It is not literally
    rendered in the TUI; the diagram does not say so. Either it needs an explicit
    eyebrow/caption ("Agent lifecycle that the three tabs together support") or it
    should be dropped.
13. **The shared chrome is missing entirely.** `app.py:233-239,268-269` shows that every
    tab is wrapped by `Header`, the top-bar indicator stack, the `KeybindingFooter`, and
    the platform `Footer`. None of these is drawn, which is the most concrete miss
    against the "one control plane" framing.
14. **No prompt sidecar exists for this image.** Peer infographics
    (`commit-workflow-infographic`, `rust-backend-boundary-infographic`,
    `workflow-execution-infographic`, `xprompt-resolution-infographic`, `sase_overview`)
    all have a `.prompt.md` sidecar; this one does not. The regen phase (`sase-2s.17`)
    will need to _create_ `docs/images/sase_tui_tabs_infographic.prompt.md` from
    scratch, not merely revise it.

## Concrete suggested changes for the regenerated image

These are scoped so the regen agent (`sase-2s.17`) can act on them directly.

1. **Wrap the three tab cards in a single explicit "control plane" frame** that depicts
   the persistent ACE chrome: a top bar containing the tab pills plus four small
   indicators (Task / LLM-override / Inactive / Notifications), and a bottom keybinding
   footer strip. This is the single most important change because it is what makes the
   title's "one control plane" claim visible.
2. **Replace each card's three icon rows with a "Surfaces / Lifecycle / Actions" trio**,
   explicitly labelled, so the reader knows which row is "what you see", "what state
   model is in play", and "what you can do":
   - **PRs**: Surfaces = `Patch list · detail · ancestors/children`; Lifecycle =
     `WIP → Draft → Ready → Mailed → Submitted`; Actions =
     `accept · mail · rebase · diff · checkout`.
   - **Agents**: Surfaces =
     `agent tree · retry chains · AgentDetail (prompt / files / diffs / thinking)`;
     Lifecycle = `pending → running → completed (✓ / ✗)` with retry-chain note; Actions
     = `resume · tag · kill · open`.
   - **AXE**: Surfaces =
     `BgCmd list · Axe dashboard · daemon health · Lumberjack output`; Lifecycle =
     `queued → running → done / errored`; Actions =
     `start / stop daemon · run command · open log`. Note that scheduled-work
     _configuration_ lives in `sase axe schedule` outside the tab.
3. **Either re-frame the bottom `plan / launch / monitor / land` strip as the explicit
   "Agent lifecycle the three tabs together support", or remove it.** If kept, draw
   three thin tinted bands behind the strip — teal under `plan`, light-blue under
   `launch / monitor`, red under `land` — to show which tab(s) own each phase. Keep the
   circuit-trace style.
4. **Drop the merely decorative icons** (the magnifying-glass / envelope / play /
   document / calendar / heartbeat glyphs that just repeat the row label). Replace them
   with mini-glyphs that convey _content type_ (e.g. a tree glyph for the agent tree
   row, a diff-glyph for prompts/files/diffs).
5. **Show the cycling affordance.** A small `Tab ⇄ Shift-Tab` chip on the tab bar, or a
   circular-arrow glyph between the three tab pills, will signal that the three tabs are
   cycled rather than parallel windows.
6. **Add a one-line legend tying card colour to `_TAB_COLORS`.** A small caption like
   `card colour = tab brand colour (PRs #00D7AF · Agents #87D7FF · AXE #FF5F5F)` removes
   the "is red a warning?" ambiguity.
7. **Keep the existing 16:9 layout, neutral palette, no-text-in-base-render policy, and
   DejaVu-Sans deterministic labels.** Style consistency with peer infographics under
   `docs/images/` should be preserved per `docs/images/infographic-style-brief.md`
   (referenced by the regen-phase pattern in `sdd/epics/202605/diagram_review.md`).
8. **Create a new `docs/images/sase_tui_tabs_infographic.prompt.md` sidecar** alongside
   the regenerated PNG. Since no sidecar exists today, the regen agent must author one
   from scratch — this should record the operator-facing intent ("show ACE as one
   control plane wrapping three tabs"), the chrome elements, and the per-tab
   Surfaces/Lifecycle/Actions trio so future regenerations have a starting point.

## Out-of-scope (do not change in this critique phase)

Per the epic plan (`sdd/epics/202605/diagram_review.md`), this phase only writes the
critique. The PNG (`docs/images/sase_tui_tabs_infographic.png`), the (currently-missing)
prompt sidecar, and the embedding doc (`docs/index.md`) are unchanged. The regen phase
(`sase-2s.17`) is responsible for creating both the new PNG and the new prompt sidecar
from the suggestions above.
