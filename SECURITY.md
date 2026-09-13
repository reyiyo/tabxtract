# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security vulnerabilities.

Report privately through
[GitHub Security Advisories](https://github.com/reyiyo/tabxtract/security/advisories/new).
That form is only visible to the maintainers.

Expect an acknowledgement within a few days. This is a volunteer project, so response times
vary.

## Scope

TabXtract is a desktop application that processes local files. Relevant areas:


- **The local HTTP backend.** It binds `127.0.0.1` only, on an OS-assigned ephemeral port,
  and requires a random handshake token generated at startup. A way to reach it without the
  token, or from another origin, is a valid vulnerability.
- **Sidecar process lifecycle.** Orphaned or hijackable sidecar processes.
- **Media parsing.** We shell out to `ffmpeg`; crafted input reaching it in unintended ways
  is in scope.
- **The auto-updater.** Update manifests are signed. Signature bypass is in scope.
- **Path handling.** Traversal via crafted filenames or output paths.

## Out of scope

- Vulnerabilities in bundled third-party binaries (`ffmpeg`, `yt-dlp`) — please report
  those upstream. Do tell us if we're shipping a version with a known CVE.
- Unsigned builds triggering SmartScreen on Windows or Gatekeeper on macOS. Documented in the README.
- Anything requiring an attacker to already have local code execution as the user.

## What we don't collect

TabXtract has no telemetry, no analytics and no crash reporting. It makes no outbound
network requests other than downloads you explicitly request and the update check, which
you can disable.
