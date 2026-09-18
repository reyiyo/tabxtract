# Contributing to TabXtract

## Reporting a video the detector handles incorrectly

The pipeline was developed against a limited set of layouts, so videos it fails on are
useful input. If TabXtract produces a wrong or incomplete PDF, open an
[extraction failure issue](../../issues/new?template=extraction_failure.yml) with the
verification report and a description of the layout. No debugging on your side is required.

If you built a layout profile by hand for a source that isn't covered, you can export it
from the app and attach it to a [profile issue](../../issues/new?template=layout_profile.yml).

## Before changing the pipeline

Read [ARCHITECTURE.md](ARCHITECTURE.md), particularly the **Failure modes** section.

Several of the documented failures are what the straightforward implementation of that
stage produces. Deduplicating pages by image similarity, for example, is a reasonable thing
to write and it silently drops pages. If a change looks like a simplification of an
awkward-seeming stage, check whether that awkwardness is one of the eight recorded failure
modes.

## Constraints

1. **No per-instrument code paths.** The engine does not interpret notation. Bass, guitar,
   ukulele and drums take the same path. Line counts are display metadata, not a branch.
2. **Thresholds derive from the data.** If a constant is unavoidable, document in a comment
   why it can't be derived.
3. **`tabextract/` imports nothing from `server/` or `src-tauri/`.** It must work as a
   library and CLI on its own, and it is the only part published to PyPI.
4. **New failure modes get a check in `verify.py`** and appear in the report. Failures in
   this pipeline are silent, so detection has to be explicit.
5. **No telemetry.** No analytics, no phone-home, no crash reporting to a server. The only
   outbound requests are downloads the user initiates and the update check.

## Setup

```bash
git clone https://github.com/reyiyo/tabxtract && cd tabxtract
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,desktop]"
npm install
```

Requires `ffmpeg` on your `PATH`; `tesseract` too, if you want the bar-number check to run.

Run the engine standalone. This needs no GUI and is the fastest loop for pipeline work:

```bash
tabextract analyze sample.mp4 --workdir ./work
tabextract render sample.mp4 --workdir ./work
```

Run the desktop app in dev mode. Tauri starts the Vite dev server and the Python sidecar,
and hands the frontend the port and token:

```bash
npm run tauri dev
```

To work on the frontend in a plain browser instead, start the backend by hand and point
Vite at it — it prints the port and token on the handshake line:

```bash
python -m server                      # prints TABXTRACT_READY {"port": …, "token": …}
VITE_BACKEND_PORT=… VITE_BACKEND_TOKEN=… npm run dev
```

Building the installers locally needs one more step, because the backend ships frozen:

```bash
python scripts/build_sidecar.py       # PyInstaller onedir, then starts it to verify
python scripts/fetch_native_deps.py   # GPL ffmpeg, yt-dlp, eng.traineddata
npx tauri icon src-tauri/icons/source.png
npm run tauri build
```

The Linux artifacts can also be built in a container, with no toolchain on the host:

```bash
scripts/build-in-docker.sh deb,appimage
```

They land in `dist-artifacts/`. This works for Linux only — a `.dmg` needs macOS with
Xcode and a Windows installer needs Windows, and beyond the bundler, PyInstaller does not
cross-compile, so the sidecar has to be frozen on the target platform. Budget roughly 8 GB
of free disk: the image is ~2.5 GB and the cargo and release-target caches another ~5 GB,
kept in a `tabxtract-build-cache` volume. The artifact's architecture is the Docker
daemon's — on Apple Silicon that means arm64 unless you pass `--platform linux/amd64`.

## Tests

```bash
pytest                      # engine
npm test                    # frontend
ruff check tabextract server tests scripts
mypy tabextract server
```

If you would rather not install Python, Node, ffmpeg or tesseract on the host, everything
above except the desktop window itself runs in a container:

```bash
scripts/dev-in-docker.sh pytest -q
scripts/dev-in-docker.sh npm test
scripts/dev-in-docker.sh              # a shell inside the container
```

The first run builds the image and installs the dependencies into named volumes; the
repository is mounted, so edits on the host are seen immediately. `npm run tauri dev` and
the `.dmg`/Windows installers still need their own operating system.

The end-to-end tests in `tests/e2e/` (marker `e2e`) encode a synthetic video with ffmpeg,
start the real sidecar and render PDFs through it and through the CLI. They need ffmpeg and
the `desktop` and `e2e` extras (`pip install -e ".[dev,desktop,e2e]"`), and skip when either
is missing; the container has both. Tesseract is optional: without it the bar-number check
reports as unavailable, which these tests do not assert on. They take about a minute;
`pytest -m "not e2e"` runs only the fast engine tests. Test material is always generated
from `tests/synthetic.py` at test time — no video or PDF ever enters the repository.

The browser test in `e2e/` drives the built frontend against a real sidecar with Playwright:

```bash
npx playwright install chromium     # once
npm run test:e2e
```

Its setup starts the sidecar (so the `desktop` extra and ffmpeg are needed), builds the app
into a temporary directory pointed at that sidecar, and serves it with `vite preview`. This
one does **not** run in the development container: the image has no browser.

The identical-pages regression test covers Failure mode 1. If it fails, silent page loss
has been reintroduced.

New pipeline behaviour needs a test. For a new layout, add a short clip and its expected
verification report — reports are compared rather than pixels, since pixel comparison is
unstable across ffmpeg versions.

## Pull requests

- Branch off `main`, one topic per PR.
- Describe what you observed, not only what changed. "This video produced 6 pages instead
  of 10" is more actionable than "improved dedup".
- For pipeline changes, include before/after verification reports.
- Run `ruff` and `mypy` for Python, `eslint` and `tsc` for the frontend.

## Releasing

Releases are built by `.github/workflows/release.yml` on a `v*` tag. Two things have to be
set up once, by hand, before the first release:

1. **Updater signing keys.** These are unrelated to code signing and cost nothing:

   ```bash
   npm run tauri signer generate -- -w ~/.tauri/tabxtract.key
   ```

   Put the public key in `src-tauri/tauri.conf.json` under `plugins.updater.pubkey`,
   replacing the placeholder. Put the private key and its password in the repository
   secrets as `TAURI_SIGNING_PRIVATE_KEY` and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`.

   **Until this is done the release build fails.** `bundle.createUpdaterArtifacts` is on,
   and the placeholder in the committed config is not a real key — it is left in place
   deliberately, so that a missing key is a loud build failure rather than a release that
   ships a silently broken updater. If you want to cut a release before setting up keys,
   set `createUpdaterArtifacts` to `false` first and drop `includeUpdaterJson` from
   `release.yml`.

2. **Nothing else.** There are no Apple or Windows signing secrets, and none are wanted:
   the builds are unsigned by decision, and both README and the release notes tell users
   how to open them.

Then:

```bash
git tag v0.2.0 && git push origin v0.2.0
```

The workflow builds all four targets, attaches the installers and `latest.json` to a draft
release, and warns if any expected platform asset is missing — the landing page finds
builds by file extension, so those suffixes have to survive.

## Licensing of contributions

TabXtract is GPL-3.0. Contributions are licensed under it. Add a license header to new
source files.

## Code of conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
