<div align="center">
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="src/flux/assets/logo-dark.png">
    <img src="src/flux/assets/logo-light.png" alt="Flux" width="150">
  </picture>
</div>

Convert images between JPG, PNG and WebP in a fast, offline desktop app.

## Features

- 🖼️ **Drag & drop or pick** — drop images onto the window or use **Select files**; dropped files keep their real paths (a Python-side drop listener delivers them over the bridge).
- 🔁 **Batch conversion** — queue as many files as you like and hit **Convert all**; files are grouped by target format and each row finishes with its own status.
- 🎛️ **Per-file format picker** — switch any row between JPG ⇄ PNG ⇄ WebP; a sensible target is preselected based on the input format.
- 👁️ **Previews** — every row shows a thumbnail; click it for a fullscreen preview modal with an alpha checkerboard backdrop.
- 📊 **Live progress** — per-row progress bars stream from Python as `flux-progress` events, so conversions never freeze the UI.
- 📁 **Sticky output folder** — pick an output folder once (it is remembered) and jump to it with **Open output folder**.
- 🌗 **Light / dark theme** — follows the OS until you choose a side, then remembers your choice.
- 🔔 **In-app updates** — a bell in the header shows a yellow badge when a newer GitHub release exists; download it with live progress and speed, then restart straight into the new version.
- 🔒 **Offline-first** — Vue, Tailwind and the Inter font are vendored/committed; there is no CDN and no runtime network call except the update check.
- 🧩 **Extensible converters** — every format family plugs into a single `BaseConverter` interface (images today).

> **Network note:** Flux has no background network traffic — the only requests it ever makes are the once-per-launch GitHub release check (silent when it fails) and the download of an update you explicitly start. Everything else, including all conversions, runs locally.

## Architecture

```
flux/
├── .github/
│   └── workflows/
│       ├── test.yml              # CI: pytest matrix, frontend checks, CSS freshness, Inno script
│       └── release.yml           # CD: v* tags → flux.exe + flux-setup-<ver>.exe on the release
├── installer/
│   └── flux.iss                  # Inno Setup script (packages dist/flux.exe into the setup)
├── scripts/
│   └── check-frontend.js         # node syntax/template/index checks (no npm dependencies)
├── docs/
│   ├── PRD.md                    # Product requirements & scope
│   ├── ARCHITECTURE.md           # Layers, bridge API surface, threading model
│   ├── DECISIONS.md              # Architecture decision records
│   └── timeline.md               # Build log
├── src/
│   └── flux/
│       ├── __init__.py           # __version__ - the runtime version source
│       ├── main.py               # Entry point: pywebview window, --version / --help
│       ├── window.py             # FluxAPI - the JS ↔ Python bridge (and updater entry points)
│       ├── converter.py          # BaseConverter ABC, registry, format normalization
│       ├── services/
│       │   ├── image_converter.py  # PillowImageConverter (JPG/PNG/WebP)
│       │   └── updater.py          # GitHub release check + installer download
│       ├── assets/               # Logos, favicons, app icon
│       └── frontend/             # Vue 3 + Tailwind (vendored, no bundler)
│           ├── index.html
│           ├── main.js           # App state and wiring
│           ├── components/       # AppHeader, UpdateBell, DropZone, FileList, FileRow, ...
│           ├── composables/      # useFlux (bridge calls), useTheme
│           ├── assets/           # input.css (source) + app.css (compiled, committed)
│           └── vendor/           # vue.global.prod.js
├── tests/                        # pytest suite (version sync + updater primitives)
├── flux.spec                     # PyInstaller spec → dist/flux.exe
├── pyproject.toml                # Metadata, deps, uv_build backend
└── uv.lock                       # Locked dependency graph
```

## Flow

```
   Drop files / Select files
             │
             ▼
┌────────────────────────────┐
│  Rows appear               │  name · size · thumbnail · target format
│  (Python pushes real paths │
│   back as dropped paths)   │
└────────────────────────────┘
             │  Convert all
             ▼
┌────────────────────────────┐        ┌────────────────────────────────┐
│  Bridge: convert(files,    │───────▶│  PillowImageConverter          │
│  format, { outputDir })    │        │  open → transform → save       │
│  → returns jobId at once   │        └────────────────────────────────┘
└────────────────────────────┘                        │ progress_cb(i, n)
             ▲                                        ▼
             │  flux-progress events        ┌────────────────────────────────┐
             │  { jobId, status, progress } │  FluxAPI._emit_progress        │
             │                              │  (worker thread → evaluate_js) │
             └──────────────────────────────┴────────────────────────────────┘
```

