"""Patch helpers for the suite cost-attribution pytest plugin."""

from __future__ import annotations

import contextvars
import functools
import importlib
import inspect
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any


class _AsyncContextProxy:
    """Time an async context manager's enter and exit without changing it."""

    def __init__(self, recorder: CostPatchMixin, wrapped: Any) -> None:
        self._recorder = recorder
        self._wrapped = wrapped

    async def __aenter__(self) -> Any:
        with self._recorder.measure("textual_app_run_test_enter"):
            return await self._wrapped.__aenter__()

    async def __aexit__(self, *args: Any) -> Any:
        with self._recorder.measure("textual_app_run_test_exit"):
            return await self._wrapped.__aexit__(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


class CostPatchMixin:
    """Install and restore cost-recorder monkeypatches."""

    _patches: list[tuple[Any, str, Any]]

    def measure(self, cause: str) -> AbstractContextManager[None]:
        raise NotImplementedError

    def _patch(self, target: Any, name: str, replacement: Any) -> None:
        original = getattr(target, name)
        self._patches.append((target, name, original))
        setattr(target, name, replacement)

    def _install_patches(self) -> None:
        self._patch_subprocess()
        self._patch_function("gettext", "find", "gettext_find")
        self._patch_function("yaml", "load", "yaml_load")
        self._patch_function("sase.main.parser", "create_parser", "parser_create")
        self._patch_function(
            "sase.config.core", "load_merged_config", "config_load_merged"
        )
        self._patch_async_method("textual.pilot", "Pilot", "pause", self._pause_cause)
        self._patch_async_function(
            "textual._wait", "wait_for_idle", "textual_wait_for_idle"
        )
        self._patch_async_function(
            "sase.ace.testing.settle", "settle_pilot", "ace_settle_pilot"
        )
        self._patch_async_function(
            "sase.ace.testing.settle",
            "pause_until_cpu_idle",
            "ace_pause_until_cpu_idle",
        )
        self._patch_async_function(
            "sase.ace.testing", "settle_pilot", "ace_settle_pilot"
        )
        self._patch_async_function(
            "sase.ace.testing",
            "pause_until_cpu_idle",
            "ace_pause_until_cpu_idle",
        )
        self._patch_app_run_test()
        self._patch_async_method(
            "sase.ace.testing.ace_page", "AcePage", "__aenter__", "ace_page_enter"
        )
        self._patch_async_method(
            "sase.ace.testing.ace_page", "AcePage", "__aexit__", "ace_page_exit"
        )

    def _patch_function(self, module_name: str, attr: str, cause: str) -> None:
        try:
            module = importlib.import_module(module_name)
            original = getattr(module, attr)
        except (ImportError, AttributeError):
            return

        if inspect.iscoroutinefunction(original):
            self._patch_async_callable(module, attr, original, cause)
        else:
            self._patch_sync_callable(module, attr, original, cause)

    def _patch_sync_callable(
        self,
        target: Any,
        attr: str,
        original: Callable[..., Any],
        cause: str,
    ) -> None:
        @functools.wraps(original)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with self.measure(cause):
                return original(*args, **kwargs)

        self._patch(target, attr, wrapper)

    def _patch_async_callable(
        self,
        target: Any,
        attr: str,
        original: Callable[..., Any],
        cause: str | Callable[[tuple[Any, ...], dict[str, Any]], str],
    ) -> None:
        @functools.wraps(original)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            measured = cause(args, kwargs) if callable(cause) else cause
            with self.measure(measured):
                return await original(*args, **kwargs)

        self._patch(target, attr, wrapper)

    def _patch_async_function(self, module_name: str, attr: str, cause: str) -> None:
        try:
            module = importlib.import_module(module_name)
            original = getattr(module, attr)
        except (ImportError, AttributeError):
            return
        if not inspect.iscoroutinefunction(original):
            return
        self._patch_async_callable(module, attr, original, cause)

    def _patch_async_method(
        self,
        module_name: str,
        class_name: str,
        attr: str,
        cause: str | Callable[[tuple[Any, ...], dict[str, Any]], str],
    ) -> None:
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
            original = getattr(cls, attr)
        except (ImportError, AttributeError):
            return
        if not inspect.iscoroutinefunction(original):
            return
        self._patch_async_callable(cls, attr, original, cause)

    def _patch_app_run_test(self) -> None:
        try:
            module = importlib.import_module("textual.app")
            cls = module.App
            original = cls.run_test
        except (ImportError, AttributeError):
            return

        @functools.wraps(original)
        def wrapper(app: Any, *args: Any, **kwargs: Any) -> Any:
            return _AsyncContextProxy(self, original(app, *args, **kwargs))

        self._patch(cls, "run_test", wrapper)

    def _patch_subprocess(self) -> None:
        try:
            module = importlib.import_module("subprocess")
            original_run = module.run
            original_popen = module.Popen
        except (ImportError, AttributeError):
            return

        in_run: contextvars.ContextVar[bool] = contextvars.ContextVar(
            "sase_test_cost_in_subprocess_run", default=False
        )

        @functools.wraps(original_run)
        def run_wrapper(*args: Any, **kwargs: Any) -> Any:
            token = in_run.set(True)
            try:
                with self.measure("subprocess_run"):
                    return original_run(*args, **kwargs)
            finally:
                in_run.reset(token)

        recorder = self

        class TimedPopen(original_popen):  # type: ignore[misc, valid-type]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                if in_run.get():
                    super().__init__(*args, **kwargs)
                    return
                with recorder.measure("subprocess_popen"):
                    super().__init__(*args, **kwargs)

        TimedPopen.__name__ = getattr(original_popen, "__name__", "Popen")
        TimedPopen.__qualname__ = getattr(original_popen, "__qualname__", "Popen")
        TimedPopen.__module__ = getattr(original_popen, "__module__", "subprocess")

        self._patch(module, "run", run_wrapper)
        self._patch(module, "Popen", TimedPopen)

    @staticmethod
    def _pause_cause(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        delay = kwargs.get("delay")
        if len(args) >= 2:
            delay = args[1]
        return "pilot_pause_none" if delay is None else "pilot_pause_delay"

    def _restore_patches(self) -> None:
        for target, name, original in reversed(self._patches):
            setattr(target, name, original)
        self._patches.clear()
