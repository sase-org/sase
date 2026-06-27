---
plan: sdd/tales/202606/prompt_history_three_word_minimum.md
---
 When the user cancels the current prompt in the prompt input widget, we currently only seem to save the prompt to prompt history when the prompt is at least two words long. Can we make it so we don't store the prompt unless it's at least three words long? Think this through thoroughly and create a plan using your `/sase_plan` skill. Submit your plan with the
`sase plan propose` command (as the skill instructs) before making any file changes.


%xprompts_enabled:false
### Questions and Answers

#### Q1: Scope

> The two-word minimum for saving a cancelled prompt is actually a SHARED threshold (_MIN_PROMPT_WORDS = 2 / is_recordable_prompt). It also gates normally-SUBMITTED prompts, multi-agent prompt segments, and a history-doctor diagnostic. Raising it to three words can mean two different things. Which scope do you want?

- [ ] **Cancel-only (3 words)** — Cancelled prompts require >=3 words to be saved; submitted prompts keep the existing >=2-word floor. Surgical: adds a cancelled-aware threshold. Matches your literal request, no behavior change to submitted-prompt history.
- [x] **Global (3 words)** — Raise the shared threshold to 3 everywhere: cancelled, submitted, and multi-agent segments all require >=3 words. Simplest change (one constant) but also stops saving 2-word SUBMITTED prompts (e.g. "fix bug") and makes the history-doctor flag existing 2-word entries.

%xprompts_enabled:true