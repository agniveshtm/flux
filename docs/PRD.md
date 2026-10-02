# Flux — Product Requirements Document

## Overview

Flux is a desktop file converter application for general consumers. It provides a simple, offline-first interface for converting between common image formats (JPG, PNG, WebP, ICO, AVIF and GIF). The application runs entirely offline, packaged as a native Windows installer.

**Tech Stack**: Python + pywebview (desktop shell), Vue 3 + Tailwind CSS (frontend, in `src/flux/frontend`), Pillow (image conversion), PyInstaller + Inno Setup (packaging).

## Goals

- Provide a clean, CloudConvert-inspired UI (crimson-red + black theme with light/dark toggle) for file conversion
- Support all six image formats in both directions (Phase 1.1): JPG, PNG, WebP, ICO, AVIF, GIF
- Work fully offline — no CDN dependencies, Vue vendored locally, Tailwind compiled via standalone CLI
- Distribute via a single Windows installer (Inno Setup) built with PyInstaller
- Keep conversion operations off the UI thread with progress reporting

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


## Non-Goals

- **Video conversion (Phase 2)** — explicitly deferred; leaning toward ffmpeg but not in v1.0
- Cloud/online conversion features — app must work fully offline
- macOS/Linux installers in v1.0 — Windows only initially
- Batch folder processing — single/multiple file selection only
- Advanced editing (crop, resize, filters) — conversion only
- Plugin/extension system — fixed converter set per release

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