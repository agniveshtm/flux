# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Flux Windows executable.
#
#   uv run pyinstaller flux.spec     -> dist/flux.exe (one-file, windowed)
#
# dist/flux.exe is uploaded to each GitHub release as the portable build and
# is the input for installer/flux.iss, which packages it into
# dist/flux-setup-<ver>.exe. Both artifacts are published by
# .github/workflows/release.yml on every v* tag.

from PyInstaller.utils.hooks import collect_submodules

# pywebview resolves its platform backend by name at runtime (webview.util
# picks winforms/edgechromium/etc. after startup), so static analysis alone
# can miss webview.platforms.* imports and the frozen app would die with a
# "backend not found" error on launch. Collecting every submodule up front
# removes that race. webview's own bundled hook (webview/__pyinstaller) is
# auto-discovered via the pyinstaller40 entry point and adds the js/ and
# lib/ data files (WebView2 interop DLLs) on top of this.
hiddenimports = collect_submodules("webview")

a = Analysis(
    ["src/flux/main.py"],
    # src-layout: tells the analyzer where the `flux` package lives.
    pathex=["src"],
    binaries=[],
    datas=[
        # Runtime static files, looked up through flux.main._bundled_path().
        # Modules imported from the bundle get __file__ = <_MEIPASS>/flux/...,
        # so the "flux/" destination lines up with the source layout
        # (src/flux/...) for them. The entry script is the exception - PyInstaller
        # runs it with __file__ = <_MEIPASS>/main.py, one level above the
        # package - which is why _bundled_path anchors frozen runs at
        # sys._MEIPASS/"flux" instead of Path(__file__).parent. Keep both
        # sides in sync; tests/test_main.py pins the contract.
        ("src/flux/frontend", "flux/frontend"),
        ("src/flux/assets", "flux/assets"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="flux",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # GUI application: end users must not get a console window. A windowed
    # build still gets a working sys.stdout when the parent supplies a handle,
    # which is what the release smoke test relies on: -RedirectStandardOutput
    # gives the process a real stdout pipe, so `flux.exe --version` prints the
    # version on it and the workflow can assert the text, not just the exit
    # code. sys.stdout is None only when nothing provides a handle (Explorer).
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="src/flux/assets/favicon.ico",
)