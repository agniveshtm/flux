from __future__ import annotations

import sys
from pathlib import Path

import webview

from flux import __version__
from flux.converter import ConverterRegistry
from flux.services import PillowImageConverter
from flux.window import FluxAPI

_CLI_USAGE = """\
usage: flux [--help] [--version]

A desktop app for file conversions.
"""


def _cli_print(text: str) -> None:
    """Best-effort stdout write for the informational CLI flags.

    The packaged build is a windowed (console-less) executable: sys.stdout
    exists there only while the parent supplies a handle. The release smoke
    test redirects the process stdout, so the version text is delivered; a
    plain launch (e.g. from Explorer) supplies none and sys.stdout is None.
    --version and --help must exit 0 in both cases, so a missing or unusable
    stream degrades to silence instead of a traceback that would fail the
    smoke test.
    """
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return
    try:
        print(text, file=stream)
    except (OSError, ValueError):
        pass


def _handle_cli_flags(argv: list[str]) -> bool:
    """Handle --version/--help before any GUI work, and report if handled.

    The release workflow smoke-tests the built executable with --version:
    the flag path deliberately runs after the module-level imports so the
    test exercises the whole frozen import chain (webview, Pillow, the
    flux package) while never opening a window.
    """
    if "--version" in argv or "-V" in argv:
        _cli_print(f"flux {__version__}")
        return True
    if "--help" in argv or "-h" in argv:
        _cli_print(_CLI_USAGE)
        return True
    return False


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
    if _handle_cli_flags(sys.argv[1:]):
        return
    create_window()
    icon_path = Path(__file__).parent / "assets" / "favicon.ico"
    webview.start(icon=str(icon_path))


if __name__ == "__main__":
    main()