#!/usr/bin/env python3
# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""Fail if the version is not the same everywhere it is declared.

The version lives in four files (npm, Tauri, Cargo, Python) and none of them
can read the others at build time. CI runs this so a release cannot ship an
installer that reports one version and an engine that reports another.
"""
from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    found = {
        "package.json": json.loads((ROOT / "package.json").read_text())["version"],
        "src-tauri/tauri.conf.json": json.loads((ROOT / "src-tauri/tauri.conf.json").read_text())["version"],
        "src-tauri/Cargo.toml": tomllib.loads((ROOT / "src-tauri/Cargo.toml").read_text())["package"]["version"],
        "pyproject.toml": tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"],
    }
    tag = sys.argv[1] if len(sys.argv) > 1 else None
    if tag:
        found["git tag"] = re.sub(r"^v", "", tag)

    versions = set(found.values())
    for where, version in found.items():
        print(f"{where:28} {version}")
    if len(versions) > 1:
        print("::error::the version differs between files", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
