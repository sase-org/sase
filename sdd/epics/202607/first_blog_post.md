---
create_time: 2026-07-07 23:59:07
bead_id: sase-5k
tier: epic
status: wip
prompt: sdd/prompts/202607/first_blog_post.md
---
# Plan: First SASE Blog Post — "SASE: Structured Agentic Software Engineering"

## Goal

Write and integrate the **first real SASE blog post** — a narrowly focused, user-facing launch post that covers exactly
four topics:

1. How SASE integrates with **agent CLIs instead of models directly**.
2. How **XPrompts** work.
3. How the **Agents tab UX** works in the `sase ace` TUI.
4. How to **install, configure, and initialize** SASE properly.

The post opens with an introduction that explains the status quo it improves on (the "Boris Cherny method": many tmux
windows, each holding one agent CLI instance, and a human hopping between them — as automated by Bryan's
`tmux_ai_window` script) and closes with a short teaser of future posts. The five demo GIFs under `demos/out/` are
reviewed, improved where necessary, and integrated into the post.

## Why now / context

- A 40k-word-class launch draft already exists at `docs/blog/posts/why-coding-agents-need-orchestration.md` ("[00]"),
  but an external review (consolidated in Bryan's notes) found it too long (~5,400 words), too fragmented (20 H2
  sections), image-free, missing Open Graph metadata, and burdened by a "[00]" title that "feels like homework." The
  review proposed the title **"SASE: Structured Agentic Software Engineering"**.
- Bryan's outline notes (Obsidian `sase_blog_0`) narrow the scope to the four topics above, ask for the `tmux_ai_window`
  framing in the intro, funny devil/halo emoji bullets, TUI screenshots/demos, good citations, and a "Future Blog Posts"
  outro.
- Five polished demo GIFs already exist in `demos/out/` with a deterministic regeneration pipeline (`just demos`, VHS
  tapes in `demos/tapes/`, seeder in `demos/scripts/seed_sase_ace_demo`).

## Decisions baked into this plan (approving the plan approves these)

1. **The new post replaces [00] as the launch post.** The old draft `why-coding-agents-need-orchestration.md` gets
   `draft: true` and comes out of the nav/series (kept in the repo as salvage material). New post file:
   `docs/blog/posts/structured-agentic-software-engineering.md`, title **"SASE: Structured Agentic Software
   Engineering"** (per the review note), no "[00]" prefix anywhere.
