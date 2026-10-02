"""The in-app update must launch the installer fully unattended.

Restart Manager raises its own "close all applications" prompt when it finds
flux.exe holding the files the setup is about to replace. That prompt is not
part of the wizard, so /SILENT does not suppress it - without the close flags
the upgrade stalls on a dialog asking the user to close the very app that is
waiting for that dialog.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from flux.window import FluxAPI

# Every switch installUpdate must pass. Documented in Inno Setup's
# topic_setupcmdline help.
REQUIRED_FLAGS = {
    "/SILENT",  # no wizard/background window (progress bar stays)
    "/CLOSEAPPLICATIONS",  # let Restart Manager close the app
    "/FORCECLOSEAPPLICATIONS",  # terminate rather than ask
    "/NORESTARTAPPLICATIONS",  # the .iss [Run] section owns relaunching
    "/SUPPRESSMSGBOXES",  # only effective alongside /SILENT
    "/NORESTART",  # never raise a "Reboot now?" box
}


@pytest.fixture
def setup_exe(tmp_path: Path) -> Path:
    path = tmp_path / "flux-setup-9.9.9.exe"
    path.write_bytes(b"MZ")
    return path


@pytest.fixture
def on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let installUpdate take its Windows path from any platform.

    The updater is Windows-only, and its launch flags reference
    subprocess.DETACHED_PROCESS and CREATE_NEW_PROCESS_GROUP, which exist only
    in the Windows build of the subprocess module. CI runs this suite on Linux
    as well as Windows, so the platform guard and both constants are supplied
    here; otherwise these tests would either refuse to run off Windows or fail
    with AttributeError.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    # Win32 values: DETACHED_PROCESS and CREATE_NEW_PROCESS_GROUP.
    monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)


def _capture_install(api: FluxAPI, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    captured: list[str] = []

    def fake_popen(args, **kwargs):
        captured.append(list(args))
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(api, "_destroy_window_for_update", lambda: None)
    result = api.installUpdate()
    assert result == {"installing": True}, result
    assert captured, "the installer was never launched"
    return captured[0]


def test_install_passes_every_unattended_flag(
    setup_exe: Path, monkeypatch: pytest.MonkeyPatch, on_windows: None
) -> None:
    api = FluxAPI()
    api._downloaded_setup = setup_exe

    args = _capture_install(api, monkeypatch)

    missing = REQUIRED_FLAGS - set(args)
    assert not missing, f"installer launched without {sorted(missing)}"


def test_install_targets_the_downloaded_setup(
    setup_exe: Path, monkeypatch: pytest.MonkeyPatch, on_windows: None
) -> None:
    api = FluxAPI()
    api._downloaded_setup = setup_exe

    args = _capture_install(api, monkeypatch)

    assert args[0] == str(setup_exe)


def test_install_runs_detached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, on_windows: None
) -> None:
    # The app exits ~0.4s after launching, so the setup must not die with it.
    api = FluxAPI()
    setup = tmp_path / "flux-setup-9.9.9.exe"
    setup.write_bytes(b"MZ")
    api._downloaded_setup = setup

    seen: dict = {}

    def fake_popen(args, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(api, "_destroy_window_for_update", lambda: None)
    api.installUpdate()

    flags = seen.get("creationflags", 0)
    assert flags & subprocess.DETACHED_PROCESS
    assert flags & subprocess.CREATE_NEW_PROCESS_GROUP


def test_install_refuses_without_a_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The NOT_DOWNLOADED check runs before the platform guard, so this holds on
    # every platform without pretending to be Windows.
    api = FluxAPI()
    api._downloaded_setup = None

    result = api.installUpdate()

    assert result.get("code") == "NOT_DOWNLOADED"


def test_install_refuses_off_windows(
    setup_exe: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The mirror image: with a real setup on hand but no Windows, the updater
    # must refuse rather than hand a foreign binary to the OS.
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("launched"))
    api = FluxAPI()
    api._downloaded_setup = setup_exe

    result = api.installUpdate()

    assert result.get("code") == "UNSUPPORTED_PLATFORM"