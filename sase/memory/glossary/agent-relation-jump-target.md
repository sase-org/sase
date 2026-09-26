---
keyword: Agent Relation Jump Target
aliases:
  - agent jump target
---

An agent relation jump target is what an Agents-tab numeric keymap jumps to: a sase
node, or a dismissed sase agent that the keymap revives, reached through one of the
selection's agent relations. Each one is a numbered row, its number chip at the left, in
that relation's roster section: `SESSION TURNS` (an agent session's sase turns, monitor
and gate turns included), `NEIGHBORS` (the selected agent's agent neighbors, dismissed
ones included), `CLAN MEMBERS` (an agent clan's direct members), or `TRIBE MEMBERS` (an
agent tribe's top-level clans, sessions, workflows, and agents). The rosters shown for
one selection share a single number sequence: `0`–`9`, or `00`–`99` past ten targets,
capped at 100. Typing a number selects its target and reveals it through any folds; a
dismissed target is revived instead. The jump panel, the sticky footer below the deck
panels, lists every live agent relation jump target.

Only numbered rows are agent relation jump targets. Rows behind a `… +N more` tail,
unnumbered child rows, `… also listed under SESSION TURNS` duplicates, and tribe
`CLAN SUMMARIES` / `PROMPTS` chips that reuse a member's number are not. Plain "jump
target" is ambiguous, and none of its other uses is an agent relation jump target: `'`
entry hints (including the `AgentJumpTarget` type in `jump_hints.py`), `,j`/`,J` unread
and stopped-agent jumps, `Ctrl+]` prompt-definition jumps, and Admin Center section and
`,L` error-log jumps. The Artifacts tab's relation panel `<`/`>` keys follow artifact
relations, not agent relations.
