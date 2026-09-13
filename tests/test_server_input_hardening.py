"""Untrusted input reaching the sidecar cannot turn into something else.

A pasted "URL" is handed to the yt-dlp binary, so it must never be parsed as
an option (`--exec` runs commands) nor point at a non-http source. Imported
profiles are written to profiles.json, which every analysis loads, so a
malformed one must be refused before it gets there.
"""
from __future__ import annotations

import io
import subprocess

import pytest
from pydantic import ValidationError

from server import ytdlp
from server.schemas import ProfileIn


@pytest.mark.parametrize("raw, expected", [
    ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc"),
    ("  youtu.be/abc  ", "https://youtu.be/abc"),
    ("HTTP://example.com/v", "HTTP://example.com/v"),
])
def test_normalize_url_accepts_http_links(raw, expected):
    assert ytdlp.normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["file:///etc/passwd", "ftp://example.com/v.mp4", "https://", ""])
def test_normalize_url_refuses_other_sources(raw):
    with pytest.raises(ytdlp.YtdlpError) as exc:
        ytdlp.normalize_url(raw)
    assert exc.value.kind == "invalid_url"


def _fake_binary(monkeypatch):
    monkeypatch.setattr(ytdlp, "_binary", lambda: "yt-dlp")


def test_probe_never_lets_the_url_become_an_option(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"title": "t", "formats": []}', stderr="")

    _fake_binary(monkeypatch)
    monkeypatch.setattr(ytdlp.subprocess, "run", fake_run)

    ytdlp.probe("--exec=touch /tmp/pwned")

    cmd = calls[0]
    assert cmd[-2:] == ["--", "https://--exec=touch /tmp/pwned"]
    assert "--ignore-config" in cmd


def test_download_never_lets_the_url_become_an_option(monkeypatch, tmp_path):
    calls = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append(cmd)
            self.stdout = iter(())
            self.stderr = io.StringIO("ERROR: Video unavailable")

        def wait(self):
            return 1

    _fake_binary(monkeypatch)
    monkeypatch.setattr(ytdlp.subprocess, "Popen", FakePopen)

    with pytest.raises(ytdlp.YtdlpError):
        ytdlp.download("-J", tmp_path / "source")

    cmd = calls[0]
    assert cmd[-2:] == ["--", "https://-J"]
    assert "--ignore-config" in cmd


def test_expected_sha256_reads_the_published_sums():
    sums = "aaa  yt-dlp\nBBB  yt-dlp_macos\n"
    assert ytdlp._expected_sha256(sums, "yt-dlp_macos") == "bbb"
    with pytest.raises(ytdlp.YtdlpError):
        ytdlp._expected_sha256(sums, "yt-dlp.exe")


def _profile(**overrides):
    data = {"name": "Songsterr 1080p", "video_width": 1920, "video_height": 1080,
            "region": [0, 100, 1920, 500], "mode": "paginated", "created_at": 1.0}
    data.update(overrides)
    return data


def test_valid_profile_round_trips_to_json():
    dumped = ProfileIn.model_validate(_profile()).model_dump(mode="json")
    assert dumped == _profile()


@pytest.mark.parametrize("overrides", [
    {"mode": "sideways"},
    {"region": [0, 0, 10]},
    {"video_width": -1},
    {"name": ""},
    {"video_height": "tall"},
])
def test_malformed_profile_is_refused(overrides):
    with pytest.raises(ValidationError):
        ProfileIn.model_validate(_profile(**overrides))
