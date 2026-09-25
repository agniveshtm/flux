"""The bundled resources must resolve where flux.spec actually puts them.

The v0.1.0 release built fine but its window opened on WebView2's
ERR_FILE_NOT_FOUND page: the entry script resolved the frontend with
Path(__file__).parent, which inside a one-file build is the archive root
(<_MEIPASS>/main.py) rather than the package directory the data files are
bundled under (<_MEIPASS>/flux/...). _bundled_path is the single resolver;
these tests pin its source-tree branch, its frozen branch, and the
flux.spec destination the frozen branch depends on.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from flux.main import _bundled_path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_frontend_index_resolves_in_source_tree() -> None:
    assert _bundled_path("frontend", "index.html").is_file()


def test_window_icon_resolves_in_source_tree() -> None:
    assert _bundled_path("assets", "favicon.ico").is_file()


def test_frozen_build_resolves_under_meipass_flux(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # In the one-file build the entry script's __file__ sits at the archive
    # root, so resolution must be anchored at <_MEIPASS>/flux - the directory
    # flux.spec bundles the data files into - not at Path(__file__).parent.
    bundled = tmp_path / "flux" / "frontend"
    bundled.mkdir(parents=True)
    (bundled / "index.html").write_text("<html></html>", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    resolved = _bundled_path("frontend", "index.html")
    assert resolved == bundled / "index.html"
    assert resolved.is_file()


def test_spec_bundles_data_where_frozen_resolver_looks() -> None:
    # The frozen branch of _bundled_path hardcodes the "flux/" destination;
    # if flux.spec ever moves the data files, this test fails before a
    # release can ship a window that only shows ERR_FILE_NOT_FOUND again.
    spec = (REPO_ROOT / "flux.spec").read_text(encoding="utf-8")
    assert '("src/flux/frontend", "flux/frontend")' in spec
    assert '("src/flux/assets", "flux/assets")' in spec
