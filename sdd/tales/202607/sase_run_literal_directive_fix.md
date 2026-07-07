---
create_time: 2026-07-06 23:59:48
status: done
prompt: sdd/prompts/202607/sase_run_literal_directive_fix.md
---
# Plan: Fix /sase_run literal-directive guidance and relaunch the failed demo #5 agent

## Context: what actually failed

The three-agent demo launch (request `launch-1587dd02`, submitted by agent `@01`, approved 2026-07-06 23:07) did **not**
fail at approval. All three slots dispatched (`launched_count: 3`):

- Slot 0 → agent `@02` → `demos/tapes/sase_ace_prs_pipeline.tape` — **succeeded**, landed as `fea5e06fa`.
- Slot 1 → agent `@03` → `demos/tapes/sase_ace_prompt_history_stash.tape` — **succeeded**, landed as `c8fedfa15`.
- Slot 2 (demo #5, the multi-model fan-out tape) — **died 0.2s after dispatch**. The failure notification ("Agent
  failed: ace(run)-260706_230719 / DirectiveError") fired one second after the approval keystroke, which is why it
  looked like the approval itself failed.

Root cause of the slot-2 death: the requested prompt is a full sase prompt that is **re-parsed for directives and
xprompt references at dispatch time**, and slot 2's task text _described_ prompt syntax in prose:

1. The phrase "completion into `#git:nova`" was picked up as a live VCS workspace xprompt. It out-resolved the intended
   leading `#gh:gh_sase-org__sase` reference, so the run was dispatched into the fictional `nova` demo project
   (confirmed by the run's `xprompts.json`, which lists both `gh: gh_sase-org__sase` and `git: nova`).
2. The two prose mentions of the model directive ("verify the %m model-directive syntax", "its own %m(...) model
   directive") were collected as duplicate model directives and raised
   `DirectiveError: %m ... %m(...) is no longer supported; use %{%m:...} instead`, killing the run instantly (error
   report: `~/.sase/projects/nova/artifacts/ace-run/202607/06/20260706230719/error_report.md`).

The /sase*run skill invites this failure: it says "`%` directives and `#` xprompt references all work" but never warns
that the _entire* prompt body is live syntax, never documents the escaping mechanisms, and never requires a preflight
expansion check. Both protection mechanisms already exist in the parser and were verified to work:

- **Fenced code blocks** are never parsed for directives, references, or multi-agent separators, and survive the request
  → dispatch → agent pipeline verbatim (`src/sase/xprompt/_fenced_blocks.py`).
- **Disabled regions** (`%xprompts_enabled:false` … `%xprompts_enabled:true` marker lines) protect enclosed text; the
  markers are stripped before the launched agent sees the prompt (`src/sase/xprompt/_disabled_regions.py`).
- `sase xprompt expand '<prompt>'` reproduces the DirectiveError ahead of time, so it works as a preflight check.

Secondary observations from the same review (no action in this plan):

- An earlier proposal round (agent `@w`, 19:54) submitted three separate 1-slot requests whose prompts started with
  `#git:home`, so the one approved slot (agent `@x`) ran in the `home` project instead of the sase project. The
  workspace-reference guidance added to the skill at 22:41 (`2894fd280`) already addresses that mistake.
- The ACE TUI currently spams `tui.log` with `FileNotFoundError` tracebacks from
  `src/sase/ace/tui/actions/event_refresh/_watcher.py:86` (`Path.cwd()` on a deleted ephemeral workspace cwd). Unrelated
  to the launch failure; follow-up candidate below.

## Changes

### 1. `src/sase/xprompts/skills/sase_run.md` — add literal-syntax and multi-slot guidance

Add a new subsection at the end of `## Compose The Requested Prompt` (after "### Other xprompts"):

```markdown
### Literal Directive Text

The requested prompt is re-parsed at dispatch: every `%` directive and `#` reference anywhere in it is live, even
mid-sentence. A stray `#git:<ref>` in prose silently re-targets the workspace; a stray `%m` mention fails the launch
after approval. When the prompt must show prompt syntax literally (docs, demos, tests):

- Put the literal syntax in a fenced code block; fenced content is never parsed.
- Or enclose a prose region between `%xprompts_enabled:false` and `%xprompts_enabled:true` marker lines; the markers are
  stripped before the launched agent sees the prompt.
- Otherwise name the syntax in words ("the model directive") instead of writing the token.

Always preflight with `sase xprompt expand '<prompt>'`: it must succeed and report only the directives and references
you intended.
```

Also add a short multi-agent note to `## Request A Launch` (this request shape was used successfully but is
undocumented): a prompt containing `---` separator lines outside fenced blocks plans one slot per segment, and
`max_slots` must be at least the segment count or the request fails with `max_slots_exceeded`.

Keep every existing phrase intact — `tests/main/test_init_skills_sources.py` asserts on the current wording.

### 2. `tests/main/test_init_skills_sources.py` — pin the new guidance

Extend the `sase_run` expected-phrases tuple with stable anchors from the new text, e.g. `"%xprompts_enabled:false"`,
`"sase xprompt expand"`, and `"max_slots_exceeded"`, so regenerated provider skills keep the guidance.

### 3. Regenerate and deploy the generated skills

Per the generated-skills memory: `sase skill init --force` (run so it renders from this repo's updated template), then
`chezmoi apply`. Verify the deployed `~/.claude/skills/sase_run/SKILL.md` contains the new subsection.

### 4. Validate

`just install`, then `just check`.

## Relaunch: one corrected agent for demo #5

Demos #3 and #4 already landed with their media, so re-running the full three-slot request would duplicate merged work.
The original ask ("three slots") is two-thirds complete; only the failed slot is relaunched — **one** new agent,
`max_slots: 1`, via a fresh /sase_run LaunchApproval request.

The corrected prompt keeps slot 2's task content but removes all live syntax from prose (the demo-beat tokens the tape
must type are named in words, with the tape agent directed to verify exact syntax against `docs/xprompt.md` and
`src/sase/default_config.yml` before scripting — same verification instruction as the original). It will be preflighted
with `sase xprompt expand` before submission. Draft:

> `#gh:sase`
>
> Write a new VHS demo tape at demos/tapes/sase_ace_multi_model_fanout.tape showing SASE's multi-runtime fan-out:
> composing one prompt that becomes three agents on three different models/runtimes (Claude, Codex, and Gemini), ending
> on the Launch Approval modal without ever launching. This is demo video #5; the first prompt-input demo only briefly
> showed a two-pane prompt stack, so this one makes uniform multi-runtime orchestration the headline.
>
> Before writing the tape, study the existing pattern: demos/README.md, demos/tapes/CLAUDE.md, the existing tapes
> (especially demos/tapes/sase_ace_prompt_input.tape, whose prompt-input choreography this builds on), and
> demos/scripts/seed_sase_ace_demo. Follow the same hermetic conventions exactly: identical Set geometry/font/theme
> header, seed via the seeder script, rebuild the agent index, cd into the seeded demo workspace, disable axe with -x,
> fixed fictional data, and absolutely no live agent submission — the Launch Approval modal is the finale and must be
> dismissed with Escape.
>
> Demo beats (verify the exact model-directive syntax and multi-agent separator behavior against docs/xprompt.md and the
> prompt parser, and the prompt-stack keybindings against src/sase/default_config.yml, before scripting — do not guess):
>
> - Launch ACE from the seeded workspace, open the prompt input with Space, and reference the seeded nova project
>   through project completion (typing a plus sign then "nov" and accepting the completion), the way the first tape
>   does.
> - Compose a multi-agent prompt of three short segments separated by the multi-agent separator lines, giving each
>   segment its own per-segment model directive using three distinct models already present in the seeded data:
>   claude-sonnet-4-6, gpt-5-codex, and gemini-2.5-pro. Let the directive/completion menus render on screen while
>   typing.
> - Show the prompt input reflecting that the prompt now represents three agents (agent-count indicator or prompt-stack
>   view, whichever the widget surfaces).
> - Press Enter to reach the Launch Approval modal listing all three agents with their three distinct models, hold for a
>   beat so viewers can read it, then Escape without launching and quit the way the existing tapes do.
>
> Output demos/out/sase_ace_multi_model_fanout.mp4 and .gif. Register the new tape everywhere the existing tapes are
> registered (the `just demos` recipe and demos/README.md). Regenerate media with `just demos -y` as
> demos/tapes/CLAUDE.md requires, and verify the result by extracting a few frames from the rendered mp4 with ffmpeg and
> reading them — confirm all three model names are visible in the Launch Approval modal frame.

## Follow-up candidates (out of scope)

- Validate slot prompts at `sase launch request` time (run directive extraction per planned slot) so a DirectiveError
  surfaces to the requesting agent instead of after user approval.
- Fix the ACE TUI artifact watcher's `Path.cwd()` crash loop when the TUI's launch cwd has been deleted.
