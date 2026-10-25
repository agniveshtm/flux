# Flux — Product Requirements Document

## Overview

Flux is a desktop file converter application for general consumers. It provides a simple, offline-first interface for converting between common image formats (JPG, PNG, WebP, ICO, AVIF, GIF and HEIC/HEIF), and — since Phase 2.1 — for converting video into MP4, still frames and animated GIF. The application runs entirely offline, packaged as a native Windows installer.

**Tech Stack**: Python + pywebview (desktop shell), Vue 3 + Tailwind CSS (frontend, in `src/flux/frontend`), Pillow + pillow-heif (image conversion), a vendored ffmpeg sidecar binary (video conversion, `vendor/ffmpeg.exe`), PyInstaller + Inno Setup (packaging).

## Goals

- Provide a clean, CloudConvert-inspired UI (crimson-red + black theme with light/dark toggle) for file conversion
- Support all seven image formats in both directions (Phase 1.1 + 1.3): JPG, PNG, WebP, ICO, AVIF, GIF, HEIC
- Convert video: video containers to MP4, video to still frames, and clips to animated GIF (Phase 2.1, capability-gated on ffmpeg)
- Work fully offline — no CDN dependencies, Vue vendored locally, Tailwind compiled via standalone CLI
- Distribute via a single Windows installer (Inno Setup) built with PyInstaller
- Keep conversion operations off the UI thread with progress reporting
- Publish a project site showing what the app does, its release history and its recent activity, kept current automatically from GitHub (Phase 1.2)

## Phase 1.1 — Format support

`image_converter.INPUT_FORMATS` / `OUTPUT_FORMATS` are the single source of truth.
The frontend derives its input→target matrix from `getSupportedFormats()` rather
than keeping its own table, so a format cannot be offered in the UI unless the
backend can actually write it.

| Format | Notes |
|--------|-------|
| JPG | Flattens transparency onto white. Quality and subsampling options. |
| PNG | Lossless; transparency preserved. |
| WebP | Lossy/lossless; transparency preserved. Quality and method options. |
| ICO | Writes 16/32/48/256 frames at once, square-padded with transparency, clamped to what the source can supply. |
| AVIF | libavif, built into Pillow ≥ 11.3 — no extra dependency. Quality and speed options; ICC/XMP carried through. |
| GIF | Palette reduction with a working dither control. Animated sources keep every frame, per-frame duration and disposal. |

Deliberate limits:

- Converting an image to the format it is already in is not offered.
- Animated sources collapse to their first frame for every non-GIF target; only
  GIF output preserves animation.
- GIF transparency is binary (one transparent palette index) — partial alpha is
  cut at a threshold.
- AVIF is encoded 8-bit by Pillow, so HDR *colour profiles* survive but 10-bit
  HDR encoding is not reachable.

## Phase 1.3 — HEIF/HEIC support

Extends the format matrix to seven formats (42 cross-pairs) by adding HEIC/HEIF
— the container iPhone and Android camera apps produce. `.heic` and `.heif` are
the same container and both are accepted as inputs; `heic` is the single
canonical output (following the `jpeg`/`jpg` precedent).

| Format | Notes |
|--------|-------|
| HEIC | HEVC/AV1-coded container via pillow-heif. Quality option; transparency and ICC preserved. `.heif` accepted as input alias. |

Unlike AVIF, HEIF requires a second runtime dependency: **pillow-heif 1.8.1**
(2.32 MB footprint) registers a Pillow opener for `.heic`/`.heif`. The format
is capability-gated exactly like AVIF — a build without the dependency simply
does not offer the target.

Deliberate limits:

