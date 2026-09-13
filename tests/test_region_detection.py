from tabextract.region import detect_region
from tabextract.sampling import FrameCache

from .synthetic import REGION, paginated_video, write_frames


def test_detects_stable_region_and_instrument(tmp_path):
    frames = paginated_video(n_pages=3, steps_per_page=5)
    paths = write_frames(frames, tmp_path / "frames")
    cache = FrameCache(paths)

    result = detect_region(cache, n_samples=15)

    x0, y0, x1, y1 = REGION
    r = result.region
    last_line_y = y0 + 20 + 3 * 30  # see synthetic.make_frame: 4 strings, gap 30, top y0+20
    # Tolerance: the algorithm crops tight to the group of lines plus fixed
    # padding, not to the arbitrary rectangle of the synthetic fixture -- it
    # only has to contain the whole staff without clipping it.
    assert abs(r.x0 - x0) < 15
    assert abs(r.x1 - x1) < 15
    assert r.y0 <= y0 + 25
    assert r.y1 >= last_line_y
    assert r.y1 <= y1
    assert result.instrument == "bass"
    assert result.n_lines == 4
    assert result.confidence > 0.5
    assert result.low_res_warning is False
