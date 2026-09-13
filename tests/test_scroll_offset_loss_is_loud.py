"""If the displacement estimator cannot measure a frame pair and the content
is assumed not to have moved, content is lost silently: the accumulated jumps
get SMALLER, so `check_overlap_scroll` -- which looks for jumps that are TOO
LARGE -- passes happily and the PDF comes out pretty with a piece missing.
This domain prefers a loud failure to a pretty output."""

from tabextract.compose import ScrollOffsets, compute_scroll_offsets
from tabextract.region import Region
from tabextract.verify import check_overlap_scroll

from .synthetic import REGION, stepwise_scrolling_video
from .test_advance_stepwise_scroll import _MemoryCache


def test_unmeasurable_pair_is_reported_even_though_jumps_look_fine():
    # The offsets grow slowly: no jump exceeds the visible window.
    offsets = ScrollOffsets(values=[0, 50, 100, 100, 150], unresolved=[2])

    check = check_overlap_scroll(offsets, window=400)

    assert check.max_jump < check.window, (
        "the test has to exercise the case where the jump check passes"
    )
    assert not check.ok, "an unmeasured pair is possibly lost content"
    assert check.unresolved_pairs == [2]
    assert "no measurable displacement" in check.message


def test_clean_offsets_still_pass():
    check = check_overlap_scroll(ScrollOffsets(values=[0, 50, 100, 150]), window=400)

    assert check.ok
    assert check.message == "ok"


def test_stepwise_scroll_offsets_recover_every_jump():
    """The accumulated total has to equal the real sum of the jumps, with
    none of them pinned at 0."""
    dy, hold, n = 90, 6, 72
    frames = stepwise_scrolling_video(n_steps=n, dy_per_jump=dy, hold=hold)
    x0, y0, x1, y1 = REGION

    offsets = compute_scroll_offsets(_MemoryCache(frames), Region(x0, y0, x1, y1))

    expected = ((n - 1) // hold) * dy
    assert offsets.values[-1] == expected, (
        f"expected {expected}px accumulated, measured {offsets.values[-1]}"
    )
    assert offsets.unresolved == []
