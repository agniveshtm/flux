"""Unit tests for the update primitives that need no network access."""

from __future__ import annotations

from flux.services.updater import UpdateInfo, is_newer, parse_version, pick_setup_asset


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
