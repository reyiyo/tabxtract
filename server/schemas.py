# TabXtract - extracts tablature from video and rebuilds it as a PDF.
# Copyright (C) 2026 TabXtract contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See <https://www.gnu.org/licenses/>.
"""Contracts of the local API."""
from __future__ import annotations

import time

from pydantic import BaseModel, Field

from tabextract.advance import AdvanceMode


class RegionOverride(BaseModel):
    x0: int
    y0: int
    x1: int
    y1: int


class SongBoundaryIn(BaseModel):
    index: int
    start_frame: int
    end_frame: int
    title: str | None = None


class LocalJobRequest(BaseModel):
    """A file already on the user's disk: no upload, just a path."""

    path: str


class UrlJobRequest(BaseModel):
    url: str
    format_id: str | None = None


class ProbeRequest(BaseModel):
    url: str


class RegionPatchRequest(BaseModel):
    region: RegionOverride | None = None
    songs: list[SongBoundaryIn] | None = None


class RenderRequest(BaseModel):
    region: RegionOverride | None = None
    songs: list[SongBoundaryIn] | None = None
    save_profile_name: str | None = None
    output_dir: str | None = None


class PreferencesPatch(BaseModel):
    output_dir: str | None = None
    updates_enabled: bool | None = None
    legal_notice_acknowledged: bool | None = None
    youtube_max_height: int | None = None


class ProfileIn(BaseModel):
    """One imported profile, validated before it reaches profiles.json: a
    malformed entry there makes every later analysis fail on load."""

    name: str = Field(min_length=1, max_length=200)
    video_width: int = Field(gt=0)
    video_height: int = Field(gt=0)
    region: tuple[int, int, int, int]
    mode: AdvanceMode
    created_at: float = Field(default_factory=time.time)


class ProfileImportRequest(BaseModel):
    """Profiles exported as JSON, to be passed around through an issue."""

    profiles: list[dict]
