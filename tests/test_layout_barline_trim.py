"""Failure mode 3: trim at the last detected barline to remove the bar
repeated between pages, except on the song's last page. If trimming would
remove more than 45% of the width, detection probably failed: skip the trim
and flag low confidence."""
import cv2
import numpy as np

from tabextract.layout import trim_overlap

WIDTH = 800
N_LINES = 4
LINE_GAP = 10
TOP = 30


def _band_with_barline_at(x: int) -> np.ndarray:
    band = np.full((150, WIDTH), 255, dtype=np.uint8)
    for i in range(N_LINES):
        y = TOP + i * LINE_GAP
        cv2.line(band, (10, y), (WIDTH - 10, y), 120, 2)
    cv2.line(band, (x, TOP - 4), (x, TOP + (N_LINES - 1) * LINE_GAP + 4), 20, 4)
    return band


def test_trims_at_last_barline_when_within_guard():
    band = _band_with_barline_at(700)
    trimmed, frac, low_conf = trim_overlap(band, is_last_of_song=False)
    assert not low_conf
    assert trimmed.shape[1] < WIDTH
    assert 0 < frac < 0.45


def test_guard_skips_trim_when_it_would_remove_too_much():
    band = _band_with_barline_at(50)  # would trim >45% of the width
    trimmed, frac, low_conf = trim_overlap(band, is_last_of_song=False)
    assert low_conf
    assert trimmed.shape[1] == WIDTH
    assert frac == 0.0


def test_last_page_of_song_is_never_trimmed():
    band = _band_with_barline_at(700)
    trimmed, frac, low_conf = trim_overlap(band, is_last_of_song=True)
    assert trimmed.shape[1] == WIDTH
    assert frac == 0.0
    assert not low_conf
