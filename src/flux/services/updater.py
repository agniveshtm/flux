"""GitHub-releases based update checking and downloading.

Deliberately stdlib-only (urllib): the project keeps runtime dependencies to
Pillow + pywebview, and an occasional update check does not justify a
networking client of its own.

The release pipeline (.github/workflows/release.yml) publishes three Windows
files per tag:

    flux.exe                         portable one-file build (PyInstaller)
    flux-setup-<ver>.exe             Inno Setup installer
    flux-setup-<ver>.exe.sha256      SHA-256 of the installer

The updater downloads the *installer* because that is the only artifact that
can replace an existing installation (see FluxAPI.installUpdate). It refuses to
hand over a file it cannot verify: the digest is fetched from the release and
the streamed bytes must match it, or the file is discarded.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Repository hosting the releases; keep in sync with the git remote.
REPO_SLUG = "agniveshtm/flux"
RELEASES_API = f"https://api.github.com/repos/{REPO_SLUG}/releases/latest"
USER_AGENT = "flux-updater"

# Downloads land in the OS temp dir rather than next to the executable: a
# per-user install directory is writable, but a Program Files install (or a
# portable exe on read-only media) is not.
DOWNLOAD_DIR_NAME = "flux-update"

_CHUNK_SIZE = 64 * 1024
# A published checksum file is a single short line; the cap keeps a hostile or
# mis-configured response from being read into memory.
_MAX_CHECKSUM_BYTES = 4096
_REQUEST_TIMEOUT = 15  # seconds, applied per socket operation

ProgressCallback = Callable[[int, int], None]


class UpdateError(RuntimeError):
    """An update failure carrying a stable frontend-facing error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_version(version: str) -> tuple[int, ...]:
    """Numeric core of a version string: 'v1.2.3-rc.1' -> (1, 2, 3).

    Anything without a leading number parses to an empty tuple, which never
    compares as newer - a tag we cannot understand must never be pushed at a
    user as an upgrade.
    """
    match = re.match(r"v?(\d+(?:\.\d+)*)", (version or "").strip(), re.IGNORECASE)
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    """True only when `latest` strictly supersedes `current`.

    Missing segments are zero-padded so "0.1" and "0.1.0" compare equal, and
    comparison only over the numeric core keeps a pre-release of the same
    release (0.2.0-rc1 vs 0.2.0) from counting as an upgrade.
    """
    latest_parts = parse_version(latest)
    current_parts = parse_version(current)
    if not latest_parts or not current_parts:
        return False

    width = max(len(latest_parts), len(current_parts))
    latest_parts += (0,) * (width - len(latest_parts))
    current_parts += (0,) * (width - len(current_parts))
    return latest_parts > current_parts


def pick_setup_asset(assets: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The Windows installer asset of a release, if the release has one.

    A release carries both the portable `flux.exe` and the
    `flux-setup-<ver>.exe` installer, so a naive "first .exe" rule would
    download the portable build and then fail when asked to run it as an
    updater. Only setup/installer-named executables qualify; when none
    exists the download fails with an explicit NO_ASSET error rather than
    silently installing the wrong artifact.
    """
    if not isinstance(assets, list):
        return None
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").lower()
        if name.endswith(".exe") and ("setup" in name or "installer" in name):
            return asset
    return None


# Hosts a download may come from. The URL is taken from the release JSON, so it
# is untrusted input: only GitHub's own hosts are accepted, which keeps a
# manipulated `browser_download_url` - or a redirect it triggers - from
# pointing the downloader at an arbitrary server. GitHub serves assets from
# github.com and redirects to (release-)assets.githubusercontent.com.
_TRUSTED_DOWNLOAD_HOSTS = ("github.com", "githubusercontent.com")


def is_trusted_download_url(url: str) -> bool:
    """True when `url` is https and hosted by GitHub itself."""
    parsed = urllib.parse.urlparse(url or "")
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return any(host == name or host.endswith(f".{name}") for name in _TRUSTED_DOWNLOAD_HOSTS)


# Characters allowed in the on-disk name of a downloaded asset. Everything
# else - path separators, drive colons, quotes - is replaced.
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def safe_download_name(asset_name: str, version: str) -> str:
    """Single-component filename to store a release asset under.

    `asset_name` comes from the release JSON, i.e. from whoever published the
    release, so it is never used as a path: separators, drive letters and
    traversal (../../Startup/installer.exe) do not survive, and a name that
    leaves nothing usable falls back to the canonical installer name. Only
    characters valid in a Windows filename are kept, which also keeps the
    result a plain name on POSIX, where a backslash is an ordinary character.
    """
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", asset_name or "").strip(".")
    if not cleaned:
        return f"flux-setup-{version}.exe"
    return cleaned


# Every release ships the installer's SHA-256 as a sibling asset with this
# suffix, and the updater refuses an installer whose digest it cannot check.
CHECKSUM_SUFFIX = ".sha256"


def pick_checksum_asset(
    assets: list[dict[str, Any]] | None, installer_name: str
) -> dict[str, Any] | None:
    """The `<installer>.sha256` asset published next to `installer_name`."""
    if not installer_name or not isinstance(assets, list):
        return None
    wanted = f"{installer_name}{CHECKSUM_SUFFIX}".lower()
    for asset in assets:
        if isinstance(asset, dict) and str(asset.get("name") or "").lower() == wanted:
            return asset
    return None


def parse_checksum(text: str, filename: str) -> str:
    """Lower-case SHA-256 digest for `filename` found in a checksum file.

    Understands `sha256sum`-style lines ("<64 hex>  <name>", the format the
    release pipeline writes, with or without the binary-mode `*` marker) and a
    bare 64-character digest. Returns "" when no digest for `filename` is
    present, which callers treat as "cannot verify" rather than "verified".
    """
    named = filename.strip().lower()
    for raw_line in text.splitlines():
        fields = raw_line.strip().split(None, 1)
        if not fields:
            continue
        digest = fields[0].lstrip("*").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            continue
        if len(fields) == 1:
            return digest
        listed = fields[1].strip().lstrip("*").strip().replace("\\", "/")
        if listed.lower() == named or listed.rsplit("/", 1)[-1].lower() == named:
            return digest
    return ""


def sha256_file(path: Path) -> str:
    """SHA-256 of `path`, read in chunks so a large installer stays off-heap."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class UpdateInfo:
    """Everything the frontend needs to present (and act on) a release."""

    available: bool
    current_version: str
    latest_version: str
    notes: str
    published_at: str
    asset_name: str
    asset_url: str
    # URL of the installer's published SHA-256 (a sibling release asset). Empty
    # when the release carries none, which the download path treats as
    # unverifiable - and therefore uninstallable.
    asset_sha256_url: str = ""
    # Size of the installer asset in bytes (GitHub's `size` field); 0 when
    # unknown. The update card shows it before the download and uses it as
    # the progress total until Content-Length arrives.
    asset_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "currentVersion": self.current_version,
            "latestVersion": self.latest_version,
            "notes": self.notes,
            "publishedAt": self.published_at,
            "assetName": self.asset_name,
            "assetSize": self.asset_size,
        }


