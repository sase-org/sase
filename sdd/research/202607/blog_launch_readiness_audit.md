# Blog Launch Readiness Audit — XPrompts, Agents Tab, Install/Init/Config

**Date:** 2026-07-02
**Context:** An announcement blog post for SASE is being prepared. It will focus on (1) xprompts, (2) the Agents tab of
the `sase ace` TUI, and (3) what users must do to install, initialize, and configure SASE. This audit maps the current
state of all three areas and ranks the gaps that matter most for a public launch, where brand-new users will follow the
post's instructions verbatim and form first impressions in minutes.

**Method:** Three parallel codebase audits (one per area), followed by manual spot-verification of the highest-stakes
claims (the quickstart's `#cd` isolation narrative, the unknown-`#name` expansion path, and the draft xprompts post's
YAML example). All file:line references were reported against the tree at commit `c05047fa5`.

---

## Top 3 Recommended Improvements (ranked)

### 1. Fix the workspace-isolation narrative in the published quickstart (docs-only, safety-critical)

`docs/blog/posts/hello-sase-your-first-15-minutes.md` — the published post the announcement will inevitably funnel
readers into — makes a false safety claim at its core:

- Step 3 (~line 73): "`sase run` allocates an isolated **workspace** — a sibling clone of the repo named `sase_<N>` —
  and runs the provider CLI there... what lets a failed run be retried without touching your real checkout."
- Step 5 (~line 117): "the agent has permission to make a visible diff in its isolated workspace. Review the resulting
  workspace or ChangeSpec before bringing anything back to your primary checkout."

Both steps use `#cd:$(pwd)`, and `#cd` deliberately skips workspace allocation: the plugin's
`ws_get_workspace_directory` returns `primary_workspace_dir` unchanged
(`src/sase/workspace_provider/plugins/cd_workspace.py:61-71`; confirmed by `docs/workspace.md:130-133`, which states
`#cd` "deliberately skips numbered workspace allocation, checkout, diff, submit, and release"). **The very first
editable command the quickstart hands a reader (Step 5) modifies their real checkout while telling them it won't.**
Two adjacent inaccuracies compound it:

- Even for real `#git:` runs, "sibling clone named `sase_<N>`" is stale — the default `workspace.root` is now
  `xdg-state` (platform state dir); the sibling layout is opt-in via `workspace.root: adjacent`
  (`src/sase/default_config.yml:344-348`).
- Step 5's "review the resulting workspace or ChangeSpec" describes artifacts a `#cd` run never creates (no ChangeSpec
  appears on the PRs tab, no separate workspace exists), which also breaks Step 4's "find the run's workspace path"
  narrative.

**Why #1:** it is a data-safety hazard (trusting readers let an agent edit their actual checkout believing it's
sandboxed) and a credibility hazard (readers who notice will distrust the rest of the docs), on the exact page the
announcement drives traffic to. The fix is cheap — either rewrite Steps 3–5 around `#cd`'s true in-place semantics
("the agent works directly in this directory; start read-only") or switch the editable example to a `#git:` run that
actually allocates an isolated workspace. The new announcement post must also describe isolation accurately.

### 2. Make xprompt authoring failures loud (the blog's headline feature fails silently in every common mistake mode)

The announcement features xprompts, so the launch-week user journey is "copy an example, tweak it, run it." Today every
common mistake in that journey produces **zero feedback**:

- **Unknown `#name` is silently passed to the model.** The expander skips unknown references
  (`src/sase/xprompt/processor.py:397-407` — `break` when no known xprompt, `continue` per unknown match) and no
  warning exists anywhere in the launch path (`src/sase/agent/multi_agent_xprompt.py`,
  `src/sase/prompt/cli_run.py` — grep found none). A typo like `#reviewww`, or a reference to an xprompt that failed
  to load, sends the literal text to the LLM with no diagnostic.
- **Malformed definitions silently vanish.** Workflow YAML parse errors return `None`
  (`src/sase/xprompt/workflow_loader.py:256-257`), load-time validation errors return `None` or defer
  (`workflow_loader.py:200-201, 236-239`), broken markdown frontmatter is silently treated as body text
  (`src/sase/xprompt/loader_parsing.py:50-52`), and project `sase.yml` load errors log at debug only
  (`src/sase/xprompt/loader_sources.py:471-472`). Net effect: one YAML typo and the user's xprompt simply doesn't
  appear in `sase xprompt list`, completion, or expansion — nowhere they'd look says why.
