"""The in-app update must launch the installer fully unattended.

Restart Manager raises its own "close all applications" prompt when it finds
flux.exe holding the files the setup is about to replace. That prompt is not
part of the wizard, so /SILENT does not suppress it - without the close flags
the upgrade stalls on a dialog asking the user to close the very app that is
waiting for that dialog.
"""

from __future__ import annotations

import subprocess
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
    setup_exe: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FluxAPI()
    api._downloaded_setup = setup_exe

    args = _capture_install(api, monkeypatch)

    missing = REQUIRED_FLAGS - set(args)
    assert not missing, f"installer launched without {sorted(missing)}"


def test_install_targets_the_downloaded_setup(
    setup_exe: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FluxAPI()
    api._downloaded_setup = setup_exe

    args = _capture_install(api, monkeypatch)

    assert args[0] == str(setup_exe)


def test_install_runs_detached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr("sys.platform", "win32")
    api = FluxAPI()
    api._downloaded_setup = None

    result = api.installUpdate()

    assert result.get("code") == "NOT_DOWNLOADED"