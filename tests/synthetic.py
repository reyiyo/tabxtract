"""Synthetic frame generator for the tests, with no dependency on ffmpeg or
real videos. It simulates a 4-string (bass) tablature inside a frame with
colourful "chrome" around it, like a real screen capture."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

FRAME_W, FRAME_H = 960, 540
REGION = (60, 150, 900, 330)  # x0,y0,x1,y1 - a 4-line bass staff
N_STRINGS = 4
STRING_GAP = 30


def _chrome_background(seed: int) -> np.ndarray:
    """Performance footage plus UI chrome: colourful and varied in brightness,
    unlike paper, which is near-white and low saturation. A wide value range
    avoids uniform dark streaks that the horizontal-line detector could
    mistake for a staff."""
    rng = np.random.default_rng(seed)
    frame = rng.integers(0, 256, size=(FRAME_H, FRAME_W, 3), dtype=np.uint8)
    frame[:, :, 2] = np.clip(frame[:, :, 2].astype(int) + 60, 0, 255).astype(np.uint8)  # saturated red tint
    return frame


def make_frame(measure_start: int, n_measures: int = 5, cursor_x: int | None = None,
               cursor_color=(0, 140, 255), title_seed: int = 0, region=REGION) -> np.ndarray:
    x0, y0, x1, y1 = region
    frame = _chrome_background(title_seed)
    frame[y0:y1, x0:x1] = 255  # white paper

    string_top = y0 + 20
    for s in range(N_STRINGS):
        y = string_top + s * STRING_GAP
        cv2.line(frame, (x0 + 10, y), (x1 - 10, y), (180, 180, 180), 2)

    staff_bottom = string_top + (N_STRINGS - 1) * STRING_GAP
    measure_w = (x1 - x0 - 40) // n_measures
    for m in range(n_measures + 1):
        bx = x0 + 20 + m * measure_w
        cv2.line(frame, (bx, string_top - 4), (bx, staff_bottom + 4), (0, 0, 0), 3)
        if m < n_measures:
            for s in range(N_STRINGS):
                y = string_top + s * STRING_GAP
                cv2.putText(frame, "3", (bx + measure_w // 2 - 6, y + 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    cv2.putText(frame, str(measure_start), (x0 + 5, string_top - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

    if cursor_x is not None:
        cx = x0 + int(cursor_x)
        cv2.rectangle(frame, (cx, y0 + 5), (cx + 10, y1 - 5), cursor_color, -1)

    return frame


def write_frames(frames: list[np.ndarray], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, f in enumerate(frames):
        p = out_dir / f"frame_{i:06d}.png"
        cv2.imwrite(str(p), f)
        paths.append(p)
    return paths


def paginated_video(n_pages: int, measures_per_page: int = 5, steps_per_page: int = 6,
                     region=REGION, duplicate_pages: set[int] | None = None,
                     cursor_color=(0, 140, 255)) -> list[np.ndarray]:
    """Simulate a paged video: `n_pages` pages, each with a cursor sweeping
    left to right and then wrapping as the next one starts. `duplicate_pages`
    forces those pages to use the same measure_start as the previous one (a
    repeated riff, failure mode 1: visually identical content)."""
    duplicate_pages = duplicate_pages or set()
    x0, y0, x1, y1 = region
    width = x1 - x0
    frames = []
    measure = 1
    last_measure_used = 1
    for page in range(n_pages):
        if page in duplicate_pages:
            m_start = last_measure_used
        else:
            m_start = measure
            last_measure_used = measure
            measure += measures_per_page
        for step in range(steps_per_page):
            cursor_x = int((step / max(steps_per_page - 1, 1)) * (width - 30)) + 10
            frames.append(make_frame(m_start, measures_per_page, cursor_x=cursor_x,
                                      cursor_color=cursor_color, region=region))
    return frames


def scrolling_video(n_steps: int, dy_per_step: int = 12, region=REGION) -> list[np.ndarray]:
    """Simulate vertical scroll: a tall canvas is generated once with
    increasing bar numbers, and an advancing window is cropped out of it."""
    x0, y0, x1, y1 = region
    width = x1 - x0
    height = y1 - y0
    total_h = height + n_steps * dy_per_step
    tall = np.full((total_h, width, 3), 255, dtype=np.uint8)

    band_h = 90
    n_bands = total_h // band_h + 2
    for b in range(n_bands):
        top = b * band_h
        if top + N_STRINGS * STRING_GAP + 20 > total_h:
            break
        st = top + 20
        for s in range(N_STRINGS):
            yy = st + s * STRING_GAP
            if yy < total_h:
                cv2.line(tall, (10, yy), (width - 10, yy), (180, 180, 180), 2)
        cv2.putText(tall, str(b + 1), (5, max(st - 8, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    frames = []
    for i in range(n_steps):
        off = i * dy_per_step
        crop = tall[off:off + height, :]
        frame = _chrome_background(seed=1)
        frame[y0:y1, x0:x1] = crop
        frames.append(frame)
    return frames


def stepwise_scrolling_video(n_steps: int, dy_per_jump: int = 90, hold: int = 6,
                             region=REGION) -> list[np.ndarray]:
    """Stepwise scroll: the view stays still for `hold` frames and then jumps
    `dy_per_jump` at once.

    This is how a tablature web app advances: nothing moves while the cursor
    sweeps a system, and it only scrolls once the cursor reaches the bottom.
    The median |dy| of this signal is 0 -- most pairs are identical -- so a
    classifier looking only at the median mistakes it for a paged video.
    """
    x0, y0, x1, y1 = region
    width, height = x1 - x0, y1 - y0
    n_jumps = n_steps // hold + 2
    total_h = height + n_jumps * dy_per_jump
    tall = np.full((total_h, width, 3), 255, dtype=np.uint8)

    band_h = 90
    for b in range(total_h // band_h + 2):
        st = b * band_h + 20
        if st + N_STRINGS * STRING_GAP > total_h:
            break
        for s in range(N_STRINGS):
            cv2.line(tall, (10, st + s * STRING_GAP), (width - 10, st + s * STRING_GAP),
                     (180, 180, 180), 2)
        cv2.putText(tall, str(b + 1), (5, max(st - 8, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)

    frames = []
    for i in range(n_steps):
        off = (i // hold) * dy_per_jump
        frame = _chrome_background(seed=1)
        frame[y0:y1, x0:x1] = tall[off:off + height, :]
        frames.append(frame)
    return frames
