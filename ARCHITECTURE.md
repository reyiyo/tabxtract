# Architecture

This document describes how TabXtract works and why each stage is built the way it is.

Most of the non-obvious decisions come from failure modes encountered during development,
recorded in the "Failure modes" section. Several of them are what you get from the
straightforward implementation of the stage they belong to, so it's worth reading that
section before modifying the pipeline.

---

## Layout

```
tabextract/           CV engine. No Tauri, no FastAPI, no HTTP.
  sampling.py           Frame extraction via ffmpeg
  region.py             Tab region detection
  advance.py            Advance-mode classification
  cursor.py             Playback cursor detection
  compose.py            Median compositing
  songs.py              Song boundary segmentation
  layout.py             System splitting and A4 page packing
  geometry.py           Shared ink/line/gap primitives
  profiles.py           Saved per-source layout profiles
  verify.py             Verification and confidence reporting
  binaries.py           Resolves ffmpeg/tesseract from the environment
  cli.py                Standalone CLI
server/               FastAPI layer. Binds to 127.0.0.1 only, token-gated.
  __main__.py           Sidecar entry point: ephemeral port + handshake
  runner.py             Thread pools, cancellation, output publishing
  db.py                 SQLite job history
  ytdlp.py              URL ingestion
src/                  React frontend
src-tauri/            Tauri shell, sidecar lifecycle
scripts/              PyInstaller build, native dependency fetch
tests/                Engine tests
docs/                 GitHub Pages landing
```

`tabextract/` imports nothing from `server/` or `src-tauri/`. This separation is what allows
the engine to be used as a library or CLI without the application, and to be repackaged
(CLI, wheel, frozen sidecar) without touching it. The dependency runs one
way: `server/` imports the engine, never the reverse.

The Python distribution is `tabextract`; the application is TabXtract. Only the engine is
published to PyPI — `server/` lives in this repository but is not part of the wheel.

---

## Design constraint

The pipeline does not interpret musical notation. It has no representation of a fret
number. It crops a region, detects when content advances, deduplicates, and lays out the
result.

This means there is no per-instrument code path. A condition on instrument type indicates
that notation-level knowledge has entered the pipeline, which the rest of the design does
not account for. Staff line counts are used as display metadata only.

---

## Pipeline

### 1. Sampling

ffmpeg extracts frames at **2 fps** at native resolution.

2 fps rather than 1 for the reason in Failure mode 1. Higher rates increase compositing
cost linearly, and 2 fps already yields 20-35 contributing frames per region.

### 2. Region detection

Locate the stable rectangle containing the tablature:

- Near-white, low saturation. Notation is dark on light; performance footage and UI chrome
  are not.
- Contains groups of parallel horizontal lines, isolated with a morphological open using a
  long horizontal kernel.
- Stable across the video — sample ~40 frames spread out and take the **median of each
  edge**, with confidence being the fraction of samples that agree with it.

Intersecting the per-frame boxes instead, which is the obvious way to combine them, does
not work: ink coverage varies frame to frame, so the intersection converges on the
worst-case box rather than the fixed rectangle. That was measured, not theorised — it
returned `y:93-220` for a strip whose real extent was `y:0-291`.

Counting lines per group indicates the instrument (4 = bass, 6 = guitar, 5 = standard
staff). Display metadata only.

### 3. Advance-mode classification

`cv2.phaseCorrelate` between consecutive frames, restricted to the detected region, yields
`(dx, dy)`:

| Signal | Mode | Strategy |
|---|---|---|
| \|dy\| dominant | vertical scroll | panorama stitch |
| \|dx\| dominant | horizontal scroll | horizontal stitch |
| both ≈ 0, periodic discontinuities | paged | page dedup |

The paged case is easy to overlook. In one test video `dx` was 0 for 380 of 398 frame
pairs: the score does not move, it swaps.

### 4. Cursor detection

Cursor colour varies between sources — orange and green have both been observed — so
colour is not used for detection.

Detect structurally: a narrow vertical band of anomalous saturation relative to its local
background, moving monotonically and wrapping back to the left.

The cursor also supplies the page-advance signal in paged mode, which is the only reliable
source for it (Failure mode 1).

### 5. Compositing

**Per-pixel median across every frame covering a region.** The median makes no colour
assumptions and removes the playback cursor, note highlights and misaligned frames in a
single pass.

Scroll mode: accumulate offsets, process in ~200-row bands, take the median of frames
covering each band completely.

Paged mode: group frames by page via cursor wrap, take the median of the group, discarding
the first and last frame — those are partially rendered transitions.

Below 3 contributors, fall back to per-pixel max and mark the region low-confidence.

### 6. Layout

- Cut at the centre of blank gaps, not through a staff.
- The gap threshold is derived from the data (Failure mode 4).
- Scale every band in a song by the same factor, so bar width stays consistent across the
  document.
- A4 at 300 DPI (2480×3508), 1-bit bitonal.

---

## Failure modes

Each of these was encountered during development. All produced output with no visible
defect.

### 1. Deduplicating pages by image similarity drops content

Grouping frames by image hash reduced a 10-page song to 6. The song contained a repeated
riff, so consecutive pages were pixel-identical and were merged. Four pages of bars were
lost with no visible symptom.

