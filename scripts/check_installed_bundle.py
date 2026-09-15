#!/usr/bin/env python3
# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""Smoke test of the .deb as installed on the machine, not as built.

Usage (after `apt-get install ./TabXtract_x.y.z_amd64.deb`):
    python scripts/check_installed_bundle.py --deb path/to/package.deb

What only shows up on the user's machine is what gets checked: resources
declared in tauri.conf.json that never reached the package, executables that
lost their executable bit on the way (the app's own chmod cannot fix that
under /usr/lib, where the user has no write access, and it ignores the
failure), native binaries that do not start, missing shared libraries, and a
frozen sidecar that does not come up when launched from the installed tree.

Everything runs against the installed files. src-tauri/ is only read as the
list of what should have been installed.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_sidecar import SidecarCheckError, start_and_verify  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TAURI_DIR = ROOT / "src-tauri"
SIDECAR_REL = Path("sidecar/tabxtract-server/tabxtract-server")
# Placeholders that keep the empty resource directories in git; whether the
# bundler ships them is irrelevant to the app.
IGNORED_NAMES = {".gitkeep"}
NATIVE_PROBES = {
    "ffmpeg": ["-version"],
    "ffprobe": ["-version"],
    "yt-dlp": ["--version"],
    "tesseract": ["--version"],
}
PROBE_TIMEOUT = 30


def declared_resource_dirs() -> list[str]:
    """The directories bundled as resources, read from tauri.conf.json.

    Only the `<dir>/**/*` form is understood. Anything else fails loudly, so
    a change to the config cannot quietly leave resources unchecked.
    """
    config = json.loads((TAURI_DIR / "tauri.conf.json").read_text())
    dirs = []
    for pattern in config["bundle"]["resources"]:
        if not pattern.endswith("/**/*") or "*" in pattern[:-len("/**/*")]:
            raise SystemExit(f"error: unsupported resource pattern {pattern!r}; update this check")
        dirs.append(pattern[:-len("/**/*")])
    return dirs


def files_under(base: Path) -> dict[Path, os.stat_result]:
    """Relative path -> stat (following symlinks) of every file under `base`."""
    out = {}
    for path in base.rglob("*"):
        if path.name in IGNORED_NAMES or not path.is_file():
            continue
        out[path.relative_to(base)] = path.stat()
    return out


def is_executable_by_anyone(mode: int) -> bool:
    return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def compare_tree(built_dir: Path, shipped_dir: Path) -> list[str]:
    """Differences between a resource directory as built and as installed."""
    built = files_under(built_dir)
    shipped = files_under(shipped_dir)
    print(f"{built_dir.name}/: {len(built)} built, {len(shipped)} installed")
    if not built:
        return [f"{built_dir.name}/ is empty in the build tree: nothing to verify against"]

    common = set(built) & set(shipped)
    findings = {
        "missing": sorted(set(built) - set(shipped)),
        "not declared but installed": sorted(set(shipped) - set(built)),
        "size differs": sorted(rel for rel in common if built[rel].st_size != shipped[rel].st_size),
        # Installed files are owned by root and run by the user, so the bit
        # that matters is "others"; checking any bit would miss 0744.
        "lost the executable bit": sorted(
            rel for rel in common
            if is_executable_by_anyone(built[rel].st_mode) and not shipped[rel].st_mode & stat.S_IXOTH),
    }
    problems = []
    for label, items in findings.items():
        if items:
            shown = ", ".join(str(i) for i in items[:20])
            more = f" (+{len(items) - 20} more)" if len(items) > 20 else ""
            problems.append(f"{built_dir.name}/: {len(items)} {label}: {shown}{more}")
    return problems


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deb", required=True, type=Path, help="the .deb that was installed")
    args = parser.parse_args()

    problems: list[str] = []

    package = run(["dpkg-deb", "-f", str(args.deb), "Package"]).stdout.strip()
    listing = run(["dpkg", "-L", package])
    if not package or listing.returncode != 0:
        print(f"error: package {package!r} from {args.deb} is not installed\n{listing.stderr}",
              file=sys.stderr)
        return 1
    installed = [Path(line) for line in listing.stdout.splitlines() if line.startswith("/")]
    print(f"package {package}: {len(installed)} paths installed")

    # --- where the resources landed ---------------------------------------
    sidecars = [p for p in installed if p.as_posix().endswith("/" + SIDECAR_REL.as_posix())]
    if len(sidecars) != 1:
        print(f"error: expected one installed {SIDECAR_REL}, found {sidecars}", file=sys.stderr)
        return 1
    sidecar = sidecars[0]
    resource_root = sidecar.parents[2]
    print(f"resource root: {resource_root}")

    # --- declared resources: present, same size, nothing extra ------------
    for directory in declared_resource_dirs():
        problems += compare_tree(TAURI_DIR / directory, resource_root / directory)

    # --- native binaries start from the installed tree ---------------------
    native = resource_root / "native"
    for name, probe in NATIVE_PROBES.items():
        binary = native / name
        if not binary.is_file():
            continue  # absence is already reported above if it was built
        env = {**os.environ}
        if name == "tesseract":
            env["TESSDATA_PREFIX"] = str(native / "tessdata")
        try:
            result = run([str(binary), *probe], env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            problems.append(f"native/{name} does not start: {exc}")
            continue
        if result.returncode != 0:
            problems.append(f"native/{name} {' '.join(probe)} exited {result.returncode}: "
                            f"{(result.stderr or result.stdout)[-500:]}")
        else:
            first = (result.stdout or result.stderr).strip().splitlines()[:1]
            print(f"native/{name}: {first[0] if first else 'ok'}")

    # --- the app binary links ----------------------------------------------
    app_binaries = [p for p in installed if p.parent == Path("/usr/bin") and p.is_file()]
    if not app_binaries:
        problems.append("no binary installed under /usr/bin")
    for binary in app_binaries:
        unresolved = [line.strip() for line in run(["ldd", str(binary)]).stdout.splitlines()
                      if "not found" in line]
        if unresolved:
            problems.append(f"{binary} has unresolved libraries: {unresolved}")
        else:
            print(f"{binary}: all shared libraries resolve")

    # --- the frozen sidecar comes up, launched as the user -----------------
    if not sidecar.stat().st_mode & stat.S_IXOTH:
        problems.append(f"{sidecar} is not executable by the user; not starting it")
    else:
        try:
            health = start_and_verify(sidecar, require_binaries=True)
            print(f"sidecar: handshake and /api/health ok (version {health['version']})")
        except SidecarCheckError as exc:
            problems.append(f"sidecar from the installed tree: {exc}")

    if problems:
        print(f"\n{len(problems)} problem(s) with the installed package:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("\ninstalled package ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
