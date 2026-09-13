"""In a multi-song video, the crossing from one song to the next is a
crossfade: the frames in between are mostly the background footage. If the
cursor wrap lands there, those frames form their own page group and composite
into a near-black rectangle that prints as a solid band in the PDF.

A tablature page is paper: mostly light. The ones that are not get flagged as
transitions and never become systems."""
import numpy as np

from tabextract.compose import compose_paginated
from tabextract.layout import build_systems_from_pages
from tabextract.region import Region

from .synthetic import REGION, make_frame
from .test_advance_stepwise_scroll import _MemoryCache


def _region():
    x0, y0, x1, y1 = REGION
    return Region(x0, y0, x1, y1)


def _video_with_crossfade_at_the_end() -> list[np.ndarray]:
    """Two real pages and then a fade to footage, with no paper."""
    x0, y0, x1, y1 = REGION
    width = x1 - x0
    frames = []
    for _page, measure in enumerate((1, 6)):
        for step in range(8):
            cursor_x = int(step / 7 * (width - 30)) + 10
            frames.append(make_frame(measure, cursor_x=cursor_x, region=REGION))
    # Crossfade: the cursor wraps to the start and the tab is barely visible.
    for step in range(4):
        f = make_frame(11, cursor_x=10 + step, region=REGION)
        f[y0:y1, x0:x1] = (f[y0:y1, x0:x1] * 0.06).astype(np.uint8)
        frames.append(f)
    return frames


def test_crossfade_page_is_marked_and_never_becomes_a_system():
    frames = _video_with_crossfade_at_the_end()

    pages = compose_paginated(_MemoryCache(frames), _region())
    transitions = [p for p in pages if p.is_transition]

    assert transitions, "the crossfade page has to be detected"
    assert all(p.paper_fraction < 0.5 for p in transitions)
    assert all(p.paper_fraction > 0.5 for p in pages if not p.is_transition)

    bands = build_systems_from_pages(pages)
    assert len(bands) == len(pages) - len(transitions)


def test_last_real_page_is_treated_as_last_of_song():
    """If the transition page was the last one, the last REAL page must not be
    trimmed for overlap: there is no following page repeating its last bar."""
    pages = compose_paginated(_MemoryCache(_video_with_crossfade_at_the_end()), _region())

    bands = build_systems_from_pages(pages)

    assert bands[-1].is_last_of_song
    assert bands[-1].trimmed_fraction == 0.0
