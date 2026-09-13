"""In standard notation plus tablature, the barline is drawn unbroken from
the staff above to the tab below. The white space between them is as wide as a
real separation between systems, so Otsu picks it as a cut and splits one
system down the middle (notation on top, tab below). The barline crossing it
is the typographic mark that both staves are a single system.

The barlines are drawn thin and spaced out on purpose: they have to contribute
LESS ink per row than the blank-row threshold, otherwise the row never counts
as blank and the gap never exists. That is exactly the situation in the real
video that motivated the fix (barlines of ~29px of ink on a 1920px canvas,
against a 38px threshold)."""
import cv2
import numpy as np

from tabextract.layout import find_system_blocks
from tabextract.verify import check_cuts_on_ink

WIDTH, HEIGHT = 800, 660
TAB_OFFSET = 150     # distance from the top of the notation to the top of the tab
SECOND_SYSTEM = 420


def _canvas(with_bridging_barlines: bool) -> np.ndarray:
    canvas = np.full((HEIGHT, WIDTH), 255, dtype=np.uint8)

    def system(top: int) -> None:
        for i in range(5):  # notation staff
            cv2.line(canvas, (20, top + i * 10), (WIDTH - 20, top + i * 10), 120, 2)
        tab_top = top + TAB_OFFSET
        for i in range(4):  # tablature
            cv2.line(canvas, (20, tab_top + i * 10), (WIDTH - 20, tab_top + i * 10), 120, 2)
        for x in np.linspace(80, WIDTH - 80, 3).astype(int):
            if with_bridging_barlines:
                cv2.line(canvas, (x, top), (x, tab_top + 30), 30, 2)
            else:
                cv2.line(canvas, (x, top), (x, top + 40), 30, 2)
                cv2.line(canvas, (x, tab_top), (x, tab_top + 30), 30, 2)

    system(40)
    system(SECOND_SYSTEM)
    return canvas


def test_barline_bridging_notation_and_tab_keeps_one_system_together():
    canvas = _canvas(with_bridging_barlines=True)

    blocks, cut_ys = find_system_blocks(canvas)

    assert len(blocks) == 2, (
        f"notation and its tab are one system; it was split into {len(blocks)} blocks"
    )
    assert check_cuts_on_ink(canvas, cut_ys) == [], "no cut may land on ink"


def test_unbridged_gap_of_the_same_width_is_still_a_valid_cut():
    """Control: the guard looks at ink crossing the gap, not at its width.

    Same canvas, same gap, same barlines -- but cut in the middle, not
    crossing. There the cut is correct, and it has to keep happening.
    """
    canvas = _canvas(with_bridging_barlines=False)

    blocks, _cut_ys = find_system_blocks(canvas)

    assert len(blocks) == 4, (
        "with no barlines crossing it, the same gap does separate notation from tab"
    )
