"""Layout profiles confirmed by the user.

Layouts repeat per source (Songsterr, Guitar Pro screen captures, particular
channels). Before running full auto-detection the existing profiles are
tried; if the new video matches on resolution (and optionally on the aspect
ratio of the region), that configuration is reused. The library improves with
use: every job a human confirms can be saved as a new profile.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .advance import AdvanceMode
from .region import Region

RESOLUTION_TOLERANCE = 0  # exact resolution required: same source means same encoder/export


@dataclass
class Profile:
    name: str
    video_width: int
    video_height: int
    region: tuple[int, int, int, int]
    mode: str
    created_at: float

    def region_obj(self) -> Region:
        return Region(*self.region)


def _profiles_path(profiles_dir: Path) -> Path:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return profiles_dir / "profiles.json"


def load_profiles(profiles_dir: Path) -> list[Profile]:
    path = _profiles_path(profiles_dir)
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return [Profile(**p) for p in raw]


def save_profile(profiles_dir: Path, name: str, video_width: int, video_height: int,
                  region: Region, mode: AdvanceMode) -> Profile:
    profiles = load_profiles(profiles_dir)
    profiles = [p for p in profiles if p.name != name]
    profile = Profile(
        name=name,
        video_width=video_width,
        video_height=video_height,
        region=region.as_tuple(),
        mode=mode.value if isinstance(mode, AdvanceMode) else mode,
        created_at=time.time(),
    )
    profiles.append(profile)
    _profiles_path(profiles_dir).write_text(json.dumps([asdict(p) for p in profiles], indent=2))
    return profile


def match_profile(profiles_dir: Path, video_width: int, video_height: int) -> Profile | None:
    for p in load_profiles(profiles_dir):
        if abs(p.video_width - video_width) <= RESOLUTION_TOLERANCE and \
           abs(p.video_height - video_height) <= RESOLUTION_TOLERANCE:
            return p
    return None
