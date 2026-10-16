---
title: "ACE configuration behavior"
description: "Behavior settings for the SASE Admin Center and other TUI surfaces."
---

# ACE configuration behavior

Behavior settings for the SASE Admin Center and other TUI surfaces.

## ace

Configures sase's TUI behavior. Defaults are provided by `src/sase/default_config.yml`.

```yaml
ace:
  axe_description_expanded: true # Services-tab description panel starts expanded
  artifacts:
    description_mode: summary # off | summary | full
    panes:
      "ref:plan":
        description: Project implementation plans
        description_body: Proposed, approved, and archived plan documents.
    relations_expanded: false # Relation panel starts collapsed as a rail; . expands it
    stitches:
      default_query: "sidecar:false merges:hide since:24h"
  tribes:
    default:
      icon: "⌂"
      color: "#87D7FF"
      description: "Agents with no assigned tribe."
    job:
      icon: "†"
      color: "#FFAF5F"
      initially_expanded: false
      description: "Scheduled AXE job automation."
  updates:
    startup_toast: true # show SASE/plugin/agent-CLI updates on startup
    startup_toast_max_commits: 20 # total incoming subjects across repositories
    post_update_toast: true # confirm the version transition after self-update restart
    post_update_toast_diffstat: true # show applied file and line counts
    post_update_toast_commits: true # show applied commits grouped by repository
    post_update_toast_max_commits: 5 # applied subjects shown per repository
    agent_cli_history: true # show Agent CLIs update history in the Updates tab
    agent_cli_history_max_rows: 8 # history rows/runs shown; 0 shows all
    indicator: true # show the segmented SASE + agent-CLI update badge
    prebuild_rust: true # background-cache editable sase-core Rust artifacts
    incoming_commits:
      enabled: true # show incoming commit subjects in the Updates tab
      max_per_repo: 7 # cap subjects per repository
      confirm_max_per_repo: 250 # larger per-repository cap in confirmations
    check_interval_minutes: 10 # attempt a periodic check this often
    check_ttl_minutes: 10 # refresh latest-version checks at most this often
    recompute_interval_minutes: 60 # periodic full network recompute cadence
  prompt_submission:
    confirm_on_enter: true # plain Enter opens the prompt submission panel first
  keymaps:
    config:
      select_subtab: "0"
    statistics:
      prev_view: "left_square_bracket" # active only while Statistics is focused
      next_view: "right_square_bracket"
      select_view: "0"
      jump_to_entry: "apostrophe"
      cycle_range: "t"
      cycle_range_reverse: "T"
      custom_range: "c"
      cycle_group: "g"
      cycle_project_filter: "p"
      cycle_project_filter_reverse: "P"
      scroll_down: "ctrl+d"
      scroll_up: "ctrl+u"
      refresh: "r"
      help: "question_mark"
    app:
      next_patch: "j"
      prev_patch: "k"
      edit_query: "slash" # structured query on Artifacts and Agents; defaults render as `/`
      show_help: "question_mark" # app-level Help; defaults render as bare `?`
      # ... all app-level keybindings are configurable
    modes:
      # Built-in modes (fold, copy, leader, bang) are configurable
      leader_mode:
        prefix: "comma"
        keys:
          repeat_last: "comma" # press the leader prefix, then this key; defaults render as `,,`
          search_forward: "slash" # Agents metadata search; defaults render as `,/`
          models_panel: "m"
          update_sase: "U"
          update_everything: "E"
          full_history_refresh: "y" # opens the Refresh panel on Full history
          collapse_fold_by_hint: "H" # Agents fold-collapse hints; `,H`
      fold_mode:
        prefix: "z"
        keys:
          set_level_1: "1" # PR detail: set every section to level 1
          set_level_2: "2"
          set_level_3: "3"
          cycle_stitches: "c" # `cycle_commits` is accepted as an alias
          cycle_hooks: "h"
          agents:
            set_level_1: "1" # session 1-2; clan/agent 1-3; tribe 1-4
            set_level_2: "2"
            set_level_3: "3"
            set_level_4: "4"
      # Custom modes can be added here
      my_mode:
        prefix: "B"
        keys:
          run_tests:
            key: "t"
            shell: "just test"
```

