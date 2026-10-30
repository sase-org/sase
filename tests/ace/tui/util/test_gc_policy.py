"""Compatibility facade for the split GC policy tests."""

from __future__ import annotations

from collections.abc import Iterator  # noqa: F401
from contextlib import AsyncExitStack, contextmanager  # noqa: F401
import logging  # noqa: F401
import threading  # noqa: F401
from types import SimpleNamespace  # noqa: F401
from typing import Any  # noqa: F401

import pytest  # noqa: F401
from textual.screen import ModalScreen  # noqa: F401
from textual.widgets import Input, TextArea  # noqa: F401

from sase.ace.tui.actions._event_keyboard import EventKeyboardMixin  # noqa: F401
from sase.ace.tui.util import gc_policy, gc_telemetry  # noqa: F401
from sase.ace.tui.util.gc_policy import (  # noqa: F401
    GCPolicy,
    install_gc_policy,
    uninstall_gc_policy,
)
from .test_gc_policy_census import *  # noqa: F403
from .test_gc_policy_lifecycle import *  # noqa: F403
from .test_gc_policy_policy import *  # noqa: F403
from .test_gc_policy_lifecycle import active_guard  # noqa: F401
from .test_gc_policy_policy import clock, collector, recorder, tags  # noqa: F401

modal_text_input_active = gc_policy._modal_text_input_active
__test__ = False
__all__ = [name for name in globals() if not name.startswith("_")]
