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


def test_spec_collects_pillow_heif_binaries() -> None:
    """flux.spec must bundle pillow-heif's root-level binaries.

    pillow_heif ships its native extension and libheif at site-packages root,
    not inside the package directory. PyInstaller's static analysis finds the
    .pyd when pillow_heif is imported (it is referenced from Python), but
    nothing references libheif-*.dll statically - so without an explicit
    binaries= entry the frozen exe would fail to open .heic files while
    passing the --version smoke test.
    """
    import pillow_heif

    site_pkgs = Path(pillow_heif.__file__).resolve().parent.parent
    libheif = list(site_pkgs.glob("libheif-*.dll")) + list(site_pkgs.glob("libheif-*.so"))
    pyd = list(site_pkgs.glob("_pillow_heif.*.pyd")) + list(site_pkgs.glob("_pillow_heif.*.so"))

    assert libheif, f"libheif binary not found in {site_pkgs}"
    assert pyd, f"_pillow_heif extension not found in {site_pkgs}"

    # The spec must reference a binaries= collection that would pick these up.
    source = SPEC.read_text(encoding="utf-8")
    assert "_pillow_heif_binaries" in source, (
        "flux.spec does not call _pillow_heif_binaries(); libheif would not "
        "be bundled and the frozen exe could not open .heic files"
    )
    assert "binaries=_pillow_heif_binaries()" in source, (
        "flux.spec defines _pillow_heif_binaries but does not pass it to "
        "Analysis(binaries=...)"
    )
