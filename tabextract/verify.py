"""Verification and confidence - a first-class requirement.

Every failure in this domain is silent: the PDF looks professional and is
missing four pages. This module implements the checks and assembles a report
with an overall score and the doubtful pages flagged. A loud failure beats a
pretty output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import cv2
import numpy as np
import pytesseract

from .advance import AdvanceMode
from .binaries import configure_tesseract
from .layout import GAP_INK_ROW_THRESHOLD, SystemBand
from .region import Region

if TYPE_CHECKING:  # avoids a circular import at runtime
    from .compose import ScrollOffsets

configure_tesseract()

OCR_CONFIG = "--psm 6 -c tessedit_char_whitelist=0123456789"
NUMBER_BAND_ABOVE_STAFF = 70   # height of the strip above the topmost staff
NUMBER_BAND_WIDTH = 300        # width to the right of the staff's left edge
NUMBER_BAND_LEFT_PAD = 30
GLYPH_MIN_H, GLYPH_MAX_H = 6, 34   # digit height; clefs and stems are taller
GLYPH_MIN_W, GLYPH_MAX_W = 3, 40
DIGIT_GAP = 30                 # maximum spacing between digits of one number
OCR_UPSCALE = 4                # tesseract reads much better with large glyphs
MIN_READ_FRACTION = 0.5        # below this the OCR has no standing to judge
MIN_CONTRIBUTORS = 3
DISCARDED_INK_WARN = 300
DISCARDED_INK_ERROR = 3000


@dataclass
class MeasureIssue:
    system_index: int
    kind: str  # "gap" | "backwards"
    from_measure: int
    to_measure: int


@dataclass
class MeasureContinuity:
    numbers: list[int | None]
    issues: list[MeasureIssue] = field(default_factory=list)
    summary: str = ""


@dataclass
class OverlapCheck:
    applicable: bool
    max_jump: float = 0.0
    window: float = 0.0
    ok: bool = True
    message: str = ""
    unresolved_pairs: list[int] = field(default_factory=list)


@dataclass
class VerificationReport:
    measure_continuity: MeasureContinuity
    low_confidence_systems: list[int]
    overlap: OverlapCheck
    cuts_on_ink: list[int]
    discarded_ink_by_block: list[int]
    discarded_ink_flag: str  # "ok" | "warn" | "error"
    score: float
    notes: list[str] = field(default_factory=list)


def read_measure_number(band_image: np.ndarray) -> int | None:
    """Read the bar number heading a system.

    The number is printed at the top left of the WHOLE system, that is, above
    the TOPMOST staff. Looking for it above the tab staff (the lower one in
    standard notation plus tab) lands in the middle of the notation and reads
    nothing: that is why this check used to report "no signal" on almost every
    song.

    Even with the crop in the right place, handing the whole strip to
    tesseract fails: the clef and the stems sticking out of the staff fall
    inside the crop and wreck its line segmentation. The number is isolated
    first via connected components -- they are small glyphs, unlike the clef --
    and the LEFTMOST group of digits is taken, because whatever appears
    further right at the same height is the tempo or a dynamic, not the bar.
    """
    crop = _measure_number_crop(band_image)
    if crop is None:
        return None

    glyphs = _digit_like_glyphs(crop)
    if not glyphs:
        return None

    x0, x1, y0, y1 = _leftmost_digit_cluster(glyphs)
    sub = crop[max(0, y0 - 6):y1 + 6, max(0, x0 - 6):x1 + 6]
    if sub.size == 0:
        return None

    sub = cv2.resize(sub, None, fx=OCR_UPSCALE, fy=OCR_UPSCALE, interpolation=cv2.INTER_CUBIC)
    sub = cv2.copyMakeBorder(sub, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)

    try:
        text = pytesseract.image_to_string(sub, config=OCR_CONFIG).strip()
    except (pytesseract.TesseractNotFoundError, pytesseract.TesseractError):
        # Without tesseract there is no bar continuity, but the rest of the
        # verification still holds. The report says so: one check fewer beats
        # a PDF that never gets made.
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _measure_number_crop(band_image: np.ndarray) -> np.ndarray | None:
    """The strip above the topmost staff, starting at its left edge."""
    from .geometry import horizontal_line_rows, ink_mask

    rows = np.nonzero(horizontal_line_rows(band_image, min_frac=0.6))[0]
    if rows.size == 0:
        return None
    top_staff = int(rows.min())

    cols = np.nonzero(ink_mask(band_image[top_staff]))[0]
    if cols.size == 0:
        return None
    staff_left = int(cols.min())

    y0 = max(0, top_staff - NUMBER_BAND_ABOVE_STAFF)
    x0 = max(0, staff_left - NUMBER_BAND_LEFT_PAD)
    x1 = min(band_image.shape[1], staff_left + NUMBER_BAND_WIDTH)
    crop = band_image[y0:top_staff, x0:x1]
    return crop if crop.size else None


def _digit_like_glyphs(crop: np.ndarray) -> list[tuple[int, int, int, int]]:
    mask = (crop < 200).astype(np.uint8)
    count, _labels, stats, _c = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = []
    for i in range(1, count):
        w = stats[i, cv2.CC_STAT_WIDTH]
        h = stats[i, cv2.CC_STAT_HEIGHT]
        if GLYPH_MIN_H <= h <= GLYPH_MAX_H and GLYPH_MIN_W <= w <= GLYPH_MAX_W:
            left = stats[i, cv2.CC_STAT_LEFT]
            top = stats[i, cv2.CC_STAT_TOP]
            out.append((int(left), int(left + w), int(top), int(top + h)))
    out.sort()
    return out


def _leftmost_digit_cluster(glyphs: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    cluster = [glyphs[0]]
    for g in glyphs[1:]:
        if g[0] - cluster[-1][1] > DIGIT_GAP:
            break
        cluster.append(g)
    return (min(g[0] for g in cluster), max(g[1] for g in cluster),
            min(g[2] for g in cluster), max(g[3] for g in cluster))


def check_measure_continuity(bands: list[SystemBand]) -> MeasureContinuity:
    """Read each system's bar number and check the sequence advances without
    holes. See `analyze_measure_sequence` for the criterion."""
    numbers = [read_measure_number(b.image) for b in bands]
    return analyze_measure_sequence(numbers)


def analyze_measure_sequence(numbers: list[int | None]) -> MeasureContinuity:
    """A system spans SEVERAL bars, not one.

    An earlier version only accepted `last + 1`, so a healthy progression like
    11 -> 18 -> 25 (seven bars per system) was reported as a gap at every
    system. The normal increment is not 1: it is whatever this song uses, and
    it is measured from the sequence itself.

    Three more things the OCR forces us to allow for:

    - The increment is normalised by how many systems separate two readings.
      If the numbers in between could not be read, the jump between the two
      that were read is legitimately larger.
    - A reading the sequence recovers from on its own is a misread, not
      missing content: it is not reported, and it does not become the
      reference for the next comparison either.
    - The first reading is validated against nothing, so the sequence starts
      at the first reading that is consistent with the next one.
    """
    known = [(i, n) for i, n in enumerate(numbers) if n is not None]
    issues: list[MeasureIssue] = []

    per_system = [(b - a) / (j - i)
                  for (i, a), (j, b) in zip(known, known[1:]) if b > a]
    typical = float(np.median(per_system)) if per_system else 1.0
    tolerance = max(2.0 * typical, typical + 4.0)

    start = 0
    for k in range(len(known) - 1):
        i, a = known[k]
        j, b = known[k + 1]
        if 0 <= b - a <= tolerance * max(1, j - i):
            start = k
            break

    accepted = known[start][1] if known else 0
    accepted_idx = known[start][0] if known else 0
    coherent: list[int] = [accepted] if known else []

    for pos in range(start + 1, len(known)):
        idx, num = known[pos]
        delta = num - accepted
        allowed = tolerance * max(1, idx - accepted_idx)

        if 0 <= delta <= allowed:
            accepted, accepted_idx = num, idx
            coherent.append(num)
            continue

        if pos + 1 < len(known):
            nxt_idx, nxt = known[pos + 1]
            if 0 <= nxt - accepted <= tolerance * max(1, nxt_idx - accepted_idx):
                continue

        # No content loss inside a song explains a jump of this magnitude:
        # these are glyphs the OCR ran together.
        if delta > 20 * allowed:
            continue

        kind = "backwards" if delta < 0 else "gap"
        issues.append(MeasureIssue(idx, kind, accepted, num))
        accepted, accepted_idx = num, idx
        coherent.append(num)

    # If the OCR could not read even half the systems, it is in no position to
    # judge continuity: its "gaps" would be its own noise, not missing content.
    # That is stated explicitly, rather than reporting false gaps (or staying
    # quiet, which would read as everything being fine).
    read_fraction = len(known) / len(numbers) if numbers else 0.0
    if numbers and read_fraction < MIN_READ_FRACTION:
        return MeasureContinuity(
            numbers=numbers, issues=[],
            summary=(f"unreliable OCR: only {len(known)} of {len(numbers)} systems "
                     "have a legible number, not enough to verify continuity"),
        )

    if not coherent:
        summary = "no bar number could be read (no OCR signal)"
    elif not issues:
        discarded = len(known) - len(coherent)
        extra = f" ({discarded} unreadable reading(s) discarded)" if discarded else ""
        summary = f"bars {coherent[0]}-{coherent[-1]}, no gaps{extra}"
    else:
        parts = [f"{'gap' if i.kind == 'gap' else 'repeat'} detected: {i.from_measure} -> {i.to_measure}"
                 for i in issues]
        summary = "; ".join(parts)

    return MeasureContinuity(numbers=numbers, issues=issues, summary=summary)


def check_overlap_scroll(offsets, window: int) -> OverlapCheck:
    """Two different ways to lose content in scroll mode.

    The first is a jump larger than the visible window: between two frames the
    content advanced further than fits on screen, and nobody saw what was in
    between.

    The second is the inverse and does not show up in `max_jump`: if the
    estimator could not measure a pair and its displacement was left at 0, the
    content is lost all the same, but the jumps get SMALLER and this check
    would pass happily. That is why unresolved pairs are reported separately.
    """
    unresolved = list(getattr(offsets, "unresolved", []))
    values = list(offsets)
    if len(values) < 2:
        return OverlapCheck(applicable=False, unresolved_pairs=unresolved)
    jumps = np.diff(np.array(values))
    max_jump = float(jumps.max()) if jumps.size else 0.0
    ok = max_jump < window and not unresolved
    if max_jump >= window:
        msg = (f"a {max_jump:.0f}px jump exceeds the visible window ({window}px): "
               "content was lost between frames, resample at a higher fps")
    elif unresolved:
        msg = (f"{len(unresolved)} frame pair(s) with no measurable displacement "
               f"(indices {unresolved[:5]}): the content of those jumps may be "
               "missing from the output with no visible trace")
    else:
        msg = "ok"
    return OverlapCheck(applicable=True, max_jump=max_jump, window=float(window),
                         ok=ok, message=msg, unresolved_pairs=unresolved)


def check_cuts_on_ink(canvas_gray: np.ndarray, cut_ys: list[int],
                       thresh: int = GAP_INK_ROW_THRESHOLD) -> list[int]:
    """Must come back empty: no system boundary should land on ink."""
    bad = []
    w = canvas_gray.shape[1]
    for y in cut_ys:
        if 0 <= y < canvas_gray.shape[0]:
            ink = int((canvas_gray[y] < thresh).sum())
            if ink > 0.01 * w:
                bad.append(y)
    return bad


def check_discarded_ink(canvas_gray: np.ndarray, blocks: list[tuple[int, int]],
                         thresh: int = GAP_INK_ROW_THRESHOLD) -> int:
    total_ink = int((canvas_gray < thresh).sum())
    kept_ink = sum(int((canvas_gray[a:b] < thresh).sum()) for a, b in blocks)
    return max(0, total_ink - kept_ink)


def build_report(bands: list[SystemBand], mode: AdvanceMode,
                  scroll_offsets: ScrollOffsets | list[int] | None, region: Region,
                  canvas_gray: np.ndarray | None, blocks: list[tuple[int, int]] | None,
                  cut_ys: list[int] | None) -> VerificationReport:
    continuity = check_measure_continuity(bands)

    low_conf = [i for i, b in enumerate(bands) if b.low_confidence]

    if mode == AdvanceMode.PAGINATED:
        overlap = OverlapCheck(applicable=False)
    else:
        window = region.height if mode == AdvanceMode.SCROLL_VERTICAL else region.width
        overlap = check_overlap_scroll(scroll_offsets or [], window)

    cuts_bad = check_cuts_on_ink(canvas_gray, cut_ys or []) if canvas_gray is not None else []

    discarded = check_discarded_ink(canvas_gray, blocks or []) if canvas_gray is not None else 0
    if discarded > DISCARDED_INK_ERROR:
        discarded_flag = "error"
    elif discarded > DISCARDED_INK_WARN:
        discarded_flag = "warn"
    else:
        discarded_flag = "ok"

    penalties = 0.0
    penalties += 15 * len(continuity.issues)
    penalties += 10 * len(low_conf)
    penalties += 25 if (overlap.applicable and not overlap.ok) else 0
    penalties += 20 * len(cuts_bad)
    penalties += {"ok": 0, "warn": 10, "error": 30}[discarded_flag]
    score = max(0.0, 100.0 - penalties)

    notes = []
    if any(i.kind == "gap" for i in continuity.issues):
        notes.append("unexplained bar-number gaps: check the neighbouring pages")
    if low_conf:
        notes.append(f"{len(low_conf)} system(s) with fewer than {MIN_CONTRIBUTORS} contributing frames")
    if overlap.applicable and not overlap.ok:
        notes.append(overlap.message)
    if cuts_bad:
        notes.append(f"{len(cuts_bad)} cut(s) land on ink")
    if discarded_flag != "ok":
        notes.append(f"{discarded} px of ink discarded outside every block ({discarded_flag})")

    return VerificationReport(
        measure_continuity=continuity,
        low_confidence_systems=low_conf,
        overlap=overlap,
        cuts_on_ink=cuts_bad,
        discarded_ink_by_block=[discarded],
        discarded_ink_flag=discarded_flag,
        score=round(score, 1),
        notes=notes,
    )
