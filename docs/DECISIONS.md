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

## 2026-09-19 — Frontend: Vue 3 global build + classic script tags (no bundler)

- **Decision:** Use Vue 3 global production build (`vue.global.prod.js`) loaded via classic `<script>` tags, no bundler, no `.vue` files, no `<script setup>`.
- **Alternatives:** Vite + SFC compilation, Webpack + vue-loader, esbuild, Rollup.
- **Why:** `file://` protocol (used by pywebview) blocks ES modules (`type="module"`). Classic scripts work reliably. Global namespace (`window.Flux`) avoids module complexity. Components as plain JS objects with template strings are simple and debuggable.

## 2026-09-19 — Frontend: Tailwind CSS compiled via standalone CLI (v3)

- **Decision:** Compile Tailwind CSS at build time using the standalone CLI (`npx tailwindcss@3 -i ... -o ...`), commit `assets/app.css`.
- **Alternatives:** Tailwind v4 (new CLI), PostCSS plugin, CDN.
- **Why:** v3 standalone CLI is a single binary with no Node runtime required in packaged app. Custom theme values (colors, fonts) map to CSS variables for dynamic theming. Committed CSS works offline and from `file://`.

## 2026-09-19 — Frontend: Inter font bundled locally

- **Decision:** Bundle Inter variable font (TTF) locally in `assets/fonts/`, declare via `@font-face`, fallback to `system-ui`.
- **Alternatives:** Google Fonts CDN, `@fontsource` npm package, system fonts only.
- **Why:** Offline-first requirement forbids CDN. Variable font covers all weights (100-900) in one file (~260 KB). `system-ui` fallback matches platform UI font style.

## 2026-09-19 — Frontend: Theming via CSS variables + Tailwind darkMode: 'class'

- **Decision:** Define all colors as CSS variables on `:root` (light) and `.dark` (dark), mapped to semantic Tailwind classes (`bg-surface`, `text-fg`, `border-line`, `bg-accent`). Toggle `.dark` class on `<html>`.
- **Alternatives:** Tailwind `darkMode: 'media'` only, inline styles, CSS-in-JS.
- **Why:** CSS variables enable instant theme switching without rebuild. `darkMode: 'class'` gives programmatic control. Inline script in `index.html` applies saved theme before paint to prevent flash. Semantic class names (`bg-surface` not `bg-white`) keep components theme-agnostic.

## 2026-09-19 — Frontend: Convention mode design (CloudConvert-inspired)

- **Decision:** Follow convention mode (utility tool) — familiar patterns, no signature element, no unrequested aesthetic risks. Fixed palette from brief (crimson + neutrals).
- **Why:** File converter is a tool; users need to find "Convert" without thinking. CloudConvert reference sets expectations. One name per action across flow ("Convert all" → "Converted"). Errors state what went wrong and how to fix, no apologies. Empty states guide next action.

## 2026-09-24 — Release pipeline: PyInstaller one-file + Inno Setup, tag-driven CI

- **Decision:** Ship every `v*` tag through `.github/workflows/release.yml`: pytest gate, tag↔pyproject↔`flux.__version__` version check, PyInstaller one-file `dist/flux.exe` (windowed, smoke-tested via `--version`), Inno Setup `dist/flux-setup-<ver>.exe` from `installer/flux.iss`, both uploaded to the GitHub release. No wheel/sdist artifacts.
- **Alternatives:** onedir bundle (faster start, folder to ship), `cx_Freeze`/`Nuitka`, publishing only the exe or only the installer, keeping `uv build` outputs in the release.
- **Why:** The release needs both artifacts for a reason: `flux.exe` is the portable download, `flux-setup-<ver>.exe` is what the in-app updater can actually run to replace an installation (and what the `.iss` relaunches after upgrade). One-file keeps the portable download a single file; `console=False` keeps users from seeing a terminal. The smoke test uses `--version` because a GUI exe would hang CI otherwise. Version is asserted in three places (tag, pyproject, `__version__`) because the updater compares `__version__` against release tags — a mismatch would break update detection for everyone already installed.

## 2026-09-24 — In-app updates: GitHub releases via stdlib, bell UI, explicit restart

- **Decision:** Check GitHub `/releases/latest` at startup with stdlib `urllib` (`flux/services/updater.py`), surface newer releases through a bell button in the header with a yellow "!" badge, and offer Download update / Dismiss / Mark as read. The downloaded artifact is always the Inno setup; applying it requires an explicit **Restart & update**, which runs the setup `/SILENT` and closes the app.
- **Alternatives:** `requests`/`httpx` for networking, a full auto-updater framework (e.g. `pyupdater`, `tufup`), silent auto-install the moment the download completes, checking on a timer instead of at startup, ignoring the badge state in `localStorage`.
- **Why:** The offline-first dependency policy rules out a networking client for one GET; `urllib` ships with Python. Auto-installing the moment bytes land would kill in-flight conversions — the industry-standard explicit restart step keeps the user in control while `/SILENT` + `PrivilegesRequired=lowest` makes the actual upgrade (and relaunch, via the `.iss` `[Run]` entries) unattended and UAC-free. Dismiss is session-only and Mark as read persists (`flux-seen-release`), so "later" and "never for this version" stay distinct. Download goes to the temp dir as `.part`-then-rename so a truncated file can never be executed as an installer.

## 2026-09-25 — Update downloads: origin allowlist, SHA-256 verification, Windows-only install

- **Decision:** Verify the installer before the app can run it. Every release publishes `<installer>.sha256` (CI writes it with `Get-FileHash` in `sha256sum` format), `check()` records that asset's URL, and `download()` fetches the digest from a GitHub host over https, hashes the streamed file and discards it unless the two match (`CHECKSUM_MISMATCH`); a release that publishes no digest is refused outright (`NO_CHECKSUM`) before a single installer byte is fetched. Both payload URLs are allowlisted (`is_trusted_download_url`, re-checked after redirects), the asset name is reduced to one safe filename component inside `flux-update/` (`safe_download_name`), and `installUpdate` refuses to run off Windows (`UNSUPPORTED_PLATFORM`).
- **Alternatives:** Authenticode (`WinVerifyTrust` via `ctypes`) against a pinned publisher certificate, a digest pinned out-of-band in the app or a separate `SHA256SUMS` fetch path, trusting `browser_download_url`, the asset name and the payload bytes as given (the previous behaviour), launching the downloaded setup on any platform and letting the OS fail.
- **Why:** The URL, the name and the bytes all come from whoever published the release, and the file is subsequently *executed*, so none of them may be taken on faith. The digest is fetched as its own request — and, for release assets, from a different host than the body (github.com → `*.githubusercontent.com`) — so bytes substituted in transit cannot also adjust the value they are checked against; the residual trust is GitHub's release metadata over TLS. Authenticode would be stronger but is unimplementable today: the artifacts are unsigned, so verification could only fail closed and block every release until the project owns a signing certificate, which is the recorded follow-up (together with the CI step that would attach the signature). Failing closed on a missing digest costs nothing because no release predates this rule.
