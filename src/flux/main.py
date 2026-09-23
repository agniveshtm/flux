from __future__ import annotations

from pathlib import Path

import webview

from flux.converter import ConverterRegistry
from flux.services import PillowImageConverter
from flux.window import FluxAPI


def create_window() -> webview.Window | None:
    registry = ConverterRegistry()
    registry.register(PillowImageConverter())

    api = FluxAPI(registry)

    frontend_path = Path(__file__).parent / "frontend" / "index.html"
    window = webview.create_window(
        "Flux",
        url=frontend_path.as_uri(),
        js_api=api,
        width=900,
        height=600,
        min_size=(640, 400),
        text_select=False,
    )
    if window is not None:
        api.attach_window(window)
    return window


def main() -> None:
    create_window()
    icon_path = Path(__file__).parent / "assets" / "favicon.ico"
    webview.start(icon=str(icon_path))


if __name__ == "__main__":
    main()