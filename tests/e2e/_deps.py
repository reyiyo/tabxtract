"""Optional dependencies of the end-to-end tests.

Outside CI's e2e combination the desktop extras, ffmpeg or tesseract may be
missing, and the tests skip. Where TABXTRACT_E2E_REQUIRED is set, a missing
piece fails instead: an end-to-end suite that skipped in silence reads exactly
like one that passed.
"""
from __future__ import annotations

import importlib
import os
import shutil
from types import ModuleType

import pytest

REQUIRED = bool(os.environ.get("TABXTRACT_E2E_REQUIRED"))


def need_module(name: str) -> ModuleType:
    if REQUIRED:
        return importlib.import_module(name)
    return pytest.importorskip(name)


def need_binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        if REQUIRED:
            pytest.fail(f"{name} is not on PATH", pytrace=False)
        pytest.skip(f"{name} is not on PATH")
    return path
