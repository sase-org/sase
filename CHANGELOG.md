# Changelog

## [0.4.0](https://github.com/sase-org/sase/compare/v0.3.0...v0.4.0) (2026-06-18)


### ⚠ BREAKING CHANGES

* **tui:** Prompt Ctrl+G now starts the prompt-local INSERT-mode prefix instead of opening the editor directly. Use Ctrl+G g or Ctrl+G Ctrl+G to open the current prompt or prompt stack in the editor.

### Features

* **agents:** auto-add derived agent names to groups ([7862d83](https://github.com/sase-org/sase/commit/7862d83745e5c213b4b8831e98f3c414481a46a9))
* **bead:** add Python search command (sase-4w.3) ([90d2d6e](https://github.com/sase-org/sase/commit/90d2d6ebec45b03e1214efe58018159d69331a40))
* **tui:** add prompt Ctrl+G insert prefix ([d4dd47d](https://github.com/sase-org/sase/commit/d4dd47dd5272dc047f2adb3e64dca5030f90b38a))
* **tui:** bundle multi-pane prompt stash rows ([599d71c](https://github.com/sase-org/sase/commit/599d71caac4cd02e845cccbd5c29b0c848229aff))
* **tui:** improve frontmatter add-property picker ([6fbc748](https://github.com/sase-org/sase/commit/6fbc748f52453eed1a31ba253ca904ef2a93bd41))
* **tui:** split frontmatter add keymaps ([36eb840](https://github.com/sase-org/sase/commit/36eb8403b5bbb6af0fe2bfb24c7b559f966eae48))


### Bug Fixes

* stop orphaned axe lifecycle processes ([1ba8c98](https://github.com/sase-org/sase/commit/1ba8c988e279bba47b23a47547487285e3db4d2b))
* **tui:** acknowledge unread on mark auto-advance ([a011b42](https://github.com/sase-org/sase/commit/a011b4247f2d41f745cf10b236cef6d174dddc53))
* **tui:** clear prompt search highlights on escape ([b2c9905](https://github.com/sase-org/sase/commit/b2c9905c369873cd7115540d8b95c06a9bd64bec))
* **tui:** restore stashed prompt properties ([e7aaede](https://github.com/sase-org/sase/commit/e7aaedeee249de5db54e3d5a0bf1a5eab93b24be))
* **tui:** scope bead display cache by project ([#179](https://github.com/sase-org/sase/issues/179)) ([821ae68](https://github.com/sase-org/sase/commit/821ae68a97195e2ade16a530c0dc77587fe9062f))


### Documentation

* **beads:** document search command (sase-4w.4) ([0a299d7](https://github.com/sase-org/sase/commit/0a299d7af0283f2d4095df4370c25159a769c8e5))

## [0.3.0](https://github.com/sase-org/sase/compare/v0.2.0...v0.3.0) (2026-06-18)


### ⚠ BREAKING CHANGES

* **memory:** Memory notes must now live directly under `memory/*.md`. The legacy `memory/short`, `memory/long`, and `long/foo.md` read aliases are no longer accepted.
* **ace:** Prompt stack selected-pane submit no longer uses Ctrl+Shift+S. Use g<enter> in NORMAL mode, or Esc g<enter> from INSERT mode.
* **tui:** Prompt-stack pane focus is now K/J (was Ctrl+H/Ctrl+L), pane reorder is now Up/Down (was Ctrl+Shift+H/Ctrl+Shift+L), the properties panel toggle is now Ctrl+Shift+= (was Ctrl+Shift+-), and the Vim normal-mode J line join is removed.
* **tui:** Typing `---` in the prompt input no longer opens the frontmatter panel or splits the prompt into a new pane. Use `Ctrl+Shift+-` / `,f` for the properties panel and `Ctrl+-` to add a pane.
* **tui:** The prompt stack add-pane shortcut is now Ctrl+- and the normal-mode `-` keymap no longer adds a pane.
* **cli:** the `sase agents` command group is renamed to `sase agent`; scripts invoking `sase agents ...` must use `sase agent ...`.
* **cli:** `sase agents status` is removed; use `sase agents list` (or bare `sase agents`) instead.
* **ace:** `Shift+Enter` no longer submits a prompt stack; use `Ctrl+S` instead.
* **tui:** the `kill_marked_and_edit` leader keymap is removed. Custom configs that bind `leader.kill_marked_and_edit` no longer take effect; the marked kill-and-edit behavior is now reached via `,x` when agents are marked.
* **cli:** the `sase chats` command has been renamed to `sase chat` with no backwards-compatible alias; scripts and references must use `sase chat`.
* **memory:** the `sase memory episodes` command family, the ACE Episode Explorer, and the `sase_chop_memory_episodes` script are removed. Persisted episode records under `~/.sase/projects/<project>/episodes/` remain inert.
* **cli:** the top-level `sase skills` command is removed; use `sase skill` instead. The `sase init skills` alias is unaffected.
* **skills:** `sase skills log` has been renamed to `sase skills use`. Use `sase skills use <name> --reason <reason>` to record skill use.
* The `%plan` xprompt directive and its `%p` alias are no longer recognized. Use the `/sase_plan` skill or `%epic` for planning flows.

### Features

* **ace:** add Agents-tab leader `,r` revert for done agents ([bf81671](https://github.com/sase-org/sase/commit/bf816714784875ee326cfdc4f6adc3219edd95af))
* **ace:** add prompt stack data model and canonical split/join (sase-4p.1) ([5aef3e0](https://github.com/sase-org/sase/commit/5aef3e0914fd91429450942dcd41b1a7902e5da0))
* **ace:** add prompt stack submit chooser ([a2f8e1a](https://github.com/sase-org/sase/commit/a2f8e1ae0b21932b31fc8bde95cda4c950f04cc7))
* **ace:** add stack keymaps and live splitting (sase-4p.3) ([85b85bd](https://github.com/sase-org/sase/commit/85b85bd31afa13211db4f24130d4a144402f80b5))
* **ace:** add transient ANSWERED agent status ([823c4e5](https://github.com/sase-org/sase/commit/823c4e50dafca88c3cf881b34ffda05587731ac8))
* **ace:** attribute agent-family context in metadata panel ([64bd2fb](https://github.com/sase-org/sase/commit/64bd2fbd66cc46b96a769af0e5a25fd319b7d724))
* **ace:** bulk-revert all marked agents with leader `,r` ([7babf67](https://github.com/sase-org/sase/commit/7babf670a8caab72e9d4ae928f20c8084fbc3c71))
* **ace:** display repeat STOP slots as STOPPED ([d95bcf7](https://github.com/sase-org/sase/commit/d95bcf78c0192e80af7e02fc540bf6d8e41cb3b5))
* **ace:** hide empty MEMORY lane in agent context section ([7189b64](https://github.com/sase-org/sase/commit/7189b64407571282bc0552a8d41cd9c7cbd43c90))
* **ace:** hide empty SKILLS lane in AGENT CONTEXT ([e6ede85](https://github.com/sase-org/sase/commit/e6ede8522932abd468e07789ec7a0888b3347303))
* **ace:** highlight stopped agent status ([4aa31d8](https://github.com/sase-org/sase/commit/4aa31d8959a3afb6a07b619612bec96ec7a7f885))
* **ace:** launch integration and edge cases for prompt stack (sase-4p.5) ([f1c7112](https://github.com/sase-org/sase/commit/f1c7112b9ddae4f16853e9219927c59acc165b08))
* **ace:** move current-pane submit to g-enter ([a505b16](https://github.com/sase-org/sase/commit/a505b16a9988dd50c2124a29e26f752377821413))
* **ace:** move runners panel to leader `,R` ([1c4e039](https://github.com/sase-org/sase/commit/1c4e0394fdaf8811887ae330e5d7f1111563b3ac))
* **ace:** polish log panel display (sase-4t.4) ([da3557e](https://github.com/sase-org/sase/commit/da3557e1691b37b88be5fa709ca9430fb26421fa))
* **ace:** push Agents-tab revert commits to GitHub ([904e612](https://github.com/sase-org/sase/commit/904e6123a338a30b84f7cb4f9141eb639189cb57))
* **ace:** remove Shift+Enter prompt-stack submit alias ([b017a62](https://github.com/sase-org/sase/commit/b017a6207188cd84cbc44cfb350e0ca8055095dc))
* **ace:** render prompt stack of panes in PromptInputBar (sase-4p.2) ([24ecfc4](https://github.com/sase-org/sase/commit/24ecfc43d69ad93b98d3567289ee8540617d880f))
* **ace:** render v-selected images via artifact viewer ([d2e91c1](https://github.com/sase-org/sase/commit/d2e91c11caf4b74a8543e8922217cc29ce07ad7a))
* **ace:** show pencil badge for live agent workspace edits ([9148408](https://github.com/sase-org/sase/commit/91484084ba7d66c81b28b3e347610fcf236a0a85))
* **ace:** submit and cancel semantics for prompt stack (sase-4p.4) ([2e3e85c](https://github.com/sase-org/sase/commit/2e3e85cfe58175a1219f66cd94d20aaa242d092a))
* **ace:** support Jinja prompt input ([540bbe3](https://github.com/sase-org/sase/commit/540bbe3fd02bcb300d8f15e0234eb31b082c5ac9))
* **ace:** visual polish and stack-aware help for prompt stack (sase-4p.6) ([3813516](https://github.com/sase-org/sase/commit/381351639e12dbb75f26662213e0720c9ecd6b83))
* add memory note foundation (sase-4u.1) ([d844d5c](https://github.com/sase-org/sase/commit/d844d5c366ad9a068c045f1bfb22f9aca23b1a9b))
* add skills log command ([32617fc](https://github.com/sase-org/sase/commit/32617fc101cf575168d3810b0559c320e2246020))
* audit generated skill usage ([9f6e739](https://github.com/sase-org/sase/commit/9f6e739789a55c3b00e85f6bb07b270cbd11bf62))
* capture xprompt usage metadata ([0374375](https://github.com/sase-org/sase/commit/03743757ac53eb5bb4eecdcce271724061a754f9))
* **cli:** rename `agents status` to `agents list` ([00dc569](https://github.com/sase-org/sase/commit/00dc569bba2ce6e1850ebab0bd7de17cda0d664e))
* **cli:** rename `sase agents` to `sase agent` ([d25be1f](https://github.com/sase-org/sase/commit/d25be1fa2186a486bd21e9da584981a6adb14c00))
* **cli:** rename `sase skills` command to `sase skill` ([66d6c68](https://github.com/sase-org/sase/commit/66d6c688c555319377ecd407ceecdadc2a135fbc))
* include planner runtime in plan approval notifications ([46e694a](https://github.com/sase-org/sase/commit/46e694a49ab9cedaae7fc38a90b7fb6b980885f2))
* **memory:** generate flat project memory notes (sase-4u.3) ([b78261a](https://github.com/sase-org/sase/commit/b78261a5870221801e127ea2075c633e09e0937b))
* **memory:** remove legacy memory layout support (sase-4u.5) ([257d9e6](https://github.com/sase-org/sase/commit/257d9e6545a88ff8e495bbc420b27a435374713c))
* **memory:** remove the memory episodes feature ([37973b8](https://github.com/sase-org/sase/commit/37973b8b3faa00322d218bd819e8b3e4e9d2bce5))
* **memory:** support flat memory read paths (sase-4u.2) ([45b3b0f](https://github.com/sase-org/sase/commit/45b3b0f0ef6da127dbd23034fa7ecc76519bd51d))
* **prompt-stash:** add Python prompt-stash facade and wire types (sase-4q.1) ([7575927](https://github.com/sase-org/sase/commit/7575927a974063ab4f4ef21486c745b2a5717b3f))
* **prompt-stash:** capture keymaps, top-bar indicator, and toasts (sase-4q.2) ([fec3f86](https://github.com/sase-org/sase/commit/fec3f86830367ecd7914f1e3087ea5909dc9f451))
* **prompt-stash:** polish — concurrent refresh, preview fit, snapshots (sase-4q.4) ([9f1f088](https://github.com/sase-org/sase/commit/9f1f088bfc68816c29fdbd9880cb694b41031e87))
* **prompt-stash:** restore picker modal, pop semantics, load into bar (sase-4q.3) ([9729e80](https://github.com/sase-org/sase/commit/9729e80474da713554095df0d545b84ab8f25362))
* remove legacy %plan/%p xprompt directive ([58b44e2](https://github.com/sase-org/sase/commit/58b44e2d84882dae5729707e6c8b11076b08b581))
* **skills:** rename `sase skills log` to `sase skills use` ([76a7f0c](https://github.com/sase-org/sase/commit/76a7f0c0175d8182e360397a87b504718d8cc741))
* **tui:** add `,L` Log panel modal for launch failures (sase-4t.2) ([6532710](https://github.com/sase-org/sase/commit/65327103d203a534bfbe2c95139fbbf051ed2ba3))
* **tui:** add Agents-tab bulk kill-and-edit (sase-4r) ([b129002](https://github.com/sase-org/sase/commit/b129002382fdc67a08a6e653a73ca14d3bb13383))
* **tui:** add Ctrl+Shift+- toggle for xprompt properties panel ([f07fe19](https://github.com/sase-org/sase/commit/f07fe193af72427424f312e8acf43214fa25abae))
* **tui:** add Frontmatter Panel widget to prompt input bar (sase-4r.3) ([5f1cbf1](https://github.com/sase-org/sase/commit/5f1cbf1ce97e175c4a986d41ff7741c88392627f))
* **tui:** add interactive prompt input search (sase-4v.2) ([97fc3cb](https://github.com/sase-org/sase/commit/97fc3cb2894081abfd22dc19b57ba2b4d5da55cc))
* **tui:** add non-destructive `gp` stash load and retire leader `,P` (sase-4s.4) ([6c2f547](https://github.com/sase-org/sase/commit/6c2f54777c948d3a84e7e4893737030adb44e11e))
* **tui:** add prompt change surround keymap ([6a1de15](https://github.com/sase-org/sase/commit/6a1de15fcbc02458a79c881abb0bd44af52e02bc))
* **tui:** add prompt delete surround keymap ([8a2aa5e](https://github.com/sase-org/sase/commit/8a2aa5e3d36d400123ebb91978b1266a97af5dbb))
* **tui:** add prompt search highlight foundation (sase-4v.1) ([5e1a766](https://github.com/sase-org/sase/commit/5e1a7667962fdd2554a329883c5d1fe439d3e83d))
* **tui:** add prompt surround operator ([e2f93a7](https://github.com/sase-org/sase/commit/e2f93a7f19a5f4384465ddd41d66b3aae2d1ca0e))
* **tui:** add prompt-input all-panes editor keymap ([0b874c9](https://github.com/sase-org/sase/commit/0b874c93c32eda2182f7d6901ee268b7069a35df))
* **tui:** add repeat prompt search (sase-4v.3) ([f8d2ca3](https://github.com/sase-org/sase/commit/f8d2ca347e22f6f2571f447ba29105ab39e0abad))
* **tui:** add spaced editor markdown for prompt stack &lt;ctrl+g&gt; ([831e358](https://github.com/sase-org/sase/commit/831e358c3e69ae552aa3bcb9cd08c07819421c38))
* **tui:** add structured input/xprompts editors + local-xprompt completion parity (sase-4r.4) ([b3d8240](https://github.com/sase-org/sase/commit/b3d8240bd9624433c97b3d98c39bec5394818e71))
* **tui:** build prompt `g` prefix foundation and remove comma leader (sase-4s.1) ([94ac293](https://github.com/sase-org/sase/commit/94ac2932744b98be65555ff9e6aa0db93316f1b5))
* **tui:** collect frontmatter inputs at launch (sase-4r.5) ([f4f4969](https://github.com/sase-org/sase/commit/f4f496984239fa764fcdc68d3aeec5eb9ca457a5))
* **tui:** cycle prompt-stack pane focus and reorder at edges ([f3448bc](https://github.com/sase-org/sase/commit/f3448bcc53eddbc54c5ccb8f0597e69f5813e552))
* **tui:** durable launch-failure logging foundation (sase-4t.1) ([1feff11](https://github.com/sase-org/sase/commit/1feff110934ab6fa299d2ad87d2b2658e99ee5bc))
* **tui:** fold marked kill-and-edit into contextual leader `,x` ([fae3c9e](https://github.com/sase-org/sase/commit/fae3c9e11a8bbedd1833980b7aef048403fef388))
* **tui:** make Ctrl+G the single stack-aware prompt editor key ([e6d547f](https://github.com/sase-org/sase/commit/e6d547f542bff0063b38f8665933056240d62a9d))
* **tui:** migrate add-pane and xprompt properties panel to `g-` / `g=` (sase-4s.3) ([e29bd38](https://github.com/sase-org/sase/commit/e29bd388f10b153b79fef1130f3a7b19aa85664e))
* **tui:** migrate prompt pane nav/reorder to `g` prefix and restore Vim `J` (sase-4s.2) ([e2369f0](https://github.com/sase-org/sase/commit/e2369f0efb525610005285018baacfed6362e933))
* **tui:** migrate prompt stack add-pane to Ctrl+- ([cdc5027](https://github.com/sase-org/sase/commit/cdc5027b285899d782ae6c09c5385cd56394fc3a))
* **tui:** migrate prompt stack pane navigation to Ctrl+Shift+J/K ([770f4e9](https://github.com/sase-org/sase/commit/770f4e9e08ed722a09b4f742ea2abda833f1925b))
* **tui:** migrate prompt stack reorder to Ctrl+Shift+H/L ([21fee88](https://github.com/sase-org/sase/commit/21fee88e05cc501a7d64c0cad410f75f76f67d55))
* **tui:** move prompt-stack pane focus to Ctrl+H/L ([ed4f9c7](https://github.com/sase-org/sase/commit/ed4f9c716a6b53d91b6163beee0c329993ca8a69))
* **tui:** polish prompt stack presentation ([bf87804](https://github.com/sase-org/sase/commit/bf878045b9701e5fc53ee16faa46854abb0cc96b))
* **tui:** rebind prompt-stack controls to terminal-safe keys ([36de758](https://github.com/sase-org/sase/commit/36de7588f321a5a3a8b2fc04e925e6c49064014d))
* **tui:** redesign agent context lanes ([ac4d3f3](https://github.com/sase-org/sase/commit/ac4d3f32324d8304b60ae991f0d74a42de0c1d8a))
* **tui:** remove implicit `---` live prompt shortcuts ([95e3d36](https://github.com/sase-org/sase/commit/95e3d366555658789f72d9eb3e63424e04a1c68c))
* **tui:** render agent names with brackets in Agents tab ([fde6594](https://github.com/sase-org/sase/commit/fde659437dcdc9aac154ee0572f8816ac9320bf5))
* **tui:** render agent names without brackets in Agents list ([70d906f](https://github.com/sase-org/sase/commit/70d906f61376f3f7bde6f497473976260fe9e54e))
* **tui:** route `%edit` returns through xprompt markdown semantics ([203cbec](https://github.com/sase-org/sase/commit/203cbec04dafa34c95279579243ca457d95f0bd2))
* **tui:** show prompt comma-leader hints ([1eef9c3](https://github.com/sase-org/sase/commit/1eef9c39cc957c31c7742e66ca0d10473ae54a74))
* **tui:** use distinct color for xprompt part values ([7531efc](https://github.com/sase-org/sase/commit/7531efcc4df00dcfc1c5e25f09634afbdbf46fdb))
* use role-aware agent family child names ([085d336](https://github.com/sase-org/sase/commit/085d336667325b5996b72eecc0e002882145b54d))
* **xprompt:** add frontmatter schema adapter over sase_core (sase-4r.1) ([20a9589](https://github.com/sase-org/sase/commit/20a95891d2fcdc1a90f9c8b7d1aa14d461c80d9a))
* **xprompt:** add log_skill_use to control audit directive injection ([a4bcf9f](https://github.com/sase-org/sase/commit/a4bcf9fc0a7ebefdaa345759853e964ed4ca4299))
* **xprompt:** add structured PromptFrontmatter model + stack round-trip (sase-4r.2) ([b8ad5db](https://github.com/sase-org/sase/commit/b8ad5db760b41da505f20a08a4205ac131bee3b4))
* **xprompt:** update multi-agent prompt references ([a2771d3](https://github.com/sase-org/sase/commit/a2771d3bc8b0bfbae462587290d3eb23f9999c1a))


### Bug Fixes

* **ace:** cancel loader executor on quit ([2805071](https://github.com/sase-org/sase/commit/2805071a9e1fa90cd3ef0205ae9053fa21b26e1c))
* **bead:** force-reuse deterministic owners on bead work relaunch ([be748b6](https://github.com/sase-org/sase/commit/be748b627aa1824edfffab70e7ab6b0ed5753323))
* guard prompt pruning and sharded plan lookup ([#176](https://github.com/sase-org/sase/issues/176)) ([115cb41](https://github.com/sase-org/sase/commit/115cb41d432c36bc13ef06878264a89bd5a41aec))
* harden runner args and terminal live hints ([#177](https://github.com/sase-org/sase/issues/177)) ([8c0d967](https://github.com/sase-org/sase/commit/8c0d967102909627e6551d4c78b0a9e9a626b5d7))
* **history:** keep alternate project MRU refs ([af35df7](https://github.com/sase-org/sase/commit/af35df7e29c2041ff7fe45434e194bd079c7e18e))
* mark root and child rows ANSWERED when a question is answered ([c4c8622](https://github.com/sase-org/sase/commit/c4c8622c0105559ed556c456b8166bbfc53651d7))
* **memory:** follow parented long notes during init checks (sase-4u) ([6d1a4b5](https://github.com/sase-org/sase/commit/6d1a4b541990f39f903fdd6bf0eeb55621ed2bfe))
* **plan:** discover day-sharded artifacts in plan list approvals ([0aef321](https://github.com/sase-org/sase/commit/0aef32173cdae6e9244c4e0a2d1255d7f3d360b9))
* point launch failures at log panel (sase-4t.3) ([d11e66f](https://github.com/sase-org/sase/commit/d11e66f05e324c4bc7447b93667d41375999238f))
* rebuild question continuations from the interrupted phase prompt ([14de3b4](https://github.com/sase-org/sase/commit/14de3b4e91030f45a36f64164a826aecb8af0cb2))
* refresh docs PDF blog sentinels ([928b7f6](https://github.com/sase-org/sase/commit/928b7f63a134540fb7772d7344465ef8c78e552f))
* **run:** stop creating CWD project on bare `sase run` ([5bc999d](https://github.com/sase-org/sase/commit/5bc999d04f189e678ae611ff6e813bb88b8baf66))
* **tui:** clear stale QUESTION status on answered question rows ([eca16bf](https://github.com/sase-org/sase/commit/eca16bf4782940b4a611326209940e0131f2cba8))
* **tui:** expand launch-shaping xprompts before planning fan-out ([fb921a3](https://github.com/sase-org/sase/commit/fb921a31125f83b0aee8654f093028eb79c002bc))
* **tui:** label plan-feedback context members by suffix ([29ab809](https://github.com/sase-org/sase/commit/29ab80962476bc2321220199d990656d77a2e619))
* **tui:** preserve launch failure log hints (sase-4t) ([98b2dc1](https://github.com/sase-org/sase/commit/98b2dc1640d41f7b806c828af07b276bd2f45cb2))
* **tui:** preserve prompt body with frontmatter panel ([a14450e](https://github.com/sase-org/sase/commit/a14450ed3ee898a512203de6fed39198559a7959))
* **tui:** stop treating path-typed workflow outputs as diffs ([d4f25bc](https://github.com/sase-org/sase/commit/d4f25bcc1bd340ba8c24f05dfdd1f8ab92c9c043))
* **tui:** support tmux Ctrl-minus add pane ([d1fb91a](https://github.com/sase-org/sase/commit/d1fb91a4156a62cdc5bf3294b915cf548096ede5))
* **xprompt:** capture launch-boundary xprompt metadata for daemon agents ([ecd13bf](https://github.com/sase-org/sase/commit/ecd13bf83276677daa5d6bf4ad18dcb615a70810))


### Performance Improvements

* **ace:** defer live diff hints out of the agents startup loader ([94af722](https://github.com/sase-org/sase/commit/94af72277d063c971a71ea0a32530fb57a19d094))
* **bead:** speed up `sase bead work` launch path ([4be6f73](https://github.com/sase-org/sase/commit/4be6f73525d9c923d5f215a1fac40af4f6efc4d8))
* reduce ACE startup active index work ([c029ba2](https://github.com/sase-org/sase/commit/c029ba2da5f7388dc7c750c58bc4cda331272249))
* **tui:** resolve agent bead details asynchronously ([d01a652](https://github.com/sase-org/sase/commit/d01a6522d861f835800a0ad946e17fc0e6117b55))


### Documentation

* add agent revert research infographic ([513b3ae](https://github.com/sase-org/sase/commit/513b3ae0150f336651e5918e8bd423c5eda384d6))
* add alternate research take on dynamic agent family workflows ([127ca32](https://github.com/sase-org/sase/commit/127ca32f3b461a84a7cb85b641ec5cb292339057))
* add audio generation infographic ([fc35b8a](https://github.com/sase-org/sase/commit/fc35b8a6a5b0c1661cac3c23a525c6351899bc41))
* add blog launch research infographic ([0fbdbfd](https://github.com/sase-org/sase/commit/0fbdbfdd916486c38636aa216707fe670603600e))
* add dynamic agent families infographic ([2b44df7](https://github.com/sase-org/sase/commit/2b44df75a1ac9fa3ca5b6a48a9897b39fc3b5246))
* add first blog post review research ([5fe2a73](https://github.com/sase-org/sase/commit/5fe2a7376cf007f7f54469f4dac7d24a3c10f10f))
* add model purpose config infographic ([440b907](https://github.com/sase-org/sase/commit/440b9075684f9fc49fa45299084b5315f08a930d))
* add review research for blog00 launch post ([d295d35](https://github.com/sase-org/sase/commit/d295d35a1da27d325e85a77851e4a12850488782))
* add TUI performance infographic ([130c0ca](https://github.com/sase-org/sase/commit/130c0ca7e26e303f33b02c5826403fe3b301f633))
* add TUI tmux performance research ([79cbd23](https://github.com/sase-org/sase/commit/79cbd234d2a44546b348badf6d837b0be5060747))
* clarify ACE prompt stack behavior ([f3d4ede](https://github.com/sase-org/sase/commit/f3d4ede18695ac3ae82457ae919a40de1a6fadb6))
* clarify prompt stack documentation ([fe552dd](https://github.com/sase-org/sase/commit/fe552dd5574694102729216447d1d024207d0d7a))
* consolidate agent revert research ([2e11fea](https://github.com/sase-org/sase/commit/2e11fea04fe4c4631824571670135925c2a639e0))
* consolidate audio generation research ([5cabccc](https://github.com/sase-org/sase/commit/5cabcccfb8939a7f267953b0ccad37df03f928ef))
* consolidate blog launch post research ([d31cd89](https://github.com/sase-org/sase/commit/d31cd89f2a9e270acea8b9a3b875ab804211de7b))
* consolidate dynamic agent family research ([e2e277b](https://github.com/sase-org/sase/commit/e2e277bd359c1d4e6f3a52f488b858d7011d8fc4))
* consolidate model purpose config research ([15557e8](https://github.com/sase-org/sase/commit/15557e87cdd5ce4f882cca835a01cd8a8f844577))
* consolidate TUI performance research ([89db64b](https://github.com/sase-org/sase/commit/89db64bb56349f29e894478669b10b5dc54877a2))
* credit SASE paper in orchestration post ([ea8815d](https://github.com/sase-org/sase/commit/ea8815dced545ecee0ab56d3b757990afe51cdc6))
* research agents tab revert workflow ([34ec561](https://github.com/sase-org/sase/commit/34ec5610dcc8dd12fe07183c831566ce6ef25a09))
* research dynamic agent family workflows ([a20841f](https://github.com/sase-org/sase/commit/a20841fb4ae44baf476434d8c068a31ffc95e74b))
* research SASE audio generation ([7cab247](https://github.com/sase-org/sase/commit/7cab247bd66a8a77154079f2600b312223317b59))
* research unified model purpose config ([928449e](https://github.com/sase-org/sase/commit/928449e550eb083214c4abb7c9e0ac571e85fdfd))
* **research:** add audio podcast generation feasibility study ([67dd47a](https://github.com/sase-org/sase/commit/67dd47acc170601fe0c987e4f26c6df397ab360b))
* **research:** add temporary revert-agent keymap fixture marker ([806f487](https://github.com/sase-org/sase/commit/806f487e2498d8b562ac8aadd87097cddc5c80e5))
* **research:** add TUI performance profiling findings ([e15a9aa](https://github.com/sase-org/sase/commit/e15a9aabdb800b758575f8e1fa653079bcbb03ae))
* **research:** analyze ,r keymap to revert a done agent's commits ([0dce323](https://github.com/sase-org/sase/commit/0dce323c9aef7fba3039e84a88feef1424bc176d))
* **research:** analyze model role config unification ([111616f](https://github.com/sase-org/sase/commit/111616f747e166f2b09b0a89242b7400329587e3))
* rewrite SASE launch essay ([e965101](https://github.com/sase-org/sase/commit/e96510106d45be3afae9216a3cc5589c7857918e))
* standardize "Gas Town" spelling in orchestration post ([f08f1ff](https://github.com/sase-org/sase/commit/f08f1ff6e8ecd7ac679537eaa33189ae0352a51e))
* update ACE prompt stack documentation ([c2a7379](https://github.com/sase-org/sase/commit/c2a7379250a109321f02d3be9fe7b2e4c9dce41e))
* update flat memory guidance (sase-4u.4) ([41bed16](https://github.com/sase-org/sase/commit/41bed160a1fd26512650df835fd4f4f4d7db0165))
* update prompt g-prefix help references (sase-4s.5) ([a6bb438](https://github.com/sase-org/sase/commit/a6bb43850d7f8b1fb755310d6449099a9adcbd42))
* update prompt stack documentation ([58556f6](https://github.com/sase-org/sase/commit/58556f6c3f89978a5a3b68ccdd9d1be473b67b86))


### Code Refactoring

* **cli:** rename `sase chats` command to `sase chat` ([86849c6](https://github.com/sase-org/sase/commit/86849c6df9363015e869f75be85ca3a60aeb3961))

## [0.2.0](https://github.com/sase-org/sase/compare/v0.1.7...v0.2.0) (2026-06-13)


### ⚠ BREAKING CHANGES

* llm_provider.worker_model is no longer accepted. Configure llm_provider.worker_models entries keyed by provider/model, model, or provider.

### Features

* **ace:** add prompt-input history trigger (sase-4m.3) ([4e40764](https://github.com/sase-org/sase/commit/4e40764920a28e1ee243ca753c74e43695b6e67a))
* add plan approval CLI path ([ca8f5de](https://github.com/sase-org/sase/commit/ca8f5def1b9202af025d112baf29d25498e9a683))
* add sharded agent artifact migration ([6cfa3b1](https://github.com/sase-org/sase/commit/6cfa3b1714a1b1bc8fe53b9347abe658ff5ef3dc))
* make prompt history recency-only (sase-4m.1) ([224b632](https://github.com/sase-org/sase/commit/224b6324e0d5b2638b80637ec0bf7a14cac6c7a5))
* map worker models by primary lane ([51a36b8](https://github.com/sase-org/sase/commit/51a36b83d0caea4147e99a86fe99335c3f06ee58))
* **prompt:** add doctor, delete, and prune maintenance commands (sase-4o.3) ([32d8dfd](https://github.com/sase-org/sase/commit/32d8dfd2d746ceaa05dc039ea5c84465819ab22f))
* **prompt:** add export and save subcommands (sase-4o.4) ([7e0f9f0](https://github.com/sase-org/sase/commit/7e0f9f07de03761d89c1f7783d0d48416dac9e0b))
* **prompt:** add read-only `sase prompt` command group (sase-4o.1) ([3bc6d17](https://github.com/sase-org/sase/commit/3bc6d177b75b5d6c36412c0c6c38cadaceab8622))
* **prompt:** add replay, selection, and clipboard commands (sase-4o.2) ([a385fa5](https://github.com/sase-org/sase/commit/a385fa563d5cdd82a30d728964f4a45479d0e59a))
* **prompt:** polish, document, and integration-test the command group (sase-4o.5) ([f163194](https://github.com/sase-org/sase/commit/f1631941eb9ff715a60ecb7facb88299e58e7373))
* **repeat:** add STOP output variable to halt later repeat slots ([cf9d54a](https://github.com/sase-org/sase/commit/cf9d54a8916cc55cf49e083f5eaeb079ddce3666))
* resolve worker-lane models from the planner's primary context ([2da49fb](https://github.com/sase-org/sase/commit/2da49fbed5dcc57808237c7b3256f9c0cef2144d))
* Save failed agent prompts (sase-4m.4) ([3ba4e78](https://github.com/sase-org/sase/commit/3ba4e78b4e3cb45ca10c24b707ae3c849f7917c3))
* **tui:** redesign prompt history modal ([06700fa](https://github.com/sase-org/sase/commit/06700fa2ae5283e00269c1dff78d5433972c7fe3))
* **tui:** surface prompt metadata in history modal ([bdea1b3](https://github.com/sase-org/sase/commit/bdea1b3f805fde1dfa2a9851159d18f00e97681e))


### Bug Fixes

* **ace:** rebind prompt history to ctrl+k ([d7e45bc](https://github.com/sase-org/sase/commit/d7e45bc0744e1f4f0df155e7bdfabe29a547b6d1))
* **ace:** remove prompt history sorting references (sase-4m.2) ([ac817e0](https://github.com/sase-org/sase/commit/ac817e0c19098d2b3fda8f432094e69af1cb61ee))
* **agent-index:** use Rust facade for index metadata ([f13b4c6](https://github.com/sase-org/sase/commit/f13b4c6cb443bf602b7d949bb45c7fea94ac87d5))
* **agents:** support sharded artifact layout readers ([ae6e9ff](https://github.com/sase-org/sase/commit/ae6e9ff9ca09916827c66c114bb2611d523d57a4))
* **cli:** polish plan command help ([e5bf27a](https://github.com/sase-org/sase/commit/e5bf27ae4e218fc0e867b661eb806437d34254d3))
* keep axe restart status indicators accurate ([51ea133](https://github.com/sase-org/sase/commit/51ea1334ce6dcb8eae8f58ef9b8ce25b85f5779c))
* **plan:** filter pending approvals to live agents ([f15d55c](https://github.com/sase-org/sase/commit/f15d55c7efb914a3dc795a4e3867c1b279ca4bef))
* record failed non-TUI launches as cancelled history ([d9910fc](https://github.com/sase-org/sase/commit/d9910fcc25d827b1e565e30fdc7945c1854b5c21))
* record failed TUI launches as cancelled history (sase-4m.4) ([2a562f3](https://github.com/sase-org/sase/commit/2a562f3fc68947dc6df0114fc4c431e574180a2d))
* serialize artifact index metadata facade calls ([d5007f6](https://github.com/sase-org/sase/commit/d5007f63ebb653652a6da2135718418001247564))
* serialize artifact index startup maintenance ([265f3e9](https://github.com/sase-org/sase/commit/265f3e90be0b37298aa26b3582b45accaf072a03))


### Performance Improvements

* speed up plan list inventory ([cfbad85](https://github.com/sase-org/sase/commit/cfbad8509c0b263a83f8154d669d8c7d10ea5a4e))
* **tui:** avoid repeated tool artifact scans ([a4088d5](https://github.com/sase-org/sase/commit/a4088d57cfcb687456ab6ebd8086e5d8a21ab992))
* **tui:** defer forced-reuse cleanup to launch task ([5dfa29b](https://github.com/sase-org/sase/commit/5dfa29b219d3caa96e24e46b7ed21eee00a1e8c1))


### Documentation

* add PyPI version badge ([3276c82](https://github.com/sase-org/sase/commit/3276c827f2e46b2c1e0967b05ae2060c02574bdf))
* add research for proposed `sase prompt` command ([5c7a16e](https://github.com/sase-org/sase/commit/5c7a16ee020aced196c3131be162496e97845741))
* add sase prompt research infographic ([d3991f2](https://github.com/sase-org/sase/commit/d3991f2cde46672bad62214f2cd4a1c3e62d38cb))
* clarify plan approval workflow ([e5ab602](https://github.com/sase-org/sase/commit/e5ab602c5d65ef9182bafdd70d6e2fe612574e53))
* consolidate sase prompt command research ([cb7b4fb](https://github.com/sase-org/sase/commit/cb7b4fbd63dac72183c0b9c706832d8b34d955d7))
* **nav:** move [01] Hello, SASE post under Blog section ([db1043b](https://github.com/sase-org/sase/commit/db1043bec5f4b2036e990133574c38afc2ad3d5b))
* refresh plan workflow documentation ([30c1d6a](https://github.com/sase-org/sase/commit/30c1d6a9d4e29aeba116873e4eba330e5fe15bbe))
* research sase prompt command ([88bb7c1](https://github.com/sase-org/sase/commit/88bb7c1d0361b4ef393a2c32712b248f57d7ed11))

## [0.1.7](https://github.com/sase-org/sase/compare/v0.1.6...v0.1.7) (2026-06-13)


### Features

* **ace:** add agents detail zoom modal ([1bfd6a8](https://github.com/sase-org/sase/commit/1bfd6a888b945a05bf612375eb9f681eba5ee876))
* **ace:** add prompt vim quote and bracket text objects (sase-4l.3) ([14c0021](https://github.com/sase-org/sase/commit/14c00218029a4a7736b264e7fecb874e242b5021))
* **ace:** add prompt Vim visual mode (sase-4l.2) ([ef4363f](https://github.com/sase-org/sase/commit/ef4363fdccea2aa38f372a2ada328b35e9c45129))
* **ace:** add vim prompt fidelity commands (sase-4l.4) ([915fdc7](https://github.com/sase-org/sase/commit/915fdc737dda451657b2775dce14dec0bd17d546))
* **ace:** cycle VCS MRU prefixes in prompt bodies ([d297e00](https://github.com/sase-org/sase/commit/d297e000d1a043028cfa08d38008f51897adf5e6))
* add prompt vim indent and case operators (sase-4l.6) ([db9214c](https://github.com/sase-org/sase/commit/db9214c5f2201ad889d95ac4ea84a4f988aeb258))
* add prompt Vim yank and paste (sase-4l.1) ([a8603da](https://github.com/sase-org/sase/commit/a8603da30bd21ab891a669aed1730268530f8087))
* add vim paragraph motions to prompt input (sase-4l.5) ([abb8f9e](https://github.com/sase-org/sase/commit/abb8f9ecd38aef6c6e15385165e903f343e499b4))


### Bug Fixes

* pin codex model for pylimit split agents ([84d8fd7](https://github.com/sase-org/sase/commit/84d8fd7da775a89c9b27a46c5690ffa08651f677))
* resolve 11 bugs found auditing recent commits ([#170](https://github.com/sase-org/sase/issues/170)) ([08915a2](https://github.com/sase-org/sase/commit/08915a2fbd74449e0f847efc79b23987896deb28))


### Documentation

* expand git commit tag guidance ([1d59abb](https://github.com/sase-org/sase/commit/1d59abbcd27ccf52af8503f2c330ffe6b768f59f))

## [0.1.6](https://github.com/sase-org/sase/compare/v0.1.5...v0.1.6) (2026-06-12)


### Bug Fixes

* resolve 11 bugs found in recent-commit audit (cb7a4a556..690d4a3be) ([#167](https://github.com/sase-org/sase/issues/167)) ([93c8ccb](https://github.com/sase-org/sase/commit/93c8ccb35bd197a082269dc107cae7696fac6b04))

## [0.1.5](https://github.com/sase-org/sase/compare/v0.1.4...v0.1.5) (2026-06-10)


### Features

* add Claude Fable 5 model metadata ([7c7a5c6](https://github.com/sase-org/sase/commit/7c7a5c6a48298ffd2eab7787abce943ef38b4ed2))
* add dual-lane model override TUI (sase-4k.3) ([838d400](https://github.com/sase-org/sase/commit/838d40007f5e693c9ec3f1ec9f910fa291cc8b8b))
* add worker lane LLM resolution core (sase-4k.1) ([6afc114](https://github.com/sase-org/sase/commit/6afc114ac2c0a212256fbba220801bb90bd77d86))
* route epic phase agents through worker model lane (sase-4k.2) ([bb02d8f](https://github.com/sase-org/sase/commit/bb02d8f9a310282bec6b2a67c73197830c5c6b79))
* route plan-implementation handoffs through the worker model lane ([6a680c1](https://github.com/sase-org/sase/commit/6a680c1fd3ed2614e6d85290ed7537e0ad844f24))
* show all row provider badges ([f36a4b5](https://github.com/sase-org/sase/commit/f36a4b56f33eb6e88b7c62d9772943084940abc9))
* show single count in notification indicator ([91755ca](https://github.com/sase-org/sase/commit/91755ca46b23847d12a87b149f6194e823773b4d))
* track agent kill/dismiss persistence in task queue ([d204dae](https://github.com/sase-org/sase/commit/d204dae4a3bbb8311b8ea6c751f5c4d004e3d16e))


### Bug Fixes

* eliminate pre-paint dismissed-index sync from `sase ace` startup ([cf57ff5](https://github.com/sase-org/sase/commit/cf57ff540f6a9b498f79926409e770f8f1c1ea74))
* hide diff badge for plan-only changes ([575e6b4](https://github.com/sase-org/sase/commit/575e6b45de96aa55d0a43fbd68c30999b759fcea))
* preserve handoff model providers ([c27b66a](https://github.com/sase-org/sase/commit/c27b66a7d0d3877e23226395e8805ab941b15502))

## [0.1.4](https://github.com/sase-org/sase/compare/v0.1.3...v0.1.4) (2026-06-10)


### Features

* add compact root CLI help ([3161450](https://github.com/sase-org/sase/commit/3161450fc57f1db9f677ad98ac81d1504691b416))
* add doctor command runtime checks (sase-4i.2) ([4ab5e7f](https://github.com/sase-org/sase/commit/4ab5e7f09fb3338926d94e98940a76d04258a78c))
* add phase 3 doctor checks (sase-4i.3) ([def2859](https://github.com/sase-org/sase/commit/def285906e0289ecd1937c43c8bc7fab867f5e15))
* add phase 4 doctor checks (sase-4i.4) ([e802a84](https://github.com/sase-org/sase/commit/e802a84efa89d36c67d835bea77eb0746e13391d))
* add runtime version command (sase-4h.3) ([fa6b12d](https://github.com/sase-org/sase/commit/fa6b12d6aebdd38dfb77f6324b473cae3e97d61f))
* add runtime version inventory collector (sase-4h.1) ([9a6fed3](https://github.com/sase-org/sase/commit/9a6fed341fb50c609f7a9c227e60c82a0f896934))
* add shared diagnostics foundation (sase-4i.1) ([fc2d009](https://github.com/sase-org/sase/commit/fc2d0097d5f2306365c9f8ac2ccc26ac24e38b73))
* allocate fan-out names through templates (sase-4g.4) ([59cb6a5](https://github.com/sase-org/sase/commit/59cb6a5e0d2b27bed270a29315ebdff4fb43fa08))
* clean up agent name template references (sase-4g.5) ([f65466f](https://github.com/sase-org/sase/commit/f65466f22828cee27dddf449c555ba405e3f18bd))
* discover plugin packages in version inventory (sase-4h.2) ([28933e2](https://github.com/sase-org/sase/commit/28933e2fc8d14065e416910cd685cbe22a1a6107))
* harden version runtime inventory (sase-4h.4) ([e10427e](https://github.com/sase-org/sase/commit/e10427eb38871507c5f28462e2155be0dd7c4dd1))
* optimize agents tab local refresh paths (sase-4f.6) ([4d9c4cc](https://github.com/sase-org/sase/commit/4d9c4ccc78f65e5967acc6b5eefeef2ab45d8732))
* plan generic agent name templates (sase-4g.3) ([8f81b30](https://github.com/sase-org/sase/commit/8f81b30cd927a12d411799ad84629d4e75b8f22e))
* polish doctor support workflow (sase-4i.5) ([8887451](https://github.com/sase-org/sase/commit/8887451643e417f440e542e4990c1feb7a4ae5ff))
* reconcile launch results with artifact deltas (sase-4f.4) ([1eee25b](https://github.com/sase-org/sase/commit/1eee25b3f825f597278a7aa386e3ea271e963af1))
* show prompt previews in agent restore records ([2fdb10e](https://github.com/sase-org/sase/commit/2fdb10e163479707a952530e8cff8a62d15c6df0))
* sort and color compact root help ([47a1190](https://github.com/sase-org/sase/commit/47a1190270a8971dcec368f76524d102741102ff))
* support registry-backed @ name templates (sase-4g.2) ([2fb3d3b](https://github.com/sase-org/sase/commit/2fb3d3b5b1c880113d617933fbe6ed550d91cd72))
* support zoomed artifact pane opens ([556af4b](https://github.com/sase-org/sase/commit/556af4baf4d550404646627d6985bdd9203796bf))
* track TUI agent launches in task queue ([eb5db8a](https://github.com/sase-org/sase/commit/eb5db8a27e969aab3c3b6ed07cde6887812bd28d))
* **tui:** use exact agent deltas for notification refreshes (sase-4f.5) ([08c945d](https://github.com/sase-org/sase/commit/08c945d0c77786ab0f321741122aa1f296ca076c))
* update built-in templates terminology (sase-4g.6) ([0dd2cda](https://github.com/sase-org/sase/commit/0dd2cda86ada7142b3fa65d983dd728dd0c97fe6))


### Bug Fixes

* purge dismissed bundles on revive so agents stay visible ([cab1bf5](https://github.com/sase-org/sase/commit/cab1bf5519e3443c9e9ff3970bd2ae539e445f4f))
* render doctor help options compactly ([#162](https://github.com/sase-org/sase/issues/162)) ([a2a0fe0](https://github.com/sase-org/sase/commit/a2a0fe047361b0356a9a15f621b4f48d7297ecd1))
* reserve agent template namespaces ([75f999e](https://github.com/sase-org/sase/commit/75f999ecd223802b9fdf55fd4b13214978eea970))
* resolve live diff workspace via canonical WorkspaceStore ([2c0b9c1](https://github.com/sase-org/sase/commit/2c0b9c121765e34cf9dcfa70e3dcd2467391b0d7))
* surface missing LLM provider CLI setup (sase-4j.1) ([237c932](https://github.com/sase-org/sase/commit/237c932f9d9fcaeab76a9da996fa76ef9aa090d7))
* validate agent namespace template binding ([#163](https://github.com/sase-org/sase/issues/163)) ([a0658b6](https://github.com/sase-org/sase/commit/a0658b6d916739c869ded743c78d3239fa7e56a1))
* validate setup dependency groups ([d445153](https://github.com/sase-org/sase/commit/d4451532b9fc9fd6c61d92630084f2b91ed52567))
* validate setup dependency groups ([02ccc79](https://github.com/sase-org/sase/commit/02ccc79ef77e714242f0ed4f5e48a79a90625ebb))
* **version:** make verbose audit readable (sase-4h) ([d218778](https://github.com/sase-org/sase/commit/d218778855235a4115678f3fba9875362aa11a58))

## [0.1.3](https://github.com/sase-org/sase/compare/v0.1.2...v0.1.3) (2026-06-08)


### Features

* add agents refresh telemetry taxonomy (sase-4f.1) ([43ec668](https://github.com/sase-org/sase/commit/43ec668316ae38938a3b50bc2ef5ca03955cb01f))
* add exact artifact delta loading (sase-4f.2) ([8209751](https://github.com/sase-org/sase/commit/8209751f8dbf1f703adc800d287f87759f097253))
* add incremental Agents display refresh (sase-4f.3) ([5a14acc](https://github.com/sase-org/sase/commit/5a14acc1e18db369b7333f7aff93b1b8b57ce79c))

## [0.1.2](https://github.com/sase-org/sase/compare/v0.1.1...v0.1.2) (2026-06-08)


### Bug Fixes

* reserve planned multi-prompt agent names ([5418147](https://github.com/sase-org/sase/commit/5418147ea88f5edbdb01e58a9854b7ff35a576aa))
* use PR terminology in ACE command labels ([bbe05e9](https://github.com/sase-org/sase/commit/bbe05e9b2905af299f68be0067987db1d34eb30d))
* use PR terminology in ACE command labels ([90b8261](https://github.com/sase-org/sase/commit/90b826121193d211b415a83787dd2301e0da8881))

## [0.1.1](https://github.com/sase-org/sase/compare/v0.1.0...v0.1.1) (2026-06-08)

### Bug Fixes

- honor active venv in just test setup
  ([b98e55c](https://github.com/sase-org/sase/commit/b98e55cea7b478cd456fdfdbbc492a8274bb20f6))
- honor active venv in just test setup
  ([0224105](https://github.com/sase-org/sase/commit/0224105ac98c6a944eb3b8e5367178dcbb1528e3))
