# Why "Prompt too long" errors surged after Opus 4.7

## Problem

Since upgrading to Claude Opus 4.7, Claude Code sessions frequently terminate with `Prompt is too long` — often in
conversations that previously fit comfortably within the context window on Opus 4.6.

## Root cause: new tokenizer inflates token counts by up to ~1.47x

Opus 4.7 ships with a new tokenizer. Anthropic's own release notes state it may use **1.0x to 1.35x as many tokens** as
Opus 4.6 for the same input, varying by content type. Independent measurements on real Claude Code workloads came in
even higher:

| Content type            | Token multiplier (4.7 vs 4.6) |
| ----------------------- | ----------------------------- |
| General English prose   | ~1.20x                        |
| Python source           | ~1.29x                        |
| TypeScript source       | ~1.36x                        |
| User prompts            | ~1.37x                        |
| **CLAUDE.md files**     | **~1.45x**                    |
| Technical documentation | ~1.47x                        |
| CJK content             | ~1.01x                        |

The same 1M-token context window holds meaningfully less text under the new tokenizer — Anthropic's own figure is ~555k
words for Opus 4.7 versus ~750k words for Opus 4.6. Code-heavy and docs-heavy workloads are hit hardest, which matches
the typical Claude Code session.

This is not a context-window regression. The window size didn't shrink; each character simply consumes more of it.
Conversations that historically fit are now overflowing, and **auto-compact can fail to trigger in time** because the
trigger threshold was calibrated against the old token accounting.

## Contributing factors

Several other Opus 4.7 changes compound the pressure:

- **Extended thinking budgets removed.** Adaptive thinking is the only thinking-on mode; it can spend more or fewer
  thinking tokens than a fixed budget did.
- **Fewer tool calls, more reasoning by default.** Thinking tokens replace what used to be tool-call round-trips, which
  shifts bytes from tool results into the thinking stream.
- **Response length calibrates to task complexity.** Complex tasks produce longer responses than Opus 4.6 would have,
  even at the same effort level.
- **Max effort sessions (`CLAUDE_CODE_EFFORT_LEVEL=max` in `~/.claude/settings.json`) amplify all of the above.** Higher
  effort = more thinking = more tokens.

## Anthropic's official mitigation

From the Opus 4.7 release notes:

> We suggest updating your `max_tokens` parameters to give additional headroom, **including compaction triggers**.

Translation: the auto-compact threshold was tuned for the old tokenizer. It needs to trigger earlier now.

## Recommended solution

A layered approach, in priority order:

### 1. Let auto-compact trigger earlier (primary fix)

Ensure `DISABLE_AUTO_COMPACT` is **not** set in your environment. Auto-compact is on by default and is the main line of
defense against this error. If it has been disabled for any reason, re-enable it.

Verify with:

```bash
env | grep -i auto_compact   # should return nothing
```

### 2. Actively watch and manage context

- Run `/context` mid-session to see the breakdown (system prompt, tools, memory, messages). Get used to running it
  before long operations.
- Run `/compact` manually at natural breakpoints — don't wait for auto-compact.
- When you see the error, press **Esc twice** to step back several turns, then `/compact`. Running `/compact` after the
  error often fails with `Conversation too long` because there's no room left to hold the summary.
- Use `/clear` to start a fresh session (previous session recoverable via `/resume`).

### 3. Trim the always-loaded context

The biggest easy win: anything loaded every turn now costs ~1.45x what it did.

- **CLAUDE.md / AGENTS.md files**: audit for stale or redundant instructions. Measured 1.445x multiplier makes these the
  most expensive line-for-line.
- **Path-specific rules**: move instructions that only apply to certain subdirectories into path-scoped `CLAUDE.md`
  files so they load on demand.
- **MCP servers**: every connected server's tool definitions sit in context from turn one. Disable unused ones with
  `/mcp disable <name>`. This matters most for subagents, which inherit all parent MCP tools.
- **Run `/doctor`**: it flags oversized memory files and subagent definitions.

### 4. Adjust effort if you don't need max

`CLAUDE_CODE_EFFORT_LEVEL=max` in `~/.claude/settings.json` maximizes thinking tokens. For routine tasks, `high` is
Anthropic's recommended baseline on Opus 4.7 and consumes less context. Use `/effort` to check and adjust per-session.

### 5. Fall back to Opus 4.6 or Sonnet for context-heavy work

If a specific workflow consistently overflows even after the steps above, `/model` back to Opus 4.6 (old tokenizer, ~30%
more effective context for the same bytes) or Sonnet for the duration of that task.

## SASE-specific considerations

The SASE framework loads several files on every turn:

- `CLAUDE.md` → `AGENTS.md` (37 lines)
- `memory/short/build_and_run.md`, `glossary.md`, `gotchas.md`, `workspaces.md` (45 lines combined)
- Dynamic (tier-2) memory appended per-prompt based on keyword matches

Under the 1.45x CLAUDE.md multiplier, the always-loaded footprint grew meaningfully after the upgrade, even though
nothing about the files changed. Worth considering:

- **Audit `memory/short/*.md`** for anything that could move to `memory/long/` (tier 3, load-on-demand). The tier-3
  system exists exactly for this tradeoff.
- **Tier-2 dynamic memory**: make sure keyword matchers aren't over-broad — each match adds a full file to the prompt.
- **Subagent usage**: spawned agents inherit the full memory footprint. Heavy subagent use multiplies the problem.
  Consider whether each delegation is worth the fresh context cost, and scope what subagents receive.

## Quick checklist

- [ ] Confirm `DISABLE_AUTO_COMPACT` is unset
- [ ] Run `/context` on an active session to establish a baseline
- [ ] Run `/doctor` to surface oversized memory files
- [ ] Audit `memory/short/*.md` and `AGENTS.md` for trim targets
- [ ] Disable unused MCP servers with `/mcp disable`
- [ ] Consider lowering `CLAUDE_CODE_EFFORT_LEVEL` from `max` to `high` for routine work
- [ ] Use `/compact` proactively at breakpoints rather than waiting

## Sources

- [What's new in Claude Opus 4.7 — Anthropic API Docs](https://platform.claude.com/docs/en/about-claude/models/whats-new-claude-4-7)
- [Error reference — Claude Code Docs](https://code.claude.com/docs/en/errors)
- [Context windows — Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [Introducing Claude Opus 4.7 — Anthropic](https://www.anthropic.com/news/claude-opus-4-7)
- [I Measured Claude 4.7's New Tokenizer. Here's What It Costs You. — Claude Code Camp](https://www.claudecodecamp.com/p/i-measured-claude-4-7-s-new-tokenizer-here-s-what-it-costs-you)
- [Claude Opus 4.7 pricing: $5/1M, new tokenizer explained — TokenCost](https://tokencost.app/blog/claude-opus-4-7-pricing)
- [Claude Opus 4.7: Benchmarks, Tokenizer Changes, and Coding Performance — Better Stack](https://betterstack.com/community/guides/ai/claude-opus-4-7/)
