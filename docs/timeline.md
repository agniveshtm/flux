## 2026-09-19

- Created project documentation structure (docs/ folder)
- Wrote PRD.md with Overview, Goals, Non-Goals, User Stories, Success Criteria
- Confirmed: target users = general consumers; Phase 2 (video/ffmpeg) is OUT of scope for v1.0
- Documented Phase 1 extensions as sub-phases (additional image formats beyond jpg/png/webp)
- Stack locked: Python/pywebview + Vue 3/Tailwind + Pillow + PyInstaller/Inno Setup
- Set up ARCHITECTURE.md with layers, API surface, threading model, converter interface, folder structure, offline constraints
- Logged initial ADRs in DECISIONS.md: Pillow for images, no Vite/CDN, pywebview shell, PyInstaller+Inno packaging, ffmpeg tentative for Phase 2