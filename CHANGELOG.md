# Changelog

## [0.16.0](https://github.com/sase-org/sase/compare/v0.15.0...v0.16.0) (2026-08-07)


### ⚠ BREAKING CHANGES

* publication outbox files are written at schema version 5 and older sase versions cannot read them. Queued `bead_pages`, `plan_header`, and `sidecar_push` records in an existing v4 outbox are dropped on first read; that work is published inline on the commit path instead.
* the `sase_chop_sidecar_publication` console script and the `publications` axe lumberjack lane are gone. `sase axe chop run sidecar_publication` now fails with "unknown chop". Remove any `publications` lane overrides from local axe configuration.

### Features

* **ace-tui:** add shared list-marker model and ordered renumber engine ([cb1007e](https://github.com/sase-org/sase/commit/cb1007e0900c4be02fe4b94d966ccbec164a503d))
* **ace-tui:** drop and renumber ordered markers on NORMAL-mode J ([ecce0c3](https://github.com/sase-org/sase/commit/ecce0c3888b8381dce9fb0881a2927090d05b2e0))
* **ace-tui:** give each notification exactly one tab, counted in the core ([5e6a94a](https://github.com/sase-org/sase/commit/5e6a94a3890d192dca6091d2165783381c8348e3))
* **ace-tui:** give every notification tab a stable, configurable color ([821966d](https://github.com/sase-org/sase/commit/821966dd2812965d9deb2cc2045603644e69c342))
* **ace-tui:** grow and renumber ordered lists on INSERT-mode Ctrl+J ([af0555b](https://github.com/sase-org/sase/commit/af0555bd60926526bc9087458647f9a935e30a5f))
* **ace-tui:** highlight ordered-list markers like bullet dashes ([f7f479a](https://github.com/sase-org/sase/commit/f7f479a55ba1a6f7bfb5130e6ab8314f831b9b17))
* **ace-tui:** nest and unnest ordered prompt items with Tab and Shift+Tab ([686bd5f](https://github.com/sase-org/sase/commit/686bd5f5165734e719f7809fdc0f0f0b15444102))
* **ace-tui:** open numbered ordered siblings on NORMAL-mode o and O ([a3108ef](https://github.com/sase-org/sase/commit/a3108ef4f2950f9d7fb1d481d0704471d6317d20))
* **ace-tui:** show FAMILY MEMBERS roster on family-member detail panels ([8fcc252](https://github.com/sase-org/sase/commit/8fcc2520fb17e20ba0d8c17381bbde58e8145949))
* **ace-tui:** show one indicator chip per notification tab ([09bb443](https://github.com/sase-org/sase/commit/09bb443ea4206edf188b54042713cf561fc89f94))
* **ace-tui:** snooze task beads from the Beads pane ([0f7960d](https://github.com/sase-org/sase/commit/0f7960d0853a7cd52721cec1361ae1c394cd0dee))
* **ace:** show bead close history in the beads pane ([4130721](https://github.com/sase-org/sase/commit/413072167f8069fb0b6714075897358cb9920e78))
* **ace:** show commit creation time in the commit panel ([301f33a](https://github.com/sase-org/sase/commit/301f33a544c596224477d2a9499e0e4dcb59b821))
* **ace:** show explicit created and updated ages on bead surfaces ([865281b](https://github.com/sase-org/sase/commit/865281be4146ee9475a820e345c8b4930b701d17))
* **agents-sync:** link published agent pages back to their bead pages ([48a34b4](https://github.com/sase-org/sase/commit/48a34b4a11b9dd3553a3e0bd0fa4545ccddb10f6))
* **bead-pages:** render close history and reopen badge on generated pages ([bf448ef](https://github.com/sase-org/sase/commit/bf448ef99c12a28702cc1f38eaae03634a4dc089))
* **bead:** add roster creation-time column and regression coverage ([4330fd0](https://github.com/sase-org/sase/commit/4330fd0d5a6f2e36a84e8142d902faaf282a37c0))
* **bead:** add sase bead snooze and snooze-aware detail surfaces ([b723ace](https://github.com/sase-org/sase/commit/b723ace648b5c99923874f933c3f16e99cc1eeb9))
* **bead:** add shared bead time presentation module ([53fc8d9](https://github.com/sase-org/sase/commit/53fc8d9f89160af121517827803d134f41102252))
* **bead:** add shared reopen presentation vocabulary ([9d0422f](https://github.com/sase-org/sase/commit/9d0422fdacd5d64144885212bbbe5515b7c62a03))
* **bead:** carry close history through Python bead storage ([1da5a3e](https://github.com/sase-org/sase/commit/1da5a3e277326bf52cf79c72c1ec824cbdc2e02b))
* **bead:** include snoozed status in default bead list filter ([8b92115](https://github.com/sase-org/sase/commit/8b92115e835227b0cd67754d4842ef9ef4183da1))
* **bead:** keep exactly one pending gate per task bead ([b0e10d1](https://github.com/sase-org/sase/commit/b0e10d1284e0a364db8ccfae462ab3ab1e2d4a08))
* **bead:** mirror the snoozed task-bead status in Python ([1f0d1a2](https://github.com/sase-org/sase/commit/1f0d1a2ae39b68634be1e1176454f694fefba5ee))
* **bead:** raise a BeadSnooze gate when a snoozed task wakes ([17fcbb4](https://github.com/sase-org/sase/commit/17fcbb485e907962b8be4a3aa396d1873f094b4f))
* **bead:** show bead creation time on task triage gates ([8065b58](https://github.com/sase-org/sase/commit/8065b58c411b2ec5bd7bbb2caa54c718d22c74c1))
* **bead:** surface bead creation time across CLI detail, list, and dependency views ([e4fce05](https://github.com/sase-org/sase/commit/e4fce05b61985d8f28e8f6dc44008526ce2d89c4))
* **bead:** surface bead creation time on mobile, page tables, and clan summaries ([734d2e0](https://github.com/sase-org/sase/commit/734d2e0c261834051c4c2c7bd139e7f848a8f071))
* **bead:** surface reopen history in bead show, JSON, list rows, and search ([d0e59df](https://github.com/sase-org/sase/commit/d0e59dfdd4d37de450f997bbc1d418ba4fa8af35))
* **bead:** warn on prior close in the TaskTriage gate ([81d6191](https://github.com/sase-org/sase/commit/81d6191e3326265822b36b7040339fba7ce1eabd))
* **cli:** add `sase plan show` detail command ([2c11c4e](https://github.com/sase-org/sase/commit/2c11c4eb85e3c421e76897c871b47c5425cb663a))
* **dev-update:** warn when a code swap could tear a live agent runner ([b5c78f9](https://github.com/sase-org/sase/commit/b5c78f972a3e21f897eadf959a2343fddec8bd74))
* narrow the durable publication outbox back to agent-hood retries ([ccf4d77](https://github.com/sase-org/sase/commit/ccf4d77a9b1ffe83936e81c082040d61d2b8af60))
* Per-member Model lanes for agent family detail panels ([7ba83b1](https://github.com/sase-org/sase/commit/7ba83b1e1bdd020a74c6a7bbc87daa07a138792f))
* remove the sidecar_publication chop and publications lumberjack ([e99f501](https://github.com/sase-org/sase/commit/e99f5017d39fc15f6a8f5082fbd82ed2d768a2db))
* **sdd:** adopt header-invalid diagnostic and pin it at every validation surface ([d9c1354](https://github.com/sase-org/sase/commit/d9c13549f9809f2ba8d695027dc7bf76440e7844))
* **test-selection:** add a bounded-parallelism middle gear for large selections ([ca6c1e0](https://github.com/sase-org/sase/commit/ca6c1e09e8be639db7d4f386860c043f4da1a3af))
* **test-selection:** escalate on estimated serial runtime, not file count ([af3aa32](https://github.com/sase-org/sase/commit/af3aa326cfe5fa193251ed4968630a3a57fca731))
* **test-selection:** record a contexts baseline from a local full run ([2ef98cb](https://github.com/sase-org/sase/commit/2ef98cb3e646ca6e6f5298398b5a8c4855273774))
* **test-selection:** record per-test-file timings from full-lane runs ([6cf5a94](https://github.com/sase-org/sase/commit/6cf5a94d7ce95c5e80e5f924bd58bddec13ecfb4))
* **test-selection:** report the scoped lane's tail, not just its median ([cc241fa](https://github.com/sase-org/sase/commit/cc241fae0c5cb96e0dbffc468e1cc5f77fde4d6b))
* **test-selection:** surface the scoped lane's summary on the success path ([da6105b](https://github.com/sase-org/sase/commit/da6105b51edf8141b979478882ba6c0aa4b0a81a))
* **test-selection:** walk one hop deeper when no contexts baseline is usable ([b4c4c18](https://github.com/sase-org/sase/commit/b4c4c182e1a68037fed639215c4d35ebbeab7e15))
* **tests:** add a scoped run mode to the pytest runner ([8c4e14a](https://github.com/sase-org/sase/commit/8c4e14ab0f564eee9242e66ac21f2d82d53f0027))
* **tests:** add the static import-graph test selection engine ([8c8d197](https://github.com/sase-org/sase/commit/8c8d1973d095c454fd39fd648738c0a86def34c1))
* **tests:** track test-selection health and detect selection false negatives ([96183d7](https://github.com/sase-org/sase/commit/96183d71b3ef6edd427d8c388ba0f96644af6244))
* **tests:** union per-test coverage contexts into diff-scoped selection ([d66101e](https://github.com/sase-org/sase/commit/d66101e8f292cb53b48ae2287f0f5f723b3c3ff9))
* **tui:** show bead creation time in context lane ([256da28](https://github.com/sase-org/sase/commit/256da2887127cbe390cfd55d9ac5387b830ec25c))


### Bug Fixes

* **ace-tui:** stop bulk-kill-and-edit test racing relaunch prompt resolution ([bde727e](https://github.com/sase-org/sase/commit/bde727ecc0dbe67a734584e2c1abf3dbe49e8730))
* **ace:** resolve Artifacts project scope through project refs ([9a366e0](https://github.com/sase-org/sase/commit/9a366e0d6c5a0357a25044feb485357ad7ee2121))
* **ace:** stop the beads detail pane from oscillating between two layouts ([01398f5](https://github.com/sase-org/sase/commit/01398f5afc1061812388696daf82c78441665987))
* **agents-sync:** repair stale hood-snapshot digests and add drift check ([2a9627b](https://github.com/sase-org/sase/commit/2a9627bc0814c495b8b5a99145eb7c17c72059ee))
* **agents-sync:** retry deferred prompt archives on the full sync path ([2ac967d](https://github.com/sase-org/sase/commit/2ac967d781bb182891932ac680e8235bbc9f92b2))
* **agents-sync:** stop dismissed agents' owned legacy-v1 hoods from importing as unknown-user ([8b8acb4](https://github.com/sase-org/sase/commit/8b8acb4335881db4d490650461652237a405dd60))
* **artifact-file:** resolve logical plans: references when synthesizing plan rows ([b3ac417](https://github.com/sase-org/sase/commit/b3ac417f3a595cee7ee123a5da819a384e50cc6c))
* **axe:** keep host-owned epic launches alive after an SDD store failure ([75a1ffc](https://github.com/sase-org/sase/commit/75a1ffc10692d24c8016ee6574ad901197d1752a))
* **axe:** refuse to evict workspace sidecar clones holding unpublished bead commits ([d1b6f01](https://github.com/sase-org/sase/commit/d1b6f01a9e1ae04bb912cb17f360aaafd6b9df25))
* **axe:** serialize workspace prep with agents sync on the shared sidecar clone ([625b5ca](https://github.com/sase-org/sase/commit/625b5cac40fba4d0db7edf41b026fd36ac516798))
* **axe:** survive mid-run editable source swaps in agent runners ([4895b8f](https://github.com/sase-org/sase/commit/4895b8f32f64878321f3c4965f39b6d00c340eaa))
* **bead:** recover sync when two clones mint the same bead id ([6b3b46e](https://github.com/sase-org/sase/commit/6b3b46e85b6df66d595e506609ebe322a2803eb3))
* **bead:** verify bead-store mutations are published before reporting success ([99eedf7](https://github.com/sase-org/sase/commit/99eedf74912088e92a3e8b3cbf0786bf83b85633))
* **commit-finalizer:** break async-wait deadlock in finalizer passes ([840cdff](https://github.com/sase-org/sase/commit/840cdff10664d2629ddc38f2677ec80e7dcaaca8))
* **commit-finalizer:** fail the run when auto-committed bead state is never published ([980bdd3](https://github.com/sase-org/sase/commit/980bdd33767edd55ce358ff9d2bd9a89b81a502c))
* **commit-finalizer:** import progress_fingerprint directly so symvision can see it ([a4a2c1a](https://github.com/sase-org/sase/commit/a4a2c1a6004016667c71b50522be8807bb8368da))
* Disambiguate duplicate agents sidecar entries in sase repo open ([638f99b](https://github.com/sase-org/sase/commit/638f99b89c230d74b2902b6ee5e9f875a1debe23))
* drop member-role anchor fragment from agent Page URL ([5daa94f](https://github.com/sase-org/sase/commit/5daa94ff7042f62ea3c6987fb5fbb5c565a93952))
* **llm:** wrap agent prompts at the repo-wide 120-column width ([5da1934](https://github.com/sase-org/sase/commit/5da193482e4f755413418330e7f5c3e681ccf73f))
* **plan-approval:** resolve the project key when archiving an approved plan ([4934094](https://github.com/sase-org/sase/commit/49340948a4f6d4077af86f7e8b0c36a244784d6f))
* publish sidecar work inline on the commit path ([de78052](https://github.com/sase-org/sase/commit/de7805278926e3a9abd97b475afca158363d7ffc))
* **sdd-store:** degrade unresolvable agents sidecar instead of aborting store resolution ([baebfcd](https://github.com/sase-org/sase/commit/baebfcd216319315e169d4c189666fe3db148048))
* **sdd:** report header-invalid from plan links validate ([fa8fc69](https://github.com/sase-org/sase/commit/fa8fc69e46c49bc3367ea274584d7fa928aa1dc9))
* **sdd:** validate plan header before projection at the archive boundary ([b088620](https://github.com/sase-org/sase/commit/b08862001860814452c89553f10cc6a52c88d87e))
* **test-selection:** attribute and narrow the core-identity-changed escalation ([f88b740](https://github.com/sase-org/sase/commit/f88b7403cd0dcc2d5522d909582a7cdbddbb1304))
* **test-selection:** drop deleted test paths from scoped selection ([cf130a2](https://github.com/sase-org/sase/commit/cf130a278505f0cf9921acb016011b8fb9789a60))
* **test-selection:** rank coverage-contexts baselines by breadth, not mtime ([368cf15](https://github.com/sase-org/sase/commit/368cf151a445f9e0cb96a7e2c958decb91c031b3))
* **test-selection:** stop charging known flakes to the false-negative metric ([87961cd](https://github.com/sase-org/sase/commit/87961cd0e17a2d5a137b327325bb68b28156cc28))
* **test-selection:** stop reporting an escalated run as one with no baseline ([559d4c2](https://github.com/sase-org/sase/commit/559d4c2443b78ae495f25842bd94a42ad05ceb78))
* **test-selection:** stop the codeblock cursor test racing the blink timer ([3f69267](https://github.com/sase-org/sase/commit/3f69267d516c5131ecca44b22399e67838b508c1))
* **tests:** allow chezmoi-deploy-locks in tmp-leak-guard allowlist ([48bd000](https://github.com/sase-org/sase/commit/48bd0009ebdcf7ae883abfd548e1a02967c3e318))
* **tests:** give the git-sync sidecar clone a committer identity ([260ea5a](https://github.com/sase-org/sase/commit/260ea5a0d99d536fcb38d30ea51270c5b775bfa7))
* **tests:** isolate xprompt usage tests from ambient swarm env var ([02dee21](https://github.com/sase-org/sase/commit/02dee218264828a6d4359623434ed3eed6c433c7))
* **tests:** restrict selection-health false-negative correlation to matching changes ([e7917a2](https://github.com/sase-org/sase/commit/e7917a2682e81c2119509e75bbdf19e7c4da0796))
* **tests:** stop CI worker collapse and drop visual from default lane ([9672c56](https://github.com/sase-org/sase/commit/9672c5602816c39f3d6f2e4af2b50a2e032f0d5e))
* **tests:** stop real-uv harness leaking lock files into watched temp root ([6ee11e5](https://github.com/sase-org/sase/commit/6ee11e5e9df5f47b1233ca34ed49f0a1989c323e))
* tolerate forward-compatible owner manifests ([0e40dec](https://github.com/sase-org/sase/commit/0e40decdcebd063b5d136b5a8359b9a59a52bb48))


### Performance Improvements

* prefer LibYAML C loader for trusted config YAML reads ([dc993cc](https://github.com/sase-org/sase/commit/dc993ccd87657982f3f0213f8214dea2c43f26ac))
* simplify agent prefix matching ([#272](https://github.com/sase-org/sase/issues/272)) ([939794c](https://github.com/sase-org/sase/commit/939794c398018b01d735de247a01e03c29d9b5e1))


### Documentation

* **ace-tui:** document ordered-list numbering, run, and nesting rules ([96a53e7](https://github.com/sase-org/sase/commit/96a53e7ab0d06116fd9adb8a3b18565d00cac75e))
* **artifact-ref:** describe the scratch probe against sase-core 0.18.4 ([a15f409](https://github.com/sase-org/sase/commit/a15f409dd11322a32649c627e226a0fd448c9070))
* **bead:** document the snoozed task-bead status and per-tab indicator ([44727b0](https://github.com/sase-org/sase/commit/44727b0275df6c62f09c7929677ce54e35f4a8a4))
* **beads:** document close history and reopen provenance ([d7ac0da](https://github.com/sase-org/sase/commit/d7ac0dab5cdfc4c2b00f102e588d5d8506b6196f))
* correct and clarify the refreshed user-facing docs ([a7e6f05](https://github.com/sase-org/sase/commit/a7e6f05143450eddaca6cdc9dd011ad64f363065))
* describe restored inline sidecar publication ([02dcea6](https://github.com/sase-org/sase/commit/02dcea68b016131e31f6d79bde7d9511a51385c2))
* **justfile:** correct the scoped lane's suite-gate lease claim ([9e4e4ff](https://github.com/sase-org/sase/commit/9e4e4ff54aff6ac9d37393625b4053e2bda6dbc8))
* **memory:** document two-speed verification contract, fix stale visual-snapshot claim ([6f1a071](https://github.com/sase-org/sase/commit/6f1a0717f1af3ee11f757a4820822427f5489670))
* refresh user-facing documentation ([5311383](https://github.com/sase-org/sase/commit/531138373fc480b581242fbd3cee4ebadcfc4819))
* **test-selection:** document the implemented false-negative rule ([b657fce](https://github.com/sase-org/sase/commit/b657fce17e86ef9a15e596866f9203e8e73edbdf))
* **test-selection:** document the tail phase's slow-run and cost-not-measured fields ([a042950](https://github.com/sase-org/sase/commit/a04295008fbb1e7c973ffd9ed69b848d2cea7a68))

## [0.15.0](https://github.com/sase-org/sase/compare/v0.14.0...v0.15.0) (2026-08-05)


### ⚠ BREAKING CHANGES

* **xprompt:** write_xprompt_sources() and the xprompt_sources.json launch artifact are removed; the private xprompt source collector is now the public collect_xprompt_sources() API.
* **cli:** `sase chat show` no longer accepts `-x`, `--rendered`, or `-f xprompt/rendered`, and `sase agent prompts show --rendered` is removed. Consumers should read the archived prompt document or raw chat transcript.
* **history:** save_chat_history and write_chat_history no longer accept xprompt_prompt or rendered_prompt, and chat_history.rendered_prompt_max_bytes is no longer a supported config option.
* **prompt-archive:** Prompt archives no longer include rendered prompt sections or xprompt link rewrites, and prompt validation JSON no longer reports legacy_files.
* **sdd:** keep validation green while sidecar publication is pending
* **cli:** `sase bead show -S` is replaced by `-s`, and `--style color` is removed; use `--style rich` with `--color` for styled detail output.
* **ace:** The ACE Statistics pane no longer exposes dedicated Runs or Runtime tabs, and numbered view selection now targets only the seven remaining Statistics views.
* **prompt:** `sase prompt export --sdd` no longer writes prompt snapshots. Use `--out` for an explicit file export or `sase agent prompts` for archived agent prompts. The canonical search source is now `archive`; `sdd` remains a deprecated compatibility alias.
* **agent:** Historical prompt files now live in the agents sidecar; plans-store prompt discovery and repair are no longer supported.
* **beads:** New task beads require an explicit size, and the @task_worker alias is no longer available; use a size-specific phase-worker alias instead.
* **cli:** Compact bead list/show output no longer includes the type word column before the status glyph. Scripts that parse compact output should use full or JSON output, or treat the first field as a type glyph only.
* **commit:** Commit workflows now reject non-conventional or empty subjects by default; use a valid Conventional Commit subject or disable the policy in configuration.
* **bead:** `sase bead ready` now reports unblocked task beads in ready status instead of treating open epic phases as generally ready work.
* The bundled bd/next xprompt is removed; launch ready task beads through bd/work_task.

### Features

* **ace-tribes:** drop bundled research tribe display config ([e023e68](https://github.com/sase-org/sase/commit/e023e68a9d8e363a92e2504e881d92d00f26c39d))
* **ace-tribes:** require a description for configured agent tribes ([ba611aa](https://github.com/sase-org/sase/commit/ba611aa4834ce85727808aa2738687dae16515a4))
* **ace-tui:** load prompt commit snapshots independently ([6b7284c](https://github.com/sase-org/sase/commit/6b7284ce4d21a62c274bf016c9c6ef9ca4ece0f2))
* **ace:** add alternate-section jump to Admin Center opener key ([0002a05](https://github.com/sase-org/sase/commit/0002a0590cfe4e2b801a1244046b8311034d4fa1))
* **ace:** add clan commit context lane ([1b29a74](https://github.com/sase-org/sase/commit/1b29a74183de99e9e50cec95b1287e7188511939))
* **ace:** add undo for bulk agent read toggle ([d53f085](https://github.com/sase-org/sase/commit/d53f0856eed0f83076e2afe96ad5b1fb0bee5707))
* **ace:** add word to aspell personal dictionary from spellcheck panel ([0f273b6](https://github.com/sase-org/sase/commit/0f273b6083eca865bc23b6064fb37ef3d88502fa))
* **ace:** polish agent CLI update history ([d55db39](https://github.com/sase-org/sase/commit/d55db39c9fb6c0b1e63d7bd838d62bb1f4df6785))
* **ace:** polish beads and nested files views ([80d44e3](https://github.com/sase-org/sase/commit/80d44e38414c1ce4258535271208c6c6be38ad9b))
* **ace:** remember admin center entry selections ([460b8ff](https://github.com/sase-org/sase/commit/460b8ff2356cc7f35357d2207b14f23182eef3c9))
* **ace:** remember misspelled words and squiggle them in every prompt ([e2d56df](https://github.com/sase-org/sase/commit/e2d56dfce25e5add6a2d1630be04588f4ceed568))
* **ace:** remove Statistics runs and runtime tabs ([bcefbb8](https://github.com/sase-org/sase/commit/bcefbb8e40d48578b3aa221b6bd343669b13a2e9))
* **ace:** render structured output variables ([668bf20](https://github.com/sase-org/sase/commit/668bf209d35dd7cabc6c0b5bfb64b60f6f9e31f5))
* **ace:** render tribe description as a labeled block below the header ([146982d](https://github.com/sase-org/sase/commit/146982d144c3c4c68cba7d65afae5646808dd793))
* **ace:** schedule snooze reminders by deadline ([38c57e1](https://github.com/sase-org/sase/commit/38c57e178101114294aee51a8563e23ed9dbceec))
* add durable sidecar publication queue ([6e39779](https://github.com/sase-org/sase/commit/6e397794552c9e7e8e2feb593cb57f7382fd6b37))
* add read-only Artifacts Beads pane ([2e1264e](https://github.com/sase-org/sase/commit/2e1264eed3c42450b5dab0b3e303353291a839a3))
* add structured output variable values ([3c7e588](https://github.com/sase-org/sase/commit/3c7e5887c2fa1b7195ac51fbbfd7dc2f754bed77))
* **agent-clis:** journal update runs ([55eb243](https://github.com/sase-org/sase/commit/55eb24331e77f758be540d45c9db4451cac84b5e))
* **agent-clis:** render update history panel ([a086b0f](https://github.com/sase-org/sase/commit/a086b0f30ecef9cf0f66891695650fd165fd8f5d))
* **agent-clis:** wire update history into pane load, config, and session state ([e4ad939](https://github.com/sase-org/sase/commit/e4ad939168acf54a963c5a404a39cbd059ef969e))
* **agent-names:** migrate historical agent identities ([b4db947](https://github.com/sase-org/sase/commit/b4db947d2c746c1c4aebc68f3d3ecee95ae44a9f))
* **agent-scan:** preserve structured output variables ([2b95bd3](https://github.com/sase-org/sase/commit/2b95bd329fb0a8fa1b666b1019fed154b6870b7f))
* **agent:** add canonical prompt archive validation ([64c26f1](https://github.com/sase-org/sase/commit/64c26f106fac8b03237761f420079fae71c116b3))
* **agent:** migrate prompts to the agents archive ([fa7e7c8](https://github.com/sase-org/sase/commit/fa7e7c8a7d58ca15e3a9e906ae90f7e4959972a3))
* **agents-sync:** publish structured output variables ([b66357e](https://github.com/sase-org/sase/commit/b66357ee238c45291b58764504232d2397f0e872))
* archive committed prompts and artifacts ([149b57e](https://github.com/sase-org/sase/commit/149b57e4f42fa70fa2bda7dde41a760cc3cc6c53))
* **artifact-refs:** propagate repository kind into wire form and parity test ([70410a0](https://github.com/sase-org/sase/commit/70410a05b1a6250bbe6adb86c41a65cbef827e9b))
* **artifact:** reclaim stored bytes from durable VCS ([ac2d5b2](https://github.com/sase-org/sase/commit/ac2d5b22cf2d4cc0c0c25f5accb039d9118cee79))
* **artifacts:** add Beads pane filtering ([c194459](https://github.com/sase-org/sase/commit/c1944592a025e618ab4a6168815c3c7ea73ff052))
* **artifacts:** link Beads and Plans panes ([db504de](https://github.com/sase-org/sase/commit/db504de6e348401c3fa960cef38980afd4a8b1e6))
* **artifacts:** stage prompt references for durable capture ([24432d9](https://github.com/sase-org/sase/commit/24432d9d50246e39109dcb0468816f98dbd7635c))
* **artifact:** surface bead references and attach on create ([87ece3e](https://github.com/sase-org/sase/commit/87ece3ee34d613780923e2d9d9a2f0349ff12f0a))
* **axe:** drain queued sidecar publications ([0d6ed1a](https://github.com/sase-org/sase/commit/0d6ed1a194b2cdb8c398399e82fcbcc903ee51f8))
* **axe:** triage ready task beads ([d8028ee](https://github.com/sase-org/sase/commit/d8028eeebf7f240c76a5f0cd034f0629b066d5c0))
* **bead-pages:** render bead creators ([3b08766](https://github.com/sase-org/sase/commit/3b087669e066c5552adf0154d2d202be45565045))
* **bead:** add shared type presentation helpers ([6e02e30](https://github.com/sase-org/sase/commit/6e02e3063a8803bf1c8239aa2c7bffb9c7d39e24))
* **bead:** colorize and syntax-highlight `sase bead show` ([6e8029b](https://github.com/sase-org/sase/commit/6e8029b7b460bf1c38e857bc0f605b0381a6f2cb))
* **bead:** label redundant close history ([6521dd3](https://github.com/sase-org/sase/commit/6521dd3c28b95ef49731a154f87ced3c5dc500a7))
* **bead:** launch standalone task workers ([879af9b](https://github.com/sase-org/sase/commit/879af9b0831fa59a0bccaf580d11f6afd26ffb2c))
* **bead:** mirror task readiness in Python ([d0da0d9](https://github.com/sase-org/sase/commit/d0da0d94f9f4a8c748c68c390c9016ef881566b8))
* **bead:** persist bead work launch timing ([cb6efd7](https://github.com/sase-org/sase/commit/cb6efd7de3380634387b10c30d08ffdfe7bd288c))
* **bead:** resolve the acting agent as a bead creator ([578e4f5](https://github.com/sase-org/sase/commit/578e4f5c6499c32d21468734e142ff1c6d092eac))
* **bead:** retry bead-work preclaims on store-lock contention ([09c1d0d](https://github.com/sase-org/sase/commit/09c1d0d6b793cc278a644bdbde4aa05c08c58148))
* **beads:** accept multiple bead IDs in `sase bead update` ([50988fe](https://github.com/sase-org/sase/commit/50988fe7f0b77c0f54fbd71fd9de89ae3788662b))
* **beads:** add disciplined task creation skill ([2ec8613](https://github.com/sase-org/sase/commit/2ec86131dcb38e9b6213723d08a7898b2165f1b5))
* **beads:** add task promotion and size-based routing ([767852a](https://github.com/sase-org/sase/commit/767852ac977c63beae5e2e994fac7db5f15142c1))
* **beads:** attribute creation to the responsible agent ([b2b1e73](https://github.com/sase-org/sase/commit/b2b1e73d9210383f11b4e61a5ef08fd8bc3a63fc))
* **beads:** expose prefix migration facade ([b763878](https://github.com/sase-org/sase/commit/b763878d3dc938672722d6053737f8e706cdc180))
* **bead:** show task type and ready status on pages and mobile ([2ce43ee](https://github.com/sase-org/sase/commit/2ce43ee3e84c960fafa9326d15d8cd2f26475756))
* **bead:** show type indicator in `sase bead list` compact rows ([01ace66](https://github.com/sase-org/sase/commit/01ace663f411fc6eab8d6bbfbf2f73cb5c3fe2d7))
* **beads:** integrate atomic task evidence contract ([c9aed8a](https://github.com/sase-org/sase/commit/c9aed8a6fca8eeaca467f60234d5a74d05a84800))
* **beads:** present task corroboration across user surfaces ([d63a86b](https://github.com/sase-org/sase/commit/d63a86bfddc4558ddd91c69850f3d35b8ab86d6d))
* **beads:** repair stale event projections ([9fdae1e](https://github.com/sase-org/sase/commit/9fdae1e1e1349d255f0800d3a4cc481d48159c00))
* **beads:** rewrite historical bead references ([f7e1fe2](https://github.com/sase-org/sase/commit/f7e1fe2161e24e208869b1e8c64879ee3495ac94))
* **beads:** show creator attribution links ([2c15257](https://github.com/sase-org/sase/commit/2c152578537e50209de8b6e750d4d179182a5e44))
* **beads:** support shorthand bead ids ([7765a07](https://github.com/sase-org/sase/commit/7765a07c915d1bae5469ad2f43072136f4620ae6))
* **beads:** teach agents to file task follow-ups ([cfeeabc](https://github.com/sase-org/sase/commit/cfeeabc341065b96e91413238bfac374d313bfa7))
* bound and instrument bead store locks ([70c85e0](https://github.com/sase-org/sase/commit/70c85e0125f2c3023588568ddc873cc5aa6ed877))
* **changespec:** add artifact reference support ([f921f42](https://github.com/sase-org/sase/commit/f921f428dba97720bec8b0853fc5e6bcb34f535c))
* **cli:** remove stored prompt rendering surfaces ([1239c5f](https://github.com/sase-org/sase/commit/1239c5f5c834782fa5ef90f5d21e471a0402d22d))
* **cli:** render compact bead rows with glyph-only type cells ([7d4afb3](https://github.com/sase-org/sase/commit/7d4afb3948a3236ea393aeaeb46976ba9e458f67))
* **cli:** wrap bead show prose ([e257d6b](https://github.com/sase-org/sase/commit/e257d6b1b2da21d1b59414fe7fc1214b37aa5659))
* **commit:** add commit subject validation policy ([748b617](https://github.com/sase-org/sase/commit/748b617c0b060a20861331e8b65b6d3725fbcf44))
* **commit:** reject invalid conventional subjects ([8472192](https://github.com/sase-org/sase/commit/84721922edb8209904588698dc3068b09e6a3109))
* **config:** add file hook configuration and listing ([57e41fd](https://github.com/sase-org/sase/commit/57e41fd860155633e75aa73fc8eac831273bbf22))
* **core-time:** add parse_local/format_local display helpers ([2c70516](https://github.com/sase-org/sase/commit/2c70516acaad31563eb4a07866a5a3f424204259))
* derive gate behavior from adapter capabilities ([6e5b360](https://github.com/sase-org/sase/commit/6e5b36028a879f2f86d2678d7d07dde30970ebef))
* expose stored prompt renderings ([e3ca2c1](https://github.com/sase-org/sase/commit/e3ca2c11c53040a67e50010e683f270efc1c624a))
* **file-hooks:** run hooks for committed files ([f40c517](https://github.com/sase-org/sase/commit/f40c517bfc7d0421d2a8df1fabb526b21964278e))
* **gates:** add generic presentation metadata ([d02ab49](https://github.com/sase-org/sase/commit/d02ab49e58e81a1860c2f11f83c5a61c76c94e2a))
* **gates:** add TaskTriage decision workflow ([010fe0f](https://github.com/sase-org/sase/commit/010fe0fc067fd818302a8967197297ef5d7c1b34))
* **gates:** title gate review modal from adapter and show filer ([86a51e1](https://github.com/sase-org/sase/commit/86a51e1d5b2825c402b3d699d3acc51d7e5e41a2))
* **history:** restore single-prompt chat markdown ([376a3b1](https://github.com/sase-org/sase/commit/376a3b1bbcb0dad5cccab0650611c7898aa49f3a))
* **history:** store both prompt renderings in chats ([e6624e3](https://github.com/sase-org/sase/commit/e6624e324e7857a1967757c8b22984ff7d49b4a8))
* improve task triage gate presentation ([63a24a0](https://github.com/sase-org/sase/commit/63a24a025223680adeceac91397ab58313e0fb10))
* **llm_provider:** drive shipped model alias defaults from one YAML file ([f55ce07](https://github.com/sase-org/sase/commit/f55ce07d164d57b1c05d6585b191459adcc9e5e7))
* **llm-provider:** hide fakey from model pickers and %model completion ([e5361f4](https://github.com/sase-org/sase/commit/e5361f4dee7eec736acd8e4f32812f804cb998a1))
* **llm:** add provider-specific coder defaults ([e4c13b3](https://github.com/sase-org/sase/commit/e4c13b3e837b8d8464013cf52194a596a1c4ac9b))
* **llm:** default smartest alias to Opus at max effort ([0d7c351](https://github.com/sase-org/sase/commit/0d7c351e43d258f67ee98c346f41ec246f1f7573))
* **llm:** load balance cheapest alias by default ([6e96ff1](https://github.com/sase-org/sase/commit/6e96ff12fdb14cab6f7ff6cbb7c8074db6efc678))
* **llm:** update phase worker alias defaults ([9bf11ef](https://github.com/sase-org/sase/commit/9bf11efdaa5ca5de8f571fc2227556a00b54089a))
* **memory:** generate Tier 2 bead workflow note ([d6a2cce](https://github.com/sase-org/sase/commit/d6a2cce1f0e7464aa36dd3e22b77b95e57bef298))
* **memory:** retire bundled sase_beads skill source ([642b4f4](https://github.com/sase-org/sase/commit/642b4f490b302311ce5b737ac76d3720f4404f01))
* **notifications:** apply mark actions in bulk ([df5054c](https://github.com/sase-org/sase/commit/df5054c4073357c29ecf644de8f8ddeb7dc60f58))
* **notifications:** expose canonical snooze snapshots ([09517a0](https://github.com/sase-org/sase/commit/09517a0fb011f0922e132d34591c2ec380911c6d))
* **notifications:** order projections by resurface activity ([459ef97](https://github.com/sase-org/sase/commit/459ef9786dd1ff5ef39ea4eb6f556ccf8db3ceae))
* **opencode:** recognize ZHIPU_API_KEY in OpenCode auth checks ([bc359cc](https://github.com/sase-org/sase/commit/bc359cca664cc00070ab4f9bbc2959e9668761e9))
* **prompt-archive:** store rendered prompts and link xprompts ([f578c0a](https://github.com/sase-org/sase/commit/f578c0aa4e1cdd699ce9fb715ce59fcea89cb93e))
* **prompt:** use the canonical prompt archive ([53b1fc0](https://github.com/sase-org/sase/commit/53b1fc0378c8e8b7441ce638abbc17e9af70b3fc))
* queue interactive sidecar publication ([3ac2b09](https://github.com/sase-org/sase/commit/3ac2b097beac842dc02df1edf88704ff87cd351d))
* replace bd/next with task bead workflow ([cf4088f](https://github.com/sase-org/sase/commit/cf4088f751c30827fb016c17d3697bbc02fb6cdc))
* retune cheap model alias defaults ([50c2656](https://github.com/sase-org/sase/commit/50c265692926d8981137834a2146a9e9d9fb160d))
* **sdd:** cross-link plans and archived prompts ([6107515](https://github.com/sase-org/sase/commit/61075153cbf05a43c58725ffd2cae538de85f8aa))
* **sdd:** keep validation green while sidecar publication is pending ([1116bcc](https://github.com/sase-org/sase/commit/1116bccb0a4390e748a4042b9e92bbcb50d991a2))
* **sdd:** show phase and wave counts in epic clan summary ([9d6b40c](https://github.com/sase-org/sase/commit/9d6b40c6c6e512799414bfc1cba098d2f4959fa5))
* **sidecars:** surface publication queue observability ([6719992](https://github.com/sase-org/sase/commit/6719992521adee5f78e8b353ab708315503831be))
* **stats:** report plan and question activity from gates ([6800c3d](https://github.com/sase-org/sase/commit/6800c3d3eff788c7850d06e2619dd79d253c323c))
* support artifacts in plan headers ([20f6735](https://github.com/sase-org/sase/commit/20f673572dcf86d36c3ba4e460cf7e6f32137c84))
* **tribe-panel:** remove description label in tribe headers ([574b776](https://github.com/sase-org/sase/commit/574b7761fa05e69eafca3956d31f57ed27ae7f5c))
* **tui:** add Beads mutation workflows ([eb3433e](https://github.com/sase-org/sase/commit/eb3433ec94119a9765beae732e8b562f0ff0aee7))
* **tui:** add clan slow tool report hints ([6a1afad](https://github.com/sase-org/sase/commit/6a1afad8a7f2cc35b76821ca18f382385fe80f4d))
* **tui:** add file hints to clan member bodies ([ac7a3b4](https://github.com/sase-org/sase/commit/ac7a3b4c4a25133b21dd8f6b27caaf60c774a05f))
* **tui:** add file hints to clan summaries ([dd862b7](https://github.com/sase-org/sase/commit/dd862b7670deba99fd70f41d0a9d0cb567a22ad7))
* **tui:** add structured clan context hints ([cffd22b](https://github.com/sase-org/sase/commit/cffd22be5fdb6da60f0306798e259a1f3f8fdac8))
* **tui:** dedicate Plans pane to plan documents ([4d7b6fa](https://github.com/sase-org/sase/commit/4d7b6fae40375402736182a4c8078a41826f96a9))
* **tui:** nest artifact file tabs ([9f80b41](https://github.com/sase-org/sase/commit/9f80b413627c3a2614bbea4b0a58c97be03546b3))
* **tui:** resolve clan hint paths off-thread ([d1f55ce](https://github.com/sase-org/sase/commit/d1f55cec31a7ce1a97ec0030c8e7c9853cfe4be6))
* **tui:** route notifications through declared panels ([661699f](https://github.com/sase-org/sase/commit/661699f387a830d107f02a45558e121bdfff494c))
* **tui:** show bead notes in agent headers ([cd12442](https://github.com/sase-org/sase/commit/cd124420f4115892a1f569a7ba19df7abefe26a1))
* **tui:** show notification send time in detail pane ([143666b](https://github.com/sase-org/sase/commit/143666ba5caee2ee1d9c66c7161f51bbf9e16fe0))
* **tui:** show published agent page URLs ([c081bb6](https://github.com/sase-org/sase/commit/c081bb6e16fd45a5e5269a5dcb3fac4b3083d22b))
* **tui:** surface task beads in ACE ([f592b43](https://github.com/sase-org/sase/commit/f592b43dfe5d0c6e1e68ab1e71c2124f6d013d2a))
* **var:** support structured output variables ([6f7c560](https://github.com/sase-org/sase/commit/6f7c56043164900af7c80d2fd7899018434828de))
* **xprompt:** add rich show renderer ([d26d663](https://github.com/sase-org/sase/commit/d26d6635febfe1ace3a6d60d07cfe8ba76f5c4d7))
* **xprompt:** add shared highlighting core ([eccca60](https://github.com/sase-org/sase/commit/eccca60200fec18d23d3640202e6ac91b773444b))
* **xprompt:** add show CLI command ([c8211ae](https://github.com/sase-org/sase/commit/c8211ae5cf3e08f0c3d4402ee5b6bdfe6617a0e0))
* **xprompt:** add show definition resolver ([98f2af2](https://github.com/sase-org/sase/commit/98f2af2fd7a012ca2a8f7093bb6ea3e8d31360d3))
* **xprompt:** capture definition provenance at launch ([cb90eaf](https://github.com/sase-org/sase/commit/cb90eaf00a707a32fa7cea009e719df7cdd4cb43))
* **xprompt:** resolve hosted URLs for captured definition provenance ([e309358](https://github.com/sase-org/sase/commit/e30935808ba50079c927c2c54130c4b155b9d0e1))
* **xprompt:** stop writing launch-time provenance JSON ([1a2040e](https://github.com/sase-org/sase/commit/1a2040e73d351ec7c1c280bdc4c4d16dbda10f7e))


### Bug Fixes

* **ace-tui:** repair prompt commit inventory binding and worker lifecycle ([aab4899](https://github.com/sase-org/sase/commit/aab489997eb1c745d34cfda0978089696aed1135))
* **ace-tui:** restore tasks-tab selection for durable-store rows ([f393b91](https://github.com/sase-org/sase/commit/f393b9151dc2f8151f0901628c3c47f1015d1bbd))
* **ace:** resolve clan summary hint targets ([a5aa2e9](https://github.com/sase-org/sase/commit/a5aa2e9c0e426b78910a73bf7e3037e0de8d9450))
* **ace:** restore app help keymap ([fa43d2f](https://github.com/sase-org/sase/commit/fa43d2f46f7a368c015743bd422b8772f5b69f4a))
* **agent-clis:** hide internal providers from CLI management ([1c29afa](https://github.com/sase-org/sase/commit/1c29afae277b55a4bbe584c9f73193d90ef3f1a4))
* **agent-clis:** isolate subprocess temporary files ([fa0f427](https://github.com/sase-org/sase/commit/fa0f427e73cf38a873a1882e4eb9e505089f1a34))
* **agent:** ignore run marker during identity discovery ([14d6622](https://github.com/sase-org/sase/commit/14d66229a4a5cb3247d01653f74064e31b55c715))
* allow family conversion beside hood prefix claims ([7fe068c](https://github.com/sase-org/sase/commit/7fe068cee9708f74ff50395bbc15f6c451fc38ba))
* **artifact:** extend consumption protection coverage ([be94f09](https://github.com/sase-org/sase/commit/be94f098a761cee54e5e4b855374b504b92f6eb8))
* **artifact:** protect artifacts referenced only by beads ([daeb410](https://github.com/sase-org/sase/commit/daeb4109a079c971f654ba72266e16c8a752dfae))
* **artifacts:** mint timestamps in the configured timezone ([eda7c15](https://github.com/sase-org/sase/commit/eda7c1564387abf356e601dd32d86c68b4efedd8))
* **artifacts:** render timestamps in configured timezone ([d4be80d](https://github.com/sase-org/sase/commit/d4be80d3f9a6c96890f6b83c8c4af0a20797f214))
* **axe:** normalize handoff interruptions structurally, not by provider error text ([fcaf211](https://github.com/sase-org/sase/commit/fcaf211326a42faf7337996c4cc3d621afb617a5))
* **bead:** align compact search type column ([d3c2dee](https://github.com/sase-org/sase/commit/d3c2dee7357125d37472964fedfafe687fba4adb))
* **bead:** derive issue prefixes from PROJECT_NAME, not ProjectSpec key ([22e78f7](https://github.com/sase-org/sase/commit/22e78f792c3a5f251d70cf69a991770be1dcb27c))
* **bead:** expose sync helper implementation symbols ([943ffd0](https://github.com/sase-org/sase/commit/943ffd0d3659298d16e29195da06d5d82dfeabea))
* **bead:** force color in prose rendering so --color always beats NO_COLOR ([a7ac9cc](https://github.com/sase-org/sase/commit/a7ac9cc9af0e7e720d4303a7cef934c5e623f829))
* **bead:** restore sase bead ref add/rm dispatch ([4ba3fb4](https://github.com/sase-org/sase/commit/4ba3fb4e5d9780e7c8309c35f395038370451997))
* **bead:** route sase bead create through the attributing handler ([4fd54a9](https://github.com/sase-org/sase/commit/4fd54a96707a0931b3c86a8c3551a2e0fbed0ea5))
* **beads:** repair stale project-key prefixes before minting ([77ef395](https://github.com/sase-org/sase/commit/77ef3953e5c67c8be6247c4de1e2e62c474243a3))
* **beads:** report close mutation outcomes honestly ([5f682e2](https://github.com/sase-org/sase/commit/5f682e2b1b0ebb7fb295c8cffef49ba495c70f8c))
* **beads:** restore pre-alias resolution tests ([a35846f](https://github.com/sase-org/sase/commit/a35846f4cf60ac0da274370698d16340a6c61791))
* **beads:** route deferred close pushes correctly ([e3a898b](https://github.com/sase-org/sase/commit/e3a898b6a32609979d79ce03d31f6dbf0d7dbc16))
* **beads:** stop approved epic archives from dropping their PROMPT link ([6e96dea](https://github.com/sase-org/sase/commit/6e96deaf8fdb94af4e3080a92882f0394d4ded55))
* **beads:** use default priority for task workers ([5022003](https://github.com/sase-org/sase/commit/502200368dd7d2f4762ee8bb5d8fd18b33e2ae88))
* **bead:** wait for sync worker before launch publication ([9162b27](https://github.com/sase-org/sase/commit/9162b27e32fd8971a48daa1902a385f1a13f95f8))
* **commit:** apply conventional subject gate updates ([9a6b203](https://github.com/sase-org/sase/commit/9a6b20390e44b2b2dec6c546d2bf241b174021f4))
* **commit:** write agent commit messages under .sase/ instead of repo root ([ae3c010](https://github.com/sase-org/sase/commit/ae3c0109adf2402e8e8528c9af2ef4dda0438134))
* complete task bead contract cleanup ([c1efe9f](https://github.com/sase-org/sase/commit/c1efe9f939d682405d29c226884100b9154aedfe))
* dedupe notification toasts by activity cursor ([d2d8151](https://github.com/sase-org/sase/commit/d2d8151165ac64ca67e1a4c44fe9feb1cf648ecf))
* **deps:** bump sase-core-rs floor to 0.17.4 for bead_update_many binding ([#269](https://github.com/sase-org/sase/issues/269)) ([650aad0](https://github.com/sase-org/sase/commit/650aad06483e3cac454a29cb34d7ff4743291993))
* **deps:** raise sase-core-rs floor to 0.17.4 for bead_update_many binding ([#270](https://github.com/sase-org/sase/issues/270)) ([d462e97](https://github.com/sase-org/sase/commit/d462e97bbdf23f624c96683a63da56a22617b8e6))
* **dev-update:** guard code swaps during bead work ([4fcaee9](https://github.com/sase-org/sase/commit/4fcaee95a5e543fd6635fc820e64b3cd2776480d))
* **doctor:** de-hardcode shipped model default in phase_worker migration warning ([2d87ba5](https://github.com/sase-org/sase/commit/2d87ba54442343070b2b84087f50c017b87699a0))
* guard configured-timezone timestamp display ([6424082](https://github.com/sase-org/sase/commit/6424082f968b220212dd3656413d076fd1ce9fb0))
* ignore bead mutation holder metadata ([ecc1e90](https://github.com/sase-org/sase/commit/ecc1e901bd49142fcf91a80fa50dcff789752d7c))
* keep epic bead agents at default priority ([8b6f8fd](https://github.com/sase-org/sase/commit/8b6f8fdfe2d3019706f416da0fe886f78b1e7ad4))
* **lint:** remove stale symvision state ([234e817](https://github.com/sase-org/sase/commit/234e8175cd28e7a3f040510f0c68a0f5fba1494b))
* **llm:** refresh Antigravity model catalog ([fe397e3](https://github.com/sase-org/sase/commit/fe397e3630186dd79d8167f87b6f94e732a79cef))
* **llm:** route claude coder default to gpt-5.5 ([a39ca1f](https://github.com/sase-org/sase/commit/a39ca1f9d4cb3c5c2579ff7075dbc9a4007ab28e))
* **llm:** route provider coder aliases through shared coder default ([aace448](https://github.com/sase-org/sase/commit/aace4488ded58da60877f75972abd48bd2156c7c))
* **memory:** scope generated bead memory note to project repos only ([f0e1a25](https://github.com/sase-org/sase/commit/f0e1a25e6ee5be14ba7e94439610d64e261d2500))
* preserve provider display names in model completions ([9562e53](https://github.com/sase-org/sase/commit/9562e53663e551795eadbc48a8873f8040286614))
* **prompt-archive:** publish archived prompt bodies verbatim ([92b31a1](https://github.com/sase-org/sase/commit/92b31a1b444277ab1a8cb488a1ad4fd28ee0c09e))
* **prompt:** search canonical authored prompt text ([09bedce](https://github.com/sase-org/sase/commit/09bedcef00edfc730851c3178c06eb320b78eb77))
* **prompts:** make archive migration durable ([7ba7ce6](https://github.com/sase-org/sase/commit/7ba7ce664afec6308a65b998c47e6e72c444c8e2))
* render timestamps in configured timezone ([c449ce2](https://github.com/sase-org/sase/commit/c449ce27cf0cd18b0f5a78f80f8742963a7c97f3))
* **sdd:** stop approved epic plans from losing their PROMPT link ([cf2aba8](https://github.com/sase-org/sase/commit/cf2aba89a9b641bb216c8e9f1c1493cdad316448))
* serialize epic approvals before store discovery ([186fd20](https://github.com/sase-org/sase/commit/186fd201084fa785b3746ae133383cb2bb00286b))
* **stats:** expose runner occupancy diagnostics ([5143cb9](https://github.com/sase-org/sase/commit/5143cb9813d129850bbea0ec52246238bc31f696))
* **tests:** drain clipboard tasks between palette key presses ([bba5aa1](https://github.com/sase-org/sase/commit/bba5aa19dc5dc0a27426e8bd09a9a41fa1edc8df))
* **tribe-panel:** correct description wrap expectations in tests ([7e9527c](https://github.com/sase-org/sase/commit/7e9527c7af8f2e969ce8f464a56ab61d566e20c4))
* **tui:** ignore file hints inside HTTP URLs ([3f5f64b](https://github.com/sase-org/sase/commit/3f5f64b0f587d851c5fd0d873ed7a46f424bdb0e))
* **tui:** preserve admin center selection across rebuilds ([976d838](https://github.com/sase-org/sase/commit/976d838db5d9b9ef8460e279f2088d18a2077ef6))
* **tui:** project plan-family status onto promoted family roots ([1273c78](https://github.com/sase-org/sase/commit/1273c78a9174a94dd544bf1655826f597a8e52ac))
* **tui:** render panel timestamps in configured timezone ([f0e562b](https://github.com/sase-org/sase/commit/f0e562bda9965cf42ba6d8c9dbb152a5a4ed2fd7))
* update vendored pyscripts validator ([93dfb63](https://github.com/sase-org/sase/commit/93dfb63587ece702ffde02b752cfd293da7eb2d8))
* **validation:** skip unavailable prompt archive context ([404fac3](https://github.com/sase-org/sase/commit/404fac3b5dfcd4bd069a6f94a1a1f37f1435cffc))


### Performance Improvements

* **bead:** resolve detail from one core snapshot ([7a66461](https://github.com/sase-org/sase/commit/7a66461b98890f66413bfbc67bc7a6d90b2c736f))
* bound agent registry scans during association builds ([c6bed82](https://github.com/sase-org/sase/commit/c6bed82365b3fd316637c9bc68aa5ecc2479c7ad))
* **cli:** build only the invoked command parser ([e5208ec](https://github.com/sase-org/sase/commit/e5208ec977cbe6974ccfa32526f4197b697caf1e))
* **repo:** cache inventory identity derivations ([25e706f](https://github.com/sase-org/sase/commit/25e706f76b593d8e3147c86fdd01cd3d457ae4b0))
* snapshot agent registry during association builds ([c82eff9](https://github.com/sase-org/sase/commit/c82eff9a0234d037c8057c96e41fa9af1b530f28))


### Reverts

* **agent-names:** remove historical identity migration ([f2cd75b](https://github.com/sase-org/sase/commit/f2cd75bc55a1c6c786961572f4703605ae6d91a5))
* **beads:** remove historical reference rewriting ([850cb91](https://github.com/sase-org/sase/commit/850cb910ee9f944e6c5871187581758cdba9c9d3))
* **beads:** remove prefix migration facade ([e433d38](https://github.com/sase-org/sase/commit/e433d388575fa71423dd6c15b3264e8a9572636b))


### Documentation

* **ace:** document clan view hints and cover the clan `v` flow ([624db9a](https://github.com/sase-org/sase/commit/624db9a9f7baf4545451cd460a026684198a34f1))
* **artifact:** document the artifact store lifecycle ([38e3b72](https://github.com/sase-org/sase/commit/38e3b725a75b9bc16d888cfeedc0b96c6fd21b59))
* clarify archived prompt representations ([fe0d71e](https://github.com/sase-org/sase/commit/fe0d71e09fc1ce0984d67df49917c8e2055c0b4b))
* **commit:** document the conventional subject gate ([2f565d0](https://github.com/sase-org/sase/commit/2f565d0be3ba54489a50982aab93964990ec1df0))
* correct task bead workflow guidance ([76e9ab4](https://github.com/sase-org/sase/commit/76e9ab408cda6f9aff104217e57ada008246763c))
* document agents-sidecar prompt archives ([527e645](https://github.com/sase-org/sase/commit/527e6458225baeb0e45feb6e63e2b24900eeb3a2))
* document artifact reference persistence ([84d47aa](https://github.com/sase-org/sase/commit/84d47aa78bf75e88486e4ace484d782b74139fe6))
* document commit reference completion ([dfab05f](https://github.com/sase-org/sase/commit/dfab05f8c81d13b851aa8669ba06a80b2f3cf302))
* **llms:** fix source-layout table misattribution for alias name constants ([c14e8a4](https://github.com/sase-org/sase/commit/c14e8a4484577cfea934cb7069192cf4f220aa11))
* **llms:** generate model alias defaults table ([568a965](https://github.com/sase-org/sase/commit/568a9652403973d126b3e2f16136a7c811738b0e))
* **memory:** document bulk bead update semantics ([33c6311](https://github.com/sase-org/sase/commit/33c63112c911958e5a3c6111eb4f01caeb945794))
* refresh current user workflows ([e93ab3d](https://github.com/sase-org/sase/commit/e93ab3db05a1bf5ff5dc89e4724ad92fffd89f19))
* refresh documentation to match repository behavior since e93ab3db0 ([2e9608e](https://github.com/sase-org/sase/commit/2e9608e7bb2ef85e8208ab836f50c00618fc6f2a))
* refresh guidance for current prompt and ACE behavior ([39ef28e](https://github.com/sase-org/sase/commit/39ef28e0186afbd437cace47a433d279d24c6472))
* update prompt archive docs and plans map ([af0a6b8](https://github.com/sase-org/sase/commit/af0a6b818f6b53102d81b5623079f304b253c7f4))

## [0.14.0](https://github.com/sase-org/sase/compare/v0.13.3...v0.14.0) (2026-07-30)


### ⚠ BREAKING CHANGES

* Python ChangeSpec wire records now use schema version 5 and include a refs array.
* **artifacts:** sase artifact create now keeps its source file by default. Pass --move to retain the previous source-removal behavior.

### Features

* **docs:** document the agents-sidecar prompt and artifact archive
* **ace:** add artifact file copy actions ([fec7898](https://github.com/sase-org/sase/commit/fec7898b284d148c7c3ac2ba168ca8b6f24dfa3e))
* **ace:** add artifact file copy representations ([132bd79](https://github.com/sase-org/sase/commit/132bd79c77d514bc109d3fecf0a6d2a4a0c0bc02))
* **ace:** add artifact file detail panel ([f0c803a](https://github.com/sase-org/sase/commit/f0c803af859c627c92f2e52e02f7e1628d71c4b4))
* **ace:** add artifact file filtering ([842723f](https://github.com/sase-org/sase/commit/842723f6f6db058f7d301d732e61bb24aaf052f5))
* **ace:** add artifact file open actions ([f5df5e1](https://github.com/sase-org/sase/commit/f5df5e12221c5da96fdd9f542ce481ee2f327914))
* **ace:** add artifact files list browsing ([2edfc8b](https://github.com/sase-org/sase/commit/2edfc8b7071b29aa44e8d58338184c1887c53ffe))
* **ace:** add artifact reference prompt completion ([e55aab9](https://github.com/sase-org/sase/commit/e55aab9c92f73f5f902fa58ee39641da6a78686a))
* **ace:** add bead and agent completion catalogs ([3173dae](https://github.com/sase-org/sase/commit/3173dae12003cace00cb98563e8c134398bd87fc))
* **ace:** add contextual Copy as palette ([3da9140](https://github.com/sase-org/sase/commit/3da9140b4968f590f84ace1db91f21c565746381))
* **ace:** add numbered Statistics subtabs ([216d027](https://github.com/sase-org/sase/commit/216d027d8ba439f6156b45557750e292c029311b))
* **ace:** add paste-ready copy representations ([cf844c3](https://github.com/sase-org/sase/commit/cf844c3e5d574d7c8898a73fd36cba686c17a6ad))
* **ace:** add source search to preview reader ([cc7a347](https://github.com/sase-org/sase/commit/cc7a347c3a9a15af4154117acb33ce27384e48cd))
* **ace:** allow alt braces before punctuation ([a79dad1](https://github.com/sase-org/sase/commit/a79dad1639a7a54406a4c185fdc15be00d8e8628))
* **ace:** complete Files copy-as palette ([86fb630](https://github.com/sase-org/sase/commit/86fb630bb8315f86895a48ac4a9be1a9243e8612))
* **ace:** copy artifact references from artifact tabs ([d16fe1d](https://github.com/sase-org/sase/commit/d16fe1dcd9abe1bcc0e6b44af0bc98e2b0ad5788))
* **ace:** copy bead and agent references ([751f469](https://github.com/sase-org/sase/commit/751f4695712a5cc7d6e68d6c30b930157e6cda84))
* **ace:** finalize xprompt statistics contract ([d0b2ed9](https://github.com/sase-org/sase/commit/d0b2ed97cde8d15ab71afa62d7be06da1cb816f1))
* **ace:** focus statistics on an xprompt ([c81eb5d](https://github.com/sase-org/sase/commit/c81eb5d429127ee80cf0098c0e20932b74cc0ffa))
* **ace:** gate artifact file completion rows ([9ba92b0](https://github.com/sase-org/sase/commit/9ba92b09a7cacd192f59ccc0756970d8ca67526d))
* **ace:** render plan previews as markdown ([afad2e6](https://github.com/sase-org/sase/commit/afad2e6ca1b5bce83e1facb22f584c137346bf40))
* **ace:** turn preview modal into artifact reader ([a4d026b](https://github.com/sase-org/sase/commit/a4d026ba78e0406fa2f13701d2c56afbfd4b72cc))
* **ace:** unify clipboard delivery ([77ec879](https://github.com/sase-org/sase/commit/77ec8798e0c6f435e3b32a4f24e161ce268fb81f))
* add authorship-aware artifact capture policy ([d309f95](https://github.com/sase-org/sase/commit/d309f95370d8ecd8bda05e89b3e80057d3d6ca94))
* **agent:** carry swarm provenance through launches ([0683114](https://github.com/sase-org/sase/commit/068311411b65de0931d755cdfc88e66114a918b3))
* **agents-sync:** attribute commit history to agent lanes ([eefd432](https://github.com/sase-org/sase/commit/eefd432bab1b6562947545e0f1c52a67ea48c5a3))
* **agents-sync:** preserve family lane commits ([59b0ecd](https://github.com/sase-org/sase/commit/59b0ecd227a23891e7c6ed0eb588376a9a3b7135))
* **agents:** add shared agent-lane vocabulary ([c537f7e](https://github.com/sase-org/sase/commit/c537f7e03de7315d07f041def613cbba0bcde354))
* **agents:** anchor sidecar publication requests on the agent lane ([1cd59c3](https://github.com/sase-org/sase/commit/1cd59c3b11e16835ab23dc030f8234e871bb194e))
* **artifact-refs:** add bead and agent resolution context ([85b5b64](https://github.com/sase-org/sase/commit/85b5b642167aa400538f77121546a705f93fbe9f))
* **artifact:** add pruning and trash lifecycle ([be4c199](https://github.com/sase-org/sase/commit/be4c19969fc6ce227ee4e474d9952722ea172b02))
* **artifact:** add store lifecycle statistics ([18c01a1](https://github.com/sase-org/sase/commit/18c01a15257c3cb5b3d8540b65a91eab69e5e065))
* **artifact:** expose consumption read surfaces ([a4880ce](https://github.com/sase-org/sase/commit/a4880ce321df4a9afdf1a2be5ce86eed8a5860fe))
* **artifacts:** add artifact reference facade ([9988b61](https://github.com/sase-org/sase/commit/9988b6161c9b47b3a657b49981fb11b1bf3e0c98))
* **artifacts:** add opt-in retention policy ([6999e31](https://github.com/sase-org/sase/commit/6999e31a3dd9b90e117ae36efe30a4a113fccdb9))
* **artifacts:** copy created artifacts by default ([e0b1ca4](https://github.com/sase-org/sase/commit/e0b1ca4450b89a02b8f2bae3b019eddc649e1976))
* **artifacts:** expand references during prompt launch ([46b40c5](https://github.com/sase-org/sase/commit/46b40c5f6610b2ccd97d0e315b853a6563b2ab1a))
* **artifacts:** expose VCS-backed files across ACE ([03663eb](https://github.com/sase-org/sase/commit/03663eb8455b04110a43e6dcaed21389be8a34bb))
* **artifacts:** materialize VCS-backed files on demand ([c9edec5](https://github.com/sase-org/sase/commit/c9edec56145a050d89ed18911c27f90831e7a9dc))
* **artifacts:** wire VCS-backed default capture ([94daa1e](https://github.com/sase-org/sase/commit/94daa1ebdcff2d3adf11c24599d04807f8a5a03a))
* **bead-pages:** associate commits across project repositories ([8e7120e](https://github.com/sase-org/sase/commit/8e7120ebe048dca1737c71592100244c8a52dc93))
* **bead-pages:** guard against misattributed commit links ([f62e8cd](https://github.com/sase-org/sase/commit/f62e8cd01713c934cb6e5fcf0374667805a78ceb))
* **bead:** close selected epic phases ([1f0296a](https://github.com/sase-org/sase/commit/1f0296ade1a22ac55dbd93d410f0247e6befba3a))
* **bead:** integrate persistent artifact references ([4aee2f4](https://github.com/sase-org/sase/commit/4aee2f49fecb256d4ed5a06b23c0f401f94b3da8))
* **cli:** add artifact read commands ([30e2ed3](https://github.com/sase-org/sase/commit/30e2ed37ed28cc2dab894e69419d206fec79ce05))
* **editor:** materialize artifact reference catalog for LSP ([3f6e4ea](https://github.com/sase-org/sase/commit/3f6e4ea81a0ea13d5f0427358df02aa0c5cdde0a))
* enrich artifact file records ([f39b0c4](https://github.com/sase-org/sase/commit/f39b0c405616accf8e4431c34461bddad8006a22))
* record artifact consumption during prompt expansion ([3a0a92d](https://github.com/sase-org/sase/commit/3a0a92d84cffe20b3f1a9e7f57f4eb57ecb190f9))
* **sdd:** add checkout anchor resolver ([ad0f038](https://github.com/sase-org/sase/commit/ad0f038a05e9b840247a5c97822c2ee3ebb05830))
* show repository names in commit tables ([63d0ca5](https://github.com/sase-org/sase/commit/63d0ca504d48b8daed6702e38d79443d77af44cb))
* **stats:** add XPrompt statistics view models ([6d99736](https://github.com/sase-org/sase/commit/6d99736516c426d900faa813f2584336fb3cffdc))
* support ChangeSpec reference lists ([2433d6b](https://github.com/sase-org/sase/commit/2433d6bb83edfddbd0b2b3d2e1974906faea3560))
* support entity artifact references in prompt paths ([278e169](https://github.com/sase-org/sase/commit/278e16952b95de02025a6f21f438db530362bc7d))
* track xprompt swarm provenance on expansion records ([3054ea5](https://github.com/sase-org/sase/commit/3054ea56f2fbaa4709c02bfad2124c7636552c46))
* **tui:** add xprompt statistics view ([7ddfbb1](https://github.com/sase-org/sase/commit/7ddfbb16a13bd0771d1bf3d47fc19beee3a31086))
* **tui:** highlight artifact references in prompts ([de57f5a](https://github.com/sase-org/sase/commit/de57f5a5f3e8563b48400f2843737ef7b4c8b33b))
* **tui:** highlight fuzzy artifact reference matches ([b6b51f2](https://github.com/sase-org/sase/commit/b6b51f2399df191dc5a926a26a3040a74bda3b03))
* **tui:** render grouped @ reference completions ([fedea3a](https://github.com/sase-org/sase/commit/fedea3aa9b28d063add5edc2e83fbe108d0bae19))
* **tui:** render the swarm xprompt kind ([e62f9a6](https://github.com/sase-org/sase/commit/e62f9a6ee5bbe1072e517ca3adae4265e8479033))
* **tui:** scaffold artifacts files tab ([49e6b4c](https://github.com/sase-org/sase/commit/49e6b4cd17708195e8843d3806c98551f3846244))
* **tui:** unify @ reference completion menu ([9eb1f5d](https://github.com/sase-org/sase/commit/9eb1f5d29e4182d3a41049ec67e80ca2907b7d93))
* **xprompts:** capture swarm launch provenance ([01f9912](https://github.com/sase-org/sase/commit/01f9912ce6ef3042d2761de1d40aba7d602c29b4))
* **xprompts:** require sase-core-rs with the swarm xprompt kind ([6e35387](https://github.com/sase-org/sase/commit/6e35387e2ba5564c134ccc7ce1b84c5cd5957850))


### Bug Fixes

* **ace:** acknowledge unread agents on panel entry ([64ffecf](https://github.com/sase-org/sase/commit/64ffecf887426a28d64bb635c6b93ddae709a614))
* **ace:** align Files path preview with what the copy yields ([8fa0f57](https://github.com/sase-org/sase/commit/8fa0f573a6f0895d263598b7c588e9774c4aa142))
* **ace:** keep completion panel rows within budget ([53b3496](https://github.com/sase-org/sase/commit/53b34965f1cf960e92935ca1ec999ff9c24ec4f7))
* **ace:** mirror launch-boundary xprompt usage in the Python scan wire ([f35c4ce](https://github.com/sase-org/sase/commit/f35c4ce33185d857fac08c0b80b6e93ef4a2ea50))
* **ace:** stabilize prompt input and visual waits ([0a7282f](https://github.com/sase-org/sase/commit/0a7282f20787c94e85c57319d33a6dfbd9f2f909))
* **agents:** match SASE_AGENT commit tags by lane ([c407b3f](https://github.com/sase-org/sase/commit/c407b3f39e21af5c906eac128752474087d601e8))
* anchor bead page publication on primary checkout ([5ba1f08](https://github.com/sase-org/sase/commit/5ba1f08d0262d14300f295b60b8fee2df3866d50))
* **artifact:** protect consumed files from retention ([d6eb412](https://github.com/sase-org/sase/commit/d6eb4127138b071e02e179b4cd8bf0c1da7c9948))
* **changelog:** enforce release-please ownership ([619de09](https://github.com/sase-org/sase/commit/619de093a7e9f9cb86a05042fb402f2710039996))
* normalize agent associations by lane ([78522a3](https://github.com/sase-org/sase/commit/78522a318c48a33c3622d05b1885a8d045cbbbe0))
* resolve agent links through checkout anchors ([f1289a1](https://github.com/sase-org/sase/commit/f1289a124ba4e94478b2ea0f973344c8a96ebc46))
* resolve artifact entities for workspace projects ([a78894e](https://github.com/sase-org/sase/commit/a78894e7c409ce576b873af1526570b71d367cce))
* resolve clipboard lint and test flake ([01ac81a](https://github.com/sase-org/sase/commit/01ac81a0bd90b28cf38496bbe58bd1e55d7da64e))
* **sdd:** project canonical plan header links ([4866ece](https://github.com/sase-org/sase/commit/4866ece4a6dca7bc148f10323b5ce418f145729d))
* tag family agent commits by lane ([5f94aae](https://github.com/sase-org/sase/commit/5f94aae4009ad5f260446a26d0f4d8e0c3f47e4e))
* **tui:** load artifact catalog from target project ([03739dc](https://github.com/sase-org/sase/commit/03739dcecdc357d73dba1e83c3edce0b4309a58d))
* **tui:** show full prompt input values ([07aebb2](https://github.com/sase-org/sase/commit/07aebb2f956550d47051b7d42f41d1642369dfff))


### Performance Improvements

* **artifact-refs:** cache bounded payload catalogs ([cbe3d21](https://github.com/sase-org/sase/commit/cbe3d214af47a9e645bfac725cd64960f337409c))
* **tui:** warm prompt path inventory off keystrokes ([dc3462d](https://github.com/sase-org/sase/commit/dc3462d484a7cccabe4173a9182cf12779f2afdd))
* warm artifact completion through Rust query ([af42951](https://github.com/sase-org/sase/commit/af42951798753ef28a2c73e75bcbef1780dbfb83))


### Documentation

* **ace:** document Files pane and add PNG snapshot coverage ([7994afa](https://github.com/sase-org/sase/commit/7994afadcfcc49a1fb51045f136b900c31bb5a76))
* **artifacts:** document artifact consumption ledger ([0d01edb](https://github.com/sase-org/sase/commit/0d01edb911a117c69515ba1947c8d0f904e3c458))
* **artifacts:** document VCS-backed artifact files ([658e576](https://github.com/sase-org/sase/commit/658e57696301cdab8119f77ef0ec1cd4fda16037))
* clarify artifact reference handoffs ([a3130df](https://github.com/sase-org/sase/commit/a3130df52c0bff060db58bb4468d4a0ef82925f2))
* correct artifact handoff and Rust boundary guidance ([7164ac9](https://github.com/sase-org/sase/commit/7164ac9e9cb71ac17d5431d166a1f36b5b312f3c))
* correct artifact-reference completion reachability claims ([5ff7b8a](https://github.com/sase-org/sase/commit/5ff7b8ab899d014b5f8d4d2be7af6fe0a865213a))
* describe lane-scoped commit provenance ([b030a3b](https://github.com/sase-org/sase/commit/b030a3b91085af677d76799b1d112185e6a5b692))
* document bead and agent artifact refs ([34b2f7f](https://github.com/sase-org/sase/commit/34b2f7f2fdb1038d2c0ff3b82300a9b199b34732))
* document fuzzy artifact reference completion ([43c5562](https://github.com/sase-org/sase/commit/43c55620fd790c7390e743b203c6fcef6800f825))
* document grouped at-reference completion ([9d8a700](https://github.com/sase-org/sase/commit/9d8a70048e5aabeb5c594d1d50e28ba7f36fb84e))
* document the sase artifact read commands ([c40aa7f](https://github.com/sase-org/sase/commit/c40aa7f9f5b755223e54469ee31693edc24d46f7))
* document the ViewReport notification action ([7396862](https://github.com/sase-org/sase/commit/7396862437c034428ca25b4244beb4f0f92d325b))
* **editor:** document artifact semantic highlighting ([a0ca459](https://github.com/sase-org/sase/commit/a0ca459ea1c0e9b4b938df8e42bcb1b0ba33d51d))
* **memory:** Remove 'Agents-Tab Nesting' glossary entry ([6394252](https://github.com/sase-org/sase/commit/63942523cad5e016afb6da5df711b6b481db12a5))

## [0.13.3](https://github.com/sase-org/sase/compare/v0.13.2...v0.13.3) (2026-07-29)


### Features

* **ace:** complete the context-aware Copy as palette across Artifacts panes
* **ace:** add file-kind representations to the artifact-files Copy as palette
* **ace:** add paste-ready link and metadata JSON copy representations
* **ace:** add copy mode to artifact sub-tabs ([7d41d17](https://github.com/sase-org/sase/commit/7d41d17a02a44aea76dbe7f19d800bb24d0889c9))
* **ace:** browse all document sidecars ([880c9c8](https://github.com/sase-org/sase/commit/880c9c891757ac2c1e3a29e6fc98f3ef2b056c31))
* **ace:** delete persistent completion entries ([1054f3b](https://github.com/sase-org/sase/commit/1054f3b79dc1f8b71e8f5b2913f18f3b0a90a699))
* **ace:** link epic summaries to hosted bead pages ([f36f37d](https://github.com/sase-org/sase/commit/f36f37d3ceb5154e1b23602f5ce50ed44eebb52d))
* **ace:** raise history word completion default ([4ee5cd0](https://github.com/sase-org/sase/commit/4ee5cd092b45fe813c6e359f04f9248f8ff71c6a))
* **ace:** support marks across artifact panes ([d867a44](https://github.com/sase-org/sase/commit/d867a44ff21343d9a193f9480c46435f881ef5fd))
* **agent:** expose keyed agent-name markers in Python ([79be1d5](https://github.com/sase-org/sase/commit/79be1d53a316d326790a9421435edf2942481fd9))
* **agent:** resolve keyed name markers at launch ([6209176](https://github.com/sase-org/sase/commit/6209176ae2b38de2c5a4fd5bdf18909d647b2619))
* **axe:** render structured chop result reports ([bc501e5](https://github.com/sase-org/sase/commit/bc501e595b0ee0e09d915daf68b7528b1bc50a84))
* **chops:** add typed report builder ([5885890](https://github.com/sase-org/sase/commit/58858901b857cfb9b3831cb61bb8c00e1bfbfd78))
* enrich model completion alias metadata ([e55e18b](https://github.com/sase-org/sase/commit/e55e18b94f132b52eb0badf6440d49a849ad717d))
* **notifications:** add generic report action contract ([73cc28b](https://github.com/sase-org/sase/commit/73cc28b7c5e6df26486971d62e2a4ac55debcf26))
* **plan-search:** support generic document sidecar roles ([5f554c3](https://github.com/sase-org/sase/commit/5f554c3ea4112ef6e472ef5eced04978776298d5))
* qualify keyed markers per xprompt invocation ([62a6ba6](https://github.com/sase-org/sase/commit/62a6ba6f7ad25c7e601ea94525b7cde3a9128e25))
* **sdd:** route document sidecars through role registry ([107904b](https://github.com/sase-org/sase/commit/107904b6bea97c5d036921b2fbbc7ee92e7ceb0e))
* **sdd:** support generic sidecar roles ([70a22c3](https://github.com/sase-org/sase/commit/70a22c347e617988e3a25b62975ab12837ea4444))
* **tui:** add notification report viewer ([1a4ad18](https://github.com/sase-org/sase/commit/1a4ad1828148b7ae17fd9eaca457c82793224246))
* **tui:** enrich model completion rows ([c5d2e1a](https://github.com/sase-org/sase/commit/c5d2e1a2cbec42eb6903c2ae4069a8cda792692d))
* **tui:** show tribe panel entry target ([2110954](https://github.com/sase-org/sase/commit/2110954eb1d6833a03228298d5716681d484980a))


### Bug Fixes

* **ace:** anchor artifact-file path copy ([69d403c](https://github.com/sase-org/sase/commit/69d403c4c7f17f665cccaffd52dc910be8177c99))
* **ace:** exit populated bullets with ctrl+j ([3463978](https://github.com/sase-org/sase/commit/3463978fb3b571b5770eae676279ded54b39f780))
* **ace:** mark handed-off root questions answered ([e7e4121](https://github.com/sase-org/sase/commit/e7e41216496356c24fa1268ca4fd4e4d67c02216))
* **ace:** remove PDF activity from agent rows ([7e20cd2](https://github.com/sase-org/sase/commit/7e20cd22e847c12fc6e435e6da4003e9d054f358))
* **ace:** restore prompt-local placeholder precedence ([1e44e03](https://github.com/sase-org/sase/commit/1e44e0367cdc1fa4fbf81b9dde350de8c45a8103))
* **ace:** safely dump text artifact fallback ([02e8384](https://github.com/sase-org/sase/commit/02e83845b1ef0fa7e173915a1a010fe27cfa047a))
* **ace:** strip prompt bullet markers on join ([a813226](https://github.com/sase-org/sase/commit/a8132265be0d7e27f93695c6ad3da8d3191ec217))
* **config:** initialize chezmoi machine overlays safely ([9180a1f](https://github.com/sase-org/sase/commit/9180a1fd67ae9b32231153fe65a2378fb179733c))
* harden task ownership and temporary cleanup ([#260](https://github.com/sase-org/sase/issues/260)) ([dfd3c48](https://github.com/sase-org/sase/commit/dfd3c48ab6390e62726d40bebe91cc5b306b9b26))
* keep epic page labels inline with URLs ([13b8aab](https://github.com/sase-org/sase/commit/13b8aab3687aefc453a9cdf7681572a24ed91844))
* keep leading model aliases in completion context ([6405e40](https://github.com/sase-org/sase/commit/6405e40eeb57d97909c601d5bc4764b61dae5f8b))
* preserve epic bead page URLs ([9e5eadc](https://github.com/sase-org/sase/commit/9e5eadc6b364d218571ea1cbde82f48d72f3d082))
* report lane counts in cleanup confirmations ([65732cb](https://github.com/sase-org/sase/commit/65732cb3b621319e012b44905d7bf50722f20e53))


### Documentation

* **ace:** document the %model alias completion rows ([fe53df8](https://github.com/sase-org/sase/commit/fe53df885faf473a7ec5e459258e35764e6f8049))
* document keyed xprompt markers ([0272356](https://github.com/sase-org/sase/commit/0272356a5df3070960e1634eae673524fe3d0bc0))

## [0.13.2](https://github.com/sase-org/sase/compare/v0.13.1...v0.13.2) (2026-07-29)


### Documentation

* correct refreshed workflow guidance ([6fcf391](https://github.com/sase-org/sase/commit/6fcf3913de7dd251f3280bf6ae210beca0ecf073))
* refresh current user workflows ([791dec5](https://github.com/sase-org/sase/commit/791dec5ca0fe40d303ab1e409ca61cb1665b83c3))

## [0.13.1](https://github.com/sase-org/sase/compare/v0.13.0...v0.13.1) (2026-07-29)


### Features

* **beads:** preassign epic work before launch ([1943e18](https://github.com/sase-org/sase/commit/1943e18a74f5f2ca3731dd051e68837574ea1c1e))


### Bug Fixes

* **ace:** finish tribe wait integration ([0b3d16c](https://github.com/sase-org/sase/commit/0b3d16ce40b7b0d20aa504d748c4147d3dfc9967))
* **ace:** render explicit waits for queued agents ([212472e](https://github.com/sase-org/sase/commit/212472e3acc6c84d639c269c8110000bf1cfa49a))
* **beads:** land the sidecar commit-consolidation epic ([4f08f4f](https://github.com/sase-org/sase/commit/4f08f4f1b1cbbc9221017ac14f67cad5bf938446))
* **ci:** stabilize full matrix isolation ([887999f](https://github.com/sase-org/sase/commit/887999fb5d0c7acd0ca0a232e9a98f33d1fcc182))

## [0.13.0](https://github.com/sase-org/sase/compare/v0.12.0...v0.13.0) (2026-07-28)


### ⚠ BREAKING CHANGES

* **sdd:** Parent plan associations are now written in the PARENT header section instead of the legacy parent frontmatter field.

### Features

* **ace:** add foldable slow tool call details ([e73040a](https://github.com/sase-org/sase/commit/e73040accf00f09ec3d7a0dbc6657114aa159805))
* **ace:** add project facet to commits filters ([fc72269](https://github.com/sase-org/sase/commit/fc72269b639c93cc29cd617d5b3dd3da4d91cd3d))
* **ace:** display tribe wait bindings ([ed04c42](https://github.com/sase-org/sase/commit/ed04c42f239002a2f682ca9dc0761442a140cf4c))
* **ace:** keep family conversations fully visible ([71942fe](https://github.com/sase-org/sase/commit/71942fe16dacc0fd1ea1819ef53b09bdd000144a))
* **ace:** render wait fields as responsive lanes ([61013b2](https://github.com/sase-org/sase/commit/61013b22957ca7c8c35c0bd93be4c2a10fc59c15))
* **ace:** show phase titles in BEAD context ([4dcb779](https://github.com/sase-org/sase/commit/4dcb77960eb8484913c531cd53e64914f3231f42))
* add linked bead commit footer tags (sase-ai.2) ([4f2694c](https://github.com/sase-org/sase/commit/4f2694c9211b289b0dc8f48622fd3334975a2675))
* add snapshot-driven tribe wait binding resolver ([21e7527](https://github.com/sase-org/sase/commit/21e75272f628e4ce84bfe55453f2cb5fe55950e4))
* adopt bead state into dedicated sidecar (sase-a8.8) ([2a795b0](https://github.com/sase-org/sase/commit/2a795b049c56283d2e55be8d6abfaaafbb89cf39))
* **agents-sync:** add lane neighbor sections (sase-a9.4) ([f9064d7](https://github.com/sase-org/sase/commit/f9064d7630ca8b542f2d01323cc81ba3e3a380d6))
* **agents-sync:** publish linked commit artifacts (sase-a9.2) ([11ddd27](https://github.com/sase-org/sase/commit/11ddd277631aa24521c24e4d8d484d904a704e54))
* **agents-sync:** publish output variables (sase-a9.3) ([33b57c3](https://github.com/sase-org/sase/commit/33b57c3709b688730e05da2ef0dda74534815c86))
* **agents-sync:** stabilize sidecar page anatomy (sase-a9.5) ([9a7fb3f](https://github.com/sase-org/sase/commit/9a7fb3fbe157c7c5e87bbdb35656ef0a5f18ebdd))
* **agents-sync:** surface retired publication requests to operators (sase-ah.3) ([ee5938a](https://github.com/sase-org/sase/commit/ee5938a20b9a42b247a73601c2accc3d5d984504))
* **agents:** add page breadcrumbs and golden refresh (sase-a9.1) ([dbddc16](https://github.com/sase-org/sase/commit/dbddc16c12396524ab7dec8c81a1fa1e33019d53))
* **agents:** classify all runner-slot waiters as queued ([d8c2f50](https://github.com/sase-org/sase/commit/d8c2f5019f58e957b34e124f735899dcadc3a307))
* **axe:** gate lumberjack launches by runner capacity (sase-af.2) ([bd630ec](https://github.com/sase-org/sase/commit/bd630ec7316770881d33fb16b8b822e9a2a25948))
* **bead-pages:** render deterministic bead pages (sase-ai.4) ([6e15f0d](https://github.com/sase-org/sase/commit/6e15f0dc06c87b9f09241f675f81057d4975a70b))
* **beads:** add bead page refresh commands ([4b9e313](https://github.com/sase-org/sase/commit/4b9e3131ae6f5c5f219e7a471fa80d8dd194d2fd))
* **beads:** close with verification notes ([c1272d1](https://github.com/sase-org/sase/commit/c1272d19d702892d26240b50e8b518a3c142a300))
* **bead:** show hosted page URLs in bead detail ([88a317a](https://github.com/sase-org/sase/commit/88a317a87684772c5c9384ee6f8a8f9a53ad21ae))
* **beads:** materialize split sidecar on demand (sase-a8.7) ([73a75f9](https://github.com/sase-org/sase/commit/73a75f94d4370b0ba582bccfa025f45839f4976f))
* **beads:** support repository-root bead stores (sase-a8.5) ([5cf149c](https://github.com/sase-org/sase/commit/5cf149c1f5c2a914c1df0a98a63bd7d02fad5b81))
* **cli:** support multiline output variable values ([d5e1017](https://github.com/sase-org/sase/commit/d5e10175dfcc58a1d1df0e9b1800f5dcc1b87fa2))
* illustrate agents sidecar lifecycle ([d4198f1](https://github.com/sase-org/sase/commit/d4198f1cc9b1e87b361fd80b6e0f99c94c5cec27))
* **plan:** add bulk provenance link refresh (sase-ag.5) ([ca29de3](https://github.com/sase-org/sase/commit/ca29de3befeea34321826e749ffc1e689a8a8b5e))
* **plan:** project bead links into plan headers (sase-ai.8) ([ab1c360](https://github.com/sase-org/sase/commit/ab1c360404b7af12251a19716b0ed51b429cdbde))
* **plan:** surface plan header block in viewers and docs (sase-ag.6) ([5c74052](https://github.com/sase-org/sase/commit/5c74052a6728503ee4bd1a42b8b4be58e72f5318))
* publish bead lineage after commits (sase-ai.5) ([b645718](https://github.com/sase-org/sase/commit/b6457189ccceea2aa2c2df2b78362fabe307ca51))
* register beads as a managed sidecar (sase-a8.4) ([c113156](https://github.com/sase-org/sase/commit/c113156466bd746064212cfe48e80fc74073ffe3))
* **sdd:** add bead page addressing and hosted bead URLs (sase-ai.1) ([2a8d2eb](https://github.com/sase-org/sase/commit/2a8d2eb6e42537b6eb56e935d1faf3cdce811d2d))
* **sdd:** add beads sidecar guide bundle (sase-a8.2) ([fde7e62](https://github.com/sase-org/sase/commit/fde7e62a15f934b3824264848cc068af7f81f88a))
* **sdd:** add hosted URL resolution for plans, agents, and commits (sase-ag.2) ([563deaf](https://github.com/sase-org/sase/commit/563deafc555973c025e1d99633e4dc770392cd4d))
* **sdd:** add typed plan header block adapter (sase-ag.1) ([8b2baa8](https://github.com/sase-org/sase/commit/8b2baa881e24ab30dadfe527da1bba514a99d817))
* **sdd:** derive plan provenance associations (sase-ag.3) ([7270b98](https://github.com/sase-org/sase/commit/7270b986bf6fbcd9055315469c631d2c586c2b5a))
* **sdd:** index bead commit and agent associations (sase-ai.3) ([9a9bec4](https://github.com/sase-org/sase/commit/9a9bec4ad2673012a77c6e6fe96bce98d654cf01))
* **sdd:** route bead operations to dedicated sidecar (sase-a8.6) ([3dba997](https://github.com/sase-org/sase/commit/3dba997d0c80ce4ec8234d650514ae50eff838a0))
* **sdd:** support split beads sidecar records (sase-a8.3) ([f9bd6ad](https://github.com/sase-org/sase/commit/f9bd6ad226fba1067e1abfd6ae885e3ad312c371))
* **sdd:** write plan provenance headers (sase-ag.4) ([9701511](https://github.com/sase-org/sase/commit/97015111b388e663506d996a2d9c6a7511af0eda))
* See the 'acecommit' phase of 202607/land_beads_sidecar_epic.md (sase-ab.4) ([11f16e3](https://github.com/sase-org/sase/commit/11f16e3275e53e10681c71400c6dd9dd7a769832))
* **skills:** enforce monotonic deploy provenance (sase-ae.2) ([046a92a](https://github.com/sase-org/sase/commit/046a92a3b6ce4495d53f431bcca8008c895c8413))
* **skills:** guard chezmoi deploy source integrity (sase-ae.1) ([3537aa1](https://github.com/sase-org/sase/commit/3537aa141d844123c02fbca3552dbcc669673b3d))
* surface agent publication outbox health (sase-ad.4) ([5842f04](https://github.com/sase-org/sase/commit/5842f04af4d3eabebed72d81b64a6bec477125a3))
* **xprompt:** add canonical project identity helpers (sase-ac.1) ([370f260](https://github.com/sase-org/sase/commit/370f2607f684d68272b2416a313133c8d7058e59))
* **xprompt:** resolve registered project prompts outside cwd (sase-ac.3) ([9148e45](https://github.com/sase-org/sase/commit/9148e45e1829a445e772a07c8c71b6d919a6ff56))


### Bug Fixes

* **ace:** canonicalize prompt-bar VCS-tag xprompt lookup (sase-ac.6.2) ([a0a2e40](https://github.com/sase-org/sase/commit/a0a2e4007ae03a801a00f85d79a286683dc2c515))
* **ace:** escape dead-end panel row focus ([9cdfb37](https://github.com/sase-org/sase/commit/9cdfb378a43753436abac5a9c673f4efa8c60e51))
* **ace:** prioritize selected clan collapse ([a016706](https://github.com/sase-org/sase/commit/a016706a6118a9d5ce89e0ad817790a79d6d8fb1))
* **ace:** resolve plans roots through SDD store (sase-ab.3) ([ac12273](https://github.com/sase-org/sase/commit/ac12273f547df64aee8b59ab951ada5e440750da))
* **ace:** show configured project names in commits UI ([4fb5980](https://github.com/sase-org/sase/commit/4fb5980600a819238d77e4add6bc3487378d5d94))
* **ace:** surface unresolvable tribe waits ([641229f](https://github.com/sase-org/sase/commit/641229f896b6c59ecf1e1c596b2159e7ef7c6294))
* **agents-sync:** allow container-named hood publication (sase-ad.2) ([53e94ca](https://github.com/sase-org/sase/commit/53e94ca4a5e8456316a32ffbb5af8222a0d0c385))
* **agents-sync:** recover sidecar transaction state (sase-ad.3) ([ca5c526](https://github.com/sase-org/sase/commit/ca5c526c724957db6bdcd273b57fe860df2d0883))
* **agents-sync:** retire terminal publication requests (sase-ah.2) ([d8afeb7](https://github.com/sase-org/sase/commit/d8afeb7b0c0331c24d9bdcf7a4c78679020c9548))
* **bead-pages:** link plan BEAD bullets only to pages that exist ([48edca8](https://github.com/sase-org/sase/commit/48edca8c449d805ba9c1bc9f3df7f2301e8d4977))
* **bead:** protect root-layout stores during workspace prep (sase-ab.1) ([0ee67b1](https://github.com/sase-org/sase/commit/0ee67b10a5e36519ffa93998a4b2969c8eca86a1))
* **bead:** require core dependency removal support (sase-a3.4) ([830245c](https://github.com/sase-org/sase/commit/830245c8cdf01ef0f60c3b86346fba02a0b6d68a))
* **beads:** consolidate post-commit sidecar sync ([e1e86f2](https://github.com/sase-org/sase/commit/e1e86f276f86192fe469c8a121054d1c4ce93546))
* **beads:** resolve generated page conflicts (sase-ai.6) ([5043949](https://github.com/sase-org/sase/commit/50439492a6551facacdf8e082c87f418c20db1a1))
* **beads:** skip commits for no-op mutations ([aae07cf](https://github.com/sase-org/sase/commit/aae07cfee19c92b1134447604a13b1a8cc37d623))
* **commit:** attribute family member runs correctly (sase-ad.1) ([b201c92](https://github.com/sase-org/sase/commit/b201c9200c8954b36c226dde675af52fd7b1b66d))
* **commit:** resolve publication targets by repository path (sase-ah.1) ([4fc555d](https://github.com/sase-org/sase/commit/4fc555db0a6b86ccd1f5437c49fdfa668495e169))
* invalidate xprompt identity on project mutations (sase-ac.6.4) ([02eee83](https://github.com/sase-org/sase/commit/02eee837542948dba30c2327120de3a9c8e6fb3d))
* label sidecar commits by repository role ([8049b46](https://github.com/sase-org/sase/commit/8049b46ccb83fa3f88ecb8aba4d70545111f19aa))
* make approved plan linking atomic ([cfbac39](https://github.com/sase-org/sase/commit/cfbac3928a5039a06090e7e4cdf5ce2ef47ee862))
* materialize beads sidecar before launch claim ([86dd439](https://github.com/sase-org/sase/commit/86dd439409b08005fe24758419e7d669d4c808c7))
* **memory:** correct generated instruction grammar ([3bd59cd](https://github.com/sase-org/sase/commit/3bd59cdda2a0317ee4b6e60a6ed72b9f1bcec83b))
* preserve flat plans sidecar with plans README (sase-ab.2) ([8137b10](https://github.com/sase-org/sase/commit/8137b10480ef0e1c03613c3cad862f707e56d95d))
* **sdd:** defer type-only annotations at runtime ([ee087a3](https://github.com/sase-org/sase/commit/ee087a3df01a59617c8a8650ee333b127c5393b3))
* **sdd:** keep published core integration commit-safe (sase-af) ([a643a86](https://github.com/sase-org/sase/commit/a643a864c33b1eb864f570c9e009ff89d313a69f))
* serialize skill chezmoi deploys (sase-ae.3) ([105d9d3](https://github.com/sase-org/sase/commit/105d9d36930f5f6824e49face0fff277e39d4fa9))
* settle stopped family predecessors ([13e3b1d](https://github.com/sase-org/sase/commit/13e3b1ddc93a77b1fdc1aece5c26aecad554eae1))
* **tribes:** reject reserved tribe references in wait and fork targets ([d67de4c](https://github.com/sase-org/sase/commit/d67de4caf9530ff1a4912ffa4ecf2727a50d35df))
* **tui:** preserve active prompts on Ctrl+Space ([18d0d92](https://github.com/sase-org/sase/commit/18d0d924179e250a32cd14f048fbce01f4acbe6f))
* **tui:** tighten commas after xprompt completions ([5568411](https://github.com/sase-org/sase/commit/5568411c9545b2c34bd112fb30f0d39afd4aacc2))
* **xprompt:** canonicalize project catalog namespaces (sase-ac.2) ([40f2d52](https://github.com/sase-org/sase/commit/40f2d526e6b1e0b992dbc3e80c8cee66d5750ac6))
* **xprompt:** canonicalize project-local browser identities (sase-ac.6.1) ([0db608e](https://github.com/sase-org/sase/commit/0db608e985e2031bdb8a58322d8f29b0ce8484fb))
* **xprompt:** canonicalize workflow project identity (sase-ac.6.3) ([699456a](https://github.com/sase-org/sase/commit/699456a521e25e0aaa38f4e289db38e71a6488a6))
* **xprompt:** normalize ACE completion project identity (sase-ac.4) ([b449b8a](https://github.com/sase-org/sase/commit/b449b8a4b5a133ded4771fa07e22307bf97620cb))
* **xprompt:** preserve trailing punctuation in completion ([ad3c751](https://github.com/sase-org/sase/commit/ad3c75151077382cc7f77fe67556b77bb875aadb))


### Performance Improvements

* **ace:** guard Agents-tab view-hints latency (sase-a5.6) ([a49e63e](https://github.com/sase-org/sase/commit/a49e63e3581075d5681a3a593234ddb6462f78d1))
* **bead-pages:** precompute refresh relationship details ([ee2bb5e](https://github.com/sase-org/sase/commit/ee2bb5eee4d0ca76c5cd1d5087abae5269a0b3e3))
* **tui:** bound file hint rendering work (sase-a5.2) ([9385e8a](https://github.com/sase-org/sase/commit/9385e8a6209256a46176353cda1e5fd2a36f8539))
* **tui:** cache annotated hint documents (sase-a5.4) ([57c5b8c](https://github.com/sase-org/sase/commit/57c5b8c6a9007fae7c6b18ba4ea56b9e038be88a))
* **tui:** defer agent hint document rendering (sase-a5.3) ([419790e](https://github.com/sase-org/sase/commit/419790e846b17308052b65ce0d22096d7094ce59))
* **tui:** skip unchanged hint document renders (sase-a5.5) ([41ba006](https://github.com/sase-org/sase/commit/41ba006bd4c6f41a041abae4508d2ed90c5c8f24))


### Documentation

* **beads:** document truthful completion contract (sase-a1.6) ([6ad452e](https://github.com/sase-org/sase/commit/6ad452e1e84d47bafc39eb3a2850a954a1891768))
* describe the dedicated beads sidecar (sase-a8.9) ([9ddd75a](https://github.com/sase-org/sase/commit/9ddd75a3f34902c48e361942cfe9a652b37b7d49))
* document the commit-then-deploy skill workflow (sase-ae.6) ([53d732f](https://github.com/sase-org/sase/commit/53d732f30e91839e58eee9047d6e6b5a18cd248f))

## [0.12.0](https://github.com/sase-org/sase/compare/v0.11.1...v0.12.0) (2026-07-27)


### ⚠ BREAKING CHANGES

* **bead:** Closing a bead with unfinished descendants now requires --force, a reason, and a canceled or superseded resolution.
* **axe:** AXE lumberjacks and chops must provide a non-blank description, and bare-string chop list entries must be replaced with map or object entries.
* **axe:** Lumberjack and chop `description` values require a non-blank line 1 summary of at most 100 characters, a blank line 2 before any multi-line body, and at most 2000 characters overall; violations fail config loading with `description_summary_blank`, `description_summary_too_long`, `description_body_separator_required`, or `description_too_long`.
* Epic approvals no longer support foreground, TUI-tracked, or agent-side subprocess launch modes; callers must follow the detached task.
* **llm-provider:** llm_provider.model_aliases.builtin.epic_creator is no longer accepted as a builtin override; remove the stale entry from SASE configuration.
* **agents:** Current agent APIs, wires, metadata, queries, and display terminology use tribe instead of tag; standalone assignments live in `~/.sase/agent_tribes.json` under `tribe`; the Agents query uses `tribe:` instead of `tag:`; legacy persisted tag data remains readable.
* **agents:** Agents sync status schema v4 removes the unexported_agents field and the CLI UNEXPORTED column.
* New commits no longer emit SASE_MACHINE; consumers should use the global SASE_AGENT identity instead.
* **identity:** Agent launches and new commit provenance now require id.username and id.machine_name in the selected overlay. Run `sase config init` to migrate legacy configuration.
* **bead:** --yes now skips only launch confirmation; use --yes-to-all to authorize destructive cleanup non-interactively.
* **config:** The public SASE configuration schema now requires a machine_name matching ^[a-z_]+$.
* **cli:** `sase plan validate` no longer accepts `-t` or `--tier`; set `tier: tale` or `tier: epic` in plan frontmatter instead.
* **ace:** Tribe panel isolation and restore now use the zoom_panel action, bound to Z by default, instead of hooks_or_collapse_all on H. Custom keymaps should bind zoom_panel to choose the isolation key.
* **ace:** Agents-tab lowercase h now navigates to a parent container or tribe instead of collapsing structural folds; use uppercase H to collapse.
* @phase_worker is no longer a built-in alias. Configure phase sizes through @small_phase_worker, @medium_phase_worker, and @large_phase_worker, or define a custom phase_worker alias for legacy explicit references.
* Overriding phase_worker now affects medium and explicit phase-worker launches only; configure the small_phase_worker and large_phase_worker aliases to restore the previous shared routing.
* Large phases without an explicit model now route through @large_phase_worker, which falls back to @phase_worker, instead of @smartest. Configure large_phase_worker as @smartest to preserve the previous routing.
* Rename ace.prompt_completion.history_word_min_length to word_min_length.

### Features

* **ace:** add chat details and filtering (sase-90.6) ([99bcd56](https://github.com/sase-org/sase/commit/99bcd567f0e6f6a129bac9616a55f9d59730beb5))
* **ace:** add collapsible AXE description panel (sase-9w.3) ([9b3074c](https://github.com/sase-org/sase/commit/9b3074c66cafe32b21f392a3af7f9c6392652d95))
* **ace:** add default effort controls to Models panel ([a2c33ea](https://github.com/sase-org/sase/commit/a2c33ea03d1936d0f953ed9448ade95c2c5dd3c5))
* **ace:** add digit jumps for lane neighbors (sase-99.4) ([23c0061](https://github.com/sase-org/sase/commit/23c0061450fdeeb83dc6644ea1918391c6aef9e8))
* **ace:** add numbered gate branch shortcuts ([ec03529](https://github.com/sase-org/sase/commit/ec0352909ef3d51fdf6e5f70e537aeffd29d1481))
* **ace:** add prompt word definitions and spellcheck ([08f163b](https://github.com/sase-org/sase/commit/08f163b59e47983fff74a67ec59d519946d60bc5))
* **ace:** add selected-panel collapse ladder ([d3da2f1](https://github.com/sase-org/sase/commit/d3da2f1a502918e0b91c3d17f812747d02fbfe86))
* **ace:** add shared config editor components (sase-8m.2) ([331932b](https://github.com/sase-org/sase/commit/331932b2c8c82517dd5920b5129822e50466079d))
* **ace:** add tribe-scoped fold hints ([266eac0](https://github.com/sase-org/sase/commit/266eac076ab2986a6153fd5f2818761d4b11d109))
* **ace:** clarify Help Guide tab content ([06338fc](https://github.com/sase-org/sase/commit/06338fc148dbad0297cf94fa90651680a72817a1))
* **ace:** collapse clans from selected agent panel ([d32b2d4](https://github.com/sase-org/sase/commit/d32b2d4a0ed321c310943e2de5347f1cab021f38))
* **ace:** confirm launches containing TODO markers ([dc6ef5f](https://github.com/sase-org/sase/commit/dc6ef5fade7cf1410513b96c4011d1fc97fba3c0))
* **ace:** consolidate Agents header status counts ([86dc5a0](https://github.com/sase-org/sase/commit/86dc5a04895671ef29fe61ba695eff1bf6ec7eaa))
* **ace:** continue prompt bullets on Ctrl+J ([2695bf7](https://github.com/sase-org/sase/commit/2695bf72af57c11f71b2110430c4468b8ac192c4))
* **ace:** continue prompt bullets with normal-mode o ([f7e974d](https://github.com/sase-org/sase/commit/f7e974d66aa20b3b6d6746ec8ba73334c8c0cd27))
* **ace:** continue prompt bullets with open-above ([30503fc](https://github.com/sase-org/sase/commit/30503fca89e08e303ef58874edcf683e1f617251))
* **ace:** default Artifacts to Commits ([1026740](https://github.com/sase-org/sase/commit/1026740c50ef4383bb739267fdb2b7e9e9cde57c))
* **ace:** distinguish saved placeholder completions (sase-9m.4) ([141aaf7](https://github.com/sase-org/sase/commit/141aaf7f51cc8a7a3bfd47b717eb8ff8f219c033))
* **ace:** edit wait priority from wait modal (sase-9k.4) ([3a8540f](https://github.com/sase-org/sase/commit/3a8540f321764da347f69c38eced0b96c1f0119f))
* **ace:** exit prompt bullets with ctrl+j ([4f783d4](https://github.com/sase-org/sase/commit/4f783d4b6efcae81eae4014d53154993b6083693))
* **ace:** highlight leading bullet dashes in prompt input ([0e26ea1](https://github.com/sase-org/sase/commit/0e26ea1939823a2f5d5e5922c519cd2525ea5385))
* **ace:** highlight TODO annotations in prompts ([5839250](https://github.com/sase-org/sase/commit/58392509657b46b69db09190290438e8b50bdab0))
* **ace:** honor xprompt placeholder argument toggle (sase-9q) ([f5f30f9](https://github.com/sase-org/sase/commit/f5f30f91e6f5c76b02d58b371d64761910448e39))
* **ace:** jump from collapsed panels to expanded panel ([678414a](https://github.com/sase-org/sase/commit/678414a6ce10e728fe4d9a32cae741752a87094f))
* **ace:** jump to parent agent containers ([7900eeb](https://github.com/sase-org/sase/commit/7900eeb50a3542af97a6ed0404ff2bb3e45d23f0))
* **ace:** let q close the AXE entry editor ([c1fc89c](https://github.com/sase-org/sase/commit/c1fc89c571ff2607365caef4bcfe527073eb7d9e))
* **ace:** move the lane NEIGHBORS section above SASE CONTEXT ([c917bc0](https://github.com/sase-org/sase/commit/c917bc04d341885ec11fdf4285288cc846fa4469))
* **ace:** move tribe panel isolation to zoom action ([d8e30b5](https://github.com/sase-org/sase/commit/d8e30b51d3eea3817693b9b9b68cf5775dadbcdb))
* **ace:** offer saved common placeholder tags in prompt completion (sase-9m.3) ([e3e0bd8](https://github.com/sase-org/sase/commit/e3e0bd8bb65997d26def5abc2056d1faf3d215d8))
* **ace:** persist Admin Center resume tab ([f16a123](https://github.com/sase-org/sase/commit/f16a123612db28ba4ac57720921b6bf1c0161ac9))
* **ace:** persist the commits default filter ([4f86191](https://github.com/sase-org/sase/commit/4f86191c2866975f8ca40173345a3adf01617035))
* **ace:** redesign AXE entry editor ([104a31c](https://github.com/sase-org/sase/commit/104a31c715ac950d6a73de08d12b0266beda2fe7))
* **ace:** redesign AXE entry editor as property sheet ([5a9a01f](https://github.com/sase-org/sase/commit/5a9a01fe64ff0936cb1b20a368876ff6897aced4))
* **ace:** refine top-bar override pills ([41e44d1](https://github.com/sase-org/sase/commit/41e44d1c4205f7049723e109c53350460cc36913))
* **ace:** reorder Artifacts subtabs ([0e38edf](https://github.com/sase-org/sase/commit/0e38edf56bf8fb7266362e95504b5477d7b1864f))
* **ace:** report agent holes in tribe panels ([bdde10d](https://github.com/sase-org/sase/commit/bdde10dceb45dc86cadb85be5d8400207b387b7c))
* **ace:** separate cached agent updates from full sync (sase-8v.8) ([906690b](https://github.com/sase-org/sase/commit/906690b506d82c39c7b970a30293fe580fda94ca))
* **ace:** separate left navigation from collapsing ([fbcfb1e](https://github.com/sase-org/sase/commit/fbcfb1eb193c14aaeafc527c41224c03470c1d02))
* **ace:** show applied commits in post-update toast ([7c71edf](https://github.com/sase-org/sase/commit/7c71edf08ff7e6581a56af3cc9072272fae3a5cc))
* **ace:** show commit timeline position badge ([1fe0afe](https://github.com/sase-org/sase/commit/1fe0afee6009fa5af8eccd3ddf278bdecae8b582))
* **ace:** show explicit wait priorities (sase-9k.3) ([68723be](https://github.com/sase-org/sase/commit/68723bedb8e0b29b53533200999f6a25f36b081e))
* **ace:** show globally queued agent counts ([ca348d7](https://github.com/sase-org/sase/commit/ca348d7034c1887b600464b913d8b29cba304ef9))
* **ace:** show model pool effort details ([d57e220](https://github.com/sase-org/sase/commit/d57e2207c097dd7fc097f7267e700db5727c3bde))
* **ace:** show runner queue position context ([0218ce8](https://github.com/sase-org/sase/commit/0218ce832fe25ebf5452d8dcc8210a163d12a142))
* **ace:** show statuses for waited-on beads ([28c4097](https://github.com/sase-org/sase/commit/28c40972a2c41abec5a165560da188ba732caac8))
* **ace:** support insert-mode bullet indentation ([0846479](https://github.com/sase-org/sase/commit/084647975d1ba6e239c0697b839ab40e65ed544a))
* **ace:** surface agents repository sync status (sase-8k.7) ([a075c01](https://github.com/sase-org/sase/commit/a075c014fd5faed7f6c7556fca7d4db51286b891))
* **ace:** uncap default commit queries ([4d98fe0](https://github.com/sase-org/sase/commit/4d98fe0d262fe159a759cf0b412f75c2bba956ae))
* **ace:** warn on custom builtin alias shadows ([ff8af79](https://github.com/sase-org/sase/commit/ff8af79b91e305d55e89f2f98d6c70d64e75f048))
* add `sase task` commands (sase-95.5) ([6e97d2a](https://github.com/sase-org/sase/commit/6e97d2a4f53be62c3303e830e6386d72144c7baf))
* add clickable SDD frontmatter links ([8e7851e](https://github.com/sase-org/sase/commit/8e7851edeb78730fceabd9adfe2ee0b9d1f56ee3))
* add hidden agents sidecar foundation (sase-8k.4) ([ba0a3cd](https://github.com/sase-org/sase/commit/ba0a3cd92f02754effe0db0f647ff21c82b8b32f))
* add load-balanced model alias pools ([5a23c29](https://github.com/sase-org/sase/commit/5a23c297f8a43ffc3a537da23ebb4aa319a68a22))
* add machine-qualified agent hoods (sase-8k.3) ([e828aa9](https://github.com/sase-org/sase/commit/e828aa927e3dff3c3c4f1f4539a3c8c5201ea83e))
* add prompt input plan for raw placeholders (sase-9q.3) ([73269f8](https://github.com/sase-org/sase/commit/73269f8e47a788be43ec5d2c6f5ebd5768a6b345))
* add runner limit controls ([1aa37dc](https://github.com/sase-org/sase/commit/1aa37dc35d9ad2bd5c165c118363b45db0b0a21c))
* Admin Center Tasks tab over the durable store (sase-95.6) ([8eafb2a](https://github.com/sase-org/sase/commit/8eafb2aa587005f2499ada614e9542346bd4a066))
* **agent:** persist local names relative to owner (sase-8v.3) ([5bf430b](https://github.com/sase-org/sase/commit/5bf430b67eb42f61e5472f689e0cba4a0d276669))
* **agents:** add completed agent sync engine (sase-8k.6) ([58d1ca2](https://github.com/sase-org/sase/commit/58d1ca2da51df1bcd9bdc2464503985de59a416c))
* **agents:** complete tribe terminology cutover (sase-7j.4) ([0138849](https://github.com/sase-org/sase/commit/0138849d919e0136b6eedadbcfb28e603f2b58bb))
* **agents:** publish owner-sharded v2 hood snapshots (sase-8v.4) ([2464be5](https://github.com/sase-org/sase/commit/2464be5462bd99580d0a91b2802abea3560e9064))
* **agents:** retire legacy v1 sync payloads (sase-92.5) ([712a6b1](https://github.com/sase-org/sase/commit/712a6b1f3bb1c209e07919f4794acd4f4a0fc211))
* **axe:** add config management workflows (sase-8m.3) ([058cd64](https://github.com/sase-org/sase/commit/058cd646fb1d3113fe28186473f252dc4f488d13))
* **axe:** add side-effect-free status snapshots (sase-8t.2) ([0689333](https://github.com/sase-org/sase/commit/0689333f778ad10c96e2fe82a03076b3c3f7e752))
* **axe:** add whole-system status command (sase-8t.3) ([d0cf97a](https://github.com/sase-org/sase/commit/d0cf97a12930b4c28e0f86097518cf05965ca306))
* **axe:** apply exact conflict-safe config edits (sase-8m.1) ([5a9cef8](https://github.com/sase-org/sase/commit/5a9cef88329bc5f3323603300bc86040509530a0))
* **axe:** carry clan summaries through chop launches (sase-8l.1) ([eaef2d7](https://github.com/sase-org/sase/commit/eaef2d78b1faf15a0764e08b066383ee4d6a48e3))
* **axe:** expose chop run source and dry-run state (sase-a2.1) ([f15c05d](https://github.com/sase-org/sase/commit/f15c05dc6cb8b9c7a6b5564655a676a3d3257e6f))
* **axe:** plumb optional lumberjack descriptions (sase-9t.2) ([b3bfb81](https://github.com/sase-org/sase/commit/b3bfb817399efea2d19a58b4df106dbe4b8c1534))
* **axe:** plumb structured descriptions (sase-9w.2) ([dd114a6](https://github.com/sase-org/sase/commit/dd114a6ef057de37974490ff941554e1d25529ec))
* **axe:** reap the managed SASE temp root (sase-96.8.7) ([15a5a0e](https://github.com/sase-org/sase/commit/15a5a0e67ad521644e7b85063aaefba5798b2adf))
* **axe:** require configuration descriptions (sase-9t.6) ([98a3d9c](https://github.com/sase-org/sase/commit/98a3d9c4e30fbf12ba21bcb0e4931d2089711038))
* **axe:** show selected item descriptions (sase-9t.4) ([7681646](https://github.com/sase-org/sase/commit/7681646627201d68281dcb2edda2caab1c2b283a))
* **axe:** show summary-first list descriptions (sase-9w.4) ([f2c53c2](https://github.com/sase-org/sase/commit/f2c53c28f83fd9961460f8ff7dcb4fea29424364))
* **axe:** surface descriptions in the AXE CLI listings (sase-9t.5) ([a24874d](https://github.com/sase-org/sase/commit/a24874d2df2db84c542eadf5a547c6304e87c478))
* **bead:** add dependency removal command (sase-a3.2) ([786b672](https://github.com/sase-org/sase/commit/786b6720e72cb520408b6e93e425406cbb092bda))
* **bead:** add dependency tree command (sase-a3.3) ([793887c](https://github.com/sase-org/sase/commit/793887cf80f9e5491e4cd227682a344c4aece8ae))
* **bead:** add list output formats ([672ecbb](https://github.com/sase-org/sase/commit/672ecbb4c835507817b78af6c573c399145c3b08))
* **bead:** add note append command (sase-a1.3) ([b25e7db](https://github.com/sase-org/sase/commit/b25e7dbc677ef9e5653f6bef7419c827463f85cb))
* **bead:** add show output formats ([d51475b](https://github.com/sase-org/sase/commit/d51475b249f77dbd8760df96cc268e24a9f7d2e1))
* **bead:** expose typed close resolutions (sase-a1.2) ([d1b02a6](https://github.com/sase-org/sase/commit/d1b02a69f3471c97c40cb214eb42f411bd5184e8))
* **bead:** launch approved epics as detached tasks (sase-9s.5) ([6d78d49](https://github.com/sase-org/sase/commit/6d78d490d27eec12e0b28f2f554a44dc60c46b5e))
* **bead:** report recurring managed-sync failures (sase-9x.6) ([7538b93](https://github.com/sase-org/sase/commit/7538b9395489ffc74de8c58525bd9cee2d870889))
* **bead:** require explicit descendant close sweeps (sase-a1.4) ([3deac7d](https://github.com/sase-org/sase/commit/3deac7d22675315a5adbebe28fd6a2fc4c549241))
* **beads:** add claimed status read-side support (sase-8y.3) ([5ca1756](https://github.com/sase-org/sase/commit/5ca1756fc685499fa42e8a784ae5c3beb7e5c39e))
* **beads:** add history command (sase-a1.1) ([3dd9765](https://github.com/sase-org/sase/commit/3dd976565937d0b9851d25c94be1ef89442d2885))
* **beads:** list dependency graph edges (sase-a3.1) ([87bc8f7](https://github.com/sase-org/sase/commit/87bc8f72f5c917ee898a1da18218ff4710d7b0a6))
* **beads:** manage claims across runner lifecycle (sase-8y.4) ([408b789](https://github.com/sase-org/sase/commit/408b7894952c7c8504915df22e6f1ac68cae1048))
* **beads:** reconcile stale pre-launch claims (sase-8y.5) ([bd7ad46](https://github.com/sase-org/sase/commit/bd7ad46a43a2c894aec15d319ec069a1ae25c451))
* **beads:** repair legacy design references (sase-9z.5) ([7ac5b91](https://github.com/sase-org/sase/commit/7ac5b917c08ebe10f847caacdcabf2a2fcc401a6))
* **beads:** restore overwritten note revisions (sase-a1.5) ([b24e69c](https://github.com/sase-org/sase/commit/b24e69c047a2e8428784f5992cdc734ed4b4e428))
* **beads:** route approved epic launch through the task runner (sase-95.7) ([441882d](https://github.com/sase-org/sase/commit/441882db9949c7f057bd7e68a2be0aaeffc986bd))
* **beads:** support atomic multi-bead removal (sase-8x.2) ([fed1886](https://github.com/sase-org/sase/commit/fed18866e1738bee92fbdb9587ca261bfa895e26))
* **bead:** support extended phase sizes (sase-8w.3) ([a5c5d03](https://github.com/sase-org/sase/commit/a5c5d0398e31032622ca93624fddc95d8a1bcc58))
* cache foreign agent state for offline integration (sase-8v.7) ([f76a9ed](https://github.com/sase-org/sase/commit/f76a9ede7738308fc89ca7cfe6f476e0a6598727))
* **chats:** expose publication quarantine provenance (sase-90) ([e5d953e](https://github.com/sase-org/sase/commit/e5d953eadd0b66ce4c9d8806d045048943107825))
* **chats:** integrate publication state with provenance ([80cc705](https://github.com/sase-org/sase/commit/80cc705f4bd78b9c691d1c220c0d0a466e00944f))
* **chat:** surface sync provenance in `sase chat list` (sase-90.4) ([c1c0e15](https://github.com/sase-org/sase/commit/c1c0e1557314fb6a0db27a0bce919c9c466c72e7))
* **claude:** register Claude 5 model metadata ([7dd9a0f](https://github.com/sase-org/sase/commit/7dd9a0fdb0ce23440501965d111a18104e4e8990))
* **cli:** infer plan validation tier ([6b3457b](https://github.com/sase-org/sase/commit/6b3457b0bc765201ca33a8a80fddf544ae3a67cb))
* **config:** add machine identity initialization (sase-8k.1) ([770ad01](https://github.com/sase-org/sase/commit/770ad01ab111e5454d375ec786a1e60cb64c775d))
* **core:** add SHA and legacy ownership facades (sase-92.1) ([d1353c6](https://github.com/sase-org/sase/commit/d1353c635849625aaf25c20230bc55b762dc5aa4))
* **doctor:** add unclaimed-live-agent advisory and claim race coverage (sase-94.4) ([792b019](https://github.com/sase-org/sase/commit/792b019473512d0acff042c1c8fcfc0caa3b24b7))
* expand phase-worker model alias ladder (sase-8w.2) ([18ca7cb](https://github.com/sase-org/sase/commit/18ca7cb9684c5b24ca311b6a8e8f8706a3a13f85))
* **history:** add durable common-placeholder store (sase-9m.2) ([9f8f04a](https://github.com/sase-org/sase/commit/9f8f04a4ae7f927447469de0674ebb2ca76d38dd))
* **history:** add provenance-aware chat catalog (sase-90.3) ([7bb87b1](https://github.com/sase-org/sase/commit/7bb87b1f54e9ed4da661fe169e11948740dfa595))
* **identity:** expose owner-aware agent facade (sase-8v.1) ([de816e0](https://github.com/sase-org/sase/commit/de816e064b19a40f4490f4aa1407e0e8093de614))
* **identity:** require nested owner configuration (sase-8v.2) ([97230f1](https://github.com/sase-org/sase/commit/97230f1a2901308ea2c28d1079d561ab00670847))
* import agent packages transactionally (sase-8v.5) ([2409ed2](https://github.com/sase-org/sase/commit/2409ed2e37e454f712f44651534516d04517ef4f))
* Improve /sase_plan skill using the new `--explain` plan validation option ([e0aa232](https://github.com/sase-org/sase/commit/e0aa2327bb140fd0201ce09c1a6fdf1b3e2fc91e))
* integrate core capitalized snippet aliases (sase-8u.2) ([6e6b8d8](https://github.com/sase-org/sase/commit/6e6b8d85c3c4314d84ba5167c22a955bacf623fe))
* **llm-provider:** retire epic_creator model alias ([14bf5f1](https://github.com/sase-org/sase/commit/14bf5f15c169579fe947609236c23f7d77ccb6f4))
* **llm:** add ordered model alias fallbacks ([31e9697](https://github.com/sase-org/sase/commit/31e9697ac65d69917929f8348810857ee8e2cdb2))
* **models:** clarify alias ownership in Models panel ([abf8dd3](https://github.com/sase-org/sase/commit/abf8dd3c48d446a3148d860af34cd7dbb6fe4e95))
* **models:** make medium phase worker follow default ([e0f310d](https://github.com/sase-org/sase/commit/e0f310d8da7a01c7e67aac9e030582ab746b9b22))
* **pdf:** render plan frontmatter as properties cards ([215721f](https://github.com/sase-org/sase/commit/215721fd5a17f70ba42937223cd3db84411a66a3))
* **plan:** document five phase sizes in --explain text (sase-8w.5) ([39f90d3](https://github.com/sase-org/sase/commit/39f90d3764eb050ae869f711a62e36f467874d64))
* planner-member-tokens (sase-9n.2) ([f15d02d](https://github.com/sase-org/sase/commit/f15d02d03a81e74931151400b52bcb4eaedf6e7f))
* preserve effort through model aliases and overrides (sase-8z.1) ([4457a87](https://github.com/sase-org/sase/commit/4457a87c4290fa08751ac6e9c161b87fce2f3831))
* preview commits for comprehensive updates ([26c9b5b](https://github.com/sase-org/sase/commit/26c9b5bd6ea096906addd24439befa745be21047))
* publish linked agent hoods after commits (sase-8v.6) ([9aab8a7](https://github.com/sase-org/sase/commit/9aab8a713d27977956c68eb80b4affa9ac41a00b))
* remove legacy epic approval launch paths (sase-9s.6) ([b6d59fa](https://github.com/sase-org/sase/commit/b6d59fa0fa7824a21dbf393c2b689797dbaa2d73))
* render claimed bead status in TUI (sase-8y.6) ([cf1d3aa](https://github.com/sase-org/sase/commit/cf1d3aa4fc181597d71ddbcb19e9908e1e2928b9))
* **repo-init:** initialize agents sidecars with explicit consent (sase-8k.5) ([44ccbe8](https://github.com/sase-org/sase/commit/44ccbe84c7c23d1ad21433b428235dc37493072e))
* route large epic landers through smartest alias ([96fe7e7](https://github.com/sase-org/sase/commit/96fe7e78af7e3cb687d2cef83c91713229fc6663))
* route phase workers through size aliases ([eb93169](https://github.com/sase-org/sase/commit/eb93169eb8874e70e01d17daf2709521627072fc))
* **sdd:** add shared plan reference facade (sase-9z.1) ([6065356](https://github.com/sase-org/sase/commit/6065356e7beacd1dfd452b081ad093a0894afe99))
* **sdd:** render artifact links as Markdown bullets ([f9837f7](https://github.com/sase-org/sase/commit/f9837f70f955c891b50849de35f18f2543b96bac))
* **sdd:** surface plan references and where they resolve (sase-9z.4) ([881636a](https://github.com/sase-org/sase/commit/881636a745de9f88d43cbfcec868f6a537e9f0a2))
* **sessions:** add session registry and display identity (sase-95.2) ([9ebae15](https://github.com/sase-org/sase/commit/9ebae1577d22b0155eb4cc95521d50e852e5d2f6))
* share word completion minimum length ([99fcb50](https://github.com/sase-org/sase/commit/99fcb506b2daeac9f8314931b5f36247188d8678))
* simplify phase model aliases ([58bacaf](https://github.com/sase-org/sase/commit/58bacaf668db5541554a49922203b828df9de916))
* **statistics:** add configurable half-page scrolling ([2b875db](https://github.com/sase-org/sase/commit/2b875dbcc6a5ad959f9da4a1fdd010ca328a2e9d))
* **statistics:** add contextual project keymaps ([12166f1](https://github.com/sase-org/sase/commit/12166f196a7affd4f36cd3cf863e2295f3f90a76))
* **statistics:** add reverse time range cycling ([fdbdf2d](https://github.com/sase-org/sase/commit/fdbdf2d968e45be0047b1a443d7c60f26f249688))
* **stats:** add Python runner-occupancy view model contract (sase-8j.2) ([624adb3](https://github.com/sase-org/sase/commit/624adb3d843b107513ee4d150d3102abe8a9a9a5))
* surface runner-cap queued agent status ([899a257](https://github.com/sase-org/sase/commit/899a257f22b0a36225485f8c81faaf72cef4fdf9))
* **tasks:** add detached task supervision (sase-95.4) ([13598dc](https://github.com/sase-org/sase/commit/13598dc3d14bd28b004406794b8a99df3f8b21fe))
* **tasks:** add durable task store facade (sase-95.3) ([b262933](https://github.com/sase-org/sase/commit/b26293395587b056bf4cf340a8038a4e4e968b30))
* **tasks:** expose detached work across CLI and TUI (sase-9s.7) ([9176e23](https://github.com/sase-org/sase/commit/9176e2396ef8e4516e38c0221c5b9513bc65647b))
* **tasks:** record detached epic launch origins (sase-9s) ([f499ca1](https://github.com/sase-org/sase/commit/f499ca1db61a7f2ccef55e6d8d59f57048617d49))
* **tasks:** submit, own, and filter detached tasks (sase-9s.4) ([f49e598](https://github.com/sase-org/sase/commit/f49e598037b7e1183e4434bc198cc39a4d72bbf4))
* **tui:** add catalog-backed Chats list (sase-90.5) ([cc85ef8](https://github.com/sase-org/sase/commit/cc85ef89b3ba7f2f03389a751a6a212b94030267))
* **tui:** add runner statistics experience (sase-8j.3) ([6c052e8](https://github.com/sase-org/sase/commit/6c052e8169789a0b4ffa1fd536cf642c9a9bd88f))
* **tui:** add unified prompt inputs panel (sase-9q.4) ([1106561](https://github.com/sase-org/sase/commit/11065612bcdb544d9f1e41036b9f23d9ad950898))
* **tui:** collect prompt inputs on prompt-bar submit (sase-9q.5) ([2ce0f95](https://github.com/sase-org/sase/commit/2ce0f956da2facb017cfcb5f1874388fb10e2b5c))
* **tui:** color runner limits by capacity ([63ad0ab](https://github.com/sase-org/sase/commit/63ad0ab6b188392f9a7348b545f733d991d74f42))
* **tui:** color tribe identities consistently ([0bff029](https://github.com/sase-org/sase/commit/0bff029f30a56c04b8cf0488e68051355e25c49b))
* **tui:** extend shared member roster rendering (sase-99.2) ([a8f9e58](https://github.com/sase-org/sase/commit/a8f9e5802c395c3cce113edee9dac1c53d56dc08))
* **tui:** link chats to local agents (sase-90.7) ([8a0ae27](https://github.com/sase-org/sase/commit/8a0ae2730091422830390c8385b59df993e753e7))
* **tui:** present all five phase sizes (sase-8w.4) ([f19e031](https://github.com/sase-org/sase/commit/f19e031dd1aebbb6ebb1b86fd4385f02d91c5901))
* **tui:** preserve effort in model picker flows (sase-8z.2) ([28c5c86](https://github.com/sase-org/sase/commit/28c5c86d274f1fbdfb47f3b001384f419f5ab027))
* **tui:** redesign plugin action confirmation previews ([a5f4dd2](https://github.com/sase-org/sase/commit/a5f4dd23ec4ba669862b3f1fa67c22325c6a684e))
* **tui:** render fold-aware lane neighbors (sase-99.3) ([a53f5a5](https://github.com/sase-org/sase/commit/a53f5a55b9c0ff299ef5cc3b2db9f3f2c0c1fa5c))
* **tui:** reorder Artifacts tabs by usage ([93c58bd](https://github.com/sase-org/sase/commit/93c58bd88c547aadad4a04e77409777b1edc92a1))
* **tui:** scaffold artifacts chats pane (sase-90.2) ([5fa1507](https://github.com/sase-org/sase/commit/5fa15073914d71aec5271d46db369b45ec371bf4))
* **tui:** show linked plans in commit view ([e4cdefd](https://github.com/sase-org/sase/commit/e4cdefd621267341005fcbed6ac6cceb51bf5c49))
* unify plan reference resolution across readers (sase-9z.2) ([f593eca](https://github.com/sase-org/sase/commit/f593eca04f2279b35c41e05472e21a3ca5cf3224))
* **vim:** support visual surround selections ([99d29be](https://github.com/sase-org/sase/commit/99d29be7594c410d8f9c8025c52b3da2ff4f69ef))
* **xprompt:** add raw placeholder facade (sase-9q.2) ([aedbb6b](https://github.com/sase-org/sase/commit/aedbb6b07ad73fb4c61c4c02db2e0d3e71d8029f))
* **xprompt:** convert placeholders to input arguments (sase-9q.6) ([5654ed2](https://github.com/sase-org/sase/commit/5654ed2bd7a19bafb60f42730de84038c699617b))


### Bug Fixes

* **ace:** align status summaries with agent holes ([85aa33e](https://github.com/sase-org/sase/commit/85aa33e908bb7286d09ace4befb6c2f42666c382))
* **ace:** clarify cached agent hood update copy (sase-92.6) ([f17ccbf](https://github.com/sase-org/sase/commit/f17ccbf8f5b365ff83d5fc77d180feeab7739ca1))
* **ace:** collapse group clans before grouping banners ([010c061](https://github.com/sase-org/sase/commit/010c061757c693cc271e49043a049627eb2f4793))
* **ace:** collapse houses before agent groups ([1da3817](https://github.com/sase-org/sase/commit/1da3817eb72f994709f2d4147277134e3c36c73b))
* **ace:** count agent holes in headline ([1232a8c](https://github.com/sase-org/sase/commit/1232a8c1c91b6dcabb6fb5d0959d631b7135d6a1))
* **ace:** enable view hints for agent families ([6cbb38f](https://github.com/sase-org/sase/commit/6cbb38faf62635b8e070ec66347ff118c2d6bd3d))
* **ace:** exclude a lane from its own neighbor list (sase-99.5) ([c4063f4](https://github.com/sase-org/sase/commit/c4063f44788f86af1169ee1ac22ca4565c1858b2))
* **ace:** exclude queued agents from waiting counts ([b1b5db1](https://github.com/sase-org/sase/commit/b1b5db1fd7392a731ffdf7ec3c0fb848a7489498))
* **ace:** keep prompt Ctrl+J from clearing a lone empty bullet ([6c4b65f](https://github.com/sase-org/sase/commit/6c4b65f7bd0a1339d62af6b63c47f42febe1bfef))
* **ace:** keep running count color stable ([1892887](https://github.com/sase-org/sase/commit/18928870295811986d816146b9af5f4679ed91ca))
* **ace:** keep ungrouped agent houses first ([cba6525](https://github.com/sase-org/sase/commit/cba65253b1f0bd5414755120f5f0a2f198d2d7e4))
* **ace:** key agent lanes by the name they present ([9ea6edc](https://github.com/sase-org/sase/commit/9ea6edc3ec5de0c221223ec61b7f508ec73ea146))
* **ace:** make agent dismissal tier-independent (sase-9o.1) ([44c5ce3](https://github.com/sase-org/sase/commit/44c5ce3de5cf9b29b431a1207018e275ac8f4ca2))
* **ace:** navigate to all agent house parents ([fe8c2e0](https://github.com/sase-org/sase/commit/fe8c2e0277e5cd77cce6d591f135407924c0385b))
* **ace:** omit queued chip from leaf agent rows ([53d36a2](https://github.com/sase-org/sase/commit/53d36a2980bd3930de103ccc65f94c4117f59f39))
* **ace:** preserve clan member name during kill and edit ([c05db01](https://github.com/sase-org/sase/commit/c05db016318c53f7394ad4a3f54fcd66221189e3))
* **ace:** preserve prompt space below frontmatter panel ([d6688f1](https://github.com/sase-org/sase/commit/d6688f133b0320d413d2bb4a2c857a15ddaa9782))
* **ace:** preserve runner roots sharing child pid ([4a6776f](https://github.com/sase-org/sase/commit/4a6776f1255df378d3a9d9f9439680dc388213e9))
* **ace:** prevent quit hangs on in-flight workers ([c0f1c6e](https://github.com/sase-org/sase/commit/c0f1c6e5a3c775ee314a6ca14c16ca5913b83d05))
* **ace:** prioritize queued clan status ([30f3a22](https://github.com/sase-org/sase/commit/30f3a22c86d445f7be5560bc7e9a966286c1bd60))
* **ace:** reconcile cross-surface plan approval status ([9f11060](https://github.com/sase-org/sase/commit/9f1106068caa951039966938424ade137a01e5a0))
* **ace:** remove clan and family identity icons ([605b7ba](https://github.com/sase-org/sase/commit/605b7baa1d4a9a95b4188f32fb69a05d23031eab))
* **ace:** report capped commit results truthfully (sase-8h.3) ([54e8736](https://github.com/sase-org/sase/commit/54e8736ea7ed487b3f600ad71939316764957b43))
* **ace:** respect Markdown structure in TODO highlighting ([da207ba](https://github.com/sase-org/sase/commit/da207ba769eba6a058c408c04162adda0d3556dd))
* **ace:** restore arrival bell for plan reviews ([679a41b](https://github.com/sase-org/sase/commit/679a41b42eaed4821cfa699139d3088f804cbd77))
* **ace:** show bare container names for family roots ([4d09e81](https://github.com/sase-org/sase/commit/4d09e81b9c6669c4ca04594e8fc26dbaf057e080))
* **ace:** skip collapsed tribe panels during jumps ([178f5d5](https://github.com/sase-org/sase/commit/178f5d53fd7228e8363cfd1ce7adf594bb6127ac))
* **ace:** summarize cleanup confirmations by agent lane ([339e06f](https://github.com/sase-org/sase/commit/339e06f651ca5268f340a4910646dc19ff491006))
* **ace:** suppress alerts for handled plans ([e8134fd](https://github.com/sase-org/sase/commit/e8134fdbdca1a527bfafe593955c719a0919b036))
* **ace:** use deep navy for TODO markers ([6d6cf8e](https://github.com/sase-org/sase/commit/6d6cf8e773f6bf192af569829262d67c3b1dc96d))
* **agent-clis:** ignore orphaned npm package listings ([dda37da](https://github.com/sase-org/sase/commit/dda37dae347caea88a124df0667d5fcbfe2e60c7))
* **agent:** keep generated family-role suffixes terminal (sase-91.5) ([d31c886](https://github.com/sase-org/sase/commit/d31c8866bb473f3cfd36b95cfe5cb0670b19d89a))
* **agents-sync:** break the agents_sync/ace.tui import cycle (sase-9r.3) ([87d46a6](https://github.com/sase-org/sase/commit/87d46a659e4386136acf96e2ccb74f0eba836148))
* **agents-sync:** diagnose inventory classifier failures (sase-91.2) ([ae44c73](https://github.com/sase-org/sase/commit/ae44c73b551a0e9fb88c7a81ccc4f7257d4127dc))
* **agents-sync:** ignore owner-observed v1 updates (sase-92.2) ([aed7fa5](https://github.com/sase-org/sase/commit/aed7fa5efb68df509475ce1b3d1647b9b694f460))
* **agents-sync:** prevent future import timestamps (sase-9o.3) ([e0fbcec](https://github.com/sase-org/sase/commit/e0fbcecc8f3b4709c1aeea7fa9769fbce8064e72))
* **agents-sync:** prevent imported history amplification (sase-9o.4) ([2a40c25](https://github.com/sase-org/sase/commit/2a40c2530ce18b4c3369d15e9cc9b0f7b53e279f))
* **agents-sync:** skip tribe wait relationships (sase-9v) ([9e63c5e](https://github.com/sase-org/sase/commit/9e63c5eb785c8ed009e74841cf4cc301a5bbcc9d))
* **agents:** force-stage ignored sidecar payloads (sase-92.3) ([5004fe8](https://github.com/sase-org/sase/commit/5004fe81ba42012fc7fc09a09bf7078709617c92))
* **agents:** normalize machine-hood presentation (sase-8k) ([61395b8](https://github.com/sase-org/sase/commit/61395b8ab1fa2f2de8158f677abd2ae9017d4b6d))
* **agents:** prevent owner duplicate legacy imports (sase-92.4) ([5965216](https://github.com/sase-org/sase/commit/596521653e220b29c3155b53aa464226b99a99ba))
* **agents:** quarantine failing publication requests (sase-91.3) ([7bb485d](https://github.com/sase-org/sase/commit/7bb485d33f966a4471cd67c59a20b0b4e6c0982e))
* **agents:** recover historical sidecar publications (sase-91.6) ([447d96e](https://github.com/sase-org/sase/commit/447d96e09d692f77b72783ca7e78c5e8bce41c3d))
* **agents:** repair future-dated imported state (sase-9o.5) ([7ae51f4](https://github.com/sase-org/sase/commit/7ae51f46342ce4ce6cc86665d748f61f22b84734))
* **agents:** support same-user multi-machine imports (sase-8v.10) ([e47f240](https://github.com/sase-org/sase/commit/e47f240e14efb6cc9c3c8112c756df4bcb09c0ae))
* **agent:** tolerate un-globalizable legacy names in registry rebuild ([1a6d7b0](https://github.com/sase-org/sase/commit/1a6d7b061507ba1b67fc8654f64d27324e2110e6))
* **axe:** fit bead_store_refresh chop inside its time budget (sase-9v.6) ([54f4203](https://github.com/sase-org/sase/commit/54f42034b81f28bc6b08294c43505cec8c2b2890))
* **axe:** remove persistent tab guide hint ([8fc6a2a](https://github.com/sase-org/sase/commit/8fc6a2a901730ba20bf9b1339ae07d9a43f584e4))
* **bead:** confirm destructive forced-reuse cleanup ([485e562](https://github.com/sase-org/sase/commit/485e5624ef9630119bd3e4fa2a11c0d1f51d743e))
* **bead:** emit byte-identical JSONL from both store writers (sase-9x.2) ([19bb1ad](https://github.com/sase-org/sase/commit/19bb1adc74f8194b0d451936f07e7291bb473723))
* **bead:** limit epic phase planning to large work ([50e5693](https://github.com/sase-org/sase/commit/50e5693e88ce5723c45d1dac3fbcec7ce0095fb5))
* **bead:** persist canonical plan references (sase-9z.3) ([b3a4bc2](https://github.com/sase-org/sase/commit/b3a4bc282b0fd04bc849797b00dd0d8570282cef))
* **bead:** reconcile claim residue and flag stuck beads (sase-9v.3) ([896e024](https://github.com/sase-org/sase/commit/896e024004e1ce40a5247f7c17583a092d24b8d2))
* **bead:** relax legacy phase size constraints (sase-8w.7.1) ([b638df3](https://github.com/sase-org/sase/commit/b638df32f1709b59c8c3bed44f6d37abe9b227d3))
* **bead:** resolve sidecar store from plain checkouts (sase-a0.1) ([26ead3f](https://github.com/sase-org/sase/commit/26ead3f39ac89b6969b71ce1872edab834760aee))
* **bead:** restore epic work CLI contracts (sase-9v.7) ([1f1c406](https://github.com/sase-org/sase/commit/1f1c4064c705581b23dd672dc4f8c47466503350))
* **beads:** diagnose concurrent claim recovery residue (sase-9r.8) ([616657f](https://github.com/sase-org/sase/commit/616657f2b0cf4cef50cc8914d0721716b11a63a0))
* **beads:** harden managed sync worker hygiene (sase-9v.5) ([241de00](https://github.com/sase-org/sase/commit/241de00c2ee716e9daf0f20aee70881801e41683))
* **beads:** integrate epic changes with landed work (sase-9r) ([45edb9a](https://github.com/sase-org/sase/commit/45edb9a268896e7fe1985504ac65dce40b1eacb9))
* **beads:** persist and safely release waiting claims (sase-9v.2) ([a91b71d](https://github.com/sase-org/sase/commit/a91b71d3702a24a8dde5a1a1fb0f8c811bc4f143))
* **beads:** publish epic graph before worker launch ([fd9db05](https://github.com/sase-org/sase/commit/fd9db0526eaf20827ab198ddbfc726707bbc43b4))
* **beads:** publish runner claim transitions synchronously ([7ba445a](https://github.com/sase-org/sase/commit/7ba445a4514e0562bd2535c7d8482c1fc7b34cf6))
* **beads:** recover from transient sync divergence (sase-9x.4) ([5993058](https://github.com/sase-org/sase/commit/59930584cdf8a46d651d246cdaa763c88ada407e))
* **beads:** recover waiting claims after publication lag (sase-94.1) ([a8b63c2](https://github.com/sase-org/sase/commit/a8b63c27f0fb89b04f4bd214b556685925bd39f4))
* **beads:** serialize mutation and commit under store lock (sase-9r.1) ([a89f4c0](https://github.com/sase-org/sase/commit/a89f4c05948e6ad748fee395754ad7738d45cd5e))
* **beads:** serialize the launch-claim mutation under the store write lock (sase-9v.1) ([26c26fe](https://github.com/sase-org/sase/commit/26c26fec23542b62be756aad42c559a868e12f73))
* break agents sync ace import cycle (sase-9s.1) ([a3b3ff7](https://github.com/sase-org/sase/commit/a3b3ff7bf14b1fd6fb555c6c7c2703c152e5e4d9))
* clean up production temp artifacts (sase-96.4) ([c3316b7](https://github.com/sase-org/sase/commit/c3316b71948506cebdb15da499b171f02d1ce584))
* **config:** make machine identity optional per document ([cf8832b](https://github.com/sase-org/sase/commit/cf8832b7e8bf6a99183e9de9535945ceb3ce3c5d))
* **config:** wrap j and k tree navigation ([ea575c7](https://github.com/sase-org/sase/commit/ea575c7c1f366d3a2b8d0885c987bcb5c710935b))
* defer epic completion notifications until launch settles ([c9f2450](https://github.com/sase-org/sase/commit/c9f2450ae0d1c0a183fa31f680670b281d2ae04b))
* Enable --agents sidecar repo on this repo ([2272e9f](https://github.com/sase-org/sase/commit/2272e9f4b708daabed879b68cdea11757ddff89c))
* fail closed on sdd git probe errors (sase-9v.4) ([f3680c3](https://github.com/sase-org/sase/commit/f3680c3c9d0a8a1680887a8754abbf288e4392bb))
* finish claimed status landing cleanup (sase-8y) ([d0495f1](https://github.com/sase-org/sase/commit/d0495f1cba07b4706cc7696a1561d9fa0a0c3343))
* give the agent-launch prompt file a reapable home (sase-96.8.2) ([63b9d88](https://github.com/sase-org/sase/commit/63b9d8814590ea857e4675b5b55099a0d475f3c4))
* guard the event-store manifest repair write path (sase-9l) ([84f6619](https://github.com/sase-org/sase/commit/84f6619ec4e9478559701a049c95e8ea60036498))
* **history:** discover imported chat transcripts (sase-90.1) ([e7da5cd](https://github.com/sase-org/sase/commit/e7da5cd18d378bf10a0289e849f028816e2b813f))
* honor projected buckets in clan counts ([b3f400c](https://github.com/sase-org/sase/commit/b3f400c8ea1e621da88f1c892a594e39438de0ee))
* **init:** warn instead of blocking when the agents sidecar has no project key (sase-93.1) ([53d25b3](https://github.com/sase-org/sase/commit/53d25b3173ae0df30909d3f4e256c9d4d52d08f6))
* make visual convergence robust under CPU contention (sase-9y.2) ([a0636fc](https://github.com/sase-org/sase/commit/a0636fcbbaf268c80434ef429b0caba6ccd19281))
* **models:** rename user alias ownership to Custom ([90e268d](https://github.com/sase-org/sase/commit/90e268d045fc1b184d4d65eed4db5c7c67a1397f))
* **notifications:** dismiss settled gate notifications ([7f688d0](https://github.com/sase-org/sase/commit/7f688d070d0240af65bd82379d47bb4c69f356c6))
* persist clan summary stderr diagnostics (sase-8i.1) ([a75a477](https://github.com/sase-org/sase/commit/a75a477d8b9511cdf9b16685828d9d94dfd8b037))
* persist waiting bead claims through shutdown (sase-94.2) ([42b9316](https://github.com/sase-org/sase/commit/42b93168e5d1bec586d9487b0c16adff7ff3994d))
* **plugins:** detect receipt-owned installations ([ef2cc16](https://github.com/sase-org/sase/commit/ef2cc164e8ed6269775605c0ce2269b3c7120c91))
* preserve bead commits before sidecar workspace reset (sase-9x.3) ([0b51af9](https://github.com/sase-org/sase/commit/0b51af99549e2a3cfbb1fc7201cb0faf9ba4a19a))
* preserve bead notes during commit workflows ([396e272](https://github.com/sase-org/sase/commit/396e27268fe1ba4e4411e851375e1451ee80c296))
* preserve launch xprompt metadata during deferred expansion ([4df8b4e](https://github.com/sase-org/sase/commit/4df8b4e7c27fbda2ad5dbd9b146342627cf2206c))
* preserve proposal associations from agent metadata ([3e06256](https://github.com/sase-org/sase/commit/3e06256aa6f65243bb424b91b8ed18ab865c5e11))
* propagate default overrides through alias resolution ([a0b40ef](https://github.com/sase-org/sase/commit/a0b40ef37c1ec7afd8581fb31dd38ff0ca372937))
* reap stale pytest scratch entries (sase-96.8.4) ([88cb087](https://github.com/sase-org/sase/commit/88cb0876d1990363dae046381a6ce22eab5de516))
* reconcile missing pre-launch bead claims (sase-94.3) ([2b7b71b](https://github.com/sase-org/sase/commit/2b7b71b608e7a943d3aa6dd3115d48b829e23130))
* record dismissed identities during v2 import (sase-9o.2) ([6363f22](https://github.com/sase-org/sase/commit/6363f22db23d6c6a90585dbad53d0a741d962d99))
* recover interrupted agent families during forced reuse ([5fb55a5](https://github.com/sase-org/sase/commit/5fb55a5a98e91fbc807d3e008f3af55d3d3863a1))
* refresh bead stores for active waiters ([f429d11](https://github.com/sase-org/sase/commit/f429d118c2433f99522be4e6a7138aa071f5ea6e))
* refresh clan summaries after workspace preparation (sase-8i.3) ([865d5c1](https://github.com/sase-org/sase/commit/865d5c191e7fcecf6f7f96c9f1ba2732d6436d6b))
* resolve epic launch workspace from shared env contract (sase-9s.3) ([657f14f](https://github.com/sase-org/sase/commit/657f14f778c6dcaf636f9b6ec2e8a73cefd1440c))
* restart exact agent family members ([330c258](https://github.com/sase-org/sase/commit/330c25856f83465adfefe190495f6ddbc3369867))
* restore epic clan summaries ([a20e82d](https://github.com/sase-org/sase/commit/a20e82dca2d2867920ad7534447c806845258fe5))
* **runner-slots:** defer deprioritized admission (sase-9k.1) ([43ba5da](https://github.com/sase-org/sase/commit/43ba5daf72c0d112902fe4b33fbc9bc07e4a86c1))
* **sdd:** ignore rerere for managed git commands (sase-9r.4) ([b8ec882](https://github.com/sase-org/sase/commit/b8ec882ce10a20b445845667fd923792b7e19f94))
* **sdd:** reap safe recovery residue (sase-9r.7) ([9c845cb](https://github.com/sase-org/sase/commit/9c845cb3add536e74a0ce3d850a67ec4a9748bf2))
* **sdd:** stop reporting git probe failures as "no conflicts" (sase-9r.3) ([a4b9515](https://github.com/sase-org/sase/commit/a4b9515b5b3cb8c626a291e6324fca68b86eec71))
* **sdd:** throttle repeated failed sidecar integrations (sase-9r.5) ([b9bcae7](https://github.com/sase-org/sase/commit/b9bcae7fee0d23ffcb881cfd921e3c30bf3c2d79))
* **sdd:** verify owned rollback invariants (sase-9r.2) ([69c6b67](https://github.com/sase-org/sase/commit/69c6b67d4231d56c950236e4de0c2d7b4b2fd56d))
* **sdd:** wait for the store write lock in worktree mutators (sase-9r.6) ([eee631d](https://github.com/sase-org/sase/commit/eee631d3b032f074ed395ecc0c38ec7692210d76))
* show source plan basename in approval toasts ([7ba379f](https://github.com/sase-org/sase/commit/7ba379f49d84512ca1f3ef6f597955e7be1a9c6f))
* silence terminal bells for plan reviews ([8add798](https://github.com/sase-org/sase/commit/8add7988232a70a8dbd39fe1b9fb71b891c96afe))
* snapshot epic plans before clan launch (sase-8i.2) ([b825a0d](https://github.com/sase-org/sase/commit/b825a0db49967ac243be2721eef722b5612c10a9))
* stop the test suite from writing into the managed temp root (sase-96.8.3) ([bd16432](https://github.com/sase-org/sase/commit/bd16432c966c92dc66f4a31489eef8214f4d73a1))
* suppress completion bell during handoffs ([6307a3f](https://github.com/sase-org/sase/commit/6307a3fc3bc4b4b832ce8152e44fa70d2e382e25))
* **test:** move pytest scratch off tmpfs (sase-96.1) ([15ea05a](https://github.com/sase-org/sase/commit/15ea05af681131a2266531414b69cf823d574520))
* **tests:** contain bead resolution in pytest sandbox (sase-9l.1) ([5ae5e9a](https://github.com/sase-org/sase/commit/5ae5e9a4dcdc51c496009259baa4e0625ba44b9c))
* **tests:** deny unsandboxed pytest bead-store writes (sase-9l.2) ([289222b](https://github.com/sase-org/sase/commit/289222b19ca37c8fdf34a86112aa3997807abf96))
* **tui:** align plan gate clipboard shortcuts ([9c40093](https://github.com/sase-org/sase/commit/9c400939a9202481f53238ea9410d2442d3632b4))
* **tui:** align TODO annotations with running gold ([3543cd2](https://github.com/sase-org/sase/commit/3543cd2a43ef0da449b2ff5591844a9c034d7802))
* **tui:** avoid terminal task mirror races (sase-95.8) ([54e0978](https://github.com/sase-org/sase/commit/54e097800228f0779af2d98db6717a55efaccec8))
* **tui:** contain unhandled vim mode keys ([e40bce9](https://github.com/sase-org/sase/commit/e40bce924375f7bf7d8690caf9f92c0b1f693e1c))
* **tui:** flag missing agent wait targets ([d27422f](https://github.com/sase-org/sase/commit/d27422fd7e8007c5b3073f4ce9bc0d083d17b571))
* **tui:** highlight agent runner limit ([f943218](https://github.com/sase-org/sase/commit/f943218ef38a0eb9a42f7630ddec8ff3f4624394))
* **tui:** highlight selected collapsed tribe titles ([7630f7f](https://github.com/sase-org/sase/commit/7630f7f26273eb6c02ee97c56ea833e8258d5ffd))
* **tui:** include collapsed clan lanes in completions ([467fc76](https://github.com/sase-org/sase/commit/467fc76b82222a7d44fd64cafdc5d86478746632))
* **tui:** keep artifact selection in viewport ([01b06e3](https://github.com/sase-org/sase/commit/01b06e3d6507c68b3ae9a1ccebc6859a13e40c66))
* **tui:** keep TODO markers legible ([627b0b3](https://github.com/sase-org/sase/commit/627b0b377c15b3c7ad322333fc38303b840defe7))
* **tui:** normalize clan references across machine hoods ([0d3955e](https://github.com/sase-org/sase/commit/0d3955e6c2e5e6493cd1c42c12da5f4ed92f4673))
* **tui:** offload legacy epic approval launch (sase-9v.8) ([0c051a0](https://github.com/sase-org/sase/commit/0c051a009d8ca740c801bb9d1ef9fe3281ba94c3))
* **tui:** restore Agents parent navigation ([dd16a88](https://github.com/sase-org/sase/commit/dd16a883e31138187f91bdce092b29897ec449ff))
* **tui:** show clan members before summary ([7917c0f](https://github.com/sase-org/sase/commit/7917c0f79fece6d823e200233d1cc8220ab66027))
* **tui:** soften TODO annotation styling ([ac9fb40](https://github.com/sase-org/sase/commit/ac9fb4081c92e903639142c6d03c52a303c20375))
* **vcs:** make commit collection truncation-aware (sase-8h.2) ([f9345e7](https://github.com/sase-org/sase/commit/f9345e7c11bedb3b947dc2e17ae65d7b2e6d6d72))
* **vcs:** re-anchor date filter bounds (sase-8h.1) ([08f91b4](https://github.com/sase-org/sase/commit/08f91b43df3ccac5f40b2d7a334973ed7ddd8e85))
* **wait:** persist wait priority explicitness (sase-9k.2) ([64ac40d](https://github.com/sase-org/sase/commit/64ac40d38983ea26c6ed2d983813495e74058809))
* **xprompt:** preserve fork query spacing ([05b45da](https://github.com/sase-org/sase/commit/05b45da0193c11c084c80673208a38db045fc6a5))
* **xprompt:** read the new placeholder candidate shape from sase-core (sase-9m.1) ([26b4a4c](https://github.com/sase-org/sase/commit/26b4a4cc936d3270f654c6ab20fe7b5e1ec75f36))
* **xprompts:** deprioritize epic agents ([5c7f258](https://github.com/sase-org/sase/commit/5c7f25834f1d4ae04bed2289cee9202f794dd7c1))


### Performance Improvements

* **agents-sync:** reduce publication drain lock work (sase-91.4) ([1449c9b](https://github.com/sase-org/sase/commit/1449c9bb7b46348f391ffdbb8fffdd6d5a38384d))
* reuse fresh roots for update previews ([e2ba793](https://github.com/sase-org/sase/commit/e2ba79309adfa14722851c93c13c29c8c468be83))
* reuse machine identity during registry rebuild ([9e35517](https://github.com/sase-org/sase/commit/9e355175c9af4fe649101a1990d3c1ef9955ace4))
* **test:** avoid copying large directory map assets (sase-96.2) ([7340235](https://github.com/sase-org/sase/commit/7340235b22b94173d94dc752127932895552f749))


### Documentation

* **ace:** describe lane fold behavior in help and agent docs (sase-99) ([ffc7aa8](https://github.com/sase-org/sase/commit/ffc7aa874735fb008fa5a489fa254e36c02092ae))
* **agents:** document the agent index repair subcommand (sase-9o) ([eda646e](https://github.com/sase-org/sase/commit/eda646ec02177d9e28ebb03cb322a68b52bb2f9c))
* align behavior reference with current implementation ([bf1570a](https://github.com/sase-org/sase/commit/bf1570adbe72af0eb451f61e0068157e98f19965))
* align operational guidance with current behavior ([56cb94f](https://github.com/sase-org/sase/commit/56cb94f058a948705d15a8b6e59f55c3917fd9d4))
* align operational guidance with current behavior ([717abb8](https://github.com/sase-org/sase/commit/717abb8eca81707407fa6bd39762b8fc82d03cb9))
* **axe:** document the AXE description contract (sase-9w.7) ([3694f5a](https://github.com/sase-org/sase/commit/3694f5a484480749a938a8963d83b7b4157f25f1))
* **axe:** expand builtin chop descriptions (sase-9w.5) ([cdde8de](https://github.com/sase-org/sase/commit/cdde8dec1e7d51fca75a11facbaf453d0a31dc24))
* **beads:** align bead docs and CLI help with current behavior (sase-9v.11) ([480cbfc](https://github.com/sase-org/sase/commit/480cbfc3a99d8dbf76d7ec31c77de526af4d8838))
* **beads:** document the claimed bead status (sase-8y.7) ([3b5937b](https://github.com/sase-org/sase/commit/3b5937b986bf37520a852eb5954c8fc642d1ea9f))
* **beads:** refresh command skill accuracy ([39aa7cf](https://github.com/sase-org/sase/commit/39aa7cf172a8b34d9c5300940193cef451945249))
* clarify verified ACE workflows ([5e9170f](https://github.com/sase-org/sase/commit/5e9170f4f231a22c8aa13c88ca68221105457b53))
* document bounded runner-slot deference (sase-9k) ([4b9281d](https://github.com/sase-org/sase/commit/4b9281d3d7d92f0de8a03c8bdea802d28eea6901))
* document capitalized snippet alias parity across surfaces (sase-8u.3) ([ec229ad](https://github.com/sase-org/sase/commit/ec229ad32c315ccd7b0754dd1140fe9cf46610eb))
* document raw placeholder prompt inputs (sase-9q.7) ([a397e5b](https://github.com/sase-org/sase/commit/a397e5b6bef5c0d46749bb8e47c8c9ed6b1a856c))
* document templated chop member names in the plugin guide (sase-9n) ([4b9a5be](https://github.com/sase-org/sase/commit/4b9a5bec2bf492792020be3fb71ef61a9a48a0a5))
* reconcile manuals with five-size phase routing (sase-8w.7.2) ([39c9fe7](https://github.com/sase-org/sase/commit/39c9fe7dca53caf21b23e86049efeb346219d4ff))
* reconcile phase-size guidance (sase-8w.7.4.1) ([4c3fde9](https://github.com/sase-org/sase/commit/4c3fde93ece244e409c9514f390b18e8e166f1c9))
* record final visual contention baseline (sase-9y) ([a947469](https://github.com/sase-org/sase/commit/a947469eece2988bdfff48bd6ee40b5a9701172f))
* refresh current user workflows ([63ce10c](https://github.com/sase-org/sase/commit/63ce10cf03df26416a66c3e099be6ffdb207b2b5))
* refresh guides for current behavior ([d369a98](https://github.com/sase-org/sase/commit/d369a98ce19183d408cba7f9233388cad2c2ce8a))
* refresh guides for current SASE behavior ([b987b8b](https://github.com/sase-org/sase/commit/b987b8b5ce928edc4af51c5987d0c80cf385bd6a))
* refresh user-facing behavior reference ([de5581d](https://github.com/sase-org/sase/commit/de5581d8c06dd70976196544dba2b0231f97cde6))
* refresh user-facing documentation ([b0f4918](https://github.com/sase-org/sase/commit/b0f491800236604b55a0e68371d84818b970351c))
* standardize epic phase description prefixes ([4b6c2c3](https://github.com/sase-org/sase/commit/4b6c2c3cadf2ea71e9ff1d9f99df0f8ca5cb0a53))

## [0.11.1](https://github.com/sase-org/sase/compare/v0.11.0...v0.11.1) (2026-07-18)


### Bug Fixes

* **deps:** require sase-core-rs 0.7.0 and gate published bindings ([44132ed](https://github.com/sase-org/sase/commit/44132edaa3be5fd89becade93273533b2e1471ec))

## [0.11.0](https://github.com/sase-org/sase/compare/v0.10.2...v0.11.0) (2026-07-18)


### ⚠ BREAKING CHANGES

* **gates:** New gate request specs must use schema_version 3 and declare primary_branch as one complete branch in canonical query order.
* **ace:** Ctrl+T no longer toggles xprompt/snippet mode in the unified save panel; use Ctrl+X instead.
* **mobile:** Mobile gate actions now accept selected_option_ids through the generic gate-action operation instead of kind-specific choice payloads.
* **notification-gates:** producer responses now use selected_option_ids and option_results instead of legacy choice and extra fields.
* **cli:** Use sase gate create and sase gate wait instead of the removed notify gate forms.
* **notification-gates:** Notification gates now require schema version 2 with query, options, and optional groups; legacy choices, extras, and choice execution APIs are removed.
* **agent:** Bare family roots are now persisted as suffixed members; the unsuffixed name is reserved for the family container.
* **bead:** Epic land agent names now use the `<epic_id>.land` form.
* **xprompt:** The %family and %f launch directives are removed; use %clan:name or %c:name instead.
* **agent:** %group, %g, and `sase agent tag` are removed; use %tribe, %t, and `sase agent tribe` instead.
* **xprompt:** Xprompt invocations now reject surplus positional values unless the final declared input is repeatable.
* **telemetry:** The telemetry export-config command and bundled Prometheus, Grafana, and Pushgateway assets have been removed.
* **telemetry:** Telemetry commands no longer accept Prometheus source or charts flags, and snapshot no longer supports Prometheus-format output.
* **telemetry:** The push_metrics and register_push_on_exit APIs are replaced by flush_metrics and register_flush_on_exit.
* `sase artifact` is now `sase artifact-file`, and explicit artifact configuration and API names now use `artifact_file` terminology.
* resolve_content_layout and resolve_content_layout_from_cwd are no longer exported.
* **agent-family:** kind: agent_family xprompts and plan approval --with/--without member selection are no longer supported.
* Tale and epic plans must include a non-empty title in YAML frontmatter.
* #!sase/toobig_split is no longer bundled with SASE.
* **ace:** On the Agents tab, H and L now collapse and expand the focused panel instead of changing all nested fold levels.
* Non-GitHub HTTP(S) sidecar remotes are no longer accepted; configure an SSH or local Git remote instead.
* Epic approvals no longer launch bd/new_epic, and the implicit @epic_creator model alias is no longer available. Select land and phase models in structured epic plan frontmatter instead.
* **repos:** Managed projects must declare a research sidecar explicitly, such as in global repos.sidecar configuration.
* **cli:** The `sase sdd` command has been removed; use `sase plan links` and `sase plan search --kind prompt` instead.
* **cli:** Remove sase init sdd and sase init workspace. Use sase repo init or its sase init repo alias instead.
* **cli:** `sase repo list` now defaults to the current project instead of all enabled projects. Use `sase repo list --all` for the previous scope.
* **sdd:** Python APIs, provider hook names and options, and newly written SDD store records now use sidecar terminology; integrations must migrate companion names to their sidecar equivalents.
* **tui:** Admin Center tab cycling moves from brackets to Tab and Shift+Tab; Projects state cycling moves from Tab and Shift+Tab to brackets.
* Standard derived agent names now use `.f0`, `.w0`, and `.r0` for numeric IDs, adding the dash only for letter-leading IDs such as `.f-a`; noncanonical historical spellings are no longer matched as planned descendants.
* Invoke the workflow as #!sase/toobig_split; the #!sase/pylimit_split name is no longer available.
* **memory:** Memory write no longer accepts --keyword, and xprompt configuration no longer accepts the keywords field.
* **ace:** The reset_file_trim and show_all_file_lines ACE keymap settings and their corresponding actions are removed.
* Plans and research companion clones now live at `sase/repos/plans` and `sase/repos/research` instead of repository-named paths.
* Numbered-workspace linked repositories now materialize under `sase/repos/linked/<name>` instead of `sase/repos/<name>`.
* Configured linked repositories now materialize lazily unless their entry sets auto_clone: true.
* **sdd:** Repository plans are discovered, linked, and written only under plans/; legacy tales/ and epics/ filesystem aliases are no longer accepted or migrated by sase sdd init.
* **sdd:** `sase init --yes` no longer authorizes creation of a missing GitHub SDD companion; creation now requires interactive y/yes confirmation.
* Rename precommit_command to commit_hooks.before.
* `memory.enabled` no longer authorizes repository management. Set `is_sase_managed: true` in the target repository's `sase.yml` instead.
* **memory:** Projects that rely on generated project memory or a managed root AGENTS.md must set memory.enabled: true in their local sase.yml.
* **workspaces:** Remove linked_repos[].workspace.strategy; numbered linked repositories now use <host_workspace>/.sase/workspaces/<repo>.
* /bob_dataview is no longer distributed by SASE; use /bob_query.
* **vcs:** sase vcs log no longer includes separate SDD history by default; pass --sdd to include it.
* **vcs:** `sase vcs log -a` now selects all projects. Use `-A` for author filtering; `--author` is unchanged.
* **xprompt:** The hg workspace xprompt is no longer recognized, and affected workflows no longer default vcs_type to hg.
* **sdd:** `sase sdd migrate` and `sase sdd init --storage` are removed; workspace providers now control and materialize SDD storage.
* legend/myth SDD directories, legend plan approval actions, legend bead tiers, epic_count metadata, and legend work commands are no longer supported. Use tales, epics, research notes, and plan/epic bead tiers instead.
* The built-in #cd launch form and SASE*CD*\* environment contract are removed. Use a registered workspace provider ref such as #git:home instead.
* **agent:** Newly generated fork, wait, and retry derived names now render as examples like foo.f-0, foo.w-0, and foo.r-0 instead of foo.f1, foo.w1, and foo.r1.
* sase.integrations.agent_status_groups no longer exports group_agent_statuses, AgentStatusGroup, or _agent_status_bucket.

### Features

* **ace:** add alias options to model picker ([a27479e](https://github.com/sase-org/sase/commit/a27479e795300e33aff8d1d5cd94ffe437e36334))
* **ace:** add Bugs artifact pane (sase-69.5) ([2511b71](https://github.com/sase-org/sase/commit/2511b71875900273b78c42af9ca43b586e7cabb8))
* **ace:** add clan hierarchy to agents tab (sase-6n.6) ([21d995c](https://github.com/sase-org/sase/commit/21d995ce59c5b684e06ee947288e95dd07bec0b8))
* **ace:** add Ctrl+X xprompt snippet chord ([2ac99da](https://github.com/sase-org/sase/commit/2ac99dab516508ae27d12fe22ebd1f292b5ce1be))
* **ace:** add fast navigation to artifact lists ([abf5cdc](https://github.com/sase-org/sase/commit/abf5cdcd51a2d3d40f2f446d4019bedb336aafbc))
* **ace:** add gate debug view ([2cab7b0](https://github.com/sase-org/sase/commit/2cab7b07973b70291a6c923992968ec45243586e))
* **ace:** add inline xprompt property editing ([7776f7a](https://github.com/sase-org/sase/commit/7776f7a85726f3e05ea6b0fd135ee9b65cd1b1cb))
* **ace:** add interactive Plans artifacts pane (sase-69.6) ([69fe487](https://github.com/sase-org/sase/commit/69fe487c618a7427f5c4b4913ce641479fd1ec34))
* **ace:** add jump hints for collapsed agent panels ([494d5c5](https://github.com/sase-org/sase/commit/494d5c5632822b3efd5b3c913907915949d59a59))
* **ace:** add model alias buckets ([1654299](https://github.com/sase-org/sase/commit/1654299f0297286883d6802e52c070546214c50d))
* **ace:** add numbered artifacts and saved query picker ([8359294](https://github.com/sase-org/sase/commit/835929471ffe7618503a3d3b5fa193206136a5ca))
* **ace:** add periodic update checks ([138a600](https://github.com/sase-org/sase/commit/138a600ac36a68141a8719c9c45fc9786f5945a2))
* **ace:** add phase bead context lane ([eab9e3f](https://github.com/sase-org/sase/commit/eab9e3f34810dc7f92a3a3c5adeaf9c27631db5a))
* **ace:** add prompt-local word completion ([c21db1e](https://github.com/sase-org/sase/commit/c21db1e560bcd623763eb2af150ae3c8e2f96ecf))
* **ace:** add ranked artifacts context lane ([6b84f2a](https://github.com/sase-org/sase/commit/6b84f2add16e3e28af29837d2c6189ab9b76c1ed))
* **ace:** add repository and workspace inventory tabs ([83138f0](https://github.com/sase-org/sase/commit/83138f0bd0baa85bd2cdbcd18c4d257d30ab0c90))
* **ace:** add role-aware epic phase metadata ([bbb01e1](https://github.com/sase-org/sase/commit/bbb01e1faec78ac570ff58342aa201aec0cb75b2))
* **ace:** add selected panel folding mode ([b02ae14](https://github.com/sase-org/sase/commit/b02ae14fb4625e3940ae5e5d25835fd48ec6ba9e))
* **ace:** auto-expand panels for agent jumps ([9624746](https://github.com/sase-org/sase/commit/9624746a4948f0935eebe8778c89cb33ea6a660f))
* **ace:** clean up collapsed agent panels ([cd31c08](https://github.com/sase-org/sase/commit/cd31c083075dd2787525dc85c4872f928805a8cf))
* **ace:** collapse focused agent panels ([5e9bfa1](https://github.com/sase-org/sase/commit/5e9bfa1987f0b9ba998173e4e3e5e23793b10f85))
* **ace:** compact parallel family status counts ([45c04ae](https://github.com/sase-org/sase/commit/45c04ae99c7c8738d2b2f66271a37ea82f915b77))
* **ace:** compact phase bead identity header ([f18fcfa](https://github.com/sase-org/sase/commit/f18fcfae17f30b07c5d9dae46b3192ceff42f028))
* **ace:** distinguish agent family rows ([4c20b1b](https://github.com/sase-org/sase/commit/4c20b1bdb1d62ceea0c52532cff6691e9c198b23))
* **ace:** enrich agent view hints asynchronously ([5346d2e](https://github.com/sase-org/sase/commit/5346d2edf32ddae932d19009650dce2448401365))
* **ace:** highlight xprompts in agent panels ([2fd3c84](https://github.com/sase-org/sase/commit/2fd3c84a703fd55c6883105f802ecfc2343c19dd))
* **ace:** label axe daemon status badge ([6e3d7df](https://github.com/sase-org/sase/commit/6e3d7df86332f9935a4ecf995e8b8ca2cb5a7d61))
* **ace:** label primary gate footer action ([6fd595d](https://github.com/sase-org/sase/commit/6fd595daac75ab88e60d84a041a3c8c52fb43f43))
* **ace:** make commits actions configurable (sase-69) ([54f75ab](https://github.com/sase-org/sase/commit/54f75ab41f768e8223b80d778169e1aea8513c88))
* **ace:** make update check interval configurable ([147090d](https://github.com/sase-org/sase/commit/147090de1a6cbac42d11c2efa30dbd321c85fa81))
* **ace:** merge plan into SASE context ([125f342](https://github.com/sase-org/sase/commit/125f342cb18e2a5bee33370948a204733c25e948))
* **ace:** navigate agent metadata sections ([a434e09](https://github.com/sase-org/sase/commit/a434e09e675c08adb8567cb342add9add087e120))
* **ace:** navigate unread agents in collapsed clans ([fd31c86](https://github.com/sase-org/sase/commit/fd31c8691584969cb53ee7757d4eade5ed940aba))
* **ace:** persist Agents fold state across sessions ([d1a3bda](https://github.com/sase-org/sase/commit/d1a3bdaf1d32b1a6b01e5605c1d603f09eef63da))
* **ace:** place artifacts directly below plan ([b7b64b7](https://github.com/sase-org/sase/commit/b7b64b7199510be56c5638d0302bc2d002e31a7c))
* **ace:** polish artifacts tab integration (sase-69.7) ([6bc7613](https://github.com/sase-org/sase/commit/6bc7613fae64f1f0040d8200dcfe8773e116ce7c))
* **ace:** polish plan lane visuals ([38760e2](https://github.com/sase-org/sase/commit/38760e2f2eb9ef47bebbb1c89d4ec97624e8e598))
* **ace:** redesign projects inventory pane ([9d98417](https://github.com/sase-org/sase/commit/9d98417d5ea89ef32ea91798aac68047b6f127a0))
* **ace:** remove file panel trimming ([f115c3c](https://github.com/sase-org/sase/commit/f115c3c5babe3c4f40c742092c9f532bb1fd2b81))
* **ace:** render clan and family identities name first ([91959c1](https://github.com/sase-org/sase/commit/91959c10cdd6241b649439b6f92912d323c35d27))
* **ace:** render complete responsive plan goals ([2394f83](https://github.com/sase-org/sase/commit/2394f83054581ff1babff2b03fd97f3618c1f1cd))
* **ace:** render gates from option branches (sase-6p.4) ([dc183a7](https://github.com/sase-org/sase/commit/dc183a727b7cad626cbc27cb78fe30293bd3bcef))
* **ace:** scaffold the Artifacts tab (sase-69.1) ([a626470](https://github.com/sase-org/sase/commit/a62647069c6787b1fb9a7d65c5c8fb8ed55c5ac1))
* **ace:** show associated plan goals in agent details ([5ac12cc](https://github.com/sase-org/sase/commit/5ac12ccff8c0a8aa145b373703975aef37952c28))
* **ace:** show associated plan metadata ([75bf5c7](https://github.com/sase-org/sase/commit/75bf5c791c302823415a4efa4b277740fc7e79ff))
* **ace:** show epic phase roadmaps ([4779fcb](https://github.com/sase-org/sase/commit/4779fcbc57e6ead87c01e110e9ca85493d2d23df))
* **ace:** signal core rebuilds in update badge ([97ffad6](https://github.com/sase-org/sase/commit/97ffad6cf262cc964e5f4643bd5a9ad09018b695))
* **ace:** summarize collapsed agent panels ([328b3b5](https://github.com/sase-org/sase/commit/328b3b5208c5a005b1db105669769e29f27f7338))
* **ace:** support composable notification gates (sase-6i.5) ([9ab0c0c](https://github.com/sase-org/sase/commit/9ab0c0c58eb589ac70b7e05f2f469614b4201395))
* **ace:** support exact-time model overrides ([bec37b5](https://github.com/sase-org/sase/commit/bec37b564563dab50b3ef7917f99d6ef64facf57))
* **ace:** support external repository workflows (sase-5y.4) ([69e8b84](https://github.com/sase-org/sase/commit/69e8b847f178bc398c47d5e362711b928d4ead46))
* **ace:** view prompt jump images in terminal ([64f5608](https://github.com/sase-org/sase/commit/64f560802da4f19a7acf916d3107f1cdc08e89c6))
* Add /sase_project and /sase_repo skills ([d72a4ee](https://github.com/sase-org/sase/commit/d72a4ee42b61e04b74c79a7ef3055b3bcd2b3cea))
* Add `sase init -y` as postcommit hook for sase ([e0f7fa0](https://github.com/sase-org/sase/commit/e0f7fa05d1d8a46f6666f190470c5146cd409def))
* add big epic lander alias configuration (sase-6q.2) ([02bb467](https://github.com/sase-org/sase/commit/02bb4670b5feb48992717f1b59f7410a68a952d5))
* add commit filter query language (sase-6s.1) ([d857fc7](https://github.com/sase-org/sase/commit/d857fc7c62feafc37e8be5678b5aab8f602efda4))
* add concurrent agent limit directive plumbing (sase-5u.1) ([c321764](https://github.com/sase-org/sase/commit/c321764e3379fcb71c96df83b9242a83c1d700fd))
* add custom notification gate skill (sase-6i.7) ([d468f87](https://github.com/sase-org/sase/commit/d468f873849798025cfdb679228bc1041b17a837))
* add first-class fakey provider integration (sase-5o.3) ([7ecc017](https://github.com/sase-org/sase/commit/7ecc0173eff527f7ec87cfd2ceea919936d7fa93))
* add gpt-5.6 model support ([848c812](https://github.com/sase-org/sase/commit/848c812bb89b63444d9a601fa1c01333ec9c495f))
* add phased commit hooks ([4f87e3e](https://github.com/sase-org/sase/commit/4f87e3e022dc15d20b96f3aa0df04b659dcec8fc))
* add shared agent list projection ([649674e](https://github.com/sase-org/sase/commit/649674e09ea242e5278dad9755db73cbc92ec889))
* adopt conditional separators for derived agent IDs ([b5a5cfb](https://github.com/sase-org/sase/commit/b5a5cfb659b7f08ceefc7b37a858caa2f20133fe))
* **agent-family:** remove custom lifecycle roles (sase-6e.1) ([023aadf](https://github.com/sase-org/sase/commit/023aadf1d11595e98c11387f7e0990e575f4ce57))
* **agent-scan:** expose runner slot waiting fields (sase-5u.3) ([6136c45](https://github.com/sase-org/sase/commit/6136c452923dbcac9de867a0e932aaeca9c2ea0c))
* **agent:** allocate derived names through templates ([6b51a9c](https://github.com/sase-org/sase/commit/6b51a9c86114be04752652eb1cc9faff1d6a4c20))
* **agent:** persist sequential family promotion (sase-6n.4) ([01da419](https://github.com/sase-org/sase/commit/01da41927a323008f378f2a377d76405a4731135))
* **agent:** rename plan family roots ([fbe165b](https://github.com/sase-org/sase/commit/fbe165baf8bd7b6492c06cf35da5d9ca1610c16e))
* **agent:** replace group terminology with tribes (sase-6n.3) ([01661d3](https://github.com/sase-org/sase/commit/01661d3c9b965e3fb86afd4000b2c43122f2e42f))
* **agents:** cascade cleanup across parallel families (sase-6g.4) ([c3040b9](https://github.com/sase-org/sase/commit/c3040b945696965a2c3c35ab9ac3afcd0c6fcf23))
* **amd:** support customizable agent templates ([ab0a559](https://github.com/sase-org/sase/commit/ab0a55920427b845eb14fa674239278dcf04843b))
* **bead:** carry total authored phase count (sase-6q.1) ([be14464](https://github.com/sase-org/sase/commit/be1446457e88914a3325d3db0201554a8d0475cb))
* **bead:** group epic workers into agent families (sase-6g.7) ([5601773](https://github.com/sase-org/sase/commit/5601773404cd487fe81fe5ce4cd8d380c55a7a79))
* **bead:** migrate epic launches to clans (sase-6n.5) ([d1e772f](https://github.com/sase-org/sase/commit/d1e772f646e2d421ba087569b330252d9edfabb5))
* **bead:** route big epics to dedicated lander (sase-6q.3) ([1497022](https://github.com/sase-org/sase/commit/1497022522ede983e002f8bd358f4b7d131d4914))
* **beads:** accelerate companion mutations ([438d3c7](https://github.com/sase-org/sase/commit/438d3c7e05e92e537376c03d217e38837137931b))
* **cli:** add audited repository open command (sase-5x.1) ([3a8eea0](https://github.com/sase-org/sase/commit/3a8eea0c28798a597b759cb3780a3044ecd26047))
* **cli:** add first-class gate commands (sase-6p.2) ([fe87a8f](https://github.com/sase-org/sase/commit/fe87a8fcef91529c72845762493cdac6c00ac624))
* **cli:** add plan list status and limit filters ([5e4ae55](https://github.com/sase-org/sase/commit/5e4ae55d3a066b7c178ee0a754a9b5f9acfcc15d))
* **cli:** add repository and workspace inventories ([93e2227](https://github.com/sase-org/sase/commit/93e2227a1f8db9669cef5817821fe4be6d82f351))
* **cli:** add repository path resolution ([3d103bd](https://github.com/sase-org/sase/commit/3d103bd062af0e74e69a7b75ecceec1cfc1823dd))
* **cli:** generalize repository initialization ([5db03cb](https://github.com/sase-org/sase/commit/5db03cb123e66b5f401cc0c6bfd9a86b6d2ce534))
* **cli:** launch epic work from plan files (sase-64.1) ([a6c5c69](https://github.com/sase-org/sase/commit/a6c5c69a649387b820fbdb52c02478c6ea05aaf6))
* **cli:** let init enable project memory ([ff96b2c](https://github.com/sase-org/sase/commit/ff96b2c85569e093e4a4a52562606383f8aeeffb))
* **cli:** move SDD operations under plan commands ([78057dd](https://github.com/sase-org/sase/commit/78057dd22a6f8d8d55f441d12377a15bdeda3b8b))
* **cli:** open registered and external repositories (sase-5y.2) ([61b29ff](https://github.com/sase-org/sase/commit/61b29fff98f68f058e981b584d1ae8d4f9acdea8))
* **cli:** preview init changes before applying ([f7cc1d7](https://github.com/sase-org/sase/commit/f7cc1d7f4975f925d93fd51c0180e63678910c49))
* **cli:** redesign repo list inventory (sase-5x.2) ([ffcfae3](https://github.com/sase-org/sase/commit/ffcfae364dd34df5ca2ddd5780c3a59d619caff6))
* **cli:** show titles in plan inventory ([d284ed1](https://github.com/sase-org/sase/commit/d284ed1e593db3f1f2fae7d3163289b1d9b8df41))
* Close sase-6k telemetry epic ([7dc2479](https://github.com/sase-org/sase/commit/7dc24797bd783921ed2bc7d804e6757c49187e29))
* complete notification gate compatibility rollout (sase-6e.7) ([5e234c0](https://github.com/sase-org/sase/commit/5e234c07d7d3fc1b53e146cb2d4710be5df62fbc))
* **config:** add Telegram command configuration (sase-6f.1) ([0333dcf](https://github.com/sase-org/sase/commit/0333dcf68aff95efb7f090b7e3d3cecb7f8092ea))
* **config:** generalize linked and sidecar repositories (sase-60.1) ([e7411b8](https://github.com/sase-org/sase/commit/e7411b8a89e895931c1606f7c84fada9724623c4))
* **demos:** add captioned media post-processing (sase-6l.3) ([a26d4d2](https://github.com/sase-org/sase/commit/a26d4d24453e6bab373852a93efcbf083f85790d))
* **demos:** showcase live multi-model fan-out (sase-6l.4) ([ed23598](https://github.com/sase-org/sase/commit/ed235980f058eabe99970b62777a4aec887e3c55))
* **doctor:** diagnose stale project and workspace state ([5ac9cae](https://github.com/sase-org/sase/commit/5ac9cae00422448957adbe9b288eb0eedb051232))
* **editor:** complete repeatable agent arguments (sase-6m.3) ([0de3c14](https://github.com/sase-org/sase/commit/0de3c14e23925147089050adcfd9940e95054a2a))
* enforce global runner slot admission (sase-5u.2) ([28f563f](https://github.com/sase-org/sase/commit/28f563f3fa85e683b0d6dda4cf4526e37058d167))
* enforce SSH transport for sidecar remotes ([750ad6b](https://github.com/sase-org/sase/commit/750ad6b8fa9d7b861045cc4d6d88bf1b72e5db94))
* expose canonical SASE content layout (sase-6d.1) ([f4365f3](https://github.com/sase-org/sase/commit/f4365f30968d627dd114a1e37ad8534ec5192b89))
* **fakey:** add deterministic scenario CLI (sase-5o.1) ([ad3e1eb](https://github.com/sase-org/sase/commit/ad3e1eba20969489ebd368118019f76209fb6e5e))
* finalize commits in external repositories (sase-5y.3) ([b644bab](https://github.com/sase-org/sase/commit/b644bab27cef696e4c112b27dd791b7adc2f19f7))
* **gates:** add canonical primary branch submission ([005f431](https://github.com/sase-org/sase/commit/005f431eb8e50c8ea187145d6c9eeb612ba32b88))
* **gates:** add custom notification gate execution (sase-6i.2) ([158e9a2](https://github.com/sase-org/sase/commit/158e9a293c8e679728ef94f8989e895f6126f4a2))
* generalize user questions into command gates (sase-6e.5) ([3b0c4ad](https://github.com/sase-org/sase/commit/3b0c4adc6fb2a1ee139e5dc91825e86390111038))
* harden epic approval handoff (sase-64.2) ([3c0b0ea](https://github.com/sase-org/sase/commit/3c0b0ea24a1085a7d719f37d644f663b1e0c469e))
* highlight literal code in prompts ([a9813bf](https://github.com/sase-org/sase/commit/a9813bf2c4014b6ac467476c2dcd7870436917e7))
* highlight xprompt syntax in prompt input ([db9ad5d](https://github.com/sase-org/sase/commit/db9ad5d513e1e6b80a5776193ad4058ad46106e6))
* hold failed agent workspaces until dismissal ([4518dc1](https://github.com/sase-org/sase/commit/4518dc19dd8c68e3f2377630dd35c1e54fc17dcb))
* include VCS tags in plan approval notifications ([e9473ca](https://github.com/sase-org/sase/commit/e9473ca007b578df53ca7f7f4e1d515ccaa1d34c))
* **init:** initialize all active projects ([78e0676](https://github.com/sase-org/sase/commit/78e0676ad36e1b7266d3495df9ce99a751764ae0))
* isolate linked repository clones from companions ([df60999](https://github.com/sase-org/sase/commit/df60999b5b38ef1c94dcb247b66a52e744d6e4ad))
* launch approved epics from structured plans (sase-61.5) ([9ef9688](https://github.com/sase-org/sase/commit/9ef9688c8bc2856466c2d57d0daa3ac132271ebd))
* link plan tags in commit footers ([69d7142](https://github.com/sase-org/sase/commit/69d7142b45cecdf43ded7aef7e976df2d816d900))
* **llm:** support execution provider overrides (sase-6l.2) ([f8a8922](https://github.com/sase-org/sase/commit/f8a892234fa7192492c9c7b3bf1247f49950ed3f))
* make epic approval launches host-owned (sase-64.3) ([33d30ba](https://github.com/sase-org/sase/commit/33d30ba0f4ce450bb7e56e22228dcf6b246883e2))
* make linked repository materialization opt-in (sase-5q.1) ([c13664d](https://github.com/sase-org/sase/commit/c13664dc6b1ce83bd6f4ea9f4755d71dad78cf61))
* **memory:** migrate runtime to canonical sase paths (sase-6d.3) ([21dfb11](https://github.com/sase-org/sase/commit/21dfb110a47f7e45cbff8199d58b3e9e32c3745a))
* **memory:** remove keyword metadata ([21e1640](https://github.com/sase-org/sase/commit/21e1640ee7373759701865b7917a7828b2d233bb))
* **memory:** render lazy sidecar repositories (sase-62.1) ([776f69e](https://github.com/sase-org/sase/commit/776f69eb4b9b0e996378968716682b070a8feb8b))
* **memory:** require explicit project opt-in ([8ee7fa5](https://github.com/sase-org/sase/commit/8ee7fa57d2ca5e2e63c051ef50dd3e82cb8aef1a))
* Migrate from pylimit to toolong ([9b54670](https://github.com/sase-org/sase/commit/9b546708973291b5754c25a2dba9391124abb573))
* Migrate from pyvision to symvision (sase-5t.5) ([039204f](https://github.com/sase-org/sase/commit/039204fe2e8d62d685f1e7d089ba077989ed128a))
* migrate plan approvals to notification gates (sase-6e.6) ([763bf73](https://github.com/sase-org/sase/commit/763bf73edceb0d0604058f48848fe7484107c650))
* migrate project config and xprompt runtime paths (sase-6d.2) ([01a1adb](https://github.com/sase-org/sase/commit/01a1adbe73866475de7c068fa3637d2a0009e0c8))
* migrate project content to canonical sase tree (sase-6d.5) ([5894a48](https://github.com/sase-org/sase/commit/5894a487f32be50e247db0819b0f9429ecaf1731))
* **mobile:** unify gate action bridge (sase-6p.5) ([d667014](https://github.com/sase-org/sase/commit/d667014aeae56b3b8c1710f27ce8dacfaaf8269b))
* **models:** group coder aliases in built-in bucket ([ed7714b](https://github.com/sase-org/sase/commit/ed7714b5b2e5f714cd54105139b054e28c7a8fb7))
* move Bob query skill to user configuration ([aa08bdf](https://github.com/sase-org/sase/commit/aa08bdf80daee0b5bb50120d10ee416178f84daf))
* **notification-gates:** add option-query gate contract (sase-6p.1) ([789cbfe](https://github.com/sase-org/sase/commit/789cbfe5d7974b601ba87eaef6c428c0c73bd3e5))
* **notification-gates:** finalize adapter-owned auto resolution (sase-6e) ([a0dc62d](https://github.com/sase-org/sase/commit/a0dc62d2fa5788eb06a5e60a7be14976c2f09eb5))
* **notification-gates:** migrate producers to option queries (sase-6p.3) ([f072f8a](https://github.com/sase-org/sase/commit/f072f8a824f6310f2b3db57e3d6baeca6a0bf109))
* **notifications:** add durable command-backed gates (sase-6e.3) ([7294db9](https://github.com/sase-org/sase/commit/7294db9bb5c60ab2935ee059e4af528026b7323d))
* **notifications:** migrate launch approvals to durable gates (sase-6e.4) ([5c8cd12](https://github.com/sase-org/sase/commit/5c8cd1276b472ccd65cbcfadd3dcf7ff6d3eacbe))
* **notifications:** summarize agent questions in notification modal ([b5198f7](https://github.com/sase-org/sase/commit/b5198f7e18032c025c2a609a5fd9fbac9bbf900c))
* **notify:** add mechanical gate wait command (sase-6i.3) ([c5d7e77](https://github.com/sase-org/sase/commit/c5d7e771ed7abb1960515086150739116936ff5f))
* **plan:** add strict plan validation command (sase-61.2) ([4881a04](https://github.com/sase-org/sase/commit/4881a04bfa1ede8580925fe14bae6935ca1eb620))
* **plan:** guide phase description authoring ([c9c8131](https://github.com/sase-org/sase/commit/c9c81317859bd220dc6839167d0dfd62b71e7dfe))
* **plans:** add filter query and search index (sase-6t.1) ([ef982d8](https://github.com/sase-org/sase/commit/ef982d84ac1450ae9132eb8cd38567ca778261bd))
* **plans:** add shared plan filter bar (sase-6t.2) ([1e9bfc9](https://github.com/sase-org/sase/commit/1e9bfc9c50b6d9e6ceb40d7e0fff7150ec36ed3f))
* **plans:** aggregate enabled projects by default (sase-6a.1) ([0a910c5](https://github.com/sase-org/sase/commit/0a910c51803d3a556d1e2d2fb9746a94cd243930))
* **plans:** redesign plan pipeline list (sase-6a.2) ([ec1a006](https://github.com/sase-org/sase/commit/ec1a006f53282265330668704a416bb0d03562df))
* **plan:** validate plans before proposal (sase-61.3) ([d2e9613](https://github.com/sase-org/sase/commit/d2e9613a8ad23368037fcb1c0161e4e1a6480273))
* **projects:** adopt enabled and disabled lifecycle states (sase-5w.1) ([f47815d](https://github.com/sase-org/sase/commit/f47815df3109bb7708303c230d63e09c33fb4239))
* refresh materialized SDD companions through providers ([5b50fc5](https://github.com/sase-org/sase/commit/5b50fc5fd230352282b36cb87ff49ee37720b0db))
* remove bundled toobig split workflow ([22654f8](https://github.com/sase-org/sase/commit/22654f82b69b9e7b3d8f099303e2d10c509c7e3e))
* remove directory workspace xprompt ([f150306](https://github.com/sase-org/sase/commit/f150306cebf1de284548241316ef51a548877bba))
* remove legend and myth planning flows ([1815d55](https://github.com/sase-org/sase/commit/1815d551553a28e69e2b097a034c5c57d8fe1f7a))
* remove stale agent status grouping helper ([eb2338f](https://github.com/sase-org/sase/commit/eb2338f83093f917f9ae4e01b107580b412ccf4e))
* rename explicit artifacts to artifact files ([2443fc8](https://github.com/sase-org/sase/commit/2443fc80e26aeb126c77ef2f7ee400aa631560a1))
* rename pylimit_split workflow to toobig_split ([a086bb9](https://github.com/sase-org/sase/commit/a086bb95274059d4a46b35b1161792f974e51aa9))
* render generated markdown from packaged templates ([19bcf39](https://github.com/sase-org/sase/commit/19bcf3944fee8d6c934f8db980310b9fa08138a7))
* **repo:** add external repository domain model (sase-5y.1) ([f324809](https://github.com/sase-org/sase/commit/f324809f09d2e49852bd9430a3b57a0793a695aa))
* **repo:** add repository open log dashboard (sase-5x.3) ([1ec31b8](https://github.com/sase-org/sase/commit/1ec31b87d4535e9f298ea22d738a171b28232f79))
* **repos:** make research sidecars explicit ([8c716fa](https://github.com/sase-org/sase/commit/8c716fa745b03fd9b9bed87c9ad23ae55bafea9a))
* require and display plan titles ([f8b44c4](https://github.com/sase-org/sase/commit/f8b44c49fbc8db391bb41cd30e4f8e7907cd8909))
* require explicit SASE project management authorization ([7657ed4](https://github.com/sase-org/sase/commit/7657ed44435ac830f41728e0f9244538440743bc))
* resolve parallel agent families at launch (sase-6g.3) ([8c73c22](https://github.com/sase-org/sase/commit/8c73c22c5cf1bada5df9f7c7c97ba1f61b7b8f41))
* **runner-slots:** admit parallel family members (sase-6g.2) ([702ab60](https://github.com/sase-org/sase/commit/702ab603aaad29970098aa81db003cccef85f54c))
* **runtime:** expose clan wall-clock aggregation (sase-6n.1) ([35c44d8](https://github.com/sase-org/sase/commit/35c44d8221717b7c70c9e1552402f2d51901f33c))
* **sdd:** add split companion initialization and migration (sase-5q.4) ([4976cdb](https://github.com/sase-org/sase/commit/4976cdbd8972db717e65e01448d035a1de9d5db0))
* **sdd:** create companion repo during init ([46670fb](https://github.com/sase-org/sase/commit/46670fbf4d2afccdc30cf6ec344d5a003d358f3b))
* **sdd:** enforce committed plan schema cutover (sase-61.6) ([b33ef20](https://github.com/sase-org/sase/commit/b33ef206cfa69408823d1b681b2b82f2eb20fe2d))
* **sdd:** finalize companion repository changes ([3169f35](https://github.com/sase-org/sase/commit/3169f351b9f9698720f62881a2763262748d86a3))
* **sdd:** make provider storage authoritative ([747d9be](https://github.com/sase-org/sase/commit/747d9be322fda3d635d436217365084031d12188))
* **sdd:** nest prompt snapshots with monthly plans ([71effb3](https://github.com/sase-org/sase/commit/71effb3204c815deb34f1bab3a4d3ac6eb3d69e2))
* **sdd:** rename companion repositories to sidecars (sase-5w.2) ([3cf8ea2](https://github.com/sase-org/sase/commit/3cf8ea2bfb4c50022141a93af8b1f327fb1d204e))
* **sdd:** require confirmation for GitHub companion creation ([47d0066](https://github.com/sase-org/sase/commit/47d0066bd77795d50e225290fb5a915895d23752))
* **sdd:** retire legacy plan layout ([546a115](https://github.com/sase-org/sase/commit/546a1155f210569ae093e3dc0ffa3bd05f36e47f))
* **sdd:** route split companion operations by repository (sase-5q.3) ([0bbd3cb](https://github.com/sase-org/sase/commit/0bbd3cb502d7be5e6f6bef9448d964c899ede46e))
* **sdd:** support split companion repositories (sase-5q.2) ([4c40d5a](https://github.com/sase-org/sase/commit/4c40d5af8f3f6ecdb367891483a720b68b6cd3a0))
* **sdd:** unify tale and epic plan storage ([b3c7582](https://github.com/sase-org/sase/commit/b3c75827571fde1b6027e3f7d2f0bac40d3d9530))
* show alias references in Models panel ([59ea6e5](https://github.com/sase-org/sase/commit/59ea6e53ec4207741f793cd61f9547cb3ae62e2e))
* simplify custom revival search ([8af1d23](https://github.com/sase-org/sase/commit/8af1d23841e8e9e6f3d9a85e4f2fdf228050e7f3))
* support launch-scoped model alias overrides ([ddd0b63](https://github.com/sase-org/sase/commit/ddd0b63f22dce1e5e5d2c8d35af96b9fd2967a3f))
* support multi-parent fork conversations (sase-6m.2) ([900c75f](https://github.com/sase-org/sase/commit/900c75f5b1ef2e28d42b4bd593708b5228d3cf41))
* **telemetry:** add deterministic terminal chart toolkit (sase-6k.2) ([171bf04](https://github.com/sase-org/sase/commit/171bf04e2d59a26972a9b2ec448d9e5d7d433ea6))
* **telemetry:** query the local store from the CLI (sase-6k.4) ([04f7be6](https://github.com/sase-org/sase/commit/04f7be663fd601b5289514bcf9dcc1f2f9986ac3))
* **telemetry:** remove bundled monitoring stack (sase-6k.6) ([55df5a7](https://github.com/sase-org/sase/commit/55df5a75baa7004e4c04902b4256b3e08d4c4f2e))
* **telemetry:** replace Prometheus ingestion with local storage (sase-6k.3) ([7ccc468](https://github.com/sase-org/sase/commit/7ccc4688c393478423072db4d7d045ed0f869b19))
* **tui:** add Admin Center telemetry dashboard (sase-6k.5) ([79f0a1b](https://github.com/sase-org/sase/commit/79f0a1b4730c5d2b0d5ce04748abbfe9f63c4d8a))
* **tui:** add aggregate clan detail panel (sase-6n.7) ([8119612](https://github.com/sase-org/sase/commit/8119612f48bf8fe0b68075993db2e8bdce75d3d5))
* **tui:** add commit filter bar completion widget (sase-6s.2) ([6f8a97a](https://github.com/sase-org/sase/commit/6f8a97a6f1ea79c9f55a53f6dca660a62c6547b8))
* **tui:** add commit hint viewer ([cca9d50](https://github.com/sase-org/sase/commit/cca9d500cd88751180efd0d6f47c0ab9b73e7902))
* **tui:** add commits artifact pane (sase-69.3) ([72142d7](https://github.com/sase-org/sase/commit/72142d75a3ca12be2339e2ab9df3941c82c89182))
* **tui:** add custom gate command keymaps ([d5cf13b](https://github.com/sase-org/sase/commit/d5cf13b23278165b87b3ed48ff8f9ba1eca27635))
* **tui:** add on-demand prompt formatting ([fac33c7](https://github.com/sase-org/sase/commit/fac33c7a2f920b86d70ef05774ce4b699c9df7d3))
* **tui:** add prompt placeholder completion (sase-6b.2) ([b74adbf](https://github.com/sase-org/sase/commit/b74adbf4cad66da4435017a41df074965d53a694))
* **tui:** add prompt stash leader shortcut ([fd0a3c5](https://github.com/sase-org/sase/commit/fd0a3c53c3c8aa4aae17313ad63c577e5a4ed5f0))
* **tui:** add prompt stash preview panes ([6ab1482](https://github.com/sase-org/sase/commit/6ab1482bb99eeb9d03a008a82ef5456a4dd596d8))
* **tui:** add responsive gate review workbench ([0fa8b64](https://github.com/sase-org/sase/commit/0fa8b643ef3bc0367091c5d56c6be301f8a75564))
* **tui:** aggregate agent output variables ([d50c2e5](https://github.com/sase-org/sase/commit/d50c2e52e706da04790419df19e6684b04354344))
* **tui:** aggregate parallel agent family status (sase-6g.5) ([a0a81e4](https://github.com/sase-org/sase/commit/a0a81e445a5888e046b68b19603eed054fb01eab))
* **tui:** compact Plans rows and state indicators ([cb733da](https://github.com/sase-org/sase/commit/cb733dacf3baa2d631ed706c7a1fb07c9b39a560))
* **tui:** distinguish artifact types with icons ([dc12217](https://github.com/sase-org/sase/commit/dc1221799490b32d8c1939394dd502da83479f65))
* **tui:** expose parallel agent family details (sase-6g.6) ([d395776](https://github.com/sase-org/sase/commit/d39577633017b3a19a2ade11453410a928ca8f11))
* **tui:** expose runner slot wait state (sase-5u.4) ([82abd47](https://github.com/sase-org/sase/commit/82abd478e5c4a6a29d2cfa101aca6d79441836b6))
* **tui:** flash yanked prompt text ([7bc4ff3](https://github.com/sase-org/sase/commit/7bc4ff38f5e4943c52e755ec069cc48aeb1bd4b3))
* **tui:** highlight known slash skills in prompts ([c5ded4a](https://github.com/sase-org/sase/commit/c5ded4a86e5ad590b3f421615052b7284daf8a83))
* **tui:** integrate live commit filter bar (sase-6s.3) ([a18747f](https://github.com/sase-org/sase/commit/a18747fccf77f5e36b75428a741e82cd3b090685))
* **tui:** keep commit timeline entries on one line ([ce3258b](https://github.com/sase-org/sase/commit/ce3258be0a7665e12a321f56a3a7747ed74539fd))
* **tui:** navigate selected commit views ([69e2d79](https://github.com/sase-org/sase/commit/69e2d795cf3bd4f95b404b4106407629eff66c7e))
* **tui:** record sub-threshold watchdog hitches (sase-6j.1) ([e73d140](https://github.com/sase-org/sase/commit/e73d1400c4097432461316e3a2fca827ab9c8f75))
* **tui:** redesign plans detail pane (sase-6a.3) ([1d9b5d0](https://github.com/sase-org/sase/commit/1d9b5d0a9ae6ef86b610258fbcdb931b89ed1e82))
* **tui:** redesign xprompt save panel ([dcafd64](https://github.com/sase-org/sase/commit/dcafd64e74d695d194f6ab2b0893a098e38b3c40))
* **tui:** render fenced code blocks as full-width cards ([df67fec](https://github.com/sase-org/sase/commit/df67fecb82eac898295074432b934d76a82d33b9))
* **tui:** support slash skills in preview and jump actions ([7346e04](https://github.com/sase-org/sase/commit/7346e04c5fe445b15b02b4d4eb92a3fbd1ac3f0e))
* **tui:** swap Admin Center tab keymaps ([8a1a4f4](https://github.com/sase-org/sase/commit/8a1a4f46772e3eb0fbab6eb39fd20dedc1f3cfb9))
* **tui:** underline available plan titles ([42cadf4](https://github.com/sase-org/sase/commit/42cadf45175e65694650cbd03f010fa5bd20eae1))
* **tui:** unify clan and family row identities ([a1152a8](https://github.com/sase-org/sase/commit/a1152a88c72f1362d8f9c1fd802387c7288f8117))
* **tui:** uppercase active nested tab labels ([70d1fb5](https://github.com/sase-org/sase/commit/70d1fb5668f0940bec221004e209e45a175bd0f6))
* use fixed companion clone directory names ([e1c2fd0](https://github.com/sase-org/sase/commit/e1c2fd0c40b97f836799698a496776bc43b40e9d))
* validate tiered plans before approval (sase-61.4) ([bc32fb8](https://github.com/sase-org/sase/commit/bc32fb844cdc36181f824c2bfa78fcda7e9c6548))
* **vcs-log:** render SASE tags as styled chips ([600eb4d](https://github.com/sase-org/sase/commit/600eb4df714eae16beece21919bbd8b210a803b9))
* **vcs:** add all-project commit log scope ([cebc837](https://github.com/sase-org/sase/commit/cebc837720036c1dae660bcacf3f7f4f37006378))
* **vcs:** add issue-tracker provider seam (sase-69.2) ([e5d2995](https://github.com/sase-org/sase/commit/e5d29958205915ef9fb218fd12785861800804ad))
* **vcs:** cache log fetches and show tags by default ([31b4d01](https://github.com/sase-org/sase/commit/31b4d012e1c707ff832e0850d550cd67e5223b87))
* **vcs:** make SDD log history opt-in ([86c7034](https://github.com/sase-org/sase/commit/86c7034f2132b3112e7c3c68bbf544952d8d3d7e))
* **vcs:** show 40 log commits by default ([e853025](https://github.com/sase-org/sase/commit/e85302525ec562b5759aaa39244089bd87f1ac10))
* **vcs:** show remote fetch progress ([ba60137](https://github.com/sase-org/sase/commit/ba60137dd626c6ed156fdf5622719aeb92e3c247))
* **vcs:** show SASE tags in log ([6137dba](https://github.com/sase-org/sase/commit/6137dbafecf1b8e80a8f32f6a0ad57952166a716))
* **workspace:** relocate linked repository clones ([953f070](https://github.com/sase-org/sase/commit/953f0704710b7c51e8dbf4f0a17cd95e648fdff7))
* **workspaces:** scope linked repos to host workspaces ([a262729](https://github.com/sase-org/sase/commit/a2627294293db6ac85b0273cec6b5730a7a38a10))
* **xprompt:** integrate epic changes before landing ([0ed6b32](https://github.com/sase-org/sase/commit/0ed6b32e49b9d31e84f26a869d41a523609256fe))
* **xprompt:** parse family directives (sase-6g.1) ([e24fd65](https://github.com/sase-org/sase/commit/e24fd654f3f227999c3b0005ce06e5d0c2783c5c))
* **xprompt:** remove Mercurial workspace workflow references ([afe3701](https://github.com/sase-org/sase/commit/afe37010f171b7a1b33ad1d02c06024f54c8b2ea))
* **xprompt:** replace parallel family launches with clans (sase-6n.2) ([f3bc42c](https://github.com/sase-org/sase/commit/f3bc42caaee2d60fdfa1fee6e49d9c8ed7631fc5))
* **xprompt:** support repeatable input binding (sase-6m.1) ([762736f](https://github.com/sase-org/sase/commit/762736fd680d566c4961dcd838c621d0e3c272cc))


### Bug Fixes

* **ace:** compact SASE plan heading ([ede79bc](https://github.com/sase-org/sase/commit/ede79bc989570e82fe5ed8da00f425b8e924e48d))
* **ace:** cycle metadata navigation through document top ([6d7f472](https://github.com/sase-org/sase/commit/6d7f47203bab8c974f6b0bb2dfdac1f543fd80ed))
* **ace:** distinguish prompt stash badge color ([992722f](https://github.com/sase-org/sase/commit/992722f44d5330b9669b6166b95f55556b4ed40d))
* **ace:** hide redundant clan tags in split panels ([c203382](https://github.com/sase-org/sase/commit/c203382e31e0177310601b56c298bbee6a843e1c))
* **ace:** highlight code in xprompt-led lines ([77b92ac](https://github.com/sase-org/sase/commit/77b92ac8deb01f84d49b6b68ba78a99afaeb0f53))
* **ace:** isolate clan member fold state ([fb37a09](https://github.com/sase-org/sase/commit/fb37a09eef03292a849359feca9cadb7c5510f03))
* **ace:** keep agent refresh responsive during cleanup (sase-6j.3) ([6ade59e](https://github.com/sase-org/sase/commit/6ade59edcd93d25cc6fbb438dba51d36508bcb06))
* **ace:** keep agent subtrees in outer grouping ([d849d62](https://github.com/sase-org/sase/commit/d849d628bf0ac28c000e489fcd6e5074c860fbc0))
* **ace:** keep artifact fields under context navigation ([b296828](https://github.com/sase-org/sase/commit/b29682808132418e06eb4601f7c6a7b6d2e2a715))
* **ace:** keep collapsed agent panels last ([c08a434](https://github.com/sase-org/sase/commit/c08a43458d712f78f2008113044ffef2df6b47b3))
* **ace:** keep saved snippets live in prompt catalog ([d68b0a4](https://github.com/sase-org/sase/commit/d68b0a461f8dd963b5506136e10700c7cb7b3994))
* **ace:** keep startup and modal handlers responsive (sase-6j.4) ([af95760](https://github.com/sase-org/sase/commit/af95760dfa3c3ee31ed8e1202b7a4c3eb35daeff))
* **ace:** load prompt history inline instead of replacing the stack ([7bb7914](https://github.com/sase-org/sase/commit/7bb79141b4bc255dedd0b48991525b21237b6e81))
* **ace:** polish plans pane visual coverage (sase-6a.4) ([721b64c](https://github.com/sase-org/sase/commit/721b64ce6ec37b138767a53108182b8615cee772))
* **ace:** prepare project reverts on default branches ([fef304c](https://github.com/sase-org/sase/commit/fef304cfaa2c810b82e1acb842ca6c554a1562a9))
* **ace:** preserve explicit plan approval tiers ([8ab0936](https://github.com/sase-org/sase/commit/8ab0936f13cfa11e96e70385aeb587f12dbe12bf))
* **ace:** preserve phase context across runner refresh ([f915c05](https://github.com/sase-org/sase/commit/f915c05cf41e88c03da38fea81b738119ce4f5e9))
* **ace:** preserve programmatic plan choices (sase-6p.4) ([6ff0f17](https://github.com/sase-org/sase/commit/6ff0f17a0e24cd1843ad193567d878999981e61d))
* **ace:** preserve retry state during workflow dedup (sase-5o.5) ([46e7869](https://github.com/sase-org/sase/commit/46e7869e69fabb412a093f0a2c7c27461131d105))
* **ace:** project parallel family status counts ([4dc5ca6](https://github.com/sase-org/sase/commit/4dc5ca609890eee56a780793e997709de57de52b))
* **ace:** require explicit agent panel groups ([16c6bcd](https://github.com/sase-org/sase/commit/16c6bcd996919bd5a401a4ced3adde92e3c2be88))
* **ace:** scope group folds to agent panels ([81eca4e](https://github.com/sase-org/sase/commit/81eca4e6663478ea9d7cec34594d2ad43cc057c1))
* **ace:** show created status after epic launch ([50ce11d](https://github.com/sase-org/sase/commit/50ce11d988b443ccaf107f412bcb4e79d236a4d1))
* **ace:** show failed workflow log output ([79cce79](https://github.com/sase-org/sase/commit/79cce7991c549ec56f6558200c95fcba3539eee9))
* **ace:** show retrying status before the next attempt ([786cdb7](https://github.com/sase-org/sase/commit/786cdb7f7bfa71d9bef874be15c27062611676ac))
* **artifacts:** attribute attachments to commit repositories ([5bd4014](https://github.com/sase-org/sase/commit/5bd40142d85b2071e157343a15bf7f401503085e))
* attribute nested linked repository commits correctly ([5605178](https://github.com/sase-org/sase/commit/56051782c1ac46bf44720f6ee27f47bc685443a2))
* attribute SDD artifacts to the completing agent ([4067411](https://github.com/sase-org/sase/commit/4067411bc5dd51a0e9ab8ea2cc1f601e9883ad1b))
* auto-commit Q&A prompt snapshots ([bfb468c](https://github.com/sase-org/sase/commit/bfb468ca853939662e7ed9fc2fd5ce1c558ebc1b))
* avoid false init memory drift in lint ([#216](https://github.com/sase-org/sase/issues/216)) ([12e0f99](https://github.com/sase-org/sase/commit/12e0f997f78be848e5869e0369b2e66780f35e07))
* avoid stale agents tab diff fallback ([b38c1b2](https://github.com/sase-org/sase/commit/b38c1b262cb3da46385d3a8590463413406a5d6c))
* **axe:** project question gate results from v2 responses ([babae68](https://github.com/sase-org/sase/commit/babae68a49daad1ec8f72411f258eb4c1ec2e619))
* **beads:** defer epic launch store pushes (sase-67.3) ([35edd9b](https://github.com/sase-org/sase/commit/35edd9bafe9f119f9b6cac2ec10d9b1899cf904a))
* **beads:** route separate SDD writes to workspace clone ([47899b7](https://github.com/sase-org/sase/commit/47899b7a15d70fe8e62d421e9f3a831b8f04ea06))
* clone launch sidecars from authoritative remotes ([e68ff17](https://github.com/sase-org/sase/commit/e68ff172ddd53906806432e3f886ece2a203c7e3))
* **codex:** use GPT-5.6 SOL model ID ([ccc02c0](https://github.com/sase-org/sase/commit/ccc02c0f95823e80892d4df9dea30d0fafd54927))
* complete Symvision migration recovery (sase-5t.5) ([3d5fe9c](https://github.com/sase-org/sase/commit/3d5fe9c50a8e3d68f04bf1a5a033247e65f79c0a))
* contain scrollable update commit previews ([05dc1db](https://github.com/sase-org/sase/commit/05dc1db089965775e5f20be4dcacda66a60411a4))
* **core:** tolerate unknown keys in wire rehydration ([fde0d42](https://github.com/sase-org/sase/commit/fde0d425e33c81534510397d01f8664f083ad042))
* correct helper visibility across module boundaries ([e217bf3](https://github.com/sase-org/sase/commit/e217bf31a4ab8527520e9f92448cd54add5098f2))
* correct runner launch admission ordering ([d546a81](https://github.com/sase-org/sase/commit/d546a813cb18d41484f7c8969156b5bed4aff941))
* decouple source linting from SASE validation ([#225](https://github.com/sase-org/sase/issues/225)) ([3b54a7b](https://github.com/sase-org/sase/commit/3b54a7bd1761ae7ccb041d170fc3cf986d5ec380))
* **demos:** preserve truecolor in generated media (sase-6l.1) ([7a65aeb](https://github.com/sase-org/sase/commit/7a65aeb8cc171d83a92766fb8185752f455901e8))
* dismiss notifications after named-agent kills (sase-63.2) ([6047ada](https://github.com/sase-org/sase/commit/6047ada2e930aaaba56a5b93b09d9cd94747f087))
* display configured project names in plan inventory ([ea38782](https://github.com/sase-org/sase/commit/ea387821a77118ac2450a746950f1e6cbb8ac36c))
* drain runners before detached workflow launches ([e635b1f](https://github.com/sase-org/sase/commit/e635b1f2a8bee7d44a3ceb50392cb19125c9454e))
* exclude internal SDD files from completion attachments ([71ee815](https://github.com/sase-org/sase/commit/71ee8156030e9526c0b788c606fa3401723c3fe3))
* expose family runner-slot occupancy in agent listings ([eaf6f68](https://github.com/sase-org/sase/commit/eaf6f6809e89010b1e31a6880d0cbaab37794195))
* finalize interrupted tool calls on agent teardown ([1064f1d](https://github.com/sase-org/sase/commit/1064f1df38ce7c73354c8f42375e5d74cba98da8))
* gate runners before deferred workspace setup ([8675b6b](https://github.com/sase-org/sase/commit/8675b6bc17b6b067bedbfcfc2a0a4a2db6eba68d))
* guard remote SDD creation and plan routing ([cb9deb0](https://github.com/sase-org/sase/commit/cb9deb06929189178ba2953c13364360f7111991))
* handle pinned prompt stash bundles consistently ([711120b](https://github.com/sase-org/sase/commit/711120b638d3362f4b9c0b1211c49a4af9ab5b69))
* hide audit launcher marker notifications ([73b7db3](https://github.com/sase-org/sase/commit/73b7db3afbd1c9951be5703247624ee58427728f))
* honor retry fallback model overrides (sase-5o.4) ([3648ce1](https://github.com/sase-org/sase/commit/3648ce1d2a36fe04678b342e0fa887c62d41a9d0))
* include companion SDD artifacts in finalization ([28168ad](https://github.com/sase-org/sase/commit/28168ad0566e54baf577836221f1ab778c1b6dd2))
* **init:** filter batch inventory to projects ([d2157eb](https://github.com/sase-org/sase/commit/d2157eb0e53bcf6363055a294ed15a11696665ac))
* initialize project-specific research sidecars (sase-62.2) ([47514b7](https://github.com/sase-org/sase/commit/47514b77a887b7a518a7df1013c1021d9d73e498))
* **init:** wrap inline code spans atomically in memory shims ([cc1a166](https://github.com/sase-org/sase/commit/cc1a166781b83518a4a0f78967e9fcdd8b97acdd))
* isolate nested external repository identity (sase-6d.6) ([8985b05](https://github.com/sase-org/sase/commit/8985b05247d25a5994685c956868e28d12468271))
* keep dependency waiters pending after failures ([608ec52](https://github.com/sase-org/sase/commit/608ec521b32420c7a132c8cebd71678158f2a321))
* label tale plan submit action ([dc09732](https://github.com/sase-org/sase/commit/dc09732399aa651f54579f753c9234b08c6d66d9))
* **llm:** prune invalid persisted override timestamps ([#220](https://github.com/sase-org/sase/issues/220)) ([6fd4f64](https://github.com/sase-org/sase/commit/6fd4f6404461c73eeeac0e4a724f9cd07142abef))
* make retry visual tests hermetic ([4376456](https://github.com/sase-org/sase/commit/437645675ee74440a32fd4079fee031bbe3524f3))
* make workflow retries independent of workspace helper ([1c0154b](https://github.com/sase-org/sase/commit/1c0154b904984bb6c3b5475c499030426775094f))
* **memory:** finalize linked repository initialization (sase-5q.1) ([5df88d7](https://github.com/sase-org/sase/commit/5df88d7ca00e1cae07fd7033be28ed0a17f2fdb4))
* **memory:** fold agent doc source changes into init commits ([f6f0224](https://github.com/sase-org/sase/commit/f6f02240fed6e4f6435469b4de016f81e39788b0))
* migrate lint integration to toobig ([a66dc39](https://github.com/sase-org/sase/commit/a66dc398a401c0726b8309a9b3d235fb6a6661d3))
* **mobile:** thread feedback into unified gate bridge input ([1bf22f3](https://github.com/sase-org/sase/commit/1bf22f300b7da9712d0616180f8b00a77f0bb8dd))
* normalize GitHub sidecar origins to SSH ([fc3fc55](https://github.com/sase-org/sase/commit/fc3fc552c09b3b78c30fdb0765eaf02ea70af32d))
* **notifications:** limit completion image attachments ([22d3906](https://github.com/sase-org/sase/commit/22d3906155cf97804938ddc70beb55168009ce6b))
* **plan-gate:** distinguish tale approval action ([8775f42](https://github.com/sase-org/sase/commit/8775f42a892b6091aa71948cb6ed41b6e57eaca7))
* **plan-gate:** label epic approval action as Epic ([60d2960](https://github.com/sase-org/sase/commit/60d29600174e9dbe5e7c101efd7800bf1f7bca0a))
* **plan-gates:** preserve selected approval capabilities ([1d2df4e](https://github.com/sase-org/sase/commit/1d2df4eebb4d66f3d1d2c950c1356a176753cf06))
* **plugin:** use sase--plugin catalog topic ([dff80f1](https://github.com/sase-org/sase/commit/dff80f129e7181036a2b70c0e0efb282bbb39961))
* preserve agents view hints during detail refresh ([b732cc7](https://github.com/sase-org/sase/commit/b732cc73fd2f3a715f07a35a0f10bcbb8312f95c))
* preserve canonical plan identity through approval gates ([3b263a5](https://github.com/sase-org/sase/commit/3b263a578066048f3134735a0012f9177b1c3877))
* preserve command output tails in tool reports ([73c2dc6](https://github.com/sase-org/sase/commit/73c2dc6db11abcad2cc0402e85b9774a7c523101))
* preserve display-prefixed ChangeSpec refs ([08b2f73](https://github.com/sase-org/sase/commit/08b2f73ed69df95437787a046ab9465af7a88455))
* preserve primary commit diff provenance ([e2274e5](https://github.com/sase-org/sase/commit/e2274e52b3b8cb6897eb0c8fe22eb32ae5c97064))
* preserve SASE plan tags for separate stores ([3d23bdd](https://github.com/sase-org/sase/commit/3d23bdd9b6f2cdedf3340b76cd2e0984b14dc847))
* preserve sidecar identity during repository cutover ([1e3ab66](https://github.com/sase-org/sase/commit/1e3ab66b5a04aa87350801f993fc98c6fe422eed))
* prevent lost override and plan state updates ([#221](https://github.com/sase-org/sase/issues/221)) ([1cfa9b1](https://github.com/sase-org/sase/commit/1cfa9b11364c97681dddcdcc53f25243e4235fef))
* publish review runner environment before invocation ([39122ff](https://github.com/sase-org/sase/commit/39122ff058279b2f7f840a3315258e6d5e5be67a))
* **query:** propagate project names to ChangeSpec search ([c224c98](https://github.com/sase-org/sase/commit/c224c98bdc679e6894defe0a2a1c40d2754ca06f))
* reconcile memory init config path API (sase-6d.2) ([6dbd568](https://github.com/sase-org/sase/commit/6dbd5688ef77df23640164328b26f794e304244e))
* release failed workspaces without visible notifications ([836d738](https://github.com/sase-org/sase/commit/836d73818b0218403744da2ff32d3133679bf2fc))
* release runner slots while awaiting answers ([0a124f7](https://github.com/sase-org/sase/commit/0a124f74492e310a7abea7a8828f2d4e0d01864e))
* require plan validation core bindings (sase-61) ([beeefa6](https://github.com/sase-org/sase/commit/beeefa6c2b358bf36a79f172d2274e13275d9afe))
* require repo skill for repository web fetches ([d6771fe](https://github.com/sase-org/sase/commit/d6771fe404545914ee60bef9026294b83d3276ec))
* resolve epic launches from canonical project identity ([3362655](https://github.com/sase-org/sase/commit/33626551f485a0dd65ecf0c37626eab7f9ea2259))
* retry model capacity failures ([887f689](https://github.com/sase-org/sase/commit/887f6890ce0323ec5608c940196ba2b76270b520))
* **runner:** preserve prompt across code refresh (sase-68.1) ([2b96521](https://github.com/sase-org/sase/commit/2b96521f53a4aa44a0aa9d494331d44362c93413))
* **runner:** record bootstrap failures in artifacts ([83f26c7](https://github.com/sase-org/sase/commit/83f26c714eb2730fa5e6f61b5cd227874f59bf15))
* **runner:** refresh stale code after dependency waits ([f7cbca6](https://github.com/sase-org/sase/commit/f7cbca6fd4b19430d2c833d50c4ab9e5142f8b39))
* **sdd:** handle legacy stores during companion init ([d3da6c9](https://github.com/sase-org/sase/commit/d3da6c93b789a6e9f443ca7986a26969be4261fb))
* **sdd:** integrate concurrent companion pushes before failing ([b668e91](https://github.com/sase-org/sase/commit/b668e919a95e9ad33338838a3d5fe87d584c5332))
* **sdd:** keep stale companion clones from blocking sdd init ([a3c5806](https://github.com/sase-org/sase/commit/a3c5806ce2224accd438eb578f476119b6579cc6))
* **sdd:** make sidecar integration transactional ([f678228](https://github.com/sase-org/sase/commit/f6782286e42727c2cdda919f27e6a3c2dbc813d5))
* **sdd:** preserve unknown store records ([6df95bb](https://github.com/sase-org/sase/commit/6df95bbecc640071a22a768af6c5718242227d1d))
* **sdd:** retry git writes on lock contention (sase-67.1) ([63d3b01](https://github.com/sase-org/sase/commit/63d3b01de476ca79ab8d7c0d9156fb1b52b6a519))
* serialize SDD store git write transactions ([7fb6078](https://github.com/sase-org/sase/commit/7fb607857e9745c04a550a1be46386e2a028cac6))
* sort custom revival rows by recency ([1180425](https://github.com/sase-org/sase/commit/1180425d1192c6a3017aece24f67524a19b942dd))
* suppress refresh docs marker notification ([f1f5324](https://github.com/sase-org/sase/commit/f1f5324e21cd6fa25f29dd47af0c672c5de6269e))
* **telegram:** exclude completed epic agents from active list ([78eaa34](https://github.com/sase-org/sase/commit/78eaa34f9dfc96334aeda82300b593edbced26b5))
* **tui:** allow repeat agent across artifact subtabs ([d98b284](https://github.com/sase-org/sase/commit/d98b2846247b9d5edcba07e779feaaddfc5991f7))
* **tui:** compact agent metadata sections ([728595e](https://github.com/sase-org/sase/commit/728595e54ae517b2befb140dca7d5b29e8be2934))
* **tui:** complete residual freeze verification (sase-6j.5) ([e5eef71](https://github.com/sase-org/sase/commit/e5eef716c705c6745d69bef8e6b2a4dcaa412056))
* **tui:** count effective agents in headline ([de9d360](https://github.com/sase-org/sase/commit/de9d36014a20c6795a557dae1435b4b25fa22471))
* **tui:** defer update restart for background tasks ([52c99ca](https://github.com/sase-org/sase/commit/52c99ca5de304fdc673f0ba76002a260321f5bd0))
* **tui:** distinguish xprompt argument colors ([36b0286](https://github.com/sase-org/sase/commit/36b0286934e3ff86e1886fa50b6fb22076491453))
* **tui:** handle control-byte prompt chords ([228b496](https://github.com/sase-org/sase/commit/228b496e0e109962d8acb42a4af6e7b335394e7d))
* **tui:** hide commit message bookkeeping deltas ([4330f6f](https://github.com/sase-org/sase/commit/4330f6f2c92357d3204b930ba334003e4b386bae))
* **tui:** improve inline code visibility ([4d2fb87](https://github.com/sase-org/sase/commit/4d2fb87e5c444c5a82cf7370a95bdc158c5f7293))
* **tui:** invalidate stale detail work before hint rendering ([028ecae](https://github.com/sase-org/sase/commit/028ecaea069c24c89dd2156106df60555d2cd2ec))
* **tui:** preserve agent names in bulk kill-and-edit ([05ef506](https://github.com/sase-org/sase/commit/05ef5069984b6a42023bb565411e58cb677c4934))
* **tui:** prevent bead warmup pump stalls ([38f64ca](https://github.com/sase-org/sase/commit/38f64ca8e8c48c56e0a719e62e9b3f478aec67eb))
* **tui:** prevent message pump starvation ([b788ca5](https://github.com/sase-org/sase/commit/b788ca52264df2652e7b29063c5d3a67448ee75f))
* **tui:** scope group actions to focused panel ([a450a34](https://github.com/sase-org/sase/commit/a450a34034d417021f83a8c8b27e415010615bbc))
* **tui:** widen models panel content ([2e7ed4d](https://github.com/sase-org/sase/commit/2e7ed4d869ebc88046dc8dd247c74dcacf3a2173))
* **update:** always use the dev sase-core build in editable installs ([6262c16](https://github.com/sase-org/sase/commit/6262c16a6b21ba322393734069b50f37bdf9dd6f))
* **update:** upgrade core wheel with editable sources ([add1577](https://github.com/sase-org/sase/commit/add1577de51e02459bdb3ba67a72ca69207210da))
* **vcs:** exclude phantom repositories from global inventory ([d0c4f88](https://github.com/sase-org/sase/commit/d0c4f8838b3e7a1cbdfde32230d5c04170dd3e71))
* **workspace:** reset repository clones before launch ([33c02ed](https://github.com/sase-org/sase/commit/33c02ed90a44096ffbf8559ad648d3ca3e9e7de1))
* **workspaces:** isolate generated SASE repo metadata ([36b962a](https://github.com/sase-org/sase/commit/36b962ad9f664186dfa52b372469a9318b2c0fa7))
* **xprompt:** preserve time-shaped wait dependency names ([8d2179c](https://github.com/sase-org/sase/commit/8d2179ced988a670782773751ec7c6c0858c6f5f))
* **xprompt:** render declared inputs inside inline code ([f5d7184](https://github.com/sase-org/sase/commit/f5d718444ae0a67ef92791014a33e419994210ed))


### Performance Improvements

* **ace:** avoid redundant periodic update recomputes (sase-6c.4) ([578dad2](https://github.com/sase-org/sase/commit/578dad292b6d603478179eeb8eed070ffe9364ea))
* **ace:** bound plain diff rendering ([4dff939](https://github.com/sase-org/sase/commit/4dff93912801d7f4a6e310edd07990e630cc8438))
* **ace:** defer runtime ticks during navigation (sase-6n.9) ([c98fd78](https://github.com/sase-org/sase/commit/c98fd786744734fe7aee6ffeff247c250b5c0e56))
* **bead:** make SQLite mirror lazy and transactional (sase-6r.1) ([c5f48a2](https://github.com/sase-org/sase/commit/c5f48a2643f0614e93b445de0c3273a3ddaddcae))
* **config:** refresh config tokens off-thread (sase-6j.2) ([fbf6213](https://github.com/sase-org/sase/commit/fbf62139df84a7fd6f66612c549d196aaf2157eb))
* **config:** throttle freshness scans in render paths (sase-6c.2) ([4309efb](https://github.com/sase-org/sase/commit/4309efbf19bad8b26f33ef4e0fbb7ee6aa8c87dd))
* gate sidecar integration with freshness TTL (sase-6r.2) ([0c1c875](https://github.com/sase-org/sase/commit/0c1c875d4179c9d1a4dd5293336c8561b81677ea))
* **sdd:** avoid repeated database rebuilds during migration ([#222](https://github.com/sase-org/sase/issues/222)) ([4fa00b5](https://github.com/sase-org/sase/commit/4fa00b52f11ca8019df3a8dd1b366d5d1b24057d))
* **tui:** keep remaining maintenance off the message pump (sase-6c) ([b8b7d65](https://github.com/sase-org/sase/commit/b8b7d65e1a0bb39a59ec2385416b9c8cbf5400f6))
* **tui:** move slow refresh work off the message pump (sase-6c.1) ([0d33d2a](https://github.com/sase-org/sase/commit/0d33d2a8c71f0a175afb7fbc1163f7499c1ad93e))
* **tui:** move stale index rebuild off startup path (sase-6c.3) ([f463941](https://github.com/sase-org/sase/commit/f4639414a457e969e369078eedd71970f5402f98))
* **tui:** reuse update freshness for confirmation ([94d7cdc](https://github.com/sase-org/sase/commit/94d7cdc48c43a7e6cd2c9472b3c3b69ca443497a))


### Documentation

* add pyvision memory note ([e137094](https://github.com/sase-org/sase/commit/e137094bcd23e30110a7f4be972a28e48a138213))
* add xprompt memory note ([2a2d9af](https://github.com/sase-org/sase/commit/2a2d9afb194e7f83e167df1cd253a916eb11bc67))
* align SDD docs with per-project research sidecars (sase-62) ([7a03b9c](https://github.com/sase-org/sase/commit/7a03b9c8a4ae8e89cf9761948e26590ee8471bac))
* clarify lifecycle and launch workflows ([ea1db4f](https://github.com/sase-org/sase/commit/ea1db4f4b559e970ad1d7054cd7258d266913525))
* clarify refreshed SASE usage docs ([848aa07](https://github.com/sase-org/sase/commit/848aa07fe280fccaf1dabb089305df6690b3290c))
* clarify SDD migration and model routing ([70bb4f4](https://github.com/sase-org/sase/commit/70bb4f40a959402b6ee77d1c7c9cee64c7a7f103))
* correct project glossary storage terminology ([7432331](https://github.com/sase-org/sase/commit/743233177c26e56948bc59ddab43550a1d615dbd))
* document agent clans, families, and tribes (sase-6n.8) ([325efd1](https://github.com/sase-org/sase/commit/325efd1529b9f55f91f21c121a99f603d5e3c157))
* document basher vendoring workflow (sase-5v) ([d6b6ab7](https://github.com/sase-org/sase/commit/d6b6ab73f53bb19b6f4f46b4bf275a1abacab753))
* document canonical SASE content layout (sase-6d.7) ([0bf8eb0](https://github.com/sase-org/sase/commit/0bf8eb0d90f85f1ae98f9216766587c88ee6541a))
* document custom notification gates (sase-6i.8) ([3bbcfda](https://github.com/sase-org/sase/commit/3bbcfda69c507fea23339bcb1a5ea3ecce4f3d80))
* document epic plan handoff workflow ([3394455](https://github.com/sase-org/sase/commit/3394455f9a22d955be7702e799a63eb38a50d421))
* finish canonical SASE path cleanup (sase-6d.9) ([1a39e38](https://github.com/sase-org/sase/commit/1a39e3872aa5e2aae02105453b7016d97d4c98f0))
* **gates:** migrate guidance to option queries (sase-6p.7) ([e3a1b4a](https://github.com/sase-org/sase/commit/e3a1b4a8a5c97218f13c92c9241364ca7ed3337f))
* improve sase overview infographic ([24637e4](https://github.com/sase-org/sase/commit/24637e49e213068b5dcfa1383a000f1222b8c4a9))
* migrate linked repository guidance to repo commands (sase-5x.4) ([5afb9b3](https://github.com/sase-org/sase/commit/5afb9b33c781cf27ed63789c2b18e7bcff96abd7))
* overhaul README and PyPI rendering ([094ee4a](https://github.com/sase-org/sase/commit/094ee4ab617c54e6308f212594d3cfec741ca69f))
* redesign README landing page ([ac92d6a](https://github.com/sase-org/sase/commit/ac92d6adeae089f629f7ec748bbb821730093723))
* refresh guides for current SASE behavior ([c7cb86f](https://github.com/sase-org/sase/commit/c7cb86f07e9b4e4c689c6ef1c401723cbac225f2))
* refresh SASE usage documentation ([deb6d4c](https://github.com/sase-org/sase/commit/deb6d4ca6df06df73297beaa907c6199f1d96e24))
* refresh SDD storage and model routing guidance ([ccdd104](https://github.com/sase-org/sase/commit/ccdd104828c38809d039228bc7ff7d27216c47af))
* refresh TUI performance guidance ([6a4a47f](https://github.com/sase-org/sase/commit/6a4a47f94322474395c3d7b80f42fe6c9e0136de))
* remove legacy paths from xprompt infographic ([a800419](https://github.com/sase-org/sase/commit/a8004197d5de182a62d55a2d5d3c45261e2cd529))
* **sdd:** add companion repository infographics (sase-5q.5) ([75ee0fb](https://github.com/sase-org/sase/commit/75ee0fb6a8ec7cc1dfa00214c05d704e8383507e))
* tighten pyvision memory guidance ([1514023](https://github.com/sase-org/sase/commit/151402345dc3dcec1145d0e070a5d2b9ca9e65ae))


### Code Refactoring

* remove unused content layout entry points (sase-6d) ([aa38ebf](https://github.com/sase-org/sase/commit/aa38ebf34fc2be9484d5b06f2c79c05a4e062725))

## [0.10.2](https://github.com/sase-org/sase/compare/v0.10.1...v0.10.2) (2026-07-06)


### Features

* add approved agent launch requests (sase-5g.8) ([deaf571](https://github.com/sase-org/sase/commit/deaf571e08fbd1b1577308e4bffac627dcba23ce))
* add file-backed custom agent-family roles (sase-5g.5) ([72fc527](https://github.com/sase-org/sase/commit/72fc527b2286b8eea4e122cda332f13b24f97455))
* add launch approval pending-action infrastructure (sase-5g.7) ([19a0785](https://github.com/sase-org/sase/commit/19a07856d3dd8c7be92c828f478f87ea0cc4fc21))
* add plan approval member selection (sase-5g.6) ([b762964](https://github.com/sase-org/sase/commit/b762964a53714994d8c578f7fc6475428b14ff24))
* add typed plan-chain handoff evaluator (sase-5g.3) ([bfe4cc2](https://github.com/sase-org/sase/commit/bfe4cc29893c86e3a4a4efd661352be862fa7afd))
* **agent-family:** display custom role status labels (sase-5g.9) ([5eb4508](https://github.com/sase-org/sase/commit/5eb450842dd30b31777259c202e4b722e83e2339))
* **agent-family:** emit role completion lifecycle events ([19e780d](https://github.com/sase-org/sase/commit/19e780dd50ad288b23b280dd69ab36e3efe4bee4))
* move consumed plan files into archive on propose ([8585d19](https://github.com/sase-org/sase/commit/8585d194d6bd805a79dcdf08820e5df7ce48177b))


### Bug Fixes

* **mode-switch:** fast-forward reusable dev checkouts ([a4edccd](https://github.com/sase-org/sase/commit/a4edccd46a18f6506a25d5ced975518b551cb2e8))
* **plan:** archive run approvals through shared choice registry (sase-5g.2) ([5f39034](https://github.com/sase-org/sase/commit/5f390345a4398b549c87953ab4cae82cca21a1f8))
* provider coder aliases inherit [@coder](https://github.com/coder) instead of [@default](https://github.com/default) ([54033e8](https://github.com/sase-org/sase/commit/54033e8b9ababb08d6152b400191bac599137cac))
* recover bare git projects from partial init state ([dff269e](https://github.com/sase-org/sase/commit/dff269e3a8642a84609ae17d7b3c4ba91595f577))
* refresh upstream refs before fast-forward merges ([#205](https://github.com/sase-org/sase/issues/205)) ([75e4470](https://github.com/sase-org/sase/commit/75e4470f2eea6e0d38e64987d9f977c7bee9e33d))
* require core wheel with agent role metadata ([#207](https://github.com/sase-org/sase/issues/207)) ([01babf3](https://github.com/sase-org/sase/commit/01babf3a82e2efd3df7c0771e4eaa1241bab0797))
* resolve standalone workflow scope from workspace ([1b6df81](https://github.com/sase-org/sase/commit/1b6df81760a819d4b1de431b56edcbdf46d60f91))
* stop phantom projects from crashing ace startup ([91743c4](https://github.com/sase-org/sase/commit/91743c4802bffbf930d9013193a796746343b4ec))
* **tui:** make config preview scrolling deterministic ([c1475be](https://github.com/sase-org/sase/commit/c1475bee0af886f4ca31cb53e60582df09bdd9d5))
* **tui:** preserve live file hints across reloads ([c363142](https://github.com/sase-org/sase/commit/c3631420d355e99fe66658a8a3e0002380f93c83))


### Documentation

* add dynamic agent families infographic ([f424add](https://github.com/sase-org/sase/commit/f424add87b6a0a6005083dcbe9b3fc5842828d32))
* add dynamic agent families user manual research ([b9d91d6](https://github.com/sase-org/sase/commit/b9d91d6161335356e4013d77950df00e12b42e6a))
* correct verified inaccuracies in agent families and ACE docs ([9a784e2](https://github.com/sase-org/sase/commit/9a784e2cabc182c3d7c436bde01f939afcfa10f5))
* document VCS ref root completion (sase-5i.6)
* document VCS repo slash completion (sase-5h.6)
* note supersession of agent families research by docs/agent_families.md ([d735e80](https://github.com/sase-org/sase/commit/d735e80509ab592f9f4bb60a298ea66edcd3f1f9))
* refresh docs for recent features and add agent families page ([2b4d8e9](https://github.com/sase-org/sase/commit/2b4d8e9aed2a8ccf6f802cd420a94b33a0152525))

## [0.10.1](https://github.com/sase-org/sase/compare/v0.10.0...v0.10.1) (2026-07-06)


### Features

* add embedded follow-up prompt xprompts (sase-5f.2) ([41b27fb](https://github.com/sase-org/sase/commit/41b27fbaa8481568c1655feb561ac5a51063e0a2))
* compose follow-up xprompts with family attach (sase-5f.5) ([a660d92](https://github.com/sase-org/sase/commit/a660d92277d2f348a4fb67c4025bc19fdd10763b))
* queue family children behind running parents (sase-5f.4) ([dfd9f50](https://github.com/sase-org/sase/commit/dfd9f50f07181b96940a33c1987084c42f402df9))
* support dynamic agent family attach launches (sase-5f.3) ([7b357a0](https://github.com/sase-org/sase/commit/7b357a097d70fb92bffe90c2659f2883a20a9b3b))
* **tui:** add vim + readline editing to config edit inputs ([1c21d26](https://github.com/sase-org/sase/commit/1c21d266a286f0b52f505556813970862bb16788))
* **tui:** adopt vim text areas for modal inputs ([085054e](https://github.com/sase-org/sase/commit/085054e325c5c32667f677eae30a2d04cf8771e6))
* **tui:** expand config edit modal for multiline content ([f56f137](https://github.com/sase-org/sase/commit/f56f137fc88b637959f98cc54f944e8677d8408d))


### Bug Fixes

* **ace:** normalize family child rows (sase-5f.1) ([9caeb0d](https://github.com/sase-org/sase/commit/9caeb0d37921f403d0a9eb3e5a95f2136ba27e94))
* close dynamic family edge cases (sase-5f) ([c5f18ae](https://github.com/sase-org/sase/commit/c5f18ae90c284e866aa79f1ffce9656886af1146))
* harden dev update rust repair flow ([44c9096](https://github.com/sase-org/sase/commit/44c90960ceb99fe30e82bc16fffd690dc2a24b12))
* order slow tool calls by start time ([5f29a7f](https://github.com/sase-org/sase/commit/5f29a7fddcf5afdb0ed24afc4b88fe59ec786530))
* **tui:** align workflow child approval indicators ([3e4c53d](https://github.com/sase-org/sase/commit/3e4c53d359c795a9d80338b5b98fe018688ad99c))
* **tui:** keep bead displays visible while revalidating ([47a7d5d](https://github.com/sase-org/sase/commit/47a7d5dad9ad317e2b4fa26116538d99bfc2266f))
* **tui:** strip ANSI controls from semantic AXE logs ([d6855ae](https://github.com/sase-org/sase/commit/d6855ae890cbafadc80cc7f22d380a11fbf5779d))


### Documentation

* **research:** add dynamic agent families v1/v2 design ([43186b4](https://github.com/sase-org/sase/commit/43186b41b96b75124ee6d4228a75846fd23fc7a4))
* **research:** critique dynamic agent families project note ([6b7b3e9](https://github.com/sase-org/sase/commit/6b7b3e98102d45762a2ce94160b69f553616e742))

## [0.10.0](https://github.com/sase-org/sase/compare/v0.9.1...v0.10.0) (2026-07-05)


### ⚠ BREAKING CHANGES

* #research, #research/image, #research/more, #research/prompt, #research_swarm, and #old_research_swarm are no longer package defaults. Define them in user or project config when needed.
* **mode-switch:** `sase update --to dev` now uses `~/projects/github/<owner>/<repo>` by default instead of flat checkouts under `~/projects/git/<repo>`. Configure `update.dev_root` or move existing checkouts to the owner-nested layout to keep using existing working trees.

### Features

* **mode-switch:** use GitHub dev checkout layout ([672c3ce](https://github.com/sase-org/sase/commit/672c3cea88582de76508080ff5a1639201a0efea))
* remove packaged research xprompts ([bc6a9cc](https://github.com/sase-org/sase/commit/bc6a9cc87f2ef91166c3cd4b344f8afc3318f710))
* **tui:** add guide learn-more links ([3767e7f](https://github.com/sase-org/sase/commit/3767e7ff71e12a042f7a3a8cf66f9a717733fc77))


### Bug Fixes

* **ace:** scope slow tool calls by source ([2bde0b5](https://github.com/sase-org/sase/commit/2bde0b594e11e540c33606870de3fc46781a5d8c))
* **tui:** cap config edit modal value previews ([46f5f4c](https://github.com/sase-org/sase/commit/46f5f4c05fe17392d98b64d1bb4bce4bf071021c))

## [0.9.1](https://github.com/sase-org/sase/compare/v0.9.0...v0.9.1) (2026-07-04)


### Features

* **tui:** add tab guide modal ([bde2155](https://github.com/sase-org/sase/commit/bde21558c0028b4d4b012a25aa8642283fa0022a))


### Bug Fixes

* **axe:** check telegram token sources in chop doctor ([99d2435](https://github.com/sase-org/sase/commit/99d24356bbd93b1622aae2c90f4d2f0a2b8f79d0))

## [0.9.0](https://github.com/sase-org/sase/compare/v0.8.0...v0.9.0) (2026-07-04)


### ⚠ BREAKING CHANGES

* llm_provider.model_aliases is no longer a flat builtin-alias map, and llm_provider.custom_model_aliases is removed. Configure builtin role overrides under llm_provider.model_aliases.builtin and user aliases under llm_provider.model_aliases.custom.

### Features

* **ace:** show sase version instead of PID in the TUI title ([9deb012](https://github.com/sase-org/sase/commit/9deb01206b0de988b6de7827e4ff6253631f0bc8))
* Add support for custom model aliases ([72c6264](https://github.com/sase-org/sase/commit/72c62642ad241a8931583ecbf9a7a1661a63ed97))
* **init:** add skills check mode ([4a23371](https://github.com/sase-org/sase/commit/4a23371ec6fb28742d672b0057ba586e7e3a1e36))
* Migrate SVG framework to fix screenshot test determinism ([ed95a7c](https://github.com/sase-org/sase/commit/ed95a7c303438c8c9c71db95584ef7673c0c3d89))
* **plugin:** restart after plugin package changes ([6910d18](https://github.com/sase-org/sase/commit/6910d1842ad30eb3ed7876bedfced0dca5fbeaf5))
* **tui:** add PRs onboarding empty state ([5ab9907](https://github.com/sase-org/sase/commit/5ab9907f2b45b34300c36e29c2a4a65a87427258))
* **tui:** improve config edit navigation ([2e38f97](https://github.com/sase-org/sase/commit/2e38f97a8ca6dcb38148d0484c5ea53c27a729b5))
* **tui:** surface slow tool calls in agent metadata ([4536419](https://github.com/sase-org/sase/commit/4536419035284fb5064c9a09a964986362f6a8f0))
* unify model alias config ([8b0ff2c](https://github.com/sase-org/sase/commit/8b0ff2c9fc2bd6a3eb95e16aa2ad2bbe8f2999d0))
* **update:** add install mode switching ([5131ec8](https://github.com/sase-org/sase/commit/5131ec849b03b3a00232d1ea5c4e04edc56ad0ab))
* **xprompt:** diagnose unresolved xprompt references ([d698779](https://github.com/sase-org/sase/commit/d698779c60c01082a75f2a642dd9f23cd986994f))


### Bug Fixes

* Pin "local time" to the configured timezone everywhere ([c318af1](https://github.com/sase-org/sase/commit/c318af1e724b3bfced9347f4bbb3ce1b442e7e52))
* Tests and limit 'just test' to 1/4 the CPUs ([6fb24ab](https://github.com/sase-org/sase/commit/6fb24ab6ac73dcc00810bdfa415cc40891dd1964))
* **tui:** make Models-panel alias description strip visible ([5151906](https://github.com/sase-org/sase/commit/51519066ac93c7bd77467a917f1ca2e4d6f277d4))
* **tui:** show configured PROJECT_NAME in VCS xprompt prefill surfaces ([2856003](https://github.com/sase-org/sase/commit/2856003484aac9950419951b94e25fd0c5afd095))


### Documentation

* add blog-launch audit of xprompts, agents tab, and TUI ([5ad8673](https://github.com/sase-org/sase/commit/5ad86738c375645de32abd05d41a08d11f69e2c7))
* add launch audit infographic ([da99696](https://github.com/sase-org/sase/commit/da996960eb2df36067e18a5c3f5a8b47ea9ae1f8))
* add launch blog TUI research audit ([8e25a3d](https://github.com/sase-org/sase/commit/8e25a3d050b4c654414a62fb37f32fde0efa40f9))
* consolidate launch blog research audit ([9fd56bd](https://github.com/sase-org/sase/commit/9fd56bd62e77039834e10dcf58f33733919326ba))
* refresh SASE quickstart workspace examples ([286446e](https://github.com/sase-org/sase/commit/286446e557d4ce1dd3dc1f5a0b23c6f0762d444d))
* **research:** add blog launch readiness audit for xprompts, agents tab, and install flow ([67929ab](https://github.com/sase-org/sase/commit/67929abea95837d22b15b0a9d317100a70039a01))

## [0.8.0](https://github.com/sase-org/sase/compare/v0.7.1...v0.8.0) (2026-07-02)


### ⚠ BREAKING CHANGES

* ace.inactive_seconds and the ACE idle/activity keybindings and UI surfaces are removed; old idle key overrides are retired during keymap loading.
* **cli:** `sase run` no longer supports the foreground runner, `--list`, or `--resume` flags. Use the default detached launch path, and use `#fork` or `#fork_by_chat` for retrying or branching from existing chats.

### Features

* **cli:** make run detached-only ([b20637f](https://github.com/sase-org/sase/commit/b20637f4f09fc5eb9e72ee1dbb3fdcdbc728f8d2))
* remove ACE idle activity tracking ([a39f524](https://github.com/sase-org/sase/commit/a39f5240141dd057b8ac5af0fdd103db6e1e7f22))


### Bug Fixes

* archive closed submitted checks ([df54ba5](https://github.com/sase-org/sase/commit/df54ba51bcc7400bea1d75c41ddf05032115daba))

## [0.7.1](https://github.com/sase-org/sase/compare/v0.7.0...v0.7.1) (2026-07-02)


### Bug Fixes

* **ace:** include STARTING agents in Agents tab headline total ([97f34fa](https://github.com/sase-org/sase/commit/97f34fa983c53adfe1e5ddee4753c7bf3d234ae9))
* package config schema in wheel ([3580f1c](https://github.com/sase-org/sase/commit/3580f1c68810f9409fd7dded341ea312cf39e8bf))


### Documentation

* recommend plain `uv tool install sase` and add INSTALL.md ([702c8fe](https://github.com/sase-org/sase/commit/702c8fee83d33d8eecd3440a64e4f3b303c80c18))

## [0.7.0](https://github.com/sase-org/sase/compare/v0.6.1...v0.7.0) (2026-07-01)


### ⚠ BREAKING CHANGES

* **llm_provider:** The worker model-override lane is removed. The `@worker` and `@other` implicit model aliases are retired, the `role="worker"` temporary-override API and `llm_provider.worker_models` config resolvers are gone, and bead/epic launches now use the `@phase_worker`, `@epic_lander`, and `@epic_creator` role aliases.
* **axe:** accepted-plan coder follow-ups now launch with a coder alias directive (`%model:@<provider>_coder`) instead of a concrete worker-lane model directive.
* **llm_provider:** The public config schema no longer accepts `llm_provider.worker_models` (migrate each entry to a `<provider>_coder` alias under `llm_provider.model_aliases`) or a stale `llm_provider.default_model` (move its value to `llm_provider.model_aliases.default`). `sase doctor` reports both with migration guidance.
* **ace:** The Tab/Shift-Tab cycling order changed because Agents is now the first tab instead of the second.
* Model aliases in %model and %m directives must now use the @alias form. For example, use %model:@worker or %model:@#agy_flash instead of %model:worker or %model:#agy_flash.
* **ace:** ACE leader-mode default chords are reassigned. `,o` no longer opens Model Overrides (now `,m`); Mentor Review moves to `,C`; and the Agents-tab repro bundle capture moves to `,B`. Re-bind via `ace.keymaps.modes.leader_mode.keys` to restore the previous chords.

### Features

* **ace:** models panel for viewing aliases and per-alias overrides (sase-5e.2) ([df160e3](https://github.com/sase-org/sase/commit/df160e361c289688cf097727c0c4041eff12ba28))
* **ace:** move Agents to the first tab position ([2404af6](https://github.com/sase-org/sase/commit/2404af6d2a8d32eb2deb910298b25ee50219faa1))
* **ace:** move Model Overrides to leader `,m` ([0edfb84](https://github.com/sase-org/sase/commit/0edfb846b2bc80a4288e7a1a10d34686c935ddc6))
* **ace:** persistent alias editing + commit/push in models panel (sase-5e.3) ([aebfbf2](https://github.com/sase-org/sase/commit/aebfbf247cef8d783fffdc327b90c46c3cfeaee3))
* **ace:** render bare count in Agents info strip ([937278e](https://github.com/sase-org/sase/commit/937278ecb1b0723a4aa42d55fe60f1cd635e8660))
* **ace:** show dev update diff stats in restart toast ([c78d5c2](https://github.com/sase-org/sase/commit/c78d5c250064809639ac4cb1ba8257d638ca9222))
* **ace:** top-bar indicator for non-default alias overrides (sase-5e.4) ([c1cd662](https://github.com/sase-org/sase/commit/c1cd66291d8071d4192fd820ca692e347bdd56b2))
* add leader shortcut for SASE updates ([cbb6135](https://github.com/sase-org/sase/commit/cbb61358a39faaf7a96609d5f09e2bb0e6546be5))
* **axe:** route plan coder follow-ups through provider coder alias (sase-5d.3) ([02a9d4d](https://github.com/sase-org/sase/commit/02a9d4db9496a6a821f05234e547fdb79edcd19d))
* **bead:** default closed list results to newest 20 ([b926688](https://github.com/sase-org/sase/commit/b9266887d7f25c0950ef3a4a0a77aa1218256ae0))
* **bead:** limit list results and fall back to closed ([4d3264c](https://github.com/sase-org/sase/commit/4d3264c366be8562da0025eaf7828b20f72f3d34))
* **llm_provider:** add core alias resolver and [@default](https://github.com/default) launch semantics (sase-5d.1) ([4d1a4b7](https://github.com/sase-org/sase/commit/4d1a4b71ff832c07364f242848371a85dfa7a0e9))
* **llm_provider:** migrate alias parser, completion, doctor, and schema (sase-5d.2) ([829b43d](https://github.com/sase-org/sase/commit/829b43d25ddf4a164cd0a44e88c9bf034a2c7805))
* **llm_provider:** per-alias temporary model overrides (sase-5e.1) ([9f93305](https://github.com/sase-org/sase/commit/9f933053e8b9e9b75c200d1ae72d82f9d2fc98f7))
* **llm_provider:** route bead/epic launches through role aliases and retire worker lane (sase-5d.4) ([788e321](https://github.com/sase-org/sase/commit/788e321c6445309771f65c300d91841d7e1a55f1))
* recommend plugins during agents onboarding ([9e77bd3](https://github.com/sase-org/sase/commit/9e77bd393aed7b6bf604abbfb88c7e9ed8c65784))
* require @ marker for model aliases ([5856cd7](https://github.com/sase-org/sase/commit/5856cd7a0c6746156c865a1e605556672a68e6e7))


### Bug Fixes

* **ace:** hide onboarding launch hint without targets ([1b9395b](https://github.com/sase-org/sase/commit/1b9395b059364c4c3f04934d3c079a4dfedcc29f))
* **ace:** improve post-update toast layout ([dbaf6ad](https://github.com/sase-org/sase/commit/dbaf6adcf11571e7eb07d30f0bac71c7a2226ed1))
* **ace:** order agents-onboarding tabs to match the tab bar ([282fc6c](https://github.com/sase-org/sase/commit/282fc6ccf29c72e3ff003d878afccfaff4714153))
* **chezmoi:** apply target path on config edits and always use --force ([09d0c44](https://github.com/sase-org/sase/commit/09d0c44ddb955a7503e61169efee1b21c6dafd62))
* **config:** preserve YAML source around scalar edits ([0844ec9](https://github.com/sase-org/sase/commit/0844ec91505e99124319455d0cda0de7da8c1b5c))
* **dev-update:** fetch release tags from upstream ([31c9895](https://github.com/sase-org/sase/commit/31c98951ce0acb47910225275ff318c2a15b1c3a))
* dismiss completion notifications with agent rows ([86a4b6b](https://github.com/sase-org/sase/commit/86a4b6b8c21c65af943293b10b431c8321b10a42))
* handle quoted Antigravity model directives ([0e0020b](https://github.com/sase-org/sase/commit/0e0020b4aeae7536f3ed7ab946b6c24429ff57fd))
* **init:** skip project-scoped setup outside VCS dirs ([08ef0f2](https://github.com/sase-org/sase/commit/08ef0f24655c204c2ee097a6ae25c140bbe0e28f))
* mark answered question continuations ([631beaf](https://github.com/sase-org/sase/commit/631beaf863226145930cd0bd9b6d45f175aa7b58))
* show agents onboarding when no rows are visible ([f783204](https://github.com/sase-org/sase/commit/f7832045b7ec7052a3454aef208a86786b68d413))
* **tui:** align Models panel state column ([d297933](https://github.com/sase-org/sase/commit/d2979336e22b6c692fa91e266c32b3a4d7fc8ee5))
* **tui:** recommend update keymap in update notices ([8ba81d7](https://github.com/sase-org/sase/commit/8ba81d7ff03166ff0e54df1ac448ea1cb4e6d1b6))
* **tui:** show provider coder model kind as coder ([c8b9321](https://github.com/sase-org/sase/commit/c8b93210fb722bebcba1bacbf363b531f3549ed9))


### Documentation

* **ace:** document unified Models panel and per-alias overrides (sase-5e.5) ([37b8257](https://github.com/sase-org/sase/commit/37b8257d2fd96fe48cb42f0bee1628991ec0a433))
* Add "Agent Hoods" and "Agent Neighbors" memory/glossary.md entries ([c05e092](https://github.com/sase-org/sase/commit/c05e0920b7f07173a981390b06bb8df543e50f62))
* clarify GitHub plugin install and Enterprise setup ([d337fc0](https://github.com/sase-org/sase/commit/d337fc01f315b086de8ff134a2d0dffa70a1a1c9))
* **llm_provider:** align docs and shipped config with role-alias model (sase-5d.5) ([a27b457](https://github.com/sase-org/sase/commit/a27b4572ecc94114f06e808ba0697390678bdb98))

## [0.6.1](https://github.com/sase-org/sase/compare/v0.6.0...v0.6.1) (2026-06-30)


### Bug Fixes

* require sase-core-rs 0.3 ([5474f44](https://github.com/sase-org/sase/commit/5474f4491032de750e1f1ee2a524cf7dd0deb066))

## [0.6.0](https://github.com/sase-org/sase/compare/v0.5.0...v0.6.0) (2026-06-29)


### ⚠ BREAKING CHANGES

* **ace:** Config Center no longer provides the one-key sibling_repos to linked_repos migration action. Edit sibling_repos and linked_repos directly.
* The Plugins tab no longer supports the `S` SASE update shortcut or the `U` update-all shortcut. Use `u` for the comprehensive update and `U` for the selected plugin update.
* `allocate_project_alias` and `ensure_project_alias_locked` are no longer exported from `sase.project_aliases`.
* **commit:** commit footer tag keys produced by `sase commit` are now prefixed with `SASE_` (e.g. `SASE_TYPE`, `SASE_AGENT`, `SASE_BUG`, and configured `vcs_provider.pr_tags` keys). External tooling that parses the unprefixed footer keys must be updated to accept the prefixed names. Historical unprefixed keys remain readable; commit history is not migrated.
* **ace:** The standalone leader.task_queue binding and default ,t shortcut are removed. Use the Admin Center Tasks tab or the "Open tasks panel" command instead.
* **tui:** the default Agents-tab keys for opening artifacts and accepting proposals are swapped (`a` opens artifacts, `A` accepts). Users relying on the old defaults should rebind via `ace.keymaps.app` config.
* **tui:** The standalone `,L` log-panel leader command is retired; open logs through Admin Center's Logs tab or the keyless command-palette entry.
* **cli:** `sase amd`, `sase amd list`, `sase amd init`, and `sase init amd` are removed. Use `sase memory agent-docs list` to inspect agent documents and `sase memory init` as the combined initializer.
* **ace:** The `%edit` / `%e` prompt directive has been removed. To reload an edited prompt for review, put ` @` at the end of any line from your external editor instead.
* **cli:** the `sase plugin list` and `sase plugin doctor` commands are removed. Use `sase version -v`/`sase version -j` for installed plugin packages, `sase doctor` (`plugins.resources`, `plugins.github`) for resource/provider diagnostics, and `sase axe chop list`/`sase axe chop doctor` for chop scripts and Telegram chop setup.
* %time is no longer accepted as a live launch directive; use %wait(time=<time>) or #t:<time> instead.
* `%plan`, `%tale`, `%epic`, `%approve`, `%p`, and `%t` are no longer recognized as auto-approval directives. Use `%auto`, `%auto:tale`, or `%auto:epic` instead.

### Features

* **ace:** add agent name completions ([1c8acbd](https://github.com/sase-org/sase/commit/1c8acbd9447ed47c6d11a4c00a422feea721e8e8))
* **ace:** add prompt jump to definitions ([1b4be00](https://github.com/sase-org/sase/commit/1b4be006bc4bdb5433d64603d2437a163e0d1dcd))
* **ace:** add prompt preview keymap ([43d2d05](https://github.com/sase-org/sase/commit/43d2d05e5598df0b8d4bd0a483c8f43b19367b41))
* **ace:** add quit/restart menu ([e70f5e4](https://github.com/sase-org/sase/commit/e70f5e483bc7b8661749fc82db9ef33cf2a05491))
* **ace:** check for updates every 10 minutes on ACE startup ([1dde590](https://github.com/sase-org/sase/commit/1dde59049348f5dc8d16892cdd8f9000b0562e16))
* **ace:** claim fresh workspaces for agent reverts ([5fd8741](https://github.com/sase-org/sase/commit/5fd874121bef6eb10c9110def7d44b2a0bd2ae16))
* **ace:** complete directive argument values ([d2b31ce](https://github.com/sase-org/sase/commit/d2b31cefcd68d341509c224f5c6f384ee4163a17))
* **ace:** move agent row pencil after runtime suffix ([af132fb](https://github.com/sase-org/sase/commit/af132fb8eb329e27294a9d7c7de9512271924655))
* **ace:** move task queue into admin center ([f14944c](https://github.com/sase-org/sase/commit/f14944cf58337f740d8cfa85411fdb30a63c6957))
* **ace:** open directive menu on bare percent ([8f53363](https://github.com/sase-org/sase/commit/8f5336300aa23ef9f24136749d3a5ebbb1177a1a))
* **ace:** open directive menu on bare percent ([8ebcec3](https://github.com/sase-org/sase/commit/8ebcec3cadf40ecbd63490fbd247f1513504f3f3))
* **ace:** persist Admin Center tab across TUI restarts ([ca24e3a](https://github.com/sase-org/sase/commit/ca24e3af8a732855948dbfd102634cce1b9c8526))
* **ace:** remove repo-key migration UI ([b453ab7](https://github.com/sase-org/sase/commit/b453ab7e507bff2ea1aec08c6511c01a4cea92f8))
* **ace:** replace %edit directive with editor ` @` review marker ([4fc6077](https://github.com/sase-org/sase/commit/4fc6077cfd6f35917c0b8782192f05aefb285df8))
* **ace:** replace agent siblings with hood-based neighbors ([d121dcd](https://github.com/sase-org/sase/commit/d121dcd06c0ef5191b1d0e4c83e89f2c5db685c4))
* **ace:** revert agent changes across linked repos ([008972d](https://github.com/sase-org/sase/commit/008972df48a2c59ed6c4c3d2da640303d72391c9))
* **ace:** show post-update version toast ([b02dd41](https://github.com/sase-org/sase/commit/b02dd4197175ccec6616349ca196c61fd80f6438))
* **ace:** show startup toast for available updates ([d22ef80](https://github.com/sase-org/sase/commit/d22ef802056d18a98806f81b7be598bc101535f7))
* add editable dev update backend (sase-5c.1) ([c4581d9](https://github.com/sase-org/sase/commit/c4581d91dc1ea42faf41b6fbe81d51c89d020c4a))
* add numbered Admin Center tab navigation ([d4be96a](https://github.com/sase-org/sase/commit/d4be96a4cd50990414fdbdee699e43f79b1a9002))
* add persistent prompt stash pins ([8326560](https://github.com/sase-org/sase/commit/832656055139ccd92dfdaf412081aab1e3c26796))
* **cli:** migrate `sase amd` into `sase memory` ([128d0d2](https://github.com/sase-org/sase/commit/128d0d26a5d9f64fa71d912ff81186093fcfaca6))
* **cli:** retire legacy `sase plugin` command ([41afaf7](https://github.com/sase-org/sase/commit/41afaf7f5ac41dfed6dc163b8666dfc05862b95c))
* **commit:** prefix SASE commit footer tags with SASE_ ([d671181](https://github.com/sase-org/sase/commit/d6711811f24a03542095fa5e085416d1bfa4cfb2))
* complete model directive values ([4964ee0](https://github.com/sase-org/sase/commit/4964ee0eeb0b72bde81b0340a5aa168195a6d9ea))
* **config:** pretty render structured config values ([f6fa3fb](https://github.com/sase-org/sase/commit/f6fa3fbc6384078e1ade4257dfc711af18b9373b))
* **directives:** make %e an alias for %effort ([1e40bf1](https://github.com/sase-org/sase/commit/1e40bf11f72b2c535eee0fa1cedb962919dce531))
* **doctor:** guard model xprompt presets against provider fallback ([a708cd4](https://github.com/sase-org/sase/commit/a708cd44b81bb8dadfebea0bda2eceb0894af90a))
* **llm:** wrap agent prompts at 80 columns ([b09728a](https://github.com/sase-org/sase/commit/b09728a8c211caaed28dd06ac2cfebc7f7725454))
* **main:** add top-level `sase update` command (sase-58.2) ([6578bb3](https://github.com/sase-org/sase/commit/6578bb36846bbc147c9219398dbe1361d409a5f7))
* **memory:** add fence-aware short-term memory inlining helpers (sase-5b.1) ([4827c09](https://github.com/sase-org/sase/commit/4827c093e0180e121d76d6699e53d69dd73402dc))
* **memory:** fold dirty memory edits into init commits ([04595d3](https://github.com/sase-org/sase/commit/04595d3159d7451bca8a1eef28b24ee6c7d6f200))
* **memory:** inline short-term memory into `AGENTS.md` (sase-5b.2) ([41de8f1](https://github.com/sase-org/sase/commit/41de8f1b3ee20673802a4a6817a65bb354f3a3ba))
* **memory:** number inlined short memory headers ([b091695](https://github.com/sase-org/sase/commit/b091695f7bf9515ce096364a786e685b2e4e501d))
* **memory:** provider files become full copies of `AGENTS.md` (sase-5b.3) ([394f41b](https://github.com/sase-org/sase/commit/394f41b878b8010ee69b68b8f2caf37ee6d198c2))
* **memory:** regenerate artifacts with inlined short-term memory (sase-5b.4) ([17bc99c](https://github.com/sase-org/sase/commit/17bc99cbd8a7d340f2c9547ff9a77d95e41ca4e6))
* **memory:** shorten inlined memory headers ([57b6a4e](https://github.com/sase-org/sase/commit/57b6a4ed2c31f83ced4e44dc4336c69977cde0f6))
* move time waits under the wait directive ([86322d4](https://github.com/sase-org/sase/commit/86322d43b2b77acd82cd836daae9d77cf794dc0f))
* **notifications:** record handled plan actions in shared store ([02fb83e](https://github.com/sase-org/sase/commit/02fb83e8928441bef861fdfc40cbde7d35b5388a))
* **plan:** add `sase plan reject` CLI command ([83f155c](https://github.com/sase-org/sase/commit/83f155cf162dcd77ad1e530b0d1aa259f3627764))
* **plugin:** add `sase plugin install` and `sase plugin update` (sase-58.3) ([e9d1742](https://github.com/sase-org/sase/commit/e9d17424efc8c7813c232ce0c2d64bb45ca8bd56))
* **plugins:** add `sase plugin list` command + rendering (sase-57.2) ([cd7f4f6](https://github.com/sase-org/sase/commit/cd7f4f67f1ea69dab9b145519b5d5b0baa4a7a56))
* **plugins:** add `sase plugin show` command + rendering (sase-57.3) ([518e4f8](https://github.com/sase-org/sase/commit/518e4f8854c3f50909e62866b1f6dbe333bfe5b8))
* **plugins:** add `sase plugin uninstall <plugin>` ([2834fe4](https://github.com/sase-org/sase/commit/2834fe4158137388c8cd70b8c5258d9f3493d4a3))
* **plugins:** add plugin catalog engine (library-only) (sase-57.1) ([cc0e304](https://github.com/sase-org/sase/commit/cc0e304ce1807e14c724e38ac18f49df6cd9e46f))
* **plugin:** show latest version indicators ([235d8a6](https://github.com/sase-org/sase/commit/235d8a6c263cd960edfefc03423335035e4cf87b))
* **plugins:** show dev latest versions (sase-5c.2) ([4a06b31](https://github.com/sase-org/sase/commit/4a06b3128522f340f2c5c09ad7a69ef3a73d7b39))
* record source prompt for multi-agent transcripts ([5550be6](https://github.com/sase-org/sase/commit/5550be6015252ef589e1ebc3a15293445b5f07ff))
* remove legacy project alias allocation helpers ([48d3783](https://github.com/sase-org/sase/commit/48d37839417cf8767278a1f7bf39e5365fd1d4c3))
* rework plugin update keybindings ([c095d43](https://github.com/sase-org/sase/commit/c095d438d9ce42eaf10f800e5ed9defe69ee47d4))
* save prompt drafts as xprompts ([8428b79](https://github.com/sase-org/sase/commit/8428b7962fe6346ab31a7712c391025641a1ee9e))
* show multi-repo commit results in agents panel ([68720ff](https://github.com/sase-org/sase/commit/68720ff0b700ed33de26212e7b3e9952d1d28524))
* support dev execution in sase update (sase-5c.3) ([d80fc0c](https://github.com/sase-org/sase/commit/d80fc0c3fcc75a8489e9d38373c82f6d8acc814e))
* support project display names ([1cbe79f](https://github.com/sase-org/sase/commit/1cbe79f91fd773dc1d865065be8b924a9e971cc7))
* **tui:** add "Create a new snippet" option to prompt save menu ([0311120](https://github.com/sase-org/sase/commit/0311120d48b97deae8b0ba88a76c0607d5f02083))
* **tui:** add agents tab onboarding state ([af0105b](https://github.com/sase-org/sase/commit/af0105be98cb39f8f38b2a1108c31e4db6460759))
* **tui:** add cancel-all prompt stack chord ([f2ac8b2](https://github.com/sase-org/sase/commit/f2ac8b20f3bb5615091372316870b70538952b70))
* **tui:** add command palette position indicator ([c772feb](https://github.com/sase-org/sase/commit/c772feb216286526e1a1d3a4f92e3648e105cb7f))
* **tui:** add config detail scroll keys ([75deba2](https://github.com/sase-org/sase/commit/75deba204262c26b7040898595f07a4262edf8cc))
* **tui:** add config detail scroll shortcuts ([ed5686f](https://github.com/sase-org/sase/commit/ed5686f6d4d3da95aa241ffa0bb82211d98afeac))
* **tui:** add Ctrl+I to load xprompt from Admin Center XPrompts tab ([8b0d270](https://github.com/sase-org/sase/commit/8b0d2707e6bf992f6f2df020ce6cad2e3a9b2dd2))
* **tui:** add five-stop Admin Center title gradient ([005fe0d](https://github.com/sase-org/sase/commit/005fe0de14c92301a73f85a585f020e154925a2c))
* **tui:** add gX / Ctrl+G X to convert prompt pane to local xprompt ([5b9e38f](https://github.com/sase-org/sase/commit/5b9e38fd0b0d603ba7ee7355968da5e197d551fd))
* **tui:** add Plugins detail panel, refresh, offline and verbose toggles (sase-59.3) ([d0a020f](https://github.com/sase-org/sase/commit/d0a020fe67ba14c01850f7dbfa1533771afb2338))
* **tui:** add Plugins install action with confirm-preview modal (sase-59.4) ([28b1780](https://github.com/sase-org/sase/commit/28b1780c88e8d8afd9e97a136ca61b55427d73d6))
* **tui:** add Plugins tab with read-only list browse (sase-59.2) ([5b07536](https://github.com/sase-org/sase/commit/5b07536e6ef0d34d064e8dc16ee8828904a46529))
* **tui:** add Plugins update and update-all actions with confirm-preview (sase-59.5) ([a57001b](https://github.com/sase-org/sase/commit/a57001bc24b88392193fd89d9d7218d032ded315))
* **tui:** add Projects pane to the ACE Admin Center (sase-5a.1) ([be370bd](https://github.com/sase-org/sase/commit/be370bd2ce08a6f024415688a2e0aefa2b428fa2))
* **tui:** add Updates tab core updater ([46bf6e7](https://github.com/sase-org/sase/commit/46bf6e7bcae2f8d08d3b73e430f47418fc5770ea))
* **tui:** always offer snippet creation from gx save panel ([590289a](https://github.com/sase-org/sase/commit/590289a7d27ad73c00c6936623b5ec97905cbcf1))
* **tui:** auto-reload xprompt completion catalog ([1a51990](https://github.com/sase-org/sase/commit/1a51990c80bd18998a26bf2bf3cc47a5a786887b))
* **tui:** auto-restore lone prompt stash entry ([4c38617](https://github.com/sase-org/sase/commit/4c386170b373672f5ba1c0a3e68ce480fb41513e))
* **tui:** close Admin Center after confirming full SASE update ([f33532d](https://github.com/sase-org/sase/commit/f33532d9d66ae8894fbec264bc541a1609f9463c))
* **tui:** colorize confirm dialog content ([cd84ab5](https://github.com/sase-org/sase/commit/cd84ab5aade0bc7788ac5dc2573bfc43d24bb1d8))
* **tui:** describe Admin Center tabs ([9ac9d31](https://github.com/sase-org/sase/commit/9ac9d31c9ed0be1b26a32466c18a07fd53083832))
* **tui:** flag unknown waited-for agents ([f9b635d](https://github.com/sase-org/sase/commit/f9b635df2f79017f5415b50b4253bbbbca0a415f))
* **tui:** hide workflow child step prefixes ([50cfd8a](https://github.com/sase-org/sase/commit/50cfd8a0341a2acdce6fd4e71e68266a1093cb08))
* **tui:** include ancestors in agent neighbor jumps ([4ffd1f1](https://github.com/sase-org/sase/commit/4ffd1f1442105cd333977ce15157fa349ea4cbc2))
* **tui:** include descendants in agent neighbor navigation ([8c318e7](https://github.com/sase-org/sase/commit/8c318e7d20cf0e754f6b3478c82bbf3734a5588c))
* **tui:** make ACE suspend handoffs watchdog-aware ([a4afcdf](https://github.com/sase-org/sase/commit/a4afcdfecb7720a4d39e7fa7e753b942449cbf41))
* **tui:** merge tasks and logs under operations ([192a4dc](https://github.com/sase-org/sase/commit/192a4dc940b972b235f03696e2e6f62bf69edee7))
* **tui:** move logs into Admin Center ([4ffe90b](https://github.com/sase-org/sase/commit/4ffe90b280bb983204c54bbc23835e8790f79b09))
* **tui:** move updates badge left of model indicator ([afb7b74](https://github.com/sase-org/sase/commit/afb7b74147d7e80f5d3485783c05399ee4c17378))
* **tui:** persist agent directive edits in background ([d309209](https://github.com/sase-org/sase/commit/d3092097634024e4d000201137a1aedfd918d742))
* **tui:** polish Plugins tab help, docs, and hints (sase-59.6) ([a05523a](https://github.com/sase-org/sase/commit/a05523ac014ce1ac285432c5e36a91430440558c))
* **tui:** rebind prompt-history load-more to Ctrl+K ([095f4d6](https://github.com/sase-org/sase/commit/095f4d656a0392f8c7a084803cb9df964f486ef2))
* **tui:** redesign Admin Center header with gradient title and helm icon ([8c3a285](https://github.com/sase-org/sase/commit/8c3a285492ab2f7b7e951cf76d9e8ef506824ced))
* **tui:** redesign agent wait modal ([aabf7d1](https://github.com/sase-org/sase/commit/aabf7d1cae9e25cf3f2ccc641b10b1610bcb89ce))
* **tui:** redesign revert confirmation modal ([7cd69a7](https://github.com/sase-org/sase/commit/7cd69a7464df8737a1a87e9c0750fc00851cb3a4))
* **tui:** redesign SASE Config panel ([df3f47d](https://github.com/sase-org/sase/commit/df3f47dd3605645b44ba1c6cd5dc145c8e4cce4c))
* **tui:** remove icon from Admin Center title ([b541a0c](https://github.com/sase-org/sase/commit/b541a0cb6f86306fe68987cfb01c79f80590c77a))
* **tui:** rename SASE Config to Admin Center ([b9c3692](https://github.com/sase-org/sase/commit/b9c3692ee13a35267c052435db032de2a33fe86f))
* **tui:** render Auto metadata before Xprompts ([b68ffc3](https://github.com/sase-org/sase/commit/b68ffc3ef8d4333434a9e99fd1798ce0f83517b3))
* **tui:** render Model metadata between Auto and Xprompts ([db1eba5](https://github.com/sase-org/sase/commit/db1eba5eb7acf96be5ee90d35f6f6c06bbbd2ded))
* **tui:** restore prompt stash rows by number ([64de8e9](https://github.com/sase-org/sase/commit/64de8e9bcbe7879cc3a8c4866b7ca09ddc8242dd))
* **tui:** shorten Agents wait metadata label to "Wait:" ([e84474f](https://github.com/sase-org/sase/commit/e84474f5dd97e2aedd6896e606ad0b70e308c6c1))
* **tui:** show concise wait countdown rows ([1261bfe](https://github.com/sase-org/sase/commit/1261bfeaefa67d5ee806422a69a71a8e40afea53))
* **tui:** show persistent updates indicator ([6f9e54f](https://github.com/sase-org/sase/commit/6f9e54fe6d1a6123a67a3ad553e56315d376625a))
* **tui:** show waiting dependency status badges ([f4c1acf](https://github.com/sase-org/sase/commit/f4c1acf36ae74b9bea7594daafd11284b7a08870))
* **tui:** split Admin Center Operations back into Logs and Tasks tabs ([81f8374](https://github.com/sase-org/sase/commit/81f83742e1af11344b1e8efafd3d903fcb3da610))
* **tui:** stash prompt drafts on restart ([b54e0d8](https://github.com/sase-org/sase/commit/b54e0d877c9f3ec42f746b72ad3ffaa18f9208e9))
* **tui:** stream live task output in tasks tab ([2b2cd38](https://github.com/sase-org/sase/commit/2b2cd389eb916149de61fb102ea9365a3bd11da6))
* **tui:** support editable dev updates in admin center (sase-5c.4) ([571fdbb](https://github.com/sase-org/sase/commit/571fdbbe7a080643dbd3f05c74bceda7caf8b479))
* **tui:** surface persisted commit diffs ([9b93600](https://github.com/sase-org/sase/commit/9b93600a48913f3cb6f63d60d59310dae960847e))
* **tui:** swap Agents-tab `a`/`A` keymap defaults ([e8e17de](https://github.com/sase-org/sase/commit/e8e17de24eea0942876645325d1c989d681f3cc7))
* **tui:** swap idle keymaps ([3308b2c](https://github.com/sase-org/sase/commit/3308b2c86f93a7634c280127055045f5179a2200))
* **tui:** underline SASE Config title ([45afc6e](https://github.com/sase-org/sase/commit/45afc6eabad41beef66f27024fe741f2115ea6e4))
* **tui:** update pinned prompt stash ([a439daf](https://github.com/sase-org/sase/commit/a439daf2f52d2fb1987f45e6bc113c8372f32dfc))
* unify auto approval directive ([36559c4](https://github.com/sase-org/sase/commit/36559c4b7051ef1bdb42956bdfc2d9b36acd16b2))
* **updates:** show incoming commits for available updates ([d6117f3](https://github.com/sase-org/sase/commit/d6117f3d33e890001fd4f4b27514c65fd13941c1))
* **uv_tool:** add shared uv tool engine (sase-58.1) ([5357c14](https://github.com/sase-org/sase/commit/5357c14c7dd16c38c8cbc390050ec77411761616))
* **wait:** support %wait on submitted plan agents ([53428f1](https://github.com/sase-org/sase/commit/53428f1e76fb0e33f197d0851a4142da25893859))


### Bug Fixes

* **ace:** enter normal mode when escaping prompt completion ([58f1230](https://github.com/sase-org/sase/commit/58f12304f8c7908723ad39029ab12a26d2a7e262))
* **ace:** improve plugin detail scrolling ([ec82208](https://github.com/sase-org/sase/commit/ec82208ef438c5bb4d51d345807451a137f4a124))
* **ace:** lift frontmatter on prompt history loads ([ae869eb](https://github.com/sase-org/sase/commit/ae869eb5ddf31ffc4476dcbb56c8c83ed3447969))
* **ace:** open prompt stash panel on empty ctrl-s ([c1afd14](https://github.com/sase-org/sase/commit/c1afd14a547d953418b74cb9ff0525e4b4a47b82))
* **ace:** return to metadata on Ctrl-P after zoom file reveal ([ab5ae80](https://github.com/sase-org/sase/commit/ab5ae80407c374c3c7c78da8adefe73da7524ee5))
* **ace:** show pencil badge on redirected Plan agent rows ([c98a35e](https://github.com/sase-org/sase/commit/c98a35e0c5135e557a0e4e28f493e7438d748ead))
* **ace:** stop axe robustly before quit ([83f7bf4](https://github.com/sase-org/sase/commit/83f7bf4a8a2114000f48ccdf861f0c684e44f5ba))
* auto-approve pending plans during wait loop ([1add4d9](https://github.com/sase-org/sase/commit/1add4d9d8a0d4409439ed80a5b0c2521a53ecdd5))
* **axe:** avoid self-signaling during daemon stop ([94f9cb8](https://github.com/sase-org/sase/commit/94f9cb8dead1035f828c940f17ed963cc83d8096))
* **axe:** prefer recorded daemon lock holder ([50f9a16](https://github.com/sase-org/sase/commit/50f9a1624fdf85c55c9c6ee68fbbd443a6999448))
* bound cancellation and cache freshness edge cases ([#190](https://github.com/sase-org/sase/issues/190)) ([844427a](https://github.com/sase-org/sase/commit/844427a91b0e99aeb059407348e5f72fdcf482fe))
* clean up stale starting agent claims ([39f362c](https://github.com/sase-org/sase/commit/39f362ccc38df7e0e29d90af2cc1ac7a9aebd01d))
* guard sase-core-rs source version skew ([350c2a3](https://github.com/sase-org/sase/commit/350c2a3590a780388432b5dbe1e932487257ccee))
* **history:** require five-word prompt entries ([f1f8677](https://github.com/sase-org/sase/commit/f1f86778359e09a27feef96b9ef35caa31e0401a))
* **history:** require three-word prompt entries ([a71f97a](https://github.com/sase-org/sase/commit/a71f97ad67babde830941ce7488aba39a51c142a))
* **init-memory:** keep managed instructions prettier-stable ([#191](https://github.com/sase-org/sase/issues/191)) ([1e036c7](https://github.com/sase-org/sase/commit/1e036c7ef3e5408ea5c3c9789273592a25cf703d))
* keep auto plan approvals non-committing ([a3e494d](https://github.com/sase-org/sase/commit/a3e494d93859235c30a0caa81ead36570bd7dc6b))
* mark superseded planner rounds as feedback ([d03d22f](https://github.com/sase-org/sase/commit/d03d22fd26118c8e74a0b907ff94d819f16a8c9d))
* **plugins:** lazy-import packaging in is_newer ([a2596a9](https://github.com/sase-org/sase/commit/a2596a973655c1612428aecb97749a93ceea2003))
* preserve soft SIGTERM for plan handoff ([4fe7faf](https://github.com/sase-org/sase/commit/4fe7faf649b4ba263379bb7c77928cf9c3d34b87))
* preserve workspace claims during handoff ([7a00e22](https://github.com/sase-org/sase/commit/7a00e22079cd2fd055ab7b0101ffb1019570d6f7))
* recognize prompt jinja runtime variables ([9eb77c1](https://github.com/sase-org/sase/commit/9eb77c1dd4683024e9dffb765989ad4dcaeba080))
* reconstruct approved follow-up statuses ([073c330](https://github.com/sase-org/sase/commit/073c330f510416fc704af5c8eb0c8e347343acb9))
* record VCS xprompt MRU for launch paths ([669ecfe](https://github.com/sase-org/sase/commit/669ecfee73629bc256859990a066f1adc34ee049))
* show top-level counts for saved agent groups ([3cbe90e](https://github.com/sase-org/sase/commit/3cbe90e500b94146dddbd7ff4e29ca3a521285f3))
* skip xprompt completion space before punctuation ([d1bc30f](https://github.com/sase-org/sase/commit/d1bc30f9c2eeb371dcfb3073775ef794826894b6))
* start dependency wait duration after deps are ready ([eaeff11](https://github.com/sase-org/sase/commit/eaeff119de8167dc7b7602a3106801c76e1eb63e))
* stop provider timer threads under load ([1a9c06b](https://github.com/sase-org/sase/commit/1a9c06b2caf2fab3d26df397921ac3eb9117218e))
* tolerate corrupt prompt history during directive persistence ([#186](https://github.com/sase-org/sase/issues/186)) ([0f0cb70](https://github.com/sase-org/sase/commit/0f0cb704c26c49a0d9ec3d4e023c6ff0166e7bd2))
* treat disabled xprompt regions as inert Jinja ([3b17ee3](https://github.com/sase-org/sase/commit/3b17ee3afb4204973cad51a6ba0bbf964a943c6c))
* **tui:** center confirmation dialogs ([06dd1f9](https://github.com/sase-org/sase/commit/06dd1f9ae3ee0eafa0b0b4abe2672ece3b5cf048))
* **tui:** complete agent names from all panels ([1506956](https://github.com/sase-org/sase/commit/1506956b2c33da4bd8e81e09e00a41fc8b26faf0))
* **tui:** complete fork args after colon ([2d007df](https://github.com/sase-org/sase/commit/2d007dfef6ac3399655f2c58f4a05fedb73d8c01))
* **tui:** complete fork args after earlier xprompt reference ([c318feb](https://github.com/sase-org/sase/commit/c318feb6499095c5278f1047be0dbe4d3374bc10))
* **tui:** don't reopen wait-agent completion on prose commas ([2479fbd](https://github.com/sase-org/sase/commit/2479fbd4bc7da580d12e06338388e93d6b2b6dd5))
* **tui:** guard completion panel teardown ([ae1c2d1](https://github.com/sase-org/sase/commit/ae1c2d1a64eec3d2570218ebb2b7f669f4b5a74f))
* **tui:** hide workflows from xprompt save targets ([63e8cbf](https://github.com/sase-org/sase/commit/63e8cbf6692c7786eeffa735f8696043c7cc6afb))
* **tui:** let agent onboarding use full tab ([4b89b1b](https://github.com/sase-org/sase/commit/4b89b1b17bad35d0fccebc239c19496c89011f5b))
* **tui:** only toast saved cancelled prompts ([60776ae](https://github.com/sase-org/sase/commit/60776ae601d7dc9b624298955e0810a9e460730a))
* **tui:** open xprompt argument menu after spacer colon ([aa7f615](https://github.com/sase-org/sase/commit/aa7f615ca43b936f5a657fd94c75898919f171af))
* **tui:** pad directive alt brace pairs ([36810c5](https://github.com/sase-org/sase/commit/36810c583ab61cfaa4fc887b541668802ca5a836))
* **tui:** render custom revival search first page without typing ([3f5b1ad](https://github.com/sase-org/sase/commit/3f5b1adf73b1698c268529ff76632829e393647d))
* **tui:** reserve numeric tab keys in the XPrompts filter ([d478de9](https://github.com/sase-org/sase/commit/d478de9bba29708ca9ac2d74efd6ecc0a559cfa9))
* **tui:** show auto-approve kind in agent metadata ([39be97a](https://github.com/sase-org/sase/commit/39be97a15ee5c58c46707f0ed4452b35ead5de35))
* **tui:** show project display names consistently ([91d6a4f](https://github.com/sase-org/sase/commit/91d6a4f18f3fbd37e6a3d524cced33b2752d1df1))
* **tui:** show project display names in agent rows ([b7e9829](https://github.com/sase-org/sase/commit/b7e982967a7e4a17e05d9159523e682761c9b681))
* **tui:** swap prompt stash restore keys ([6553db1](https://github.com/sase-org/sase/commit/6553db1d1e5a5bfeaaa27e57140244e2f6580adc))
* **tui:** use rich parseable agent status fallback ([092d37c](https://github.com/sase-org/sase/commit/092d37c365a80e653b5b0937fea0aa753e4ac19e))
* **tui:** wrap SASE CONTEXT reasons within 80 columns ([0db9fe9](https://github.com/sase-org/sase/commit/0db9fe9d33e00481f25b96f6a5fa05affeef6210))
* **uv_tool:** dedupe plugin rows in update surfaces ([5ab6374](https://github.com/sase-org/sase/commit/5ab6374a57897567b762cb14cc1b48baddc4a791))
* **uv_tool:** polish update/plugin output and add real-uv harness (sase-58.4) ([5d1a5bd](https://github.com/sase-org/sase/commit/5d1a5bd4152b65651e039e8d93cb47ae22ec7ced))
* **xprompt:** disambiguate leading-zero wait names ([bb04443](https://github.com/sase-org/sase/commit/bb0444316c01c8beae8365a4fb98be68e65091cf))
* **xprompt:** preserve config formatting on edits ([cfa6a8d](https://github.com/sase-org/sase/commit/cfa6a8d905fb4bf7cf86213975ab1ec2f139f312))
* **xprompt:** reserve Jinja globals statically ([12a6967](https://github.com/sase-org/sase/commit/12a6967ed547252758a83c632fe7a6a4ec0fdec5))
* **xprompt:** sort snippet insertions by trigger name ([a250134](https://github.com/sase-org/sase/commit/a250134d292104d772c11968afef2022ee3399dd))
* **xprompt:** use strip-chomped block scalars for config-saved entries ([4f23848](https://github.com/sase-org/sase/commit/4f2384867e67f2e1eb5664b734f2190a5c6838c8))


### Performance Improvements

* **ace:** page dismissed archive revive loads ([d4bef54](https://github.com/sase-org/sase/commit/d4bef5479d810854bae333fe642012aea3a2fe41))
* **tui:** async enrich agent detail headers ([abe91de](https://github.com/sase-org/sase/commit/abe91de7f22ed5773672b3e2eb94795de76a5b3a))
* **tui:** run xprompt commit push in background ([#187](https://github.com/sase-org/sase/issues/187)) ([0c5fbaa](https://github.com/sase-org/sase/commit/0c5fbaa65fbdeed0b489aa518b78f634f0be7ed1))
* **tui:** track marked-agent save persistence ([10f43ed](https://github.com/sase-org/sase/commit/10f43ed2a2e5048227ccab8f9153a303b60e9a4a))


### Documentation

* **ace:** drop retired projects leader key and close sase-5a ([4143811](https://github.com/sase-org/sase/commit/41438115571e5f65f46f6280a3a475b6c7e25eba))
* **ace:** sync help and docs to Projects tab (sase-5a.3) ([9e3de03](https://github.com/sase-org/sase/commit/9e3de039c7eafc6f13b42b0fb668c4e453be97ee))
* add admin center research infographic ([7c7f984](https://github.com/sase-org/sase/commit/7c7f984159fad1c5288815ffc5896b64a84014d3))
* add AMD memory init infographic ([0089626](https://github.com/sase-org/sase/commit/008962676a48224d9093f0cec644a5a5ac8f6584))
* add curl installer research infographic ([89f202f](https://github.com/sase-org/sase/commit/89f202feaeb6ba6b2536a8276fcb5086bc8d36f1))
* add development install infographic ([dc70b1d](https://github.com/sase-org/sase/commit/dc70b1d9d1573caa0e4ba2842fbd454439f2abc5))
* add epic bead work migration infographic ([b46d9e3](https://github.com/sase-org/sase/commit/b46d9e312db9f5f5d3fa2877bb2f20ade1ea53f5))
* add research on auto-loading snippets and xprompts in the TUI ([4ad86da](https://github.com/sase-org/sase/commit/4ad86da3344151a17d860d0329978d2b9c57e7d1))
* Add research on merging amd init into memory init ([5af9b38](https://github.com/sase-org/sase/commit/5af9b3810ecf5f378dbb47a770203cbef0f091dd))
* add research on parallel sase/sase-dev installs ([a939e51](https://github.com/sase-org/sase/commit/a939e51f1f7c1a0943403fe1d90417850dcadf12))
* add research on TUI + xprompt LSP shared-index freeze ([03a52fe](https://github.com/sase-org/sase/commit/03a52fe838468a0b067faf2a393251f54907c1fe))
* add sase update dev infographic ([920b89b](https://github.com/sase-org/sase/commit/920b89beb22b9e3b2bcaeb50e166a79a1f9edf80))
* add sase-dev install strategy infographic ([2460ac2](https://github.com/sase-org/sase/commit/2460ac2321dd424d401c0fa76b95affc27105fc5))
* add tiny field note ([2579d18](https://github.com/sase-org/sase/commit/2579d18c554507c1e79bd7bbea32287f1a0e0e2a))
* add TUI auto-loading research infographic ([0682924](https://github.com/sase-org/sase/commit/0682924ec831c80253075f74764732b05d6f0c7c))
* add TUI freeze research infographic ([01b5839](https://github.com/sase-org/sase/commit/01b5839248f85137568feed98a09db0a6d1b64ea))
* add TUI freeze research infographic ([c3a331c](https://github.com/sase-org/sase/commit/c3a331cb2c813444a141f26e515e3fa5931b22ab))
* add TUI slowdown infographic ([60b55cc](https://github.com/sase-org/sase/commit/60b55cc812cf5b7adf344da27488bdbbf9320df1))
* add TUI slowdown profiling research ([2f3c79a](https://github.com/sase-org/sase/commit/2f3c79a6c3fc698d4f7d2e97ce56fcdc576ae9b2))
* add TUI slowdown research on artifact-index broad loads ([bbb84c1](https://github.com/sase-org/sase/commit/bbb84c14173b5403fb149d87e8f4072ba06bf1b3))
* clarify ACE workflow references ([e72f2dc](https://github.com/sase-org/sase/commit/e72f2dc273473a2ffe5895f6661a2d2b0d890c46))
* clarify plan and prompt workflows ([6ad36d6](https://github.com/sase-org/sase/commit/6ad36d67ef1121ca1094d8cb7cbb36d570d1ee64))
* clarify refreshed user documentation ([a313b71](https://github.com/sase-org/sase/commit/a313b7174315bc71b93926e3180368518895a6b9))
* consolidate admin center tab migration research ([0702f7f](https://github.com/sase-org/sase/commit/0702f7f9215648abe84a75d3bfd55630a223a4b1))
* consolidate AMD memory init research ([d839b5b](https://github.com/sase-org/sase/commit/d839b5b9f3721ff0fd3a362f2876dd29df89bcaa))
* consolidate curl installer research ([65923e2](https://github.com/sase-org/sase/commit/65923e2bd5f6833dfa0ecf820ad313e11cf9234c))
* consolidate development install research ([fb5c558](https://github.com/sase-org/sase/commit/fb5c558e636d259cfdc8c7d16be2ac30052317da))
* consolidate epic bead work PR migration research ([0bfd0c8](https://github.com/sase-org/sase/commit/0bfd0c84ee98045cea5b1647c11869c0cc5fa1a2))
* consolidate sase dev update research ([a323d33](https://github.com/sase-org/sase/commit/a323d33fa42dada649e9f8d4b041ef692ddd396b))
* consolidate sase-dev install research ([70d34ce](https://github.com/sase-org/sase/commit/70d34cea6a495231664379083f89462c98a03621))
* consolidate TUI prompt auto-loading research ([343691c](https://github.com/sase-org/sase/commit/343691cd877c6dbc8c4ea2613af53a5d3a287229))
* consolidate TUI slowdown research ([444ed94](https://github.com/sase-org/sase/commit/444ed94753c222cf78a0a9c2fc7dd85af1870ecc))
* consolidate TUI startup freeze research ([e072a65](https://github.com/sase-org/sase/commit/e072a659bcc85da321227b28923b805f4ec3d75e))
* consolidate TUI/xprompt-LSP freeze research ([9394ef7](https://github.com/sase-org/sase/commit/9394ef71b8bb0453b185273a1ad3688e2ed38c33))
* correct ACE quit-menu and Admin Center reopen details ([546c3d2](https://github.com/sase-org/sase/commit/546c3d2ab1b962b645cb566833bdd05120c70db8))
* correct Admin Center tabs and refresh feature docs ([450644b](https://github.com/sase-org/sase/commit/450644be7bbfca8ac334b713bde41b526c122ea1))
* document TUI freeze and xprompt LSP findings ([f53674e](https://github.com/sase-org/sase/commit/f53674e04683382a9177808c659ac5800cbb0534))
* **memory:** Give the generated_skills.md file a better description. ([d639bc1](https://github.com/sase-org/sase/commit/d639bc1bafcf659cdc99e8529bf62e2cdb2cecde))
* **plugins:** polish `sase plugin` help text and document catalog commands (sase-57.4) ([2c7ec47](https://github.com/sase-org/sase/commit/2c7ec4718b178047d505eb839bf7817adefc39ee))
* refresh SASE user documentation ([f7fdd66](https://github.com/sase-org/sase/commit/f7fdd66e99b99778944891b4628ef299fd16a94d))
* research admin center tab migration candidates ([cfdaf30](https://github.com/sase-org/sase/commit/cfdaf304ddc66403637c8793c1c6ce3f2d91b7e3))
* research AMD init and memory init consolidation ([bb49553](https://github.com/sase-org/sase/commit/bb495538abb4ee2df7672f3043b0384df778e12a))
* research development runtime install strategy ([fbb4c78](https://github.com/sase-org/sase/commit/fbb4c781ab8c31404c425ff68c94d46edd712aa3))
* research epic bead work PR migration ([674fcea](https://github.com/sase-org/sase/commit/674fcead430501499cab773872cc3531e232ecc2))
* research sase-dev parallel installs ([ac18bd7](https://github.com/sase-org/sase/commit/ac18bd7fabd444f330504f01d83f54504c5ea586))
* research sase-dev update option ([152f4c3](https://github.com/sase-org/sase/commit/152f4c3c98fce27fdedabf7cb0dd2b775eeb2d68))
* research TUI external editor freeze ([0434175](https://github.com/sase-org/sase/commit/0434175ef47a309cef5af0d15fc7d05e897ab407))
* research TUI prompt catalog auto reload ([8d023ac](https://github.com/sase-org/sase/commit/8d023ac1e31a78e026fff6e349f8f0b2c2e2ec36))
* research TUI startup freeze from editor suspend ([d35c306](https://github.com/sase-org/sase/commit/d35c306dd2cdc8406743baaeabee229a9a223cc8))
* **research:** add uniform dev install environment research ([3a770cd](https://github.com/sase-org/sase/commit/3a770cd9374a57ba371cebe5ade8bf92a03d6908))
* **research:** analyze one-PR-per-epic bead work migration ([83e60b1](https://github.com/sase-org/sase/commit/83e60b19b795df27fd7c54ee12900055d6570022))
* **research:** critique sase update --dev install plan ([398d0c0](https://github.com/sase-org/sase/commit/398d0c0e3338784a36e8845973a2b9805bd18759))
* **research:** evaluate curl install.sh bootstrap script ([88c3d68](https://github.com/sase-org/sase/commit/88c3d68c6a7f1804e424d9dc83a3a81bd6517ffc))
* **research:** expand curl installer recommendation ([ab23e17](https://github.com/sase-org/sase/commit/ab23e17247917ed12fbd478b2c96ba46b917e9f9))
* **research:** survey admin center tab migration candidates ([77c2177](https://github.com/sase-org/sase/commit/77c2177e9e2d795faf3acce3b7638cc06efca698))
* update CLI and ACE references ([53dd55b](https://github.com/sase-org/sase/commit/53dd55b89fffa73e583be53c302fe4983b775665))
* update SASE user documentation ([1628f68](https://github.com/sase-org/sase/commit/1628f6808c6173299e90465b37817316f23197eb))

## [0.5.0](https://github.com/sase-org/sase/compare/v0.4.0...v0.5.0) (2026-06-24)


### ⚠ BREAKING CHANGES

* Ctrl+S no longer submits the whole prompt stack, and gS is no longer a prompt binding. Use the submit chooser for whole-stack submission and gs / Ctrl+G s to stash all panes.
* **directives:** the `%t` directive alias now resolves to `tale` rather than `time`; use the `%time` long form instead. `%approve`/`%a` are deprecated (still resolve to `plan`) and no longer advertised in completion.
* %m(opus,sonnet) and repeated top-level %model directives no longer fan out. Use %{%m:opus | %m:sonnet} instead.
* **tui:** gp, gP, and Ctrl+G P no longer open the prompt stash. Use @ or Ctrl+G p instead.
* **ace:** the default key to open the ACE custom-agent selector is now `+` instead of `@`. Users who rely on the default must press `+`; existing explicit `start_custom_agent: "at"` overrides continue to work.
* ACE no longer auto-inserts or paired-deletes the closing brace for `%{}` alt shorthand. Use editor brace-pairing behavior or type the closing brace manually.
* **workspace:** `sase workspace open` now requires `-r/--reason`; invocations without it exit with usage error code 2.
* **llm:** The Gemini CLI provider has been removed. Use the Antigravity (agy) provider instead. The sase.gemini_wrapper module and its GeminiCommandWrapper/invoke_agent shim are gone; import from sase.file_references.
* VCS project completion now uses `#+` and `#+query` instead of `+` and `+query`.
* **skills:** The `/sase_plan_search` skill is no longer generated, listed, or installed. Use the `sase plan search` CLI command directly.
* **cli:** sase git init is no longer a public CLI command. Use #git:<project> for first-use bare-git initialization or #git:<bare-repo-path> to register an existing bare repository.

### Features

* **ace:** add %{...} alt-shorthand prompt editing behavior (sase-52.3) ([2e5d157](https://github.com/sase-org/sase/commit/2e5d1578bc4b4b154507414687354c059784c477))
* **ace:** add Auto-Approve menu modal and rewire approve keymap (sase-56.2) ([b44dda1](https://github.com/sase-org/sase/commit/b44dda18dec4b6e07b577c73ba9b8aab0b53f1be))
* **ace:** add blank-line normal-mode keymaps ([3acbe8a](https://github.com/sase-org/sase/commit/3acbe8ae1e71c1cf1ce54c223bb5c07ade99ab1e))
* **ace:** add global @ keymap to restore stashed prompts ([53db425](https://github.com/sase-org/sase/commit/53db42597fdbd014d6967eaf62dfb908274933d6))
* **ace:** append space after end-of-line xprompt double-colon skeleton ([d3eeb4d](https://github.com/sase-org/sase/commit/d3eeb4d7c1594251a9932a3f9d7533af47c9bc4e))
* **ace:** auto-open completion menu for directives and xprompt skills ([27258f1](https://github.com/sase-org/sase/commit/27258f105b87e5f70fc59ab5bc712ab857e23eac))
* **ace:** auto-open xprompt completion menu ([133c2ae](https://github.com/sase-org/sase/commit/133c2ae5841d16b7d5e98c63e118f1e8c158cf34))
* **ace:** auto-pair angle brackets in prompt input ([63e5292](https://github.com/sase-org/sase/commit/63e5292c8ffaec3526f3a65f0d681fa48930cc71))
* **ace:** change custom-agent launcher keymap from @ to + ([6a8a9ee](https://github.com/sase-org/sase/commit/6a8a9ee85079653179b0d7d1a1db5c207b2bf3d2))
* **ace:** delete saved groups from restore panel ([4a47da3](https://github.com/sase-org/sase/commit/4a47da3358291c0f9f9f0b114679a6a6a77b7a36))
* **ace:** inline expand xprompts with inputs ([620ccda](https://github.com/sase-org/sase/commit/620ccda1c20a256070eac1f53c411514a214598d))
* **ace:** mark collapsed agent groups ([9a86edf](https://github.com/sase-org/sase/commit/9a86edf1875ea0ed734cce2d114366baf5c69b4b))
* **ace:** persist and display reasoning effort uniformly (sase-55.4) ([d6b9ebe](https://github.com/sase-org/sase/commit/d6b9ebe1bf1e3f7bdc742783a8eb281feb7136bd))
* **ace:** polish auto-approve presentation in agent list, footer, and help (sase-56.3) ([52cbe00](https://github.com/sase-org/sase/commit/52cbe00d54ed8892c4a83a8ff5a29a6344de85ec))
* **ace:** rewrite optional xprompt spacer to colon on next ":" ([8244755](https://github.com/sase-org/sase/commit/82447552f14c76c2f402f899d6d1f2036996758d))
* **ace:** show bead glyph and metadata only for confirmed beads ([a4aff73](https://github.com/sase-org/sase/commit/a4aff7337a142637a7069277de6aeed2e7211d0f))
* **ace:** show running tasks before quitting ([f472f51](https://github.com/sase-org/sase/commit/f472f51ce0b2bf5933963b1992d84c62b96ee2ae))
* **ace:** support vim number increment commands ([9e19bdb](https://github.com/sase-org/sase/commit/9e19bdb286296530d46d51563eb4942a6b9aded1))
* **agy:** extract trajectory tool calls ([6c661bb](https://github.com/sase-org/sase/commit/6c661bbdbae36b100fed2fa4cfe6bb57a4093f4e))
* **amd:** commit AMD-managed changes during init by default ([8aa4017](https://github.com/sase-org/sase/commit/8aa401739292cc569e9cb211d97b4f755dba3230))
* **cli:** notify when delegating bare command group to list ([0e6217b](https://github.com/sase-org/sase/commit/0e6217b5ee5c3cee2e3660d955215066f7189caa))
* **cli:** remove sase git init ([70651ab](https://github.com/sase-org/sase/commit/70651abeb701f0cbf1817ca4cfc86463e24270e5))
* **config:** add edit, validate, and write to Config Center (sase-54.5) ([710d8a1](https://github.com/sase-org/sase/commit/710d8a104be5682db846288b98e89fe2787cc497))
* **config:** add Python config backend and write execution (sase-54.2) ([618c275](https://github.com/sase-org/sase/commit/618c27537c6624c12571556f3a8bb60ef09e13ca))
* **config:** add read-only config browser to Config Center (sase-54.4) ([8792e87](https://github.com/sase-org/sase/commit/8792e87dc538b81ec9c23159965fec7e5f12e792))
* **config:** surface linked_repos as the public configured-repo key (sase-51.3) ([b0f316a](https://github.com/sase-org/sase/commit/b0f316ab71ef2d7371c22d92f406755fd7169a0d))
* **config:** warn on deprecated sibling_repos key (sase-51.4) ([d5f3fca](https://github.com/sase-org/sase/commit/d5f3fca9269bf7cbb9bb3e08826bcccc513ac439))
* **directives:** add %tale directive and repurpose %plan for plan auto-approval (sase-56.1) ([4b22421](https://github.com/sase-org/sase/commit/4b224219c1e52b68e163409b91f7b2c16b870361))
* **fork:** make `#fork:<name>` imply `%w:<name>` ([e64a9eb](https://github.com/sase-org/sase/commit/e64a9ebf1ce354e1cd039a61239e38f547ac123f))
* **init_memory:** generate /sase_plan warning in project memory ([01f3c3b](https://github.com/sase-org/sase/commit/01f3c3b55f3f92a52a4c6083a80f7617779ed1da))
* **init:** repair AGENTS.md via onboarding title fallback ([8062e6f](https://github.com/sase-org/sase/commit/8062e6f1c71ab74344ad2f1f56dd74a94292ff47))
* **launch:** preserve submitted prompt when an agent launch fails ([1ffc49b](https://github.com/sase-org/sase/commit/1ffc49b0f93b57598b3f8482d5af16ab69408b6d))
* **linked_repos:** add canonical linked_repos module with sibling_repos compat (sase-51.1) ([81ef778](https://github.com/sase-org/sase/commit/81ef778a1aba18535e8244dc6cfe091ae6efb190))
* **llm_provider:** add default_effort config field (sase-55.2) ([88bc7f1](https://github.com/sase-org/sase/commit/88bc7f1266df53f98078c5322b7895491ba0a67c))
* **llm_provider:** translate reasoning effort into per-run CLI args (sase-55.3) ([7535d98](https://github.com/sase-org/sase/commit/7535d98b718faaa5489e7ea7bc447e210b3edff1))
* **llm:** add core Antigravity (agy) provider (MVP) (sase-50.2) ([86c8614](https://github.com/sase-org/sase/commit/86c8614726acac65409a55ff39d7b43869294328))
* **llm:** integrate agy provider into registry, doctor, config, and TUI (sase-50.3) ([2428355](https://github.com/sase-org/sase/commit/2428355bebd5095829885b8d32f32b848e46a1c3))
* **llm:** remove Gemini CLI provider in favor of agy (sase-50.6) ([6a623cd](https://github.com/sase-org/sase/commit/6a623cd7a2a277993a9787bf744804a2e6152cef))
* **llm:** support agy provider in skill init (sase-50.4) ([7931c7e](https://github.com/sase-org/sase/commit/7931c7e57f44c45c2db3092ab4409408b7079ec0))
* **logs:** record project creation diagnostics ([63f69be](https://github.com/sase-org/sase/commit/63f69beaf7709a1c5c69fe55ebbb7735a2a02913))
* **plan-search:** add `sase plan search` CLI with JSON output (sase-4x.4) ([668b090](https://github.com/sase-org/sase/commit/668b090f051350835d1c92461e71d09cade64125))
* **plan-search:** add compact/full/markdown rendering + color (sase-4x.5) ([b733512](https://github.com/sase-org/sase/commit/b733512740d2fb35099bf82ea241205340e2c0f2))
* **plan-search:** add generated skill, docs, and e2e tests (sase-4x.6) ([21c14d7](https://github.com/sase-org/sase/commit/21c14d74b2c775a773143135e5d9b5731b91a933))
* **plan-search:** add Python facade for plan search (sase-4x.3) ([3ac4746](https://github.com/sase-org/sase/commit/3ac47468abc82728b563511d9160fb014ed4de19))
* **prompt-history:** shard prompt history storage ([f23698c](https://github.com/sase-org/sase/commit/f23698c872209b12731334e1f741c823ba290ac0))
* **prompt-search:** surface local .sase/sdd snapshots in SDD search (sase-4y) ([552cba5](https://github.com/sase-org/sase/commit/552cba5bbd4628d7789e61ce355c27b787e34acd))
* **prompt:** add json + full search renderers (sase-4y.4) ([e189234](https://github.com/sase-org/sase/commit/e1892344db5e0ca78daf58c3d22f5c6191b58766))
* **prompt:** add prompt search CLI surface (Phase 3) (sase-4y.3) ([0b762df](https://github.com/sase-org/sase/commit/0b762dfc25ae1575edd606fa214906091a80fe7d))
* **prompt:** add prompt search engine (Phase 2) (sase-4y.2) ([6056b94](https://github.com/sase-org/sase/commit/6056b94ad3b274bfa88b6fbdf930b9bd810d97ca))
* **prompt:** add unified prompt search data layer (Phase 1) (sase-4y.1) ([30faa26](https://github.com/sase-org/sase/commit/30faa263b09db638d8feb6de1d15333df3ab5786))
* rebind prompt stash shortcuts ([b81437a](https://github.com/sase-org/sase/commit/b81437a8b4198f2197e1889ebd43e267319dea16))
* reject legacy multi-model directives ([231792b](https://github.com/sase-org/sase/commit/231792b322bf5bcc3ac0c63571a452d3893c5e4b))
* require #+ for VCS project completions ([909b2cd](https://github.com/sase-org/sase/commit/909b2cd9c8904e032ce65613c13111c0177a5ab6))
* **skills:** remove unintended sase_plan_search skill ([5c5fe42](https://github.com/sase-org/sase/commit/5c5fe42a8b4281b5fbabaa986ff1d9d8b38d2f0c))
* stop auto-pairing alt braces in ACE ([131a669](https://github.com/sase-org/sase/commit/131a6699887a18663f437ba1be3db59743893198))
* support directive value fanout ([6d26305](https://github.com/sase-org/sase/commit/6d263059944d092943b17224dff6a14419104f8a))
* support snippet reference syntax ([4dc06e9](https://github.com/sase-org/sase/commit/4dc06e92d9795577b061c287af940b6147d51c64))
* **tui:** add apostrophe jump hints to Agent Restore modal ([cb85e8e](https://github.com/sase-org/sase/commit/cb85e8e52cecf706a3a2c57d2ac1927cb55f5a52))
* **tui:** add Config Center modal and migrate XPrompt Browser (sase-54.3) ([9a32303](https://github.com/sase-org/sase/commit/9a32303963d0b5052395e2cac0fe3942d07d6028))
* **tui:** add Ctrl+I expand action to xprompt select modal (sase-53.3) ([f8b80df](https://github.com/sase-org/sase/commit/f8b80df762ef9192c0a003dda0e098999bcdec8e))
* **tui:** add g/G top-bottom scrolling to ACE Logs panel ([de38910](https://github.com/sase-org/sase/commit/de389106dfc2b89519b96431532a39b474785b22))
* **tui:** add Jinja variable paired deletion ([9720160](https://github.com/sase-org/sase/commit/9720160f43fc2e81e618532832e4305940779b0d))
* **tui:** add safe inline xprompt expansion helper (sase-53.2) ([3c9d6cf](https://github.com/sase-org/sase/commit/3c9d6cff939490f79c6c8f10d96ad15c06d29b37))
* **tui:** add tmux workspace chooser for agents with opened workspaces ([fb422ed](https://github.com/sase-org/sase/commit/fb422edde684fb6852378f8aa61a5bdc9bd0b6f5))
* **tui:** apply xprompt expansion to prompt text with undo (sase-53.4) ([5def141](https://github.com/sase-org/sase/commit/5def141cc2539bba4ab348c13d8807a6dcb7a09c))
* **tui:** color vim prompt cursor by mode ([2ab68db](https://github.com/sase-org/sase/commit/2ab68dbb54957e2c110436da97cf5665fcae0376))
* **tui:** delete VCS xprompt tag on prompt-local Ctrl+N ([39e6290](https://github.com/sase-org/sase/commit/39e62902e0dd68d41b26fbe906c8ce0cc1aaec24))
* **tui:** enable Ctrl+G prompt prefix in NORMAL mode ([be9b975](https://github.com/sase-org/sase/commit/be9b97517af00fda312efe6aa79b96e2ad0f3a0b))
* **tui:** escalate startup stopwatch colors ([ec8c494](https://github.com/sase-org/sase/commit/ec8c49412ee66f455c2f55dfcbb605f5d61529c5))
* **tui:** exclude default VCS xprompt from prompt cycling ([c2b53bc](https://github.com/sase-org/sase/commit/c2b53bc35bd592360159f543a676f1959b45a987))
* **tui:** expand local xprompts in #@ selector with parity (sase-53.5) ([60c504a](https://github.com/sase-org/sase/commit/60c504a678e741157ae9b22c63601c52d563b88b))
* **tui:** generalize prompt input auto-pairing ([b0e668f](https://github.com/sase-org/sase/commit/b0e668f7cc998dcf9be81a6e5a91a31566189e26))
* **tui:** highlight %{...} alt shorthand in ACE prompt input (sase-52.4) ([57e9fd6](https://github.com/sase-org/sase/commit/57e9fd6f35f9ef2f197d65ffe97a6dd422b426df))
* **tui:** indicate reverted agents ([c949acf](https://github.com/sase-org/sase/commit/c949acf56bbc8d225c5020c6538f2cf53042707c))
* **tui:** polish agent restore panel rows ([6458af0](https://github.com/sase-org/sase/commit/6458af0ab3cb22321ee8ba2b980a23bc6d5f2e11))
* **tui:** show agent commit messages ([1f8c86d](https://github.com/sase-org/sase/commit/1f8c86dcea01018f181425112d7c7433a67da448))
* **tui:** show linked repo deltas for agents ([a47a4ca](https://github.com/sase-org/sase/commit/a47a4ca5cb9869a651fe97d098d4fe0719bfe20b))
* **tui:** show linked repo diffs in file panel ([e471144](https://github.com/sase-org/sase/commit/e471144b5f5d2655806dcb5950eade89a96f939e))
* **tui:** show opened workspaces in SASE context ([039877a](https://github.com/sase-org/sase/commit/039877a444f3857edde032bc532e414226f60034))
* **tui:** split VCS prompt deletion from MRU cycling ([6dd7586](https://github.com/sase-org/sase/commit/6dd7586f39cb554f23ef66ca2b9350f0d08bb4f3))
* **tui:** target originating pane for #@ snippet selector (sase-53.1) ([93f9dbf](https://github.com/sase-org/sase/commit/93f9dbfd03b3c6b75d261852e065b80c959220d9))
* **tui:** unify prompt stash panel ([727c08d](https://github.com/sase-org/sase/commit/727c08d55e578fba6a0fd293f98c3ac0db778c63))
* **workspace:** require -r/--reason for `sase workspace open` ([7239f02](https://github.com/sase-org/sase/commit/7239f028e0b1a0c0f6c20b8bc746bdf8aa4211a7))
* **xprompt:** add `+` project completion menu in the TUI prompt (sase-4z.2) ([ddff98d](https://github.com/sase-org/sase/commit/ddff98d70bd792db3529238bc228451d56481c67))
* **xprompt:** add headless project catalog + expansion helpers for `+` VCS completion (sase-4z.1) ([1039d73](https://github.com/sase-org/sase/commit/1039d73ed2218fdd80116ea7b1559a72c4a2a1be))
* **xprompt:** include PRs in VCS completion ([8034d33](https://github.com/sase-org/sase/commit/8034d33578674992ba988a4e1df4d155aa99aeb6))
* **xprompt:** materialize VCS project catalog for the xprompt LSP (sase-4z.4) ([1524b96](https://github.com/sase-org/sase/commit/1524b964fbf4dda8195c5cbdf3176eafc9779180))
* **xprompt:** open VCS project completion on bare `+` at prompt start ([ba69732](https://github.com/sase-org/sase/commit/ba6973285639f419f1976285bf8f6490dff7c804))
* **xprompt:** parse reasoning-effort levels in directives (sase-55.1) ([9b5a715](https://github.com/sase-org/sase/commit/9b5a715f21995ffdd6b455aaa6e59756a5eafb0c))
* **xprompt:** wire %{...} brace alt shorthand through Python fan-out (sase-52.2) ([2cb2239](https://github.com/sase-org/sase/commit/2cb2239e4018902d9b4c5ba2921f011ccec2c371))


### Bug Fixes

* **ace:** attribute linked commits by persisted cwd ([d9da0e5](https://github.com/sase-org/sase/commit/d9da0e56ac32f88c5b0b8ad45c6fc08336554b7d))
* **ace:** complete prompt vim dot repeat ([8233079](https://github.com/sase-org/sase/commit/82330792f3fb9f93b3dc7c7c17cfc42cdc71995f))
* **ace:** couple xprompt inline-expansion staged inputs to body undo/redo ([9d0c55c](https://github.com/sase-org/sase/commit/9d0c55cda44c2c73a62cfba41947a4640bbf4121))
* **ace:** exclude #git:home from Ctrl+Space replay history ([840e697](https://github.com/sase-org/sase/commit/840e69794825f2c1caad3777521e105a8cdf343d))
* **ace:** make prompt history load-more use Ctrl-D ([e5bd4b7](https://github.com/sase-org/sase/commit/e5bd4b7d8aa858213a8f6f434ae7c037abe7a1df))
* **ace:** preserve approved question continuation planners ([55352d6](https://github.com/sase-org/sase/commit/55352d61c17878971626285b43c2a4f053780e23))
* **ace:** rebuild Agents list when cycling back to project grouping ([c63271e](https://github.com/sase-org/sase/commit/c63271e9485734aa80aa42d17e62c88354a04541))
* **ace:** render file-change glyph before runtime suffix ([825c70b](https://github.com/sase-org/sase/commit/825c70b8a8edb7ae0cf9f46cff88e45e0aa1ad0c))
* **ace:** render seeded zoom file panels ([0a45157](https://github.com/sase-org/sase/commit/0a45157381f84336fa2cc570e802614b645356d5))
* **ace:** restore bidirectional Ctrl+N VCS MRU cycling ([1dd07e9](https://github.com/sase-org/sase/commit/1dd07e9fe4f259bb7fbae2966b2270a0df9377e3))
* **agent-scan:** rebuild stale linked repo index rows ([a152741](https://github.com/sase-org/sase/commit/a1527417768cf5a51bf4099e6e1e3c0c7294e1e7))
* **agents:** restore reasoning-effort metadata in agent panels ([937a5c4](https://github.com/sase-org/sase/commit/937a5c492b205d169360336d4e1c73b169f865fa))
* **agy:** ignore stale workspace pins ([86a71ec](https://github.com/sase-org/sase/commit/86a71ecda860f43a344a15d26be29d7ce5277fb4))
* **agy:** recover from no-progress print replies ([1eb26d3](https://github.com/sase-org/sase/commit/1eb26d367668d3c32f7d53acb2f03d166a3e8e37))
* avoid replaying old agy tool calls ([#182](https://github.com/sase-org/sase/issues/182)) ([7aa16e8](https://github.com/sase-org/sase/commit/7aa16e85f1d90627504c6cb49f43ddffa07f62e4))
* **bead:** show matching compact search snippets ([#181](https://github.com/sase-org/sase/issues/181)) ([130a1ed](https://github.com/sase-org/sase/commit/130a1edd5be96a98618fa789a87857fc54823d7d))
* clear tag modal input for tagged agents ([c280737](https://github.com/sase-org/sase/commit/c2807378840d353a7c158a616d6ce8a2d5145354))
* **config:** reject path-like overlay names ([#184](https://github.com/sase-org/sase/issues/184)) ([0466184](https://github.com/sase-org/sase/commit/04661847ddd2d0fa318db9896ca9d65ad60e3569))
* defer workspace allocation for fork references ([8e5fdfa](https://github.com/sase-org/sase/commit/8e5fdfaf6cdb512df3c451ede63b69d20257c57e))
* detect brace alt directives after openers ([0c91326](https://github.com/sase-org/sase/commit/0c91326a530e985bbaf975a70cf024c3789a6ded))
* disable sase_plan skill-use logging ([e3b1475](https://github.com/sase-org/sase/commit/e3b1475678c2999a57229c20dbed33e3faeec308))
* finalize recorded sibling workspaces ([7d9f003](https://github.com/sase-org/sase/commit/7d9f0036f42f372db1af53d0832587ce22cc8f0d))
* gate finalizer sibling checks by opened workspaces ([db79196](https://github.com/sase-org/sase/commit/db79196c85a1cb339956d58b663fbab3783901c6))
* ignore embedded prompts in disabled regions ([86f89d4](https://github.com/sase-org/sase/commit/86f89d40fe060d3d809f25b3024e2ab1e36323d1))
* **llm:** guard oversized agy prompts ([214c1c5](https://github.com/sase-org/sase/commit/214c1c592f67c21d0063d411351a17cb437f3441))
* persist follow-up reasoning effort ([06bfa10](https://github.com/sase-org/sase/commit/06bfa1070a65b4fa8f8b63e52d95117f3dbbd796))
* preserve blank lines in VCS project completions ([950e621](https://github.com/sase-org/sase/commit/950e6212c9eb869933013951792e00d574ec38f2))
* preserve disabled regions during early Jinja render ([3be2894](https://github.com/sase-org/sase/commit/3be2894bd0cdcf935c6b60fd63b8cc99089f9a8f))
* prevent duplicate hint input bars ([5ea9cc1](https://github.com/sase-org/sase/commit/5ea9cc128b52a176efafd8e8763b3e79f351f21a))
* **project-aliases:** canonicalize alias project state paths ([1abeee4](https://github.com/sase-org/sase/commit/1abeee4164281536b5e6dd151b5351e3b5181153))
* restore ACE prompt alt brace pairing ([397f201](https://github.com/sase-org/sase/commit/397f201e00073babf581ed811503f76db0bd4e08))
* serialize linked repo bundle metadata ([4097b43](https://github.com/sase-org/sase/commit/4097b4338162aa725b8dd11b0a56e9597ba697fa))
* skip nested repos in pyscripts lint ([92cbdd1](https://github.com/sase-org/sase/commit/92cbdd150acff2a0c52513bb6a7a464d52c588a0))
* skip waits for resolved dependencies ([7debc17](https://github.com/sase-org/sase/commit/7debc17587be50a51cd0cb906096fea31583b892))
* **tui:** add freeze telemetry watchdog ([37631ae](https://github.com/sase-org/sase/commit/37631ae8f2412b333dd6112d0b048d31ce937f2d))
* **tui:** clamp prompt completion height reservation ([23a3a5e](https://github.com/sase-org/sase/commit/23a3a5e87057b5fe24a856baae81dcdbb4ef2e95))
* **tui:** clear persisted agent meta tags on unset ([4d60ba2](https://github.com/sase-org/sase/commit/4d60ba2260c48a56b34ec3c5ea196aa2372a2b0d))
* **tui:** correct question continuation planner runtime ([19e55af](https://github.com/sase-org/sase/commit/19e55af2b40bb7d2ba47f6c661f4693da7a5cc60))
* **tui:** distinguish working plan handoff rows ([8d9e359](https://github.com/sase-org/sase/commit/8d9e35978622db689678804692b7bf53a9c5078f))
* **tui:** freeze approved plan runtimes ([80fcc2b](https://github.com/sase-org/sase/commit/80fcc2ba6df06701d32183974d3ff8e982b8ca0e))
* **tui:** handle doubled same-character surround delimiters ([9b464da](https://github.com/sase-org/sase/commit/9b464da0b4e82b1ae57ad910ed54cef40b31df68))
* **tui:** keep `/` and `?` as literal char targets in prompt NORMAL mode ([838bf81](https://github.com/sase-org/sase/commit/838bf81ed1051cb0e67ba68341a51e0b2bca01c9))
* **tui:** mark answered question families done ([78a7f14](https://github.com/sase-org/sase/commit/78a7f14ee6eaff8d19e4e6dc51615a93240133eb))
* **tui:** preserve working status invariants ([9de865b](https://github.com/sase-org/sase/commit/9de865bf4eec23383ef242c552f969e6aef1eee5))
* **tui:** reveal zoom file panel from collapsed state ([a6bfd13](https://github.com/sase-org/sase/commit/a6bfd1322521e094e5d307802ee5bf4e37b7879b))
* **vcs:** archive branch safely from a checked-out worktree ([988bd32](https://github.com/sase-org/sase/commit/988bd32f17d32092c7369c450159f4a41216e669))
* **xprompt:** keep virtual catalog sources global ([8ed5ba9](https://github.com/sase-org/sase/commit/8ed5ba9278555d7e43dd4e05e1cecb7d2dc8d09d))
* **xprompt:** preserve alt axes in model fanout names ([e377aae](https://github.com/sase-org/sase/commit/e377aae2b7ee0f382f450f2fc678189cb2494ac3))
* **xprompt:** replace VCS tag at EOF during `#+` completion ([1c0269b](https://github.com/sase-org/sase/commit/1c0269b65047f0cbf68a69cea3efcfdee50792dd))


### Performance Improvements

* **tui:** avoid broad reloads after artifact cleanup ([f04bea6](https://github.com/sase-org/sase/commit/f04bea6d77e1a749b5a5cbeda157c92eb4ed3d40))
* **tui:** defer artifact index maintenance off the event loop ([4998611](https://github.com/sase-org/sase/commit/49986114d251c67b51e3774bdf4e330f466b9aae))


### Documentation

* **ace:** update auto-approve docs for the Auto-Approve menu (sase-56) ([d605ae5](https://github.com/sase-org/sase/commit/d605ae5119e31d0055a0dd8d823bd97fc177ccc0))
* add ACE demo video infographic ([3933e7f](https://github.com/sase-org/sase/commit/3933e7f732d4263bbfec9c4096f85a83b5d7b3fa))
* add ACE demo-video tooling research ([d6172a0](https://github.com/sase-org/sase/commit/d6172a0e204c980a776c87576841cae9ca565a5f))
* add agent QoL research infographic ([6f273cc](https://github.com/sase-org/sase/commit/6f273ccfefd9cc6e248503286f3e50155401dfe1))
* add agy migration infographic ([c41320c](https://github.com/sase-org/sase/commit/c41320c9563cd13481b0a38e3200fd91223e11ac))
* add agy tools panel infographic ([7e275ea](https://github.com/sase-org/sase/commit/7e275ea0ee95f930c75f2f3c256a3cb6bc235a9a))
* add bead work latency infographic ([7608303](https://github.com/sase-org/sase/commit/76083037828319e246a8ef4d318740ac5ae4f826))
* add config TUI research infographic ([027565e](https://github.com/sase-org/sase/commit/027565e95ee9a3ff133865ea4338159c67482721))
* add coral naming infographic ([1a0b181](https://github.com/sase-org/sase/commit/1a0b181e2a8ecaff2cce50365433ae9d23697c53))
* add coral subcommand naming research ([52af3b1](https://github.com/sase-org/sase/commit/52af3b1a64afd73b3e3e31e354521919701d86ee))
* add coral subcommand naming research ([665f846](https://github.com/sase-org/sase/commit/665f846449d914167a3c0f6dc42af390e14c877a))
* add directives xprompts infographic ([18c103c](https://github.com/sase-org/sase/commit/18c103ca3594d66d0455e56c8fc5031e6e7d48b6))
* add Gemini Antigravity infographic ([9f53821](https://github.com/sase-org/sase/commit/9f538217466bf7cfee5922ecdf11db8dbe765d9b))
* add Hacker News timing research ([1dd3ffc](https://github.com/sase-org/sase/commit/1dd3ffc69ccdb190a53512569f02d2648129fb15))
* add HN timing infographic ([d77054c](https://github.com/sase-org/sase/commit/d77054cbd9bceda595014e05160441b02fe7c415))
* add license research infographic ([701bf6d](https://github.com/sase-org/sase/commit/701bf6d926d48c27a74ac63716d6027811f858d2))
* Add project rename naming research ([2523003](https://github.com/sase-org/sase/commit/252300300d54f5827199e7199aaf05ec10241965))
* Add research on directives vs xprompts merge architecture ([bf6e8ec](https://github.com/sase-org/sase/commit/bf6e8eca978fa45ccadbfa22c041fcff69ee21bd))
* add research on Gemini CLI deprecation and Antigravity migration ([2909601](https://github.com/sase-org/sase/commit/2909601e80a0fb7af0827728f779eed4be87563d))
* Add research on Gemini CLI to Antigravity migration ([fd9e163](https://github.com/sase-org/sase/commit/fd9e16338a77b22ad9272913d88eb6e81a3f674d))
* Add research on tools panel support for anti-gravity provider ([ff7ed06](https://github.com/sase-org/sase/commit/ff7ed06066c32d0e90abfc0667543c5da7c3f5bd))
* add SASE ACE CLI demo video research ([bae5e26](https://github.com/sase-org/sase/commit/bae5e263576917e2c0c3a4ea2332565cf368d19d))
* add SASE recent chat pattern research ([0cba285](https://github.com/sase-org/sase/commit/0cba2851e8f8551699beaa84a9d49850fe91b22a))
* add SASE rename research ([f6159ce](https://github.com/sase-org/sase/commit/f6159cea5c8d9fcdef16ba6ef799ff39078e65be))
* add SASE rename research infographic ([fe5b816](https://github.com/sase-org/sase/commit/fe5b816c422a05d4775d5ee63166d43be139cb93))
* add sibling repo research infographic ([c700455](https://github.com/sase-org/sase/commit/c7004559c2ade765398b3707d00ad588ba0b35b7))
* add sibling repo tracking infographic ([d2ef8de](https://github.com/sase-org/sase/commit/d2ef8de416fec84cd2e3c2adcd4db40a86f55ff2))
* add TUI freeze research infographic ([836dce8](https://github.com/sase-org/sase/commit/836dce8b1f2102df17f77224c1d67c3f95f6a381))
* add TUI performance infographic ([03813d9](https://github.com/sase-org/sase/commit/03813d90971cab622bd95c13ef3feb6804c10208))
* add TUI performance log research ([0c67c8a](https://github.com/sase-org/sase/commit/0c67c8a5b5c42a0dc5d8a9a4b3ea02ceb975e575))
* add with_q_and_a research infographic ([7695615](https://github.com/sase-org/sase/commit/769561512d840e87cf4a5119218c2806532df6b2))
* add xprompt thinking level infographic ([5ab3f9e](https://github.com/sase-org/sase/commit/5ab3f9e714feb3614155b37f0caff5ba8b74a73a))
* clarify bead search and research docs ([53b6e8c](https://github.com/sase-org/sase/commit/53b6e8cec499261de0e4dc6117089cb049743478))
* clarify completion and finalizer behavior ([e16df4e](https://github.com/sase-org/sase/commit/e16df4ecd6abee53cb5469adfc382bf2f99b6438))
* clarify linked workspace documentation ([3805b62](https://github.com/sase-org/sase/commit/3805b6229088699810bdf023a25f1fca07ee00e3))
* clarify prompt history documentation ([f7f4146](https://github.com/sase-org/sase/commit/f7f4146958fa2a851c0dfb829fd67decd26d9917))
* clarify refreshed user documentation ([8261b92](https://github.com/sase-org/sase/commit/8261b9278fdb8d08bebd1a70a8c623a621d0f01b))
* consolidate ACE demo video research ([67fb149](https://github.com/sase-org/sase/commit/67fb149a1679909b4ff75162160e1c2c247a5262))
* consolidate agent QoL chat research ([10a0afc](https://github.com/sase-org/sase/commit/10a0afca8aa8cb3192b097253d8debccb5fed6b9))
* consolidate agy migration research ([449ceea](https://github.com/sase-org/sase/commit/449ceeac0c03f768ac2eba697ccb7d849fe38851))
* consolidate agy tools panel research ([5840a69](https://github.com/sase-org/sase/commit/5840a698b87bf386d7443a412d30c85de4002b75))
* consolidate bead work latency research ([f5338b8](https://github.com/sase-org/sase/commit/f5338b812004b469631077e13a9852c37f480f7d))
* consolidate config TUI UX research ([da3314b](https://github.com/sase-org/sase/commit/da3314bb0f53c3debde7a53b3275b7dd20e9795d))
* consolidate coral subcommand naming research ([b480ee9](https://github.com/sase-org/sase/commit/b480ee9708dec683350d52aefefdf4e2e7f786eb))
* consolidate directives and xprompts research ([6d563ea](https://github.com/sase-org/sase/commit/6d563ea481a0669b5cf247594852849b696a5daf))
* consolidate Gemini Antigravity research ([6a00e72](https://github.com/sase-org/sase/commit/6a00e7237a7e61d6afddc6f52aa8c4e42bb95789))
* consolidate HN timing research ([4692e35](https://github.com/sase-org/sase/commit/4692e35152db11ddc79f55d14ccc7ab288c57b76))
* consolidate license file research ([3ffac58](https://github.com/sase-org/sase/commit/3ffac58449b9711b9240b7dacb8f423e94e77307))
* consolidate SASE rename research ([6434c16](https://github.com/sase-org/sase/commit/6434c169468e44ad6c74ca6e38682a0bef9e9d5d))
* consolidate sibling repo open-tracking research ([2759fb6](https://github.com/sase-org/sase/commit/2759fb690e20339dfc62eec49baa6bca046d4b22))
* consolidate sibling repo removal research ([fbac771](https://github.com/sase-org/sase/commit/fbac77176d04194bda0cb7041317a75131b9d1d9))
* consolidate TUI performance research ([e74784f](https://github.com/sase-org/sase/commit/e74784f3edd76059fe8a3d2a3e76613c6ca37378))
* consolidate TUI startup freeze research ([3f3b732](https://github.com/sase-org/sase/commit/3f3b73231f4d4ee567d92c0651c31ace388f5717))
* consolidate with_q_and_a xprompt research ([5d20b9a](https://github.com/sase-org/sase/commit/5d20b9aa6d7ccb0de34a8d87aca210f0aff12ab2))
* consolidate xprompt thinking level research ([c07ba30](https://github.com/sase-org/sase/commit/c07ba30a2ad8886f500c0650bf1316b6cc3f51fc))
* document reasoning-effort directive and default_effort config (sase-55.6) ([85ebbe6](https://github.com/sase-org/sase/commit/85ebbe6733b647ff6de0c65932cfae4111d523ef))
* **glossary:** document `+` VCS project completion (sase-4z.5) ([2d4d27e](https://github.com/sase-org/sase/commit/2d4d27eaef33ccc35f02220e2e1663143c53cf6f))
* **prompt:** document `prompt search` and cover bounded output (sase-4y.5) ([4dd94bf](https://github.com/sase-org/sase/commit/4dd94bf60cd8577508611689223080d78df7a337))
* refresh SASE operational documentation ([d2f20c8](https://github.com/sase-org/sase/commit/d2f20c824c2a401913acab6e728a1c44125642ed))
* refresh SASE user documentation ([5ad6af1](https://github.com/sase-org/sase/commit/5ad6af1d6e9ac8e0c61903ddbf8e02971d4dd6de))
* research agy migration scope ([e1ac8c7](https://github.com/sase-org/sase/commit/e1ac8c7e53b08698e56b8e11f4ddfcf665480e42))
* research alternation shorthand syntax ([ebb1c42](https://github.com/sase-org/sase/commit/ebb1c42acf0b5a115e39ff1685625c673a348571))
* research antigravity tools panel support ([c68276a](https://github.com/sase-org/sase/commit/c68276add6b1b17b146e5976891928371aeb8c30))
* research bead work latency ([ce2103b](https://github.com/sase-org/sase/commit/ce2103b375f177c92f2244d570d8068db7dca919))
* research config editor TUI panel UX ([5f60a1f](https://github.com/sase-org/sase/commit/5f60a1f8882aa49989250ac496d1c5952b99ca7c))
* research config TUI panel UX ([523a5a2](https://github.com/sase-org/sase/commit/523a5a2755016189a79c93750a6546e8b283eb76))
* research consequences of removing sibling repos concept ([ee69270](https://github.com/sase-org/sase/commit/ee6927081d1c7ea76b85f98a5b95a77bb7b45777))
* research directive and xprompt architecture ([533008a](https://github.com/sase-org/sase/commit/533008ade0353e0af1aaeb3c5d3083f818c8b904))
* research Gemini CLI Antigravity transition ([05a433f](https://github.com/sase-org/sase/commit/05a433f929e84763791adecec81462fce399f34c))
* research license file options ([74aecd4](https://github.com/sase-org/sase/commit/74aecd4aae6511217bfbdf8c6a2cce99cb87dad8))
* research open-tracking alternative to sibling_repos ([1645c2f](https://github.com/sase-org/sase/commit/1645c2f0b4f433d2dcfa6c31cb6a270929effa8f))
* research per-model thinking-level directive for xprompts ([2fe5213](https://github.com/sase-org/sase/commit/2fe5213ca91bbe773c91fcca31457a432e7ce458))
* research sibling repository removal ([d5d50a1](https://github.com/sase-org/sase/commit/d5d50a1b5941c02570d96cf668b3ce51fe2d7677))
* research TUI agents tab startup freeze ([f6e2134](https://github.com/sase-org/sase/commit/f6e2134680c94dcdc30511a7c21b00e55d0e395c))
* research with_q_and_a xprompt design ([cd88617](https://github.com/sase-org/sase/commit/cd886176b00cd2343237a111a72a34c859f9aca3))
* research workspace open tracking for linked repos ([24c999a](https://github.com/sase-org/sase/commit/24c999a79dae8d52ae5fdd79059c87d4512b7d33))
* research xprompt reasoning effort ([38c886f](https://github.com/sase-org/sase/commit/38c886f18eeaba38b0dcfaec3f4966deec8635ad))
* **research:** add Hacker News launch timing analysis ([a4f48cb](https://github.com/sase-org/sase/commit/a4f48cbfdf96d7195270ef71b067d3b72fbb9870))
* **research:** add LICENSE file options and recommendation ([0760521](https://github.com/sase-org/sase/commit/0760521dc7eedb70991a0848f3a40d7a1b22e7c7))
* **research:** add TUI performance log analysis ([5c8e247](https://github.com/sase-org/sase/commit/5c8e247b5eebf977e3005f10b62a835880fd214e))
* **research:** analyze agent chat friction patterns ([4d46687](https://github.com/sase-org/sase/commit/4d46687d5102ba7bc1ededa166a3a8db4eeb3114))
* **research:** analyze sase bead work command latency ([d8d7e81](https://github.com/sase-org/sase/commit/d8d7e81d4abfa094e61a9c7ac482f650087fc813))
* **research:** root-cause TUI startup freeze from synchronous terminalization ([7e320fe](https://github.com/sase-org/sase/commit/7e320feb975eb4f84260acfccb4f1e4392a0f835))
* update bead search and research docs ([e52287d](https://github.com/sase-org/sase/commit/e52287dd75120321caf27283c59b0540c1155815))
* update prompt completion and finalizer references ([27560b1](https://github.com/sase-org/sase/commit/27560b19ff1efb3c6ffd337f06e1136a15f4069b))
* update prompt history and config documentation ([b65ad93](https://github.com/sase-org/sase/commit/b65ad932e9379b3b63dcb633a3d93c19cb7db774))
* **xprompt:** document %{} alt brace shorthand (sase-52.7) ([f338e8a](https://github.com/sase-org/sase/commit/f338e8a5eb51eb209e87a03334afdcf17214cd43))

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
