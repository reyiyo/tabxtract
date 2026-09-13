"""Failure mode 4: the gap threshold is self-calibrating (Otsu over the
bimodal histogram of gap sizes), never a fixed number. Failure mode 5:
detection runs on the raw greyscale canvas, never on the already binarised
image."""
import cv2
import numpy as np

from tabextract.layout import find_system_blocks
from tabextract.verify import check_cuts_on_ink

WIDTH = 800


def _draw_system(canvas: np.ndarray, top: int, line_gap: int = 10, n_lines: int = 4) -> None:
    for i in range(n_lines):
        y = top + i * line_gap
        cv2.line(canvas, (20, y), (WIDTH - 20, y), 120, 2)
    for x in range(60, WIDTH - 40, 150):
        cv2.line(canvas, (x, top - 4), (x, top + (n_lines - 1) * line_gap + 4), 30, 3)


def test_two_systems_separated_by_large_gap_are_split_at_gap_center():
    canvas = np.full((450, WIDTH), 255, dtype=np.uint8)
    _draw_system(canvas, top=40)
    _draw_system(canvas, top=280)  # a real ~200px gap between systems

    blocks, cut_ys = find_system_blocks(canvas)

    assert len(blocks) == 2
    assert len(cut_ys) == 1
    cut = cut_ys[0]
    assert 100 < cut < 280

    bad_cuts = check_cuts_on_ink(canvas, cut_ys)
    assert bad_cuts == [], "the cut may never land on ink"


def test_internal_line_spacing_does_not_get_mistaken_for_a_system_gap():
    canvas = np.full((120, WIDTH), 255, dtype=np.uint8)
    _draw_system(canvas, top=40, line_gap=10)  # internal ~8px gaps between lines

    blocks, cut_ys = find_system_blocks(canvas)

    assert len(blocks) == 1
    assert cut_ys == []
