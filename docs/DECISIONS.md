## 2026-09-30 — AVIF via Pillow's native libavif; no `pillow-avif-plugin`

- **Decision:** Encode/decode AVIF with Pillow's built-in libavif support (Pillow ≥ 11.3) instead of adding the `pillow-avif-plugin` dependency the issue suggested considering.
- **Alternatives:** `pillow-avif-plugin`, shelling out to `avifenc`, or dropping AVIF from scope.
- **Why:** Phase 1.1 asked for AVIF with no installer-size increase. Pillow already ships AVIF, and PyInstaller's Pillow hook bundles `PIL/_avif.pyd` (7.5 MB) into the exe whether or not we reference it — so the plugin would have added a *second* AVIF implementation and no size benefit. Verified `PIL.AvifImagePlugin` lands in the PYZ and `PIL._avif` in the binary archive of a real build. `pyproject.toml` is unchanged. The plugin also lags Pillow's native path on newer libavif features.
- **Consequence:** AVIF availability is now capability-dependent, so `INPUT_FORMATS`/`OUTPUT_FORMATS` are computed from `PIL.features.check("avif")`. A build without libavif omits AVIF rather than offering a target it cannot write.

## 2026-09-30 — Format matrix derived from the backend, not duplicated in the frontend

- **Decision:** Delete the frontend's hardcoded format table and derive the input→target matrix from `getSupportedFormats()` (i.e. from `image_converter.INPUT_FORMATS`/`OUTPUT_FORMATS`).
- **Alternatives:** Keep the hardcoded table and remember to update it; or push the whole matrix to the frontend as a new bridge call.
- **Why:** The matrix was written out in five places (the converter, `main.js`, `FormatSelect.js`, `useFlux.js`'s dev mock, and the `pickFiles` dialog filter). Nothing made them agree, so a format could be offered in the dropdown and then rejected by the converter, or the reverse. Since `getSupportedFormats()` already returns both lists, the frontend only needs "every output format is a valid target for every input format except itself". `tests/test_formats.py` now pins the two remaining shadows — the dev mock and the pickers — to the backend lists, so drift fails CI.
- **Consequence:** Adding a format is a backend change plus (only if a new control is needed) UI work, instead of four coordinated edits.

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

## 2026-09-25 — Packaged resources: resolve via sys._MEIPASS, fail loudly, FLUX_DEBUG

- **Decision:** Resolve bundled data files through one helper, `flux.main._bundled_path()`: a source run anchors at `Path(__file__).parent`, a frozen build anchors at `sys._MEIPASS/"flux"` — the destination `flux.spec` bundles into. A missing `index.html` raises instead of rendering WebView2's `ERR_FILE_NOT_FOUND` page, and `webview.start(debug=...)` plus resolved-path logging are gated behind a `FLUX_DEBUG` environment variable so any built exe can be diagnosed without rebuilding it.
- **Alternatives:** Keeping `Path(__file__).parent` in both modes (the v0.1.0 behaviour), moving the spec's data destinations to the archive root, serving the frontend from an embedded HTTP server instead of `file://`, resolving `sys._MEIPASS` ad hoc at each call site.
- **Why:** The v0.1.0 exe shipped broken: PyInstaller runs the entry script as `__main__` with `__file__` set to `<_MEIPASS>/main.py` — one level *above* the package — so `Path(__file__).parent / "frontend"` looked in `<_MEIPASS>/frontend/` while the files were bundled at `<_MEIPASS>/flux/frontend/`, and every launch opened the "File not found" page (the window icon resolved wrong the same way). The release smoke test could not catch it because `--version` never opens a window; `tests/test_main.py` now pins the resolver against `flux.spec`'s destinations so the two sides cannot drift apart again. Bundling at the archive root would only fit the entry script and would break any real package module doing the same lookup later. Raising on a missing frontend turns a silent blank window into a traceback dialog (`disable_windowed_traceback=False` in `flux.spec`), and `FLUX_DEBUG=1` reproduces the diagnostic run — pywebview `debug=True` plus the resolved paths on stderr, which for a windowed exe needs a redirected stderr handle — without ever shipping a debug build to users.


## 2026-10-02 — Release and commit data via REST + a committed cache, not GraphQL

- **Decision:** The project site reads releases and commits from `docs/cache.json`, regenerated by a workflow using curl + jq against the GitHub REST API. The page falls back to calling REST directly when the cache is absent.
- **Alternatives:** GitHub GraphQL from the browser; hand-maintained changelog text; fetching REST directly on every page load with no cache.
- **Why:** GraphQL requires an authentication token, and a token shipped in browser JavaScript is readable by anyone who views source. REST needs none. The cache keeps the page working (and rate-limit-free) while still being current, and mirrors the approach already used by the author's Portfolio repo. Fetching live on every load would put the site at the mercy of the unauthenticated 60 requests/hour cap. Stdlib-free by construction: curl and jq only run in CI.

## 2026-10-02 — GitHub Releases is the changelog; no in-repo CHANGELOG.md

- **Decision:** Release notes live in GitHub Releases and are surfaced on the site through the cache. The repository deliberately has no `CHANGELOG.md`.
- **Alternatives:** A hand-written `docs/CHANGELOG.md`; generating one in CI alongside the cache.
- **Why:** A second copy of the release notes is a second source of truth, and it drifts - which is exactly the failure already fixed once in this project, where the format matrix was duplicated across four frontend files. The notes are already written once, at release time, where they belong.
- **If this changes:** If the project ever needs an in-repo changelog (offline reading, non-GitHub distribution), generate it from the same cache rather than writing it by hand, and note that both now exist.

## 2026-10-02 — The site reuses the app's design system rather than defining its own

- **Decision:** `docs/index.html` is styled with the same CSS custom properties as the desktop app, loads the same vendored Inter font and logo artwork, and shares the `flux-theme` localStorage key.
- **Alternatives:** An independent visual identity for the site; importing the app's compiled Tailwind CSS.
- **Why:** Two design systems for one product is a maintenance cost with no user-visible benefit, and the site reads as marketing for a specific build rather than a separate brand. Sharing the theme key means a visitor who picks dark mode in the app gets dark mode on the site. Tailwind was rejected because it would mean a build step for a page whose whole value is being a single file that opens from disk.
- **Consequence:** The site must not introduce colours outside the token set. An accessibility pass found crimson #DC143C fails AA as small text in both themes (3.94:1 dark, 3.70:1 on tint), so it is confined to buttons, borders and graphics where the 3:1 threshold applies. Every change must be checked against both themes.

## 2026-10-02 — Pages deploys an assembled `_site/`, not the repository

- **Decision:** `pages.yml` assembles a `_site/` directory containing the page, the four asset files it needs, and the cache, rewriting the page's in-repo asset paths as it copies. The repository itself is never uploaded.
- **Alternatives:** GitHub's suggested `upload-pages-artifact` with `path: '.'`, which publishes the whole checkout; committing a duplicate copy of the artwork into `docs/assets/`.
- **Why:** Uploading the repository puts the site at `/docs/` instead of the root and makes `src/`, `tests/` and `scripts/` reachable URLs. Committing duplicate assets was rejected earlier for the same reason - one source of truth. Assembling at deploy time gives the clean URL without the duplication, at the cost of one `sed` in the workflow.
- **Consequence:** Adding an asset to the page means copying it in the workflow too. The workflow's push paths must cover wherever that asset lives, or a change to it will not trigger a rebuild - which is how the vendored font was initially missed.

## 2026-10-10 - The site fetches the GitHub API directly; the cache is gone

- **Decision:** `docs/index.html` reads the GitHub REST API on every load (`/releases` and `/commits` in parallel, normalised in the page) and keeps a 2-minute localStorage copy to absorb the 60 requests/hour unauthenticated limit. There is no generated data file: `update-cache.yml`, `docs/cache.json`, `scripts/build_cache.py` and `scripts/build_cache.jq` are deleted, and a failure to reach GitHub now shows a link to GitHub rather than a stale snapshot.
- **Alternatives:** keep the workflow-written cache as the primary source (the original design); keep it as an offline fallback behind the API (an intermediate state that lasted a few hours and generated an hourly "update cache" commit for data nothing read first).
- **Why:** the page asks GitHub directly, so a release is visible the moment it is published instead of after the next workflow run, and the repo stops accumulating a commit per hour that only rewrites a file nothing depends on. REST rather than GraphQL keeps the no-token-in-browser-JavaScript property. The 2-minute localStorage copy covers the rate limit and paints instantly on a repeat visit; what it cannot cover - a genuinely offline visitor - is better served by an honest message than by a snapshot of unknown age.
- **Consequence:** two API calls per cold page view, per visitor, not per view. `/releases` lists drafts and pre-releases to anyone with push access and the app's updater ignores both, so `normalise()` filters them here too. *(Supersedes the fetch order in the 2026-10-02 REST entry; its REST-not-GraphQL rationale stands.)*

## 2026-10-14 - The default conversion target is an explicit preference list

- **Decision:** `TARGET_PREFERENCE = ['jpg', 'png', 'webp', 'ico', 'gif', 'avif']` in `main.js` decides which target a dropped file is preselected, via `defaultTargetFor()`, rather than taking `targetsForInput(ext)[0]`.
- **Alternatives:** keep the derived first target (the previous behaviour); ask the backend for a preferred default; make the choice depend on the input format.
- **Why:** the matrix is derived from `getSupportedFormats()`, which returns **sorted** lists, so "the first target" was the alphabetically first - `avif` for every input except AVIF itself. That made AVIF the silent default for every file a user dropped: the slowest encoder here and the least compatible output for a general consumer, offered before they chose anything, with the quality slider appearing alongside it. A per-format table would reintroduce the duplicated-format-list problem Phase 1.1 deleted.
- **Consequence:** adding an output format means adding it to `TARGET_PREFERENCE` or the `offered[0]` fallback decides instead. `tests/test_formats.py` pins that AVIF stays last and that the list covers every backend output; `scripts/check-frontend.js` executes the real `defaultTargetFor` and asserts the wiring, because the source-parsing test alone cannot catch a regression in `getDefaultTargetFormat`.

## 2026-10-14 - PyInstaller is build tooling, not a runtime dependency

- **Decision:** `pyinstaller` moves from `[project].dependencies` to `[dependency-groups].dev`. Runtime dependencies are `pillow` and `pywebview` again, as ARCHITECTURE decision 3 always stated.
- **Alternatives:** leave it as a runtime dependency (status quo); keep it in both places.
- **Why:** PyInstaller produces the frozen exe and is never imported by the running app, so declaring it a runtime requirement put a build tool and its dependency tree into every install of the package - directly contradicting the documented dependency policy. `uv sync` installs the default `dev` group, so the release workflow's `uv run pyinstaller flux.spec` is unaffected.
- **Consequence:** `uv sync` still provisions PyInstaller for local builds and CI, so nothing in the pipeline changes. Anyone installing Flux as a package gets only what the app actually imports.

## 2026-10-14 - The installer declares the architecture it builds

- **Decision:** `installer/flux.iss` sets `ArchitecturesAllowed=x64compatible` and `ArchitecturesInstallIn64BitMode=x64compatible` - Inno's documented pair for a 64-bit-only app.
- **Alternatives:** declare no architectures (status quo); `x64` alone; `win64`.
- **Why:** `ArchitecturesAllowed`'s default depends on whether ISCC emits a 32-bit or a 64-bit Setup, and on a 32-bit Setup it defaults to `x86compatible` - which would install this x64 build on 32-bit Windows, where it then fails to launch. `x64compatible` covers x64 and Arm64 (which runs x64 under emulation), so it does not over-restrict.
- **Consequence:** a 32-bit Windows user is refused at install time instead of getting a broken install. `tests/test_packaging.py` pins both directives, along with the manual-build fallback version, which had drifted to 0.1.0 because CI always overrides it with `/DMyAppVersion`.

## 2026-10-14 - A behavioural frontend check belongs in check-frontend.js

- **Decision:** `scripts/check-frontend.js` gained a check that extracts `TARGET_PREFERENCE` and `defaultTargetFor` from `main.js`, executes them, and asserts `getDefaultTargetFormat` calls the helper - alongside the existing syntax, template-compile and index-wiring checks.
- **Alternatives:** rely on `tests/test_formats.py` (which parses the same source and compares the list in Python); accept that the wiring is unverified.
- **Why:** a source-parsing test cannot catch a regression in the *wiring*. Reverting `getDefaultTargetFormat` to `return targets[0] || 'png'` left the pytest fully green while every dropped file preselected AVIF again - a reviewer caught exactly that, and the gap was real. Node can execute the shipped code, so the check runs the real function instead of a replica of it.
- **Consequence:** the pytest now states plainly that it pins the list's contents and that the wiring is verified elsewhere, rather than implying it covers both. The two are complementary: the pytest knows the backend's `OUTPUT_FORMATS` (the authoritative list), the node check executes the frontend logic.

## 2026-10-15 - Accept pillow-heif as HEIF's second runtime dependency

- **Decision:** Add `pillow-heif>=1.8.1` to `[project].dependencies` (beside `pillow` and `pywebview`) and capability-gate HEIF exactly like AVIF: `_heif_available()` tries `import pillow_heif` + `register_heif_opener()` and omits the format on failure.
- **Alternatives:** drop HEIF from scope (the pre-audit status quo); shell out to a bundled `heif-enc` CLI; require Pillow to grow native HEIF support.
- **Why:** Pillow has no HEIF support of its own (`features.check("heif")` is `False`). `pillow-heif` was verified in a throwaway venv, not assumed: 752-byte round-trip with transparency, 2.32 MB installed footprint (well under the ≤10 MB acceptance criterion), AVIF unaffected after registration. This is a deliberate exception to Architecture decision 3's "runtime deps are Pillow + pywebview only" - the issue that proposed HEIF recommended accepting it, and the capability gate means a build without the dependency still runs (the format simply does not appear).
- **Consequence:** `flux.spec` needs an explicit `binaries=` collection because pillow-heif ships `libheif-<hash>.dll` at site-packages root, not inside the package - PyInstaller's static analysis would miss it. Pinned by `test_spec_collects_pillow_heif_binaries`. The installer grows by ~2.32 MB per release.

## 2026-10-15 - HEIC is the canonical HEIF output; both extensions are inputs

- **Decision:** `.heic` and `.heif` are the same container. Both are accepted as inputs (`INPUT_FORMATS = (..., "heic", "heif")`), but only `heic` is offered as a target (`OUTPUT_FORMATS = (..., "heic")`). `normalize_format("heif")` returns `"heic"` (mirroring `jpeg` → `jpg`), and the frontend's `normalizeExt` does the same.
- **Alternatives:** treat them as two distinct formats (8 outputs / 56 pairs); canonicalize to `heif` instead (pillow-heif's format ID); accept both as outputs.
- **Why:** the `jpeg`/`jpg` precedent already established that one encoder means one canonical target name while multiple input extensions are accepted. `heic` is chosen over `heif` as the canonical because it is what iPhone users search for and expect; the underlying encoder is selected by format ID (`HEIF`), so the extension is purely a filename convention. Treating them as distinct would double the pair count for no functional gain - the same bytes are written either way.
- **Consequence:** 7 formats / 42 cross-pairs, not 8 / 56. A `.heif` input dropped into the UI is looked up under `heic` via `normalizeExt`, so the row shows the correct target list. `test_formats.py` pins the mock, picker and preview allowlist to include both extensions.
