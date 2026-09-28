---
keyword: Agent Data Deck
aliases:
  - deck
  - agent data decks
---

An agent data deck is a named, ordered set of agent data cards about the selected sase
node, shown in an Agents-tab deck panel. The built-in decks are Main (a Context card and
a Reply card — titled Output for named procs, monitors, gates, and workflow steps — or
one Summary card for agent clans and tribe panels), Files (one card per diff or attached
file), Tools (the LLM Calls card), and FINAL (an Overview card plus one card per
finalizer instance, showing how the node's host-owned finalizers ran). A deck is
presentation only and owns no agent data; `Ctrl+N`/`Ctrl+P` cycle the focused deck panel
through the decks, and the `p` picker jumps to one (`m`, `f`, `t`, `n`).
