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