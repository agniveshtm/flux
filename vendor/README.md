# vendor/

The bundled ffmpeg sidecar binary. `flux.services.ffmpeg.locate_ffmpeg()`
looks here first (after any `FLUX_FFMPEG` override), so a source checkout
gets video conversion without a system install.

## Provenance

| | |
|---|---|
| Source | https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2 |
| Asset | `ffmpeg-9.0.2-essentials_build.zip` |
| Upstream | https://www.gyan.dev/ffmpeg/builds/ (gyan.dev essentials build 9.0.2) |
| SHA-256 | `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba` |
| Verified | digest matched the GitHub release API `digest` field on 2026-10-24 |
| File | `ffmpeg.exe`, 105,423,872 bytes |

Only `ffmpeg.exe` ships (see `LICENSE-ffmpeg.txt` for its licence). The
`ffprobe.exe` and `ffplay.exe` that come with the build are deliberately
left out: Flux derives duration from ffmpeg's own `-loglevel info` stderr
and never needs a second binary. The zip is not kept - the rows above are
enough to re-download and re-verify it.

## Licence

This binary is GPLv3 (gyan.dev essentials builds enable libx264, which is
GPL). `LICENSE-ffmpeg.txt` is the licence text shipped with the build.

Flux invokes it as a separate process over argv and pipes - never linked -
so the GPL reaches the binary and nothing else (research/
phase2-video-mobile/REPORT.md §1.2.1). Do not link ffmpeg into the Python
process.

## Updating

1. Fetch the release you want from GyanD/codexffmpeg (it mirrors gyan.dev
   builds with stable tags) and record its `digest` from the GitHub API.
2. Download the `essentials_build.zip`, check its SHA-256 against that
   digest, extract `bin/ffmpeg.exe` over the file here, and update this
   table.
3. Run `uv run pytest tests/ -q` - the vendored-binary tests are skipped
   when this file is absent and run for real when it is present.
