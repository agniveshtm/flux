"""The installer's fallback version must track pyproject.toml.

installer/flux.iss ships a #define fallback for manual local builds, because
CI always passes /DMyAppVersion and never exercises it - which is how it drifted
to 0.1.0 while the project was at 0.2.0 and produced a mislabelled
flux-setup-<ver>.exe for anyone building locally.
"""

from __future__ import annotations

import re
from pathlib import Path

from flux import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
ISS = REPO_ROOT / "installer" / "flux.iss"


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
