"""Packaging contracts: installer version, sidecar deployment and CIs.

installer/flux.iss ships a #define fallback for manual local builds, because
CI always passes /DMyAppVersion and never exercises it - which is how it drifted
to 0.1.0 while the project was at 0.2.0 and produced a mislabelled
flux-setup-<ver>.exe for anyone building locally.

The installer must also place ffmpeg.exe beside flux.exe: a frozen
build resolves the sidecar relative to sys.executable, so an installer that
packages only the Python exe silently downgrades installed copies to the
image-only app. Both workflows are pinned here because a release that forgets
to stage dist\\ffmpeg.exe fails at ISCC time and a PR that forgets the test
workflow's placeholder fails in CI.

Also covers flux.spec: pillow-heif's binaries sit at site-packages root rather
than inside the package, so PyInstaller's static analysis would miss them
without an explicit collection step - and a frozen exe missing libheif fails
to open .heic files with an error the release smoke test does not catch.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

from flux import __version__
from flux.services import ffmpeg as ffmpeg_module

REPO_ROOT = Path(__file__).resolve().parents[1]
ISS = REPO_ROOT / "installer" / "flux.iss"
SPEC = REPO_ROOT / "flux.spec"
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
TEST_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"


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


def _iss_defines() -> dict[str, str]:
    """The #define constants the .iss uses for artifact names."""
    return dict(
        re.findall(
            r'^#define\s+(\w+)\s+"([^"]+)"',
            ISS.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )


def _iss_file_entries() -> list[dict[str, str]]:
    """Parse [Files] rows into {directive: value} maps.

    Comments are skipped and {#Define} placeholders are expanded, so the
    assertions compare real paths rather than Inno preprocessor syntax.
    """
    source = ISS.read_text(encoding="utf-8")
    match = re.search(r"(?ms)^\[Files\]\s*$(.*?)(?=^\[|\Z)", source)
    assert match, "[Files] section not found in installer/flux.iss"
    defines = _iss_defines()
    entries: list[dict[str, str]] = []
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        fields: dict[str, str] = {}
        for part in line.split(";"):
            key, sep, value = part.strip().partition(":")
            if sep:
                fields[key.strip()] = value.strip().strip('"')
        if "Source" in fields:
            fields["Source"] = re.sub(
                r"\{#(\w+)\}",
                lambda m: defines.get(m.group(1), m.group(0)),
                fields["Source"],
            )
            entries.append(fields)
    return entries


def test_installer_ships_ffmpeg_beside_flux() -> None:
    """The sidecar and the exe must land in the same directory.

    locate_ffmpeg() looks for ffmpeg.exe beside sys.executable, which in an
    installed copy is {app}\\flux.exe. A different DestDir (or no sidecar row
    at all) leaves installed builds image-only while every test still passes.
    """
    defines = _iss_defines()
    assert defines.get("MyFfmpegExeName") == "ffmpeg.exe"
    entries = _iss_file_entries()
    exe = [e for e in entries if e["Source"].endswith(defines["MyAppExeName"])]
    sidecar = [e for e in entries if e["Source"].endswith(defines["MyFfmpegExeName"])]

    assert len(exe) == 1, f"expected one flux.exe row, got {exe}"
    assert len(sidecar) == 1, f"expected one ffmpeg.exe row, got {sidecar}"
    assert sidecar[0]["DestDir"] == exe[0]["DestDir"] == "{app}"
    assert "ignoreversion" in sidecar[0].get("Flags", "")


def test_installer_ships_the_sidecar_licence() -> None:
    """GPLv3's licence text must accompany the GPL ffmpeg binary."""
    defines = _iss_defines()
    entries = _iss_file_entries()
    licence = [e for e in entries if e["Source"].endswith(defines["MyFfmpegLicense"])]

    assert len(licence) == 1, f"no LICENSE-ffmpeg.txt row in [Files]: {entries}"
    assert licence[0]["DestDir"] == "{app}"


def test_frozen_ffmpeg_resolves_beside_the_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The installer's {app} row is correct because the code reads that dir.

    Pins the other half of the contract: if frozen resolution ever moved
    elsewhere (a _MEIPASS resource, say), shipping the sidecar beside flux.exe
    would silently stop working while every installer test stayed green.
    """
    # locate_ffmpeg uses the platform's executable name: ffmpeg.exe on
    # Windows (what the installer ships), ffmpeg elsewhere. This suite runs
    # on Ubuntu too, so name the stand-in the way the code actually probes.
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    sidecar = tmp_path / name
    sidecar.write_bytes(b"MZ")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "flux.exe"))
    monkeypatch.delenv("FLUX_FFMPEG", raising=False)

    assert ffmpeg_module.locate_ffmpeg() == sidecar


def test_release_workflow_stages_ffmpeg_before_compiling_the_installer() -> None:
    """ISCC reads dist\\ffmpeg.exe, which only exists after the staging step."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    assert "vendor\\ffmpeg.exe" in text, "release.yml never copies the sidecar"
    assert "dist\\ffmpeg.exe" in text, "release.yml never stages it into dist"
    assert text.index("vendor\\ffmpeg.exe") < text.index("installer\\flux.iss"), (
        "the sidecar is staged after ISCC runs"
    )


def test_test_workflow_stages_a_placeholder_sidecar_for_iscc() -> None:
    """The PR installer check needs a placeholder for every Source row."""
    text = TEST_WORKFLOW.read_text(encoding="utf-8")
    assert "dist\\ffmpeg.exe" in text, (
        "test.yml's ISCC check would fail on the sidecar [Files] row"
    )


def test_release_workflow_fetches_a_verified_ffmpeg() -> None:
    """A clean checkout has no gitignored sidecar; CI must fetch and verify it."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    readme = (REPO_ROOT / "vendor" / "README.md").read_text(encoding="utf-8")
    archive_digest = re.search(r"SHA-256 \| `([0-9a-f]+)`", readme)
    assert archive_digest, "vendor/README.md no longer pins the archive digest"

    assert "ffmpeg-9.0.2-essentials_build.zip" in text, "no pinned archive to fetch"
    assert archive_digest.group(1) in text, (
        "release.yml does not verify the archive against vendor/README.md"
    )
    assert "Get-FileHash" in text, "the download is not digest-checked"
    assert "vendor\\ffmpeg.exe" in text, "the verified binary is not staged"


def test_release_workflow_enforces_the_installer_size_cap() -> None:
    """The PRD's '<100 MB installer' criterion is decimal MB, not MiB."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "100 * 1000 * 1000" in text, "no 100 MB cap in the release workflow"
    assert "100 * 1024 * 1024" not in text, "the size gate still uses MiB"


def test_release_workflow_publishes_the_optional_portable_sidecar() -> None:
    """A portable flux.exe has no ffmpeg beside it unless the asset is shipped."""
    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "dist/ffmpeg.exe" in text, (
        "portable downloads would stay image-only with no companion asset"
    )
    assert "vendor/LICENSE-ffmpeg.txt" in text, (
        "the GPLv3 sidecar is published without its licence text"
    )


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


def _heif_available() -> bool:
    """Whether pillow-heif can be imported and registered."""
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _heif_available(),
    reason="pillow-heif is not installed; HEIF support is unavailable on this build",
)
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
