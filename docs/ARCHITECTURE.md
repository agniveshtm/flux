# Flux — Architecture

## System Layers & Data Flow

```mermaid
flowchart LR
    subgraph Desktop["pywebview Window (Native)"]
        FE["Vue 3 Frontend\n(src/flux/frontend)"]
    end

    Bridge["window.pywebview.api\n(JS ↔ Python Bridge)"]

    subgraph Backend["Python Backend (src/flux)"]
        API["API Layer\n(window.py)"]
        Conv["Converter Interface\n(converter.py)"]
        ImgConv["PillowImageConverter\n(image_converter.py)"]
        FS["Filesystem\n(OS)"]
    end

    FE -- "convert(files, format, options)" --> Bridge
    Bridge -- "calls Python API" --> API
    API -- "delegates to" --> Conv
    Conv -- "uses" --> ImgConv
    ImgConv -- "reads/writes" --> FS
    ImgConv -- "progress callbacks" --> API
    API -- "emits progress events" --> Bridge
    Bridge -- "updates UI" --> FE
```

## API Surface (Exposed to Frontend)

| Method | Arguments | Returns | Errors |
|--------|-----------|---------|--------|
| `convert` | `{ files: File[], targetFormat: string, options?: object }` | `{ jobId: string }` | `VALIDATION_ERROR`, `UNSUPPORTED_FORMAT` |
| `getProgress` | `{ jobId: string }` | `{ status: 'pending'\|'running'\|'complete'\|'error', progress: 0-100, outputPaths?: string[], error?: string }` | `NOT_FOUND` |
| `cancel` | `{ jobId: string }` | `{ cancelled: boolean }` | `NOT_FOUND`, `ALREADY_COMPLETE` |
| `getSupportedFormats` | — | `{ input: string[], output: string[] }` | — |
| `pickFiles` | `{ multiple?: boolean }` | `{ paths: string[] }` | `CANCELLED` |
| `pickOutputDir` | — | `{ path: string }` | `CANCELLED` |

**Error shape**: `{ code: string, message: string, details?: object }`

## Threading & Progress Reporting

- **UI thread**: pywebview main loop + Vue frontend (single-threaded JS)
- **Conversion thread**: Each `convert` call spawns a `threading.Thread` running the converter
- **Progress channel**: Converter accepts a `progress_cb(current, total)` callable; backend pushes updates via `window.evaluate_js()` to a Vue-side event bus
- **Job registry**: In-memory dict `jobId → { thread, converter, status, progress, outputPaths, error }`; cleaned up on completion or explicit cancel
- **Cancellation**: Cooperative — converter checks a `threading.Event` flag between files/operations

## Converter Interface (Extensible for Phase 2)

```python
# src/flux/converter.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional

@dataclass
class ConversionResult:
    output_paths: list[str]
    errors: list[str]

class BaseConverter(ABC):
    @property
    @abstractmethod
    def supported_input_formats(self) -> list[str]: ...

    @property
    @abstractmethod
    def supported_output_formats(self) -> list[str]: ...

    @abstractmethod
    def convert(
        self,
        input_paths: list[str],
        output_dir: str,
        target_format: str,
        options: dict,
        progress_cb: Callable[[int, int], None],
        cancel_event: threading.Event,
    ) -> ConversionResult: ...
```

- **Phase 1**: `PillowImageConverter` implements `BaseConverter`
- **Phase 2**: `FFmpegVideoConverter` will implement same interface; frontend contract unchanged
- **Registry**: `ConverterRegistry` maps format → converter instance; `get_converter_for_format()` selects at runtime

## Folder Structure

```
flux/
├── docs/
│   ├── PRD.md
│   ├── timeline.md
│   ├── ARCHITECTURE.md
│   └── DECISIONS.md
├── src/
│   └── flux/
│       ├── __init__.py
│       ├── main.py                 # pywebview entry point
│       ├── window.py               # API exposure + JS bridge
│       ├── converter.py            # BaseConverter ABC + registry
│       ├── image_converter.py      # PillowImageConverter
│       ├── assets/                 # favicons, logos
│       └── frontend/               # Vue 3 + Tailwind (vendored)
│           ├── index.html
│           ├── src/
│           │   ├── main.js
│           │   ├── App.vue
│           │   ├── components/
│           │   ├── composables/
│           │   └── styles/
│           └── dist/               # built output (committed)
├── pyproject.toml
├── uv.lock
├── .python-version
├── README.md
└── .gitignore
```

## Offline Constraints

- **No CDN**: Vue 3, Tailwind, and all dependencies vendored in `src/flux/frontend/`
- **Tailwind**: Compiled via standalone CLI (`npx tailwindcss -i ... -o ...`) at build time; no Node runtime in packaged app
- **Vue**: Pre-built `dist/` committed; `main.py` loads `file://` path to `dist/index.html`
- **Python deps**: Resolved via `uv` + `uv.lock`; PyInstaller bundles entire `.venv` site-packages
- **Assets**: All icons, logos, fonts embedded in PyInstaller bundle
- **ffmpeg (Phase 2)**: Static binary bundled alongside executable; no system dependency