2. **The 15-minute post moves to Getting Started and the series page is removed** (per the `sase_blog_0` note task "Move
   15-minute install post to 'Getting Started' section and remove blog series page"). The blog then contains exactly one
   published post: the new one.
3. **Emoji bullets use standard Unicode 😈/😇** as a recurring rhetorical device (status-quo pain vs. SASE fix). Custom
   emoji images are out of scope; if Bryan wants bespoke art later, that is a follow-up.
4. **Funny AI-generated diagrams ship as sidecar prompt briefs, not rendered images.** We follow the existing
   `docs/images/*.prompt.md` + `infographic-style-brief.md` pattern: the media phase authors 2–3 diagram briefs plus
   HTML-comment placeholders in the post. Actually generating the raster images is a manual/follow-up step (the image
   model isn't available to these agents). The post must read fine without them.
5. GIFs are embedded as GIFs (not `<video>` tags) from `docs/images/blog/`, since mkdocs packages only `docs/` and GIFs
   work in RSS readers and GitHub previews.

## Hard constraints for every phase

- Facts, commands, flags, and keymaps in the post MUST be verified against the current docs (`docs/*.md`) — the "Content
  spec" below cites `file:line` sources, but docs drift; re-check verbatim claims before publishing.
- **Never present "gemini" as a supported agent CLI.** The five supported CLIs are exactly `claude`, `codex`, `agy`
  (Antigravity), `qwen`, `opencode` (README.md "Works with your agents" table; INSTALL.md). `gemini-2.5-pro` may appear
  as a _model_ routed through a provider; `GEMINI.md` is a generated instruction shim. Keep the distinction crisp.
- Use `#name` (not `#!name`) in xprompt examples, except when explicitly showing standalone workflows (xprompt.md:257).
- Do NOT add/edit/remove `memory/*.md`, `AGENTS.md`, or provider instruction shims.
- After file changes: `just install` then `just check`; for docs changes also `just docs-check` (mkdocs `--strict` —
  broken links fail the build).
- Voice: match the existing drafts — first person singular (Bryan's voice), dry humor, short declarative sentences,
  concrete commands over abstractions. Good salvage sources for voice AND content:
  `docs/blog/posts/why-coding-agents-need-orchestration.md` (esp. "SASE Wraps Agents, Not Models", lines ~117–138) and
  `docs/blog/posts/hello-sase-your-first-15-minutes.md` (Steps 1–6), `docs/blog/posts/xprompts-in-depth.md`.
- Target length: **2,500–3,500 words**, at most ~9 H2 sections. The review explicitly dinged 5,400 words / 20 sections.
  When in doubt, cut and link to docs.

---

## Content spec (heavy guidance for the writing agent)

### Frontmatter

```yaml
title: "SASE: Structured Agentic Software Engineering"
date: <today>
draft: true # flipped to published in Phase 3
description: >-
  <1–2 sentences: from a tmux full of coding agents to an operating layer around them — agent CLIs, XPrompts, the ACE
  Agents tab, and a 5-minute install>
categories: [Agentic Software Engineering]
slug: structured-agentic-software-engineering
links: ACE TUI (ace.md), XPrompts (xprompt.md), Initialization (init.md), Configuration (configuration.md)
```

Include the `<!-- more -->` excerpt separator after the opening 1–2 paragraphs (mkdocs-material blog convention, see
existing posts).

### §1 Intro — "The tmux window farm" (~500–650 words)

Content flow:

1. Open with the status quo, credited by name: the **Boris Cherny method** — open several terminal/tmux tabs, run one
   coding-agent CLI in each, hop between them as they finish. The writing agent should WebSearch for a citable public
   source (Boris Cherny is the creator of Claude Code; his parallel-sessions workflow has been described in interviews
   and in Anthropic's Claude Code best-practices material). Cite whichever primary-ish source is found; if nothing
   solid, cite Anthropic's best-practices doc for parallel agent sessions and name the method without a personal link.
2. Escalate to first person: "I automated the method" — describe `tmux_ai_window` (Bryan's script,
   `~/bin/tmux_ai_window` in his public dotfiles repo, github.com/bbugyi200/dotfiles — VERIFY the public URL and script
   path with `gh`/web before linking; if not public, describe without a link). Facts about the script worth using:
   - One keybinding pops a tmux `display-menu`: **claude / codex / agy / qwen / opencode**, each with an accent color
     and a one-key shortcut; uninstalled CLIs are greyed out.
   - Selecting one opens a new tmux window named `ai`, `ai2`, `ai3`, … in the current pane's directory, running that CLI
     full-throttle (`--dangerously-skip-permissions`, `--yolo`, max reasoning effort…).
   - When the CLI exits, the window vanishes and remaining `ai*` windows get renumbered. That's the entire lifecycle
     management.
3. The 😈 list — what this workflow cannot do (each bullet one line, funny but true):
   - 😈 The scrollback buffer is the database. Close the window, lose the run.
   - 😈 No notifications — "monitoring" is cycling windows with a thumb on `n`.
   - 😈 Prompts are retyped or fished out of shell history; nothing is reusable or composable.
   - 😈 No overview: seven agents, seven windows, zero idea which ones are blocked on a question.
   - 😈 One prompt = one agent; fan-out means typing the same thing N times.
   - 😈 Plans, approvals, retries, and "what did agent 4 actually change?" all live in your head.
4. Thesis paragraph: SASE keeps the _exact same five CLIs_ — the menu doesn't change, everything around it grows up.
   State what SASE is: "SASE (Structured Agentic Software Engineering, pronounced 'sassy') is an open-source operating
   layer that orchestrates coding-agent CLIs into tracked, repeatable engineering workflows" (align with README.md
   tagline). Follow with the mirrored 😇 list (durable agent records, notifications, reusable XPrompts, one control
   surface, one-prompt fan-out, plan approval gates).
5. One-sentence roadmap of the post (four topics + install at the end), and a note that deeper dives get their own
   future posts.

Media: intro is text-only (a "window farm vs. control tower" diagram brief placeholder goes here — see media spec).

### §2 SASE wraps agent CLIs, not models (~450–550 words)

Salvage and tighten the old draft's "SASE Wraps Agents, Not Models" section. Content flow:

1. The design claim: a SASE **LLM provider plugin** constructs commands for existing agent runtimes — it launches the
   CLI as a subprocess in a managed workspace and layers durable state (prompt, transcript, status, artifacts) around it
   (architecture.md:30–51, 80–86). SASE never calls model APIs directly.
2. What the user inherits by design: each CLI's auth/subscription, sandboxing, approval model, local tool behavior, and
   provider-specific improvements. "SASE orchestrates an existing provider CLI; it does not replace that provider's
   install or authentication flow" (README.md:24). You keep using the agent CLI you already trust.
3. Providers are hot-swappable per prompt: `%model:codex/o3`, `%m("agy/Gemini 3.5 Flash (High)")`; known model names
   auto-map to their provider; auto-detect order `claude → codex → qwen → opencode → agy` (configuration.md:396,
   xprompt.md:1033–1082).
4. Uniform capabilities: skills/hooks/commit workflows work the same across all five runtimes — `sase skill init`
   renders one xprompt source into per-provider `SKILL.md` files (`~/.claude/skills/...`, `~/.codex/skills/...`,
   `~/.qwen/skills/...`, etc.) and provider instruction shims are byte-for-byte copies of one generated `AGENTS.md`
   (xprompt.md:744–797, init.md:93–94). Write once, run on any agent.
5. The honest trade-off paragraph (salvage from old draft lines ~130–138): less control over token accounting and tool
   protocols; inherits provider pricing/policy shifts; that's why the layer is provider-aware and replaceable.
6. Close with the ACE scanning detail: per-provider emoji badges on agent rows — 🎭 Claude, 🪐 Antigravity, 🤖 Codex, 🐼
   Qwen, 🐙 OpenCode (ace.md:608–615) — as the segue into the fan-out GIF.

Media: `sase_ace_multi_model_fanout.gif` — one prompt fanned out to three launch-previewed agents on different models
(claude-sonnet / gpt-5-codex / gemini-2.5-pro), stopping at the Launch Approval modal. Caption must describe models
routed through provider CLIs, not "gemini CLI".

### §3 XPrompts (~650–800 words)

The longest section. Follow the outline from Bryan's notes (Directives → Alternations → Arguments → Workflows → Special
XPrompts → Editor tooling). Content flow:

1. **The smallest XPrompt**: `#name` in any prompt expands a reusable template. A single Markdown file
   (`xprompts/til.md`) becomes `sase run "#til"` — reuse the TIL example from the 15-minutes post. Definition locations,
   simplified to the three that matter for a first read: `xprompts/` next to where you run sase,
   `~/.config/sase/xprompts/`, and the `xprompts:` block in `sase.yml`; project-local wins on collisions
   (xprompt.md:183–198 — summarize, don't reproduce all 9 tiers).
2. **Typed inputs**: show the `greet` file verbatim (frontmatter `input:` with `type: word`, Jinja2 `{{ user_name }}`,
   xprompt.md:218–229). Argument syntaxes to show inline (pick 3): `#name(args)`, `#name:arg`,
   `#review: free text to blank line`.
3. **Directives**: `%`-prefixed, stripped before the model sees the prompt. Show the verbatim block from
   xprompt.md:1177–1181 (`%model`, `%name`, `%wait`) and enumerate the rest in one sentence each: `%effort`, `%auto`
   (autonomous plan approval), `%hide`, `%repeat`, `%group`.
4. **Alternations = fan-out**: `%{#review | #test | #docs}` → three agents from one prompt; multiple alternations form a
   Cartesian product; `%{%m:opus | %m:sonnet}` is the one-line multi-model benchmark (xprompt.md:1405–1486). This is the
   direct answer to the 😈 "one prompt = one agent" bullet — say so.
5. **Multi-prompt workflows**: `---` separators split one prompt into several agents; `%wait:step1` sequences them;
   segments share frontmatter-local `_helpers`. Show a trimmed version of the two-step example (xprompt.md:1705–1718).
   One sentence on YAML workflows: `.md` = prompt parts, `.yml` = full workflows with python/ bash/approval steps — link
   to workflow_spec.md rather than explaining ("Don't reach for YAML first").
6. **Special XPrompts** (one line each): `#fork` (resume a prior agent's conversation by name), workspace refs
   (`#git:home` default sandbox, `#git:<repo>`, `#gh:owner/repo` via the GitHub plugin, `#cd:<path>` in-place), and
   project xprompts like `#gh:sase #sase/pylimit_split` (xprompt.md:276–341, 827–861).
7. **Where you type them**: the ACE prompt input widget — completion (`Ctrl+T`), fuzzy file search, snippets, vim NORMAL
   mode, prompt history (`Ctrl+K`) and stash (`Ctrl+S`) — plus the same prompt language in Neovim via `sase-nvim` and
   the `sase lsp` language server (completion/hover/diagnostics) (ace.md:1761+, xprompt.md:137–173).

Media: `sase_ace_prompt_input.gif` after point 1 or 7 (typing a prompt with xprompt + completion), and
`sase_ace_prompt_history_stash.gif` at point 7 (history recall/stash). If the section feels media-heavy, the
history/stash GIF may be dropped by the media phase — writer should place both and let Phase 2/4 judge.

### §4 The Agents tab in ACE (~550–700 words)

The user-experience answer to "seven agents, seven windows". Content flow:

1. `sase ace` opens ACE (**Agentic ChangeSpec Explorer**); Agents is the default tab of three (Agents / PRs / AXE). One
   line each on PRs (ChangeSpecs — durable PR-sized work records) and AXE (background daemon) with doc links; this post
   stays on Agents.
2. **What you see**: agents grouped in tag side panels with live metric chips (`[H1 R2 W1 F1 U1 D3]` — human-input,
   running, waiting, failed, unread, done); status glyphs per row (`▶` running, `✓` done, `✎` plan, `?` question, `⚡`
   autonomous, …); provider emoji + model suffix per row (ace.md:469–599). The point to land: _state you used to keep in
   your head is now a screen you can read_.
3. **Families and hoods** (define both, they're in the glossary and GIFs): `--` name suffixes group one unit of work
   (`nova--plan`, `nova--code`) under one root entry — plan → feedback → code chains render as parent/child rows;
   `.`-separated names form hoods (`foo.bar`, `foo.baz`) navigable with `~`. Folding: `h`/`l` collapse/reveal levels,
   `H`/`L` snap (ace.md:285–518, agent_families.md).
4. **Steering, not just watching** (this is the core differentiator — spend the words here):
   - Plan approval: agents propose plans; `a` approve (spawns the coder), `r` reject, `f` feedback round, `e` edit;
     `%auto` / `A` menu for autonomous mode (ace.md:1544–1610).
   - Launch approval: when a _running agent_ tries to spawn more agents, SASE previews and gates the launch behind a
     priority notification (agent_families.md:218–256) — the fan-out GIF from §2 already showed this modal; call back to
     it.
   - Notifications panel (`i`): priority bucket for plan approvals and agent questions; toasts consolidate.
   - Everyday verbs, one key each: `f` fork, `r` edit-prompt-and-retry, `w` make an agent wait on another, `x`
     kill/dismiss, `/` structured search (`status:running AND model:opus`).
5. Close the loop with the tmux comparison: the same information density you wanted from the window farm, but with
   records, gates, and one keyboard.

Media: `sase_ace_agents_observability.gif` after point 2, plus one still PNG (extracted frame showing families + detail
pane) if Phase 2 finds a frame that reads well at blog width. `sase_ace_prs_pipeline.gif` is OUT of scope for this post
(PRs tab) — do not embed it (it may be teased in §6/future posts if the media phase wants).

### §5 Install, configure, initialize (~450–600 words)

Practical, copy-pasteable, honest about prerequisites. Content flow:

1. Prerequisites in one paragraph: `uv`, Python 3.12+ (uv can fetch it), `git` with `user.name`/`user.email`, and at
   least one authenticated agent CLI from the five. POSIX platforms with prebuilt `sase-core-rs` wheels: Linux
   x86_64/aarch64, macOS (INSTALL.md:24–31, 121–127).
2. Install + readiness (verbatim commands, INSTALL.md:1–20):

   ```bash
   uv tool install sase
   sase version
   sase doctor        # provider/auth readiness gate
   sase core health   # Rust core extension check
   ```

   Note why `uv tool install` (not pip): `sase update`, `sase plugin install`, and the Admin Center Updates tab manage
   the install through uv receipts; pip/pipx is an escape hatch that forfeits updates (INSTALL.md:17–20). Plugins:
   `uv tool install sase --with sase-github` (mention `--with` replaces the set; add later via `sase plugin install`).

3. Configure: minimal `~/.config/sase/sase.yml` — show the small `llm_provider:` block (provider auto-detect default,
   `model_aliases.builtin.default`) from configuration.md:377–392. One sentence on layering (user file → `sase_*.yml`
   overlays → project-local `./sase.yml`).
4. Initialize: `sase init -c` (report drift), `sase init` (interactive), `sase init --yes` (unattended); what it sets up
   in registry order — memory (generated `AGENTS.md` + provider shims), SDD scaffolding, skills deployed to every
   provider's skills directory (init.md:1–50). This is where the §2 "write once, every provider" claim becomes a
   command.
5. First run (README.md:43–49):

   ```bash
   sase run "#cd:$(pwd) summarize what this repository does; do not change files"
   sase agent list
   sase ace
   ```

   End by linking the Getting Started guide (the relocated 15-minutes walkthrough) for the full guided path.

Media: none required; this section is command blocks. (Optional: small still of the Admin Center Updates tab if Phase 2
has one — do not create a new tape for it.)

### §6 Outro — what's next (~150–250 words)

- One short paragraph: this post covered the operating layer's front door; the parts that make it an _engineering_
  system get their own posts. Tease (from Bryan's notes): Beads & Spec-Driven Development, ChangeSpecs (hooks, mentors,
  review comments), memory, Telegram/mobile control, and SASE's pluggable architecture.
- Call to action: `uv tool install sase`, docs at sase.sh, source at github.com/sase-org/sase, issues welcome.
- No "Series Navigation" footer (the series page is being removed).

---

## Media spec (guidance for the media phase)

GIF inventory (all in `demos/out/`, regenerable via `just demos`; tapes in `demos/tapes/`):

| GIF                                 | Duration | Size | Post placement                  |
| ----------------------------------- | -------- | ---- | ------------------------------- |
| `sase_ace_multi_model_fanout.gif`   | ~32s     | 3.8M | §2 (wraps CLIs)                 |
| `sase_ace_prompt_input.gif`         | ~29s     | 1.4M | §3 (xprompts)                   |
| `sase_ace_prompt_history_stash.gif` | ~23s     | 1.7M | §3 (optional)                   |
| `sase_ace_agents_observability.gif` | ~20s     | 774K | §4 (agents tab)                 |
| `sase_ace_prs_pipeline.gif`         | ~26s     | 1.1M | NOT used (PRs tab out of scope) |

Tasks:

1. Review every used GIF frame-by-frame (extract frames with ffmpeg) for: typos in seeded data, pacing (nothing
   important on screen <1.5s), legibility at ~800px blog width, stray real paths/names (should be hermetic
   `/tmp/sase-ace-demo...` data), and whether the clip actually demonstrates the claim its section makes. Fix by editing
   the tape and re-rendering via `just demos` (needs `vhs`, `ttyd`, `ffmpeg` — already used on this machine).
2. Optimize weight: the 3.8M fan-out GIF should get palette/lossy compression (`gifsicle -O3 --lossy` or ffmpeg
   palettegen) targeting ≤2M without visible banding; keep `demos/out/` originals untouched — optimized copies go to
   `docs/images/blog/`.
3. Copy final media to `docs/images/blog/` and replace the writer's placeholders with
   `![specific alt text](../../images/blog/<name>.gif)` embeds plus one-line italic captions.
4. Extract 1–2 still PNGs (e.g., agents observability frame with families + detail pane) for spots where a static
   screenshot reads better than a loop; same directory.
5. Author 2–3 funny diagram briefs as sidecar files `docs/images/blog/<name>.prompt.md` following
   `docs/images/infographic-style-brief.md` (16:9, light background, limited labels) + HTML-comment placeholders in the
   post. Suggested subjects: (a) "The window farm vs. the control tower" for §1; (b) "One prompt, five CLIs, one
   operating layer" for §2; (c) salvage the old draft's "prompt burrito" brief for §3. Image generation itself is a
   follow-up for Bryan.

---

## Phases

Each phase is completed by a distinct agent instance, in order. Every phase that changes repo files ends with
`just install`, `just check`, and (for docs/mkdocs changes) `just docs-check`, all passing.

### Phase 1 — Write the post

- Create `docs/blog/posts/structured-agentic-software-engineering.md` with `draft: true`, full frontmatter, and complete
  prose per the Content spec above (all six sections, 😈/😇 device, `<!-- more -->` separator).
- Insert explicit HTML-comment media placeholders where the Media spec places each GIF/still/diagram
  (`<!-- MEDIA: sase_ace_multi_model_fanout.gif — caption: ... -->`) instead of embedding files.
- Research and add citations: Boris Cherny / parallel-CLI-sessions source (WebSearch), the public dotfiles link for
  `tmux_ai_window` (verify it exists publicly first), plus internal doc links per section.
- Re-verify every command/flag/keymap quoted from the Content spec against the current docs before writing it.
- Do NOT touch nav, the old posts, or the series page in this phase (post is `draft: true`, so `--strict` stays green).

### Phase 2 — Demo media: review, improve, integrate

- Execute the Media spec: frame-by-frame GIF review, tape fixes + `just demos` re-render if needed, optimized copies
  into `docs/images/blog/`, still extraction, replace all placeholders with real embeds + alt text + captions, author
  the diagram briefs.
- If a tape re-render changes `demos/out/`, keep those artifact updates in this phase's commit scope.
- Acceptance: post renders with all media in `mkdocs serve`/`build`, no placeholder comments left except the 2–3 diagram
  placeholders, `just docs-check` passes.

### Phase 3 — Site integration: make it the launch post

- Flip the new post to published (remove `draft: true`).
- Demote `why-coding-agents-need-orchestration.md` to `draft: true`; remove "[00]"/"[01]" entries from `mkdocs.yml` nav.
- Move the 15-minutes content to Getting Started: create `docs/getting_started.md` from
  `hello-sase-your-first-15-minutes.md` (drop series framing/navigation, retitle "Getting Started: Your First 15
  Minutes"), add it to the existing `Getting Started:` nav section above Initialization, and mark the blog original
  `draft: true`.
- Remove `docs/series/agentic-software-engineering.md` and all inbound references (`docs/blog/index.md`, post `links:`
  frontmatter, other posts' "Series Navigation" sections that `--strict` will flag); add `_redirects` entries for any
  URL that was previously publicly linked (check git history / `_redirects` conventions; the site may not have been live
  yet — if so, skip redirects).
- Rewrite `docs/blog/index.md` "Start Here" to feature the new post + Getting Started guide.
- Add Open Graph/Twitter-card metadata (the review flagged its absence): prefer the mkdocs-material `social` cards
  plugin if its imaging deps are acceptable in CI (`just docs-check` + `docs-pdf-check` must stay green); otherwise a
  minimal `main.html` template override emitting `og:title/og:description/og:image` from page meta. Verify tags appear
  in the built HTML for the new post.
- Update the RSS plugin expectations if needed (post `date`, `image`).

### Phase 4 — Fact-check, polish, and final report

- Adversarial fact-check pass: run every command in the post against the installed `sase` CLI (`sase --help`,
  `sase xprompt list`, `sase init -c`, etc. — read-only invocations only) and diff every keymap/syntax claim against
  `docs/ace.md` / `docs/xprompt.md` / `docs/init.md` / `INSTALL.md` / `docs/configuration.md`. Fix discrepancies in the
  post (never by editing docs to match the post).
- Verify all links resolve (internal via `just docs-check --strict`; external via curl/WebFetch), and that the built
  blog page renders media correctly.
- Editorial pass against the launch-review criteria: ≤3,500 words, ≤9 H2 sections, images render, description/OG
  present, title free of numbering, intro reaches the thesis within the first screen. Tighten prose; kill redundant
  bullets; ensure 😈/😇 device appears in intro and is called back at least once later.
- Final gates: `just install`, `just check`, `just docs-check`.
- Produce a completion report listing: word count, media inventory, remaining manual steps for Bryan (generate the 2–3
  diagrams from briefs, review draft demotions, publish/deploy the site, check off the Obsidian `sase_blog_0` task).

## Out of scope

- AXE/Telegram section (bob outline mentions it; Bryan's narrowed scope excludes it — the outro teaser covers it).
- Actually generating AI diagram images; publishing/deploying the live site; posting announcements.
- Any change to `demos/tapes/` philosophy (hermetic seeded data, fixed geometry) — only tweaks within that contract.
