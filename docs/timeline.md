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