class Updater:
    """Update operations bound to one running version of the app."""

    def __init__(self, current_version: str, api_url: str = RELEASES_API) -> None:
        self.current_version = current_version
        self.api_url = api_url

    def _request(self, url: str) -> urllib.request.Request:
        return urllib.request.Request(
            url,
            headers={
                "User-Agent": f"{USER_AGENT}/{self.current_version}",
                "Accept": "application/vnd.github+json",
            },
        )

    def check(self) -> UpdateInfo:
        """Fetch the latest published release and compare it to this build.

        Raises UpdateError on any network/parse failure; callers surface the
        code to the frontend, which treats a failed check as "no news" rather
        than an error dialog - a check that cannot reach GitHub must never
        interrupt the app.
        """
        try:
            with urllib.request.urlopen(
                self._request(self.api_url), timeout=_REQUEST_TIMEOUT
            ) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise UpdateError("NO_RELEASES", "No published release was found.") from exc
            raise UpdateError("NETWORK_ERROR", f"Update check failed (HTTP {exc.code}).") from exc
        except urllib.error.URLError as exc:
            raise UpdateError(
                "NETWORK_ERROR", "Could not reach GitHub to check for updates."
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise UpdateError("NETWORK_ERROR", "The update check timed out.") from exc
        except ValueError as exc:  # json.JSONDecodeError / undecodable body
            raise UpdateError("BAD_RESPONSE", "GitHub returned an unreadable response.") from exc

        if not isinstance(payload, dict):
            raise UpdateError("BAD_RESPONSE", "GitHub returned an unexpected response.")

        tag = str(payload.get("tag_name") or "")
        latest = tag[1:] if tag[:1].lower() == "v" else tag
        asset = pick_setup_asset(payload.get("assets"))
        checksum_asset = pick_checksum_asset(
            payload.get("assets"), str(asset.get("name") or "") if asset else ""
        )

        # /releases/latest already excludes drafts and prereleases, but the
        # guard keeps a mis-routed payload from offering a non-final build.
        eligible = bool(latest) and not payload.get("draft") and not payload.get("prerelease")
        asset_size = 0
        if asset is not None:
            try:
                asset_size = max(0, int(asset.get("size") or 0))
            except (TypeError, ValueError):
                asset_size = 0
        return UpdateInfo(
            available=eligible and is_newer(latest, self.current_version),
            current_version=self.current_version,
            latest_version=latest or self.current_version,
            notes=str(payload.get("body") or ""),
            published_at=str(payload.get("published_at") or ""),
            asset_name=str(asset.get("name") or "") if asset else "",
            asset_url=str(asset.get("browser_download_url") or "") if asset else "",
            asset_sha256_url=(
                str(checksum_asset.get("browser_download_url") or "") if checksum_asset else ""
            ),
            asset_size=asset_size,
        )

    def _fetch_checksum(self, url: str, filename: str) -> str:
        """Download and parse the digest the release publishes for `filename`.

        The digest is a separate fetch from the installer body (and, for
        release assets, a separate host), so bytes substituted in transit do
        not also get to adjust the value they are checked against.
        """
        try:
            with urllib.request.urlopen(
                self._request(url), timeout=_REQUEST_TIMEOUT
            ) as response:
                if not is_trusted_download_url(response.geturl()):
                    raise UpdateError(
                        "BAD_RESPONSE", "The update checksum came from an untrusted URL."
                    )
                body = response.read(_MAX_CHECKSUM_BYTES).decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise UpdateError(
                "BAD_RESPONSE",
                f"The update checksum could not be fetched (HTTP {exc.code}).",
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise UpdateError(
                "NETWORK_ERROR", "The update checksum could not be fetched."
            ) from exc

        digest = parse_checksum(body, filename)
        if not digest:
            raise UpdateError("BAD_RESPONSE", "The release checksum is unreadable.")
        return digest

    def download(self, info: UpdateInfo, progress_cb: ProgressCallback | None = None) -> Path:
        """Stream the release installer to the temp dir and return its path.

        The file is written as `<name>.part` and renamed only when complete,
        so a half-finished download can never be mistaken for an installable
        update. progress_cb receives (received_bytes, total_bytes) with
        total=0 when the server did not send a Content-Length.

        Three payload-supplied values are validated before the body is read:
        the installer URL and the checksum URL (is_trusted_download_url - where
        bytes may come from) and the asset name (safe_download_name - where
        they may be written). The streamed bytes must then match the published
        digest, so an unverifiable or substituted installer is never returned.
        """
        if not info.asset_url:
            raise UpdateError(
                "NO_ASSET",
                f"Release {info.latest_version} has no Windows installer to download.",
            )

        # Checked before any connection is made; the code matches the other
        # "the release payload is not what we expect" cases.
        if not is_trusted_download_url(info.asset_url):
            raise UpdateError(
                "BAD_RESPONSE",
                "Refusing to download an update from an untrusted URL.",
            )

        # A release that publishes no digest is not installable: refusing is the
        # point, since an unverifiable installer is exactly what this guards
        # against. Both checks run before the multi-megabyte download starts.
        if not info.asset_sha256_url:
            raise UpdateError(
                "NO_CHECKSUM",
                f"Release {info.latest_version} publishes no checksum for its installer.",
            )
        if not is_trusted_download_url(info.asset_sha256_url):
            raise UpdateError(
                "BAD_RESPONSE",
                "Refusing to fetch an update checksum from an untrusted URL.",
            )

        # The temp dir is writable for both an installed and a portable copy
        # of the app, unlike the directory the executable happens to live in.
        target_dir = Path(tempfile.gettempdir()) / DOWNLOAD_DIR_NAME
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise UpdateError("WRITE_ERROR", "Could not create the download folder.") from exc

        filename = safe_download_name(info.asset_name, info.latest_version)
        target = target_dir / filename
        partial = target.with_name(filename + ".part")

        # Fetched before the installer, so the value the bytes are compared
        # against cannot be influenced by whatever delivers those bytes.
        expected_sha256 = self._fetch_checksum(info.asset_sha256_url, filename)

        received = 0
        total = 0
        try:
            with urllib.request.urlopen(
                self._request(info.asset_url), timeout=_REQUEST_TIMEOUT
            ) as response:
                # urlopen follows redirects, so the body must still come from a
                # GitHub host - otherwise a redirect could deliver an arbitrary
                # payload from a third-party server.
                if not is_trusted_download_url(response.geturl()):
                    raise UpdateError(
                        "BAD_RESPONSE",
                        "The update download was redirected to an untrusted URL.",
                    )
                try:
                    total = int(response.headers.get("Content-Length") or 0)
                except ValueError:
                    total = 0
                with partial.open("wb") as handle:
                    while True:
                        chunk = response.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        handle.write(chunk)
                        received += len(chunk)
                        if progress_cb is not None:
                            progress_cb(received, total)
        except urllib.error.HTTPError as exc:
            partial.unlink(missing_ok=True)
            if exc.code == 404:
                raise UpdateError("NO_ASSET", "The update file is no longer available.") from exc
            raise UpdateError("NETWORK_ERROR", f"The download failed (HTTP {exc.code}).") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            partial.unlink(missing_ok=True)
            raise UpdateError("NETWORK_ERROR", "The update download failed.") from exc

        # A Content-Length mismatch means a truncated body the socket layer
        # did not flag; never hand a partial file to the installer.
        if total and received != total:
            partial.unlink(missing_ok=True)
            raise UpdateError("BAD_RESPONSE", "The download ended early - please try again.")

        # Integrity: the file that reaches the installer is the one whose bytes
        # match the published digest. A mismatch means the payload was not the
        # artifact the release published, so it is deleted, not repaired.
        if sha256_file(partial) != expected_sha256:
            partial.unlink(missing_ok=True)
            raise UpdateError(
                "CHECKSUM_MISMATCH",
                "The downloaded update failed its integrity check and was discarded.",
            )

        try:
            partial.replace(target)
        except OSError as exc:
            partial.unlink(missing_ok=True)
            raise UpdateError("WRITE_ERROR", "Could not save the downloaded update.") from exc

        return target