---
keyword: Agent Data Card
aliases:
  - card
  - agent data cards
---

An agent data card is one titled unit of detail inside an agent data deck, such as
Context, Reply, one file's diff, or LLM Calls. A deck panel shows a multi-card deck
spread — every card on one scrollable page, separated by titled rules — when the cards
fit within `ace.agent_decks.spread_max_screens` panel heights, and paged — one card at a
time — otherwise. A deck panel's title shows card tabs only when the deck is paged and
has two or more cards — tabs mean pages; with no tabs the whole deck is one scrollable
document, and the title's ▴/▾ cues name the cards above and below. `Ctrl+J`/`Ctrl+K`
move to the next or previous card in both modes (jumps in spread, pages when paged), and
a paged deck keeps the chosen card (for example Reply) as the selection moves between
nodes. A card can contain optional [[glossary:agent-data-card-block]] units, which never
nest.
