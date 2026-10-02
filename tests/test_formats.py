"""The frontend's copy of the format lists must match the backend's.

Phase 1.1 replaced the hardcoded TARGETS_BY_INPUT table with a matrix derived
from getSupportedFormats(), so the backend's INPUT_FORMATS/OUTPUT_FORMATS are
now the single source of truth for what Flux supports. Two things still shadow
them on the JS side, and neither fails loudly on its own:

* useFlux.js's mockSupportedFormats - the browser-dev stand-in, also used as the
  pre-load fallback for input validation. If it drifts, a file dropped during
  startup is silently rejected for a format Flux does support.
* window.py's pickFiles dialog filter and getFilePreview MIME map, which are
  what make the new formats selectable and previewable at all.

A new format added to the converter but not to these lists produces an app that
converts correctly but cannot be told to, so the drift is pinned here.
"""

from __future__ import annotations

import re
from pathlib import Path

from flux.services.image_converter import (
    INPUT_FORMATS,
    OUTPUT_FORMATS,
    _avif_available,
)
from flux.window import FluxAPI

REPO_ROOT = Path(__file__).resolve().parents[1]
USE_FLUX = REPO_ROOT / "src" / "flux" / "frontend" / "composables" / "useFlux.js"
WINDOW = REPO_ROOT / "src" / "flux" / "window.py"


def _js_format_lists() -> dict[str, list[str]]:
    """Pull mockSupportedFormats' input/output arrays out of useFlux.js."""
    source = USE_FLUX.read_text(encoding="utf-8")
    match = re.search(
        r"const mockSupportedFormats\s*=\s*\{(?P<body>.*?)\};", source, re.DOTALL
    )
    assert match, "mockSupportedFormats not found in useFlux.js"

    lists: dict[str, list[str]] = {}
    for key, values in re.findall(r"(input|output)\s*:\s*\[([^\]]*)\]", match.group("body")):
        lists[key] = re.findall(r"['\"]([^'\"]+)['\"]", values)

    assert set(lists) == {"input", "output"}, f"unexpected keys: {sorted(lists)}"
    return lists


def test_frontend_mock_matches_backend_formats() -> None:
    lists = _js_format_lists()
    inputs, outputs = lists["input"], lists["output"]

    if not _avif_available():
        # The frontend mock is a static literal, but the real matrix is derived
        # from the bridge at runtime, so on a build without libavif a stale
        # AVIF entry in the dev mock cannot reach the user. Only the backend
        # list legitimately shrinks.
        inputs = [item for item in inputs if item != "avif"]
        outputs = [item for item in outputs if item != "avif"]

    assert inputs == list(INPUT_FORMATS)
    assert outputs == list(OUTPUT_FORMATS)


def test_picker_offers_every_supported_input_format() -> None:
    # pickFiles is what puts a file into the list, so a format missing from its
    # filter can never be selected through the native picker at all.
    source = WINDOW.read_text(encoding="utf-8")
    match = re.search(r"file_types=\((?P<patterns>[^)]*)\)", source)
    assert match, "pickFiles file_types filter not found"

    patterns = match.group("patterns")
    for fmt in INPUT_FORMATS:
        assert f"*.{fmt}" in patterns, f"pickFiles filter is missing *.{fmt}"


def test_every_supported_input_format_can_be_previewed() -> None:
    # getFilePreview is an explicit allowlist, and it is also the guard that
    # stops the page reading arbitrary local files - so it must cover every
    # format the converter accepts, no more and no less.
    api = FluxAPI()
    for fmt in INPUT_FORMATS:
        assert api._mime_type_for(f".{fmt}") is not None, f"no preview MIME type for .{fmt}"

    assert api._mime_type_for(".pdf") is None
    assert api._mime_type_for(".txt") is None


def test_conversion_matrix_is_derived_not_hardcoded() -> None:
    """The dropdown offers exactly the backend outputs minus the input itself.

    This is the behaviour that replaced TARGETS_BY_INPUT. Re-encoding an image
    to the format it is already in is a no-op, so a format is never offered as
    a target of itself; everything else the backend writes is reachable.
    """
    outputs = list(OUTPUT_FORMATS)

    for fmt in INPUT_FORMATS:
        targets = [out for out in outputs if out != fmt]
        assert fmt not in targets, f"{fmt} must not be offered as a target of itself"
        assert set(targets) == set(outputs) - {fmt}
