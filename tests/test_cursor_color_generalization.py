"""Cursor detection must not assume a fixed colour channel. It has to work
the same with an orange cursor or a green one."""
import pytest

from tabextract.cursor import detect_cursor_x
from tabextract.region import Region

from .synthetic import REGION, make_frame


@pytest.mark.parametrize("color", [(0, 140, 255), (0, 200, 0)])  # BGR: orange, green
def test_cursor_detected_regardless_of_color(color):
    region = Region(*REGION)
    frame = make_frame(measure_start=1, cursor_x=300, cursor_color=color)
    found = detect_cursor_x(region.crop(frame))
    assert found is not None
    x, strength = found
    assert abs(x - 300) < 15
    assert strength > 0
