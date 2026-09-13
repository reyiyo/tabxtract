"""Shared geometric primitives: horizontal staff-line detection and 1D
clustering. Used by region.py (region detection plus instrument metadata) and
layout.py (tab staff, barlines, gaps between systems)."""
from __future__ import annotations

import cv2
import numpy as np

INK_THRESHOLD = 200  # not 128: staff lines are light grey, not black


def ink_mask(gray: np.ndarray, thresh: int = INK_THRESHOLD) -> np.ndarray:
    return gray < thresh


def horizontal_line_rows(gray: np.ndarray, min_frac: float = 0.5,
                          thresh: int = INK_THRESHOLD, close_gap: int = 15) -> np.ndarray:
    """Rows containing a long horizontal line (a staff line), isolated with a
    morphological open using a long horizontal kernel.

    A closing pass with a short kernel first joins the line across the fret
    numbers printed on top of it: without that, any digit sitting on the line
    breaks it into short segments and the open discards all of them, even
    though the line is real.
    """
    dark = (ink_mask(gray, thresh)).astype(np.uint8) * 255
    w = gray.shape[1]
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_gap, 1))
    closed = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, close_kernel)
    open_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 6, 1), 1))
    opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, open_kernel)
    row_frac = (opened > 0).sum(axis=1) / float(w)
    return row_frac >= min_frac


def close_short_gaps_1d(mask: np.ndarray, max_gap: int) -> np.ndarray:
    """Fill short runs of False surrounded by True (for example a barline a
    few pixels wide crossing a band of "paper") so they do not fragment a long
    run that is really continuous."""
    out = mask.copy()
    n = len(mask)
    i = 0
    while i < n:
        if not mask[i]:
            j = i
            while j < n and not mask[j]:
                j += 1
            if i > 0 and j < n and (j - i) <= max_gap:
                out[i:j] = True
            i = j
        else:
            i += 1
    return out


def cluster_1d(indices: list[int] | np.ndarray, max_gap: int) -> list[list[int]]:
    """Group sorted indices into clusters separated by gaps > max_gap."""
    idx = list(indices)
    if not idx:
        return []
    clusters = [[idx[0]]]
    for v in idx[1:]:
        if v - clusters[-1][-1] <= max_gap:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return clusters


def staff_line_groups(gray: np.ndarray, line_merge_gap: int = 3,
                       staff_gap: int = 40, min_frac: float = 0.5,
                       thresh: int = INK_THRESHOLD) -> list[dict]:
    """Detect groups of parallel lines (staves/tablature) in `gray`.

    Returns a list of {top, bottom, n_lines, line_centers} dicts, one per
    group found, ordered top to bottom. `n_lines` is how many parallel lines
    the group has (4=bass, 6=guitar, 5=standard staff) and is metadata only:
    it never branches the processing.
    """
    is_line = horizontal_line_rows(gray, min_frac=min_frac, thresh=thresh)
    candidate_rows = np.nonzero(is_line)[0].tolist()
    if not candidate_rows:
        return []

    # Step 1: merge contiguous rows of one thick line into its centre.
    line_clusters = cluster_1d(candidate_rows, max_gap=line_merge_gap)
    line_centers = [int(round(sum(c) / len(c))) for c in line_clusters]

    # Step 2: group lines that are close together (the same staff).
    staff_clusters = cluster_1d(line_centers, max_gap=staff_gap)

    groups = []
    for cl in staff_clusters:
        groups.append({
            "top": cl[0],
            "bottom": cl[-1],
            "n_lines": len(cl),
            "line_centers": cl,
        })
    return groups


def infer_instrument(n_lines: int) -> str:
    return {4: "bass", 6: "guitar", 5: "staff"}.get(n_lines, f"{n_lines} lines")
