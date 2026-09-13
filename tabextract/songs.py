"""Failure mode 7 - Song segmentation inside a single video.

A multi-song video does not mark the boundaries in the tab: it marks them in
the title graphic overlaid on the footage, outside the detected region. The
area outside the region is signatured per frame and large discontinuities are
looked for; false positives from camera cuts are filtered by merging adjacent
segments whose title signature matches.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .region import Region
from .sampling import FrameCache

THUMB_SIZE = (64, 36)
BOUNDARY_Z = 4.0       # robust (MAD) outlier threshold for cut candidates
MERGE_FACTOR = 1.5     # relative threshold to merge segments with similar signatures
CLUSTER_GAP_FRAMES = 4  # one transition (fade or camera cut) can push several
                         # consecutive frames over the threshold; they count
                         # as a single candidate
MIN_SEGMENT_FRAMES = 20  # ~10s at 2fps: shorter than that is transition noise,
                          # not a real song (title card, camera blip)

# The MAD z-score is purely RELATIVE: it measures how far a frame departs
# from the typical variation, no matter how small that variation is. When
# nothing outside the region really moves (a screen capture of a web app,
# where the only external element is a near-static playback bar), the typical
# variation is compression noise and ANY flicker becomes a huge outlier, so
# the detector invents songs where there is one.
#
# This absolute floor is the counterweight: a real song boundary changes a
# substantial part of the outside area (title card, camera cut). Measured on
# the test videos, in units of "mean delta per channel per thumbnail pixel"
# (0-255): real transitions 35-69, UI noise 0.07-0.61. The floor sits two
# orders of magnitude in between, so it does not disturb the already
# validated case, where even frames WITHOUT a transition clear it easily.
MIN_BOUNDARY_DELTA = 3.0


@dataclass
class SongSegment:
    index: int
    start_frame: int
    end_frame: int  # inclusive


def _frame_signature(frame_bgr: np.ndarray, region: Region) -> np.ndarray:
    masked = frame_bgr.copy()
    x0, y0, x1, y1 = region.as_tuple()
    masked[y0:y1, x0:x1] = 0
    small = cv2.resize(masked, THUMB_SIZE, interpolation=cv2.INTER_AREA)
    return small.astype(np.float32).reshape(-1)


def _mad_z_scores(values: np.ndarray) -> np.ndarray:
    median = np.median(values)
    mad = np.median(np.abs(values - median)) + 1e-6
    return np.abs(values - median) / (1.4826 * mad)


def segment_songs(cache: FrameCache, region: Region) -> list[SongSegment]:
    n = len(cache)
    if n == 0:
        return []

    sigs = [_frame_signature(cache[i], region) for i in range(n)]
    dists = np.array([
        float(np.linalg.norm(sigs[i] - sigs[i - 1])) for i in range(1, n)
    ])
    if dists.size == 0:
        return [SongSegment(0, 0, n - 1)]

    z = _mad_z_scores(dists)
    # Normalised to "mean delta per channel per pixel" so the absolute floor
    # does not depend on the thumbnail size.
    normalized = dists / np.sqrt(sigs[0].size)
    outliers = np.nonzero((z > BOUNDARY_Z) & (normalized > MIN_BOUNDARY_DELTA))[0].tolist()
    if not outliers:
        return [SongSegment(0, 0, n - 1)]

    # Group consecutive peaks (one transition spread over several frames) and
    # keep the highest-z frame of each group as the real cut.
    clusters: list[list[int]] = []
    for idx in outliers:
        if clusters and idx - clusters[-1][-1] <= CLUSTER_GAP_FRAMES:
            clusters[-1].append(idx)
        else:
            clusters.append([idx])
    candidate_starts = [int(max(cl, key=lambda i: z[i])) + 1 for cl in clusters]

    bounds = [0] + candidate_starts + [n]
    bounds = sorted(set(bounds))

    # Representative signature per segment: the median, robust to one odd frame.
    def rep_sig(a: int, b: int) -> np.ndarray:
        return np.median(np.stack(sigs[a:b]), axis=0)

    merge_thresh = MERGE_FACTOR * float(np.median(dists))

    changed = True
    while changed and len(bounds) > 2:
        changed = False
        for i in range(1, len(bounds) - 1):
            left = rep_sig(bounds[i - 1], bounds[i])
            right = rep_sig(bounds[i], bounds[i + 1])
            if float(np.linalg.norm(left - right)) < merge_thresh:
                bounds.pop(i)
                changed = True
                break

    # Camera-cut false positives (failure mode 7) tend to survive the
    # signature merge when the "segment" they produce is itself very short (a
    # blip of a couple of frames): there is not enough signal for its
    # signature to resemble either neighbour. They get merged anyway, into
    # whichever neighbour is closest by signature, while any segment is
    # shorter than a plausible real song.
    while len(bounds) > 2:
        seg_lens = [bounds[i + 1] - bounds[i] for i in range(len(bounds) - 1)]
        shortest = int(np.argmin(seg_lens))
        if seg_lens[shortest] >= MIN_SEGMENT_FRAMES:
            break
        if shortest == 0:
            bounds.pop(1)
        elif shortest == len(seg_lens) - 1:
            bounds.pop(-2)
        else:
            cur = rep_sig(bounds[shortest], bounds[shortest + 1])
            left = rep_sig(bounds[shortest - 1], bounds[shortest])
            right = rep_sig(bounds[shortest + 1], bounds[shortest + 2])
            if float(np.linalg.norm(cur - left)) <= float(np.linalg.norm(cur - right)):
                bounds.pop(shortest)
            else:
                bounds.pop(shortest + 1)

    segments = [
        SongSegment(index=k, start_frame=a, end_frame=b - 1)
        for k, (a, b) in enumerate(zip(bounds, bounds[1:]))
    ]
    return segments
