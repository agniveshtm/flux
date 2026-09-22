## 2026-09-19 — Pillow for Phase 1 image conversion

- **Decision:** Use Pillow instead of bundling ImageMagick for Phase 1 image conversion.
- **Alternatives:** ImageMagick (via `magick` CLI or `wand`/`pgmagick` bindings), raw `PIL` via `pyvips`, `imageio` with plugins.
- **Why:** Pillow is pure Python with binary wheels, well-maintained, supports all Phase 1 formats (JPG, PNG, WebP) natively, zero external dependencies, small bundle size increase (~8 MB), and integrates cleanly with the `BaseConverter` interface.

## 2026-09-19 — No Vite; Vue vendored locally, Tailwind via standalone CLI

- **Decision:** Do not use Vite. Vendor Vue 3 locally in `src/flux/frontend/` and compile Tailwind with the standalone CLI so the app works fully offline.
- **Alternatives:** Vite + `vite-plugin-vue` + CDN-hosted Vue/Tailwind, `vite-plugin-tailwind` with local build, Webpack, Parcel.
- **Why:** Offline-first requirement forbids any network calls at runtime. Vite dev server and HMR are dev-only; production build still needs Node at build time. Standalone Tailwind CLI is a single binary (~15 MB) with no Node dependency. Vendoring Vue (ESM build) keeps the frontend self-contained. PyInstaller bundles the built `dist/` folder as static assets.

## 2026-09-19 — pywebview for desktop shell

- **Decision:** Use pywebview as the desktop application shell.
- **Alternatives:** Electron/Tauri (Node/Rust + WebView2), `tkinter`/`PyQt`/`PySide` (native widgets), `wxPython`, `flet`, `webview` (Go), plain `webbrowser` + local server.
- **Why:** pywebview is lightweight (~2 MB), uses native OS webview (WebView2 on Windows), Python-first API, supports `window.pywebview.api` for JS↔Python bridge, no Node/Rust toolchain, works with PyInstaller out of the box, and matches the "Python backend + Vue frontend" architecture.

## 2026-09-19 — PyInstaller + Inno Setup for packaging and distribution

- **Decision:** Package with PyInstaller and create Windows installer via Inno Setup.
- **Alternatives:** `cx_Freeze`, `py2exe`, `Nuitka`, `msi` via `wix`, `nsis`, zip/portable only, `pyapp`/`briefcase`.
- **Why:** PyInstaller is mature, handles hidden imports and data files well, produces a single executable or onedir bundle. Inno Setup creates professional Windows installers (uninstaller, start menu, shortcuts, file associations) with scripting for versioning and code signing. Both are pure Python/Windows tooling with no external runtime.

## 2026-09-19 — Leaning ffmpeg for Phase 2 video conversion (tentative)

- **Decision:** Lean toward ffmpeg for Phase 2 video conversion; mark as tentative.
- **Alternatives:** `moviepy` (Python wrapper), `imageio-ffmpeg`, `pymedia`, `gstreamer` Python bindings, cloud transcoding APIs.
- **Why:** ffmpeg is the industry standard, supports every codec/format, static Windows builds available (~50 MB), CLI interface fits the `BaseConverter` pattern, and can be bundled as a sidecar binary. Marked tentative because Phase 2 scope, timeline, and format requirements are not finalized; `moviepy` may suffice for simpler needs.