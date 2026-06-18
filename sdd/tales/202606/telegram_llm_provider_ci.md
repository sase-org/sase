---
create_time: 2026-06-18 08:57:54
status: wip
prompt: sdd/prompts/202606/telegram_llm_provider_ci.md
---
# Fix Telegram Launch Tests Without an Installed LLM Provider

## Context

GitHub Actions is failing 11 `TestLaunchAgent` tests with:

```text
RuntimeError: No LLM provider is available. Install a provider plugin or set llm_provider.provider explicitly.
```

The failures all occur after the test has successfully mocked `sase.agent.launcher.launch_agents_from_cwd`. The launch
itself is not the failing dependency. The exception comes from Telegram's launch confirmation rendering path:

1. `_launch_agent()` calls `_launch_agents_with_notifications()`.
2. The mocked launcher returns an `AgentLaunchResult`.
3. `_send_launch_notification()` builds the confirmation header.
4. For prompts without an explicit `%model`, it calls `get_default_provider_name()` and then
   `get_provider().resolve_model_name()`.
5. In CI there is no configured provider and no provider CLI on `PATH`, so the SASE registry raises before Telegram can
   send the confirmation message.

I reproduced the CI-shaped failure locally by using a clean `HOME` and a restricted `PATH`:

```bash
env HOME=/tmp/sase-telegram-ci-home PATH=/usr/bin:/bin \
  PYTHONPATH=/home/bryan/projects/github/sase-org/sase-telegram/src:/home/bryan/projects/github/sase-org/sase/src \
  .venv/bin/pytest tests/test_inbound.py::TestLaunchAgent::test_success_sends_confirmation
```

The root cause is that `sase-telegram` unit tests, and the production confirmation path, depend on host-level LLM
provider autodetection even after the agent launch has already succeeded. Provider/model labels are display metadata and
should not be able to abort a Telegram launch confirmation.

## Plan

1. Add a small launch-label helper in `src/sase_telegram/scripts/sase_tg_inbound.py`.
   - Keep the existing directive-aware behavior for explicit `%model` prompts.
   - When a provider can be resolved, keep using `format_provider_model_label(provider, model)`.
   - When no default provider is available, fall back to the best display label available instead of raising:
     - explicit model directive -> render the model value;
     - no provider/model information -> render `"Agent"`.
   - Log the fallback at debug or warning level so production diagnosis remains possible without making notifications
     fragile.

2. Route `_send_launch_notification()` through that helper.
   - The notification should still include the same prompt preview, workspace number, agent name, fork/wait/retry/kill
     buttons, and pending action writes.
   - Only the provider/model label resolution should change.

3. Add focused regression coverage in `tests/test_inbound.py`.
   - Cover the no-provider/no-model case by mocking the SASE registry to raise from default provider resolution and
     asserting the launch confirmation is still sent.
   - Cover an explicit model directive with unavailable default provider and assert it still labels the launch from the
     directive rather than crashing.
   - Keep existing launch-agent tests as behavior coverage for keyboard and retry handling.

4. Verify with the failing shape and the normal suite.
   - Run the clean-env focused `TestLaunchAgent` case that reproduced the CI failure.
   - Run all `TestLaunchAgent` tests.
   - Run `just test` if the local environment has the `sase` dependency wired in; otherwise run the suite with the same
     `PYTHONPATH` setup used for reproduction and note any local environment limitation.