- **Name shadowing is silent.** Discovery is strict first-wins across a 9-tier priority order
  (`src/sase/xprompt/loader.py:98-150`) with no collision/shadow warning; a user's `xprompts/commit.md` silently
  overrides the built-in `#commit`.

**Recommended scope before launch:** (a) warn at expansion/launch time when a `#name`-shaped token survives expansion
unresolved; (b) surface definition load errors in `sase xprompt list` and `sase doctor` (a "skipped: <file>: <error>"
line is enough); (c) fix the flagship example in `docs/blog/posts/xprompts-in-depth.md:106` — `input: target: word` is
invalid YAML (verified: `yaml.safe_load` raises), and because of the silent-frontmatter failure above, a reader copying
it verbatim gets `{{ target }}` undefined with no error. That post is also still `draft: true` (line 4) and absent from
the mkdocs nav/built site — decide whether it publishes alongside the announcement, since without it the on-ramp jumps
from a 3-minute taste (quickstart Step 6) straight to the 1830-line `docs/xprompt.md` reference.

**Why #2:** these failures hit exactly the audience the post recruits, in their first ten minutes, on the feature the
post is about — and the failure mode ("nothing happened, no error") is the kind that makes people close the tab.

### 3. Agents-tab screenshot & first-impression pass (regenerate stale goldens, de-emoji markers, soften STOPPED)

The Agents tab is genuinely mature (polished zero-state onboarding panel, `?` help modal, cached-then-refresh loading),
but four launch-visible issues cluster around screenshots and first impressions:

- **Stale visual goldens on the featured tab.** The June-30 tab reorder (`2404af6d2`, Agents moved to first position;
  `src/sase/ace/tui/tab_order.py:16`) regenerated axe/changespec/modal goldens but **not** the agents-list family —
  `agents_list_120x40.png`, `agents_unread_highlight`, `agents_stopped_status`, `agents_selected_row` (last touched
  `70d906f61`, 2026-06-16) still show the old "PRs Agents AXE" order. Visual tests are deselected by default
  (`pyproject.toml:199-205`), so `just test-visual` now fails on the featured tab and any reference screenshot pulled
  from goldens shows the wrong tab order. Regenerating restores the visual safety net right when it matters most.
- **Emoji markers render as tofu on non-emoji terminals.** Live `🏃‍♂️` (a ZWJ sequence), `✅`/`❌`, `✋`
  (`src/sase/ace/tui/widgets/_agent_list_render_layout.py:40-54`), `🐍`/`🐚` step glyphs
  (`_agent_list_styling.py:80-81`). The goldens themselves (FiraCode) show tofu boxes, and ZWJ/variation-selector
  emoji have inconsistent terminal cell widths → misaligned columns. At minimum, take blog screenshots on a verified
  emoji-capable terminal; better, add a font-safe glyph fallback/config.
- **Persistent bright-red "STOPPED" badge** whenever the axe daemon isn't running
  (`src/sase/ace/tui/widgets/_keybinding_status.py:194-199`). A first-time user who hasn't started axe sees an
  alarm-red badge that reads as an error; it appears in every populated golden. A neutral "axe: idle" treatment would
  remove the false-alarm from every screenshot and every first session.