- HEIF's lossy coding is H.265/HEVC-based and roughly JPEG-comparable at the
  same quality level; quality defaults to 90 (matching JPEG/WebP, not AVIF's 80).
- Multi-image HEIF sources (bursts) collapse to the first frame for non-GIF
  targets, per the existing animation rule.
- SVG was considered for this phase and excluded — both rasterizers
  (cairosvg, svglib) require cairo, which is unavailable on the build host, and
  raster→SVG output is a potrace-class tracing feature, not a converter feature.

## Phase 2.1 — Video conversion

Adds video as an input family and MP4 as an output, driven by a vendored
ffmpeg sidecar (`vendor/ffmpeg.exe`, gyan.dev essentials 9.0.2). The
input→target matrix is still derived entirely from the registry — a video
row offers MP4 plus every still target (the first frame is extracted and
run through the ordinary Pillow pipeline); a GIF row offers every image
target plus MP4, because a GIF is an animation and the video converter
reads it.

| Conversion | Notes |
|--------|-------|
| Video → MP4 | H.264 first (`libx264`, falling back to `libvpx-vp9` by availability), CRF mapped per codec from the quality slider, AAC audio, `+faststart`. |
| Video → stills | First frame extracted to a temp PNG, then the normal image pipeline; the temp file is always cleaned up. |
| Video → GIF | Full animation through ffmpeg's palette chain (`palettegen`/`paletteuse`, fps 15, width capped at 480px), `-loop 0`. |
| GIF → MP4 | GIF accepted as a video input of the video converter. |

Deliberate limits:

- MP4 is the only video **output** in Phase 2.1 (WebM/MKV/MOV etc. are
  Phase 2.2+).
- Image → MP4 is not offered: a one-frame clip is a worse still image, and
  nothing sensible plays it as a video.
- Everything video is capability-gated: without a capable ffmpeg build the
  converter registers nothing, the matrix has no video rows, and the app is
  exactly the image-only converter it was before.
- GIF appears in **both** rings of the format donut (image and video), since
  the same pair — gif → mp4, clip → gif — is a video conversion, while
  still → gif remains an image one; the grouping ships from the backend in
  `getSupportedFormats().rings`.
- Release packaging is an open item: `locate_ffmpeg` already looks for
  `ffmpeg.exe` beside the frozen executable, but the Inno Setup script does
  not ship it yet, so packaged builds currently run image-only — and bundling
  the 105 MB binary collides with the <100 MB installer success criterion.


## Non-Goals

- **Video outputs beyond MP4 (WebM, MKV, MOV, AVI) and audio extraction** —
  Phase 2.2+/not in scope yet; MP4 is the only video target for now
  (video *inputs* were un-deferred in Phase 2.1, 2026-10-24)
- Cloud/online conversion features — app must work fully offline
- macOS/Linux installers in v1.0 — Windows only initially
- Batch folder processing — single/multiple file selection only
- Advanced editing (crop, resize, filters) — conversion only
- Plugin/extension system — fixed converter set per release
- A separate visual identity for the site — it reuses the app's design system
  (DECISIONS 2026-10-02)
- An in-repo `CHANGELOG.md` — GitHub Releases is the single source, surfaced by
  the site (DECISIONS 2026-10-02)

## User Stories / Use Cases

1. **As a general consumer**, I want to drag and drop an image file and convert it to another format so I can use it in applications that don't support the original format.
2. **As a general consumer**, I want to convert multiple files at once so I don't have to repeat the process for each file.
3. **As a general consumer**, I want a simple, beautiful interface that works offline so I can convert files without internet access or privacy concerns.
4. **As a general consumer**, I want to see conversion progress so I know when my files are ready.

## Success Criteria

- App launches in under 2 seconds on typical Windows hardware
- Image conversions complete successfully for all supported format pairs
- Installer size stays under 100 MB
- Zero external network calls at runtime, except the user-visible in-app update check/download (GitHub releases)
- Light/dark theme toggle persists across sessions
- No UI freezing during conversions (progress reported via frontend)
- The project site meets WCAG AA contrast in both themes, with no authenticated
  request issued from the browser

## Phase 1.1 acceptance criteria

- [x] All 6 formats convertible in both directions (30 cross-pairs verified)
- [x] Transparency preserved across conversions (except JPG, which has no alpha)
- [x] No installer size increase > 10 MB — AVIF ships inside Pillow, so no new
      dependency; `PIL/_avif.pyd` was already bundled by PyInstaller's Pillow
      hook before this phase
- [x] Animation preserved in GIF output (frames, per-frame duration, disposal)
- [x] Colour quality maintained for AVIF output (ICC/XMP carried through)
- [x] Unit tests for the new format paths (`tests/test_image_converter.py`,
      `tests/test_formats.py`)

## Phase 1.3 acceptance criteria

- [x] HEIC and HEIF readable both ways, quality option honoured on write
- [x] All 42 cross-pairs between the 7 formats verified
- [x] Transparency preserved (except JPG, which has none)
- [x] Multi-frame `.heic` → first frame, per the existing animation rule
- [x] Installer growth ≤ 10 MB — pillow-heif is 2.32 MB, under the 100 MB cap
- [x] `flux.spec` bundles libheif — pinned by `test_spec_collects_pillow_heif_binaries`
- [x] AVIF output unchanged after registration (quality, speed, ICC)
- [x] A build without pillow-heif runs and simply omits the format
- [x] Tests pass on both CI legs

## Phase 2.1 acceptance criteria

- [x] Video containers convertible to MP4; a format is never a target of itself
- [x] Video inputs convertible to every still target via frame extraction
- [x] GIF → MP4 and video → animated GIF both work end to end
- [x] GIF listed in both donut rings from the backend `rings` payload
- [x] A build without ffmpeg is image-only and every test still passes
      (fake-backed suite runs with no binary at all)
- [x] Vendored binary SHA-256-verified against the release digest and ships
      libx264 — pinned by `test_the_vendored_build_includes_libx264`
- [x] Real-ffmpeg encodes decode back cleanly (`ffmpeg -v error … -f null -`)
- [x] Tests 111 → 141; check-frontend and all four UI checks green
- [ ] Release packaging: installer ships `ffmpeg.exe` next to `flux.exe`
      (open — see the packaging note in Phase 2.1; also affects the <100 MB
      installer criterion)