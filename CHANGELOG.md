# Changelog

Every published version and what changed in it. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versioning is
[semantic](https://semver.org/).

## [Unreleased]

### Fixed

- The job-progress WebSocket now notices that the client disconnected. It used to wait only
  on the next progress message, so closing a progress screen left the task and its
  subscription alive until the job published again — and forever for a job that did not.
  Those accumulated over a session, and uvicorn's graceful shutdown waited for them, which
  could turn closing the window into a sidecar that stayed. The shutdown is bounded too.

## [0.1.0] - first public release

### Added

- Desktop application for macOS (Apple Silicon and Intel), Windows and Linux. All
  processing happens on the user's machine: no upload, no server, no account.
- Computer-vision engine (`tabextract`) that locates the tablature region in a video,
  detects whether the score scrolls vertically, scrolls horizontally or advances page by
  page, removes the playback cursor by median compositing, splits multi-song videos and
  lays the result out on A4 pages. It also works as a standalone CLI (`tabextract analyze`,
  `tabextract render`).
- Verification report per run: bar-number continuity, frame coverage, overlap check and
  page-cut safety. Failures in this pipeline are silent, so they are measured explicitly.
- Manual correction of the detected region and of the song boundaries before generating.
- URL ingestion with yt-dlp: title, duration and available qualities are shown before
  downloading, the download can be cancelled, and the errors distinguish unavailable,
  age-restricted and private videos from an out-of-date yt-dlp. "Update yt-dlp" in
  Preferences fetches the official binary without waiting for a new release of the app.
- Native file picker and drag & drop.
- Job history, an output folder remembered between sessions, "show in file manager", and
  layout profiles that export and import as JSON so a working profile can be shared.
- Automatic updates against the GitHub releases, which can be turned off.
- A first-run legal notice.

### Security

- The backend is a local sidecar, frozen with PyInstaller, listening on `127.0.0.1` only
  with an OS-assigned ephemeral port and a random handshake token generated at startup.
  The token is compared in constant time; job ids are validated before they touch the
  file system. On Windows the port is bound exclusively, so another process cannot take
  it over.
- A pasted URL cannot be read by yt-dlp as an option: it is passed after `--`, only
  `http(s)` links are accepted, and yt-dlp's user config files are ignored.
- "Update yt-dlp" checks the downloaded binary against the release's `SHA2-256SUMS`
  before replacing the working copy.
- The bundled ffmpeg, yt-dlp and `eng.traineddata` are pinned to fixed versions and
  verified against SHA-256 digests recorded in `scripts/fetch_native_deps.py`.
- The frozen sidecar installs from a hashed lock (`requirements/sidecar.txt`), so what a
  release contains is reproducible and auditable.
- Workflows pin every action to a commit SHA, CI runs with a read-only token, and
  Dependabot keeps the pins current.
- Imported layout profiles are validated before being written.
- No telemetry: the only outbound requests are downloads the user asks for and the update
  check, which can be disabled.
