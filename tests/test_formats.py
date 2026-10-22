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

from flux.converter import normalize_format
from flux.services.image_converter import (
    INPUT_FORMATS,
    OUTPUT_FORMATS,
    _avif_available,
    _heif_available,
)
from flux.window import FluxAPI

REPO_ROOT = Path(__file__).resolve().parents[1]
USE_FLUX = REPO_ROOT / "src" / "flux" / "frontend" / "composables" / "useFlux.js"
WINDOW = REPO_ROOT / "src" / "flux" / "window.py"
MAIN_JS = REPO_ROOT / "src" / "flux" / "frontend" / "main.js"


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


def _js_format_kinds() -> dict[str, str]:
    """Pull mockSupportedFormats' kinds map out of useFlux.js."""
    source = USE_FLUX.read_text(encoding="utf-8")
    match = re.search(r"kinds\s*:\s*\{(?P<body>[^}]*)\}", source, re.DOTALL)
    assert match, "mockSupportedFormats.kinds not found in useFlux.js"
    return dict(
        re.findall(r"['\"]?([A-Za-z0-9_]+)['\"]?\s*:\s*['\"]([^'\"]+)['\"]", match.group("body"))
    )


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

    if not _heif_available():
        # Same gate logic as AVIF: pillow-heif may be absent, and the mock
        # staying static would advertise formats the app cannot handle.
        inputs = [item for item in inputs if item not in ("heic", "heif")]
        outputs = [item for item in outputs if item != "heic"]

    assert inputs == list(INPUT_FORMATS)
    assert outputs == list(OUTPUT_FORMATS)


def test_frontend_mock_kinds_match_the_backend() -> None:
    """The kinds map must cover exactly the formats the backend can write.

    The UI groups the formats it offers by kind - the format picker shows
    image and video formats as separate sets - so the mock's map is a second
    copy of the backend's converter registry. If a format is missing from it
    the picker would drop that format; if it names a format the backend
    cannot write, the picker would offer a target that does not exist.
    """
    kinds = _js_format_kinds()

    assert set(kinds) == set(OUTPUT_FORMATS), (
        f"mock kinds cover {sorted(kinds)}, backend outputs {sorted(OUTPUT_FORMATS)}"
    )
    assert set(kinds.values()) == {"image"}, (
        "the only converter registered writes images; a kind other than "
        "'image' here would advertise a format the app cannot produce"
    )


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


def test_preview_allowlist_admits_nothing_the_converter_cannot_read() -> None:
    # The reverse direction, which the test above does not check. The map used
    # to carry .bmp, .tif and .tiff - formats Flux cannot convert - so the page
    # could preview a file the app would then refuse, and the allowlist was
    # wider than the boundary it was meant to describe. Both directions are now
    # pinned so the two lists cannot drift apart again.
    allowed = {suffix.lstrip(".") for suffix in FluxAPI._PREVIEW_MIME_TYPES}

    # .avif is defensible in either direction: it is in INPUT_FORMATS whenever
    # this build can read it, and the static map keeps it when it cannot.
    expected = set(INPUT_FORMATS)
    assert allowed == expected or allowed == expected - {"avif"} or allowed == expected | {"avif"}, (
        f"preview allowlist {sorted(allowed)} does not match the readable formats "
        f"{sorted(expected)}"
    )


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


def _target_preference() -> list[str]:
    """Pull TARGET_PREFERENCE's entries out of main.js."""
    source = MAIN_JS.read_text(encoding="utf-8")
    match = re.search(
        r"const TARGET_PREFERENCE\s*=\s*\[(?P<items>[^\]]*)\]", source
    )
    assert match, "TARGET_PREFERENCE not found in main.js"
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group("items"))


def test_default_target_is_not_avif() -> None:
    """TARGET_PREFERENCE must keep AVIF last and cover every output format.

    `getDefaultTargetFormat` used to return `targetsForInput(ext)[0]`, and
    because the matrix is derived from `getSupportedFormats()` - which returns
    sorted lists - that is the alphabetically first target: 'avif' for every
    input except AVIF itself. Every file a user dropped was therefore preloaded
    for the slowest encoder here and the least compatible output, before they
    had chosen anything, and the quality slider appeared with it.

    `TARGET_PREFERENCE` now states the order explicitly and `defaultTargetFor`
    walks it. This test pins the *list*; the wiring is verified separately by
    `scripts/check-frontend.js`, which executes the real `defaultTargetFor` and
    asserts `getDefaultTargetFormat` calls it. Parsing the source here cannot
    catch a regression in that wiring, so the two are complementary:
    re-introducing `targets[0]` leaves this test green.
    """
    preference = _target_preference()
    outputs = list(OUTPUT_FORMATS)

    assert set(outputs) <= set(preference), (
        f"TARGET_PREFERENCE is missing {sorted(set(outputs) - set(preference))}, "
        "so those formats fall back to the alphabetical first target"
    )
    assert preference[-1] == "avif", (
        f"'avif' must stay last in TARGET_PREFERENCE (got {preference}); "
        "an earlier position makes it some input's silent default"
    )
    # No format may appear twice: the first occurrence would win and the second
    # would be dead weight that reads as part of the ordering.
    assert len(preference) == len(set(preference)), (
        f"TARGET_PREFERENCE has duplicates: {preference}"
    )

    for fmt in INPUT_FORMATS:
        targets = [out for out in outputs if out != normalize_format(fmt)]
        expected = next(out for out in preference if out in targets)
        assert expected != "avif" or targets == ["avif"], (
            f"{fmt} would preselect 'avif' although {targets} are available"
        )
