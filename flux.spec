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
        # Runtime static files. The code resolves them as
        # Path(__file__).parent / "frontend" (and "assets"); PyInstaller
        # reports compiled modules' __file__ bundle-relative, so the
        # destination must be "flux/..." for those paths to line up inside
        # the bundle.
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
    # GUI application: end users must not get a console window. The release
    # smoke test (`flux.exe --version`) therefore only trusts the exit code.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="src/flux/assets/favicon.ico",
)