---
title: "ACE prompt configuration"
description: "Prompt completion, snippets, prompt history, and agent deck settings."
---

# ACE prompt configuration

Prompt completion, snippets, prompt history, and agent deck settings.

<a id="acesnippetconfigpath"></a>

## `ace.snippet_config_path`

Names the config file that receives new `ace.snippets` entries written from the prompt
bar — the `gt` / `Ctrl+G t` snippet target pane, the `gX` / `Ctrl+G X` save panel's
snippet mode, and the
[Snippets panel](../tui/prompt-completion-panels.md#snippets-panel) add form all default
to it.

An empty string (the default) resolves to the user's `sase.yml` — the chezmoi source
file under `dot_config/sase/` when [`use_chezmoi`](core-behavior.md#usechezmoi) is
enabled, otherwise `~/.config/sase/sase.yml`. A relative configured value resolves
against `~/.config/sase/`, so `sase_snippets.yml` means
`~/.config/sase/sase_snippets.yml`. The path's suffix must be `.yml` or `.yaml`; the
file itself need not exist yet, but its parent directory must be writable.

A configured value that is unusable — wrong suffix, unwritable parent, invalid YAML, or
a project `sase/sase.yml` that needs migration — falls back to the default and reports
why: both the `gt` location picker (as a footer warning) and trigger-name panel and the
`gX` save panel's snippet mode append the reason to the destination line (e.g.
`configured path unusable: read-only`) rather than silently writing somewhere else. When
set to a usable file, it is the `★ configured` default of the snippet location picker
and outranks last-used. The `gX` save panel additionally always offers the resolved
`ace.snippet_config_path` destination as a selectable, pre-highlighted row — even when
it is a custom filename or path that falls outside the standard discovered locations
(`sase.yml` / `sase_*.yml` under `~/.config/sase/` or the chezmoi equivalent, and the
project's `sase/sase.yml`) — so a configured preference is never silently dropped from
the picker.

```yaml
ace:
  snippet_config_path: "sase_snippets.yml"
```

See
[Authoring a snippet from the prompt bar](../tui/snippets.md#authoring-a-snippet-from-the-prompt-bar).

Source: `src/sase/macro/snippet_targets.py`

## `ace.snippets`

Defines expandable text snippets for the prompt input widget. Each entry maps a trigger
word to a template string. Press `Tab` in the prompt input to expand the trigger word
before the cursor.

```yaml
ace:
  snippets:
    fix: "Please fix the following issue:\n$0"
    review: "Review this code for correctness, performance, and style."
    plan: "#plan\n$0"
```

Templates can contain `$1`, `$2`, ... tabstops plus `$0` for the final cursor position.
In sase's TUI prompt input, `Tab` advances through those stops and `Shift+Tab` retreats
through stops already visited. Expanding a trigger inside an active snippet nests the
new snippet's tabstops before the remaining outer stops. Templates can also splice
another merged snippet with `#[trigger]`; use `#[trigger(value)]` or `#[trigger:value]`
to fill referenced `$1`, `$2`, ... tabstops before splicing.

Every effective snippet also gains a generated initial-capital alias: only the first
character of the trigger and of the resolved template is uppercased, so
`foo: "foo bar baz"` also exposes `Foo` → `Foo bar baz`. Already-capitalized,
digit-leading, and underscore-leading triggers produce no extra entry, and an explicitly
authored `Foo` is never replaced. These aliases are runtime-only and are never written
back into config. See [Capitalized aliases](../tui/snippets.md#capitalized-aliases) for
the full rule.

See [Snippets](../tui/snippets.md#snippets-1) for usage details and
[Macro fields — Snippet CLI](../macros/fields.md#snippet-cli) for `sase snippet list`,
`show`, `add`, and `delete`.

Source: `src/sase/ace/tui/widgets/prompt_text_area.py` <a id="acepromptcompletion"></a>

## `ace.prompt_completion`

Controls automatic non-disruptive suggestions and manual prompt-local and prompt-history
word completion in sase's TUI prompt input. Suggestions appear in the prompt-bar
subtitle and are accepted with `Ctrl+L`; `Enter` still submits the prompt as typed.
Manual structured/path `Ctrl+T` completion is independent of the automatic settings, and
the `Ctrl+R` recursive fuzzy file finder is always manual.

```yaml
ace:
  prompt_completion:
    auto: soft
    debounce_ms: 90
    auto_file_paths: false
    auto_macro_menu: true
    auto_directive_menu: true
    auto_artifact_menu: true
    auto_jinja_menu: true
    max_auto_rows: 1
    history_word_count: 10000
    common_placeholder_count: 100
    word_min_length: 5
    word_ranking: smart
    word_ranking_signals: true
    placeholder_ranking: smart
    placeholder_ranking_signals: true
    next_word: auto
    next_word_max_words: 4
    next_word_confidence: balanced
    next_word_sources: [history]
```

[Generated reference for `ace.prompt_completion`](tui.md#ace-prompt_completion)

The minimum applies to the complete candidate, so a shorter typed prefix can still
complete an eligible word. Prompt-local words below the threshold are skipped before
sase's TUI considers the prompt-history fallback. Candidates from history retain their
original spelling and, under the default `word_ranking: smart`, are ordered by a
weighted composite of how strongly each word relates to the words already in the prompt
(`0.50`), how recently it was used (`0.30`), and how often it was used (`0.20`). Setting
`word_ranking: recent` restores plain most-recently-used order. A warm next-word model
promotes current-word matches ahead of that order only while `word_ranking` is `smart`
and `next_word` is not `off`. `recent` leaves the menu on its non-prediction order. The
warm cache holds the prompt-word index off-thread and is rebuilt when history shards or
the shared minimum change, while `Ctrl+D` deletions apply at query time without a
rebuild. Setting `history_word_count: 0` disables only the history fallback; eligible
prompt-local words remain available. See the History-word completion bullet in
[Prompt completion](../tui/prompt-completion.md) for the score meter, reason chip, and
legend that `word_ranking_signals` controls.

Common placeholders are stored at `sase_home()/prompt_placeholders.json` and are learned
from complete raw `<foobar>` tags outside literal zones in submitted, failed-launch, and
cancelled prompt drafts. When the store is first created, sase's TUI seeds it once from
bounded prompt history so existing tags can appear immediately. Retention evicts
least-recently-used entries down to `common_placeholder_count`. By default
(`placeholder_ranking: smart`) the `<` menu ranks saved tags by relation to the prompt
being edited, recency, and frequency; `placeholder_ranking: recent` restores the stored
count-then-recency order. Setting `common_placeholder_count: 0` disables recording,
loading, and display of saved placeholders; prompt-local placeholder completion still
works.

The former `history_word_min_length` key has been replaced by `word_min_length`.
Existing overrides must rename the key to keep controlling word completion.

The `+query` project/Patch picker uses the same completion panel and opens when the plus
is at the start of the prompt or directly follows whitespace, `{`, or `|`. It is not
disabled by `auto_macro_menu`. Manual `Ctrl+T` project/Patch completion uses the same
token rule and works regardless of these automatic-completion settings.

`@` reference completion uses a project-scoped artifact catalog and warm prompt path
inventory. `auto_artifact_menu` controls automatic opening of the grouped menu from bare
`@`, narrowed artifact-kind or local-path queries such as `@pl` and `@src/`, and
`@kind:` payload contexts; manual `Ctrl+T` remains available. Before a `:` appears,
local file rows stay hidden while the query prefix-matches an artifact kind (including
bare `@`). The panel's `[^T] files` hint marks that state; the first `Ctrl+T` reveals
files without completing the kind, and a later press completes normally. Queries with no
kind prefix match show file rows automatically. File rows preserve the `@` sigil on
insertion, directories drill down, and dotfiles are hidden unless the typed path segment
starts with `.`. A cold path inventory can briefly show a loading row while sase's TUI
refreshes it off-thread. Document, chat, indexed-file, bead, and agent payloads use
bounded project-scoped catalogs; commit and bug candidates are projected only from
already-loaded Artifacts-pane snapshots.

The `%model:` / `%m:` value menu and the `=alias` / `==model` model shortcut menus are
also controlled by `auto_directive_menu`. The `%model:` menu lists inline-typable model
names, the five built-in size aliases (`@xsmall`, `@small`, `@medium`, `@large`,
`@xlarge`), configured model aliases, and provider drill-down rows. Provider short
aliases are shown as filter/display hints but are not inserted. The `=alias` shortcut is
alias-only: accepting `=la` on `@large` rewrites the token to `%m:@large`. The `==model`
shortcut lists concrete model rows, so accepting `==gpt` can rewrite the token to
`%m:gpt-6.1-sol`; provider-qualified input such as `==codex/g` narrows to that provider.
The old `*alias` and `**model` forms remain ordinary prompt text. `Ctrl+T` remains
available for both shortcut menus when automatic directive menus are disabled.

File-path completion roots relative lookups in the prompt-selected workspace. A
`+<project>` [project tag](../macros/reference-syntax.md#project-tags), registered
workspace-provider refs, and known-project refs such as `#git:<project>` or
`#gh:<owner>/<repo>` can root lookup in that project checkout. If no prompt workspace
ref resolves, lookups fall back to the TUI process directory. These root rules are
shared by live path suggestions, manual `Ctrl+T` path completion, and the manual
`Ctrl+R` recursive finder.

Source: `src/sase/ace/tui/widgets/prompt_completion.py`,
`src/sase/ace/tui/widgets/_prompt_soft_completion.py`,
`src/sase/ace/tui/widgets/history_word_completion.py`,
`src/sase/history/prompt_word_index.py`, `src/sase/history/prompt_word_ranking.py`,
`src/sase/history/prompt_placeholders.py`,
`src/sase/ace/tui/widgets/prompt_completion_root.py`,
`src/sase/ace/tui/widgets/recursive_file_finder.py` <a id="acepromptspellcheck"></a>

## `ace.prompt_spellcheck`

Controls the sticky misspelling highlight in sase's TUI prompt input. Every word `K`
proves misspelled (an aspell `misspelled` verdict) is remembered durably and underlined
in every prompt input from then on; `K` on a word already remembered is what teaches
sase's TUI about it, not a background spell-checker.

```yaml
ace:
  prompt_spellcheck:
    highlight: true
    max_remembered_words: 5000
```

[Generated reference for `ace.prompt_spellcheck`](tui.md#ace-prompt_spellcheck)

Remembered words are stored at `sase_home()/prompt_misspellings.json`, casefolded for
matching but keeping the first-seen spelling. Pressing `a` in the correction panel
accepts a word instead of applying a suggestion, moving it into the accepted list so it
is never flagged again; `K` on an already-correct remembered word (for example, after
adding it to your `aspell` personal dictionary) clears it automatically. Retention
evicts the oldest entries once a list exceeds `max_remembered_words`.

Source: `src/sase/history/prompt_misspellings.py`, `src/sase/core/word_lookup.py`,
`src/sase/ace/tui/widgets/_misspelling_highlight.py`,
`src/sase/ace/tui/actions/_startup_misspellings.py`,
`src/sase/ace/tui/modals/spellcheck_panel_modal.py` <a id="acepromptstash"></a>

## `ace.prompt_stash`

Controls Stash Trash recovery in sase's TUI Prompts overlay (see
[Prompts Overlay](../tui/prompts-overlay.md#prompt-history-modal)). Trash recovers only
drafts deliberately discarded from Stash, up to the configured row limit.

```yaml
ace:
  prompt_stash:
    trash_limit: 100
```

[Generated reference for `ace.prompt_stash`](tui.md#ace-prompt_stash)

A lowered limit is applied the next time the overlay opens. Over-limit rows are
permanently deleted, oldest discarded first, and a toast reports how many were deleted.
The Trash list in that same window still shows the rows from before the deletion.
`Enter` on one of those already-deleted rows does not bring it back. The Trash view then
repaints from the store, so every already-deleted row disappears. Close the overlay and
open it again to see the rows that remain without pressing `Enter`. See
[Prompts Overlay](../tui/prompts-overlay.md#prompt-history-modal) for the toast text and
the failure case. Trash requires the current stash core binding: restart old TUI
processes before the new behavior takes effect, since mixed-version operation is
unsupported. <a id="aceagentdecks"></a>

Source: `src/sase/ace/config.py`, `src/sase/core/prompt_stash_facade.py`,
`src/sase/ace/tui/actions/agent_workflow/_prompt_bar_stash_restore.py`

## `ace.agent_decks`

Controls whether a multi-card agent data deck renders spread (every card on one
scrollable page) or paged (one card at a time) on the Agents tab deck panels, under the
automatic deck view (see [Deck Views](../tui/agent-statuses.md#deck-views)). A locked
deck view bypasses these thresholds entirely.

```yaml
ace:
  agent_decks:
    spread_max_screens: 1.5
    block_spread_max_screens: 1.5
    final_tail_delay_seconds: 5.0
```

Jump to any deck with `p` then its picker letter: `m` Main, `f` Files, `t` Tools, `n`
FINAL (capitals open it in the other panel). See
[Agent data decks and cards](../tui/agent-statuses.md#agent-data-decks-and-cards) and
[Finalizers on the Agents tab](../tui/agent-statuses.md#finalizers-on-the-agents-tab).

<a id="aceagentheader"></a>
[Generated reference for `ace.agent_decks`](tui.md#ace-agent_decks)

Source: `src/sase/ace/tui/agent_decks_settings.py`

## `ace.agent_header`

Controls how many rows of the selected agent's `RAW PROMPT` the collapsed Agents-tab
header previews. Session headers also show distinct recorded models while collapsed;
those model rows use the share budget before the optional prompt preview. The preview
shows at most `collapsed_preview_max_rows` rows and can use zero rows when identity and
model metadata need the available space.

```yaml
ace:
  agent_header:
    collapsed_max_share: 0.35
    collapsed_preview_max_rows: 3
```

<a id="aceagenttabs"></a>
[Generated reference for `ace.agent_header`](tui.md#ace-agent_header)

Source: `src/sase/ace/tui/agent_header_settings.py`

## `ace.agent_tabs`

Agent tab settings for the Agents tab. `machine_tabs` selects machine-tab mode: `auto`
shows one machine tab per configured dispatch machine (and a single roster when no
machines are configured), `on` always uses machine tabs, and `off` never does. `tabs`
holds per-tab styling and ordering keyed by canonical tab name; invalid names are
dropped.

```yaml
ace:
  agent_tabs:
    machine_tabs: "auto"
    launch_from_view: true
    tabs:
      sase:
        color: "#AF87FF"
        icon: "◈"
        order: 0
        description: "SASE project agents."
```

[Generated reference for `ace.agent_tabs`](tui.md#ace-agent_tabs)

Source: `src/sase/ace/tui/agent_tabs_settings.py` <a id="acepromptsubmission"></a>

## `ace.prompt_submission`

Controls whether plain `Enter` asks for confirmation before launching agent prompts from
sase's TUI prompt input.

```yaml
ace:
  prompt_submission:
    confirm_on_enter: true
```

[Generated reference for `ace.prompt_submission`](tui.md#ace-prompt_submission)

When enabled, the panel appears for non-empty ordinary single-pane prompts, targeted
single-pane drafts, and multi-pane prompt stacks. `g<enter>` in NORMAL mode and
`Ctrl+G Enter` in INSERT mode stay direct selected-pane launch routes. Set
`confirm_on_enter: false` to restore immediate plain-Enter launch: a single pane sends
normally, a stack submits the active pane, and a targeted pane launches instead of
opening the launch/write/save chooser.

<a id="acepromptinputs"></a> Source: `src/sase/ace/tui/prompt_submission_settings.py`,
`src/sase/ace/tui/widgets/_prompt_text_area_key_handling.py`,
`src/sase/ace/tui/modals/prompt_submit_choice_modal.py`

## `ace.prompt_inputs`

Controls how sase's TUI treats raw `<placeholder>` tags when a prompt is submitted or
saved as a macro.

```yaml
ace:
  prompt_inputs:
    collect_raw_placeholders: true
    macro_placeholder_args: true
```

[Generated reference for `ace.prompt_inputs`](tui.md#ace-prompt_inputs)

Raw placeholders in YAML frontmatter, inline code, fenced code, or
`%macros_enabled:false` regions are never collected. See
[Raw Prompt Placeholders](../macros/templating.md#raw-prompt-placeholders) for the
submit panel, literal-tag control, and macro conversion workflow.

Source: `src/sase/agent/prompt_placeholder_inputs.py`,
`src/sase/ace/tui/actions/agent_workflow/_launch_start.py`,
`src/sase/ace/tui/actions/agent_workflow/_prompt_bar_save_macro.py`,
`src/sase/ace/tui/widgets/_prompt_input_bar_local_macro_actions.py`,
`src/sase/ace/tui/widgets/_local_macro_conversion.py`

## Related

- [Prompts and tools configuration](prompts.md) — generated prompt and tool keys.
- [SASE Admin Center](../tui/admin-center.md) — prompt and snippet controls.