**Handling:** in paged mode the advance signal is the cursor wrap, not content similarity.
A new page begins when `cursor_x[i] < cursor_x[i-1] - threshold`. This is independent of
content, so repeated material is handled correctly.

A regression test covers this: a synthetic video with N identical pages must yield N
pages. Removing that test removes coverage of silent page loss.

### 2. Per-pixel max propagates a single bad frame

Max erases a cursor darker than a white background, but a single misaligned frame
propagates into the result. In one case it left ghost glyphs over a staff in one bar of an
entire score.

**Handling:** median. With ~25 contributors a single outlier frame does not affect the
result. Median also renders highlighted notes as solid black, where max preserved them as
grey.

### 3. Pages overlap by a partial bar

In paged videos the right edge cuts a bar in half, and that bar reappears complete at the
start of the next page. Without correction the PDF repeats one bar per page.

**Handling:** detect barlines (columns where dark pixels cover ≥85% of the tab staff
height) and trim each band at its last barline, except the final page of each song.

If trimming would remove more than 45% of the width, barline detection has failed. Skip
the trim and mark low confidence.

### 4. Gap thresholds are not transferable

A 30px threshold worked in one video and not in another. Within a single video, each song
placed its staff on different rows (200-237, 213-263, 215-267), so calibrating on the first
song produced incorrect cuts in the rest.

**Handling:** the histogram of gap sizes is bimodal — small gaps within a staff, larger
gaps between systems. Apply Otsu or 2-means to the sizes and use the split point. Staff
rows are detected per band rather than once per video.

### 5. Detection on the binarised image introduces noise

Running gap detection on the sharpened and thresholded image introduced stray pixels that
changed the result: 37 systems were merged into 31.

**Handling:** detection runs on the raw greyscale canvas. Binarisation happens at render
time only.

### 6. Upscaling does not recover detail

A 360p source upscaled 3× to fill A4 was unreadable. The same video at 1080p, requiring
1.36× scaling, was legible.

**Handling:** warn when the detected tab region is under ~800px wide. Source resolution
determines the ceiling; output DPI does not raise it.

### 7. Song boundaries are not in the notation

In a multi-song video, boundaries are marked by the title graphic overlaid on the
performance footage, not by anything in the score.

**Handling:** signature the area outside the tab region and look for discontinuities. Camera
cuts produce false positives — in one video, 7 candidate boundaries corresponded to 5
songs. Merge adjacent segments with matching title signatures, and have the user confirm.

### 8. Pillow PDF output

Pillow may have no JPEG encoder available, in which case `save_all=True` for PDF fails with
`KeyError: 'JPEG'` in mode `"L"`. Saving in mode `"1"` avoids this and is also appropriate
for printed notation: black lines without intermediate greys.

---

## Desktop specifics

The Python backend runs as a PyInstaller-frozen sidecar launched by Tauri. It is frozen in
**onedir** mode and shipped as a bundle resource, not as `externalBin`: that list only
takes single files, and onefile — which would fit — re-extracts the whole bundle on every
launch, which is what onedir exists to avoid.

Because the sidecar is a frozen bundle, it cannot be made universal on macOS. There are two
macOS builds, one per architecture, each carrying its own engine.

Details that are load-bearing:

- **Ephemeral port.** The sidecar binds port 0, the OS assigns a free port, and it is
  printed to stdout for Tauri to read. A fixed port can collide and is reachable by
  anything else on the machine.
- **Handshake token.** The sidecar generates a random token at startup and rejects requests
  without it. Without this, any web page open in the user's browser could issue requests to
  the local backend.
- **Binds `127.0.0.1` only**, not `0.0.0.0`.
- **Lifecycle.** The sidecar is terminated on window close, including abrupt exits, to
  avoid leaving an orphaned Python process consuming CPU.

`ffmpeg` is bundled, but a system installation on `PATH` takes precedence. The Tauri shell
does the resolution and passes the result to the engine as an environment variable, so the
engine itself stays free of packaging knowledge.

`yt-dlp` is deliberately **not** frozen into the bundle, because YouTube breaks it every
few weeks and users need to update it without waiting for a release. It ships as the
official standalone binary and is resolved in this order: a copy in the app data
directory, then the bundled one, then `PATH`. "Update yt-dlp" writes to the app data
directory, which is writable — the application bundle is not, on macOS or Windows. Running
from source instead of a frozen build, the same button uses `pip install -U yt-dlp`.

Tesseract is used for bar-number OCR in verification. `eng.traineddata` comes from
`tessdata_fast`; `osd.traineddata` handles orientation and script detection and is not
included. If tesseract cannot be found at all, that one check reports as unavailable and
the rest of the pipeline runs unchanged — a missing OCR binary must not cost the user
their PDF.

---

## Testing

- **Unit tests** per stage against synthetic frames — deterministic, and they cover the
  failure modes above.
- **Golden-file tests** on short real clips, comparing verification reports rather than
  pixels. Pixel comparison is unstable across ffmpeg versions.
- The identical-pages test covers Failure mode 1.

When adding support for a new layout, add a short clip and its expected report.