[Generated reference for `ace`](tui.md#ace)

<a id="aceartifactfileviewer"></a>

### `ace.artifact_file_viewer`

Controls terminal video playback when the external artifact-file viewer opens a video
artifact through mpv.

```yaml
ace:
  artifact_file_viewer:
    video:
      audio: false
      loop: false
      vo: "kitty"
      extra_mpv_args: []
```

[Generated reference for `ace.artifact_file_viewer`](tui.md#ace-artifact_file_viewer)

SASE launches mpv with `--no-config`, so put viewer-specific customization here rather
than in an mpv profile. See [Video Preview](../../agent_images.md#video-preview) for
playback keys.

### `ace.artifacts`

[Generated reference for `ace.artifacts`](tui.md#ace-artifacts)

### `ace.artifacts.stitches`

`ace.artifacts.commits` is an alias for this block and emits a warning when used.

[Generated reference for `ace.artifacts.stitches`](tui.md#ace-artifacts-stitches)

The Stitches pane validates this value with its live query parser. Invalid runtime
configuration produces a warning and falls back to the bundled query. An empty
configured query is valid and includes sidecars; the visible canonical row renders that
state as `sidecar:true merges:hide`. At startup, an explicit project from sase's TUI
query takes precedence over a `project:` in this setting, which takes precedence over
read-only current registered-project inference. The selected project is merged into the
query before the pane is composed. `project:` is singular and cannot be negated or
contain an unquoted comma list. It accepts a configured project name, ProjectSpec
directory key, or alias, and known committed values are rewritten to the configured
name. Once startup merging is complete, no `project:` token always means a true
all-project collection. The Stitches project picker replaces only that token, and **All
projects** removes it while preserving the rest of the query.

Startup injects `limit:<ace.page_size>` (default 100) when this query has no `limit:`
token. An explicit `limit:` in the configured string — including `limit:all` — is left
alone, and deleting the token at runtime leaves the list uncapped. When a numeric cap
clips the result, sase's TUI keeps the token visible and shows a lower-bound total such
as `[1/40+]` in the repository legend while the filter row says `capped`. The legend's
`[P/N]` form means selected one-based position over displayed matched entries.
`limit:all` is accepted as an unlimited synonym but is omitted from canonical query
text. Day-granular `until:` values include the full named day. This setting is
independent of the `sase stitch list` CLI's sidecar opt-in and limit contract.

<a id="aceaxedescriptionexpanded"></a>

### `ace.axe_description_expanded`

Sets whether the Services-tab description panel for service procs, routines, and jobs
starts expanded (`true`, the default) or collapsed to its summary line in each
`sase tui` session. The `toggle_axe_description` keymap action — `d` by default,
configurable under `ace.keymaps.app` — flips the state in memory for the rest of the
session; it never writes the toggle back to configuration, so this key is the only
durable setting. Descriptions themselves follow the
[AXE description grammar](../automation/scheduler-description-grammar.md#description-grammar),
and the panel's layout, height budget, and overflow row are described in
[sase's TUI — Description Panel](../../ace.md#description-panel).

Because the Services tab claims `d`, the `show_diff` action is active only on the
Patches sub-tab.

<a id="acecurrentproject"></a>

### `ace.current_project`

The current project is derived from the head of the VCS macro MRU store — the project
you last launched an agent on. `sase project set-current` and the Projects tab perform
the same MRU promotion without a launch.

[Generated reference for `ace.current_project`](tui.md#ace-current_project)

`seed_agents_query` is **off by default** on purpose. The Agents tab is the primary
at-a-glance view, and its structured query is also read by unread-jump candidates and
prospective-clan selection -- not just the visible list. Turning this on silently
re-scopes those surfaces. The capability is fully built; one line of config enables it.

When `seed_filters` is on, a filter that already has a value — an explicit `project:` /
`+name` query term, or a pick made this session — is left alone. The Patches query is
one of those seeded surfaces: the seed appends a visible `project:<name>` term for the
session only and does not write it to `last_query.txt`. The Agents query seed is also
session-only unless you submit it; it does not update the Agents remembered-query file
on its own. A mid-session MRU change moves the chip but does not re-scope surfaces that
are already open.

### `ace.tribes`

`ace.tribes` is keyed by bare tribe name (without `@`). The special `default` key
configures the reserved `@default` panel. Every configured tribe entry is **required**
to carry a `description`; the other fields are optional:

[Generated reference for `ace.tribes`](tui.md#ace-tribes)

The bundled defaults use ⌂ in sky blue for `default`, ▲ in lavender-purple for `epic`,
and † in amber-orange for `job`. They also use ◆ for `pinned` and ◉ for `review`, whose
identities retain sase's TUI gold fallback; `job` starts collapsed. Because config
entries merge deeply, setting `color: ""` explicitly clears an inherited color without
replacing that tribe's other defaults — overriding only `icon` or `color` on a bundled
tribe still inherits its bundled `description`. A manual panel expand/collapse lasts
only while that panel remains live in the current sase's TUI session. On restart, or
when a tribe panel disappears and later returns, `initially_expanded` is applied again.

SASE bundles display config only for the tribes its own source assigns (`default`,
`epic`, `job`, `pinned`, `review`); a tribe your own macros assign with
`%id(tribe=...)`, `%clan(..., tribe=...)`, or the `#tribe` macro has no bundled entry,
renders with sase's TUI gold fallback and no icon until you configure it under
`ace.tribes`, and — once configured — requires a `description` like any other entry.

A missing or blank `description` on any configured tribe is an error-severity config
diagnostic: sase's TUI Config Center refuses to write _any_ change while it is present,
not just an edit to that tribe. Run `sase doctor -C config.tribes` to list every tribe
missing a description and the exact `ace.tribes.<name>.description` key to set.

Identity colors apply only where sase's TUI already has a structured tribe value. They
do not scan free-form `@...` text or recolor selection markers, fold controls, counts,
statuses, headings, or explanatory copy. Icons likewise appear only on identity surfaces
that already include them; configuring an icon does not add one to compact name-only
rows.

sase's TUI reads this TUI setting from the user-level `~/.config/sase/sase.yml` (and
user overlays), not project-local `sase/sase.yml`.

<a id="acenotificationtabs"></a>

### `ace.notification_tabs`

`ace.notification_tabs` colors, iconifies, and reorders the per-tab counts the top-bar
notification indicator renders, keyed by notification-panel tab key. Keys use the
user-facing tab names: the synthetic `hitl`, `errors`, `general`, `snoozed`, and `muted`
tabs (never the internal `__snoozed__` / `__muted__` spellings), a gate-declared panel
name such as `beads`, or a notification tag.

[Generated reference for `ace.notification_tabs`](tui.md#ace-notification_tabs)

Colors resolve by precedence, highest first: this setting, then a color the sending gate
declared through `presentation.color`, then the built-in default for a tab sase's TUI
ships knowing about, and finally a stable auto-palette entry derived from the tab key.
The last rung means a brand-new tag tab is never colorless and keeps the same color
across restarts. The bundled defaults are amber-orange `hitl`, sky-blue `attention`, red
`errors`, lavender-purple `beads`, gold `general`, grey `snoozed`, and teal `muted`.

Icons resolve through the same shape, with one deliberate difference at the last rung:
this setting, then an icon the sending gate declared through `presentation.panel_icon`,
then the built-in default for a tab sase's TUI ships knowing about, then a default keyed
by the tab's own kind (`panel` or `tag`, so an unrecognized panel or tag tab still gets
a glyph that means something about what kind of tab it is), and finally `•` for a tab
with no kind at all. Unlike color, an icon never falls back to a hashed auto-palette
entry — an arbitrary glyph would teach the reader something false, so the chain always
bottoms out at a meaningful or honestly generic mark instead. The bundled defaults are
`⚑` `hitl`, `?` `attention`, `✖` `errors`, `◈` `beads`, `✉` `general`, `☾` `snoozed`,
and `⊘` `muted`.

Configured icons are explicit choices and are never overridden. sase's TUI guarantees
distinctness only for SASE-chosen generic icons from the kind and last-resort rungs: on
collision it derives an unused ASCII letter or digit from the tab key, and if the key is
exhausted it keeps the generic mark rather than inventing one. Run
`sase doctor -C config.notification_tabs` to report two configured tabs that use the
same glyph.

Priority is an integer in `-1000..1000`. Omit the field to inherit the default for the
tab's kind; there is no empty-string reset, because `0` is a legitimate value. Writing
the number you want at a lower config layer is how an override is cancelled. The
defaults restated from the core's tab order are `Gates` (`hitl`) `60`, any declared
panel `50`, `Errors` `40`, `General` `30`, `Done` (a `done` tag) `20`, any other tag
`10`, `Snoozed` `-10`, and `Muted` `-20`. The shipped `beads` default is `0`, which
drops `Beads` below every ordinary tab and above the two put-away tabs. A tab whose
effective priority differs from its default renders a compact `▴` (raised) or `▾`
(lowered) mark in the panel strip and the indicator tooltip.

Grouping controls section headers in the notification modal, not tab membership. The
shipped strategy is `bead_type` for the `beads` tab, grouping task-bead notifications by
task type with Due, Cleanup, and Other fallback buckets. Set
`ace.notification_tabs.beads.grouping: recent` to open Beads flat by default. Press `S`
in the notification modal to toggle the active tab for the current sase's TUI process
without rewriting config. <a id="acenotificationindicatormaxcounts"></a>

### `ace.notification_indicator_max_counts`

Maximum number of per-tab counts the top-bar notification indicator renders before the
remaining tabs collapse into a single dim `+N` chip. Must be at least 1; defaults to
`4`. Suppressed tabs are still described in the indicator's hover tooltip.

<a id="acepagesize"></a>

### `ace.page_size`

Integer step used by Ctrl+J (load more) and Ctrl+K (unload) on sase's TUI lists, and the
default Artifacts `limit:` value when a pane has no explicit cap. Must be at least 1;
defaults to `100`. Invalid or missing values fall back to 100. Changing this changes the
chord step and any default query that had no explicit `limit:`; it does not rewrite a
user-authored `limit:40`. Launch Control's model-alias history panel is the exception:
Ctrl+J / Ctrl+K there always step by 10 runs, independently of this setting and of
`llm_provider.model_alias_history_limit`.

<a id="acetoolcalls"></a>

### `ace.tool_calls`

```yaml
ace:
  tool_calls:
    slow_threshold_seconds: 20
```

[Generated reference for `ace.tool_calls`](tui.md#ace-tool_calls)

The threshold drives the `SLOW TOOL CALLS` section of the Agents metadata header and the
slow markers in the
[Agents Tab LLM Calls Panel](../tui/agents-deck-panels.md#agents-tab-llm-calls-panel). A
missing, negative, or non-integer value falls back to `20`.

### `ace.updates`

[Generated reference for `ace.updates`](tui.md#ace-updates)

Set `check_ttl_minutes` to change the startup cache TTL. Although `check_ttl_hours`
remains accepted for compatibility, sase's TUI resolves the merged `check_ttl_minutes`
value first; the bundled 10-minute default therefore prevents an hours-only override
from taking effect.

<a id="acekeymaps"></a> Moved to
[ACE keymap configuration](ace-keymap-configuration.md#acekeymaps).
<a id="acesnippetconfigpath"></a> Moved to
[ACE prompt configuration](ace-prompts.md#acesnippetconfigpath).
<a id="acesnippets"></a> Moved to
[ACE prompt configuration](ace-prompts.md#acesnippets). <a id="acepromptcompletion"></a>
Moved to [ACE prompt configuration](ace-prompts.md#acepromptcompletion).
<a id="acepromptspellcheck"></a> Moved to
[ACE prompt configuration](ace-prompts.md#acepromptspellcheck).
<a id="acepromptstash"></a> Moved to
[ACE prompt configuration](ace-prompts.md#acepromptstash). <a id="aceagentdecks"></a>
Moved to [ACE prompt configuration](ace-prompts.md#aceagentdecks).
<a id="aceagentheader"></a> Moved to
[ACE prompt configuration](ace-prompts.md#aceagentheader). <a id="aceagenttabs"></a>
Moved to [ACE prompt configuration](ace-prompts.md#aceagenttabs).
<a id="acepromptsubmission"></a> Moved to
[ACE prompt configuration](ace-prompts.md#acepromptsubmission).
<a id="acepromptinputs"></a> Moved to
[ACE prompt configuration](ace-prompts.md#acepromptinputs).

## Related

- [TUI configuration](tui.md) — generated ACE keys and defaults.
- [SASE Admin Center](../tui/admin-center.md) — editor behavior.
