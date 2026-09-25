from __future__ import annotations

import os
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


def _debug_enabled() -> bool:
    """Whether FLUX_DEBUG asks for verbose diagnostics from a packaged build.

    The executable is windowed (console-less), so pywebview's debug output -
    and everything written by _log - reaches a terminal only when the process
    is launched with its std handles wired up (a developer prompt, or
    ``Start-Process -RedirectStandardError``). Setting FLUX_DEBUG=1 therefore
    costs nothing for end users and turns the built flux.exe into a debuggable
    build: ``webview.start(debug=True)`` plus the resolved-path logging below.
    """
    return os.environ.get("FLUX_DEBUG", "").strip().lower() in {"1", "true", "yes"}


def _log(text: str) -> None:
    """Best-effort stderr diagnostic line (no-op unless FLUX_DEBUG is set).

    sys.stderr is None when nothing supplies a handle (the usual Explorer
    launch of a windowed exe), so this must never raise - diagnostics are not
    worth crashing the app over.
    """
    if not _debug_enabled():
        return
    stream = getattr(sys, "stderr", None)
    if stream is None:
        return
    try:
        print(f"[flux] {text}", file=stream, flush=True)
    except (OSError, ValueError):
        pass


def _bundled_path(*parts: str) -> Path:
    """Resolve a data file shipped with the app, in source runs and frozen builds.

    ``flux.spec`` bundles the runtime data files with a ``flux/`` destination
    (``("src/flux/frontend", "flux/frontend")``), so inside a one-file build
    they sit at ``<sys._MEIPASS>/flux/...`` - the same position the package
    occupies in a source checkout (``src/flux/...``).

    For every module imported out of the bundle, ``__file__`` points at exactly
    that package directory - *except for the entry script*. PyInstaller runs
    ``src/flux/main.py`` as ``__main__`` with ``__file__`` set to
    ``<sys._MEIPASS>/main.py``, one level *above* the package, so deriving the
    frontend/icon paths from ``Path(__file__).parent`` resolved to
    ``<sys._MEIPASS>/frontend/...`` in the packaged app: the files were in the
    bundle (under ``flux/``), the lookup missed them, and the window started on
    WebView2's ``ERR_FILE_NOT_FOUND`` page instead of the UI. Anchoring frozen
    runs at ``sys._MEIPASS / "flux"`` gives both layouts one rule.
    """
    if getattr(sys, "frozen", False):
        # sys._MEIPASS only exists in the frozen app (see flux.spec).
        base = Path(getattr(sys, "_MEIPASS")) / "flux"  # type: ignore[arg-type]
    else:
        base = Path(__file__).resolve().parent
    return base.joinpath(*parts)


def create_window() -> webview.Window | None:
    registry = ConverterRegistry()
    registry.register(PillowImageConverter())

    api = FluxAPI(registry)

    frontend_path = _bundled_path("frontend", "index.html")
    _log(f"frontend={frontend_path} exists={frontend_path.is_file()}")
    if not frontend_path.is_file():
        # Fail loudly instead of parking the user on an opaque
        # ERR_FILE_NOT_FOUND page: the windowed build shows this traceback in
        # a dialog (disable_windowed_traceback=False in flux.spec) and stderr
        # carries it whenever a handle is attached.
        raise FileNotFoundError(
            f"bundled frontend not found: {frontend_path} "
            f"(frozen={getattr(sys, 'frozen', False)}, __file__={__file__})"
        )
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
    icon_path = _bundled_path("assets", "favicon.ico")
    _log(f"icon={icon_path} exists={icon_path.is_file()}")
    webview.start(icon=str(icon_path), debug=_debug_enabled())


if __name__ == "__main__":
    main()