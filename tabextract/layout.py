"""Stage 6 - Layout and cutting.

Cuts the composited canvas into systems (staff lines), corrects the overlap
between pages (failure mode 3), scales the whole song by a single factor and
builds bitonal A4 sheets.

Everything that measures "is this a gap / a barline" always works on the raw
greyscale canvas (failure mode 5): binarisation happens only at the end, in
`render_song`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

from .compose import PageComposite

GAP_INK_ROW_THRESHOLD = 128       # per-row ink threshold, on the raw canvas
STAFF_LINE_MIN_FRAC = 0.6         # fraction of the width for a row to count as a line
STAFF_GROUP_GAP = 40              # separation between distinct groups of lines
BARLINE_HEIGHT_FRAC = 0.85        # a column inked over >=85% of the staff height is a barline
MAX_TRIM_FRACTION = 0.45          # failure mode 3 guard: never trim more than 45% of the width
MIN_INK_PER_BLOCK = 300           # drops near-empty blocks (margins) after cutting at gaps
BRIDGE_ROW_FRAC = 0.9             # a column "bridges" a gap when inked on >=90% of its rows
MIN_BRIDGE_COLUMNS = 2            # a single column could be noise; see _gap_is_bridged

PAGE_W, PAGE_H, MARGIN = 2480, 3508, 120   # A4 @ 300 DPI
HEADER_H = 110
BAND_GAP = 30
FINAL_THRESHOLD = 195


@dataclass
class SystemBand:
    image: np.ndarray
    origin_frame_range: tuple[int, int] | None = None
    is_last_of_song: bool = False
    low_confidence: bool = False
    trimmed_fraction: float = 0.0
    barline_cut_x: int | None = None


@dataclass
class LayoutResult:
    scale: float
    pages: list[np.ndarray]           # A4 sheets, uint8 greyscale (pre-binarisation)
    bands: list[SystemBand]           # scaled systems, in order
    page_gap_cuts: list[int] = field(default_factory=list)


def contiguous_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs = []
    start = None
    for i, v in enumerate(mask.tolist() + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    return runs


def otsu_threshold_1d(values: np.ndarray) -> float:
    """Classic Otsu over a histogram of 1D values (gap sizes)."""
    values = np.asarray(values, dtype=np.float64)
    if values.size < 2 or np.allclose(values.min(), values.max()):
        return float(values.max()) if values.size else 0.0

    hist, edges = np.histogram(values, bins=min(64, max(8, values.size)))
    centers = (edges[:-1] + edges[1:]) / 2
    total = hist.sum()
    sum_all = (hist * centers).sum()

    best_thr, best_var = centers[0], -1.0
    w0, sum0 = 0.0, 0.0
    for h, c in zip(hist, centers):
        w0 += h
        if w0 == 0 or w0 == total:
            continue
        sum0 += h * c
        w1 = total - w0
        m0 = sum0 / w0
        m1 = (sum_all - sum0) / w1
        var_between = w0 * w1 * (m0 - m1) ** 2
        if var_between > best_var:
            best_var, best_thr = var_between, c
    return float(best_thr)


def _gap_is_bridged(ink: np.ndarray, a: int, b: int) -> bool:
    """A gap crossed by continuous vertical strokes does NOT separate two
    systems: it joins them.

    In standard notation plus tab, the barline is drawn unbroken from the
    staff above to the tablature below, crossing the white space between them.
    That space is as wide as a real separation between systems, so Otsu picks
    it as a cut and splits one system in two (notation on top, tab below). The
    barline crossing it is precisely the typographic mark that both staves are
    a single system.

    It is counted with tolerance (>=90% of the gap's rows, not 100%) because
    the antialiasing of a compressed video can lighten the odd row of the
    barline above the ink threshold.
    """
    if b <= a:
        return False
    seg = ink[a:b, :]
    bridging = int((seg.mean(axis=0) >= BRIDGE_ROW_FRAC).sum())
    return bridging >= MIN_BRIDGE_COLUMNS


def find_system_blocks(canvas_gray: np.ndarray) -> tuple[list[tuple[int, int]], list[int]]:
    """Find the blocks (y0,y1) containing a system, cutting at the centre of
    each gap. The gap threshold is self-calibrating (failure mode 4): the
    histogram of gap sizes is bimodal, with gaps inside a staff on one side
    and real separations between systems on the other. Also returns the
    `cut_ys` (the gap centres used) so verify.py can confirm they land on
    white background."""
    h, w = canvas_gray.shape
    ink = canvas_gray < GAP_INK_ROW_THRESHOLD
    rows = ink.sum(axis=1)
    blank_row_thresh = max(3, int(0.02 * w))
    blank = rows < blank_row_thresh

    runs = contiguous_runs(blank)
    if not runs:
        return [(0, h)], []

    sizes = np.array([b - a for a, b in runs])
    min_gap = otsu_threshold_1d(sizes) if len(sizes) > 1 else 0

    real_gap_centers = [(a + b) // 2 for a, b in runs
                        if (b - a) >= min_gap and not _gap_is_bridged(ink, a, b)]
    cuts = sorted(set([0] + real_gap_centers + [h]))

    blocks = []
    for a, b in zip(cuts, cuts[1:]):
        if b <= a:
            continue
        block_ink = int(ink[a:b].sum())
        if block_ink > MIN_INK_PER_BLOCK:
            blocks.append((a, b))
    blocks = blocks or [(0, h)]

    # The reported cuts are only those separating two blocks with real ink: a
    # margin gap at the start or end of the canvas is not a cut.
    cut_ys = [(blocks[i][1] + blocks[i + 1][0]) // 2 for i in range(len(blocks) - 1)]
    return blocks, cut_ys


def tab_staff(band_gray: np.ndarray) -> tuple[int, int] | None:
    """The lowest cluster of horizontal lines is the tab staff."""
    from .geometry import cluster_1d, horizontal_line_rows

    h = band_gray.shape[0]
    is_line = horizontal_line_rows(band_gray, min_frac=STAFF_LINE_MIN_FRAC)
    cand = [y for y in np.nonzero(is_line)[0].tolist() if y < h - 16]
    if not cand:
        return None
    clusters = cluster_1d(cand, max_gap=STAFF_GROUP_GAP)
    low = clusters[-1]
    if low[-1] - low[0] >= 25:
        return low[0], low[-1]
    return None


def barlines(band_gray: np.ndarray) -> list[int]:
    """Columns where ink covers >=85% of the tab staff height are barlines."""
    st = tab_staff(band_gray)
    if st is None:
        return []
    y0, y1 = st
    h = y1 - y0 + 1
    col = (band_gray[y0:y1 + 1, :] < 200).sum(axis=0)
    cand = np.nonzero(col >= BARLINE_HEIGHT_FRAC * h)[0]
    if cand.size == 0:
        return []
    groups = []
    start = cand[0]
    prev = cand[0]
    for x in cand[1:]:
        if x - prev > 4:
            groups.append((start, prev))
            start = x
        prev = x
    groups.append((start, prev))
    return [int((a + b) // 2) for a, b in groups]


def trim_overlap(band_gray: np.ndarray, is_last_of_song: bool) -> tuple[np.ndarray, float, bool]:
    """Failure mode 3: the right edge of a paged page cuts a bar in half, and
    that bar reappears complete at the start of the next one. Trim at the last
    detected barline, unless this is the song's last page, which is left
    whole.

    Returns (trimmed_band, trimmed_fraction, low_confidence).
    """
    if is_last_of_song:
        return band_gray, 0.0, False

    bars = barlines(band_gray)
    w = band_gray.shape[1]
    if not bars:
        return band_gray, 0.0, False

    cut_x = bars[-1]
    trimmed_fraction = (w - cut_x) / w
    if trimmed_fraction > MAX_TRIM_FRACTION:
        # Detection probably failed: do not trim, flag low confidence.
        return band_gray, 0.0, True

    return band_gray[:, :cut_x], trimmed_fraction, False


def build_systems_from_scroll(canvas_gray: np.ndarray) -> tuple[list[SystemBand], list[tuple[int, int]], list[int]]:
    blocks, cut_ys = find_system_blocks(canvas_gray)
    bands = [SystemBand(image=canvas_gray[a:b]) for a, b in blocks]
    return bands, blocks, cut_ys


def build_systems_from_pages(pages: list[PageComposite]) -> list[SystemBand]:
    """Pages flagged as transitions (a crossfade between songs) are not
    systems, so they are skipped. `is_last_of_song` is computed over what
    remains, so the last REAL page is not trimmed for overlap."""
    usable = [p for p in pages if not p.is_transition]
    bands = []
    n = len(usable)
    for i, page in enumerate(usable):
        is_last = i == n - 1
        trimmed, frac, low_conf = trim_overlap(page.canvas, is_last)
        bars = barlines(page.canvas)
        bands.append(SystemBand(
            image=trimmed,
            origin_frame_range=page.frame_range,
            is_last_of_song=is_last,
            low_confidence=low_conf or page.low_confidence,
            trimmed_fraction=frac,
            barline_cut_x=bars[-1] if (bars and not is_last and not low_conf) else None,
        ))
    return bands


def layout_song(bands: list[SystemBand]) -> LayoutResult:
    """Scale every band of the song by the SAME factor and build A4 sheets."""
    content_w = PAGE_W - 2 * MARGIN
    max_w = max(b.image.shape[1] for b in bands)
    scale = content_w / max_w

    scaled_bands: list[SystemBand] = []
    for b in bands:
        h, w = b.image.shape
        nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
        blur = cv2.GaussianBlur(b.image, (0, 0), 1.2)
        sharp = cv2.addWeighted(b.image, 1.5, blur, -0.5, 0)
        resized = cv2.resize(sharp, (nw, nh), interpolation=cv2.INTER_CUBIC)
        scaled_bands.append(SystemBand(
            image=resized,
            origin_frame_range=b.origin_frame_range,
            is_last_of_song=b.is_last_of_song,
            low_confidence=b.low_confidence,
            trimmed_fraction=b.trimmed_fraction,
            barline_cut_x=None if b.barline_cut_x is None else int(b.barline_cut_x * scale),
        ))

    pages, cuts = _paginate(scaled_bands)
    return LayoutResult(scale=scale, pages=pages, bands=scaled_bands, page_gap_cuts=cuts)


def _paginate(bands: list[SystemBand]) -> tuple[list[np.ndarray], list[int]]:
    content_h = PAGE_H - 2 * MARGIN - HEADER_H
    pages: list[np.ndarray] = []
    cuts: list[int] = []

    cur_rows: list[np.ndarray] = []
    cur_h = 0
    for b in bands:
        bh = b.image.shape[0]
        extra = BAND_GAP if cur_rows else 0
        if cur_rows and cur_h + extra + bh > content_h:
            pages.append(_render_sheet(cur_rows))
            cuts.append(len(pages))
            cur_rows, cur_h = [], 0
            extra = 0
        cur_rows.append(b.image)
        cur_h += extra + bh

    if cur_rows:
        pages.append(_render_sheet(cur_rows))
    return pages, cuts


def _render_sheet(rows: list[np.ndarray]) -> np.ndarray:
    sheet = np.full((PAGE_H, PAGE_W), 255, dtype=np.uint8)
    y = MARGIN + HEADER_H
    for row in rows:
        h, w = row.shape
        x = MARGIN
        sheet[y:y + h, x:x + w] = row
        y += h + BAND_GAP
    return sheet


def render_song(title: str, layout: LayoutResult, out_path: str) -> None:
    """Binarise (bitonal, mode '1') and save the song's PDF.

    Mode '1' avoids PIL's KeyError: 'JPEG' in mode 'L' (failure mode 8) and is
    the right choice for printed notation anyway: crisp black lines, no greys.
    """
    sheets: list[Image.Image] = []
    for i, page in enumerate(layout.pages):
        _, bw = cv2.threshold(page, FINAL_THRESHOLD, 255, cv2.THRESH_BINARY)
        img = Image.fromarray(bw).convert("L")
        img = _draw_header(img, title, i + 1, len(layout.pages))
        sheets.append(img.convert("1"))

    sheets[0].save(out_path, save_all=True, append_images=sheets[1:], resolution=300.0)


def _draw_header(img: Image.Image, title: str, page_no: int, total_pages: int) -> Image.Image:
    from PIL import ImageDraw, ImageFont

    draw = ImageDraw.Draw(img)
    text = f"{title}  —  {page_no}/{total_pages}"
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 48)
    except OSError:
        font = ImageFont.load_default()
    draw.text((MARGIN, 40), text, fill=0, font=font)
    return img
