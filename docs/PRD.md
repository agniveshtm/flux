# Flux — Product Requirements Document

## Overview

Flux is a desktop file converter application for general consumers. It provides a simple, offline-first interface for converting between common image formats (JPG, PNG, WebP, and additional formats as sub-phases of Phase 1). The application runs entirely offline, packaged as a native Windows installer.

**Tech Stack**: Python + pywebview (desktop shell), Vue 3 + Tailwind CSS (frontend, in `src/flux/frontend`), Pillow (image conversion), PyInstaller + Inno Setup (packaging).

## Goals

- Provide a clean, CloudConvert-inspired UI (crimson-red + black theme with light/dark toggle) for file conversion
- Support Phase 1.0 conversions: JPG ↔ PNG, WebP → JPG, WebP → PNG
- Extend Phase 1 with additional image format conversions as sub-phases
- Work fully offline — no CDN dependencies, Vue vendored locally, Tailwind compiled via standalone CLI
- Distribute via a single Windows installer (Inno Setup) built with PyInstaller
- Keep conversion operations off the UI thread with progress reporting

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