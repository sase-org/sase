"""Pluggy hook specifications for LLM provider plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pluggy

from .types import InvokeResult, LLMInvocationOptions, ModelTier

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig

hookspec = pluggy.HookspecMarker("sase_llm")
hookimpl = pluggy.HookimplMarker("sase_llm")


class LLMHookSpec:
    """Hook specifications mirroring :class:`LLMProvider` methods.

    Every method uses ``firstresult=True`` so pluggy returns the first
    non-``None`` result from the registered plugins.  Method names are
    prefixed with ``llm_`` to namespace them within the pluggy project.

    Metadata hooks (everything below ``--- Identity ---``) are called
    directly on each registered plugin instance by the registry module
    rather than through the pluggy hook-dispatch machinery — aggregating
    across plugins requires knowing which plugin produced each value, so
    callers iterate ``pm.list_name_plugin()`` and call the decorated
    methods on the instance.  The ``@hookspec`` decorator here documents
    the contract; ``@hookimpl`` on providers marks the implementing
    methods.
    """

    # --- Core dispatch ---

    @hookspec(firstresult=True)
    def llm_invoke(
        self,
        prompt: str,
        model_tier: ModelTier,
        suppress_output: bool,
        model_override: str | None,
        options: LLMInvocationOptions | None,
    ) -> InvokeResult: ...

    @hookspec(firstresult=True)
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str: ...

    # --- Identity ---

    @hookspec(firstresult=True)
    def llm_provider_name(self) -> str: ...

    @hookspec(firstresult=True)
    def llm_provider_short_name(self) -> str:
        """Short label used in spawned-agent name suffixes (e.g. ``foo.cld``).

        Should be unique across providers. When omitted, the registry
        falls back to the provider entry-point name (``llm_provider_name``).
        """
        ...

    # --- Metadata ---

    @hookspec(firstresult=True)
    def llm_known_model_names(self) -> list[str]: ...

    @hookspec(firstresult=True)
    def llm_model_short_aliases(self) -> dict[str, str]: ...

    @hookspec(firstresult=True)
    def llm_skill_template_context(self) -> dict[str, str]: ...

    @hookspec(firstresult=True)
    def llm_skill_deploy_subpath(self) -> str | None: ...

    @hookspec(firstresult=True)
    def llm_additional_skill_deploy_subpaths(self) -> list[str] | None: ...

    @hookspec(firstresult=True)
    def llm_cli_status_color(self) -> str | None: ...

    @hookspec(firstresult=True)
    def llm_autodetect_priority(self) -> int | None: ...

    @hookspec(firstresult=True)
    def llm_autodetect_cli_name(self) -> str | None: ...

    @hookspec(firstresult=True)
    def llm_auth_evidence(self) -> dict[str, object] | None:
        """Offline auth evidence for doctor checks.

        ``credential_paths`` are file or directory paths whose presence suggests
        local provider auth has been configured. ``api_key_env_vars`` are env
        var names that can carry provider credentials. Values must not contain
        secrets; doctor only reports names and path existence. Providers that
        need no authentication may set ``auth_not_required`` to ``True``.
        """
        ...

    @hookspec(firstresult=True)
    def llm_install_metadata(self) -> dict[str, object] | None:
        """Provider CLI install and update metadata.

        ``manager`` names the external package manager needed to install this
        provider CLI, such as ``npm``. ``package`` and ``scope`` are optional
        descriptive fields used in diagnostic output. Providers may also
        declare ``display_name``, ``docs_url``, ``self_update_argv``,
        ``version_argv`` (default ``["--version"]``), ``version_regex``,
        ``latest_version_package``, and ``brew_package``.

        CLIs distributed by a version channel rather than a package registry
        may declare ``latest_version_url`` (an HTTPS JSON endpoint) with
        ``latest_version_json_field`` (default ``version``), and
        ``version_compare: "exact"`` when their release ids are not valid
        PEP 440 versions. ``self_update_env`` and ``install_env`` are env
        overlays applied to the update and install commands, and
        ``manager: "script"`` with ``install_script_url`` marks a CLI that
        ``sase agent-cli install`` can fetch and run; ``install_dir`` and
        ``install_dir_env`` name where that installer writes the binary so
        SASE can report whether it landed on ``PATH``. Values must not contain
        secrets. Consumers must treat every field as optional so third-party
        providers remain compatible.
        """
        ...

    @hookspec(firstresult=True)
    def llm_model_advisories(self) -> dict[str, dict[str, str]] | None:
        """Per-model advisories surfaced in model-selection UI.

        Maps a model id to ``{"severity": "warn"|"info", "label": <short>,
        "detail": <sentence>}``. ``label`` is a few words rendered inline next
        to the model; ``detail`` is the full sentence shown as secondary text.
        Use this for terms a user should see *at selection time* — discounted
        tiers that train on their inputs, preview models with no stability
        guarantee, free tiers with unusual retention.

        Omitting the hook means no advisories, and non-conforming entries are
        dropped rather than raising, so third-party providers stay compatible.
        """
        ...

    @hookspec(firstresult=True)
    def llm_default_retry_config(self) -> ProviderRetryConfig | None: ...

    @hookspec(firstresult=True)
    def llm_hidden_from_model_pickers(self) -> bool | None:
        """Whether this provider should be hidden from model-selection UI.

        Providers that exist only for testing (e.g. ``fakey``) return
        ``True``. Hiding affects user-facing model selection surfaces only —
        the ACE model picker and ``%model`` completion catalog — and never
        changes routing, resolution, autodetect, or doctor output. Omitting
        this hook means "not hidden", so third-party providers stay
        compatible without implementing it.
        """
        ...

    @hookspec(firstresult=True)
    def llm_hidden_from_agent_cli_management(self) -> bool | None:
        """Whether this provider should be hidden from agent-CLI management.

        Internal or otherwise non-independently manageable providers return
        ``True`` to opt out of ``sase agent-cli`` inventory/update operations
        and the Admin Center's Updates → Agent CLIs surface. Hiding here does
        not affect routing, model resolution, autodetection, direct provider
        invocation, or doctor diagnostics. Omitting this hook means "visible",
        so third-party providers stay compatible without implementing it.
        """
        ...
