<div align="center">

# TabXtract

**Extracts guitar and bass tablature from video and rebuilds it as a printable PDF.**

[Download](https://reyiyo.github.io/tabxtract) ·
[How it works](ARCHITECTURE.md) ·
[Contributing](CONTRIBUTING.md)

[![CI](https://github.com/reyiyo/tabxtract/actions/workflows/ci.yml/badge.svg)](https://github.com/reyiyo/tabxtract/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

</div>

---

## Built with AI

TabXtract was developed with AI assistance. The pipeline was prototyped, and the
application, tests and documentation were written, in collaboration with AI agents. A human directed the work, chose the approach at each decision point, and
reviewed the output.

This is stated here so you know what you're reading and running. Apply whatever scrutiny
you think that warrants. The source, the tests and the CI builds are all public.

## What it does

Some tablature is only published as video: the score scrolls or flips past while someone
plays along. TabXtract reads the notation off the video frames and reassembles it into an
A4 PDF for printing.

It runs locally. There is no upload, no account and no server.

## How it approaches the problem

The pipeline does not parse musical notation. It has no representation of a fret, a string
or a time signature. It locates a region of the frame, detects when the content advances,
removes duplicate frames, and lays the result out on a page.

Two consequences follow:

- **The instrument doesn't affect the code path.** Four-string bass, six-string guitar,
  ukulele and drum notation are processed identically. There is no per-instrument logic.
- **The output reproduces the notation in the video** rather than generating a new
  transcription, so it cannot disagree with the source.

## Features

- Reads a local video file, or downloads one from a URL with yt-dlp — quality is chosen
  before the download starts, and the download is cancellable.
- Handles score that scrolls vertically, scrolls horizontally, or advances page by page.
  The mode is detected from the video.
- Splits multi-song videos into one PDF per song.
- Removes the playback cursor from the output. Detection is structural, so it does not
  depend on the cursor's colour.
- Reports verification metrics for each extraction: bar-number continuity, frame coverage,
  page-cut safety.
- Allows manual correction of the detected region by dragging a rectangle.
- Keeps a local job history, so a run can be repeated without hunting for the video again.
- Saves layout profiles per video source; they export and import as JSON, so a profile that
  works for a particular channel can be shared through an issue.
- Includes a CLI. The engine is a standalone Python package.

## Install

Builds are on the [landing page](https://reyiyo.github.io/tabxtract) or the
[releases page](https://github.com/reyiyo/tabxtract/releases/latest).

| Platform | File |
|---|---|
| macOS, Apple Silicon | `..._aarch64.dmg` |
| macOS, Intel | `..._x64.dmg` |
| Windows | `-setup.exe` |
| Linux | `.AppImage` or `.deb` |

There are two macOS builds rather than one universal binary. The Python engine ships as a
frozen bundle, and a frozen bundle is per-architecture — a universal app would carry an
engine that only runs on half the Macs it installs on.

### Opening an unsigned build

TabXtract is distributed without a code-signing certificate on macOS or Windows. Those
certificates cost several hundred dollars a year, and this project doesn't buy them. As a
result both operating systems show a warning the first time you open the app. The steps
below are how you get past it.

Every binary is built by public CI directly from the tagged source in this repository. The
build log for any release is visible on the Actions tab.

**macOS.** The app is not notarised, so macOS blocks it the first time.

1. Open the `.dmg` and drag TabXtract to **Applications**.
2. Double-click it. macOS will say it can't be opened — close that dialog.
3. Open **System Settings → Privacy & Security**, scroll down to the message about
   TabXtract and click **Open Anyway**. Confirm with your password if asked.
4. From then on it opens normally.

If macOS instead says the app is *damaged and can't be opened*, that is the same block in
a different costume. Open the Terminal app, paste this line and press Enter, then try
again:

```bash
xattr -dr com.apple.quarantine /Applications/TabXtract.app
```

**Windows.** SmartScreen shows *"Windows protected your PC"*.

1. Click **More info**.
2. Click **Run anyway**.

Your browser may also warn about the download itself; choose Keep.

**Linux.** No signing warning. AppImages need the executable bit:

```bash
chmod +x TabXtract-*.AppImage
./TabXtract-*.AppImage
```

### CLI only

The engine is a standalone Python package and does not need the desktop app:

```bash
pip install tabextract
tabextract analyze video.mp4 --workdir ./work
tabextract render video.mp4 --workdir ./work
```

`analyze` prints the detected region, advance mode and song boundaries as JSON; `render`
runs the whole pipeline and writes the PDFs under `./work/output`. Requires `ffmpeg` on
your `PATH`, and `tesseract` for the bar-number check (without it that one check reports
as unavailable and everything else still runs).

The distribution is named `tabextract` — the application is TabXtract, the Python package
kept its original name so existing installs and imports keep working.

### Updating

TabXtract checks for a new version when it starts and asks before installing it. You can
turn that check off in **Preferences**. To update by hand, download the new version from
the same place and install it over the old one; your history, profiles and preferences
are kept.

## Quick start

1. Open TabXtract and select a video file, or paste a URL.
2. Wait for analysis. The review screen shows the detected tab region, the advance mode
   and the page count.
3. Correct the region or the song boundaries if they're wrong.
4. Generate, then read the verification report.

## Verification

Failures in this pipeline are silent: a run can drop pages and still produce a PDF that
looks complete.

This happened during development. A page deduplicator based on image similarity reduced a
song from 10 pages to 6, because a repeated riff made consecutive pages pixel-identical.
The output showed no visible defect. It was found by noticing an inconsistent number in a
log.

Each run therefore reports:

- **Bar-number continuity** — bar numbers are OCR'd and gaps are flagged. A backwards jump
  is reported separately from a forward gap, since it usually indicates a repeat rather
  than a fault.
- **Frame coverage** — how many frames contributed to each composited region. Low coverage
  is flagged.
- **Overlap check** — whether consecutive frames overlapped enough that no content fell
  between them.
- **Cut safety** — whether any page break landed on a staff.

Check the report before printing.

## Limitations

- **Output quality is bounded by source resolution.** Below roughly 800px of tab width,
  results degrade. Upscaling does not recover detail that isn't in the source.
- **Image output only.** There is no ASCII tab, Guitar Pro or MusicXML export. OCR of fret
  digits from compressed video produces errors that are not localisable by the reader.
- **No audio transcription.** TabXtract processes the image; it does not analyse the
  audio track.
- Unusual or heavily stylised notation may require the manual region override.

## Legal

TabXtract is intended for personal use on material you have the right to use.

Tablature is frequently copyrighted, and some transcriptions are commercial products.
Downloading from video platforms may conflict with their terms of service depending on
jurisdiction and circumstances. You are responsible for what you process with this tool.
It has no sharing features and no mechanism for extracted content to leave your machine.

## Reporting a problem

You don't need to know anything technical to report a problem; the forms guide you.

- **The PDF came out wrong** (missing pages, repeated bars, cut staves, wrong area of the
  video): use the [extraction failure form](https://github.com/reyiyo/tabxtract/issues/new?template=extraction_failure.yml).
  It asks for the verification report shown on the results screen — use its **Copy
  report** button.
- **The app crashed, froze, or a download failed**: use the
  [bug report form](https://github.com/reyiyo/tabxtract/issues/new?template=bug_report.yml).
  It asks for the log file: open **Preferences → Open data folder** and attach
  `tabxtract.log`. The same screen shows the app version.

Please don't attach the video itself if it isn't yours to share; a link or a description
of the layout is enough.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

Reports of videos the detector handles incorrectly are useful, since the pipeline was
developed against a limited set of layouts. Use the
[extraction failure template](https://github.com/reyiyo/tabxtract/issues/new?template=extraction_failure.yml).

[ARCHITECTURE.md](ARCHITECTURE.md) documents each pipeline stage and the failure modes
that shaped it.

## License

[GPL-3.0](LICENSE). Distributed derivative works must also be released under GPL-3.0 with
source.

Bundled components retain their own licenses: **ffmpeg** (GPL), **yt-dlp** (Unlicense),
**OpenCV** and **Tesseract** (Apache-2.0), **Tauri** (MIT/Apache-2.0).
