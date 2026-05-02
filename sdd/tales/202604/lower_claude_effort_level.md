# Plan: Durable Fix for "Prompt too long" on Opus 4.7 via Chezmoi Claude Settings

## Problem

Since upgrading to Claude Opus 4.7, Claude Code sessions terminate with `Prompt is too long` in conversations that
previously fit on Opus 4.6. The user wants a **durable, settings-level fix** in their chezmoi repo — not behavioral
workarounds like "remember to `/compact` more often."

Detailed root-cause analysis lives at `sdd/research/202604/opus_4_7_prompt_too_long.md`. Summary for this plan: Opus 4.7's new
tokenizer inflates token counts by 1.0x–1.47x for the same text (CLAUDE.md 1.45x, technical docs 1.47x), so the 1M-token
window holds materially less content. Anthropic's own mitigation is to give compaction triggers more headroom.

## Scope

The user explicitly scoped this to `~/.local/share/chezmoi/home/dot_claude/settings.json`. Memory-file trimming in the
sase repo (always-loaded `AGENTS.md` + `memory/short/*.md`) is out of scope here; that's a separate follow-up if the
effort-level change alone doesn't resolve the issue.

## Current Chezmoi Claude Settings (relevant)

From `~/.local/share/chezmoi/home/dot_claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_EFFORT_LEVEL": "max",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "DISABLE_INSTALLATION_CHECKS": "1"
  },
  "alwaysThinkingEnabled": true
}
```

Confirmed via `env | grep -iE 'claude|auto_compact'`:

- `CLAUDE_CODE_EFFORT_LEVEL=max` is live.
- `DISABLE_AUTO_COMPACT` is **not set** (good — auto-compact is active).

## Decision: Lower `CLAUDE_CODE_EFFORT_LEVEL` from `max` to `high`

This is the single actionable change in chezmoi-settings scope that directly reduces tokens-per-turn, and it's what
Anthropic explicitly recommends as the Opus 4.7 baseline.

### Why this, specifically

1. **It's what the research surfaced as the amplifier.** The research file identifies `max` effort as compounding the
   tokenizer-inflation problem (more thinking tokens per turn, on top of each token now costing more context). High is
   Anthropic's documented recommended baseline for Opus 4.7.
2. **It's surgical.** No loss of capability on complex tasks — adaptive thinking still engages when warranted; it just
   won't burn the ceiling on every turn.
3. **It's durable.** Lives in chezmoi, deploys on `chezmoi apply`, env var is read by every Claude Code invocation.
   Sets-once-and-forget.
4. **It's reversible.** One-line revert if the user wants `max` back for a specific heavy task (or they can override
   per-session with `/effort max`).

### Why not other changes

- **Keep `alwaysThinkingEnabled: true`.** In Opus 4.7, thinking is adaptive — this flag just _allows_ it, not forces
  maximum budget. Lowering effort is the right dial; removing thinking entirely would degrade reasoning quality on the
  hard tasks that actually justified `max` in the first place.
- **No default-model pinning.** Pinning to Opus 4.6 would sidestep the tokenizer change entirely, but it forfeits every
  Opus 4.7 improvement. The user upgraded for a reason; `/model` per-session is the right escape hatch when specific
  workflows need the old tokenizer.
- **No explicit `DISABLE_AUTO_COMPACT=0`.** It's already unset. Adding it defensively risks the inverse — some tooling
  treats env vars with `DISABLE_` prefix as "present = true" regardless of value. Unset is the correct state.
- **No hook-based compaction.** Slash commands can't be invoked from hooks, and the `PreCompact` hook already exists and
  is working. There's no additional hook-level lever here.

## Files to Change

| File                                                   | Change                                       |
| ------------------------------------------------------ | -------------------------------------------- |
| `~/.local/share/chezmoi/home/dot_claude/settings.json` | `CLAUDE_CODE_EFFORT_LEVEL: "max"` → `"high"` |

Diff preview:

```diff
   "env": {
-    "CLAUDE_CODE_EFFORT_LEVEL": "max",
+    "CLAUDE_CODE_EFFORT_LEVEL": "high",
     "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
     "DISABLE_INSTALLATION_CHECKS": "1"
   },
```

## Rollout Steps

1. Edit `~/.local/share/chezmoi/home/dot_claude/settings.json` — flip `max` to `high`.
2. In the chezmoi repo: `just check` (per the chezmoi rule in `.sase/memory/long-external-repos.md`).
3. Commit the chezmoi change (user-driven, follows chezmoi repo's normal commit flow).
4. Run `chezmoi apply` to sync to `~/.claude/settings.json` (required per external-repos memory).

## Verification

After rollout, in a **new** Claude Code session (env vars are read at session start):

```bash
env | grep CLAUDE_CODE_EFFORT_LEVEL
# expected: CLAUDE_CODE_EFFORT_LEVEL=high
```

And on the Claude Code side, `/effort` should report `high`.

The qualitative signal — whether "Prompt too long" errors stop recurring — will take a few days of normal usage to
confirm. If it still triggers, the follow-up lever is trimming always-loaded memory in the sase repo (audit
`memory/short/*.md` → `memory/long/` migration candidates), which is the next item in the research's priority order.

## Reversibility

Trivial. Revert the one-line change in chezmoi, re-apply, and `max` is restored. Mid-session overrides remain available
via `/effort max` without any settings change.
