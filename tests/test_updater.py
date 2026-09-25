"""Unit tests for the update primitives that need no network access."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from flux.services import updater
from flux.services.updater import (
    CHECKSUM_SUFFIX,
    DOWNLOAD_DIR_NAME,
    UpdateError,
    UpdateInfo,
    Updater,
    is_newer,
    is_trusted_download_url,
    parse_checksum,
    parse_version,
    pick_checksum_asset,
    pick_setup_asset,
    safe_download_name,
    sha256_file,
)

# sha256("abc"), also used to pin sha256_file() to a known value.
_DIGEST_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def _asset(name: str) -> dict:
    return {"name": name, "browser_download_url": f"https://example.invalid/{name}"}


class TestParseVersion:
    def test_strips_v_prefix_and_suffixes(self) -> None:
        assert parse_version("v1.2.3") == (1, 2, 3)
        assert parse_version("0.1.0-rc.1") == (0, 1, 0)

    def test_unparsable_versions_are_empty(self) -> None:
        assert parse_version("nightly") == ()
        assert parse_version("") == ()
        assert parse_version("v") == ()


class TestIsNewer:
    def test_basic_ordering(self) -> None:
        assert is_newer("0.2.0", "0.1.0")
        assert not is_newer("0.1.0", "0.1.0")
        assert not is_newer("0.0.9", "0.1.0")

    def test_accepts_v_prefix_on_latest(self) -> None:
        assert is_newer("v0.2.0", "0.1.0")

    def test_missing_segments_are_zero_padded(self) -> None:
        assert not is_newer("0.1", "0.1.0")
        assert not is_newer("0.1.0", "0.1")
        assert is_newer("0.1.1", "0.1")

    def test_same_core_is_not_an_upgrade(self) -> None:
        assert not is_newer("0.2.0-rc1", "0.2.0")

    def test_unparsable_either_side_never_offers_update(self) -> None:
        assert not is_newer("", "0.1.0")
        assert not is_newer("0.2.0", "nightly")


class TestPickSetupAsset:
    def test_prefers_installer_over_portable_exe(self) -> None:
        # A release carries flux.exe AND flux-setup-<ver>.exe; picking the
        # portable exe would make the updater try to "install" itself.
        assets = [_asset("flux.exe"), _asset("flux-setup-0.2.0.exe")]
        picked = pick_setup_asset(assets)
        assert picked is not None
        assert picked["name"] == "flux-setup-0.2.0.exe"

    def test_never_picks_the_portable_exe_alone(self) -> None:
        assert pick_setup_asset([_asset("flux.exe")]) is None

    def test_tolerates_renamed_installer(self) -> None:
        picked = pick_setup_asset([_asset("Flux-Installer-x64.exe")])
        assert picked is not None
        assert picked["name"] == "Flux-Installer-x64.exe"

    def test_ignores_non_executable_assets(self) -> None:
        assert pick_setup_asset([_asset("flux-setup-0.2.0.zip")]) is None

    def test_tolerates_missing_or_junk_input(self) -> None:
        assert pick_setup_asset([]) is None
        assert pick_setup_asset(None) is None
        assert pick_setup_asset("not-a-list") is None  # type: ignore[arg-type]


class TestUpdateInfo:
    def test_to_dict_uses_frontend_casing(self) -> None:
        info = UpdateInfo(
            available=True,
            current_version="0.1.0",
            latest_version="0.2.0",
            notes="notes",
            published_at="2026-01-01T00:00:00Z",
            asset_name="flux-setup-0.2.0.exe",
            asset_url="https://example.invalid/flux-setup-0.2.0.exe",
            asset_size=25_800_000,
        )
        payload = info.to_dict()
        assert payload["available"] is True
        assert payload["currentVersion"] == "0.1.0"
        assert payload["latestVersion"] == "0.2.0"
        assert payload["assetName"] == "flux-setup-0.2.0.exe"
        # Byte size feeds the card's "24.6 MB" label and the progress total.
        assert payload["assetSize"] == 25_800_000
        # The download URL stays backend-only; the frontend never fetches it.
        assert "assetUrl" not in payload


def test_asset_size_defaults_to_unknown() -> None:
    info = UpdateInfo(
        available=True,
        current_version="0.1.0",
        latest_version="0.2.0",
        notes="",
        published_at="",
        asset_name="",
        asset_url="",
    )
    assert info.asset_size == 0
    assert info.to_dict()["assetSize"] == 0


class TestSafeDownloadName:
    def test_keeps_a_canonical_installer_name(self) -> None:
        assert safe_download_name("flux-setup-0.2.0.exe", "0.2.0") == "flux-setup-0.2.0.exe"

    def test_strips_traversal_separators_and_drive_letters(self) -> None:
        # The name comes from the release JSON: joined to the download dir it
        # must always stay a single component inside that dir, on either OS.
        download_dir = Path("C:/Temp/flux-update")
        for hostile in (
            "../../Startup/installer.exe",
            "..\\..\\Startup\\installer.exe",
            "/etc/cron.d/installer.exe",
            "C:\\Windows\\Temp\\installer.exe",
            "nested/flux-setup-0.2.0.exe",
        ):
            name = safe_download_name(hostile, "0.2.0")
            assert "/" not in name and "\\" not in name
            assert name not in (".", "..")
            assert (download_dir / name).parent == download_dir

    def test_falls_back_when_nothing_usable_remains(self) -> None:
        assert safe_download_name("", "0.2.0") == "flux-setup-0.2.0.exe"
        assert safe_download_name("...", "0.2.0") == "flux-setup-0.2.0.exe"


class TestIsTrustedDownloadUrl:
    def test_accepts_github_release_and_asset_hosts(self) -> None:
        assert is_trusted_download_url(
            "https://github.com/agniveshtm/flux/releases/download/v0.2.0/flux-setup-0.2.0.exe"
        )
        assert is_trusted_download_url("https://objects.githubusercontent.com/x/flux.exe")
        assert is_trusted_download_url("https://release-assets.githubusercontent.com/x/y.exe")

    def test_rejects_other_schemes_hosts_and_lookalikes(self) -> None:
        assert not is_trusted_download_url("http://github.com/o/r/releases/download/v1/y.exe")
        assert not is_trusted_download_url("https://evil.example/flux-setup-0.2.0.exe")
        assert not is_trusted_download_url("https://github.com.evil.example/y.exe")
        assert not is_trusted_download_url("https://evilgithub.com/y.exe")
        assert not is_trusted_download_url("file:///C:/Temp/flux-update/y.exe")
        assert not is_trusted_download_url("")


class TestPickChecksumAsset:
    def test_matches_the_installer_it_belongs_to(self) -> None:
        assets = [_asset("flux-setup-0.2.0.exe"), _asset("flux-setup-0.2.0.exe.sha256")]
        picked = pick_checksum_asset(assets, "flux-setup-0.2.0.exe")
        assert picked is not None
        assert picked["name"] == "flux-setup-0.2.0.exe.sha256"

    def test_ignores_other_releases_and_junk(self) -> None:
        assets = [_asset("flux-setup-0.1.0.exe.sha256"), _asset("flux-setup-0.2.0.exe")]
        assert pick_checksum_asset(assets, "flux-setup-0.2.0.exe") is None
        assert pick_checksum_asset(assets, "") is None
        assert pick_checksum_asset(None, "flux-setup-0.2.0.exe") is None
        assert pick_checksum_asset("not-a-list", "flux-setup-0.2.0.exe") is None  # type: ignore[arg-type]


class TestParseChecksum:
    def test_reads_sha256sum_output(self) -> None:
        text = f"{_DIGEST_ABC}  flux-setup-0.2.0.exe\n"
        assert parse_checksum(text, "flux-setup-0.2.0.exe") == _DIGEST_ABC

    def test_reads_binary_marker_uppercase_and_paths(self) -> None:
        # `sha256sum -b` writes "<digest> *<name>", and the pipeline's
        # Get-FileHash digest is upper-case before .ToLower().
        text = f"{_DIGEST_ABC.upper()} *dist/flux-setup-0.2.0.exe\n"
        assert parse_checksum(text, "flux-setup-0.2.0.exe") == _DIGEST_ABC

    def test_reads_a_bare_digest(self) -> None:
        assert parse_checksum(_DIGEST_ABC, "flux-setup-0.2.0.exe") == _DIGEST_ABC

    def test_returns_nothing_when_the_digest_is_for_another_file(self) -> None:
        assert parse_checksum(f"{_DIGEST_ABC}  other.exe\n", "flux-setup-0.2.0.exe") == ""
        assert parse_checksum(f"{_DIGEST_ABC}  flux-setup-0.2.0.exe\n", "flux-setup-0.1.0.exe") == ""

    def test_returns_nothing_for_junk(self) -> None:
        assert parse_checksum("", "flux-setup-0.2.0.exe") == ""
        assert parse_checksum("<html>404</html>", "flux-setup-0.2.0.exe") == ""
        assert parse_checksum(f"{'ab' * 31}  flux-setup-0.2.0.exe", "flux-setup-0.2.0.exe") == ""


class TestSha256File:
    def test_matches_a_known_digest(self, tmp_path: Path) -> None:
        target = tmp_path / "payload.bin"
        target.write_bytes(b"abc")
        assert sha256_file(target) == _DIGEST_ABC


class _FakeResponse:
    """Just enough of a urlopen() result for the download path."""

    def __init__(self, body: bytes, url: str) -> None:
        self._body = body
        self._url = url
        self._served = False
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        if self._served:
            return b""
        self._served = True
        return self._body


def _stub_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, bodies: dict[str, bytes]
) -> None:
    """Serve `bodies` to the updater with its download dir inside tmp_path.

    Any other URL fails the test, which is how "nothing was downloaded" is
    asserted for the payloads that must be refused up front.
    """

    def fake_urlopen(request: object, timeout: float | None = None) -> _FakeResponse:
        url = str(getattr(request, "full_url", request))
        if url not in bodies:
            raise AssertionError(f"unexpected fetch: {url}")
        return _FakeResponse(bodies[url], url)

    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)


class TestDownloadGuards:
    _ASSET_URL = "https://github.com/agniveshtm/flux/releases/download/v0.2.0/flux-setup-0.2.0.exe"

    @staticmethod
    def _info(asset_url: str, checksum_url: str = "") -> UpdateInfo:
        return UpdateInfo(
            available=True,
            current_version="0.1.0",
            latest_version="0.2.0",
            notes="",
            published_at="",
            asset_name="flux-setup-0.2.0.exe",
            asset_url=asset_url,
            asset_sha256_url=checksum_url,
        )

    def test_untrusted_url_is_refused_before_any_download(self) -> None:
        # No network call and no filesystem work happens for a URL that came out
        # of the release payload and does not point at GitHub.
        with pytest.raises(UpdateError) as excinfo:
            Updater("0.1.0").download(self._info("https://evil.example/flux-setup-0.2.0.exe"))
        assert excinfo.value.code == "BAD_RESPONSE"

    def test_missing_checksum_is_refused_before_any_download(self) -> None:
        # Fail closed: an installer nobody can verify must not be downloaded at
        # all (the stub urlopen would raise if anything were fetched here).
        with pytest.raises(UpdateError) as excinfo:
            Updater("0.1.0").download(self._info(self._ASSET_URL))
        assert excinfo.value.code == "NO_CHECKSUM"

    def test_untrusted_checksum_url_is_refused(self) -> None:
        with pytest.raises(UpdateError) as excinfo:
            Updater("0.1.0").download(
                self._info(self._ASSET_URL, "https://evil.example/flux-setup-0.2.0.exe.sha256")
            )
        assert excinfo.value.code == "BAD_RESPONSE"

    def test_download_returns_the_file_only_when_the_digest_matches(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        body = b"installer-bytes"
        checksum_url = f"{self._ASSET_URL}{CHECKSUM_SUFFIX}"
        _stub_network(
            monkeypatch,
            tmp_path,
            {
                checksum_url: f"{hashlib.sha256(body).hexdigest()}  flux-setup-0.2.0.exe\n".encode(),
                self._ASSET_URL: body,
            },
        )
        path = Updater("0.1.0").download(self._info(self._ASSET_URL, checksum_url))
        assert path == tmp_path / DOWNLOAD_DIR_NAME / "flux-setup-0.2.0.exe"
        assert path.read_bytes() == body

    def test_download_discards_a_payload_that_fails_the_digest(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        checksum_url = f"{self._ASSET_URL}{CHECKSUM_SUFFIX}"
        _stub_network(
            monkeypatch,
            tmp_path,
            {
                checksum_url: (
                    f"{hashlib.sha256(b'the real installer').hexdigest()}"
                    "  flux-setup-0.2.0.exe\n"
                ).encode(),
                self._ASSET_URL: b"substituted payload",
            },
        )
        with pytest.raises(UpdateError) as excinfo:
            Updater("0.1.0").download(self._info(self._ASSET_URL, checksum_url))
        assert excinfo.value.code == "CHECKSUM_MISMATCH"
        # Nothing is left behind for the installer to run.
        assert list((tmp_path / DOWNLOAD_DIR_NAME).iterdir()) == []

    def test_unreadable_checksum_file_stops_the_download(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        checksum_url = f"{self._ASSET_URL}{CHECKSUM_SUFFIX}"
        _stub_network(monkeypatch, tmp_path, {checksum_url: b"<html>404</html>"})
        with pytest.raises(UpdateError) as excinfo:
            Updater("0.1.0").download(self._info(self._ASSET_URL, checksum_url))
        assert excinfo.value.code == "BAD_RESPONSE"
        assert list((tmp_path / DOWNLOAD_DIR_NAME).iterdir()) == []