- **Folding is invisible.** Child entries (the workflow-step rows the post will showcase) are hidden by default, and
  the `h`/`l`/`H`/`L` bindings are `show=False` (`src/sase/ace/tui/bindings.py:24-25,85`) and unmentioned by the
  onboarding panel (`src/sase/ace/tui/widgets/agent_onboarding.py`). One onboarding line ("press `l` to reveal
  workflow steps") closes the gap.

**Why #3:** the announcement is screenshot-driven, and these are the pixels readers judge. Each item is small; together
they are the difference between "polished TUI" and "rough demo" on first look.

---

## Area 1: XPrompts — Current State

Implementation is large and mature, centered in `src/sase/xprompt/` (singular; shipped examples live in
`src/sase/xprompts/`, plural):

- **Parsing/expansion:** `processor.py` (reference regex :56-60, iterative expander :267/:333, 100-iteration circular
  guard), eight `_parsing*.py` modules (colon/backtick/plus/text-block/shorthand args, VCS refs), `_jinja.py` (Jinja2 +
  typed inputs), `_fenced_blocks.py`/`_disabled_regions.py` (protection), `directives.py` (`%model`, `%name`, `%wait`,
  `%auto`, …), `segment_separators.py` + `src/sase/agent/multi_agent_xprompt.py` (`---` multi-agent fan-out).
- **Discovery:** `loader.py` facade with 9-tier priority (:105-150), `loader_sources.py` (config field is consistently
  `xprompts:`, read at :478), frontmatter parsing in `loader_parsing.py`.
- **Workflows (.yml):** `workflow_loader*.py`, `workflow_executor.py` (599 lines), `workflow_runner.py` (660 lines),
  validators, HITL support, `graph.py`/`explain.py` (Mermaid DAG + dry-run).
- **CLI:** `sase xprompt expand/explain/graph/list/catalog` (`src/sase/main/xprompt_handler.py:13-22`).
- **TUI discoverability is strong:** Admin Center XPrompts tab, `Ctrl+T` autocomplete in the prompt input, `gx` to
  save a prompt as an xprompt, browser/select modals (`src/sase/ace/tui/modals/xprompt_browser_*.py` et al.).
- **Tests:** extensive (655 test files reference xprompt/workflow); skips are environment guards only, no concerning
  xfails.

**Docs:** `docs/xprompt.md` (1830 lines, in nav), `docs/workflow_spec.md` (958 lines), quickstart Step 6 (accurate —
CWD `xprompts/*.md` is a real loader source, `loader.py:107`), plus the unpublished `xprompts-in-depth.md` draft.

**Other findings (below top-3 cut):**

- `sase xprompt list` emits raw single-line JSON (`xprompt_handler.py:153`); docs tell users to pipe through `jq`
  (`docs/xprompt.md:106`). The only CLI discovery command is machine-format.
- `sase xprompt catalog` requires an external PDF engine (`wkhtmltopdf`/`xelatex`/`pdflatex`) and exits code 3 on
  fresh installs (`xprompt_handler.py:210-212`; `INSTALL.md:138`) — the docs point new users at it
  (`docs/xprompt.md:122-129`).
- `sase init` scaffolds no starter `xprompts/` example; the "first xprompt" path depends entirely on copying doc
  snippets correctly (which ties back to the silent-failure findings).
- Minor: `loader.py:111` docstring advertises a `snippets:` source that the loader doesn't read; "XPrompt" vs
  "xprompt" capitalization varies in prose ("x-prompt" never occurs — that variant is a non-issue).

## Area 2: Agents Tab / TUI — Current State

- **Structure:** `TAB_ORDER = ("agents", "changespecs", "axe")` (`tab_order.py:16`), Agents is default/leftmost. App
  composition in `app.py:271-313`: `AgentInfoPanel` counts bar + `AgentList` (OptionList, `agent_list.py:48`) +
  `AgentDetail` + overlay `AgentOnboarding`. Grouping modes (project/date/status) cycle with `o`/`O`; folding via
  `actions/agents/_folding.py:544-582`.
- **Refresh model** (per `memory/tui_perf.md`): cached data shown instantly, background reload, 150 ms debounced
  detail pane, `patch_row` fast paths. Index/load errors surface as warning toasts (`_loading_apply.py:421-436`).
- **First-run experience is a strength:** cold-start spinners + "starting Xs" stopwatch (`_startup_mount.py:154-188`),
  and a polished, keymap-aware, purpose-built "Welcome to sase ace" zero-state panel (`agent_onboarding.py`, confirmed
  clean in `tests/ace/tui/visual/snapshots/png/agents_onboarding_120x40.png` — regenerated post-reorder, `282fc6ccf`).
- **Help:** `?` modal with Navigation/Actions/Folding/Leader-Bang-Copy modes/query syntax/glyph legend
  (`help_modal/agents_bindings.py:13-307`); status lifecycle is color-coded text labels with a legend — clear once
  past the issues above.

**Other findings (below top-3 cut):**

- "No prompt file found." shows in the AGENT PROMPT pane of the canonical goldens' selected DONE agents
  (`prompt_panel/_agent_display_render.py:290`) — partly a fixture artifact, but baked into the featured screenshots
  and it looks broken. Worth fixing fixtures when regenerating goldens.
- No custom crash screen: `ace_handler.py:138-165` wraps only `QueryParseError`; other unhandled exceptions fall
  through to Textual's raw traceback. File logging exists (`~/.sase/logs/tui.log`), and repro capture exists but is
  leader-mode gated and undiscoverable.
- Onboarding panel shows whenever the agent list is empty after first load (`_display_detail.py:130-136`), so a hard
  backend failure returning zero agents renders "Welcome" instead of an error state.
- Low: scrollbar-gutter artifact on the onboarding panel (`styles.tcss:1395-1401`); `x` doubly bound to `kill_agent`
  and `toggle_hide_submitted` (`default_config.yml:98,134`) — works via tab-gating in `app.py:262-269`, but latent.

## Area 3: Install / Init / Config — Current State

- **Install:** `sase` 0.8.0, `requires-python >=3.12`, ~20 console scripts, plugin entry-point groups
  (`pyproject.toml:76-110`). Hard dependency on `sase-core-rs>=0.3.0,<0.4.0` (no pure-Python fallback); prebuilt
  wheels claimed for CPython 3.12+ Linux x86_64/aarch64 + macOS (`INSTALL.md:30`). Recommended path is
  `uv tool install sase` (pip is an escape hatch because `sase update`/`sase plugin install` need the uv-tool
  receipt). **Publish CI genuinely smoke-tests the built wheel** — clean venv, `sase core health --json`,
  `sase version`, provider-less `sase doctor` (`.github/workflows/publish.yml:86-167`).
- **Init:** `sase init` coordinates memory → sdd → skills planners with `-c/--check` and `-y/--yes`
  (`src/sase/main/parser_init.py:48-133`); non-TTY without `--yes` prints guidance and exits 1
  (`init_onboarding.py:254-257`). No init path creates `~/.config/sase/sase.yml` — and none is needed.
- **Config:** merge chain bundled `default_config.yml` → plugins → `~/.config/sase/sase.yml` → overlays → `./sase.yml`
  (`src/sase/config/core.py:289-363`). Provider autodetect (`llm_provider.provider: ""`,
  `default_config.yml:277-278`; `registry.py:316-339`) means **zero config file required** for a user with a provider
  CLI on PATH — a genuine friction-reducer worth stating in the post. `sase doctor` is a strong, actionable readiness
  gate with per-provider install/auth hints (`src/sase/doctor/checks_providers.py:19-45,148-181`) — the post should
  lean on it.

**Other findings (below top-3 cut):**

- **Missing/broken `sase-core-rs` error tells public users to run developer tooling:** "reinstall with `just install`
  (or `just rust-install` … ../sase-core)" (`src/sase/core/rust.py:26-29,45-49`). A `uv tool install` user has no
  `just`, no repo, no `../sase-core` — and this is the exact audience most likely to hit a missing-wheel platform.
  Cheapest high-value fix outside the top 3.
- **`sase run` provider-missing error misdirects:** "Install a provider plugin or set llm_provider.provider
  explicitly" (`registry.py:336-339` via `query_handler/_launch.py:50`) — providers are built-in; the real fix is
  installing/authenticating a CLI, and the message never mentions `sase doctor`, which has the good version.
- **Config YAML errors are silently swallowed** (`config/core.py:158-167`, debug-only), unknown keys silently
  dropped; no `sase config validate` command (`parser_commands.py:29-61` — only `layers`/`mentor-match`/`show`).
  "My setting had no effect" confusion with no diagnostic.
- No documented minimal config / scaffold for users who want to pin a provider/model (`docs/configuration.md` is a
  ~150 KB reference with no "minimal config" section).
- Blog Step 1 omits git as a prerequisite; `sase doctor` treats git + `user.name`/`user.email` as required
  (`checks_runtime.py:53-58,296-302`); `INSTALL.md:118-122` documents it (blog/README-vs-INSTALL inconsistency).
- POSIX-only support is stated only in `pyproject.toml:22` classifiers and `INSTALL.md:30`; the README/blog never say
  Windows is unsupported.
- Cosmetic: stale untracked `dist/` artifacts at 0.4.0 while current is 0.8.0 — a foot-gun for a manual upload from a
  stale tree.

---

## Summary

The three featured surfaces are all fundamentally launch-worthy: xprompts are deep and well-tested, the Agents tab has
real first-run polish (onboarding panel, doctor-style loading states, help modal), and the install path is genuinely
`uv tool install sase` + autodetect with a CI-smoke-tested wheel. The risks are concentrated in three places: **the
published quickstart tells readers `#cd` runs are isolated when they edit the real checkout in place** (fix before the
announcement links to it), **xprompt mistakes fail silently in every common mode** (typo'd `#name`, broken YAML, name
shadowing — add warnings and fix/publish the in-depth post's broken example), and **the Agents tab's screenshot surface
has stale goldens, tofu-prone emoji, and an alarm-red STOPPED badge** (a small polish pass before screenshots are
taken). All three are small relative to the credibility they protect.