## Update flow

```
  Bell badge          checkForUpdate        GitHub /releases/latest
  (newer release) ◀── (once per launch) ◀── (draft/prerelease excluded)
        │
        ▼  Download update
  flux-setup-<ver>.exe streamed to the temp dir
  (flux-update-progress events: %, bytes, speed)
        │
        ▼  Restart & update
  setup runs /SILENT → Flux closes → files replaced → Flux relaunches
```

## Tech Stack

| Category       | Technology                                                                 |
| -------------- | -------------------------------------------------------------------------- |
| Shell          | [pywebview](https://pywebview.flowrl.com/) (WebView2 on Windows)            |
| Backend        | Python 3.12                                                                 |
| Image engine   | [Pillow](https://python-pillow.org/)                                        |
| Frontend       | [Vue 3](https://vuejs.org/) global build, vendored — no bundler, no build step |
| Styling        | [Tailwind CSS](https://tailwindcss.com/) v3, compiled via the standalone CLI (`app.css` committed) |
| Theming        | CSS variables + `dark` class, OS detection, `localStorage` persistence       |
| Bridge         | `window.pywebview.api` calls + `CustomEvent` progress streams                |
| Updates        | GitHub Releases API via the standard library (`urllib`) — no extra deps      |
| Packaging      | [PyInstaller](https://pyinstaller.org/) one-file exe + [Inno Setup](https://jrsoftware.org/isinfo.php) installer |
| CI/CD          | GitHub Actions (`.github/workflows/test.yml`, `release.yml`) + [uv](https://docs.astral.sh/uv/) |
| Testing        | pytest (backend) + node frontend checks (syntax, templates, page wiring)     |

## Usage

Launch the app (no flags) to get the window — a 900×600 resizable frame, minimum 640×400.

| Area        | What you get                                                                    |
| ----------- | ------------------------------------------------------------------------------- |
| **Header**  | Flux wordmark, update bell, light/dark toggle                                    |
| **Drop zone** | Drag & drop or click; turns crimson while dragging over                        |
| **File list** | Toolbar (file count, converted count, Clear all) + rows with thumbnail, name, size, format picker, status badge, progress bar, remove button |
| **Footer**  | Convert all · Open output folder · output folder picker · Clear completed        |

### Update bell

| Action                    | What it does                                                                                     |
| ------------------------- | ------------------------------------------------------------------------------------------------ |
| **Download update**       | Streams `flux-setup-<version>.exe` to a temp folder; the card shows version, size, %, speed and bytes transferred |
| **Dismiss**               | Hides the badge for this session (it returns on the next launch)                                  |
| **Mark as read / Mark all as read** | Remembers the version, so the badge stays away until a newer release appears             |
| **Restart & update**      | Runs the downloaded setup silently (per-user, no UAC prompt) and relaunches Flux on the new version |

### CLI

| Command              | Description                                                       |
| -------------------- | ----------------------------------------------------------------- |
| `flux`               | Launch the desktop app (the normal way to use it)                  |
| `flux --version`     | Print the version and exit (also the CI smoke test)                |
| `flux --help`        | Print usage and exit                                               |

Example:

```bash
flux --version     # flux 0.1.0
```

## Testing

```bash
uv run pytest tests/              # backend: version sync + updater primitives
node scripts/check-frontend.js    # frontend: syntax, Vue templates, page wiring
```

`uv run pytest tests/`:

```
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\Projects\flux
configfile: pyproject.toml
collected 16 items

tests\test_updater.py ..............                                     [ 87%]
tests\test_version.py ..                                                 [100%]

============================= 16 passed in 0.09s ==============================
```

`node scripts/check-frontend.js` (abridged):

```
ok    src/flux/frontend/components/UpdateBell.js syntax
ok    src/flux/frontend/composables/useFlux.js loads
ok    src/flux/frontend/components/FileList.js template compiles
ok    index.html script tags match files on disk

all frontend checks passed
```

The frontend script has no npm dependencies: it runs `node --check` over every script, compiles each component template with the **vendored Vue build the app ships**, and fails if `index.html` and the files on disk disagree about which components exist.

### CI

`.github/workflows/test.yml` runs on pushes to `main`/`feature` and on pull requests:

| Job                  | What it verifies                                                                              |
| -------------------- | --------------------------------------------------------------------------------------------- |
| `python` (ubuntu + windows) | pytest on both platforms, plus `flux.spec` syntax                                        |
| `frontend`           | `scripts/check-frontend.js` — syntax, template compilation, `index.html` wiring                |
| `css`                | rebuilds Tailwind with the pinned version and fails if the committed `app.css` is stale        |
| `installer`          | compiles `installer/flux.iss` with ISCC and asserts the setup artifact is produced             |

## Installation

### Prerequisites

- **Windows 10/11** with the WebView2 runtime — preinstalled on Windows 11 and present on Windows 10 with a current Edge.
- **Python 3.12+** and [uv](https://docs.astral.sh/uv/) — only when installing from source.

### Install via the Windows setup (recommended)

Download `flux-setup-<version>.exe` from [Releases](https://github.com/agniveshtm/flux/releases), run it, and launch Flux from the Start Menu.

- Per-user install (`%LOCALAPPDATA%\Programs\Flux`) — no admin prompt, no UAC on updates
- Start Menu entry always; optional desktop shortcut
- Uninstall from *Apps & features* / *Add or remove programs*

### Install via the portable executable

Download `flux.exe` from [Releases](https://github.com/agniveshtm/flux/releases) and run it — no installation and no Python required.

> **Tip:** Releases carry both artifacts. The setup is what the in-app updater downloads, so installed copies upgrade themselves in place.

### Install from source (development)

```bash
git clone https://github.com/agniveshtm/flux.git
cd flux
uv sync
uv run flux
```

Release artifacts are the exe and the installer only — no wheel or sdist is published. On macOS/Linux the app runs from source wherever pywebview has a native backend (WebKit, GTK or Qt).

## Building & releasing

Build the artifacts locally:

```bash
uv run pyinstaller flux.spec                    # → dist/flux.exe
ISCC /DMyAppVersion=0.1.0 installer\flux.iss    # → dist/flux-setup-0.1.0.exe
```

Cut a release:

```bash
# 1. bump the version in BOTH pyproject.toml and src/flux/__init__.py
# 2. tag it and push
git tag v0.1.0
git push origin v0.1.0
```

`release.yml` then verifies that the tag, `pyproject.toml` and `flux.__version__` all agree, runs the test suite, builds `flux.exe` (smoke-tested via `--version`), compiles the installer with that version, and publishes both files on the release with auto-generated notes. The tag version is what the updater compares against, so the three-way check is what keeps updates working for everyone already installed.

## Documentation

- [docs/PRD.md](docs/PRD.md) — product requirements, scope and success criteria
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — layers, bridge API surface, threading, update design
- [docs/DECISIONS.md](docs/DECISIONS.md) — architecture decision records (Pillow, pywebview, packaging, updater)
- [docs/timeline.md](docs/timeline.md) — chronological build log

## Project Links

- [pywebview](https://pywebview.flowrl.com/) — native-window shell and JS ↔ Python bridge
- [Pillow](https://python-pillow.org/) — image decoding/encoding
- [Vue 3](https://vuejs.org/) — frontend framework (vendored global build)
- [Tailwind CSS](https://tailwindcss.com/) — styling (compiled CSS committed)
- [uv](https://docs.astral.sh/uv/) — dependency sync, packaging and tooling
- [PyInstaller](https://pyinstaller.org/) — standalone executable builds
- [Inno Setup](https://jrsoftware.org/isinfo.php) — Windows installer and silent upgrades
- [GitHub Repository](https://github.com/agniveshtm/flux)
- [Releases](https://github.com/agniveshtm/flux/releases)

## License

[MIT](LICENSE) © 2026 [agniveshtm](https://github.com/agniveshtm)



