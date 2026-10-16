---
title: LLM Provider Integration
description: This page has moved to its new home.
search:
  exclude: true
---

<!-- generated, do not edit; source: docs/_meta/moves.yml -->

# LLM Provider Integration

This page has moved. See [Providers and models](reference/providers/index.md).

## Moved sections

<a id="overview"></a>

- [Overview](reference/providers/models.md#overview)

<a id="per-prompt-provider-switching"></a>

- [Per prompt provider switching](reference/providers/models.md#per-prompt-provider-switching)

<a id="configured-model-aliases"></a>

- [Configured model aliases](reference/providers/models.md#configured-model-aliases)

<a id="macro-model-inputs"></a>

- [Macro model inputs](reference/providers/models.md#macro-model-inputs)

<a id="implicit-role-aliases"></a>

- [Implicit role aliases](reference/providers/models.md#implicit-role-aliases)

<a id="launch-scoped-alias-overrides"></a>

- [Launch scoped alias overrides](reference/providers/models.md#launch-scoped-alias-overrides)

<a id="explicit-providermodel-syntax"></a>

- [Explicit providermodel syntax](reference/providers/models.md#explicit-providermodel-syntax)

<a id="automatic-provider-resolution"></a>

- [Automatic provider resolution](reference/providers/models.md#automatic-provider-resolution)

<a id="built-in-model-catalog"></a>

- [Built in model catalog](reference/providers/models.md#built-in-model-catalog)

<a id="model-short-aliases"></a>

- [Model short aliases](reference/providers/models.md#model-short-aliases)

<a id="model-advisories"></a>

- [Model advisories](reference/providers/models.md#model-advisories)

<a id="reasoning-effort"></a>

- [Reasoning effort](reference/providers/models.md#reasoning-effort)

<a id="requesting-an-effort"></a>

- [Requesting an effort](reference/providers/models.md#requesting-an-effort)

<a id="explicit-vs-default-semantics"></a>

- [Explicit vs default semantics](reference/providers/models.md#explicit-vs-default-semantics)

<a id="provider-support-matrix"></a>

- [Provider support matrix](reference/providers/models.md#provider-support-matrix)

<a id="model-tier-system"></a>

- [Model tier system](reference/providers/models.md#model-tier-system)

<a id="type-definition"></a>

- [Type definition](reference/providers/models.md#type-definition)

<a id="provider-tier-defaults"></a>

- [Provider tier defaults](reference/providers/models.md#provider-tier-defaults)

<a id="legacy-mapping"></a>

- [Legacy mapping](reference/upgrading/providers.md#model-selection-names)

<a id="global-override"></a>

- [Global override](reference/providers/models.md#global-override)

<a id="maintaining-the-built-in-catalog"></a>

- [Maintaining the built in catalog](reference/providers/models.md#maintaining-the-built-in-catalog)

<a id="role-aliases-for-delegated-work"></a>

- [Role aliases for delegated work](reference/providers/models.md#role-aliases-for-delegated-work)

<a id="source-layout"></a>

- [Source layout](contribute/llm-invocation.md#source-layout)

<a id="provider-architecture"></a>

- [Provider architecture](contribute/llm-invocation.md#provider-architecture)

<a id="base-class"></a>

- [Base class](contribute/llm-invocation.md#base-class)

<a id="registry"></a>

- [Registry](contribute/llm-invocation.md#registry)

<a id="selection-logic"></a>

- [Selection logic](contribute/llm-invocation.md#selection-logic)

<a id="commit-finalization"></a>

- [Commit finalization](contribute/llm-invocation.md#commit-finalization)

<a id="token-usage-tracking"></a>

- [Token usage tracking](contribute/llm-invocation.md#token-usage-tracking)

<a id="artifact-format"></a>

- [Artifact format](contribute/llm-invocation.md#artifact-format)

<a id="prompt-preprocessing-pipeline"></a>

- [Prompt preprocessing pipeline](contribute/llm-invocation.md#prompt-preprocessing-pipeline)

<a id="steps"></a>

- [Steps](contribute/llm-invocation.md#steps)

<a id="order-matters"></a>

- [Order matters](contribute/llm-invocation.md#order-matters)

<a id="home-mode"></a>

- [Home mode](contribute/llm-invocation.md#home-mode)

<a id="source-functions"></a>

- [Source functions](contribute/llm-invocation.md#source-functions)

<a id="subprocess-streaming"></a>

- [Subprocess streaming](contribute/llm-invocation.md#subprocess-streaming)

<a id="mechanism"></a>

- [Mechanism](contribute/llm-invocation.md#mechanism)

<a id="live-reply-file"></a>

- [Live reply file](contribute/llm-invocation.md#live-reply-file)

<a id="output-suppression"></a>

- [Output suppression](contribute/llm-invocation.md#output-suppression)

<a id="provider-teardown-watchdog"></a>

- [Provider teardown watchdog](contribute/llm-invocation.md#provider-teardown-watchdog)

<a id="postprocessing"></a>

- [Postprocessing](contribute/llm-invocation.md#postprocessing)

<a id="on-success-postprocesssuccess"></a>

- [On success postprocesssuccess](contribute/llm-invocation.md#on-success-postprocesssuccess)

<a id="on-error-postprocesserror"></a>

- [On error postprocesserror](contribute/llm-invocation.md#on-error-postprocesserror)

<a id="sasemd-log-format"></a>

- [Sasemd log format](contribute/llm-invocation.md#sasemd-log-format)

<a id="prompt-file-saving"></a>

- [Prompt file saving](contribute/llm-invocation.md#prompt-file-saving)

<a id="chat-history"></a>

- [Chat history](contribute/llm-invocation.md#chat-history)

<a id="file-naming"></a>

- [File naming](contribute/llm-invocation.md#file-naming)

<a id="file-format"></a>

- [File format](contribute/llm-invocation.md#file-format)

<a id="resume-support"></a>

- [Resume support](contribute/llm-invocation.md#resume-support)

<a id="invocation-lifecycle"></a>

- [Invocation lifecycle](contribute/llm-invocation.md#invocation-lifecycle)

<a id="parameters"></a>

- [Parameters](contribute/llm-invocation.md#parameters)

<a id="return-value"></a>

- [Return value](contribute/llm-invocation.md#return-value)

<a id="claude-code-integration"></a>

- [Claude code integration](reference/providers/claude.md#claude-code-integration)

<a id="command-construction"></a>

- [Command construction](reference/providers/claude.md#command-construction)

<a id="single-turn-wait-guard"></a>

- [Single turn wait guard](reference/providers/claude.md#single-turn-wait-guard)

<a id="native-helpers"></a>

- [Native helpers](reference/providers/claude.md#native-helpers)

<a id="model-mapping"></a>

- [Model mapping](reference/providers/claude.md#model-mapping)

<a id="environment-variables"></a>

- [Environment variables](reference/providers/claude.md#environment-variables)

<a id="timer-display"></a>

- [Timer display](reference/providers/claude.md#timer-display)

<a id="claude-tool-calls"></a>

- [Claude tool calls](reference/providers/claude.md#claude-tool-calls)

<a id="antigravity-agy-integration"></a>

- [Antigravity agy integration](reference/providers/agy.md#antigravity-agy-integration)

<a id="command-construction-1"></a>

- [Command construction 1](reference/providers/agy.md#command-construction-1)

<a id="print-mode-no-progress-recovery"></a>

- [Print mode no progress recovery](reference/providers/agy.md#print-mode-no-progress-recovery)

<a id="model-mapping-1"></a>

- [Model mapping 1](reference/providers/agy.md#model-mapping-1)

<a id="environment-variables-1"></a>

- [Environment variables 1](reference/providers/agy.md#environment-variables-1)

<a id="skill-deployment"></a>

- [Skill deployment](reference/providers/agy.md#skill-deployment)

<a id="structured-artifacts-parity-gap"></a>

- [Structured artifacts parity gap](reference/providers/agy.md#structured-artifacts-parity-gap)

<a id="timer-display-1"></a>

- [Timer display 1](reference/providers/agy.md#timer-display-1)

<a id="codex-cli-integration"></a>

- [Codex cli integration](reference/providers/codex.md#codex-cli-integration)

<a id="command-construction-2"></a>

- [Command construction 2](reference/providers/codex.md#command-construction-2)

<a id="codex-instruction-delivery"></a>

- [Codex instruction delivery](reference/providers/codex.md#codex-instruction-delivery)

<a id="model-mapping-2"></a>

- [Model mapping 2](reference/providers/codex.md#model-mapping-2)

<a id="plan-handling"></a>

- [Plan handling](reference/providers/codex.md#plan-handling)

<a id="environment-variables-2"></a>

- [Environment variables 2](reference/providers/codex.md#environment-variables-2)

<a id="codex-tool-call-capture"></a>

- [Codex tool call capture](reference/providers/codex.md#codex-tool-call-capture)

<a id="turn-integrity-check"></a>

- [Turn integrity check](reference/providers/codex.md#turn-integrity-check)

<a id="timer-display-2"></a>

- [Timer display 2](reference/providers/codex.md#timer-display-2)

<a id="qwen-code-integration"></a>

- [Qwen code integration](reference/providers/qwen.md#qwen-code-integration)

<a id="command-construction-3"></a>

- [Command construction 3](reference/providers/qwen.md#command-construction-3)

<a id="model-mapping-3"></a>

- [Model mapping 3](reference/providers/qwen.md#model-mapping-3)

<a id="authentication"></a>

- [Authentication](reference/providers/qwen.md#authentication)

<a id="environment-variables-3"></a>

- [Environment variables 3](reference/providers/qwen.md#environment-variables-3)

<a id="qwen-tool-call-capture"></a>

- [Qwen tool call capture](reference/providers/qwen.md#qwen-tool-call-capture)

<a id="commit-finalization-1"></a>

- [Commit finalization 1](reference/providers/qwen.md#commit-finalization-1)

<a id="timer-display-3"></a>

- [Timer display 3](reference/providers/qwen.md#timer-display-3)

<a id="opencode-integration"></a>

- [Opencode integration](reference/providers/opencode.md#opencode-integration)

<a id="command-construction-4"></a>

- [Command construction 4](reference/providers/opencode.md#command-construction-4)

<a id="model-mapping-4"></a>

- [Model mapping 4](reference/providers/opencode.md#model-mapping-4)

<a id="authentication-and-config"></a>

- [Authentication and config](reference/providers/opencode.md#authentication-and-config)

<a id="environment-variables-4"></a>

- [Environment variables 4](reference/providers/opencode.md#environment-variables-4)

<a id="timer-display-4"></a>

- [Timer display 4](reference/providers/opencode.md#timer-display-4)

<a id="muse-code-integration"></a>

- [Muse code integration](reference/providers/muse.md#muse-code-integration)

<a id="selection"></a>

- [Selection](reference/providers/muse.md#selection)

<a id="command-construction-5"></a>

- [Command construction 5](reference/providers/muse.md#command-construction-5)

<a id="single-turn-normalization"></a>

- [Single turn normalization](reference/providers/muse.md#single-turn-normalization)

<a id="model-mapping-5"></a>

- [Model mapping 5](reference/providers/muse.md#model-mapping-5)

<a id="muse-reasoning-effort"></a>

- [Muse reasoning effort](reference/providers/muse.md#muse-reasoning-effort)

<a id="the-event-stream"></a>

- [The event stream](reference/providers/muse.md#the-event-stream)

<a id="muse-tool-call-capture"></a>

- [Muse tool call capture](reference/providers/muse.md#muse-tool-call-capture)

<a id="token-usage-and-model-identity"></a>

- [Token usage and model identity](reference/providers/muse.md#token-usage-and-model-identity)

<a id="interrupts-and-retries"></a>

- [Interrupts and retries](reference/providers/muse.md#interrupts-and-retries)

<a id="skills-and-instruction-file"></a>

- [Skills and instruction file](reference/providers/muse.md#skills-and-instruction-file)

<a id="environment-variables-5"></a>

- [Environment variables 5](reference/providers/muse.md#environment-variables-5)

<a id="timer-display-5"></a>

- [Timer display 5](reference/providers/muse.md#timer-display-5)

<a id="grok-build-integration"></a>

- [Grok build integration](reference/providers/grok.md#grok-build-integration)

<a id="selection-1"></a>

- [Selection 1](reference/providers/grok.md#selection-1)

<a id="command-construction-6"></a>

- [Command construction 6](reference/providers/grok.md#command-construction-6)

<a id="model-mapping-6"></a>

- [Model mapping 6](reference/providers/grok.md#model-mapping-6)

<a id="grok-reasoning-effort"></a>

- [Grok reasoning effort](reference/providers/grok.md#grok-reasoning-effort)

<a id="the-event-stream-1"></a>

- [The event stream 1](reference/providers/grok.md#the-event-stream-1)

<a id="grok-tool-call-capture"></a>

- [Grok tool call capture](reference/providers/grok.md#grok-tool-call-capture)

<a id="token-usage"></a>

- [Token usage](reference/providers/grok.md#token-usage)

<a id="interrupts-and-retries-1"></a>

- [Interrupts and retries 1](reference/providers/grok.md#interrupts-and-retries-1)

<a id="skills-and-instruction-file-1"></a>

- [Skills and instruction file 1](reference/providers/grok.md#skills-and-instruction-file-1)

<a id="environment-variables-6"></a>

- [Environment variables 6](reference/providers/grok.md#environment-variables-6)

<a id="timer-display-6"></a>

- [Timer display 6](reference/providers/grok.md#timer-display-6)

<a id="external-provider-plugins"></a>

- [External provider plugins](reference/providers/plugins.md#external-provider-plugins-1)

<a id="subscription-usage-extension"></a>

- [Subscription usage extension](reference/providers/plugins.md#subscription-usage-extension)

<a id="configuration"></a>

- [Configuration](reference/providers/configuration.md#configuration)

<a id="config-file"></a>

- [Config file](reference/providers/configuration.md#configuration)

<a id="config-fields"></a>

- [Config fields](reference/config/llm-provider.md)

<a id="continuation-budget-preflight"></a>

- [Continuation budget preflight](reference/providers/configuration.md#continuation-budget-preflight)

<a id="cli-flags"></a>

- [Cli flags](reference/providers/configuration.md#command-line-options)

<a id="tui"></a>

- [Tui](reference/cli/tui.md)

<a id="axe"></a>

- [Axe](reference/cli/axe.md)

<a id="temporary-model-overrides"></a>

- [Temporary model overrides](reference/providers/routing.md#temporary-model-overrides)

<a id="resolution-order-default-providermodel"></a>

- [Resolution order default providermodel](reference/providers/routing.md#resolution-order-default-providermodel)

<a id="temporary-provider-disables"></a>

- [Temporary provider disables](reference/providers/routing.md#temporary-provider-disables)

<a id="state-file"></a>

- [State file](reference/providers/routing.md#state-file)

<a id="model-resolution"></a>

- [Model resolution](reference/providers/routing.md#model-resolution)

<a id="duration-parsing"></a>

- [Duration parsing](reference/providers/routing.md#duration-parsing)

<a id="public-api"></a>

- [Public api](reference/providers/routing.md#public-api)

<a id="examples"></a>

- [Examples](reference/providers/routing.md#examples)

<a id="temporary-provider-priority"></a>

- [Temporary provider priority](reference/providers/routing.md#temporary-provider-priority)

<a id="subscription-usage"></a>

- [Subscription usage](reference/providers/usage.md#subscription-usage)

<a id="usage-limit-auto-disable"></a>

- [Usage limit auto disable](reference/providers/usage.md#usage-limit-auto-disable)

<a id="reset-hint-forms"></a>

- [Reset hint forms](reference/providers/usage.md#reset-hint-forms)

<a id="draining-a-disabled-provider"></a>

- [Draining a disabled provider](reference/providers/usage.md#draining-a-disabled-provider)

<a id="environment-variable-reference"></a>

- [Environment variable reference](reference/environment-variables.md#environment-variable-reference)

<a id="generic-provider-agnostic"></a>

- [Generic provider agnostic](reference/environment-variables.md#generic-provider-agnostic)

<a id="claude-specific"></a>

- [Claude specific](reference/environment-variables.md#claude-specific)

<a id="codex-specific"></a>

- [Codex specific](reference/environment-variables.md#codex-specific)

<a id="qwen-specific"></a>

- [Qwen specific](reference/environment-variables.md#qwen-specific)

<a id="antigravity-agy-specific"></a>

- [Antigravity agy specific](reference/environment-variables.md#antigravity-agy-specific)

<a id="opencode-specific"></a>

- [Opencode specific](reference/environment-variables.md#opencode-specific)

<a id="muse-code-specific"></a>

- [Muse code specific](reference/environment-variables.md#muse-code-specific)

<a id="grok-specific"></a>

- [Grok specific](reference/environment-variables.md#grok-specific)

<a id="vcs-provider"></a>

- [Vcs provider](reference/environment-variables.md#vcs-provider)

<a id="retry-and-fallback"></a>

- [Retry and fallback](reference/providers/retry-and-fallback.md#retry-and-fallback)

<a id="configuration-1"></a>

- [Configuration 1](reference/providers/retry-and-fallback.md#configuration-1)

<a id="config-fields-1"></a>

- [Config fields 1](reference/config/llm-provider.md#llm_provider-retry)

<a id="default-configuration"></a>

- [Default configuration](reference/providers/retry-and-fallback.md#default-configuration)

<a id="provider-supplied-retry-defaults"></a>

- [Provider supplied retry defaults](reference/providers/retry-and-fallback.md#provider-supplied-retry-defaults)

<a id="retry-flow"></a>

- [Retry flow](reference/providers/retry-and-fallback.md#retry-flow)

<a id="tui-display"></a>

- [Tui display](reference/providers/retry-and-fallback.md#tui-display)

<a id="metadata-tracking"></a>

- [Metadata tracking](reference/providers/retry-and-fallback.md#metadata-tracking)

<a id="spawn-on-retry"></a>

- [Spawn on retry](reference/providers/retry-and-fallback.md#spawn-on-retry)

<a id="legacy-thinking-metadata"></a>

- [Legacy thinking metadata](reference/upgrading/providers.md#legacy-thinking-metadata)

<a id="table-of-contents"></a>

- [Table of contents](reference/providers/index.md)
