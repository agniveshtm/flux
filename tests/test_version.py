"""The version must agree everywhere it is recorded.

pyproject.toml drives packaging, flux.__version__ drives the runtime (and
the update checker), and the release tag drives the GitHub release - the
workflow verifies the tag separately, this test keeps the two source files
from drifting between releases.
"""

from __future__ import annotations

import re
from pathlib import Path

import flux

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _pyproject_version() -> str:
    match = re.search(
        r'^version = "([^"]+)"',
        PYPROJECT.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, "pyproject.toml does not declare a project version"
    return match.group(1)


def test_package_version_matches_pyproject() -> None:
    assert flux.__version__ == _pyproject_version()


def test_version_is_a_release_style_number() -> None:
    # The updater only offers releases whose numeric core is newer than the
    # running build, so the shipped version must parse as one.
    from flux.services.updater import parse_version

    assert parse_version(flux.__version__), f"unparsable version: {flux.__version__}"
