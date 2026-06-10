# Changelog

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
