## 2026-09-19

- Created project documentation structure (docs/ folder)
- Wrote PRD.md with Overview, Goals, Non-Goals, User Stories, Success Criteria
- Confirmed: target users = general consumers; Phase 2 (video/ffmpeg) is OUT of scope for v1.0
- Documented Phase 1 extensions as sub-phases (additional image formats beyond jpg/png/webp)
- Stack locked: Python/pywebview + Vue 3/Tailwind + Pillow + PyInstaller/Inno Setup
- Set up ARCHITECTURE.md with layers, API surface, threading model, converter interface, folder structure, offline constraints
- Logged initial ADRs in DECISIONS.md: Pillow for images, no Vite/CDN, pywebview shell, PyInstaller+Inno packaging, ffmpeg tentative for Phase 2

## 2026-09-19 (Frontend Implementation)

- Built complete Flux frontend in `src/flux/frontend/` with Vue 3 (vendored) + Tailwind CSS (compiled via standalone CLI)
- Implemented all 8 components: AppHeader, DropZone, FileList, FileRow, FormatSelect, ProgressBar, ThemeToggle, AppFooter
- Created 2 composables: useTheme (light/dark with OS detection + localStorage persistence), useFlux (pywebview API wrapper with mock fallbacks)
- Added Inter font (variable TTF) bundled locally with system-ui fallback
- Implemented design system per spec: CSS variables for both themes, semantic Tailwind classes, 14px base, rounded-lg, 1px borders
- Color palette: Light (bg #FAFAFA, surface #FFFFFF, border #E4E4E7, text #0B0B0D, muted #52525B) / Dark (bg #0B0B0D, surface #141417, border #2A2A30, text #F4F4F5, muted #A1A1AA)
- Accent crimson #DC143C with hover/active/tint variants; success #22C55E; errors use crimson
- Theming: Tailwind darkMode: 'class', inline script in index.html prevents flash, ThemeToggle with sun/moon icons, keyboard accessible, crimson focus ring
- Layout: ~900x600 resizable, min-width 640px, header/dropzone/filelist/footer structure
- All interactive states: hover, focus-visible (crimson ring), active, disabled
- Empty, loading, error, success states for all data-bearing components
- prefers-reduced-motion respected (disables all transitions/animations)
- Relative asset paths for file:// and PyInstaller compatibility
- Tailwind rebuild command: `npx tailwindcss -i ./assets/input.css -o ./assets/app.css --config ./tailwind.config.js`
## 2026-09-30 (Phase 1.1 - ICO, AVIF, GIF)

Delivered in six phases, each independently shippable.

- Foundation: replaced the hardcoded `TARGETS_BY_INPUT` table with a matrix derived
  from `getSupportedFormats()`. The format list was duplicated in five places
  (converter, `main.js`, `FormatSelect.js`, the `useFlux.js` dev mock, and the
  `pickFiles` dialog filter) with nothing keeping them in agreement.
  - `_save` now rejects any target with no encoder instead of falling through to
    the last branch, which would have written WebP bytes under a new extension.
  - Extracted `FluxAPI._mime_type_for` out of `getFilePreview`, and added
    `tests/test_formats.py` to pin the remaining frontend shadows to the backend.
  - Fixed a latent bug while generalizing: the picker reports `jpeg` while the
    backend normalizes to `jpg`, so a dropped `.jpeg` matched no target row.
- ICO: multi-size output (16/32/48/256), square-padded with real transparency.
  Two Pillow behaviours had to be worked around - `thumbnail()` preserves aspect
  ratio (non-square sources produced non-square icon frames), and `_save` silently
  skips sizes larger than the source, so a source below every default size wrote
  an ICO header declaring zero images.
- GIF static: palette reduction reserving one index for transparency, cutting
  partial alpha at a threshold. `Image.quantize(colors=..., dither=...)` silently
  ignores `dither` unless a reference palette is passed, so the palette is built
  first and the image requantized against it - which is also the only case where
  dithering does anything.
- GIF animation: animated sources keep every frame, per-frame duration and
  disposal. Non-GIF targets still collapse to the poster frame.
- AVIF: via Pillow's native libavif - no `pillow-avif-plugin`, so no new
  dependency and no installer growth (PyInstaller already bundled
  `PIL/_avif.pyd` before this phase). Gated on `features.check("avif")` so a build
  without libavif omits the format rather than failing at save time.
- Options UI: new `ConversionOptions` component with a quality slider and a GIF
  dithering toggle, shown only when a pending row targets a format that uses them.
  Quality stays null until touched, so each format keeps its own default
  (90 for JPG/WebP, 80 for AVIF) instead of one forced number.
- Verified: all 30 cross-format pairs, transparency across every alpha-capable
  target, animation timing, AVIF quality/ICC. Frozen build confirmed to contain
  `PIL.AvifImagePlugin` (PYZ) and `PIL._avif` (binary archive).
- Tests: 39 -> 81.

## 2026-10-02 (Project site)

Added `docs/index.html`, a single-page site for the application: what Flux
does, the six formats and the thirty conversion paths between them, the release
log and recent commits. It reuses the app's own design system - the CSS tokens
from `input.css`, the vendored Inter font, the logo artwork and the `flux-theme`
storage key - so the site and the desktop app cannot drift apart.

- Two workflows. `update-cache.yml` writes `docs/cache.json` on release publish,
  hourly and on manual dispatch, using curl + jq so no new dependency enters the
  project. `pages.yml` deploys the site to GitHub Pages. Rationale for the cache
  shape and for REST over GraphQL in DECISIONS 2026-10-02.
- The page prefers `cache.json` and falls back to the GitHub REST API, so it
  still works when opened from file:// where a sibling fetch is CORS-blocked.
  The version badge, artifact names and latest-version row all come from the
  same data.
- Deploy assembles `_site/` rather than uploading the repository: the URL is
  the site root rather than /docs/, and src/, tests/ and scripts/ are not
  published. It rewrites the page's `../src/flux/assets/` references as it
  copies, which keeps the artwork in one place instead of duplicated into
  docs/.

Bugs found and fixed while building it:

- The theme toggle rendered both icons. `.icon-btn svg { display: block }`
  outranks the UA stylesheet's `[hidden] { display: none }`, so the hidden
  attribute did nothing - and `hidden` is an HTMLElement property, so setting it
  on an <svg> was unreliable anyway. The swap is now CSS driven by the `.dark`
  class, with no JavaScript involved.
- The logo was stretched ~15%. logo-dark.png and logo-light.png are portrait
  (251x290), not square, so a fixed width fought the intrinsic aspect ratio. They
  are sized by height alone now. The SVG had hidden this because it is square.
- Crimson #DC143C fails WCAG AA as text: 3.94:1 on the dark background and 3.70:1
  on its own tint. Measured every text and graphic pair rather than sampling it -
  five failures, now zero. Crimson stays where 3:1 applies (buttons, borders,
  graphics) and every label uses --color-text or --color-muted. The green used
  for matrix cells measured 2.07:1 on the light surface and was replaced.

CodeQL reported js/incomplete-multi-character-sanitization on the API fallback's
stripHTML. Valid on both counts: the sink was innerHTML, which does not run
<script> but does fetch <img src>, so an onerror payload in a release body would
fire - reachable exactly when cache.json is absent. And a single regex pass can
leave a tag re-formed, which is what the rule documents. Replaced with DOMParser,
which builds an inert document where scripts never run and no resources are
fetched. The page now has no innerHTML, outerHTML, insertAdjacentHTML,
document.write, eval or new Function.

Review findings fixed afterwards:

- The release-triggered cache run checked out the tag, so HEAD was detached and a
  bare `git push` failed. Now pushes HEAD:main.
- The download button pointed at releases/latest, which returns text/html. It now
  resolves to the versioned asset, verified to return Content-Disposition:
  attachment.
- The API fallback supplied no `latest`, so the version badge and artifact row
  stayed blank on the file:// path.
- The Pages path filter missed the vendored font directory, so a font-only change
  left the deployed site stale.
- The jq text filter stripped tags but left script and style block contents as
  visible text, unlike build_cache.py and the page's DOMParser path.

One review finding was checked and rejected: the claim that
`${GITHUB_TOKEN:+-H "Authorization: Bearer $GITHUB_TOKEN"}` passes its quotes
through as literals. Tested in Git Bash - curl receives exactly two arguments.

## 2026-10-10 (Site data layer)

- Deleted the whole cache pipeline: `update-cache.yml`, `docs/cache.json`, `scripts/build_cache.py` and `scripts/build_cache.jq`. The site now fetches the GitHub REST API on every load with a terminal 2-minute localStorage copy. Rationale in DECISIONS 2026-10-10.
- Merged PR #10 (`ee2affa`), closing the review round: the cache was made cache-first so the fetch is skipped entirely while a fresh copy exists, and the failure message now links to GitHub instead of printing the words.
- Verified in headless Chrome that the cached path makes zero network calls, by blocking `api.github.com` and requiring the cached copy to render anyway.

## 2026-10-14 (Audit fixes)

- Audited the app before the HEIF/HEIC/SVG work and found seven defects; all are now fixed and each new test was proven able to fail before being kept.
- The preselected conversion target was AVIF for every dropped file, because `getDefaultTargetFormat` took `targets[0]` of a sorted matrix. Now driven by an explicit `TARGET_PREFERENCE` with AVIF last (DECISIONS 2026-10-14).
- Six further defects in the same area, all fixed: `getSupportedFormats()` under-reported `jpeg`; dropped files were matched to rows by name alone; duplicate detection dropped distinct files sharing name and size; a batch with the same input twice shared one output and lost the second; pruned rows leaked object URLs; and the preview allowlist admitted `.bmp`/`.tif`/`.tiff`, which Flux cannot convert.
- Packaging: PyInstaller moved out of runtime dependencies, the installer's fallback version corrected from 0.1.0, and the Inno script now declares the x64 architecture it actually builds (DECISIONS 2026-10-14).
- Two follow-up review findings on those fixes: dropped rows with no path are no longer discarded by the duplicate check, and `check-frontend.js` now runs a behavioural check on the default-target derivation - reverting to `targets[0]` left the pytest green, which is what the review caught.
- Raised the HEIF/HEIC/SVG issue, then scoped SVG out: neither rasterizer works on this host (cairosvg needs a native cairo library no wheel ships; svglib's renderer is cairo-backed too), and raster-to-SVG output cannot be done honestly.

## 2026-10-15 (Phase 1.3 - HEIF/HEIC)

- Implemented HEIF/HEIC conversion support, taking Flux from 6 to 7 formats (42 cross-pairs). SVG remains out of scope per the 2026-10-14 decision.

- Added `pillow-heif>=1.8.1` as the second runtime dependency (deliberate exception to Architecture decision 3), capability-gated exactly like AVIF: a build without the dependency simply does not offer HEIF. Rationale in DECISIONS 2026-10-15.

- `.heic` and `.heif` both accepted as inputs (same container); `heic` is the single canonical output, following the `jpeg`/`jpg` precedent. `normalize_format` and the frontend's `normalizeExt` both map `heif` ? `heic`.

- HEIF save branch reuses the lossy quality path (default 90, matching JPEG/WebP rather than AVIF's 80 - HEVC coding is roughly JPEG-comparable).

- `flux.spec` now collects pillow-heif's root-level binaries (`libheif-<hash>.dll` and `_pillow_heif.*.pyd`) explicitly - PyInstaller's static analysis would miss them, and a frozen exe without libheif fails to open `.heic` files while passing the `--version` smoke test. Pinned by `test_spec_collects_pillow_heif_binaries`.

- Extended `window.py`'s preview allowlist and `pickFiles` filter, `main.js`'s `LOSSY_TARGETS` and `TARGET_PREFERENCE`, and `useFlux.js`'s dev mock - all four format touch points updated deliberately, as `test_formats.py` pins them.

- Tests: 95 ? 110. New HEIF tests cover quality option, quality clamping, transparency preservation, dual-extension input, readback into every target, and the absence gate. All gates green: pytest 110 passed, frontend checks pass, pyright 0 errors, mypy clean.

- Docs updated: PRD Phase 1.3 section and acceptance criteria, ARCHITECTURE runtime-dependency table, DECISIONS two new ADRs (pillow-heif dependency; HEIC canonical output).

## 2026-10-19 (Code review fixes)

- Fixed two issues flagged during review of the HEIF/HEIC feature:

  1. **flux.spec: pillow-heif import is now guarded.** The `_pillow_heif_binaries()` function wrapped `import pillow_heif` in try/except, returning `[]` when the package is absent. This prevents PyInstaller builds from failing before the app can apply its runtime gate.

  2. **test_formats.py: added HEIF gateway handling.** `test_frontend_mock_matches_backend_formats` now strips heic/heif from the mock when `_heif_available()` is false, matching AVIF's treatment. Without this, a dev environment missing pillow-heif would see stale entries in the browser fallback picker.
