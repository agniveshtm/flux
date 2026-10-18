"""The installer's fallback version must track pyproject.toml.

installer/flux.iss ships a #define fallback for manual local builds, because
CI always passes /DMyAppVersion and never exercises it - which is how it drifted
to 0.1.0 while the project was at 0.2.0 and produced a mislabelled
flux-setup-<ver>.exe for anyone building locally.

Also covers flux.spec: pillow-heif's binaries sit at site-packages root rather
than inside the package, so PyInstaller's static analysis would miss them
without an explicit collection step - and a frozen exe missing libheif fails
to open .heic files with an error the release smoke test does not catch.
"""

from __future__ import annotations

import re
from pathlib import Path

from flux import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
ISS = REPO_ROOT / "installer" / "flux.iss"
SPEC = REPO_ROOT / "flux.spec"


def _iss_fallback_version() -> str:
    match = re.search(
        r'#define MyAppVersion "([^"]+)"', ISS.read_text(encoding="utf-8")
    )
    assert match, "MyAppVersion fallback not found in installer/flux.iss"
    return match.group(1)


def test_installer_fallback_version_matches_the_release() -> None:
    assert _iss_fallback_version() == __version__, (
        f"installer/flux.iss falls back to {_iss_fallback_version()!r} but the "
        f"project is at {__version__!r}; a local build without "
        "/DMyAppVersion would be mislabelled"
    )


def test_installer_declares_the_built_architecture() -> None:
    # PyInstaller on x64 Python produces an x64 exe. ArchitecturesAllowed's
    # default depends on whether ISCC emits a 32-bit or 64-bit Setup - and on
    # 32-bit Setup it is x86compatible, which would install this x64 app on
    # 32-bit Windows. The pair below is Inno's own documented example for a
    # 64-bit-only app (x64 plus Arm64, which runs x64 under emulation).
    source = ISS.read_text(encoding="utf-8")
    assert "ArchitecturesAllowed=x64compatible" in source, (
        "installer/flux.iss does not restrict the install to x64-compatible "
        "systems; on a 32-bit Setup the default would allow 32-bit Windows"
    )
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in source


def _spec_heif_binaries() -> list[tuple[str, str]]:
    """Execute flux.spec's _pillow_heif_binaries() for this platform.

    The function is extracted from the spec source rather than imported,
    because importing flux.spec would run PyInstaller's Analysis at module
    level. Executing the shipped function (rather than re-deriving its globs
    here) is what makes this a behavioural check: a regression in the spec's
    collection logic fails this test on both OS legs.
    """
    import os
    from typing import Any, Callable, cast

    source = SPEC.read_text(encoding="utf-8")
    match = re.search(
        r"(?ms)^def _pillow_heif_binaries\(\).*?(?=^\S|\Z)", source
    )
    assert match, "_pillow_heif_binaries not found in flux.spec"
    namespace: dict[str, Any] = {"os": os}
    exec(compile(match.group(0), str(SPEC), "exec"), namespace)
    fn = namespace["_pillow_heif_binaries"]
    assert callable(fn)
    return cast(Callable[[], list[tuple[str, str]]], fn)()


def test_spec_collects_pillow_heif_binaries() -> None:
    """flux.spec must bundle pillow-heif's native extension and libheif.

    pillow-heif's libraries do not sit inside the package directory: on
    Windows both parts are at site-packages root (_pillow_heif.*.pyd and
    libheif-<hash>.dll); on Linux the extension is at root while libheif
    lives in pillow_heif.libs/ under a versioned name (auditwheel). PyInstaller's
    static analysis references the extension but not the library, so without
    the spec's explicit collection the frozen exe would fail to open .heic
    files while passing the --version smoke test.
    """
    binaries = _spec_heif_binaries()
    names = [Path(src).name for src, _dest in binaries]

    assert any(name.startswith("_pillow_heif.") for name in names), (
        f"no _pillow_heif native extension collected from {names}"
    )
    assert any("libheif" in name for name in names), (
        f"no libheif library collected from {names}"
    )
    for src, dest in binaries:
        assert Path(src).is_file(), f"collected binary does not exist: {src}"
        assert dest, f"collected binary has no destination: {src}"
